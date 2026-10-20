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

DZ17_DIR = Path(__file__).resolve().parent
if str(DZ17_DIR) not in sys.path:
    sys.path.insert(0, str(DZ17_DIR))

from drivers.device_driver import DeviceDriver
from config.test_config import (
    DEFAULT_WIFI_MISSING_SSID,
    DEFAULT_WIFI_WRONG_PASSWORD,
    APP_PASSWORD_ENV,
    APP_USER_ENV,
    WIFI_MISSING_SSID,
    WIFI_MISSING_SSID_ENV,
    WIFI_PASSWORD_ENV,
    WIFI_SSID_ENV,
    WIFI_WRONG_PASSWORD,
    WIFI_WRONG_PASSWORD_ENV,
    resolve_account_credentials,
    resolve_wifi_credentials,
)
from manual_checks import (
    SoftChecks,
    ask_to_continue_measurements,
    enter_reference_distance,
    prepare_manually,
    verify_manually,
)
from tests.lamp_test_helpers import LampState, cleanup_lamp_test_state

ESP32_VIDS = {0x10C4, 0x1A86, 0x0403, 0x303A}
ESP32_DESCRIPTORS = ("cp210", "ch340", "ch343", "ft232", "esp32", "usb-to-uart", "usb serial")
SUPPORTED_VERSIONS = {"2.1.0", "2.3.0"}
FIRMWARE_VERSION_KEY = pytest.StashKey[str]()
LAMP_STATE_FIXTURE_ACTIVE = pytest.StashKey[bool]()
WIFI_STATUS_ATTEMPTS = 3
IDENTITY_ATTEMPTS = 3


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
        "buttons"
        if item.get_closest_marker("buttons") is not None
        else "distance"
        if item.get_closest_marker("distance") is not None
        else "wifi"
        if item.get_closest_marker("wifi") is not None
        else "relay"
        if item.get_closest_marker("relay") is not None
        else "guard"
        if item.get_closest_marker("guard") is not None
        else "alert"
        if item.get_closest_marker("alert") is not None
        else "lamp"
    )
    log_dir = DZ17_DIR / "logs" / "automated" / category / firmware_version
    log_dir.mkdir(parents=True, exist_ok=True)

    safe_test_name = re.sub(r"[^A-Za-z0-9._-]+", "_", item.name).strip("._")
    safe_test_name = safe_test_name or "test"
    for pattern in (
        f"*-{safe_test_name}.txt",
        f"*-{safe_test_name}.prev.txt",
    ):
        for old_log in log_dir.glob(pattern):
            old_log.unlink()

    captured_at = datetime.now().astimezone()
    base_name = f"{captured_at:%Y%m%d}-{safe_test_name}"
    log_path = log_dir / f"{base_name}.txt"
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
        "--manual-checks",
        action="store_true",
        default=False,
        help="Enable operator prompts for lamp physical observations.",
    )
    parser.addoption(
        "--wifi-ssid",
        action="store",
        default=None,
        help="Override configured Wi-Fi SSID.",
    )
    parser.addoption(
        "--wifi-password",
        action="store",
        default=None,
        help="Override configured Wi-Fi password.",
    )
    parser.addoption(
        "--app-user",
        action="store",
        default=None,
        help="Override default SENTRY SWM-2 user account.",
    )
    parser.addoption(
        "--app-password",
        action="store",
        default=None,
        help="Override default SENTRY SWM-2 user password.",
    )


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    accuracy_index = next(
        (
            index
            for index, item in enumerate(items)
            if item.name == "test_distance_interactive_measurement"
        ),
        None,
    )
    reboot_index = next(
        (
            index
            for index, item in enumerate(items)
            if item.name == "test_distance_persistence_after_reboot"
        ),
        None,
    )
    if (
        accuracy_index is not None
        and reboot_index is not None
        and accuracy_index > reboot_index
    ):
        # Run operator distance measurements before the reboot test can disrupt UART.
        accuracy_test = items.pop(accuracy_index)
        items.insert(reboot_index, accuracy_test)


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
    requires_console = item.get_closest_marker("lamp") is None or item.config.getoption(
        "manual_checks"
    )
    if (
        item.get_closest_marker("interactive") is not None
        and requires_console
        and item.config.getoption("capture") != "no"
    ):
        pytest.fail(
            "Interactive checks require console input; run with '-s'."
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
            "Interactive checks require console input; run with '-s'."
        )


@pytest.fixture
def manual_check(
    pytestconfig: pytest.Config, request: pytest.FixtureRequest
) -> Callable[[str], bool | None]:
    if (
        request.node.get_closest_marker("lamp") is not None
        and not pytestconfig.getoption("manual_checks")
    ):
        return lambda instruction: None

    _require_console(pytestconfig)
    return verify_manually


