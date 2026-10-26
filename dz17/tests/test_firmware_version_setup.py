from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest
from drivers.device_driver import DeviceDriver
from tests import lamp_test_helpers

import conftest


class FakeRequest:
    def __init__(self, expected_version: str | None, debug: bool = False) -> None:
        self.node = SimpleNamespace(
            stash=pytest.Stash(),
            nodeid="tests/test_buttons.py::test_firmware_check",
            name="test_firmware_check",
            get_closest_marker=lambda name: object() if name == "buttons" else None,
        )

        def getoption(name: str) -> str | None:
            options = {
                "--port": "DUMMY",
                "--baudrate": None,
                "--expected-fw-version": expected_version,
                "log_cli_level": "DEBUG" if debug else "INFO",
            }
            return options.get(name)

        self.config = SimpleNamespace(
            getoption=getoption,
            getini=lambda name: "INFO",
        )


def _driver_with_firmware(version: str) -> Mock:
    driver = Mock(spec=DeviceDriver)
    driver.is_open = True
    driver.uart_log = [f"RX < fw v{version}"]
    driver.version.return_value = version
    return driver


def _setup_item(
    *, lamp: bool, manual_checks: bool, capture: str = "fd"
) -> SimpleNamespace:
    markers = {"interactive"}
    if lamp:
        markers.add("lamp")
    return SimpleNamespace(
        get_closest_marker=lambda name: object() if name in markers else None,
        config=SimpleNamespace(
            getoption=lambda name: (
                capture if name == "capture" else manual_checks
            )
        ),
    )


@pytest.mark.parametrize("marker", ["auth", "ota"])
def test_auth_and_ota_uart_logs_are_saved_under_their_pack(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    marker: str,
) -> None:
    monkeypatch.setattr(conftest, "DZ17_DIR", tmp_path)
    item = SimpleNamespace(
        name=f"test_{marker}_case",
        nodeid=f"tests/test_{marker}.py::test_{marker}_case",
        get_closest_marker=lambda name: object() if name == marker else None,
    )
    driver = SimpleNamespace(uart_log=["TX > status", "RX < status: ready"])

    log_path = conftest._save_automated_uart_log(driver, item, "2.3.0")

    assert log_path.parent == tmp_path / "logs" / "automated" / marker / "2.3.0"
    assert "Test: " + item.nodeid in log_path.read_text(encoding="utf-8")


@pytest.mark.parametrize("marker", ["auth", "ota"])
def test_auth_and_ota_uart_logs_are_saved_without_debug_logging(marker: str) -> None:
    request = FakeRequest(expected_version=None)
    item = SimpleNamespace(
        get_closest_marker=lambda name: object() if name == marker else None
    )

    assert conftest._should_save_automated_uart_log(request.config, item)


@pytest.mark.parametrize("marker", ["auth", "ota"])
def test_device_driver_fixture_persists_auth_and_ota_logs_at_info_level(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    marker: str,
) -> None:
    request = FakeRequest(expected_version="2.1.0")
    request.node.name = f"test_{marker}_fixture_log"
    request.node.nodeid = f"tests/test_{marker}.py::{request.node.name}"
    request.node.get_closest_marker = (
        lambda name: object() if name == marker else None
    )
    driver = _driver_with_firmware("2.1.0")
    driver.lamp_status.side_effect = TimeoutError("lamp snapshot unavailable")
    monkeypatch.setattr(conftest, "DZ17_DIR", tmp_path)
    monkeypatch.setattr(conftest, "DeviceDriver", lambda **_: driver)

    fixture = conftest.device_driver.__wrapped__(request)
    next(fixture)
    with pytest.raises(StopIteration):
        next(fixture)

    log_dir = tmp_path / "logs" / "automated" / marker / "2.1.0"
    log_path = next(log_dir.glob(f"*-{request.node.name}.txt"))
    assert log_path.is_file()
    contents = log_path.read_text(encoding="utf-8")
    assert request.node.nodeid in contents
    assert "Firmware: 2.1.0" in contents


def test_other_uart_logs_still_require_debug_logging() -> None:
    request = FakeRequest(expected_version=None)
    item = SimpleNamespace(get_closest_marker=lambda name: None)

    assert not conftest._should_save_automated_uart_log(request.config, item)


