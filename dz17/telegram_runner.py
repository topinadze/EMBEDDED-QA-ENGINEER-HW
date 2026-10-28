"""Start allow-listed DZ17 test packs from the configured private Telegram chat.

Run on the bench PC from the dz17 folder:

    .\\.venv\\Scripts\\python.exe telegram_runner.py --port COM4

Only one pack runs at a time. While pytest runs, this process stops polling the
bot so the test session's own Telegram prompts are the only getUpdates consumer.
Chat input only selects entries from the fixed pack table below; it is never
passed to the command line.
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from utils.telegram_helper import STOP_RUN_COMMAND, TelegramInteraction

LOGGER = logging.getLogger("telegram_runner")

DZ17_DIR = Path(__file__).resolve().parent
FIRMWARE_VERSIONS = ("2.1.0", "2.3.0")
# Marker packs never include these: OTA and AU-1 registration have their own
# packs below; full alert-history cleanup and >4 m sonar checks stay console-only.
ALWAYS_EXCLUDED = (
    "not ota and not auth_registration and not alert_cleanup and not long_range"
)
OTA_TRANSITION_TESTS = {
    ("2.1.0", "2.3.0"): "test_available_update_completes_self_check",
    ("2.3.0", "2.1.0"): "test_forced_downgrade_completes_self_check",
}
OTA_CHECKS_FILTER = " and ".join(f"not {name}" for name in OTA_TRANSITION_TESTS.values())
REGISTRATION_MARKERS = "auth_registration and auth and interactive and persistent"
DETECT_ATTEMPTS = 5
DETECT_RETRY_SECONDS = 3
POLL_SECONDS = 30
API_ERROR_PAUSE_SECONDS = 15
COMMANDS = (
    ("run", "Choose and start a DZ17 test pack"),
    ("stop_execution", "Stop the running test pack (like Ctrl+C)"),
    ("status", "Show runner status"),
    ("help", "How the runner works"),
)


@dataclass(frozen=True)
class Mode:
    label: str
    markers: str | None
    persistent: bool = False


@dataclass(frozen=True)
class Pack:
    label: str
    marker: str | None
    log_category: str
    modes: tuple[str, ...]
    # "ota" and "registration" packs have their own plans instead of a marker filter.
    special: str | None = None


MODES = {
    "auto": Mode("🤖 Automated", "not interactive and not persistent"),
    "manual": Mode("🙋 Interactive", "interactive and not persistent"),
    "persistent": Mode("⚠️ Persistent", "persistent", persistent=True),
    # Same scope as the launchers' -All: interactive and persistent cases included.
    "all": Mode("🧩 All", None, persistent=True),
    "chain": Mode("🔁 Full chain", None, persistent=True),
    "checks": Mode("🧪 Checks only", None, persistent=True),
    "erase": Mode("⚠️ Erase NVS + register", None, persistent=True),
}

PACKS = {
    "buttons": Pack(
        "🔘 Buttons", "buttons", "buttons", ("manual", "persistent", "all")
    ),
    "lamp": Pack("💡 Lamp", "lamp", "lamp", ("manual", "persistent", "all")),
    "wifi": Pack(
        "📶 Wi-Fi", "wifi", "wifi", ("auto", "manual", "persistent", "all")
    ),
    "distance": Pack(
        "📏 Distance", "distance", "distance", ("auto", "manual", "persistent", "all")
    ),
    "guard": Pack("🚨 Guard", "guard", "guard", ("auto", "persistent", "all")),
    "alert": Pack("🔔 Alert", "alert", "alert", ("auto", "persistent", "all")),
    "auth": Pack("🔐 Auth", "auth", "auth", ("auto", "manual", "persistent", "all")),
    # Every relay test is persistent, so Persistent already is the whole pack.
    "relay": Pack("🔌 Relay", "relay", "relay", ("persistent",)),
    "ota": Pack("🔄 OTA", "ota", "ota", ("chain", "checks"), special="ota"),
    "registration": Pack(
        "🆕 Registration (AU-1)",
        "auth_registration",
        "auth-registration",
        ("erase",),
        special="registration",
    ),
    "all": Pack("🧪 All packs", None, "all", ("auto", "all")),
}


@dataclass(frozen=True)
class OtaStage:
    label: str
    firmware: str
    test_filter: str
    expected_after: str


def ota_stages(mode: str, start: str) -> list[OtaStage]:
    """Stages of the OTA pack, mirroring run-ota-chain.ps1."""
    stages = [OtaStage(f"checks-{start}", start, OTA_CHECKS_FILTER, start)]
    if mode == "chain":
        other = next(version for version in FIRMWARE_VERSIONS if version != start)
        stages += [
            OtaStage(f"{start}-to-{other}", start, OTA_TRANSITION_TESTS[(start, other)], other),
            OtaStage(f"checks-{other}", other, OTA_CHECKS_FILTER, other),
            OtaStage(f"{other}-to-{start}", other, OTA_TRANSITION_TESTS[(other, start)], start),
        ]
    return stages


@dataclass(frozen=True)
class RunRequest:
    pack: str
    mode: str
    firmware: str


@dataclass(frozen=True)
class RunPlan:
    argv: list[str]
    log_path: Path
    junit_path: Path


def marker_expression(request: RunRequest) -> str:
    mode_markers = MODES[request.mode].markers
    parts = [
        PACKS[request.pack].marker,
        f"({mode_markers})" if mode_markers else None,
        f"({ALWAYS_EXCLUDED})",
    ]
    return " and ".join(part for part in parts if part)


def selection_description(request: RunRequest) -> str:
    """What the confirmation screen shows as the test selection."""
    special = PACKS[request.pack].special
    if special == "ota":
        stages = ota_stages(request.mode, request.firmware)
        return "OTA stages: " + " → ".join(stage.label for stage in stages)
    if special == "registration":
        return REGISTRATION_MARKERS
    return marker_expression(request)


def _pytest_plan(
    log_dir: Path, base_name: str, port: str, selection: Sequence[str]
) -> RunPlan:
    log_path = log_dir / f"{base_name}.log"
    junit_path = log_dir / f"{base_name}-junit.xml"
    argv = [
        sys.executable,
        "-m",
        "pytest",
        "-c",
        "pytest.ini",
        *selection,
        "--port",
        port,
        "-o",
        "log_cli=true",
        "-o",
        "log_cli_level=DEBUG",
        f"--log-file={log_path}",
        "--log-file-level=DEBUG",
        f"--junitxml={junit_path}",
        "-rA",
    ]
    return RunPlan(argv, log_path, junit_path)


def build_run_plan(request: RunRequest, port: str, started_at: datetime) -> RunPlan:
    pack = PACKS[request.pack]
    log_dir = Path("logs") / "automated" / pack.log_category / request.firmware
    base_name = f"run-{started_at:%Y%m%d-%H%M%S}-telegram-{request.pack}-{request.mode}"
    if pack.special == "registration":
        selection = [
            "-m",
            REGISTRATION_MARKERS,
            "--expected-fw-version",
            request.firmware,
            "tests/test_auth_registration.py",
        ]
    else:
        selection = [
            "-m",
            marker_expression(request),
            "--expected-fw-version",
            request.firmware,
        ]
    return _pytest_plan(log_dir, base_name, port, selection)


def build_ota_stage_plan(
    stage: OtaStage, index: int, port: str, started_at: datetime
) -> RunPlan:
    log_dir = Path("logs") / "automated" / "ota" / stage.firmware
    base_name = f"run-{started_at:%Y%m%d-%H%M%S}-telegram-ota-{index:02d}-{stage.label}"
    selection = [
        "-m",
        "ota",
        "-k",
        stage.test_filter,
        "--expected-fw-version",
        stage.firmware,
        "tests/test_ota.py",
    ]
    return _pytest_plan(log_dir, base_name, port, selection)


def parse_callback(data: str) -> tuple[str, RunRequest | str | None]:
    """Map callback data back onto the allow-listed tables; reject anything else."""
    action, _, rest = data.partition(":")
    fields = rest.split(":") if rest else []
    if action in {"menu", "cancel"} and not fields:
        return action, None
    if not fields or fields[0] not in PACKS:
        return "invalid", None
    pack_key = fields[0]
    if action == "pack" and len(fields) == 1:
        return action, pack_key
    if len(fields) < 2 or fields[1] not in PACKS[pack_key].modes:
        return "invalid", None
    if action == "mode" and len(fields) == 2:
        return action, RunRequest(pack_key, fields[1], "")
    if (
        action in {"fw", "start"}
        and len(fields) == 3
        and fields[2] in FIRMWARE_VERSIONS
    ):
        return action, RunRequest(pack_key, fields[1], fields[2])
    return "invalid", None


def build_provisioning_plan(
    board_firmware: str, target: str, port: str, started_at: datetime
) -> RunPlan:
    # Like every other log, the folder is the firmware running when the test starts;
    # the UART transcript of the switch lands in the same folder.
    log_dir = Path("logs") / "automated" / "provisioning" / board_firmware
    base_name = f"run-{started_at:%Y%m%d-%H%M%S}-telegram-provision-{target}"
    return _pytest_plan(
        log_dir, base_name, port, ["-m", "provision", "--provision-fw", target]
    )


def detect_board_firmware(port: str) -> str | None:
    """Read the running firmware over UART; None when the board does not answer."""
    from drivers.device_driver import DeviceDriver

    driver = DeviceDriver(port)
    try:
        driver.open()
        return driver.version()
    except (OSError, TimeoutError, ValueError) as error:
        LOGGER.warning("Could not detect firmware on %s: %s", port, error)
        return None
    finally:
        driver.close()


def summarize_junit(junit_path: Path) -> dict[str, int] | None:
    if not junit_path.is_file():
        return None
    try:
        root = ET.parse(junit_path).getroot()
    except ET.ParseError:
        return None
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    totals = {
        key: sum(int(suite.get(key, 0)) for suite in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }
    totals["passed"] = (
        totals["tests"] - totals["failures"] - totals["errors"] - totals["skipped"]
    )
    return totals


def _run_pytest(argv: Sequence[str], env: Mapping[str, str]) -> int:
    return subprocess.run(
        list(argv), cwd=DZ17_DIR, env=dict(env), stdin=subprocess.DEVNULL, check=False
    ).returncode


def _button(text: str, data: str) -> dict[str, str]:
    return {"text": text, "callback_data": data}


def _request_title(request: RunRequest) -> str:
    return f"{PACKS[request.pack].label} — {MODES[request.mode].label}"


class TelegramTestRunner:
    def __init__(
        self,
        client: TelegramInteraction,
        port: str,
        *,
        launch: Callable[[Sequence[str], Mapping[str, str]], int] = _run_pytest,
        now: Callable[[], datetime] = datetime.now,
        detect_firmware: Callable[[str], str | None] = detect_board_firmware,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client
        self._sleep = sleep
        self._port = port
        self._launch = launch
        self._now = now
        self._detect_firmware = detect_firmware
        self._menu_message_id: int | None = None
        # Firmware the board reported when the operator saw the confirmation.
        self._confirmed_board_firmware: str | None = None
        # A stop request left unread when the last pytest session ended.
        self._stop_requested_during_session = False

    def serve(self, should_stop: Callable[[], bool] = lambda: False) -> None:
        self._client.discard_pending_updates()
        self._client.set_commands(COMMANDS)
        self._client.notify(
            "🤖 DZ17 TEST RUNNER ONLINE\n"
            f"Bench port: {self._port}\n"
            "Send /run to choose a test pack."
        )
        LOGGER.info("Runner online; waiting for Telegram commands.")
        while not should_stop():
            # The helper already retries transient API errors; if Telegram stays
            # unavailable, keep the runner alive and try again later.
            try:
                for update in self._client.poll_updates(POLL_SECONDS):
                    self.handle_update(update)
            except RuntimeError as error:
                LOGGER.error(
                    "Telegram API error: %s Retrying in %ss.", error, API_ERROR_PAUSE_SECONDS
                )
                self._sleep(API_ERROR_PAUSE_SECONDS)

    def handle_update(self, update: Mapping[str, Any]) -> None:
        message = update.get("message")
        if isinstance(message, dict):
            self._handle_message(message)
            return
        callback = update.get("callback_query")
        if isinstance(callback, dict):
            self._handle_callback(callback)

    def _handle_message(self, message: Mapping[str, Any]) -> None:
        if not self._client.is_authorized_message(message):
            return
        text = message.get("text")
        if not isinstance(text, str) or not text.startswith("/"):
            return
        command = text.split()[0].split("@")[0].casefold()
        if command in {"/run", "/start", "/menu"}:
            self._confirmed_board_firmware = None
            self._menu_message_id = self._client.send_message(*self._menu())
        elif command == STOP_RUN_COMMAND:
            # While a pack runs, pytest reads this command itself; reaching the
            # runner means nothing is running.
            self._client.notify("⚪ No run is active. Send /run to start a pack.")
        elif command == "/status":
            self._client.notify(
                f"🟢 Runner idle — ready for /run.\nBench port: {self._port}"
            )
        elif command == "/help":
            self._client.notify(
                "🤖 DZ17 TEST RUNNER\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "/run — choose pack → mode → firmware → START.\n"
                "Only one pack runs at a time; test prompts arrive here during the run.\n"
                "The board's firmware is read before START; if it runs the other "
                "supported version, you can approve an OTA switch first. A failed "
                "switch blocks the pack.\n"
                "Live progress and a results report (passed/failed/skipped) are posted "
                "here.\n"
                "🔄 OTA runs the full chain (both versions and back) or checks only; "
                "🆕 Registration erases NVS only after a typed consent phrase.\n"
                "Alert-history cleanup and long-range sonar checks are console-only.\n"
                "/stop_execution (or ⏹ STOP RUN on the status message) stops the pack like Ctrl+C: "
                "at the current prompt or before the next test, with normal cleanup. "
                "The runner stays online."
            )

    def _handle_callback(self, callback: Mapping[str, Any]) -> None:
        if not self._client.is_authorized_callback(callback):
            return
        self._client.answer_callback(callback.get("id"))
        message = callback.get("message")
        message_id = message.get("message_id") if isinstance(message, dict) else None
        data = callback.get("data")
        if message_id != self._menu_message_id or not isinstance(data, str):
            return

        action, value = parse_callback(data)
        if action != "start":
            self._confirmed_board_firmware = None
        if action == "menu":
            self._client.edit_message(message_id, *self._menu())
        elif action == "cancel":
            self._client.edit_message(message_id, "✖️ Run cancelled. Send /run to start again.")
            self._menu_message_id = None
        elif action == "pack" and isinstance(value, str):
            modes = PACKS[value].modes
            if len(modes) == 1:
                self._after_mode(message_id, RunRequest(value, modes[0], ""))
            else:
                self._client.edit_message(message_id, *self._mode_menu(value))
        elif action == "mode" and isinstance(value, RunRequest):
            self._after_mode(message_id, value)
        elif action == "fw" and isinstance(value, RunRequest):
            if PACKS[value.pack].special == "ota":
                # OTA never takes a chosen version; it starts from the board.
                self._confirm_ota_from_board(message_id, value)
                return
            self._client.edit_message(
                message_id, f"🔎 Reading firmware from the board on {self._port}…"
            )
            self._confirmed_board_firmware = self._detect_firmware(self._port)
            self._client.edit_message(
                message_id, *self._confirmation(value, self._confirmed_board_firmware)
            )
        elif action == "start" and isinstance(value, RunRequest):
            if (
                PACKS[value.pack].special == "ota"
                and value.firmware != self._confirmed_board_firmware
            ):
                return  # OTA starts only from the firmware just read from the board
            self._menu_message_id = None
            self._start(message_id, value, self._confirmed_board_firmware)

    def _after_mode(self, message_id: int, request: RunRequest) -> None:
        if PACKS[request.pack].special == "ota":
            self._confirm_ota_from_board(message_id, request)
        else:
            self._client.edit_message(message_id, *self._firmware_menu(request))

    def _confirm_ota_from_board(self, message_id: int, request: RunRequest) -> None:
        """OTA starts from the running firmware, like run-ota-chain.ps1."""
        self._client.edit_message(
            message_id, f"🔎 Reading firmware from the board on {self._port}…"
        )
        board = self._detect_firmware(self._port)
        self._confirmed_board_firmware = board
        if board not in FIRMWARE_VERSIONS:
            reason = (
                "the board did not report its firmware"
                if board is None
                else f"unsupported firmware {board}"
            )
            self._client.edit_message(
                message_id,
                f"{_request_title(request)}\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"⛔ OTA cannot start: {reason}. OTA starts from the running firmware "
                "(2.1.0 or 2.3.0); check the UART connection and try again.",
                [[_button("⬅️ Back", "menu"), _button("✖️ Cancel", "cancel")]],
            )
            return
        start = RunRequest(request.pack, request.mode, board)
        self._client.edit_message(message_id, *self._confirmation(start, board))

    def _menu(self) -> tuple[str, list[list[dict[str, str]]]]:
        keys = list(PACKS)
        rows = [
            [_button(PACKS[key].label, f"pack:{key}") for key in keys[index : index + 2]]
            for index in range(0, len(keys), 2)
        ]
        rows.append([_button("✖️ Cancel", "cancel")])
        return (
            "🧪 DZ17 TEST RUNNER\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"Choose a test pack. Bench port: {self._port}",
            rows,
        )

    def _mode_menu(self, pack_key: str) -> tuple[str, list[list[dict[str, str]]]]:
        rows = [
            [_button(MODES[mode].label, f"mode:{pack_key}:{mode}")]
            for mode in PACKS[pack_key].modes
        ]
        rows.append([_button("⬅️ Back", "menu"), _button("✖️ Cancel", "cancel")])
        return f"{PACKS[pack_key].label}\n━━━━━━━━━━━━━━━━━━\nChoose what to run:", rows

    def _firmware_menu(
        self, request: RunRequest
    ) -> tuple[str, list[list[dict[str, str]]]]:
        rows = [
            [
                _button(f"FW {version}", f"fw:{request.pack}:{request.mode}:{version}")
                for version in FIRMWARE_VERSIONS
            ],
            [_button("⬅️ Back", "menu"), _button("✖️ Cancel", "cancel")],
        ]
        return (
            f"{_request_title(request)}\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Which firmware is flashed on the board?",
            rows,
        )

    def _confirmation(
        self, request: RunRequest, board_firmware: str | None
    ) -> tuple[str, list[list[dict[str, str]]]]:
        notes: list[str] = []
        needs_switch = (
            board_firmware in FIRMWARE_VERSIONS and board_firmware != request.firmware
        )
        if board_firmware is None:
            board_line = "Board: ❔ firmware not detected (the run checks it again)"
        elif board_firmware not in FIRMWARE_VERSIONS:
            board_line = (
                f"Board: ⛔ unsupported firmware {board_firmware} — OTA switching only "
                "covers 2.1.0 ↔ 2.3.0; the run will fail its firmware check"
            )
        elif needs_switch:
            board_line = f"Board: {board_firmware} → needs OTA to {request.firmware}"
            notes.append(
                f"⚠️ FIRMWARE SWITCH FIRST: the board is updated by OTA from "
                f"{board_firmware} to {request.firmware} (needs Wi-Fi, login, and the "
                "OTA server; reboots the board and changes the active partition). "
                "If the switch fails, the pack does not start."
            )
        else:
            board_line = f"Board: {board_firmware} ✅ matches"
        if request.mode != "auto":
            notes.append(
                "🙋 Physical actions and observations will be requested in this chat."
            )
        special = PACKS[request.pack].special
        if special == "ota":
            notes.append(
                "🔄 Includes the Wi-Fi interruption / download retry test and OTA "
                "reinstalls with reboots."
                + (
                    " The chain switches to the other version and back; the runner "
                    "checks the firmware between stages and stops on a mismatch."
                    if request.mode == "chain"
                    else ""
                )
            )
        elif special == "registration":
            notes.append(
                "⚠️ ERASES THE WHOLE NVS (saved account, Wi-Fi profile, settings) only "
                "after you type the exact consent phrase in this chat, then creates "
                "the configured account."
            )
        elif MODES[request.mode].persistent:
            notes.append(
                "⚠️ Changes persistent device state (saved settings, relay, scenes) "
                "and may reboot the board."
            )
        note_text = "\n".join(notes)
        rows = [
            [
                _button(
                    "▶️ SWITCH & START" if needs_switch else "▶️ START",
                    f"start:{request.pack}:{request.mode}:{request.firmware}",
                ),
                _button("✖️ Cancel", "cancel"),
            ]
        ]
        if special == "ota":
            firmware_lines = f"Starting firmware: {request.firmware} (read from the board)\n"
        else:
            firmware_lines = (
                f"Firmware: {request.firmware} (fails if the board reports another version)\n"
                f"{board_line}\n"
            )
        return (
            "▶️ READY TO START\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"Pack: {_request_title(request)}\n"
            f"{firmware_lines}"
            f"Port: {self._port}\n"
            f"Selection: {selection_description(request)}"
            + (f"\n\n{note_text}" if note_text else ""),
            rows,
        )

    def _start(
        self, message_id: int, request: RunRequest, board_firmware: str | None
    ) -> None:
        self._client.edit_message(
            message_id,
            "🏃 RUN STARTED\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"Pack: {_request_title(request)}\n"
            f"Firmware: {request.firmware} · Port: {self._port}",
        )
        # Switch only what the operator confirmed; if the board changed since, the
        # pack's own --expected-fw-version check still stops it.
        if board_firmware in FIRMWARE_VERSIONS and board_firmware != request.firmware:
            if not self._provision(board_firmware, request.firmware):
                return
        if PACKS[request.pack].special == "ota":
            self._run_ota(request)
            return
        plan = build_run_plan(request, self._port, self._now())
        LOGGER.info("Starting %s: %s", _request_title(request), " ".join(plan.argv))
        exit_code = self._launch_session(plan)
        if exit_code is None:
            return
        summary = self._summary(request, plan, exit_code)
        # Keep the outcome on the bench console even if Telegram is unavailable.
        LOGGER.info("Run finished with pytest exit code %s.\n%s", exit_code, summary)
        self._client.notify(summary)

    def _run_ota(self, request: RunRequest) -> None:
        stages = ota_stages(request.mode, request.firmware)
        results: list[str] = []
        outcome = "✅ OTA PACK PASSED"
        for index, stage in enumerate(stages, start=1):
            plan = build_ota_stage_plan(stage, index, self._port, self._now())
            self._client.notify(
                f"🔄 OTA STAGE {index}/{len(stages)}: {stage.label}\n"
                f"Firmware {stage.firmware} on {self._port}"
            )
            LOGGER.info("OTA stage %s: %s", stage.label, " ".join(plan.argv))
            exit_code = self._launch_session(plan)
            if exit_code is None:
                return
            totals = summarize_junit(DZ17_DIR / plan.junit_path)
            counts = (
                f"✅ {totals['passed']} · ❌ {totals['failures'] + totals['errors']} · "
                f"⚪ {totals['skipped']}"
                if totals is not None
                else f"pytest exit {exit_code}"
            )
            results.append(f"{index}. {stage.label}: {counts}\n   {plan.log_path.as_posix()}")
            if exit_code == 2 or self._stop_requested_during_session:
                outcome = "⏹ OTA PACK STOPPED"
                break
            if exit_code != 0:
                outcome = "❌ OTA PACK FINISHED WITH FAILURES"
            # A failed stage may still leave the board usable; like run-ota-chain.ps1,
            # continue only while the firmware is exactly what the plan expects.
            actual = self._detect_firmware_with_retry()
            if actual != stage.expected_after:
                outcome = (
                    f"⛔ OTA PACK STOPPED: expected firmware {stage.expected_after} "
                    f"after {stage.label}, board reports {actual or 'nothing'}"
                )
                break
        summary = "\n".join(
            [outcome, "━━━━━━━━━━━━━━━━━━", *results, "Send /run for another pack."]
        )
        LOGGER.info("OTA pack finished.\n%s", summary)
        self._client.notify(summary)

    def _detect_firmware_with_retry(self) -> str | None:
        # Right after an OTA reboot the UART may not answer yet.
        for attempt in range(1, DETECT_ATTEMPTS + 1):
            version = self._detect_firmware(self._port)
            if version is not None:
                return version
            if attempt < DETECT_ATTEMPTS:
                self._sleep(DETECT_RETRY_SECONDS)
        return None

    def _provision(self, board_firmware: str, target: str) -> bool:
        plan = build_provisioning_plan(board_firmware, target, self._port, self._now())
        self._client.notify(
            "🔄 FIRMWARE SWITCH\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"OTA {board_firmware} → {target} on {self._port}. The board will reboot."
        )
        LOGGER.info("Provisioning firmware %s: %s", target, " ".join(plan.argv))
        exit_code = self._launch_session(plan)
        if exit_code is None:
            return False
        if exit_code == 0 and self._stop_requested_during_session:
            # The switch has no prompts, so a stop sent during OTA is honoured here.
            self._client.notify(
                "⏹ RUN STOPPED\n"
                f"The firmware switch finished (board now runs {target}); "
                "the test pack was not started."
            )
            return False
        if exit_code == 0:
            self._client.notify(f"✅ Board now runs firmware {target}. Starting the pack.")
            return True
        self._client.notify(
            "⛔ RUN BLOCKED — precondition failed\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"Could not switch the board from {board_firmware} to {target} "
            f"(pytest exit {exit_code}). The test pack was not started.\n"
            f"Log: {plan.log_path.as_posix()}\n"
            f"JUnit: {plan.junit_path.as_posix()}\n"
            "Check Wi-Fi, login, and the OTA server, then send /run again."
        )
        LOGGER.error("Provisioning to %s failed with exit code %s.", target, exit_code)
        return False

    def _launch_session(self, plan: RunPlan) -> int | None:
        (DZ17_DIR / plan.log_path).parent.mkdir(parents=True, exist_ok=True)
        # Hand the bot over to the pytest session: it must not see stale updates,
        # and this process does not poll until the session ends.
        self._client.discard_pending_updates()
        env = {**os.environ, "INTERACTION_MODE": "telegram"}
        try:
            exit_code = self._launch(plan.argv, env)
        except OSError as error:
            LOGGER.error("Could not start pytest: %s", error)
            self._client.notify(f"⚠️ RUN NOT STARTED\nCould not launch pytest: {error}")
            return None
        try:
            self._stop_requested_during_session = self._client.discard_pending_updates()
        except RuntimeError as error:
            # Stale taps are still ignored: START only works on the current menu.
            self._stop_requested_during_session = False
            LOGGER.warning("Could not clear queued Telegram updates: %s", error)
        return exit_code

    def _summary(self, request: RunRequest, plan: RunPlan, exit_code: int) -> str:
        headings = {
            0: "✅ RUN PASSED",
            1: "❌ RUN FINISHED WITH FAILURES",
            2: "⏹ RUN STOPPED",
            5: "⚪ NO TESTS SELECTED",
        }
        heading = headings.get(exit_code, f"⚠️ RUN ERROR (pytest exit {exit_code})")
        lines = [
            heading,
            "━━━━━━━━━━━━━━━━━━",
            f"Pack: {_request_title(request)}",
            f"Firmware: {request.firmware} · Port: {self._port}",
        ]
        totals = summarize_junit(DZ17_DIR / plan.junit_path)
        if totals is not None:
            lines.append(
                f"Tests: {totals['tests']} · ✅ {totals['passed']} · "
                f"❌ {totals['failures'] + totals['errors']} · ⚪ {totals['skipped']}"
            )
        lines.append(f"Log: {plan.log_path.as_posix()}")
        lines.append(f"JUnit: {plan.junit_path.as_posix()}")
        lines.append("Send /run for another pack.")
        return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--port",
        default=os.environ.get("DZ17_PORT", "COM4"),
        help="ESP32 UART port passed to every run (default: DZ17_PORT or COM4).",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s"
    )
    try:
        client = TelegramInteraction.from_environment()
    except ValueError as error:
        parser.error(str(error))
    try:
        TelegramTestRunner(client, args.port).serve()
    except KeyboardInterrupt:
        LOGGER.info("Runner stopped by operator.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
