from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

import telegram_runner
from telegram_runner import RunRequest, TelegramTestRunner, parse_callback

CHAT_ID = 123


class _FakeClient:
    def __init__(self) -> None:
        self.sent: list[tuple[str, Any]] = []
        self.edits: list[tuple[int, str, Any]] = []
        self.discards = 0
        self.stop_seen_on_discard: set[int] = set()
        self._next_id = 100

    def send_message(self, text: str, buttons: Any = None) -> int:
        self._next_id += 1
        self.sent.append((text, buttons))
        return self._next_id

    def notify(self, text: str) -> None:
        self.send_message(text)

    def edit_message(self, message_id: int, text: str, buttons: Any = None) -> None:
        self.edits.append((message_id, text, buttons))

    def discard_pending_updates(self) -> bool:
        self.discards += 1
        # Stop requests queued during the session are reported after it ends.
        return self.discards in self.stop_seen_on_discard

    def answer_callback(self, callback_id: object) -> None:
        _ = callback_id

    def is_authorized_message(self, message: Mapping[str, Any]) -> bool:
        return message["from"]["id"] == CHAT_ID and message["chat"]["id"] == CHAT_ID

    def is_authorized_callback(self, callback: Mapping[str, Any]) -> bool:
        return (
            callback["from"]["id"] == CHAT_ID
            and callback["message"]["chat"]["id"] == CHAT_ID
        )


def _command(text: str, sender: int = CHAT_ID) -> dict[str, Any]:
    return {"message": {"text": text, "from": {"id": sender}, "chat": {"id": sender}}}


def _tap(message_id: int, data: str, sender: int = CHAT_ID) -> dict[str, Any]:
    return {
        "callback_query": {
            "id": "cb",
            "data": data,
            "from": {"id": sender},
            "message": {"message_id": message_id, "chat": {"id": sender}},
        }
    }


def _button_data(buttons: Sequence[Sequence[Mapping[str, str]]]) -> list[str]:
    return [button["callback_data"] for row in buttons for button in row]


@pytest.fixture
def launches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> list[tuple[list[str], dict[str, str]]]:
    monkeypatch.setattr(telegram_runner, "DZ17_DIR", tmp_path)
    return []


def _runner(
    client: _FakeClient,
    launches: list[tuple[list[str], dict[str, str]]],
    exit_code: int | Sequence[int] = 0,
    junit: str | None = None,
    board: str | None = "2.3.0",
    detect: Callable[[str], str | None] | None = None,
) -> TelegramTestRunner:
    exit_codes = iter([exit_code] if isinstance(exit_code, int) else exit_code)

    def launch(argv: Sequence[str], env: Mapping[str, str]) -> int:
        launches.append((list(argv), dict(env)))
        if junit is not None:
            junit_arg = next(arg for arg in argv if arg.startswith("--junitxml="))
            junit_path = telegram_runner.DZ17_DIR / junit_arg.split("=", 1)[1]
            junit_path.write_text(junit, encoding="utf-8")
        return next(exit_codes)

    return TelegramTestRunner(
        client,
        "COM4",
        launch=launch,
        now=lambda: datetime(2026, 10, 28, 9, 30, 0),
        detect_firmware=detect or (lambda port: board),
        sleep=lambda seconds: None,
    )


def test_marker_expression_keeps_console_only_suites_excluded() -> None:
    assert telegram_runner.marker_expression(RunRequest("lamp", "manual", "2.3.0")) == (
        "lamp and (interactive and not persistent) and "
        "(not ota and not auth_registration and not alert_cleanup and not long_range)"
    )
    assert telegram_runner.marker_expression(RunRequest("all", "auto", "2.1.0")) == (
        "(not interactive and not persistent) and "
        "(not ota and not auth_registration and not alert_cleanup and not long_range)"
    )
    assert telegram_runner.marker_expression(RunRequest("lamp", "all", "2.3.0")) == (
        "lamp and "
        "(not ota and not auth_registration and not alert_cleanup and not long_range)"
    )
    assert telegram_runner.marker_expression(RunRequest("all", "all", "2.3.0")) == (
        "(not ota and not auth_registration and not alert_cleanup and not long_range)"
    )