@pytest.fixture
def manual_prepare(
    pytestconfig: pytest.Config, request: pytest.FixtureRequest
) -> Callable[[str], None]:
    if (
        request.node.get_closest_marker("lamp") is not None
        and not pytestconfig.getoption("manual_checks")
    ):
        def skip_manual_preparation(instruction: str) -> None:
            with allure.step("Manual preparation not run (UART-only mode)"):
                allure.attach(
                    instruction,
                    name="Manual preparation not run",
                    attachment_type=allure.attachment_type.TEXT,
                )
            logging.getLogger(__name__).info(
                "MANUAL PREPARE | NOT RUN (UART-only mode) | %s", instruction
            )

        return skip_manual_preparation

    _require_console(pytestconfig)
    return prepare_manually


@pytest.fixture
def manual_distance(
    pytestconfig: pytest.Config,
) -> Callable[[str], float]:
    _require_console(pytestconfig)
    return enter_reference_distance


@pytest.fixture
def manual_continue(
    pytestconfig: pytest.Config,
) -> Callable[[], bool]:
    _require_console(pytestconfig)
    return ask_to_continue_measurements


@pytest.fixture
def soft() -> SoftChecks:
    return SoftChecks()


def _snapshot_lamp(driver: DeviceDriver) -> dict[str, Any] | None:
    try:
        return driver.lamp_status(timeout=0.6)
    except Exception:
        logging.getLogger(__name__).warning("Lamp state snapshot unavailable.")
        return None


def _restore_lamp(
    driver: DeviceDriver,
    snapshot: dict[str, Any] | None,
    elapsed_s: float,
) -> None:
    """Return the lamp to the state found at test start."""
    if snapshot is None:
        try:
            driver.lamp_off(timeout=0.4)
        except Exception:
            pass
        return

    try:
        driver.lamp_set_timer(0, timeout=0.4)
        driver.lamp_set_color(snapshot["color"], timeout=0.4)
        driver.lamp_set_brightness(snapshot["brightness"], timeout=0.4)
        driver.lamp_set_mode(snapshot["mode"], timeout=0.4)
        remaining_timer_s = max(0, snapshot["timer_s"] - int(elapsed_s))
        if snapshot["lamp"] == "on" and (
            snapshot["timer_s"] == 0 or remaining_timer_s > 0
        ):
            driver.lamp_on(timeout=0.4)
        else:
            driver.lamp_off(timeout=0.4)
        if remaining_timer_s > 0:
            driver.lamp_set_timer(remaining_timer_s, timeout=0.4)
    except Exception as exc:
        logging.getLogger(__name__).warning("Failed to restore lamp state: %s", exc)


def _get_confirmed_firmware_version(
    driver: DeviceDriver, request: pytest.FixtureRequest
) -> str:
    version = driver.version()
    request.node.stash[FIRMWARE_VERSION_KEY] = version
    expected = request.config.getoption("--expected-fw-version")
    if expected is not None and version != expected:
        pytest.fail(f"Expected firmware {expected}, but device reports {version}.")
    if version not in SUPPORTED_VERSIONS:
        pytest.fail(
            f"SENTRY SWM-2 automated verification supports {', '.join(sorted(SUPPORTED_VERSIONS))}; "
            f"device reports {version}."
        )
    allure.dynamic.label("firmware_version", version)
    return version


@pytest.fixture
def device_driver(request: pytest.FixtureRequest) -> Generator[DeviceDriver, None, None]:
    port = request.config.getoption("--port") or _find_esp32_port()
    baudrate = int(request.config.getoption("--baudrate") or 115200)
    driver = DeviceDriver(port=port, baudrate=baudrate)

    lamp_snapshot = None
    lamp_snapshot_taken = False
    lamp_snapshot_time = time.monotonic()
    try:
        driver.open()
        _get_confirmed_firmware_version(driver, request)
        if request.node.get_closest_marker("persistent") is None:
            lamp_snapshot = _snapshot_lamp(driver)
            lamp_snapshot_taken = True

        yield driver
    finally:
        try:
            if (
                driver.is_open
                and lamp_snapshot_taken
                and request.node.get_closest_marker("persistent") is None
                and not request.node.stash.get(LAMP_STATE_FIXTURE_ACTIVE, False)
            ):
                _restore_lamp(
                    driver,
                    lamp_snapshot,
                    elapsed_s=time.monotonic() - lamp_snapshot_time,
                )
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
    return request.node.stash[FIRMWARE_VERSION_KEY]


