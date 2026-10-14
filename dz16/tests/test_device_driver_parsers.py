from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import conftest
import pytest
from config import test_config
from drivers.device_driver import DeviceDriver


def test_bug_07_wifi_setup_uses_configured_credentials_before_saved_credentials() -> None:
    driver = Mock()
    driver.wifi_connect.return_value = True
    driver.wifi_status.return_value = {
        "connected": True,
        "ssid": "TestNode",
        "ip": "192.168.1.20",
        "rssi": -45,
    }

    connected = conftest._connect_wifi_with_configured_credentials(
        driver,
        {"connected": False, "ssid": None, "ip": None, "rssi": None},
        "TestNode",
        "test-password",
    )

    assert connected
    driver.wifi_connect.assert_called_once_with(
        ssid="TestNode",
        password="test-password",
        timeout=10.0,
    )
    driver.wifi_connect_saved.assert_not_called()


def test_wifi_setup_does_not_attempt_configured_connection_without_password(
    monkeypatch,
) -> None:
    driver = Mock()
    driver.wifi_connect_saved.return_value = False
    monkeypatch.setattr(conftest.time, "sleep", Mock())

    connected = conftest._connect_wifi_with_configured_credentials(
        driver,
        {"connected": False, "ssid": None, "ip": None, "rssi": None},
        "TestNode",
        "",
    )

    assert not connected
    assert driver.wifi_connect_saved.call_count == conftest.WIFI_CONNECT_ATTEMPTS
    assert driver.wifi_disconnect.call_count == conftest.WIFI_CONNECT_ATTEMPTS - 1


def test_wifi_setup_uses_saved_credentials_when_no_explicit_credentials() -> None:
    driver = Mock()
    driver.wifi_connect_saved.return_value = True
    driver.wifi_status.return_value = {
        "connected": True,
        "ssid": "SavedNode",
        "ip": "192.168.1.20",
        "rssi": -45,
    }

    connected = conftest._connect_wifi_with_configured_credentials(
        driver,
        {"connected": False, "ssid": None, "ip": None, "rssi": None},
        "",
        "",
    )

    assert connected
    driver.wifi_connect_saved.assert_called_once_with()
    driver.wifi_status.assert_called_once_with()
    driver.wifi_connect.assert_not_called()


def test_wifi_setup_retries_configured_credentials_until_connection_is_valid(
    monkeypatch,
) -> None:
    driver = Mock()
    driver.wifi_connect.side_effect = [False, True]
    disconnected_status = {
        "connected": False,
        "ssid": None,
        "ip": None,
        "rssi": None,
    }
    driver.wifi_status.side_effect = [
        *(
            disconnected_status
            for _ in range(
                conftest.WIFI_STATUS_RECOVERY_CHECKS
                * (conftest.WIFI_CONNECT_ATTEMPTS - 1)
                + conftest.WIFI_CONNECT_ATTEMPTS
                - 1
            )
        ),
        {
            "connected": True,
            "ssid": "TestNode",
            "ip": "192.168.1.20",
            "rssi": -45,
        },
    ]
    monkeypatch.setattr(conftest.time, "sleep", Mock())

    connected = conftest._connect_wifi_with_configured_credentials(
        driver,
        {"connected": False, "ssid": None, "ip": None, "rssi": None},
        "TestNode",
        "test-password",
    )

    assert connected
    assert driver.wifi_connect.call_count == conftest.WIFI_CONNECT_ATTEMPTS
    assert driver.wifi_status.call_count == (
        conftest.WIFI_STATUS_RECOVERY_CHECKS
        * (conftest.WIFI_CONNECT_ATTEMPTS - 1)
        + conftest.WIFI_CONNECT_ATTEMPTS
    )
    assert driver.wifi_disconnect.call_count == conftest.WIFI_CONNECT_ATTEMPTS - 1


def test_wifi_setup_accepts_valid_status_after_connect_timeout(monkeypatch) -> None:
    driver = Mock()
    driver.wifi_connect.return_value = False
    driver.wifi_status.side_effect = [
        {"connected": False, "ssid": None, "ip": None, "rssi": None},
        {"connected": False, "ssid": None, "ip": None, "rssi": None},
        {
            "connected": True,
            "ssid": "TestNode",
            "ip": "10.123.30.49",
            "rssi": -20,
        },
    ]
    sleep = Mock()
    monkeypatch.setattr(conftest.time, "sleep", sleep)

    connected = conftest._connect_wifi_with_configured_credentials(
        driver,
        {"connected": False, "ssid": None, "ip": None, "rssi": None},
        "TestNode",
        "test-password",
    )

    assert connected
    driver.wifi_connect.assert_called_once()
    assert driver.wifi_status.call_count == conftest.WIFI_STATUS_RECOVERY_CHECKS
    driver.wifi_disconnect.assert_not_called()
    assert sleep.call_count == conftest.WIFI_STATUS_RECOVERY_CHECKS - 1