@pytest.mark.parametrize(
    "data",
    [
        "pack:provision",
        "mode:ota:auto",
        "mode:registration:all",
        "mode:relay:auto",
        "mode:relay:all",
        "fw:lamp:manual:9.9.9",
        "start:lamp:manual:2.3.0:extra",
        "start:lamp:manual",
        "pack:lamp; rm",
        "unknown:lamp",
        "",
    ],
)
def test_parse_callback_rejects_values_outside_the_allow_list(data: str) -> None:
    assert parse_callback(data) == ("invalid", None)


def test_full_flow_runs_selected_pack_and_reports_junit_totals(
    launches: list[tuple[list[str], dict[str, str]]],
) -> None:
    client = _FakeClient()
    runner = _runner(
        client,
        launches,
        exit_code=1,
        junit=(
            '<testsuites><testsuite tests="4" failures="1" errors="0" skipped="1">'
            "</testsuite></testsuites>"
        ),
    )

    runner.handle_update(_command("/run"))
    menu_id = 101
    assert "pack:lamp" in _button_data(client.sent[0][1])

    runner.handle_update(_tap(menu_id, "pack:lamp"))
    assert _button_data(client.edits[-1][2])[:3] == [
        "mode:lamp:manual",
        "mode:lamp:persistent",
        "mode:lamp:all",
    ]
    runner.handle_update(_tap(menu_id, "mode:lamp:persistent"))
    runner.handle_update(_tap(menu_id, "fw:lamp:persistent:2.3.0"))
    confirmation = client.edits[-1][1]
    assert "⚠️ Changes persistent device state" in confirmation
    assert "Board: 2.3.0 ✅ matches" in confirmation
    assert "Port: COM4" in confirmation
    assert client.edits[-1][2][0][0]["text"] == "▶️ START"

    runner.handle_update(_tap(menu_id, "start:lamp:persistent:2.3.0"))

    assert len(launches) == 1
    argv, env = launches[0]
    assert env["INTERACTION_MODE"] == "telegram"
    assert argv[argv.index("-m", 3) + 1].startswith("lamp and (persistent)")
    assert argv[argv.index("--expected-fw-version") + 1] == "2.3.0"
    assert argv[argv.index("--port") + 1] == "COM4"
    assert any(
        arg.endswith("run-20261028-093000-telegram-lamp-persistent-junit.xml")
        for arg in argv
    )
    assert client.discards == 2
    summary = client.sent[-1][0]
    assert summary.startswith("❌ RUN FINISHED WITH FAILURES")
    assert "Tests: 4 · ✅ 2 · ❌ 1 · ⚪ 1" in summary
    assert (
        "Log: logs/automated/lamp/2.3.0/run-20261028-093000-telegram-lamp-persistent.log"
        in summary
    )


def test_single_mode_pack_goes_straight_to_firmware_choice(
    launches: list[tuple[list[str], dict[str, str]]],
) -> None:
    client = _FakeClient()
    runner = _runner(client, launches)
    runner.handle_update(_command("/run"))

    runner.handle_update(_tap(101, "pack:relay"))

    assert _button_data(client.edits[-1][2])[:2] == [
        "fw:relay:persistent:2.1.0",
        "fw:relay:persistent:2.3.0",
    ]


def test_unauthorized_or_stale_input_never_starts_a_run(
    launches: list[tuple[list[str], dict[str, str]]],
) -> None:
    client = _FakeClient()
    runner = _runner(client, launches)

    runner.handle_update(_command("/run", sender=999))
    assert client.sent == []

    runner.handle_update(_command("/run"))
    runner.handle_update(_tap(101, "start:wifi:auto:2.1.0", sender=999))
    runner.handle_update(_tap(55, "start:wifi:auto:2.1.0"))
    assert launches == []

    runner.handle_update(_tap(101, "start:wifi:auto:2.1.0"))
    runner.handle_update(_tap(101, "start:wifi:auto:2.1.0"))
    assert len(launches) == 1


