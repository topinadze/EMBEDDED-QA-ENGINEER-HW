from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import allure
import pytest
import serial.tools.list_ports

DZ16_DIR = Path(__file__).resolve().parent
if str(DZ16_DIR) not in sys.path:
    sys.path.insert(0, str(DZ16_DIR))

from drivers.device_driver import DeviceDriver
from manual_checks import verify_manually

ESP32_VIDS = {0x10C4, 0x1A86, 0x0403, 0x303A}
ESP32_DESCRIPTORS = ("cp210", "ch340", "ft232", "esp32", "usb-to-uart", "usb serial")
SUPPORTED_VERSIONS = {"1.3.0", "1.4.0", "1.5.0"}


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--port",
        action="store",
        default=None,
        help="ESP32 UART port (for example COM4); otherwise detect a unique ESP32 port.",
    )
    parser.addoption(
        "--baudrate",
        action="store",
        type=int,
        default=115200,
        help="UART baud rate (default: 115200).",
    )
    parser.addoption(
        "--expected-fw-version",
        action="store",
        choices=sorted(SUPPORTED_VERSIONS),
        default=None,
        help="Fail if the connected board is not running this firmware version.",
    )


def _find_esp32_port() -> str:
    ports = list(serial.tools.list_ports.comports())
    candidates = [
        port
        for port in ports
        if port.vid in ESP32_VIDS
        or any(
            descriptor in f"{port.description or ''} {port.manufacturer or ''}".casefold()
            for descriptor in ESP32_DESCRIPTORS
        )
    ]
    if len(candidates) == 1:
        return candidates[0].device
    if not candidates:
        pytest.fail("No ESP32 serial port detected; pass --port COMx explicitly.")
    pytest.fail(
        "Multiple ESP32-like serial ports detected; pass --port COMx explicitly: "
        + ", ".join(port.device for port in candidates)
    )


def pytest_runtest_setup(item: pytest.Item) -> None:
    if (
        item.get_closest_marker("interactive") is not None
        and item.config.getoption("capture") != "no"
    ):
        pytest.fail(
            "Interactive checks require console input; run with '-s -m interactive'."
        )


@pytest.fixture
def manual_check(
    pytestconfig: pytest.Config,
) -> Callable[[str], bool]:
    if pytestconfig.getoption("capture") != "no":
        pytest.fail(
            "Interactive checks require console input; run with '-s -m interactive'."
        )
    return verify_manually


@pytest.fixture
def device_driver(request: pytest.FixtureRequest):
    port = request.config.getoption("--port") or _find_esp32_port()
    driver = DeviceDriver(port=port, baudrate=request.config.getoption("--baudrate"))
    driver.open()
    try:
        yield driver
    finally:
        try:
            if driver.is_open:
                driver.lamp_set_timer(0, timeout=0.2)
                driver.lamp_off(timeout=0.2)
        finally:
            try:
                driver.attach_uart_log()
            finally:
                driver.close()


@pytest.fixture
def firmware_version(
    device_driver: DeviceDriver, request: pytest.FixtureRequest
) -> str:
    lines = device_driver.send_command("version")
    version = device_driver.get_firmware_version(lines)
    expected = request.config.getoption("--expected-fw-version")
    if expected is not None and version != expected:
        pytest.fail(f"Expected firmware {expected}, but device reports {version}.")
    if version not in SUPPORTED_VERSIONS:
        pytest.fail(
            f"HW-16 automated lamp verification supports {', '.join(sorted(SUPPORTED_VERSIONS))}; "
            f"device reports {version}."
        )
    allure.dynamic.label("firmware_version", version)
    return version
