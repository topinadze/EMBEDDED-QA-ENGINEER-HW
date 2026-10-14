from __future__ import annotations

import ipaddress
import json
import logging
import re
import time
from typing import Any

import allure
import serial

LOGGER = logging.getLogger(__name__)
ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
VERSION_PATTERN = re.compile(
    r"(?:app version:\s*|fw:\s*v?)(\d+\.\d+\.\d+)", re.IGNORECASE
)
JSON_OBJECT_PATTERN = re.compile(r"\{.*\}")
WIFI_STATE_PATTERN = re.compile(
    r"\bWiFi\s*:\s*(connected|disconnected)\b", re.IGNORECASE
)
WIFI_SCAN_ROW_PATTERN = re.compile(r"\[\s*\d+\s*\]\s*(.+)$")
WIFI_RSSI_PATTERN = re.compile(r"\bRSSI\s*:\s*(-?\d+)\s*dBm\b|(-?\d+)\s*dBm\b", re.I)
WIFI_CHANNEL_PATTERN = re.compile(r"\b(?:channel|ch)\s*:\s*(\d+)\b", re.I)
OTA_TERMINAL_MARKERS = (
    "[OTA] self-check passed",
    "[OTA] self-check FAILED",
    "[OTA] failed:",
    "[OTA] error:",
    "[OTA] check failed:",
    "[OTA] downgrade blocked:",
    "[OTA] already up to date",
    "[OTA] up to date",
    "=== OTA Update Complete. Restarting",
)


