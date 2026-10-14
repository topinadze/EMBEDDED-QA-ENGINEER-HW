from __future__ import annotations

import logging
import os
import re
import sys
import time
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
from config.test_config import (
    DEFAULT_WIFI_MISSING_SSID,
    DEFAULT_WIFI_WRONG_PASSWORD,
    WIFI_MISSING_SSID,
    WIFI_MISSING_SSID_ENV,
    WIFI_PASSWORD_ENV,
    WIFI_SSID_ENV,
    WIFI_WRONG_PASSWORD,
    WIFI_WRONG_PASSWORD_ENV,
    resolve_wifi_credentials,
)
from manual_checks import SoftChecks, prepare_manually, verify_manually

ESP32_VIDS = {0x10C4, 0x1A86, 0x0403, 0x303A}
ESP32_DESCRIPTORS = ("cp210", "ch340", "ft232", "esp32", "usb-to-uart", "usb serial")
SUPPORTED_VERSIONS = {"1.3.0", "1.4.0", "1.5.0"}
FIRMWARE_VERSION_KEY = pytest.StashKey[str]()
WIFI_CONNECT_ATTEMPTS = 2
WIFI_CONNECT_RETRY_DELAY_SECONDS = 1.0
WIFI_STATUS_RECOVERY_CHECKS = 3


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
    category = (
        "ota"
        if item.get_closest_marker("ota") is not None
        else "wifi"
        if item.get_closest_marker("wifi") is not None
        else "system"
        if item.get_closest_marker("system") is not None
        else "lamp"
    )
    log_dir = DZ16_DIR / "logs" / "automated" / category / firmware_version
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
    parser.addoption(
        "--wifi-ssid",
        action="store",
        default=None,
        help="Override the configured Wi-Fi SSID for this test run.",
    )
    parser.addoption(
        "--wifi-password",
        action="store",
        default=None,
        help="Override the configured Wi-Fi password for this test run.",
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


def _require_console(pytestconfig: pytest.Config) -> None:
    if pytestconfig.getoption("capture") != "no":
        pytest.fail(
            "Interactive checks require console input; run with '-s -m interactive'."
        )


@pytest.fixture
def manual_check(
    pytestconfig: pytest.Config,
) -> Callable[[str], bool]:
    _require_console(pytestconfig)
    return verify_manually


@pytest.fixture
def manual_prepare(
    pytestconfig: pytest.Config,
) -> Callable[[str], None]:
    _require_console(pytestconfig)
    return prepare_manually


@pytest.fixture
def soft() -> SoftChecks:
    return SoftChecks()


def _snapshot_lamp(driver: DeviceDriver) -> dict[str, Any] | None:
    try:
        return driver.lamp_status()
    except Exception:
        logging.getLogger(__name__).warning("Lamp state snapshot unavailable.")
        return None


def _restore_lamp(
    driver: DeviceDriver,
    snapshot: dict[str, Any] | None,
    elapsed_seconds: float = 0.0,
) -> None:
    """Return the lamp to the state found at test start (settings are persisted by the firmware)."""
    restore_started_at = time.monotonic()
    driver.lamp_set_timer(0, timeout=0.2)
    if snapshot is not None:
        try:
            driver.lamp_set_color(tuple(snapshot["color"]), timeout=0.2)
            driver.lamp_set_brightness(snapshot["brightness"], timeout=0.2)
            driver.lamp_set_mode(snapshot["mode"], timeout=0.2)
        except (KeyError, TypeError):
            logging.getLogger(__name__).warning("Incomplete lamp snapshot: %r", snapshot)
    timer_seconds = snapshot.get("timer_s", 0) if snapshot is not None else 0
    has_timer = isinstance(timer_seconds, int) and timer_seconds > 0

    def remaining_timer() -> int:
        if not isinstance(timer_seconds, int):
            return 0
        total_elapsed = elapsed_seconds + time.monotonic() - restore_started_at
        return max(0, int(timer_seconds - total_elapsed))

    if (
        snapshot is not None
        and snapshot.get("lamp") == "on"
        and has_timer
        and remaining_timer() == 0
    ):
        driver.lamp_off(timeout=0.2)
        return
    if snapshot is not None and snapshot.get("lamp") == "on":
        driver.lamp_on(timeout=0.2)
        if has_timer:
            remaining_seconds = remaining_timer()
            if remaining_seconds:
                driver.lamp_set_timer(remaining_seconds, timeout=0.2)
            else:
                driver.lamp_off(timeout=0.2)
    else:
        driver.lamp_off(timeout=0.2)


@pytest.fixture
def device_driver(request: pytest.FixtureRequest):
    port = request.config.getoption("--port") or _find_esp32_port()
    baudrate = int(request.config.getoption("--baudrate") or 115200)
    driver = DeviceDriver(port=port, baudrate=baudrate)
    driver.open()
    lamp_snapshot = _snapshot_lamp(driver)
    test_started_at = time.monotonic()
    try:
        yield driver
    finally:
        try:
            if (
                driver.is_open
                and request.node.get_closest_marker("ota") is None
                and not getattr(request.node, "wifi_failure_reboot_attempted", False)
            ):
                elapsed_seconds = time.monotonic() - test_started_at
                _restore_lamp(driver, lamp_snapshot, elapsed_seconds)
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


@pytest.fixture
def wifi_ssid(request: pytest.FixtureRequest) -> str:
    ssid, _ = resolve_wifi_credentials(
        ssid_override=request.config.getoption("--wifi-ssid"),
        password_override=request.config.getoption("--wifi-password"),
    )
    if not ssid:
        pytest.skip(
            f"Configure config/wifi_secrets.py or {WIFI_SSID_ENV}, "
            "TEST_WIFI_SSID, or --wifi-ssid to run Wi-Fi station tests."
        )
    return ssid


@pytest.fixture
def wifi_credentials(
    wifi_ssid: str,
    request: pytest.FixtureRequest,
) -> tuple[str, str]:
    _, password = resolve_wifi_credentials(
        ssid_override=wifi_ssid,
        password_override=request.config.getoption("--wifi-password"),
    )
    if not password:
        pytest.skip(
            f"Configure config/wifi_secrets.py or {WIFI_PASSWORD_ENV}, "
            "TEST_WIFI_PASSWORD, or --wifi-password to run credential-based Wi-Fi tests."
        )
    if len(password) < 8:
        pytest.fail("The effective Wi-Fi password must contain at least 8 characters.")
    return wifi_ssid, password


@pytest.fixture
def wrong_wifi_password(request: pytest.FixtureRequest) -> str:
    password = WIFI_WRONG_PASSWORD or DEFAULT_WIFI_WRONG_PASSWORD
    if not password:
        pytest.skip(
            f"Set {WIFI_WRONG_PASSWORD_ENV} to run the invalid-password scenario."
        )
    if len(password) < 8:
        pytest.fail(
            f"The configured {WIFI_WRONG_PASSWORD_ENV} must contain at least 8 characters."
        )
    _, configured_password = resolve_wifi_credentials(
        password_override=request.config.getoption("--wifi-password")
    )
    if configured_password and password == configured_password:
        pytest.fail(
            f"{WIFI_WRONG_PASSWORD_ENV} must differ from the effective valid Wi-Fi password."
        )
    return password


@pytest.fixture
def missing_wifi_ssid() -> str:
    return WIFI_MISSING_SSID or DEFAULT_WIFI_MISSING_SSID


def _connect_wifi_with_configured_credentials(
    device_driver: DeviceDriver,
    initial_status: dict[str, Any],
    ssid: str,
    password: str,
) -> bool:
    if DeviceDriver.wifi_connection_is_valid(initial_status):
        return True
    if ssid and password and len(password) < 8:
        pytest.fail("The effective Wi-Fi password must contain at least 8 characters.")

    status = initial_status
    for attempt in range(1, WIFI_CONNECT_ATTEMPTS + 1):
        if attempt > 1 and DeviceDriver.wifi_connection_is_valid(status):
            return True
        with allure.step(
            f"Establish Wi-Fi connection (attempt {attempt}/{WIFI_CONNECT_ATTEMPTS})"
        ):
            if ssid and password:
                device_driver.wifi_connect(
                    ssid=ssid,
                    password=password,
                    timeout=10.0,
                )
            else:
                device_driver.wifi_connect_saved()
            connected = False
            for status_attempt in range(1, WIFI_STATUS_RECOVERY_CHECKS + 1):
                status = device_driver.wifi_status()
                if DeviceDriver.wifi_connection_is_valid(status):
                    connected = True
                    break
                if status_attempt < WIFI_STATUS_RECOVERY_CHECKS:
                    time.sleep(WIFI_CONNECT_RETRY_DELAY_SECONDS)

        if connected:
            return True

        if attempt < WIFI_CONNECT_ATTEMPTS:
            logging.getLogger(__name__).warning(
                "Wi-Fi connection attempt %d/%d failed; retrying.",
                attempt,
                WIFI_CONNECT_ATTEMPTS,
            )
            device_driver.wifi_disconnect()
            time.sleep(WIFI_CONNECT_RETRY_DELAY_SECONDS)
            status = device_driver.wifi_status()

    return False


@pytest.fixture
def wifi_connected(
    device_driver: DeviceDriver,
    request: pytest.FixtureRequest,
) -> Generator[None, None, None]:
    """
    Ensures an active, valid Wi-Fi connection is established for the test,
    falling back to configured credentials when saved credentials are unavailable.
    """
    initial_status = device_driver.wifi_status()
    was_connected = DeviceDriver.wifi_connection_is_valid(initial_status)
    ssid, password = resolve_wifi_credentials(
        ssid_override=request.config.getoption("--wifi-ssid"),
        password_override=request.config.getoption("--wifi-password"),
    )

    if was_connected:
        yield
        return
    try:
        if not _connect_wifi_with_configured_credentials(
            device_driver,
            initial_status,
            ssid,
            password,
        ):
            if ssid and password:
                pytest.fail(
                    "Could not establish a valid Wi-Fi connection using configured "
                    f"credentials after {WIFI_CONNECT_ATTEMPTS} attempts. "
                    "Verify the access point and local Wi-Fi configuration."
                )
            pytest.skip(
                f"Could not connect using saved or configured Wi-Fi credentials after "
                f"{WIFI_CONNECT_ATTEMPTS} attempts. "
                "Configure local secrets, environment variables, or run options."
            )
        yield
    finally:
        if getattr(request.node, "ota_lock_reboot_attempted", False) is not True:
            device_driver.wifi_disconnect()


@pytest.fixture
def reboot_after_ota_lock(
    device_driver: DeviceDriver,
    request: pytest.FixtureRequest,
) -> Generator[None, None, None]:
    """Reboot after BUG-06 leaves the OTA operation locked."""
    yield
    lock_error = "[ota] error: update already in progress"
    if not any(lock_error in line.casefold() for line in device_driver.uart_log):
        return

    setattr(request.node, "ota_lock_reboot_attempted", True)
    with allure.step("Reboot device to clear the locked OTA operation"):
        if not device_driver.reboot(timeout=30.0):
            pytest.fail(
                "BUG-06 left OTA locked and the recovery reboot did not return "
                "the device to the ready prompt."
            )
