from __future__ import annotations

from unittest.mock import Mock

import pytest
from drivers.device_driver import DeviceDriver
from tests.lamp_test_helpers import (
    assert_lamp_status,
    assert_lamp_timer_active,
    establish_status_led_state,
    lamp_led_off_status_expectation,
    lamp_led_off_status_question,
    lamp_led_power_cycle_expectation,
    turn_lamp_off_from_on,
)


@pytest.mark.parametrize(
    "color,meaning",
    [
        ("GREEN", "Wi-Fi connected and user logged in"),
        ("ORANGE", "Wi-Fi connected and user logged out"),
        ("RED", "Wi-Fi disconnected"),
    ],
)
def test_lamp_led_off_status_text_uses_the_same_rgb_led(
    color: str,
    meaning: str,
) -> None:
    assert lamp_led_off_status_expectation(color, meaning) == (
        "When the lamp output is switched OFF, the same RGB LED shows "
        f"{color} status indication ({meaning})."
    )
    assert lamp_led_off_status_question(color, meaning) == (
        "With the lamp output OFF, does the same RGB LED show "
        f"{color} status indication ({meaning})?"
    )


def test_lamp_led_power_cycle_text_describes_off_status_between_lamp_outputs() -> None:
    assert lamp_led_power_cycle_expectation(
        "BLUE", "GREEN", "Wi-Fi connected and user logged in"
    ) == (
        "The lamp LED shows BLUE lamp output, changes to GREEN status "
        "indication when the lamp output is switched off, shows BLUE lamp "
        "output again when switched on, then returns to GREEN status "
        "indication when switched off. GREEN means Wi-Fi connected and user "
        "logged in."
    )


@pytest.mark.parametrize(
    "connected,logged_in",
    [
        (True, True),
        (True, False),
        (False, True),
        (False, False),
    ],
)
def test_establish_status_led_state_verifies_each_connection_and_login_pair(
    connected: bool,
    logged_in: bool,
) -> None:
    driver = Mock(spec=DeviceDriver)
    driver.wifi_status.return_value = {
        "connected": connected,
        "raw": [
            "[SYSTEM] state: NORMAL",
            "[SYSTEM] watch: disarmed, CIC alerts unacked: 0",
        ],
    }
    driver.whoami.return_value = {"logged_in": logged_in}
    driver.logout.return_value = [
        "[AUTH] operator testUser relieved from watch"
    ]
    driver.wifi_disconnect.return_value = ["[LINK] disconnected"]

    establish_status_led_state(
        driver,
        connected=connected,
        logged_in=logged_in,
        firmware_version="2.3.0",
    )

    if logged_in:
        driver.logout.assert_not_called()
    else:
        driver.logout.assert_called_once_with()
    if connected:
        driver.wifi_disconnect.assert_not_called()
    else:
        driver.wifi_disconnect.assert_called_once_with()
    driver.guard_status.assert_not_called()


@pytest.mark.parametrize(
    "watch_line",
    [
        "[SYSTEM] watch: armed, CIC alerts unacked: 0",
        None,
    ],
    ids=["guard-armed", "guard-status-missing"],
)
def test_establish_status_led_state_rejects_unverified_disarmed_guard(
    watch_line: str | None,
) -> None:
    driver = Mock(spec=DeviceDriver)
    raw_status = ["[SYSTEM] state: NORMAL"]
    if watch_line is not None:
        raw_status.append(watch_line)
    driver.wifi_status.return_value = {
        "connected": True,
        "raw": raw_status,
    }
    driver.whoami.return_value = {"logged_in": True}

    with pytest.raises(AssertionError, match="requires Guard disarmed"):
        establish_status_led_state(
            driver,
            connected=True,
            logged_in=True,
            firmware_version="2.3.0",
        )

    driver.guard_status.assert_not_called()


def test_assert_lamp_status_returns_the_readback_after_expected_fields_match() -> None:
    driver = Mock(spec=DeviceDriver)
    readback = {
        "lamp": "on",
        "color": (0, 0, 255),
        "brightness": 75,
        "mode": "solid",
        "timer_s": 0,
    }
    driver.lamp_status.return_value = readback

    result = assert_lamp_status(
        driver,
        {"lamp": "on", "color": (0, 0, 255)},
    )

    assert result is readback
    driver.lamp_status.assert_called_once_with()


def test_assert_lamp_status_reports_the_mismatched_field() -> None:
    driver = Mock(spec=DeviceDriver)
    driver.lamp_status.return_value = {"lamp": "off"}

    with pytest.raises(AssertionError, match="expected lamp='on'"):
        assert_lamp_status(driver, {"lamp": "on"})


def test_assert_lamp_timer_active_checks_power_and_timer_readback() -> None:
    driver = Mock(spec=DeviceDriver)
    readback = {"lamp": "on", "timer_s": 4}
    driver.lamp_status.return_value = readback

    result = assert_lamp_timer_active(driver)

    assert result is readback
    driver.lamp_status.assert_called_once_with()


def test_turn_lamp_off_from_on_checks_transition_and_readback() -> None:
    driver = Mock(spec=DeviceDriver)
    driver.lamp_status.side_effect = [
        {"lamp": "on"},
        {"lamp": "off"},
    ]
    driver.lamp_off.return_value = ["[BEACON] off"]

    result = turn_lamp_off_from_on(driver)

    assert result == {"lamp": "off"}
    driver.lamp_off.assert_called_once_with()
    assert driver.lamp_status.call_count == 2
