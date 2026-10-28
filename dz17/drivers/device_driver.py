from __future__ import annotations

import ipaddress
import logging
import re
import time
from typing import Any

import allure
import serial

LOGGER = logging.getLogger(__name__)
ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

VERSION_PATTERN = re.compile(
    r"(?:fw\s*:?\s*v?|version\s*:?\s*v?|sentry_fw7_v?)(\d+\.\d+\.\d+)", re.IGNORECASE
)
VERSION_RESPONSE_PATTERN = re.compile(
    r"(?:SENTRY SWM-2 sonar watch module,\s*fw\s*v|"
    r"firmware version:\s*v?|sentry_fw7_v?|fw\s*:?\s*v?|version\s*:?\s*v?)"
    r"(\d+\.\d+\.\d+)\b",
    re.IGNORECASE,
)
VERSION_RESPONSE_TIMEOUT = 3.0
STATE_PATTERN = re.compile(r"\bstate:\s*(\d+)\s+([A-Z]+)\b", re.IGNORECASE)
BEACON_STATUS_PATTERN = re.compile(
    r"\[BEACON\]\s*(ON|off),\s*color\s*\((\d+)\s*,\s*(\d+)\s*,\s*(\d+)\),\s*brightness\s*(\d+)%,\s*mode\s*([a-zA-Z0-9_-]+),\s*timer\s*([^\r\n]+)",
    re.IGNORECASE,
)
VALVE_STATUS_PATTERN = re.compile(
    r"\[VALVE\]\s*(OPEN|closed),\s*auto\s*(on|off),\s*cycles\s*(\d+)",
    re.IGNORECASE,
)
SONAR_STATS_PATTERN = re.compile(
    r"measurements\s*(\d+),\s*errors\s*(\d+),\s*min\s*([-+]?\d*(?:\.\d+|\d+)),\s*max\s*([-+]?\d*(?:\.\d+|\d+)),\s*avg\s*([-+]?\d*(?:\.\d+|\d+))\s*cm",
    re.IGNORECASE,
)
SONAR_CONFIG_PATTERN = re.compile(
    r"calibration\s*([-+]?\d*(?:\.\d+|\d+))\s*cm,\s*filter\s*(?:median\s*(\d+)|(off|on)),\s*alarm\s*(on|off)",
    re.IGNORECASE,
)
OTA_BOOT_READY_MARKER = "ready. state 1 NORMAL (patrol). Type 'help'"

OTA_TERMINAL_MARKERS = (
    OTA_BOOT_READY_MARKER,
    "[OTA] self-check FAILED",
    "[OTA] check failed:",
    "[OTA] failed:",
    "[OTA] error:",
    "[OTA] already up to date",
    "[OTA] up to date",
    "[OTA] downgrade blocked:",
    "E408 downgrade blocked:",
    "E414 bad version",
    "E415 version",
    "E418 url must start with",
    "E406",
    "E412",
    "E410",
    "E402",
    "E403",
    "E401",
    "E405",
    "E407",
    "E411",
    "E003",
    "E002",
    "Rolling back...",
)
_OTA_ERROR_CODE = re.compile(r"E\d{3}")


def has_ota_terminal_result(lines: list[str]) -> bool:
    """Return True once the OTA output contains a terminal marker.

    Bare error codes must match as whole, case-sensitive words: image
    verification prints hex addresses such as ``paddr=001e0020`` that would
    otherwise contain ``E002``.
    """
    output = "\n".join(lines)
    folded = output.casefold()
    for marker in OTA_TERMINAL_MARKERS:
        if _OTA_ERROR_CODE.fullmatch(marker):
            if re.search(rf"\b{marker}\b", output):
                return True
        elif marker.casefold() in folded:
            return True
    return False


