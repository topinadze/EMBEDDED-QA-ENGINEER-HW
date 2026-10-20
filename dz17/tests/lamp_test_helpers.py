from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import allure
import pytest

from drivers.device_driver import DeviceDriver


@dataclass
class LampState:
    initial_status: dict[str, Any]
    restore_after_test: bool = True
    cleanup_skip_reason: str | None = None


def lamp_led_off_status_expectation(
    status_color: str,
    status_meaning: str,
) -> str:
    return (
        "When the lamp output is switched OFF, the same RGB LED shows "
        f"{status_color} status indication ({status_meaning})."
    )


def lamp_led_off_status_question(
    status_color: str,
    status_meaning: str,
) -> str:
    return (
        "With the lamp output OFF, does the same RGB LED show "
        f"{status_color} status indication ({status_meaning})?"
    )


def lamp_led_power_cycle_expectation(
    lamp_color: str,
    status_color: str,
    status_meaning: str,
) -> str:
    return (
        f"The lamp LED shows {lamp_color} lamp output, changes to "
        f"{status_color} status indication when the lamp output is switched "
        f"off, shows {lamp_color} lamp output again when switched on, then "
        f"returns to {status_color} status indication when switched off. "
        f"{status_color} means {status_meaning}."
    )


@allure.step("Set Beacon power to {expected_power} and verify status")
def ensure_lamp_power(
    driver: DeviceDriver,
    expected_power: str,
) -> dict[str, Any]:
    if expected_power not in {"on", "off"}:
        raise ValueError(f"Unsupported Beacon state: {expected_power}")

    status = driver.lamp_status()
    if status["lamp"] == expected_power:
        return status

    lines = driver.lamp_on() if expected_power == "on" else driver.lamp_off()
    assert any(f"[BEACON] {expected_power}" in line for line in lines), (
        f"Could not set Beacon {expected_power}: {lines}"
    )

    status = driver.lamp_status()
    assert status["lamp"] == expected_power, (
        f"Expected Beacon {expected_power}, got: {status}"
    )
    return status


@allure.step("Verify Beacon status fields: {expected}")
def assert_lamp_status(
    driver: DeviceDriver,
    expected: Mapping[str, Any],
    *,
    status: dict[str, Any] | None = None,
    context: str = "Beacon status",
) -> dict[str, Any]:
    actual = driver.lamp_status() if status is None else status
    for field, expected_value in expected.items():
        actual_value = actual.get(field)
        assert actual_value == expected_value, (
            f"{context}: expected {field}={expected_value!r}, "
            f"got {actual_value!r} in {actual}"
        )
    return actual