def test_missing_junit_still_reports_exit_status(
    launches: list[tuple[list[str], dict[str, str]]],
) -> None:
    client = _FakeClient()
    runner = _runner(client, launches, exit_code=5)
    runner.handle_update(_command("/run"))

    runner.handle_update(_tap(101, "start:guard:auto:2.3.0"))

    summary = client.sent[-1][0]
    assert summary.startswith("⚪ NO TESTS SELECTED")
    assert "Tests:" not in summary


def _confirm_and_start(runner: TelegramTestRunner, data: str) -> None:
    runner.handle_update(_command("/run"))
    runner.handle_update(_tap(101, data.replace("start:", "fw:", 1)))
    runner.handle_update(_tap(101, data))


def test_mismatched_board_is_switched_by_ota_before_the_pack(
    launches: list[tuple[list[str], dict[str, str]]],
) -> None:
    client = _FakeClient()
    runner = _runner(client, launches, exit_code=[0, 0], board="2.1.0")

    runner.handle_update(_command("/run"))
    runner.handle_update(_tap(101, "fw:wifi:auto:2.3.0"))
    confirmation, buttons = client.edits[-1][1:]
    assert "Board: 2.1.0 → needs OTA to 2.3.0" in confirmation
    assert "⚠️ FIRMWARE SWITCH FIRST" in confirmation
    assert buttons[0][0]["text"] == "▶️ SWITCH & START"

    runner.handle_update(_tap(101, "start:wifi:auto:2.3.0"))

    assert len(launches) == 2
    provision_argv, provision_env = launches[0]
    assert provision_argv[provision_argv.index("-m", 3) + 1] == "provision"
    assert provision_argv[provision_argv.index("--provision-fw") + 1] == "2.3.0"
    assert "--expected-fw-version" not in provision_argv
    assert provision_env["INTERACTION_MODE"] == "telegram"
    pack_argv = launches[1][0]
    assert pack_argv[pack_argv.index("--expected-fw-version") + 1] == "2.3.0"
    sent = [text for text, _ in client.sent]
    assert any(text.startswith("🔄 FIRMWARE SWITCH") for text in sent)
    assert "✅ Board now runs firmware 2.3.0. Starting the pack." in sent


def test_failed_firmware_switch_blocks_the_pack(
    launches: list[tuple[list[str], dict[str, str]]],
) -> None:
    client = _FakeClient()
    runner = _runner(client, launches, exit_code=[1], board="2.3.0")

    _confirm_and_start(runner, "start:auth:auto:2.1.0")

    assert len(launches) == 1
    blocked = client.sent[-1][0]
    assert blocked.startswith("⛔ RUN BLOCKED — precondition failed")
    assert "logs/automated/provisioning/2.3.0/run-20261028-093000-telegram-provision-2.1.0" in blocked


@pytest.mark.parametrize("board", [None, "2.2.0"])
def test_undetected_or_unsupported_board_is_not_switched(
    launches: list[tuple[list[str], dict[str, str]]], board: str | None
) -> None:
    client = _FakeClient()
    runner = _runner(client, launches, board=board)

    _confirm_and_start(runner, "start:guard:auto:2.3.0")

    assert "FIRMWARE SWITCH" not in client.edits[-2][1]
    assert len(launches) == 1
    assert "--provision-fw" not in launches[0][0]


def test_start_without_fresh_detection_never_switches_firmware(
    launches: list[tuple[list[str], dict[str, str]]],
) -> None:
    client = _FakeClient()
    runner = _runner(client, launches, board="2.1.0")
    runner.handle_update(_command("/run"))
    runner.handle_update(_tap(101, "fw:lamp:manual:2.3.0"))
    runner.handle_update(_command("/run"))

    runner.handle_update(_tap(102, "start:lamp:manual:2.3.0"))

    assert len(launches) == 1
    assert "--provision-fw" not in launches[0][0]