def test_lamp_interactive_setup_allows_uart_only_without_console() -> None:
    conftest.pytest_runtest_setup(
        _setup_item(lamp=True, manual_checks=False)
    )


def test_lamp_interactive_setup_requires_console_for_manual_checks() -> None:
    with pytest.raises(pytest.fail.Exception, match="require console input"):
        conftest.pytest_runtest_setup(
            _setup_item(lamp=True, manual_checks=True)
        )


def test_other_interactive_setup_still_requires_console() -> None:
    with pytest.raises(pytest.fail.Exception, match="require console input"):
        conftest.pytest_runtest_setup(
            _setup_item(lamp=False, manual_checks=False)
        )


def test_device_driver_stores_actual_firmware_version() -> None:
    request = FakeRequest(expected_version="2.1.0")
    driver = _driver_with_firmware("2.1.0")

    version = conftest._get_confirmed_firmware_version(driver, request)

    assert version == "2.1.0"
    assert request.node.stash[conftest.FIRMWARE_VERSION_KEY] == "2.1.0"
    driver.version.assert_called_once_with()


def test_device_driver_retries_firmware_version_after_timeout() -> None:
    request = FakeRequest(expected_version="2.1.0")
    driver = _driver_with_firmware("2.1.0")
    driver.version.side_effect = [TimeoutError("no response"), "2.1.0"]

    version = conftest._get_confirmed_firmware_version(driver, request)

    assert version == "2.1.0"
    assert driver.version.call_count == 2


def test_device_driver_fails_after_firmware_version_attempts_are_exhausted() -> None:
    request = FakeRequest(expected_version="2.1.0")
    driver = _driver_with_firmware("2.1.0")
    driver.version.side_effect = TimeoutError("no response")

    with pytest.raises(
        pytest.fail.Exception,
        match=f"after {conftest.FIRMWARE_VERSION_ATTEMPTS} attempts",
    ):
        conftest._get_confirmed_firmware_version(driver, request)

    assert driver.version.call_count == conftest.FIRMWARE_VERSION_ATTEMPTS


