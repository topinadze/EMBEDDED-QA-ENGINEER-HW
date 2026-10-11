from __future__ import annotations

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


class DeviceDriver:
    """UART driver for the station_WiFi ESP32-S3 Smart Lamp firmware."""

    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 0.1) -> None:
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.serial: serial.Serial | None = None
        self.uart_log: list[str] = []
        self._receive_buffer = ""

    @property
    def is_open(self) -> bool:
        return self.serial is not None and self.serial.is_open

    def _require_open_serial(self) -> serial.Serial:
        if self.serial is None or not self.serial.is_open:
            raise RuntimeError("Serial port is not open. Call open() first.")
        return self.serial

    def _record(self, direction: str, text: str) -> None:
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
    def wait_for(self, text: str, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            lines = self._read_for(min(0.2, deadline - time.monotonic()))
            if any(text.casefold() in line.casefold() for line in lines):
                return True
        return False

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

    @allure.step("Attach per-test UART transcript")
    def attach_uart_log(self) -> None:
        allure.attach(
            "\n".join(self.uart_log) or "No UART output was captured.",
            name="UART transcript",
            attachment_type=allure.attachment_type.TEXT,
        )
