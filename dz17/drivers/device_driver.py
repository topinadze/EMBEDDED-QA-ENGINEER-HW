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
    def version(self, timeout: float = 10.0) -> str:
        start_idx = len(self.uart_log)
        self.send_command_nowait("version")
        version_phrases = ("fw v", "fw:", "version:", "version ", "sentry_fw7_")
        version_response = self.wait_for_any(
            version_phrases,
            timeout=timeout,
            since_index=start_idx,
        )
        if version_response is None:
            raise TimeoutError(
                "Timed out waiting for a supported firmware version response "
                f"({', '.join(version_phrases)})."
            )
        lines = [
            entry[5:]
            for entry in self.uart_log[start_idx:]
            if entry.startswith("RX < ")
        ]
        return self.get_firmware_version(lines)

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

        if "password:" in prompt.casefold():
            self._send_line(password, sensitive=True)
        else:
            self._send_line(ssid)
            if ssid:
                password_prompt = self.wait_for("password:", timeout=6.0)
                if not password_prompt:
                    return False
                self._send_line(password, sensitive=True)

        deadline = time.monotonic() + timeout
        saw_ip = False
        saw_connected = False
        while time.monotonic() < deadline:
            lines = self._read_for(min(0.2, deadline - time.monotonic()))
            output = "\n".join(lines).casefold()
            if "password too short" in output or "wrong password" in output or "e101" in output or "e112" in output:
                return False
            if "got ip" in output or "sta ip:" in output:
                saw_ip = True
            if "connected to '" in output or "wifi:connected" in output:
                saw_connected = True
            if saw_ip and saw_connected:
                return True
        return False

    @allure.step("Reconnect to saved Wi-Fi network")
    def wifi_reconnect(self, timeout: float = 12.0) -> bool:
        start_idx = len(self.uart_log)
        self.send_command_nowait("reconnect")
        deadline = time.monotonic() + timeout
        saw_ip = False
        saw_connected = False
        while time.monotonic() < deadline:
            output = "\n".join(self.uart_log[start_idx:]).casefold()
            if "already connected" in output or "w114" in output:
                return True
            saw_ip = saw_ip or "got ip" in output or "sta ip:" in output
            saw_connected = saw_connected or "connected to '" in output
            if saw_ip and saw_connected:
                return True

            lines = self._read_for(min(0.2, deadline - time.monotonic()))
            combined = "\n".join(lines).casefold()
            if "got ip" in combined or "sta ip:" in combined:
                saw_ip = True
            if "connected to '" in combined:
                saw_connected = True
            if saw_ip and saw_connected:
                return True
            if "already connected" in combined or "w114" in combined:
                return True
        return saw_ip and saw_connected

    @allure.step("Disconnect from Wi-Fi")
    def wifi_disconnect(self, timeout: float = 1.0) -> list[str]:
        return self.send_command("disconnect", timeout=timeout)

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
        start_idx = len(self.uart_log)
        self.send_command_nowait("status")
        status_phrases = ("link:", "user:", "heap:")
        received_phrases = self.wait_for_all(
            status_phrases,
            timeout=timeout,
            since_index=start_idx,
        )
        missing_phrases = [
            phrase for phrase, received in received_phrases.items() if not received
        ]
        if missing_phrases:
            raise TimeoutError(
                "Timed out waiting for complete Wi-Fi status fields: "
                f"{', '.join(missing_phrases)}."
            )
        response_lines = [
            entry[5:]
            for entry in self.uart_log[start_idx:]
            if entry.startswith("RX < ")
        ]
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
    def distance_log(self, interval_ms: int | None = None, timeout: float = 0.6) -> list[str]:
        cmd = f"distance log {interval_ms}" if interval_ms is not None else "distance log"
        return self.send_command(cmd, timeout=timeout)

    @allure.step("Stop continuous sonar stream")
    def distance_stop(self, timeout: float = 1.0) -> list[str]:
        return self.send_command("distance stop", timeout=timeout)

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
    def distance_alarm(self, threshold: int | str, timeout: float = 0.6) -> list[str]:
        return self.send_command(f"distance alarm {threshold}", timeout=timeout)

    # --- Relay (Valve) ---

    @allure.step("Turn Valve relay OPEN")
    def relay_on(self, timeout: float = 0.6) -> list[str]:
        return self.send_command("relay on", timeout=timeout)

    @allure.step("Turn Valve relay CLOSED")
    def relay_off(self, timeout: float = 0.6) -> list[str]:
        return self.send_command("relay off", timeout=timeout)

    @allure.step("Toggle Valve relay")
    def relay_toggle(self, timeout: float = 0.6) -> list[str]:
        return self.send_command("relay toggle", timeout=timeout)

    @allure.step("Read Valve relay status")
    def relay_status(self, timeout: float = 0.6) -> dict[str, Any]:
        lines = self.send_command("relay status", timeout=timeout)
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
        return self.send_command(f"relay pulse {duration_ms}", timeout=timeout or calc_timeout)

    @allure.step("Configure Valve relay schedule: on {on_seconds}, off {off_seconds} seconds")
    def relay_schedule(self, on_seconds: int, off_seconds: int, timeout: float = 0.6) -> list[str]:
        return self.send_command(
            f"relay schedule {on_seconds} {off_seconds}", timeout=timeout
        )

    @allure.step("Stop Valve relay schedule")
    def relay_schedule_stop(self, timeout: float = 0.6) -> list[str]:
        return self.send_command("relay schedule off", timeout=timeout)

    @allure.step("Enable automatic Valve relay control (enabled={enabled})")
    def relay_auto(self, enabled: bool, timeout: float = 0.6) -> list[str]:
        return self.send_command(f"relay auto {'on' if enabled else 'off'}", timeout=timeout)

    @allure.step("Read Valve relay health")
    def relay_health(self, timeout: float = 0.6) -> list[str]:
        return self.send_command("relay health", timeout=timeout)

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