def test_bug_07_wifi_fixture_disconnects_after_unusable_configured_connection(
    monkeypatch,
) -> None:
    driver = Mock()
    driver.wifi_status.return_value = {
        "connected": False,
        "ssid": None,
        "ip": None,
        "rssi": None,
    }
    driver.wifi_connect_saved.return_value = False
    driver.wifi_connect.return_value = True
    request = Mock()
    request.node.ota_lock_reboot_attempted = False
    request.config.getoption.side_effect = lambda name: {
        "--wifi-ssid": "TestNode",
        "--wifi-password": "test-password",
    }[name]
    monkeypatch.setattr(conftest.time, "sleep", Mock())
    fixture = conftest.wifi_connected.__wrapped__(driver, request)

    with pytest.raises(pytest.fail.Exception):
        next(fixture)

    assert driver.wifi_disconnect.call_count == conftest.WIFI_CONNECT_ATTEMPTS
    assert driver.wifi_connect.call_count == conftest.WIFI_CONNECT_ATTEMPTS


def test_reboot_after_ota_lock_reboots_only_when_lock_error_was_observed() -> None:
    driver = Mock()
    request = Mock()
    request.node = SimpleNamespace()
    driver.uart_log = ["RX < [OTA] error: update already in progress"]
    driver.reboot.return_value = True
    fixture = conftest.reboot_after_ota_lock.__wrapped__(driver, request)

    next(fixture)
    with pytest.raises(StopIteration):
        next(fixture)

    driver.reboot.assert_called_once_with(timeout=30.0)
    assert request.node.ota_lock_reboot_attempted


def test_reboot_after_ota_lock_does_not_reboot_without_lock_error() -> None:
    driver = Mock()
    request = Mock()
    request.node = SimpleNamespace()
    driver.uart_log = ["RX < [OTA] failed: download interrupted"]
    fixture = conftest.reboot_after_ota_lock.__wrapped__(driver, request)

    next(fixture)
    with pytest.raises(StopIteration):
        next(fixture)

    driver.reboot.assert_not_called()
    assert not hasattr(request.node, "ota_lock_reboot_attempted")


def test_wifi_cleanup_skips_disconnect_after_ota_recovery_reboot(
    monkeypatch,
) -> None:
    driver = Mock()
    driver.wifi_status.side_effect = [
        {"connected": False, "ssid": None, "ip": None, "rssi": None},
        {
            "connected": True,
            "ssid": "SavedNode",
            "ip": "192.168.1.20",
            "rssi": -45,
        },
    ]
    driver.wifi_connect_saved.return_value = True
    request = Mock()
    request.node = SimpleNamespace()
    request.config.getoption.return_value = None
    monkeypatch.setattr(conftest, "resolve_wifi_credentials", lambda **_: ("", ""))
    fixture = conftest.wifi_connected.__wrapped__(driver, request)

    next(fixture)
    request.node.ota_lock_reboot_attempted = True
    with pytest.raises(StopIteration):
        next(fixture)

    driver.wifi_disconnect.assert_not_called()


def test_reboot_after_ota_lock_fails_explicitly_when_reboot_does_not_recover() -> None:
    driver = Mock()
    request = Mock()
    request.node = SimpleNamespace()
    driver.uart_log = ["RX < [OTA] error: update already in progress"]
    driver.reboot.return_value = False
    fixture = conftest.reboot_after_ota_lock.__wrapped__(driver, request)

    next(fixture)
    with pytest.raises(pytest.fail.Exception, match="recovery reboot"):
        next(fixture)

    driver.reboot.assert_called_once_with(timeout=30.0)
    assert request.node.ota_lock_reboot_attempted


def test_wifi_credential_resolution_prioritizes_test_over_environment_and_defaults(
    monkeypatch,
) -> None:
    monkeypatch.setattr(test_config, "DEFAULT_WIFI_SSID", "DefaultNode")
    monkeypatch.setattr(test_config, "DEFAULT_WIFI_PASSWORD", "default-password")
    monkeypatch.setenv("HW16_WIFI_SSID", "EnvironmentNode")
    monkeypatch.setenv("HW16_WIFI_PASSWORD", "environment-password")

    assert test_config.resolve_wifi_credentials() == (
        "EnvironmentNode",
        "environment-password",
    )
    assert test_config.resolve_wifi_credentials(
        ssid_override="TestNode",
        password_override="test-password",
    ) == ("TestNode", "test-password")


def test_wifi_credential_resolution_uses_local_defaults_without_environment(
    monkeypatch,
) -> None:
    monkeypatch.setattr(test_config, "DEFAULT_WIFI_SSID", "DefaultNode")
    monkeypatch.setattr(test_config, "DEFAULT_WIFI_PASSWORD", "default-password")
    monkeypatch.delenv("HW16_WIFI_SSID", raising=False)
    monkeypatch.delenv("HW16_WIFI_PASSWORD", raising=False)
    monkeypatch.delenv("TEST_WIFI_SSID", raising=False)
    monkeypatch.delenv("TEST_WIFI_PASSWORD", raising=False)

    assert test_config.resolve_wifi_credentials() == (
        "DefaultNode",
        "default-password",
    )