class DeviceDriver:
    """UART driver for SENTRY SWM-2 (fw_7) firmware."""

    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 0.1) -> None:
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.serial: serial.Serial | None = None
        self.uart_log: list[str] = []
        self._receive_buffer = ""
        self._sensitive_uart_values: set[str] = set()

    @property
    def is_open(self) -> bool:
        return self.serial is not None and self.serial.is_open

    def buffer_len(self) -> int:
        return len(self.uart_log)

    def _require_open_serial(self) -> serial.Serial:
        if self.serial is None or not self.serial.is_open:
            raise RuntimeError("Serial port is not open. Call open() first.")
        return self.serial

    def _redact(self, text: str) -> str:
        for value in sorted(self._sensitive_uart_values, key=len, reverse=True):
            if value:
                text = text.replace(value, "[REDACTED]")
        text = re.sub(
            r"((?:^|:\s*)guard\s+disarm\s+)\S+",
            r"\1[REDACTED]",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"((?:^|:\s*)guard\s+pin\s+)\S+\s+\S+",
            r"\1[REDACTED] [REDACTED]",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"^((?:login|register)\s+\S+\s+)(\S+)",
            r"\1[REDACTED]",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"((?:^|:\s*)passwd\s+)\S+\s+\S+",
            r"\1[REDACTED] [REDACTED]",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"((?:^|:\s*)sudo\s+)\S+",
            r"\1[REDACTED]",
            text,
            flags=re.IGNORECASE,
        )
        return text

    def _record(self, direction: str, text: str) -> None:
        text = self._redact(text)
        line = f"{direction} {text}"
        self.uart_log.append(line)
        LOGGER.debug("%s", line)

    def ensure_ends_with_rn(self, command: str) -> str:
        """Return a command terminated by CRLF."""
        return command.rstrip("\r\n") + "\r\n"

    @allure.step("Open UART connection")
    def open(self) -> None:
        allure.dynamic.parameter("UART port", self.port)
        if self.serial is None:
            connection = serial.Serial(
                port=None,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self.timeout,
            )
            connection.dtr = False
            connection.rts = False
            connection.port = self.port
            connection.open()
            self.serial = connection
        elif not self.serial.is_open:
            self.serial.open()

        connection = self._require_open_serial()
        connection.reset_input_buffer()
        connection.reset_output_buffer()
        self._receive_buffer = ""

    @allure.step("Close UART connection")
    def close(self) -> None:
        if self.serial is not None:
            if self.serial.is_open:
                self.serial.close()
            self.serial = None
        self._receive_buffer = ""

    def _read_for(self, timeout: float) -> list[str]:
        connection = self._require_open_serial()
        lines: list[str] = []
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            waiting = connection.in_waiting
            if waiting:
                self._receive_buffer += connection.read(waiting).decode(
                    "utf-8", errors="replace"
                )
                while "\n" in self._receive_buffer:
                    raw_line, self._receive_buffer = self._receive_buffer.split("\n", 1)
                    line = ANSI_ESCAPE.sub("", raw_line.replace("\r", "")).strip()
                    if line:
                        self._record("RX <", line)
                        lines.append(self._redact(line))
            else:
                time.sleep(0.01)

        trailing = ANSI_ESCAPE.sub("", self._receive_buffer.replace("\r", "")).strip()
        if trailing:
            self._record("RX <", trailing)
            lines.append(self._redact(trailing))
            self._receive_buffer = ""

        return lines

    @allure.step("Read UART output for up to {timeout} seconds")
    def read_for(self, timeout: float) -> list[str]:
        return self._read_for(timeout)

    def send_command(self, command: str, timeout: float = 0.6) -> list[str]:
        connection = self._require_open_serial()
        self._record("TX >", command)

        display_cmd = self._redact(command)
        with allure.step(f"UART command: {display_cmd}"):
            connection.write(self.ensure_ends_with_rn(command).encode("utf-8"))
            connection.flush()
            lines = self._read_for(timeout)

            if lines:
                sanitized_lines = [self._redact(line) for line in lines]
                allure.attach(
                    "\n".join(sanitized_lines),
                    name=f"UART response: {display_cmd}",
                    attachment_type=allure.attachment_type.TEXT,
                )
            return lines

    def send_command_nowait(self, command: str, sensitive: bool = False) -> None:
        """Write a command without consuming UART; use wait_for* for its response."""
        display_cmd = self._redact(command)
        with allure.step(f"Send UART command and await event: {display_cmd}"):
            self._send_line(command, sensitive=sensitive)

    def _send_command_wait_for_any(
        self,
        command: str,
        markers: tuple[str, ...],
        timeout: float,
    ) -> list[str]:
        start_idx = self.buffer_len()
        self.send_command_nowait(command)
        matched = self.wait_for_any(markers, timeout=timeout, since_index=start_idx)
        response = [
            entry[5:]
            for entry in self.uart_log[start_idx:]
            if entry.startswith("RX < ")
        ]
        if matched is None:
            raise TimeoutError(
                f"UART command {self._redact(command)!r} did not produce any of "
                f"{markers!r} within {timeout} seconds; response: {response!r}"
            )
        if response:
            allure.attach(
                "\n".join(response),
                name=f"UART response: {self._redact(command)}",
                attachment_type=allure.attachment_type.TEXT,
            )
        return response

    def _send_line(self, line: str, sensitive: bool = False) -> None:
        connection = self._require_open_serial()
        if sensitive and line:
            self._sensitive_uart_values.add(line)
        self._record("TX >", "[REDACTED]" if sensitive and line else line)
        connection.write(self.ensure_ends_with_rn(line).encode("utf-8"))
        connection.flush()

    def wait_for(
        self, text: str, timeout: float, since_index: int | None = None
    ) -> bool:
        display_text = self._redact(text)
        with allure.step(f"Wait for UART text '{display_text}' (timeout: {timeout} seconds)"):
            start_idx = since_index if since_index is not None else len(self.uart_log)
            if since_index is not None:
                for entry in self.uart_log[start_idx:]:
                    if text.casefold() in entry.casefold():
                        return True

            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                lines = self._read_for(min(0.2, deadline - time.monotonic()))
                for line in lines:
                    if text.casefold() in line.casefold():
                        return True
            return False

    def wait_for_all(
        self,
        texts: list[str] | tuple[str, ...],
        timeout: float,
        since_index: int | None = None,
    ) -> dict[str, bool]:
        display_texts = [self._redact(t) for t in texts]
        with allure.step(f"Wait for all UART texts {display_texts} (timeout: {timeout} seconds)"):
            start_idx = since_index if since_index is not None else len(self.uart_log)
            found: dict[str, bool] = {text: False for text in texts}

            def check_found() -> bool:
                for entry in self.uart_log[start_idx:]:
                    for text in texts:
                        if not found[text] and text.casefold() in entry.casefold():
                            found[text] = True
                return all(found.values())

            if check_found():
                return found

            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline and not all(found.values()):
                self._read_for(min(0.2, deadline - time.monotonic()))
                if check_found():
                    return found
            return found

    def wait_for_any(
        self,
        patterns: tuple[str, ...],
        timeout: float,
        since_index: int | None = None,
    ) -> str | None:
        display_patterns = [self._redact(p) for p in patterns]
        with allure.step(f"Wait for any UART message from {display_patterns}"):
            start_idx = since_index if since_index is not None else len(self.uart_log)

            def find_match() -> str | None:
                for entry in self.uart_log[start_idx:]:
                    for pattern in patterns:
                        if pattern.casefold() in entry.casefold():
                            return pattern
                return None

            already_seen = find_match()
            if already_seen is not None:
                return already_seen

            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                lines = self._read_for(min(0.2, deadline - time.monotonic()))
                for line in lines:
                    for pattern in patterns:
                        if pattern.casefold() in line.casefold():
                            return pattern
            return None

    # --- Firmware & System ---

    @allure.step("Parse firmware version from UART response")
    def get_firmware_version(self, lines: list[str]) -> str:
        versions = [
            match.group(1)
            for line in lines
            if (match := VERSION_PATTERN.search(line)) is not None
        ]
        if not versions:
            raise AssertionError(f"Could not parse firmware version from UART: {lines!r}")
        return versions[-1]

    @allure.step("Read firmware version")
    def version(self, timeout: float = VERSION_RESPONSE_TIMEOUT) -> str:
        start_idx = len(self.uart_log)
        self.send_command_nowait("version")
        deadline = time.monotonic() + timeout
        while True:
            for entry in self.uart_log[start_idx:]:
                if not entry.startswith("RX < "):
                    continue
                match = VERSION_RESPONSE_PATTERN.search(entry[5:])
                if match is not None:
                    return match.group(1)

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    "Timed out waiting for a firmware version response matching "
                    "the SENTRY version banner or a supported firmware-version line."
                )
            self._read_for(min(0.2, remaining))

    @allure.step("Parse system state from UART response")
    def parse_state(self, lines: list[str]) -> tuple[int, str]:
        for line in reversed(lines):
            match = STATE_PATTERN.search(line)
            if match:
                return int(match.group(1)), match.group(2).upper()
            state_event = re.search(r"->\s*(\d+)\s+([A-Z]+)", line, re.I)
            if state_event:
                return int(state_event.group(1)), state_event.group(2).upper()
        raise AssertionError(f"Could not parse system state from UART: {lines!r}")

    @allure.step("Get system state")
    def get_state(self, timeout: float = 0.6) -> tuple[int, str]:
        lines = self.send_command("state", timeout=timeout)
        return self.parse_state(lines)

    @allure.step("Set system state to {state}")
    def set_state(self, state: int | str, timeout: float = 0.6) -> list[str]:
        return self.send_command(f"state {state}", timeout=timeout)

    @allure.step("Reboot the device")
    def reboot(self, timeout: float = 30.0) -> bool:
        connection = self._require_open_serial()
        self._record("TX >", "reboot")
        connection.write(b"reboot\r\n")
        connection.flush()
        # SENTRY SWM-2 counts down 3-2-1 before restarting
        time.sleep(3.5)
        self._receive_buffer = ""
        connection.reset_input_buffer()
        start_idx = len(self.uart_log)
        deadline = time.monotonic() + timeout
        while True:
            for entry in self.uart_log[start_idx:]:
                response = entry.removeprefix("RX < ").strip().casefold()
                if "ready" in response or response == "sentry:":
                    return True

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            self._read_for(min(0.2, remaining))

    # --- Authentication & Account ---

    @allure.step("Register user '{username}' (password redacted)")
    def register(self, username: str, password: str, timeout: float = 2.0) -> list[str]:
        if password:
            self._sensitive_uart_values.add(password)
        return self.send_command(f"register {username} {password}", timeout=timeout)

    @allure.step("Login as user '{username}' (password redacted)")
    def login(self, username: str, password: str, timeout: float = 2.0) -> list[str]:
        if password:
            self._sensitive_uart_values.add(password)
        return self.send_command(f"login {username} {password}", timeout=timeout)

    @allure.step("Send login for user '{username}' and await UART result (password redacted)")
    def login_nowait(self, username: str, password: str) -> None:
        if password:
            self._sensitive_uart_values.add(password)
        self.send_command_nowait(
            f"login {username} {password}",
            sensitive=True,
        )

    @allure.step("Logout from current session")
    def logout(self, timeout: float = 1.0) -> list[str]:
        return self.send_command("logout", timeout=timeout)

    @allure.step("Query current user identity (whoami)")
    def whoami(self, timeout: float = 0.6) -> dict[str, Any]:
        lines = self.send_command("whoami", timeout=timeout)
        user = "not logged in"
        access = "none"
        logged_in = False
        for line in lines:
            if "not logged in" in line.casefold():
                user = "not logged in"
                access = "none"
                logged_in = False
                break
            match = re.search(r"user:\s*([^\s,]+),\s*access:\s*([^\s,]+)", line, re.I)
            if match:
                user = match.group(1).strip()
                access = match.group(2).strip()
                logged_in = True
                break
        return {"user": user, "access": access, "logged_in": logged_in, "raw": lines}

    @allure.step("Change user password (passwords redacted)")
    def passwd(
        self, old_password: str, new_password: str, timeout: float = 3.0
    ) -> list[str]:
        if old_password:
            self._sensitive_uart_values.add(old_password)
        if new_password:
            self._sensitive_uart_values.add(new_password)
        return self.send_command(f"passwd {old_password} {new_password}", timeout=timeout)

    @allure.step("Elevate user to debug mode via sudo (password redacted)")
    def sudo(self, password: str, timeout: float = 3.0) -> list[str]:
        if password:
            self._sensitive_uart_values.add(password)
        return self.send_command(f"sudo {password}", timeout=timeout)

    # --- Over-the-Air Updates (OTA) ---

    @allure.step("Read OTA status")
    def ota_status(self, timeout: float = 3.0) -> dict[str, Any]:
        lines = self.send_command("ota status", timeout=timeout)
        running_ver = None
        running_part = None
        running_state = None
        prev_ver = None
        prev_part = None
        for line in lines:
            m_run = re.search(r"\[OTA\]\s*running:\s*(?:v?(\d+\.\d+\.\d+))\s*in\s*(ota_\d+)\s*(?:\(([^)]+)\))?", line, re.I)
            if m_run:
                running_ver = m_run.group(1)
                running_part = m_run.group(2)
                running_state = m_run.group(3)
            m_prev = re.search(r"\[OTA\]\s*previous:\s*(?:v?(\d+\.\d+\.\d+)|none)\s*(?:in\s*(ota_\d+)|(?:\(([^)]+)\)))?", line, re.I)
            if m_prev:
                prev_ver = m_prev.group(1)
                prev_part = m_prev.group(2)
        return {
            "running_version": running_ver,
            "running_partition": running_part,
            "running_state": running_state,
            "previous_version": prev_ver,
            "previous_partition": prev_part,
            "raw": lines,
        }

    @allure.step("Check OTA channels (ota check)")
    def ota_check(self, timeout: float = 8.0) -> dict[str, Any]:
        lines = self.send_command("ota check", timeout=timeout)
        current = None
        stable = None
        beta = None
        channel_status = None
        for line in lines:
            m_cur = re.search(r"\[OTA\]\s*current:\s*v?(\d+\.\d+\.\d+)", line, re.I)
            if m_cur:
                current = m_cur.group(1)
            m_sta = re.search(r"\[OTA\]\s*stable:\s*v?(\d+\.\d+\.\d+)", line, re.I)
            if m_sta:
                stable = m_sta.group(1)
            m_bet = re.search(r"\[OTA\]\s*beta:\s*v?(\d+\.\d+\.\d+)", line, re.I)
            if m_bet:
                beta = m_bet.group(1)
            if any(term in line.casefold() for term in ("up to date", "update available", "running newer than stable")):
                channel_status = line.strip()
        return {
            "current": current,
            "stable": stable,
            "beta": beta,
            "status": channel_status,
            "raw": lines,
        }

    @allure.step("Show or configure OTA server ({server})")
    def ota_server(self, server: str | None = None, timeout: float = 3.0) -> list[str]:
        cmd = f"ota server {server}" if server is not None else "ota server"
        return self.send_command(cmd, timeout=timeout)

    @allure.step("Run OTA command '{command}' and wait for a terminal result")
    def run_ota(self, command: str, timeout: float = 180.0) -> list[str]:
        if timeout <= 0:
            raise ValueError("OTA timeout must be greater than zero.")
        lines = self.send_command(command, timeout=min(0.5, timeout))
        deadline = time.monotonic() + timeout

        while not has_ota_terminal_result(lines) and time.monotonic() < deadline:
            lines.extend(self._read_for(min(0.2, deadline - time.monotonic())))

        if not has_ota_terminal_result(lines):
            response = "\n".join(lines)
            allure.attach(
                response or "No OTA output was captured.",
                name=f"OTA response: {command}",
                attachment_type=allure.attachment_type.TEXT,
            )
            raise TimeoutError(
                f"OTA command {command!r} did not report a terminal result "
                f"within {timeout:.1f} seconds.\n{response}"
            )

        allure.attach(
            "\n".join(lines),
            name=f"OTA response: {command}",
            attachment_type=allure.attachment_type.TEXT,
        )
        return lines

    @staticmethod
    def _is_retryable_ota_connectivity_failure(lines: list[str]) -> bool:
        output = "\n".join(lines)
        folded = output.casefold()
        # E402 must be a whole word, not part of a hex address in image logs.
        return re.search(r"\bE402\b", output) is not None or any(
            marker in folded
            for marker in (
                "couldn't get hostname",
                "getaddrinfo()",
                "failed to open a new connection",
                "connection failed, sock",
                "cannot read stable.txt",
                "cannot read beta.txt",
            )
        )

    @allure.step("Run OTA command '{command}' with bounded connectivity retries")
    def run_ota_with_connectivity_retry(
        self,
        command: str,
        timeout: float = 180.0,
        attempts: int = 3,
        retry_delay: float = 3.0,
    ) -> list[str]:
        if attempts < 1:
            raise ValueError("OTA connectivity retry attempts must be at least one.")
        if retry_delay < 0:
            raise ValueError("OTA connectivity retry delay cannot be negative.")

        for attempt in range(1, attempts + 1):
            lines = self.run_ota(command, timeout=timeout)
            if not self._is_retryable_ota_connectivity_failure(lines):
                return lines
            if attempt == attempts:
                break

            status = self.wifi_status()
            if not self.wifi_connection_is_valid(status):
                if not self.wifi_reconnect():
                    raise ConnectionError(
                        "OTA encountered a DNS/connection failure and the device "
                        f"could not restore Wi-Fi connectivity: {status!r}"
                    )

            LOGGER.warning(
                "OTA command %r hit a transient connectivity error "
                "(attempt %d/%d); retrying in %.1f seconds.",
                command,
                attempt,
                attempts,
                retry_delay,
            )
            time.sleep(retry_delay)

        response = "\n".join(lines)
        raise ConnectionError(
            f"OTA command {command!r} failed with a DNS/connection error after "
            f"{attempts} attempts. Check internet/DNS access to the OTA host and "
            f"rerun the phase.\nLast device response:\n{response}"
        )

    # --- Beacon Lamp ---

    @allure.step("Turn Beacon lamp ON")
    def lamp_on(self, timeout: float = 0.6) -> list[str]:
        return self.send_command("lamp on", timeout=timeout)

    @allure.step("Turn Beacon lamp OFF")
    def lamp_off(self, timeout: float = 0.6) -> list[str]:
        return self.send_command("lamp off", timeout=timeout)

    @allure.step("Toggle Beacon lamp")
    def lamp_toggle(self, timeout: float = 0.6) -> list[str]:
        return self.send_command("lamp toggle", timeout=timeout)

    @allure.step("Set Beacon color to {color}")
    def lamp_set_color(
        self, color: str | tuple[int, int, int], timeout: float = 0.6
    ) -> list[str]:
        value = color if isinstance(color, str) else f"{color[0]} {color[1]} {color[2]}"
        return self.send_command(f"lamp color {value}", timeout=timeout)

    @allure.step("Set Beacon brightness to {brightness}%")
    def lamp_set_brightness(self, brightness: int, timeout: float = 0.6) -> list[str]:
        return self.send_command(f"lamp brightness {brightness}", timeout=timeout)

    @allure.step("Set Beacon mode to '{mode}'")
    def lamp_set_mode(self, mode: str, timeout: float = 0.6) -> list[str]:
        return self.send_command(f"lamp mode {mode}", timeout=timeout)

    @allure.step("Set Beacon auto-off timer to {seconds} seconds")
    def lamp_set_timer(self, seconds: int, timeout: float = 0.6) -> list[str]:
        return self.send_command(f"lamp timer {seconds}", timeout=timeout)

    @allure.step("Save Beacon scene {scene}")
    def lamp_save_scene(self, scene: int, timeout: float = 0.6) -> list[str]:
        return self.send_command(f"lamp scene save {scene}", timeout=timeout)

    @allure.step("Load Beacon scene {scene}")
    def lamp_load_scene(self, scene: int, timeout: float = 0.6) -> list[str]:
        return self.send_command(f"lamp scene load {scene}", timeout=timeout)

    @allure.step("Parse Beacon status from UART response")
    def parse_lamp_status(self, lines: list[str]) -> dict[str, Any]:
        for line in reversed(lines):
            match = BEACON_STATUS_PATTERN.search(line)
            if match:
                state_str = match.group(1).upper()
                r = int(match.group(2))
                g = int(match.group(3))
                b = int(match.group(4))
                brightness = int(match.group(5))
                mode = match.group(6)
                timer_str = match.group(7).strip()

                timer_seconds = 0
                timer_num_match = re.search(r"(\d+)\s*s", timer_str, re.I)
                if timer_num_match:
                    timer_seconds = int(timer_num_match.group(1))

                return {
                    "lamp": "on" if state_str == "ON" else "off",
                    "color": (r, g, b),
                    "brightness": brightness,
                    "mode": mode,
                    "timer": timer_str,
                    "timer_s": timer_seconds,
                    "raw": lines,
                }
        raise AssertionError(f"No beacon status found in UART response: {lines!r}")

    @allure.step("Read Beacon lamp status")
    def lamp_status(self, timeout: float = 0.6) -> dict[str, Any]:
        lines = self.send_command("lamp status", timeout=timeout)
        return self.parse_lamp_status(lines)

    # --- Wi-Fi & Network ---

    @staticmethod
    def parse_wifi_scan(lines: list[str]) -> list[dict[str, Any]]:
        access_points: list[dict[str, Any]] = []
        for line in lines:
            match = re.search(r"\[\s*(\d+)\s*\]\s*(.+?)(?:\s*-\s*(-?\d+)\s*dBm)?$", line, re.I)
            if match:
                idx = int(match.group(1))
                ssid = match.group(2).strip()
                rssi = int(match.group(3)) if match.group(3) is not None else None
                access_points.append({"index": idx, "ssid": ssid, "rssi": rssi})
        return access_points

    @allure.step("Scan nearby Wi-Fi networks")
    def wifi_scan(self, timeout: float = 10.0) -> list[str]:
        lines = self.send_command("scan", timeout=timeout)
        return [ap["ssid"] for ap in self.parse_wifi_scan(lines)]

    @allure.step("Connect to Wi-Fi SSID '{ssid}' (password redacted)")
    def wifi_connect(
        self,
        ssid: str = "",
        password: str = "",
        timeout: float = 12.0,
    ) -> bool:
        if password:
            self._sensitive_uart_values.add(password)
        initial_lines = self.send_command("connect", timeout=0.5)
        prompts = ("ssid or number:", "enter ssid", "password:")

        prompt = next(
            (
                p for p in prompts
                if any(p in line.casefold() for line in initial_lines)
            ),
            None,
        )
        if prompt is None:
            prompt = self.wait_for_any(prompts, timeout=6.0)

        if prompt is None:
            return False

        connection_start = len(self.uart_log)
        if "password:" in prompt.casefold():
            self._send_line(password, sensitive=True)
        else:
            self._send_line(ssid)
            if ssid:
                password_prompt = self.wait_for("password:", timeout=6.0)
                if not password_prompt:
                    return False
                connection_start = len(self.uart_log)
                self._send_line(password, sensitive=True)

        return self._wait_for_wifi_connection(
            connection_start,
            timeout,
            operation="connect",
        )

    @allure.step("Reconnect to saved Wi-Fi network")
    def wifi_reconnect(self, timeout: float = 12.0) -> bool:
        start_idx = len(self.uart_log)
        self.send_command_nowait("reconnect")
        if self.wait_for_any(("already connected", "W114"), 0, since_index=start_idx):
            return True
        return self._wait_for_wifi_connection(
            start_idx,
            timeout,
            operation="reconnect",
            already_connected_is_success=True,
        )

    def _wait_for_wifi_connection(
        self,
        start_idx: int,
        timeout: float,
        *,
        operation: str,
        already_connected_is_success: bool = False,
    ) -> bool:
        positive_groups = {
            "association": ("connected to '", "wifi:connected"),
            "ip": ("got ip", "sta ip:"),
        }
        failure_markers = (
            "E101",
            "E102",
            "E104",
            "E111",
            "E112",
            "password too short",
            "wrong password",
            "dhcp timeout",
            "connection failed",
            "reconnect failed",
        )
        observed: set[str] = set()
        deadline = time.monotonic() + timeout

        while True:
            entries = self.uart_log[start_idx:]
            output = "\n".join(entries).casefold()
            if already_connected_is_success and (
                "already connected" in output or "w114" in output
            ):
                return True
            failure = next(
                (
                    marker
                    for marker in failure_markers
                    if marker.casefold() in output
                ),
                None,
            )
            if failure is not None:
                LOGGER.warning(
                    "Wi-Fi %s failed after explicit UART response %r",
                    operation,
                    failure,
                )
                return False

            for group, variants in positive_groups.items():
                if any(variant in output for variant in variants):
                    observed.add(group)
            if observed == set(positive_groups):
                return True

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                missing = sorted(set(positive_groups) - observed)
                LOGGER.warning(
                    "Wi-Fi %s did not emit required UART success events; "
                    "observed=%s, missing=%s, response=%s",
                    operation,
                    sorted(observed),
                    missing,
                    entries,
                )
                return False
            self._read_for(min(0.2, remaining))

    @allure.step("Disconnect from Wi-Fi")
    def wifi_disconnect(self, timeout: float = 1.0) -> list[str]:
        start_idx = len(self.uart_log)
        self.send_command_nowait("disconnect")
        self.wait_for_any(
            (
                "[LINK] disconnected",
                "W115",
                "E001",
                "E003",
                "E005",
                "E099",
            ),
            timeout=timeout,
            since_index=start_idx,
        )
        return [
            entry[5:]
            for entry in self.uart_log[start_idx:]
            if entry.startswith("RX < ")
        ]

    @allure.step("Forget saved Wi-Fi network")
    def wifi_forget(self, timeout: float = 1.0) -> list[str]:
        return self.send_command("forget", timeout=timeout)

    @staticmethod
    def parse_wifi_status(lines: list[str]) -> dict[str, Any]:
        connected = False
        ssid: str | None = None
        ip_addr: str | None = None
        rssi: int | None = None
        internet_ok = False
        user: str = "not logged in"

        for line in lines:
            line_cf = line.casefold()
            if "link:" in line_cf:
                if "buoy link '" in line_cf or "connected (" in line_cf:
                    connected = True
                    ssid_match = re.search(r"buoy link '([^']+)'|connected \(([^)]+)\)", line, re.I)
                    if ssid_match:
                        ssid = ssid_match.group(1) or ssid_match.group(2)
                elif "buoy link down" in line_cf:
                    connected = False
                    known_match = re.search(r"known:\s*([^\s)]+)", line, re.I)
                    if known_match:
                        ssid = known_match.group(1)

                ip_match = re.search(r"ip\s+((?:\d{1,3}\.){3}\d{1,3})", line, re.I)
                if ip_match:
                    ip_addr = ip_match.group(1)

                rssi_match = re.search(r"rssi\s+(-?\d+)\s*dBm", line, re.I)
                if rssi_match:
                    rssi = int(rssi_match.group(1))

            if "internet: ok" in line_cf or "fleet network reachable" in line_cf:
                internet_ok = True

            if "user:" in line_cf:
                user_match = re.search(r"user:\s*([^\s,]+)", line, re.I)
                if user_match:
                    user = user_match.group(1)

        return {
            "connected": connected,
            "ssid": ssid,
            "ip": ip_addr,
            "rssi": rssi,
            "internet": internet_ok,
            "user": user,
            "raw": lines,
        }

    @allure.step("Read Wi-Fi / system connection status")
    def wifi_status(self, timeout: float = 10.0) -> dict[str, Any]:
        response_markers = ("heap:", "E001", "E002", "E003", "E005", "E099")
        response_marker: str | None = None
        response_lines: list[str] = []
        for attempt in range(2):
            start_idx = len(self.uart_log)
            self.send_command_nowait("status")
            response_marker = self.wait_for_any(
                response_markers,
                timeout=timeout,
                since_index=start_idx,
            )
            response_entries = self.uart_log[start_idx:]
            response_lines = [
                entry[5:]
                for entry in response_entries
                if entry.startswith("RX < ")
            ]
            if response_marker is not None:
                break
            if attempt == 0:
                LOGGER.warning(
                    "Status command emitted no terminal UART marker; retrying "
                    "once. Captured response: %s",
                    response_lines,
                )
        if response_marker is None:
            raise TimeoutError(
                "Status command emitted no terminal UART marker "
                "('heap:' or an explicit command error) after one retry; "
                f"response: {response_lines}"
            )
        if response_marker != "heap:":
            raise RuntimeError(
                "The status command returned an explicit UART error "
                f"{response_marker!r}: {response_lines}"
            )
        status_fields = ("link:", "user:", "heap:")
        missing_fields = [
            field
            for field in status_fields
            if not any(field in line.casefold() for line in response_lines)
        ]
        if missing_fields:
            raise AssertionError(
                "Status response ended with 'heap:' but omitted required fields "
                f"{missing_fields}: {response_lines}"
            )
        allure.attach(
            "\n".join(response_lines),
            name="UART response: status",
            attachment_type=allure.attachment_type.TEXT,
        )
        return self.parse_wifi_status(response_lines)

    @staticmethod
    def wifi_connection_is_valid(status: dict[str, Any]) -> bool:
        if not status.get("connected") or not status.get("ssid"):
            return False
        try:
            address = ipaddress.ip_address(str(status.get("ip")))
        except ValueError:
            return False
        return (
            isinstance(address, ipaddress.IPv4Address)
            and address.packed[0] != 0
            and not (
                address.is_unspecified
                or address.is_loopback
                or address.is_link_local
                or address.is_multicast
                or address.is_reserved
            )
        )

    # --- Distance / Sonar ---

    @allure.step("Perform distance measurement")
    def distance(self, count: int | None = None, timeout: float | None = None) -> list[str]:
        cmd = f"distance {count}" if count is not None else "distance"
        calc_timeout = (count * 0.15 + 1.0) if count is not None else 1.0
        return self.send_command(cmd, timeout=timeout or calc_timeout)

    @allure.step("Start continuous sonar stream with interval {interval_ms} ms")
    def distance_log(self, interval_ms: int | None = None, timeout: float = 3.0) -> list[str]:
        cmd = f"distance log {interval_ms}" if interval_ms is not None else "distance log"
        return self._send_command_wait_for_any(
            cmd,
            (
                "[SONAR] continuous pinging",
                "E001",
                "E003",
                "E004",
                "E005",
                "E701",
                "E702",
                "E703",
                "E704",
                "E705",
                "E711",
                "E099",
            ),
            timeout,
        )

    @allure.step("Stop continuous sonar stream")
    def distance_stop(self, timeout: float = 3.0) -> list[str]:
        return self._send_command_wait_for_any(
            "distance stop",
            (
                "[SONAR] pinging stopped",
                "W710",
                "E001",
                "E003",
                "E004",
                "E005",
                "E701",
                "E702",
                "E703",
                "E099",
            ),
            timeout,
        )

    @allure.step("Read sonar statistics")
    def distance_stats(self, timeout: float = 0.8) -> dict[str, Any]:
        lines = self.send_command("distance stats", timeout=timeout)
        stats: dict[str, Any] = {
            "measurements": 0,
            "errors": 0,
            "min": 0.0,
            "max": 0.0,
            "avg": 0.0,
            "calibration": None,
            "filter": None,
            "alarm": None,
            "raw": lines,
        }
        for line in lines:
            m1 = SONAR_STATS_PATTERN.search(line)
            if m1:
                stats["measurements"] = int(m1.group(1))
                stats["errors"] = int(m1.group(2))
                stats["min"] = float(m1.group(3))
                stats["max"] = float(m1.group(4))
                stats["avg"] = float(m1.group(5))
            m2 = SONAR_CONFIG_PATTERN.search(line)
            if m2:
                stats["calibration"] = float(m2.group(1))
                if m2.group(2) is not None:
                    stats["filter"] = int(m2.group(2))
                elif m2.group(3) is not None:
                    stats["filter"] = 1 if m2.group(3).lower() == "on" else 0
                stats["alarm"] = m2.group(4).lower()
        return stats

    @allure.step("Toggle sonar median filter (enabled={enabled})")
    def distance_filter(self, enabled: bool = True, timeout: float = 0.6) -> list[str]:
        return self.send_command(f"distance filter {'on' if enabled else 'off'}", timeout=timeout)

    @allure.step("Calibrate sonar to reference distance {ref_cm} cm")
    def distance_calibrate(self, ref_cm: int, timeout: float = 0.6) -> list[str]:
        return self.send_command(f"distance calibrate {ref_cm}", timeout=timeout)

    @allure.step("Reset sonar calibration")
    def distance_calibrate_reset(self, timeout: float = 0.6) -> list[str]:
        return self.send_command("distance calibrate reset", timeout=timeout)

    @allure.step("Configure proximity alarm threshold ({threshold})")
    def distance_alarm(self, threshold: int | str, timeout: float = 3.0) -> list[str]:
        marker = "[SONAR] alarm off" if str(threshold).casefold() == "off" else "[SONAR] alarm at"
        return self._send_command_wait_for_any(
            f"distance alarm {threshold}",
            (
                marker,
                "E001",
                "E003",
                "E004",
                "E005",
                "E701",
                "E702",
                "E703",
                "E708",
                "E099",
            ),
            timeout,
        )

    # --- Relay (Valve) ---

    @allure.step("Turn Valve relay OPEN")
    def relay_on(self, timeout: float = 3.0) -> list[str]:
        return self._send_command_wait_for_any(
            "relay on",
            ("[VALVE] OPEN", "W601", "E001", "E003", "E004", "E005", "E602", "E099"),
            timeout,
        )

    @allure.step("Turn Valve relay CLOSED")
    def relay_off(self, timeout: float = 3.0) -> list[str]:
        return self._send_command_wait_for_any(
            "relay off",
            ("[VALVE] CLOSED", "W601", "E001", "E003", "E004", "E005", "E602", "E099"),
            timeout,
        )

    @allure.step("Toggle Valve relay")
    def relay_toggle(self, timeout: float = 3.0) -> list[str]:
        return self._send_command_wait_for_any(
            "relay toggle",
            (
                "[VALVE] OPEN",
                "[VALVE] CLOSED",
                "W601",
                "E001",
                "E003",
                "E004",
                "E005",
                "E602",
                "E099",
            ),
            timeout,
        )

    @allure.step("Read Valve relay status")
    def relay_status(self, timeout: float = 3.0) -> dict[str, Any]:
        start_idx = self.buffer_len()
        self.send_command_nowait("relay status")
        error_markers = ("E001", "E003", "E004", "E005", "E602", "E099")
        status_markers = ("[VALVE] OPEN, auto", "[VALVE] closed, auto")
        matched = self.wait_for_any(
            (*status_markers, *error_markers),
            timeout=timeout,
            since_index=start_idx,
        )
        lines = [
            entry[5:]
            for entry in self.uart_log[start_idx:]
            if entry.startswith("RX < ")
        ]
        if matched is None:
            raise TimeoutError(
                "No relay status UART marker received within "
                f"{timeout} seconds; response: {lines!r}"
            )
        if matched in error_markers:
            raise RuntimeError(
                f"Relay status command returned {matched}; response: {lines!r}"
            )
        for line in reversed(lines):
            match = VALVE_STATUS_PATTERN.search(line)
            if match:
                return {
                    "state": match.group(1).upper(),
                    "auto": match.group(2).lower(),
                    "cycles": int(match.group(3)),
                    "raw": lines,
                }
        raise AssertionError(f"No relay status found in UART response: {lines!r}")

    @allure.step("Pulse Valve relay for {duration_ms} ms")
    def relay_pulse(self, duration_ms: int, timeout: float | None = None) -> list[str]:
        calc_timeout = (duration_ms / 1000.0) + 1.0
        return self._send_command_wait_for_any(
            f"relay pulse {duration_ms}",
            (
                "[VALVE] CLOSED (pulse end)",
                "E001",
                "E003",
                "E004",
                "E005",
                "E602",
                "E603",
                "E604",
                "E099",
            ),
            timeout or calc_timeout,
        )

    @allure.step("Configure Valve relay schedule: on {on_seconds}, off {off_seconds} seconds")
    def relay_schedule(
        self, on_seconds: int, off_seconds: int, timeout: float = 3.0
    ) -> list[str]:
        return self._send_command_wait_for_any(
            f"relay schedule {on_seconds} {off_seconds}",
            ("[VALVE] schedule:", "E001", "E003", "E004", "E005", "E602", "E606", "E099"),
            timeout,
        )

    @allure.step("Stop Valve relay schedule")
    def relay_schedule_stop(self, timeout: float = 3.0) -> list[str]:
        return self._send_command_wait_for_any(
            "relay schedule off",
            ("[VALVE] schedule stopped", "W605", "E001", "E003", "E004", "E005", "E099"),
            timeout,
        )

    @allure.step("Enable automatic Valve relay control (enabled={enabled})")
    def relay_auto(self, enabled: bool, timeout: float = 3.0) -> list[str]:
        return self._send_command_wait_for_any(
            f"relay auto {'on' if enabled else 'off'}",
            (
                f"[VALVE] auto {'on' if enabled else 'off'}",
                "E001",
                "E003",
                "E004",
                "E005",
                "E602",
                "E099",
            ),
            timeout,
        )

    @allure.step("Read Valve relay health")
    def relay_health(self, timeout: float = 3.0) -> list[str]:
        return self._send_command_wait_for_any(
            "relay health",
            ("seal:", "solenoid:", "E001", "E003", "E004", "E005", "E099"),
            timeout,
        )

    # --- Guard ---

    @allure.step("Read Guard status")
    def guard_status(self, timeout: float = 0.6) -> list[str]:
        return self.send_command("guard status", timeout=timeout)

    @allure.step("Set Guard zone to {zone_cm} cm")
    def guard_set_zone(self, zone_cm: int, timeout: float = 0.6) -> list[str]:
        return self.send_command(f"guard zone {zone_cm}", timeout=timeout)

    @allure.step("Arm Guard")
    def guard_arm(self, timeout: float = 0.6) -> list[str]:
        return self.send_command("guard arm", timeout=timeout)

    @allure.step("Disarm Guard using the configured PIN")
    def guard_disarm(self, pin: str, timeout: float = 0.6) -> list[str]:
        return self.send_command(f"guard disarm {pin}", timeout=timeout)

    @allure.step("Trigger Guard panic")
    def guard_panic(self, timeout: float = 0.6) -> list[str]:
        return self.send_command("guard panic", timeout=timeout)

    # --- Alert Center ---

    @allure.step("List CIC alerts")
    def alert_list(self, timeout: float = 0.6) -> list[str]:
        return self.send_command("alert list", timeout=timeout)

    @allure.step("Create a {level} CIC test alert")
    def alert_test(self, level: str, timeout: float = 0.6) -> list[str]:
        return self.send_command(f"alert test {level}", timeout=timeout)

    @allure.step("Acknowledge CIC alert {alert_id}")
    def alert_ack(
        self, alert_id: int | str | None = None, timeout: float = 0.6
    ) -> list[str]:
        command = "alert ack" if alert_id is None else f"alert ack {alert_id}"
        return self.send_command(command, timeout=timeout)

    @allure.step("Clear CIC alert history")
    def alert_clear(self, timeout: float = 0.6) -> list[str]:
        return self.send_command("alert clear", timeout=timeout)

    # --- Logging & Evidence ---

    @allure.step("Attach per-test UART transcript")
    def attach_uart_log(self) -> None:
        allure.attach(
            "\n".join(self.uart_log) or "No UART output was captured.",
            name="UART transcript",
            attachment_type=allure.attachment_type.TEXT,
        )