@pytest.fixture
def wifi_ssid(request: pytest.FixtureRequest) -> str:
    ssid, _ = resolve_wifi_credentials(
        ssid_override=request.config.getoption("--wifi-ssid"),
        password_override=request.config.getoption("--wifi-password"),
    )
    if not ssid:
        pytest.skip(
            f"Configure config/wifi_secrets.py or {WIFI_SSID_ENV}, "
            "TEST_WIFI_SSID, or --wifi-ssid to run Wi-Fi tests."
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
    return password


@pytest.fixture
def missing_wifi_ssid() -> str:
    return WIFI_MISSING_SSID or DEFAULT_WIFI_MISSING_SSID


@pytest.fixture
def app_credentials(request: pytest.FixtureRequest) -> tuple[str, str]:
    user, password = resolve_account_credentials(
        user_override=request.config.getoption("--app-user"),
        password_override=request.config.getoption("--app-password"),
    )
    if not user or not password:
        pytest.skip(
            f"Configure {APP_USER_ENV}/{APP_PASSWORD_ENV} or TEST_USER/TEST_PASSWORD, "
            "or pass --app-user and --app-password, for authenticated tests."
        )
    return user, password


@pytest.fixture
def guard_pin() -> str:
    pin = os.environ.get("HW17_GUARD_PIN", "")
    if not pin:
        pytest.skip("Set HW17_GUARD_PIN in the local environment to run Guard alarm tests.")
    if not re.fullmatch(r"\d{4}", pin):
        pytest.fail("HW17_GUARD_PIN must be exactly four digits.")
    return pin


def _ensure_wifi_connected(
    device_driver: DeviceDriver,
    request: pytest.FixtureRequest,
) -> None:
    ssid, password = resolve_wifi_credentials(
        ssid_override=request.config.getoption("--wifi-ssid"),
        password_override=request.config.getoption("--wifi-password"),
    )

    def has_valid_target_connection(status: dict[str, Any]) -> bool:
        return DeviceDriver.wifi_connection_is_valid(status) and (
            not ssid or status.get("ssid") == ssid
        )

    def read_wifi_status() -> dict[str, Any]:
        last_error: TimeoutError | None = None
        for _ in range(WIFI_STATUS_ATTEMPTS):
            try:
                return device_driver.wifi_status()
            except TimeoutError as exc:
                last_error = exc
        pytest.fail(
            "Could not read a complete Wi-Fi status response after "
            f"{WIFI_STATUS_ATTEMPTS} attempts: {last_error}"
        )

    status = read_wifi_status()
    if has_valid_target_connection(status):
        return

    with allure.step("Reconnect to the saved Wi-Fi profile"):
        device_driver.wifi_reconnect(timeout=20.0)
    status = read_wifi_status()
    if has_valid_target_connection(status):
        return

    if not ssid or not password:
        pytest.fail(
            "Could not establish a valid connection to the configured Wi-Fi network, "
            "and no configured SSID/password are available for the 'connect' fallback. "
            f"Configure {WIFI_SSID_ENV}/{WIFI_PASSWORD_ENV} or "
            "TEST_WIFI_SSID/TEST_WIFI_PASSWORD, or pass --wifi-ssid/--wifi-password."
        )

    with allure.step(f"Fallback: connect to configured Wi-Fi SSID '{ssid}'"):
        if not device_driver.wifi_connect(ssid, password, timeout=14.0):
            pytest.fail(
                "Saved Wi-Fi reconnect failed and the configured-credential "
                f"'connect' fallback did not connect to SSID '{ssid}'."
            )

    status = read_wifi_status()
    if not has_valid_target_connection(status):
        pytest.fail(
            "Wi-Fi 'connect' fallback returned success, but status did not confirm "
            f"a valid connection to the configured SSID '{ssid}' with an IP address: "
            f"{status}"
        )


def _ensure_authenticated_device(
    device_driver: DeviceDriver,
    request: pytest.FixtureRequest,
) -> None:
    user, password = resolve_account_credentials(
        user_override=request.config.getoption("--app-user"),
        password_override=request.config.getoption("--app-password"),
    )
    if not user or not password:
        pytest.skip(
            f"Configure {APP_USER_ENV}/{APP_PASSWORD_ENV} or TEST_USER/TEST_PASSWORD, "
            "or pass --app-user and --app-password, for authenticated tests."
        )

    _ensure_wifi_connected(device_driver, request)

    def read_identity() -> tuple[str | None, str | None]:
        for _ in range(IDENTITY_ATTEMPTS):
            identity_mark = len(device_driver.uart_log)
            device_driver.send_command_nowait("whoami")
            identity_result = device_driver.wait_for_any(
                ("not logged in", ", access:"),
                timeout=2.0,
                since_index=identity_mark,
            )
            if identity_result is not None:
                current_user = None
                for entry in device_driver.uart_log[identity_mark:]:
                    match = re.search(
                        r"user:\s*([^\s,]+),\s*access:\s*([^\s,]+)",
                        entry,
                        re.IGNORECASE,
                    )
                    if match:
                        current_user = match.group(1)
                        break
                return identity_result, current_user
        return None, None

    identity_result, current_user = read_identity()
    if identity_result is None:
        pytest.fail(
            "Timed out waiting for the UART identity response after "
            f"{IDENTITY_ATTEMPTS} attempts."
        )

    if identity_result != "not logged in":
        if current_user == user:
            return

        device_driver.logout()
        identity_result, _ = read_identity()
        if identity_result != "not logged in":
            pytest.fail(
                "Could not end the existing SENTRY SWM-2 session before logging "
                f"in as configured user '{user}'."
            )

    login_mark = len(device_driver.uart_log)
    device_driver.login_nowait(user, password)
    login_result = device_driver.wait_for_any(
        (
            f"[AUTH] operator {user} on watch",
            "wrong login or password",
            "E209",
            "E210",
            "E207",
            "E002",
        ),
        timeout=15.0,
        since_index=login_mark,
    )
    if login_result == "E002":
        _ensure_wifi_connected(device_driver, request)
        login_mark = len(device_driver.uart_log)
        device_driver.login_nowait(user, password)
        login_result = device_driver.wait_for_any(
            (
                f"[AUTH] operator {user} on watch",
                "wrong login or password",
                "E209",
                "E210",
                "E207",
                "E002",
            ),
            timeout=15.0,
            since_index=login_mark,
        )
    if login_result in {"wrong login or password", "E209", "E210", "E207"}:
        pytest.fail(
            "Configured SENTRY SWM-2 login was rejected or temporarily locked. "
            "Check the account state before running authenticated tests."
        )
    if login_result == "E002":
        pytest.fail(
            "Login was rejected because Wi-Fi is unavailable after the connection "
            "precondition was verified."
        )

    identity_result, current_user = read_identity()
    if identity_result != ", access:" or current_user != user:
        pytest.fail(
            f"Login for configured SENTRY SWM-2 user '{user}' did not establish "
            "the expected session after checking the UART identity response."
        )


@pytest.fixture
def ensure_wifi_connected(
    request: pytest.FixtureRequest,
) -> Callable[[DeviceDriver], None]:
    """Ensure the configured Wi-Fi connection without changing login state."""
    return lambda driver: _ensure_wifi_connected(driver, request)


@pytest.fixture
def ensure_authenticated_device(
    request: pytest.FixtureRequest,
) -> Callable[[DeviceDriver], None]:
    """Ensure Wi-Fi and the configured account session on an open device."""
    return lambda driver: _ensure_authenticated_device(driver, request)


@pytest.fixture
def authenticated_device(
    device_driver: DeviceDriver,
    ensure_authenticated_device: Callable[[DeviceDriver], None],
) -> Generator[DeviceDriver, None, None]:
    """Ensure Wi-Fi and the configured login before [login] tests."""
    ensure_authenticated_device(device_driver)
    yield device_driver


@pytest.fixture
def lamp_state(
    request: pytest.FixtureRequest,
    authenticated_device: DeviceDriver,
    ensure_authenticated_device: Callable[[DeviceDriver], None],
) -> Generator[LampState, None, None]:
    """Restore the captured Beacon state after each lamp test."""
    with allure.step("Capture the original Beacon state for teardown"):
        initial_status = authenticated_device.lamp_status()
        if initial_status["timer_s"] != 0:
            pytest.fail(
                "Lamp tests require the Beacon timer to be off before starting; "
                f"got {initial_status}."
            )
        state = LampState(initial_status)

    request.node.stash[LAMP_STATE_FIXTURE_ACTIVE] = True
    try:
        yield state
    finally:
        if state.restore_after_test:
            call_report = getattr(request.node, "rep_call", None)
            cleanup_lamp_test_state(
                authenticated_device,
                state.initial_status,
                ensure_authenticated_device=ensure_authenticated_device,
                primary_failed=call_report is not None and call_report.failed,
            )
        else:
            allure.attach(
                state.cleanup_skip_reason
                or "Beacon cleanup was skipped because device recovery was not confirmed.",
                name="Beacon cleanup skipped",
                attachment_type=allure.attachment_type.TEXT,
            )
