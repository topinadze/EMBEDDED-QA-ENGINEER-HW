from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest
from drivers.device_driver import DeviceDriver

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
    driver.send_command.return_value = [f"fw v{version}"]
    driver.get_firmware_version.return_value = version
    return driver


def test_device_driver_stores_actual_firmware_version() -> None:
    request = FakeRequest(expected_version="2.1.0")
    driver = _driver_with_firmware("2.1.0")

    version = conftest._get_confirmed_firmware_version(driver, request)

    assert version == "2.1.0"
    assert request.node.stash[conftest.FIRMWARE_VERSION_KEY] == "2.1.0"
    driver.send_command.assert_called_once_with("version", timeout=1.0)


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
        "not logged in",
        "[AUTH] operator testUser on watch",
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

    ensure_wifi.assert_called_once_with(driver, request)
    driver.login_nowait.assert_called_once_with("testUser", "secret")
    driver.wait_for.assert_called_once_with(
        "user: testUser, access:",
        timeout=5.0,
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
        "[AUTH] operator testUser on watch",
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