def test_wifi_credential_resolution_uses_aliases_and_prefers_primary_variables(
    monkeypatch,
) -> None:
    monkeypatch.setattr(test_config, "DEFAULT_WIFI_SSID", "DefaultNode")
    monkeypatch.setattr(test_config, "DEFAULT_WIFI_PASSWORD", "default-password")
    monkeypatch.delenv("HW16_WIFI_SSID", raising=False)
    monkeypatch.delenv("HW16_WIFI_PASSWORD", raising=False)
    monkeypatch.setenv("TEST_WIFI_SSID", "AliasNode")
    monkeypatch.setenv("TEST_WIFI_PASSWORD", "alias-password")

    assert test_config.resolve_wifi_credentials() == (
        "AliasNode",
        "alias-password",
    )

    monkeypatch.setenv("HW16_WIFI_SSID", "PrimaryNode")
    monkeypatch.setenv("HW16_WIFI_PASSWORD", "primary-password")
    assert test_config.resolve_wifi_credentials() == (
        "PrimaryNode",
        "primary-password",
    )


def test_wifi_credential_fixtures_use_per_run_overrides() -> None:
    request = Mock()
    request.config.getoption.side_effect = lambda name: {
        "--wifi-ssid": "RunNode",
        "--wifi-password": "run-password",
    }[name]

    ssid = conftest.wifi_ssid.__wrapped__(request)
    credentials = conftest.wifi_credentials.__wrapped__(ssid, request)

    assert ssid == "RunNode"
    assert credentials == ("RunNode", "run-password")


def test_wifi_status_parser_uses_the_explicit_status_line() -> None:
    status = DeviceDriver.parse_wifi_status(
        [
            "I (100) wifi station: retry to connect to the AP",
            "I (200) wifi station: WiFi: disconnected",
            "I (200) wifi station: SSID:",
            "I (200) wifi station: IP: 0.0.0.0",
            "I (200) wifi station: RSSI: 0 dBm",
        ]
    )

    assert status == {
        "connected": False,
        "ssid": None,
        "ip": "0.0.0.0",
        "rssi": 0,
        "raw": [
            "I (100) wifi station: retry to connect to the AP",
            "I (200) wifi station: WiFi: disconnected",
            "I (200) wifi station: SSID:",
            "I (200) wifi station: IP: 0.0.0.0",
            "I (200) wifi station: RSSI: 0 dBm",
        ],
    }


def test_wifi_scan_parser_extracts_legacy_and_labeled_rows() -> None:
    access_points = DeviceDriver.parse_wifi_scan(
        [
            "I (100) wifi station:   [1] LabNet                          -42 dBm",
            "I (100) wifi station:   [2] SSID: Guest RSSI: -70 dBm Channel: 11",
        ]
    )

    assert access_points == [
        {"ssid": "LabNet", "rssi": -42, "channel": None},
        {"ssid": "Guest", "rssi": -70, "channel": 11},
    ]


def test_uart_log_redacts_wifi_password() -> None:
    driver = DeviceDriver(port="COM4")
    driver._sensitive_uart_values.add("correct-horse-battery")

    driver._record("RX <", "password: correct-horse-battery")

    assert "correct-horse-battery" not in driver.uart_log[0]
    assert "[REDACTED]" in driver.uart_log[0]


def test_wifi_connection_guard_requires_a_complete_usable_status() -> None:
    assert DeviceDriver.wifi_connection_is_valid(
        {
            "connected": True,
            "ssid": "LabNet",
            "ip": "10.123.30.49",
            "rssi": -42,
        }
    )

    for status in (
        {"connected": False, "ssid": "LabNet", "ip": "10.123.30.49", "rssi": -42},
        {"connected": True, "ssid": "", "ip": "10.123.30.49", "rssi": -42},
        {"connected": True, "ssid": "LabNet", "ip": "0.0.0.0", "rssi": 0},
        {"connected": True, "ssid": "LabNet", "ip": "169.254.1.2", "rssi": -42},
        {"connected": True, "ssid": "LabNet", "ip": "10.123.30.49", "rssi": None},
    ):
        assert not DeviceDriver.wifi_connection_is_valid(status), status


def test_parse_chip_temperature() -> None:
    assert (
        DeviceDriver.parse_chip_temperature(
            ["I (1234) wifi station: chip temperature: 31.4 C"]
        )
        == 31.4
    )
    assert (
        DeviceDriver.parse_chip_temperature(
            ["I (1234) wifi station: Temp: 28.0 C"]
        )
        == 28.0
    )
    assert DeviceDriver.parse_chip_temperature(["No temp reported"]) is None


def test_parse_sensor_status() -> None:
    lines = [
        "I (100) wifi station: Distance: 22.8 cm",
        "I (100) wifi station: Relay: OFF",
        "I (100) wifi station: LED: auto (WiFi status)",
        "I (100) wifi station: WiFi: connected",
        "I (100) wifi station: Temp: 30.4 C",
    ]
    parsed = DeviceDriver.parse_sensor_status(lines)
    assert parsed["distance"] == 22.8
    assert parsed["relay"] == "OFF"
    assert parsed["led"] == "auto (WiFi status)"
    assert parsed["wifi"] == "connected"
    assert parsed["temperature"] == 30.4
