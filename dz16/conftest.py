from __future__ import annotations

import logging
import re
import sys
from collections.abc import Callable, Generator
from datetime import datetime
from pathlib import Path
from typing import Any

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
FIRMWARE_VERSION_KEY = pytest.StashKey[str]()


def _debug_logging_enabled(config: pytest.Config) -> bool:
    level = config.getoption("log_cli_level")
    if level is None:
        level = config.getini("log_cli_level")

    if isinstance(level, str):
        normalized_level = level.upper()
        level = (
            int(normalized_level)
            if normalized_level.isdecimal()
            else getattr(logging, normalized_level, None)
        )
    return isinstance(level, int) and level <= logging.DEBUG


def _save_automated_uart_log(
    driver: DeviceDriver, item: pytest.Item, firmware_version: str
) -> Path:
    log_dir = DZ16_DIR / "logs" / "automated" / "lamp" / firmware_version
    log_dir.mkdir(parents=True, exist_ok=True)

    safe_test_name = re.sub(r"[^A-Za-z0-9._-]+", "_", item.name).strip("._")
    captured_at = datetime.now().astimezone()
    base_name = f"{captured_at:%Y%m%d}-{safe_test_name or 'test'}"
    log_path = log_dir / f"{base_name}.txt"
    previous_path = log_dir / f"{base_name}.prev.txt"
    # Keep at most two logs per test and date: the latest and the one before it.
    if log_path.exists():
        log_path.replace(previous_path)
    header = (
        f"Test: {item.nodeid}\n"
        f"Firmware: {firmware_version}\n"
        f"Captured: {captured_at.isoformat()}\n\n"
    )
    log_path.write_text(
        header + ("\n".join(driver.uart_log) or "No UART output was captured.") + "\n",
        encoding="utf-8",
    )
    return log_path


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


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[Any]
) -> Generator[None, Any, None]:
    outcome = yield
    report = outcome.get_result()
    setattr(item, f"rep_{report.when}", report)


@pytest.fixture
def manual_check(
    pytestconfig: pytest.Config,
) -> Callable[[str], bool]:
    if pytestconfig.getoption("capture") != "no":
        pytest.fail(
            "Interactive checks require console input; run with '-s -m interactive'."
        )
    return verify_manually


def _snapshot_lamp(driver: DeviceDriver) -> dict[str, Any] | None:
    try:
        return driver.lamp_status()
    except Exception:
        logging.getLogger(__name__).warning("Lamp state snapshot unavailable.")
        return None


def _restore_lamp(driver: DeviceDriver, snapshot: dict[str, Any] | None) -> None:
    """Return the lamp to the state found at test start (settings are persisted by the firmware)."""
    driver.lamp_set_timer(0, timeout=0.2)
    if snapshot is not None:
        try:
            driver.lamp_set_color(tuple(snapshot["color"]), timeout=0.2)
            driver.lamp_set_brightness(snapshot["brightness"], timeout=0.2)
            driver.lamp_set_mode(snapshot["mode"], timeout=0.2)
        except (KeyError, TypeError):
            logging.getLogger(__name__).warning("Incomplete lamp snapshot: %r", snapshot)
    if snapshot is not None and snapshot.get("lamp") == "on":
        driver.lamp_on(timeout=0.2)
    else:
        driver.lamp_off(timeout=0.2)


@pytest.fixture
def device_driver(request: pytest.FixtureRequest):
    port = request.config.getoption("--port") or _find_esp32_port()
    driver = DeviceDriver(port=port, baudrate=request.config.getoption("--baudrate"))
    driver.open()
    lamp_snapshot = _snapshot_lamp(driver)
    try:
        yield driver
    finally:
        try:
            if driver.is_open and not getattr(
                request.node, "wifi_failure_reboot_attempted", False
            ):
                _restore_lamp(driver, lamp_snapshot)
        finally:
            try:
                driver.attach_uart_log()
            finally:
                try:
                    if _debug_logging_enabled(request.config):
                        firmware_version = request.node.stash.get(
                            FIRMWARE_VERSION_KEY, "unknown"
                        )
                        log_path = _save_automated_uart_log(
                            driver, request.node, firmware_version
                        )
                        logging.getLogger(__name__).info(
                            "Saved UART test log: %s", log_path
                        )
                finally:
                    driver.close()


@pytest.fixture
def firmware_version(
    device_driver: DeviceDriver, request: pytest.FixtureRequest
) -> str:
    lines = device_driver.send_command("version")
    version = device_driver.get_firmware_version(lines)
    request.node.stash[FIRMWARE_VERSION_KEY] = version
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