def test_runner_survives_telegram_outage_while_polling(
    launches: list[tuple[list[str], dict[str, str]]],
) -> None:
    client = _FakeClient()
    polls = iter([RuntimeError("HTTP 502 (getUpdates)"), [_command("/status")]])

    def poll_updates(timeout: int) -> list[dict[str, Any]]:
        result = next(polls)
        if isinstance(result, Exception):
            raise result
        return result

    client.poll_updates = poll_updates  # type: ignore[attr-defined]
    client.set_commands = lambda commands: None  # type: ignore[attr-defined]
    pauses: list[float] = []
    runner = TelegramTestRunner(
        client, "COM4", launch=lambda argv, env: 0, sleep=pauses.append
    )
    rounds = iter([False, False, True])

    runner.serve(should_stop=lambda: next(rounds))

    assert pauses == [telegram_runner.API_ERROR_PAUSE_SECONDS]
    assert client.sent[-1][0].startswith("🟢 Runner idle")


def test_stop_command_while_idle_says_no_run_is_active(
    launches: list[tuple[list[str], dict[str, str]]],
) -> None:
    client = _FakeClient()
    runner = _runner(client, launches)

    runner.handle_update(_command("/stop_execution"))

    assert client.sent[-1][0].startswith("⚪ No run is active")
    assert launches == []


def test_stop_during_firmware_switch_keeps_the_pack_from_starting(
    launches: list[tuple[list[str], dict[str, str]]],
) -> None:
    client = _FakeClient()
    # Discard #2 happens right after the provisioning session ends.
    client.stop_seen_on_discard = {2}
    runner = _runner(client, launches, exit_code=[0], board="2.1.0")

    _confirm_and_start(runner, "start:wifi:auto:2.3.0")

    assert len(launches) == 1
    assert "--provision-fw" in launches[0][0]
    stopped = client.sent[-1][0]
    assert stopped.startswith("⏹ RUN STOPPED")
    assert "board now runs 2.3.0" in stopped


def test_stop_execution_is_listed_in_the_bot_menu() -> None:
    assert ("stop_execution", "Stop the running test pack (like Ctrl+C)") in (
        telegram_runner.COMMANDS
    )


def _junit(tests: int, failures: int = 0) -> str:
    return f'<testsuites><testsuite tests="{tests}" failures="{failures}" errors="0" skipped="0"></testsuite></testsuites>'


def test_ota_full_chain_runs_four_stages_and_returns_to_start(
    launches: list[tuple[list[str], dict[str, str]]],
) -> None:
    client = _FakeClient()
    # Confirmation, then after each stage: 2.1.0, 2.3.0, 2.3.0, 2.1.0.
    versions = iter(["2.1.0", "2.1.0", "2.3.0", "2.3.0", "2.1.0"])
    runner = _runner(
        client,
        launches,
        exit_code=[0, 0, 0, 0],
        junit=_junit(3),
        detect=lambda port: next(versions),
    )

    _confirm_and_start(runner, "start:ota:chain:2.1.0")

    selections = [
        (argv[argv.index("-k") + 1], argv[argv.index("--expected-fw-version") + 1])
        for argv, _ in launches
    ]
    assert selections == [
        (telegram_runner.OTA_CHECKS_FILTER, "2.1.0"),
        ("test_available_update_completes_self_check", "2.1.0"),
        (telegram_runner.OTA_CHECKS_FILTER, "2.3.0"),
        ("test_forced_downgrade_completes_self_check", "2.3.0"),
    ]
    assert all("tests/test_ota.py" in argv for argv, _ in launches)
    summary = client.sent[-1][0]
    assert summary.startswith("✅ OTA PACK PASSED")
    assert "4. 2.3.0-to-2.1.0: ✅ 3 · ❌ 0 · ⚪ 0" in summary


def test_ota_chain_stops_when_the_board_reports_unexpected_firmware(
    launches: list[tuple[list[str], dict[str, str]]],
) -> None:
    client = _FakeClient()
    # The upgrade stage "passes" but the board is still on 2.1.0 afterwards.
    versions = iter(["2.1.0", "2.1.0", "2.1.0"])
    runner = _runner(
        client, launches, exit_code=[0, 0], junit=_junit(1), detect=lambda port: next(versions)
    )

    _confirm_and_start(runner, "start:ota:chain:2.1.0")

    assert len(launches) == 2
    assert client.sent[-1][0].startswith(
        "⛔ OTA PACK STOPPED: expected firmware 2.3.0 after 2.1.0-to-2.3.0, board reports 2.1.0"
    )