@allure.step("Verify Beacon is ON with an active auto-off timer")
def assert_lamp_timer_active(
    driver: DeviceDriver,
    *,
    status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    actual = assert_lamp_status(
        driver,
        {"lamp": "on"},
        status=status,
        context="Beacon with auto-off timer active",
    )
    assert actual["timer_s"] > 0, (
        f"Expected an active auto-off timer, got {actual}"
    )
    return actual


@allure.step("Turn Beacon OFF from a confirmed ON state")
def turn_lamp_off_from_on(driver: DeviceDriver) -> dict[str, Any]:
    ensure_lamp_power(driver, "on")
    lines = driver.lamp_off()
    assert any("[BEACON] off" in line for line in lines), (
        f"Expected a real ON-to-OFF transition, got: {lines}"
    )
    return assert_lamp_status(
        driver,
        {"lamp": "off"},
        context="Beacon after OFF command",
    )


@allure.step(
    "Establish status LED state: Wi-Fi connected={connected}, logged in={logged_in}"
)
def establish_status_led_state(
    driver: DeviceDriver,
    *,
    connected: bool,
    logged_in: bool,
    firmware_version: str,
) -> None:
    if not logged_in:
        driver.logout()

    if not connected:
        disconnect_lines = driver.wifi_disconnect()
        assert any(
            "[LINK] disconnected" in line or "W115" in line
            for line in disconnect_lines
        ), f"Wi-Fi disconnect was not confirmed: {disconnect_lines}"

    wifi_status = driver.wifi_status()
    assert wifi_status["connected"] is connected, (
        f"Expected Wi-Fi connected={connected}, got {wifi_status}"
    )
    identity = driver.whoami()
    assert identity["logged_in"] is logged_in, (
        f"Expected logged_in={logged_in}, got {identity}"
    )
    state_lines = [
        line for line in wifi_status["raw"] if "state:" in line.casefold()
    ]
    assert state_lines and "normal" in state_lines[-1].casefold(), (
        "Status LED mapping is only checked in NORMAL state; "
        f"got status lines: {state_lines}"
    )
    if firmware_version == "2.3.0":
        watch_lines = [
            line for line in wifi_status["raw"] if "watch:" in line.casefold()
        ]
        assert any("disarmed" in line.casefold() for line in watch_lines), (
            "Status LED mapping requires Guard disarmed; "
            f"got status lines: {watch_lines}"
        )


@allure.step(
    "Configure Beacon ON: {color}, {brightness}% brightness, {mode} mode"
)
def configure_lamp_output(
    driver: DeviceDriver,
    color: str | tuple[int, int, int],
    expected_rgb: tuple[int, int, int],
    brightness: int,
    mode: str,
) -> dict[str, Any]:
    ensure_lamp_power(driver, "on")

    color_lines = driver.lamp_set_color(color)
    if isinstance(color, str):
        expected_color_response = (
            f"[BEACON] color: {color.casefold()} "
            f"({expected_rgb[0]},{expected_rgb[1]},{expected_rgb[2]})"
        )
    else:
        expected_rgb = color
        expected_color_response = (
            f"[BEACON] color: ({color[0]},{color[1]},{color[2]})"
        )
    assert any(expected_color_response in line for line in color_lines), (
        f"Expected {expected_color_response!r}, got: {color_lines}"
    )

    brightness_lines = driver.lamp_set_brightness(brightness)
    assert any(
        f"[BEACON] brightness: {brightness}%" in line
        for line in brightness_lines
    ), f"Could not set Beacon brightness to {brightness}%: {brightness_lines}"

    mode_lines = driver.lamp_set_mode(mode)
    assert any(f"[BEACON] mode: {mode}" in line for line in mode_lines), (
        f"Could not set Beacon mode to {mode}: {mode_lines}"
    )

    status = driver.lamp_status()
    assert status["lamp"] == "on", f"Beacon is not ON after configuration: {status}"
    assert status["color"] == expected_rgb, (
        f"Expected Beacon color {expected_rgb}, got: {status}"
    )
    assert status["brightness"] == brightness, (
        f"Expected Beacon brightness {brightness}%, got: {status}"
    )
    assert status["mode"] == mode, f"Expected Beacon mode {mode}, got: {status}"
    return status


@allure.step("Restore the original Beacon settings and power state")
def _restore_lamp_state(
    driver: DeviceDriver,
    initial_status: dict[str, Any],
) -> None:
    driver.lamp_set_timer(0)
    ensure_lamp_power(driver, "on")
    driver.lamp_set_color(initial_status["color"])
    driver.lamp_set_brightness(initial_status["brightness"])
    driver.lamp_set_mode(initial_status["mode"])
    if initial_status["lamp"] == "off":
        off_lines = driver.lamp_off()
        assert any("[BEACON] off" in line for line in off_lines), (
            f"Could not restore Beacon OFF state: {off_lines}"
        )

    restored_status = driver.lamp_status()
    assert restored_status["lamp"] == initial_status["lamp"], (
        f"Expected Beacon power state {initial_status['lamp']}, "
        f"got {restored_status}"
    )
    assert restored_status["color"] == initial_status["color"], (
        f"Expected Beacon color {initial_status['color']}, got {restored_status}"
    )
    assert restored_status["brightness"] == initial_status["brightness"], (
        f"Expected Beacon brightness {initial_status['brightness']}%, "
        f"got {restored_status}"
    )
    assert restored_status["mode"] == initial_status["mode"], (
        f"Expected Beacon mode {initial_status['mode']}, got {restored_status}"
    )
    assert restored_status["timer_s"] == 0, (
        f"Expected Beacon timer to be off after restoration, got {restored_status}"
    )


@allure.step("Restore Wi-Fi, login session, and original Beacon state")
def cleanup_lamp_test_state(
    driver: DeviceDriver,
    initial_status: dict[str, Any],
    *,
    ensure_authenticated_device: Callable[[DeviceDriver], None] | None = None,
    primary_failed: bool = False,
) -> None:
    cleanup_actions = [
        (
            "Restore Wi-Fi and authenticated session",
            None
            if ensure_authenticated_device is None
            else lambda: ensure_authenticated_device(driver),
        ),
        (
            "Restore original Beacon state",
            lambda: _restore_lamp_state(driver, initial_status),
        ),
    ]
    cleanup_errors: list[tuple[str, BaseException]] = []
    for step_name, action in cleanup_actions:
        if action is None:
            continue
        try:
            with allure.step(step_name):
                action()
        except (Exception, pytest.fail.Exception) as error:
            cleanup_errors.append((step_name, error))

    if not cleanup_errors:
        return

    details = "\n".join(
        f"{step_name}: {error}" for step_name, error in cleanup_errors
    )
    if primary_failed:
        allure.attach(
            f"Cleanup failed after the primary test failure:\n{details}",
            name="Lamp/session cleanup failures",
            attachment_type=allure.attachment_type.TEXT,
        )
        return
    raise RuntimeError(f"Lamp/session cleanup failed:\n{details}") from cleanup_errors[0][1]