class DeviceDriver:
    """UART driver for the station_WiFi ESP32-S3 Smart Lamp firmware."""

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

    def _require_open_serial(self) -> serial.Serial:
        if self.serial is None or not self.serial.is_open:
            raise RuntimeError("Serial port is not open. Call open() first.")
        return self.serial

    def _record(self, direction: str, text: str) -> None:
        for value in sorted(self._sensitive_uart_values, key=len, reverse=True):
            text = text.replace(value, "[REDACTED]")
        line = f"{direction} {text}"
        self.uart_log.append(line)
        LOGGER.debug("%s", line)

    def ensure_ends_with_rn(self, command: str) -> str:
        """Return a command terminated by exactly one CRLF."""
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
                        lines.append(line)
            else:
                time.sleep(0.01)

        trailing = ANSI_ESCAPE.sub(
            "", self._receive_buffer.replace("\r", "")
        ).strip()
        if trailing:
            self._record("RX <", trailing)
            lines.append(trailing)
            self._receive_buffer = ""

        return lines

    @allure.step("Read UART output for up to {timeout} seconds")
    def read_for(self, timeout: float) -> list[str]:
        return self._read_for(timeout)

    @allure.step("UART command: {command}")
    def send_command(self, command: str, timeout: float = 0.6) -> list[str]:
        connection = self._require_open_serial()
        self._record("TX >", command)

        # Keep pending input so asynchronous timer and reboot messages are not discarded.
        connection.write(self.ensure_ends_with_rn(command).encode("utf-8"))
        connection.flush()
        lines = self._read_for(timeout)

        if lines:
            allure.attach(
                "\n".join(lines),
                name=f"UART response: {command}",
                attachment_type=allure.attachment_type.TEXT,
            )
        return lines

    def _send_line(self, line: str, sensitive: bool = False) -> None:
        connection = self._require_open_serial()
        if sensitive and line:
            self._sensitive_uart_values.add(line)
        self._record("TX >", "[REDACTED]" if sensitive and line else line)
        connection.write(self.ensure_ends_with_rn(line).encode("utf-8"))
        connection.flush()

    @allure.step("Scan nearby Wi-Fi networks")
    def wifi_scan(self, timeout: float = 10.0) -> list[str]:
        lines = self.send_command("scan", timeout=timeout)
        return [row["ssid"] for row in self.parse_wifi_scan(lines)]

    @staticmethod
    def parse_wifi_scan(lines: list[str]) -> list[dict[str, str | int | None]]:
        access_points: list[dict[str, str | int | None]] = []
        for line in lines:
            row_match = WIFI_SCAN_ROW_PATTERN.search(line)
            if row_match is None:
                continue

            row = row_match.group(1).strip()
            if row.casefold().startswith("ssid:"):
                row = row.split(":", 1)[1].strip()

            metadata_matches = [
                match.start()
                for pattern in (WIFI_RSSI_PATTERN, WIFI_CHANNEL_PATTERN)
                if (match := pattern.search(row)) is not None
            ]
            ssid = row[: min(metadata_matches)].strip() if metadata_matches else row
            if not ssid:
                continue

            rssi_match = WIFI_RSSI_PATTERN.search(row)
            channel_match = WIFI_CHANNEL_PATTERN.search(row)
            rssi_text = (
                next(group for group in rssi_match.groups() if group is not None)
                if rssi_match is not None
                else None
            )
            access_points.append(
                {
                    "ssid": ssid,
                    "rssi": int(rssi_text) if rssi_text is not None else None,
                    "channel": (
                        int(channel_match.group(1))
                        if channel_match is not None
                        else None
                    ),
                }
            )
        return access_points

    @allure.step("Connect to Wi-Fi SSID '{ssid}' (password redacted)")
    def wifi_connect(
        self,
        ssid: str = "",
        password: str = "",
        timeout: float = 10.0,
    ) -> bool:
        self.last_wifi_connect_duration: float | None = None
        prompts = ("enter ssid", "number from list", "enter password")
        initial_lines = self.send_command("connect", timeout=0.2)
        prompt = next(
            (
                expected
                for expected in prompts
                if any(expected in line.casefold() for line in initial_lines)
            ),
            None,
        )
        if prompt is None:
            prompt = self.wait_for_any(prompts, timeout=8.0)
        if prompt is None:
            return False

        if "password" in prompt.casefold():
            if not password:
                return False
            self._send_line(password, sensitive=True)
        else:
            self._send_line(ssid)
            if ssid:
                password_prompt = self.wait_for_any(
                    ("enter password", "password:"), timeout=5.0
                )
                if password_prompt is None:
                    return False
                self._send_line(password, sensitive=True)

        connect_started = time.monotonic()
        deadline = connect_started + timeout
        saw_ip = False
        saw_connected = False
        while time.monotonic() < deadline:
            lines = self._read_for(min(0.2, deadline - time.monotonic()))
            output = "\n".join(lines).casefold()
            if "password too short" in output:
                return False
            if (
                "failed to connect to ssid" in output
                or "connection timeout" in output
                or "connect to the ap fail" in output
            ):
                return False

            saw_ip = saw_ip or "got ip:" in output
            saw_connected = saw_connected or "successfully connected to ssid:" in output
            if saw_ip and saw_connected:
                self.last_wifi_connect_duration = time.monotonic() - connect_started
                return True
        return False

    @staticmethod
    def parse_wifi_status(lines: list[str]) -> dict[str, Any]:
        states = [
            match.group(1).casefold()
            for line in lines
            if (match := WIFI_STATE_PATTERN.search(line)) is not None
        ]
        ssid: str | None = None
        ip_address: str | None = None
        rssi: int | None = None

        for line in lines:
            ssid_match = re.search(r"\bSSID\s*:\s*(.*?)\s*$", line, re.IGNORECASE)
            if ssid_match is not None:
                ssid = ssid_match.group(1).strip() or None
            ip_match = re.search(
                r"\bIP(?:v4)?\s*:\s*((?:\d{1,3}\.){3}\d{1,3})\b",
                line,
                re.IGNORECASE,
            )
            if ip_match is not None:
                ip_address = ip_match.group(1)
            rssi_match = re.search(r"\bRSSI\s*:\s*(-?\d+)\s*dBm\b", line, re.I)
            if rssi_match is not None:
                rssi = int(rssi_match.group(1))

        return {
            "connected": bool(states and states[-1] == "connected"),
            "ssid": ssid,
            "ip": ip_address,
            "rssi": rssi,
            "raw": lines,
        }

    @allure.step("Read Wi-Fi connection status")
    def wifi_status(self, timeout: float = 2.0) -> dict[str, Any]:
        return self.parse_wifi_status(self.send_command("status", timeout=timeout))

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
            and status.get("rssi") is not None
        )

    @allure.step("Connect to the saved Wi-Fi network")
    def wifi_connect_saved(self, timeout: float = 10.0) -> bool:
        if self.wifi_connection_is_valid(self.wifi_status()):
            return True
        if not self.wifi_connect(ssid="", password="", timeout=timeout):
            return False
        return self.wifi_connection_is_valid(self.wifi_status())

    @allure.step("Disconnect from Wi-Fi")
    def wifi_disconnect(self, timeout: float = 2.0) -> list[str]:
        return self.send_command("disconnect", timeout=timeout)

    @allure.step("Wait for any UART message from {patterns}")
    def wait_for_any(self, patterns: tuple[str, ...], timeout: float) -> str | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            lines = self._read_for(min(0.2, deadline - time.monotonic()))
            for line in lines:
                for pattern in patterns:
                    if pattern.casefold() in line.casefold():
                        return pattern
        return None

    @allure.step("Run OTA command '{command}' and wait for a terminal result")
    def run_ota(self, command: str, timeout: float = 180.0) -> list[str]:
        if timeout <= 0:
            raise ValueError("OTA timeout must be greater than zero.")
        lines = self.send_command(command, timeout=min(0.2, timeout))
        deadline = time.monotonic() + timeout

        def has_terminal_result() -> bool:
            output = "\n".join(lines).casefold()
            return any(marker.casefold() in output for marker in OTA_TERMINAL_MARKERS)

        while not has_terminal_result() and time.monotonic() < deadline:
            lines.extend(self._read_for(min(0.2, deadline - time.monotonic())))

        if not has_terminal_result():
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
        output = "\n".join(lines).casefold()
        return any(
            marker in output
            for marker in (
                "couldn't get hostname",
                "getaddrinfo()",
                "failed to open a new connection",
                "connection failed, sock",
                "[ota] check failed: cannot read stable.txt",
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
                if not self.wifi_connect_saved():
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

    @allure.step("Reboot the ESP32")
    def reboot(self, timeout: float = 30.0) -> bool:
        connection = self._require_open_serial()
        self._record("TX >", "reboot")
        connection.write(b"reboot\n")
        connection.flush()
        # Allow the MCU to initiate hardware/software restart and purge pre-reset buffer residue
        time.sleep(0.3)
        self._receive_buffer = ""
        connection.reset_input_buffer()
        return self.wait_for("ready", timeout=timeout)

    @allure.step("Turn Smart Lamp on")
    def lamp_on(self, timeout: float = 0.6) -> list[str]:
        return self.send_command("lamp on", timeout=timeout)

    @allure.step("Turn Smart Lamp off")
    def lamp_off(self, timeout: float = 0.6) -> list[str]:
        return self.send_command("lamp off", timeout=timeout)

    @allure.step("Set Smart Lamp color to {color}")
    def lamp_set_color(
        self, color: str | tuple[int, int, int], timeout: float = 0.6
    ) -> list[str]:
        value = color if isinstance(color, str) else " ".join(map(str, color))
        return self.send_command(f"lamp color {value}", timeout=timeout)

    @allure.step("Set Smart Lamp brightness to {brightness}%")
    def lamp_set_brightness(self, brightness: int, timeout: float = 0.6) -> list[str]:
        return self.send_command(f"lamp brightness {brightness}", timeout=timeout)

    @allure.step("Set Smart Lamp mode to '{mode}'")
    def lamp_set_mode(self, mode: str, timeout: float = 0.6) -> list[str]:
        return self.send_command(f"lamp mode {mode}", timeout=timeout)

    @allure.step("Set Smart Lamp auto-off timer to {seconds} seconds")
    def lamp_set_timer(self, seconds: int, timeout: float = 0.6) -> list[str]:
        return self.send_command(f"lamp timer {seconds}", timeout=timeout)

    @allure.step("Save Smart Lamp scene {scene}")
    def lamp_save_scene(self, scene: int, timeout: float = 0.6) -> list[str]:
        return self.send_command(f"lamp scene save {scene}", timeout=timeout)

    @allure.step("Load Smart Lamp scene {scene}")
    def lamp_load_scene(self, scene: int, timeout: float = 0.6) -> list[str]:
        return self.send_command(f"lamp scene load {scene}", timeout=timeout)

    @allure.step("Read Smart Lamp status")
    def lamp_status(self, timeout: float = 0.6) -> dict[str, Any]:
        lines = self.send_command("lamp status", timeout=timeout)
        return self.parse_lamp_status(lines)

    @allure.step("Wait for UART text '{text}' (timeout: {timeout} seconds)")
    def wait_for(
        self, text: str, timeout: float, since_index: int | None = None
    ) -> bool:
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

    @allure.step("Wait for all UART texts {texts} (timeout: {timeout} seconds)")
    def wait_for_all(
        self,
        texts: list[str] | tuple[str, ...],
        timeout: float,
        since_index: int | None = None,
    ) -> dict[str, bool]:
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

    @allure.step("Parse lamp status JSON from UART response")
    def parse_lamp_status(self, lines: list[str]) -> dict[str, Any]:
        for line in reversed(lines):
            match = JSON_OBJECT_PATTERN.search(line)
            if match:
                value = json.loads(match.group(0))
                if isinstance(value, dict) and "lamp" in value:
                    return value
        raise AssertionError(f"No lamp status JSON in UART response: {lines!r}")

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

    @allure.step("Turn relay ON")
    def relay_on(self, timeout: float = 0.6) -> list[str]:
        return self.send_command("relay on", timeout=timeout)

    @allure.step("Turn relay OFF")
    def relay_off(self, timeout: float = 0.6) -> list[str]:
        return self.send_command("relay off", timeout=timeout)

    @allure.step("Turn LED ON (white)")
    def led_on(self, timeout: float = 0.6) -> list[str]:
        return self.send_command("led on", timeout=timeout)

    @allure.step("Turn LED OFF")
    def led_off(self, timeout: float = 0.6) -> list[str]:
        return self.send_command("led off", timeout=timeout)

    @allure.step("Set LED to auto mode (Wi-Fi status indication)")
    def led_auto(self, timeout: float = 0.6) -> list[str]:
        return self.send_command("led auto", timeout=timeout)

    @allure.step("Start smooth RGB cycle for 5 seconds")
    def led_rgb(self, timeout: float = 6.0) -> list[str]:
        return self.send_command("led rgb", timeout=timeout)

    @allure.step("Read system info")
    def sysinfo(self, timeout: float = 0.6) -> list[str]:
        return self.send_command("sysinfo", timeout=timeout)

    @allure.step("Read chip temperature")
    def temp(self, timeout: float = 0.6) -> list[str]:
        return self.send_command("temp", timeout=timeout)

    @allure.step("Read sensor status")
    def sensor_status(self, timeout: float = 0.6) -> list[str]:
        return self.send_command("sensor status", timeout=timeout)

    @allure.step("Measure distance for {seconds} seconds")
    def measure_distance(
        self, seconds: int | None = None, timeout: float | None = None
    ) -> list[str]:
        cmd = f"distance {seconds}" if seconds is not None else "distance"
        calc_timeout = (seconds + 2.0) if seconds is not None else 3.0
        return self.send_command(cmd, timeout=timeout or calc_timeout)

    @allure.step("Send Enter to stop continuous distance measurement")
    def stop_continuous_measurement(self, timeout: float = 0.5) -> list[str]:
        return self.send_command("", timeout=timeout)

    @staticmethod
    def parse_chip_temperature(lines: list[str]) -> float | None:
        text = "\n".join(lines)
        match = re.search(
            r"(?:chip temperature|temp(?:erature)?)\s*:\s*([-+]?\d*(?:\.\d+|\d+))\s*c",
            text,
            re.I,
        )
        if match:
            return float(match.group(1))
        return None

    @staticmethod
    def parse_sensor_status(lines: list[str]) -> dict[str, Any]:
        result: dict[str, Any] = {
            "distance": None,
            "relay": None,
            "led": None,
            "wifi": None,
            "temperature": None,
            "raw": lines,
        }
        text = "\n".join(lines)
        dist_match = re.search(
            r"distance\s*:\s*([-+]?\d*(?:\.\d+|\d+))\s*cm", text, re.I
        )
        if dist_match:
            result["distance"] = float(dist_match.group(1))
        elif re.search(r"distance\s*:\s*sensor timeout", text, re.I):
            result["distance"] = "timeout"

        relay_match = re.search(r"relay\s*:\s*(on|off)", text, re.I)
        if relay_match:
            result["relay"] = relay_match.group(1).upper()

        led_match = re.search(r"led\s*:\s*([^\r\n,]+)", text, re.I)
        if led_match:
            result["led"] = led_match.group(1).strip()

        wifi_match = re.search(r"wifi\s*:\s*(connected|disconnected)", text, re.I)
        if wifi_match:
            result["wifi"] = wifi_match.group(1).lower()

        temp_match = re.search(
            r"temp(?:erature)?\s*:\s*([-+]?\d*(?:\.\d+|\d+))\s*c", text, re.I
        )
        if temp_match:
            result["temperature"] = float(temp_match.group(1))

        return result

    @allure.step("Attach per-test UART transcript")
    def attach_uart_log(self) -> None:
        allure.attach(
            "\n".join(self.uart_log) or "No UART output was captured.",
            name="UART transcript",
            attachment_type=allure.attachment_type.TEXT,
        )