def test_ota_chain_honours_a_stop_request(
    launches: list[tuple[list[str], dict[str, str]]],
) -> None:
    client = _FakeClient()
    runner = _runner(client, launches, exit_code=[2], board="2.3.0")

    _confirm_and_start(runner, "start:ota:chain:2.3.0")

    assert len(launches) == 1
    assert client.sent[-1][0].startswith("⏹ OTA PACK STOPPED")


def test_ota_checks_only_runs_one_stage_without_version_change(
    launches: list[tuple[list[str], dict[str, str]]],
) -> None:
    client = _FakeClient()
    runner = _runner(client, launches, exit_code=[1], junit=_junit(5, failures=1), board="2.3.0")

    _confirm_and_start(runner, "start:ota:checks:2.3.0")

    assert len(launches) == 1
    assert client.sent[-1][0].startswith("❌ OTA PACK FINISHED WITH FAILURES")


def test_registration_pack_runs_the_au1_module_with_consent_warning(
    launches: list[tuple[list[str], dict[str, str]]],
) -> None:
    client = _FakeClient()
    runner = _runner(client, launches, board="2.3.0")

    runner.handle_update(_command("/run"))
    runner.handle_update(_tap(101, "pack:registration"))
    assert _button_data(client.edits[-1][2])[:2] == [
        "fw:registration:erase:2.1.0",
        "fw:registration:erase:2.3.0",
    ]
    runner.handle_update(_tap(101, "fw:registration:erase:2.3.0"))
    assert "⚠️ ERASES THE WHOLE NVS" in client.edits[-1][1]
    runner.handle_update(_tap(101, "start:registration:erase:2.3.0"))

    argv = launches[0][0]
    assert argv[argv.index("-m", 3) + 1] == telegram_runner.REGISTRATION_MARKERS
    assert "tests/test_auth_registration.py" in argv
    assert any("logs/automated/auth-registration/2.3.0/" in arg.replace("\\", "/") for arg in argv)


def test_all_packs_still_exclude_ota_and_registration() -> None:
    expression = telegram_runner.marker_expression(RunRequest("all", "all", "2.3.0"))
    assert "not ota" in expression and "not auth_registration" in expression


def test_ota_skips_the_firmware_menu_and_starts_from_the_board(
    launches: list[tuple[list[str], dict[str, str]]],
) -> None:
    client = _FakeClient()
    runner = _runner(client, launches, exit_code=[0], junit=_junit(35), board="2.3.0")

    runner.handle_update(_command("/run"))
    runner.handle_update(_tap(101, "pack:ota"))
    runner.handle_update(_tap(101, "mode:ota:checks"))

    confirmation, buttons = client.edits[-1][1:]
    assert "Starting firmware: 2.3.0 (read from the board)" in confirmation
    assert "Which firmware" not in "".join(text for _, text, _ in client.edits)
    assert _button_data(buttons)[0] == "start:ota:checks:2.3.0"

    runner.handle_update(_tap(101, "start:ota:checks:2.3.0"))

    argv = launches[0][0]
    assert argv[argv.index("--expected-fw-version") + 1] == "2.3.0"
    assert "--provision-fw" not in argv


@pytest.mark.parametrize(
    ("board", "reason"),
    [(None, "the board did not report its firmware"), ("2.2.0", "unsupported firmware 2.2.0")],
)
def test_ota_cannot_start_without_a_supported_board_firmware(
    launches: list[tuple[list[str], dict[str, str]]], board: str | None, reason: str
) -> None:
    client = _FakeClient()
    runner = _runner(client, launches, board=board)

    runner.handle_update(_command("/run"))
    runner.handle_update(_tap(101, "pack:ota"))
    runner.handle_update(_tap(101, "mode:ota:chain"))

    text, buttons = client.edits[-1][1:]
    assert f"⛔ OTA cannot start: {reason}" in text
    assert not any(data.startswith("start:") for data in _button_data(buttons))
    runner.handle_update(_tap(101, "start:ota:chain:2.1.0"))
    assert launches == []