def test_uart_log_keeps_only_latest_per_test_and_firmware(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(conftest, "DZ17_DIR", tmp_path)
    item = FakeRequest(expected_version=None).node
    current_firmware_dir = tmp_path / "logs" / "automated" / "buttons" / "2.1.0"
    other_firmware_dir = tmp_path / "logs" / "automated" / "buttons" / "2.3.0"
    current_firmware_dir.mkdir(parents=True)
    other_firmware_dir.mkdir(parents=True)
    stale_logs = (
        current_firmware_dir / "20261018-test_firmware_check.txt",
        current_firmware_dir / "20261018-test_firmware_check.prev.txt",
    )
    for stale_log in stale_logs:
        stale_log.write_text("stale transcript", encoding="utf-8")
    unrelated_log = current_firmware_dir / "20261018-test_another_case.txt"
    unrelated_log.write_text("other test transcript", encoding="utf-8")
    old_firmware_log = other_firmware_dir / "20261018-test_firmware_check.txt"
    old_firmware_log.write_text("other firmware transcript", encoding="utf-8")

    current_log = conftest._save_automated_uart_log(
        _driver_with_firmware("2.1.0"), item, "2.1.0"
    )

    assert current_log.is_file()
    assert not any(stale_log.exists() for stale_log in stale_logs)
    assert unrelated_log.is_file()
    assert old_firmware_log.is_file()
    assert len(list(current_firmware_dir.glob("*-test_firmware_check*.txt"))) == 1


def test_expected_version_mismatch_logs_actual_firmware(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(conftest, "DZ17_DIR", tmp_path)
    request = FakeRequest(expected_version="2.3.0", debug=True)
    driver = _driver_with_firmware("2.1.0")
    monkeypatch.setattr(conftest, "DeviceDriver", lambda **kwargs: driver)

    fixture = conftest.device_driver.__wrapped__(request)
    with pytest.raises(pytest.fail.Exception, match="Expected firmware 2.3.0"):
        next(fixture)

    assert driver.close.called
    saved_logs = list((tmp_path / "logs" / "automated" / "buttons" / "2.1.0").glob("*.txt"))
    assert len(saved_logs) == 1
    assert "Firmware: 2.1.0" in saved_logs[0].read_text(encoding="utf-8")


def test_device_driver_closes_when_open_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = FakeRequest(expected_version=None)
    driver = Mock(spec=DeviceDriver)
    driver.is_open = False
    driver.open.side_effect = OSError("serial open failed")
    monkeypatch.setattr(conftest, "_find_esp32_port", lambda: "DUMMY")
    monkeypatch.setattr(conftest, "DeviceDriver", lambda **kwargs: driver)

    fixture = conftest.device_driver.__wrapped__(request)
    with pytest.raises(OSError, match="serial open failed"):
        next(fixture)

    driver.close.assert_called_once_with()


def test_authenticated_device_always_checks_wifi_even_for_existing_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = FakeRequest(expected_version=None)
    driver = Mock(spec=DeviceDriver)
    driver.uart_log = []
    driver.send_command_nowait.side_effect = lambda command: driver.uart_log.append(
        "RX < I (1) sentry: user: testUser, access: user"
    )
    driver.wait_for_any.return_value = ", access:"
    ensure_wifi = Mock()
    monkeypatch.setattr(
        conftest,
        "resolve_account_credentials",
        lambda **_: ("testUser", "secret"),
    )
    monkeypatch.setattr(conftest, "_ensure_wifi_connected", ensure_wifi)

    conftest._ensure_authenticated_device(driver, request)

    ensure_wifi.assert_called_once_with(driver, request)
    driver.send_command_nowait.assert_called_once_with("whoami")
    driver.login_nowait.assert_not_called()


def test_wifi_precondition_accepts_saved_reconnect_after_status_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = FakeRequest(expected_version=None)
    driver = Mock(spec=DeviceDriver)
    driver.wifi_status.side_effect = [
        {"connected": False, "ssid": "test-network", "ip": None},
        {"connected": True, "ssid": "test-network", "ip": "192.168.1.20"},
    ]
    driver.wifi_reconnect.return_value = True
    monkeypatch.setattr(
        conftest,
        "resolve_wifi_credentials",
        lambda **_: ("test-network", "dummy-password"),
    )

    conftest._ensure_wifi_connected(driver, request)

    driver.wifi_reconnect.assert_called_once_with(timeout=20.0)
    driver.wifi_connect.assert_not_called()
    assert driver.wifi_status.call_count == 2


def test_wifi_precondition_retries_status_until_uart_response_arrives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = FakeRequest(expected_version=None)
    driver = Mock(spec=DeviceDriver)
    connected = {"connected": True, "ssid": "test-network", "ip": "192.168.1.20"}
    driver.wifi_status.side_effect = [TimeoutError("incomplete status"), connected]
    monkeypatch.setattr(
        conftest,
        "resolve_wifi_credentials",
        lambda **_: ("test-network", "dummy-password"),
    )

    conftest._ensure_wifi_connected(driver, request)

    assert driver.wifi_status.call_count == 2
    driver.wifi_reconnect.assert_not_called()


def test_wifi_precondition_falls_back_and_verifies_configured_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = FakeRequest(expected_version=None)
    driver = Mock(spec=DeviceDriver)
    disconnected = {"connected": False, "ssid": "saved-network", "ip": None}
    connected = {"connected": True, "ssid": "test-network", "ip": "192.168.1.20"}
    driver.wifi_status.side_effect = [disconnected, disconnected, connected]
    driver.wifi_reconnect.return_value = False
    driver.wifi_connect.return_value = True
    monkeypatch.setattr(
        conftest,
        "resolve_wifi_credentials",
        lambda **_: ("test-network", "dummy-password"),
    )

    conftest._ensure_wifi_connected(driver, request)

    driver.wifi_reconnect.assert_called_once_with(timeout=20.0)
    driver.wifi_connect.assert_called_once_with(
        "test-network",
        "dummy-password",
        timeout=14.0,
    )
    assert driver.wifi_status.call_count == 3


def test_authenticated_device_waits_for_login_and_expected_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = FakeRequest(expected_version=None)
    driver = Mock(spec=DeviceDriver)
    driver.uart_log = []

    def send_command(command: str) -> None:
        if command == "whoami":
            response = (
                "RX < I (1) sentry: not logged in"
                if not driver.uart_log
                else "RX < I (2) sentry: user: testUser, access: user"
            )
            driver.uart_log.append(response)

    driver.send_command_nowait.side_effect = send_command
    driver.wait_for_any.side_effect = [
        None,
        "not logged in",
        "[AUTH] operator testUser on watch",
        ", access:",
    ]
    ensure_wifi = Mock()
    monkeypatch.setattr(
        conftest,
        "resolve_account_credentials",
        lambda **_: ("testUser", "secret"),
    )
    monkeypatch.setattr(conftest, "_ensure_wifi_connected", ensure_wifi)

    conftest._ensure_authenticated_device(driver, request)

    ensure_wifi.assert_called_once_with(driver, request)
    driver.login_nowait.assert_called_once_with("testUser", "secret")
    assert driver.send_command_nowait.call_args_list == [
        call("whoami"),
        call("whoami"),
        call("whoami"),
    ]


def test_authenticated_device_reconnects_after_transient_login_wifi_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = FakeRequest(expected_version=None)
    driver = Mock(spec=DeviceDriver)
    driver.uart_log = []
    driver.send_command_nowait.side_effect = lambda command: driver.uart_log.append(
        "RX < I (1) sentry: not logged in"
        if len(driver.uart_log) == 0
        else "RX < I (2) sentry: user: testUser, access: user"
    )
    driver.wait_for_any.side_effect = [
        "not logged in",
        "E002",
        "[AUTH] operator testUser on watch",
        ", access:",
    ]
    ensure_wifi = Mock()
    monkeypatch.setattr(
        conftest,
        "resolve_account_credentials",
        lambda **_: ("testUser", "secret"),
    )
    monkeypatch.setattr(conftest, "_ensure_wifi_connected", ensure_wifi)

    conftest._ensure_authenticated_device(driver, request)

    assert ensure_wifi.call_args_list == [
        call(driver, request),
        call(driver, request),
    ]
    assert driver.login_nowait.call_count == 2


def test_authenticated_device_waits_for_reported_login_lockout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = FakeRequest(expected_version=None)
    driver = Mock(spec=DeviceDriver)
    driver.uart_log = []

    def send_command_nowait(command: str) -> None:
        if command == "whoami":
            identity = (
                "RX < I (1) sentry: not logged in"
                if len(driver.login_nowait.call_args_list) == 0
                else "RX < I (2) sentry: user: testUser, access: user"
            )
            driver.uart_log.append(identity)

    def wait_for_any(
        patterns: tuple[str, ...],
        timeout: float,
        since_index: int | None = None,
    ) -> str | None:
        if "E207" in patterns and driver.login_nowait.call_count == 1:
            driver.uart_log.append(
                "RX < E (2) sentry: E207 account locked. Try again in 2 s"
            )
            return "E207"
        if any(pattern.startswith("[AUTH] operator") for pattern in patterns):
            return "[AUTH] operator testUser on watch"
        return "not logged in" if not driver.login_nowait.call_args_list else ", access:"

    driver.send_command_nowait.side_effect = send_command_nowait
    driver.wait_for_any.side_effect = wait_for_any
    ensure_wifi = Mock()
    sleep = Mock()
    monkeypatch.setattr(
        conftest,
        "resolve_account_credentials",
        lambda **_: ("testUser", "secret"),
    )
    monkeypatch.setattr(conftest, "_ensure_wifi_connected", ensure_wifi)
    monkeypatch.setattr(conftest.time, "sleep", sleep)

    conftest._ensure_authenticated_device(driver, request)

    assert driver.login_nowait.call_count == 2
    sleep.assert_called_once_with(3)
    driver.wait_for_any.assert_any_call(
        (
            "[AUTH] operator testUser on watch",
            "wrong login or password",
            "E209",
            "E210",
            "E207",
            "E002",
        ),
        timeout=15.0,
        since_index=1,
    )


def test_authenticated_device_replaces_a_different_logged_in_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = FakeRequest(expected_version=None)
    driver = Mock(spec=DeviceDriver)
    driver.uart_log = []

    def send_command(command: str) -> None:
        if command == "whoami":
            response = (
                "RX < I (1) sentry: user: otherUser, access: user"
                if len(driver.uart_log) == 0
                else "RX < I (2) sentry: not logged in"
                if len(driver.uart_log) == 1
                else "RX < I (3) sentry: user: testUser, access: user"
            )
            driver.uart_log.append(response)

    driver.send_command_nowait.side_effect = send_command
    driver.wait_for_any.side_effect = [
        ", access:",
        "not logged in",
        "[AUTH] operator testUser on watch",
        ", access:",
    ]
    driver.wait_for.return_value = True
    ensure_wifi = Mock()
    monkeypatch.setattr(
        conftest,
        "resolve_account_credentials",
        lambda **_: ("testUser", "secret"),
    )
    monkeypatch.setattr(conftest, "_ensure_wifi_connected", ensure_wifi)

    conftest._ensure_authenticated_device(driver, request)

    driver.logout.assert_called_once_with()
    assert driver.send_command_nowait.call_args_list == [
        call("whoami"),
        call("whoami"),
        call("whoami"),
    ]
    driver.login_nowait.assert_called_once_with("testUser", "secret")


@pytest.mark.parametrize("primary_failed", [False, True])
def test_lamp_state_fixture_restores_captured_status_after_test(
    monkeypatch: pytest.MonkeyPatch,
    primary_failed: bool,
) -> None:
    request = FakeRequest(expected_version=None)
    request.node.rep_call = SimpleNamespace(failed=primary_failed)
    driver = Mock(spec=DeviceDriver)
    initial_status = {
        "lamp": "off",
        "color": (160, 0, 255),
        "brightness": 75,
        "mode": "breathe",
        "timer_s": 0,
    }
    driver.lamp_status.return_value = initial_status
    ensure_wifi = Mock()
    ensure_authenticated = Mock()
    cleanup = Mock()
    monkeypatch.setattr(conftest, "cleanup_lamp_test_state", cleanup)

    fixture = conftest.lamp_state.__wrapped__(
        request,
        driver,
        ensure_authenticated,
    )
    state = next(fixture)

    assert state.initial_status == initial_status
    assert request.node.stash[conftest.LAMP_STATE_FIXTURE_ACTIVE] is True
    with pytest.raises(StopIteration):
        next(fixture)

    cleanup.assert_called_once_with(
        driver,
        initial_status,
        ensure_authenticated_device=ensure_authenticated,
        primary_failed=primary_failed,
    )


def test_lamp_state_fixture_skips_commands_when_reboot_recovery_is_unconfirmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = FakeRequest(expected_version=None)
    driver = Mock(spec=DeviceDriver)
    driver.lamp_status.return_value = {
        "lamp": "off",
        "color": (160, 0, 255),
        "brightness": 75,
        "mode": "breathe",
        "timer_s": 0,
    }
    cleanup = Mock()
    attach = Mock()
    monkeypatch.setattr(conftest, "cleanup_lamp_test_state", cleanup)
    monkeypatch.setattr(conftest.allure, "attach", attach)

    fixture = conftest.lamp_state.__wrapped__(
        request,
        driver,
        Mock(),
    )
    state = next(fixture)
    state.restore_after_test = False
    state.cleanup_skip_reason = "Device recovery was not confirmed."

    with pytest.raises(StopIteration):
        next(fixture)

    cleanup.assert_not_called()
    attach.assert_called_once_with(
        "Device recovery was not confirmed.",
        name="Beacon cleanup skipped",
        attachment_type=conftest.allure.attachment_type.TEXT,
    )


def test_wifi_status_led_fixture_turns_off_and_restores_beacon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = FakeRequest(expected_version=None)
    driver = Mock(spec=DeviceDriver)
    initial_status = {
        "lamp": "on",
        "color": (12, 34, 56),
        "brightness": 70,
        "mode": "solid",
        "timer_s": 0,
    }
    off_status = {**initial_status, "lamp": "off"}
    driver.lamp_status.side_effect = [initial_status, off_status, initial_status]
    driver.whoami.return_value = {"logged_in": True}
    driver.lamp_off.return_value = ["[BEACON] off (command)"]
    restore_lamp = Mock()
    monkeypatch.setattr(conftest, "_restore_lamp", restore_lamp)

    ensure_authenticated = Mock()
    fixture = conftest.wifi_status_led_lamp_off.__wrapped__(
        driver, request, ensure_authenticated
    )
    ensure_lamp_off = next(fixture)
    assert callable(ensure_lamp_off)
    ensure_lamp_off()
    assert request.node.stash[conftest.LAMP_STATE_FIXTURE_ACTIVE] is True
    driver.lamp_off.assert_called_once_with()

    with pytest.raises(StopIteration):
        next(fixture)

    assert ensure_authenticated.call_count == 2
    restore_lamp.assert_called_once()
    assert restore_lamp.call_args.args[:2] == (driver, initial_status)


def test_wifi_status_led_fixture_attempts_beacon_restore_if_login_restore_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = FakeRequest(expected_version=None)
    driver = Mock(spec=DeviceDriver)
    initial_status = {
        "lamp": "on",
        "color": (12, 34, 56),
        "brightness": 70,
        "mode": "solid",
        "timer_s": 0,
    }
    off_status = {**initial_status, "lamp": "off"}
    driver.lamp_status.side_effect = [initial_status, off_status, initial_status]
    driver.whoami.return_value = {"logged_in": True}
    driver.lamp_off.return_value = ["[BEACON] off (command)"]
    restore_lamp = Mock()
    monkeypatch.setattr(conftest, "_restore_lamp", restore_lamp)
    ensure_authenticated = Mock(
        side_effect=[None, RuntimeError("login recovery failed")]
    )

    fixture = conftest.wifi_status_led_lamp_off.__wrapped__(
        driver, request, ensure_authenticated
    )
    ensure_lamp_off = next(fixture)
    ensure_lamp_off()

    with pytest.raises(
        pytest.fail.Exception,
        match="Configured login restoration failed",
    ):
        next(fixture)

    restore_lamp.assert_called_once_with(driver, initial_status, pytest.approx(0, abs=1))


def test_wifi_status_led_fixture_restores_remaining_beacon_timer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = FakeRequest(expected_version=None)
    driver = Mock(spec=DeviceDriver)
    initial_status = {
        "lamp": "on",
        "color": (12, 34, 56),
        "brightness": 70,
        "mode": "solid",
        "timer_s": 60,
    }
    off_status = {**initial_status, "lamp": "off", "timer_s": 0}
    restored_status = {**initial_status, "timer_s": 54}
    driver.lamp_status.side_effect = [initial_status, off_status, restored_status]
    driver.whoami.return_value = {"logged_in": True}
    driver.lamp_off.return_value = ["[BEACON] off (command)"]
    restore_lamp = Mock()
    restore_lamp.return_value = (55, 105.0)
    monkeypatch.setattr(conftest, "_restore_lamp", restore_lamp)
    monkeypatch.setattr(
        conftest.time,
        "monotonic",
        Mock(side_effect=[100.0, 105.0, 106.0]),
    )

    fixture = conftest.wifi_status_led_lamp_off.__wrapped__(
        driver, request, Mock()
    )
    ensure_lamp_off = next(fixture)
    ensure_lamp_off()
    with pytest.raises(StopIteration):
        next(fixture)

    restore_lamp.assert_called_once_with(driver, initial_status, 5.0)


@pytest.mark.parametrize("reported_timer_s", [0, 1])
def test_wifi_status_led_fixture_fails_if_active_beacon_timer_is_shortened(
    monkeypatch: pytest.MonkeyPatch,
    reported_timer_s: int,
) -> None:
    request = FakeRequest(expected_version=None)
    driver = Mock(spec=DeviceDriver)
    initial_status = {
        "lamp": "on",
        "color": (12, 34, 56),
        "brightness": 70,
        "mode": "solid",
        "timer_s": 60,
    }
    off_status = {**initial_status, "lamp": "off", "timer_s": 0}
    shortened_timer_status = {**initial_status, "timer_s": reported_timer_s}
    driver.lamp_status.side_effect = [
        initial_status,
        off_status,
        shortened_timer_status,
    ]
    driver.whoami.return_value = {"logged_in": True}
    driver.lamp_off.return_value = ["[BEACON] off (command)"]
    restore_lamp = Mock(return_value=(55, 105.0))
    monkeypatch.setattr(conftest, "_restore_lamp", restore_lamp)
    monkeypatch.setattr(
        conftest.time,
        "monotonic",
        Mock(side_effect=[100.0, 105.0, 106.0]),
    )

    fixture = conftest.wifi_status_led_lamp_off.__wrapped__(
        driver, request, Mock()
    )
    ensure_lamp_off = next(fixture)
    ensure_lamp_off()
    with pytest.raises(
        pytest.fail.Exception,
        match="Beacon timer restoration differs from the expected",
    ):
        next(fixture)


def test_wifi_status_led_fixture_does_not_change_an_already_off_beacon() -> None:
    request = FakeRequest(expected_version=None)
    driver = Mock(spec=DeviceDriver)
    driver.lamp_status.return_value = {
        "lamp": "off",
        "color": (12, 34, 56),
        "brightness": 70,
        "mode": "solid",
        "timer_s": 0,
    }

    ensure_authenticated = Mock()
    fixture = conftest.wifi_status_led_lamp_off.__wrapped__(
        driver, request, ensure_authenticated
    )
    ensure_lamp_off = next(fixture)
    assert callable(ensure_lamp_off)
    ensure_lamp_off()
    with pytest.raises(StopIteration):
        next(fixture)

    assert ensure_authenticated.call_count == 2
    driver.lamp_off.assert_not_called()
    driver.whoami.assert_not_called()
    assert conftest.LAMP_STATE_FIXTURE_ACTIVE not in request.node.stash


def test_wifi_status_led_fixture_requires_authentication_before_beacon_control() -> None:
    request = FakeRequest(expected_version=None)
    driver = Mock(spec=DeviceDriver)
    driver.lamp_status.return_value = {
        "lamp": "on",
        "color": (12, 34, 56),
        "brightness": 70,
        "mode": "solid",
        "timer_s": 0,
    }
    driver.whoami.return_value = {"logged_in": False}

    ensure_authenticated = Mock()
    fixture = conftest.wifi_status_led_lamp_off.__wrapped__(
        driver, request, ensure_authenticated
    )
    ensure_lamp_off = next(fixture)
    with pytest.raises(
        AssertionError,
        match="configured account is not authenticated",
    ):
        ensure_lamp_off()
    fixture.close()

    assert ensure_authenticated.call_count == 2
    driver.lamp_off.assert_not_called()
    assert conftest.LAMP_STATE_FIXTURE_ACTIVE not in request.node.stash


def test_device_driver_does_not_duplicate_lamp_state_fixture_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = FakeRequest(expected_version=None)
    request.node.stash[conftest.LAMP_STATE_FIXTURE_ACTIVE] = True
    driver = _driver_with_firmware("2.1.0")
    driver.lamp_status.return_value = {
        "lamp": "off",
        "color": (160, 0, 255),
        "brightness": 75,
        "mode": "breathe",
        "timer_s": 0,
    }
    restore_lamp = Mock()
    monkeypatch.setattr(conftest, "DeviceDriver", lambda **_: driver)
    monkeypatch.setattr(conftest, "_restore_lamp", restore_lamp)

    fixture = conftest.device_driver.__wrapped__(request)
    assert next(fixture) is driver
    fixture.close()

    driver.lamp_status.assert_called_once_with(timeout=0.6)
    restore_lamp.assert_not_called()
    driver.close.assert_called_once_with()


def test_lamp_cleanup_attempts_beacon_restore_after_pytest_recovery_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = Mock(spec=DeviceDriver)
    initial_status = {
        "lamp": "off",
        "color": (160, 0, 255),
        "brightness": 75,
        "mode": "breathe",
        "timer_s": 0,
    }
    restore_lamp = Mock()
    ensure_authenticated = Mock(
        side_effect=pytest.fail.Exception("session recovery failed")
    )
    monkeypatch.setattr(
        lamp_test_helpers,
        "_restore_lamp_state",
        restore_lamp,
    )

    with pytest.raises(RuntimeError, match="session recovery failed"):
        conftest.cleanup_lamp_test_state(
            driver,
            initial_status,
            ensure_authenticated_device=ensure_authenticated,
        )

    restore_lamp.assert_called_once_with(driver, initial_status)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("PASSED", "✅ PASSED"),
        ("FAILED", "❌ FAILED"),
        ("SKIPPED", "⚪ SKIPPED"),
        ("XFAIL", "🟠 XFAIL"),
        ("XPASS", "⚠️ XPASS"),
    ],
)
def test_telegram_test_status_uses_clear_result_indicator(
    status: str, expected: str
) -> None:
    assert conftest._telegram_test_status_label(status) == expected
