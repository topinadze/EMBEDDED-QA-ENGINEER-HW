from __future__ import annotations

import time
from typing import Any, Callable

import allure
import pytest
from drivers.device_driver import DeviceDriver
from manual_checks import SoftChecks, prepare_observation

NAMED_COLORS = [
    ("white", (255, 255, 255)),
    ("red", (255, 0, 0)),
    ("green", (0, 255, 0)),
    ("blue", (0, 0, 255)),
    ("yellow", (255, 180, 0)),
    ("purple", (160, 0, 255)),
    ("cyan", (0, 255, 255)),
    ("orange", (255, 80, 0)),
]

CUSTOM_RGB_COLORS = [
    (255, 0, 0),
    (0, 255, 0),
    (0, 0, 255),
    (224, 0, 0),
    (0, 255, 255),
    (255, 255, 255),
]

@allure.epic("SENTRY SWM-2")
@allure.feature("Beacon Lamp")
@pytest.mark.lamp
class TestLamp:

    @allure.story("LM-1 On, off and toggle state transitions")
    @allure.title("Beacon lamp on/off and toggle controls")
    @pytest.mark.positive
    @pytest.mark.smoke
    def test_lamp_on_off_toggle(self, authenticated_device: DeviceDriver) -> None:
        driver = authenticated_device

        with allure.step("Turn lamp on"):
            lines = driver.lamp_on()
            assert any("[BEACON] on" in line for line in lines)
            status = driver.lamp_status()
            assert status["lamp"] == "on"

        with allure.step("Verify duplicate lamp on returns warning W510"):
            lines_dup = driver.lamp_on()
            assert any("W510" in line for line in lines_dup)

        with allure.step("Turn lamp off"):
            lines_off = driver.lamp_off()
            assert any("[BEACON] off" in line for line in lines_off)
            status = driver.lamp_status()
            assert status["lamp"] == "off"

        with allure.step("Toggle lamp on"):
            lines_toggle_on = driver.lamp_toggle()
            assert any("[BEACON] on" in line for line in lines_toggle_on)
            status = driver.lamp_status()
            assert status["lamp"] == "on"

        with allure.step("Toggle lamp off"):
            lines_toggle_off = driver.lamp_toggle()
            assert any("[BEACON] off" in line for line in lines_toggle_off)
            status = driver.lamp_status()
            assert status["lamp"] == "off"

    @allure.story("LM-2 Named colors")
    @allure.title("Set named color: {color_name}")
    @pytest.mark.positive
    @pytest.mark.parametrize("color_name,expected_rgb", NAMED_COLORS)
    def test_lamp_named_color(
        self,
        authenticated_device: DeviceDriver,
        color_name: str,
        expected_rgb: tuple[int, int, int],
    ) -> None:
        driver = authenticated_device
        with allure.step(f"Set color to {color_name}"):
            lines = driver.lamp_set_color(color_name)
            expected_msg = f"[BEACON] color: {color_name} ({expected_rgb[0]},{expected_rgb[1]},{expected_rgb[2]})"
            assert any(expected_msg in line for line in lines), f"Expected '{expected_msg}' in {lines}"

        with allure.step("Verify lamp status reports configured color"):
            status = driver.lamp_status()
            assert status["color"] == expected_rgb

    @allure.story("LM-2 Custom RGB colors")
    @allure.title("Set custom RGB color: {rgb}")
    @pytest.mark.positive
    @pytest.mark.parametrize("rgb", CUSTOM_RGB_COLORS)
    def test_lamp_rgb_color(
        self,
        authenticated_device: DeviceDriver,
        rgb: tuple[int, int, int],
    ) -> None:
        driver = authenticated_device
        with allure.step(f"Set custom color {rgb}"):
            lines = driver.lamp_set_color(rgb)
            expected_msg = f"[BEACON] color: ({rgb[0]},{rgb[1]},{rgb[2]})"
            assert any(expected_msg in line for line in lines), f"Expected '{expected_msg}' in {lines}"

        with allure.step("Verify lamp status reports configured RGB"):
            status = driver.lamp_status()
            assert status["color"] == rgb

    @allure.story("LM-3 Brightness levels")
    @allure.title("Set brightness level: {level}%")
    @pytest.mark.positive
    @pytest.mark.parametrize("level", [0, 50, 100])
    def test_lamp_brightness(
        self,
        authenticated_device: DeviceDriver,
        level: int,
    ) -> None:
        driver = authenticated_device
        with allure.step(f"Set brightness to {level}%"):
            lines = driver.lamp_set_brightness(level)
            assert any(f"[BEACON] brightness: {level}%" in line for line in lines)

        with allure.step("Verify lamp status reports configured brightness"):
            status = driver.lamp_status()
            assert status["brightness"] == level

    @allure.story("LM-4 Operating modes")
    @allure.title("Set operating mode: {mode}")
    @pytest.mark.positive
    @pytest.mark.parametrize("mode", ["solid", "blink", "breathe", "rainbow"])
    def test_lamp_modes(
        self,
        authenticated_device: DeviceDriver,
        mode: str,
    ) -> None:
        driver = authenticated_device
        with allure.step(f"Set mode to '{mode}'"):
            lines = driver.lamp_set_mode(mode)
            assert any(f"[BEACON] mode: {mode}" in line for line in lines)

        with allure.step("Verify lamp status reports configured mode"):
            status = driver.lamp_status()
            assert status["mode"] == mode

    @allure.story("LM-5 Auto-off timer")
    @allure.title("Timer auto-off expiration turns lamp off")
    @pytest.mark.positive
    def test_lamp_timer_auto_off(self, authenticated_device: DeviceDriver) -> None:
        driver = authenticated_device
        with allure.step("Ensure lamp is ON"):
            driver.lamp_on()

        try:
            with allure.step("Set timer to 5 seconds"):
                lines = driver.lamp_set_timer(5)
                # Note: BUG-003 causes 2.1.0 to output '5 ms' instead of '5 s' on timer start.
                # Unit text correctness is tested in test_lamp_timer_unit_text.
                assert any(
                    "[BEACON] auto-off in 5 s" in line or "[BEACON] auto-off in 5 ms" in line
                    for line in lines
                ), f"Expected timer confirmation, got: {lines}"

            with allure.step("Wait for auto-off expiration"):
                expired = driver.wait_for("[BEACON] off (timer expired)", timeout=8.0)
                assert expired, "Lamp did not expire automatically after 5 seconds"

            with allure.step("Verify status shows lamp off"):
                status = driver.lamp_status()
                assert status["lamp"] == "off"
        finally:
            with allure.step("Teardown lamp"):
                try:
                    driver.lamp_off()
                except Exception:
                    pass

    @allure.story("LM-5 Auto-off timer unit text")
    @allure.title("Timer confirmation message reports seconds unit ('s')")
    @pytest.mark.positive
    def test_lamp_timer_unit_text(
        self,
        authenticated_device: DeviceDriver,
        firmware_version: str,
    ) -> None:
        driver = authenticated_device
        with allure.step("Turn lamp ON"):
            driver.lamp_on()
        try:
            with allure.step("Set timer to 5 seconds"):
                lines = driver.lamp_set_timer(5)
                has_seconds_unit = any("[BEACON] auto-off in 5 s" in line for line in lines)
                has_ms_unit = any("[BEACON] auto-off in 5 ms" in line for line in lines)
                if firmware_version == "2.1.0" and not has_seconds_unit and has_ms_unit:
                    pytest.xfail("BUG-003: Lamp timer-start message reports milliseconds instead of seconds")
                assert has_seconds_unit, f"Expected '[BEACON] auto-off in 5 s' in output, got: {lines}"
        finally:
            with allure.step("Cancel timer and turn lamp off"):
                try:
                    driver.lamp_set_timer(0)
                    driver.lamp_off()
                except Exception:
                    pass

    @allure.story("LM-5 Timer cancellation")
    @allure.title("Cancel running auto-off timer")
    @pytest.mark.positive
    def test_lamp_timer_cancel(self, authenticated_device: DeviceDriver) -> None:
        driver = authenticated_device
        with allure.step("Turn lamp ON"):
            driver.lamp_on()

        with allure.step("Start timer 10 s"):
            driver.lamp_set_timer(10)

        with allure.step("Cancel timer with 0"):
            lines = driver.lamp_set_timer(0)
            assert any("[BEACON] timer cancelled" in line for line in lines)

        with allure.step("Verify timer status is off while lamp remains ON"):
            status = driver.lamp_status()
            assert status["lamp"] == "on"
            assert "off" in status["timer"].casefold()

    @allure.story("LM-6 Scenes")
    @allure.title("Save and restore scene")
    @pytest.mark.positive
    @pytest.mark.persistent
    def test_lamp_scenes(self, authenticated_device: DeviceDriver) -> None:
        driver = authenticated_device
        initial_status = driver.lamp_status()
        assert "off" in initial_status["timer"].casefold(), (
            f"Scene test requires no active lamp timer; got: {initial_status['timer']}"
        )
        try:
            with allure.step("Configure initial state (blue, 100%, solid)"):
                driver.lamp_set_color("blue")
                driver.lamp_set_brightness(100)
                driver.lamp_set_mode("solid")

            with allure.step("Save scene 1"):
                lines = driver.lamp_save_scene(1)
                assert any("[BEACON] scene 1 saved" in line for line in lines)

            with allure.step("Change current settings to yellow, 50%, blink"):
                driver.lamp_set_color("yellow")
                driver.lamp_set_brightness(50)
                driver.lamp_set_mode("blink")

            with allure.step("Load scene 1"):
                lines_load = driver.lamp_load_scene(1)
                assert any("[BEACON] scene 1 loaded" in line for line in lines_load)

            with allure.step("Verify restored settings"):
                status = driver.lamp_status()
                assert status["color"] == (0, 0, 255)
                assert status["brightness"] == 100
                assert status["mode"] == "solid"
        finally:
            with allure.step("Restore lamp output while preserving the saved scene"):
                driver.lamp_set_color(initial_status["color"])
                driver.lamp_set_brightness(initial_status["brightness"])
                driver.lamp_set_mode(initial_status["mode"])
                if initial_status["lamp"] == "on":
                    driver.lamp_on()
                else:
                    driver.lamp_off()

    @allure.story("LM-1 to LM-6 Negative input validation")
    @allure.title("Negative validations: {cmd}")
    @pytest.mark.negative
    @pytest.mark.parametrize(
        "cmd,expected_code",
        [
            ("lamp color fozzy", "E503"),
            ("lamp color 256 0 0", "E502"),
            ("lamp color -1 0 0", "E502"),
            ("lamp brightness 101", "E504"),
            ("lamp brightness -1", "E504"),
            ("lamp mode breath", "E505"),
            ("lamp timer 3601", "E506"),
            ("lamp scene save 4", "E508"),
            ("lamp scene save 0", "E508"),
            ("lamp scene load 3", "E509"),
        ],
    )
    def test_lamp_negative_inputs(
        self,
        authenticated_device: DeviceDriver,
        cmd: str,
        expected_code: str,
    ) -> None:
        driver = authenticated_device
        lines = driver.send_command(cmd)
        assert any(expected_code in line for line in lines), (
            f"Expected error code '{expected_code}' for '{cmd}', got: {lines}"
        )

    @allure.story("LM-7 Persistence across reboot")
    @allure.title("Lamp settings and scene persistence across device reboot")
    @pytest.mark.persistent
    def test_lamp_persistence_after_reboot(
        self,
        authenticated_device: DeviceDriver,
        ensure_authenticated_device: Callable[[DeviceDriver], None],
    ) -> None:
        driver = authenticated_device
        with allure.step("Set target parameters (purple, 75%, breathe)"):
            driver.lamp_set_color("purple")
            driver.lamp_set_brightness(75)
            driver.lamp_set_mode("breathe")
            driver.lamp_save_scene(2)

        with allure.step("Reboot device"):
            assert driver.reboot(timeout=30.0), "Device failed to reboot and return to ready prompt"

        with allure.step("Restore Wi-Fi and configured account session"):
            ensure_authenticated_device(driver)

        with allure.step("Verify persisted lamp settings"):
            status = driver.lamp_status()
            assert status["lamp"] == "off", "PRD LM-1 requires lamp to start OFF after reboot"
            assert status["color"] == (160, 0, 255)
            assert status["brightness"] == 75
            assert status["mode"] == "breathe"

        with allure.step("Verify persisted scene 2"):
            load_lines = driver.lamp_load_scene(2)
            assert any("[BEACON] scene 2 loaded" in line for line in load_lines)

    @allure.story("LM-2 Physical named-color verification")
    @allure.title("Physically verify Beacon color: {color_name}")
    @pytest.mark.interactive
    @pytest.mark.parametrize(
        "color_name,expected_rgb",
        NAMED_COLORS,
        ids=[color_name for color_name, _ in NAMED_COLORS],
    )
    def test_lamp_named_color_visual(
        self,
        authenticated_device: DeviceDriver,
        manual_prepare: Any,
        manual_check: Any,
        soft: SoftChecks,
        color_name: str,
        expected_rgb: tuple[int, int, int],
    ) -> None:
        driver = authenticated_device

        with allure.step("Confirm no Beacon auto-off timer is active"):
            initial_status = driver.lamp_status()
            assert initial_status["timer_s"] == 0, (
                "Physical color check requires the Beacon auto-off timer to be off; "
                f"got {initial_status}"
            )

        prepare_observation(
            manual_prepare,
            action=(
                f"Observe the main Beacon lamp while it is set to {color_name.upper()}; "
                "no auto-off timer is active."
            ),
            expected=(
                f"The lamp shows {color_name.upper()} steadily; "
                f"expected RGB values are {expected_rgb}."
            ),
            duration="~5 seconds",
        )

        with allure.step(f"Set Beacon lamp to {color_name}"):
            driver.lamp_on()
            mode_lines = driver.lamp_set_mode("solid")
            assert any("[BEACON] mode: solid" in line for line in mode_lines), (
                f"Could not set solid display mode: {mode_lines}"
            )
            brightness_lines = driver.lamp_set_brightness(100)
            assert any("[BEACON] brightness: 100%" in line for line in brightness_lines), (
                f"Could not set full brightness: {brightness_lines}"
            )
            color_lines = driver.lamp_set_color(color_name)
            expected_line = (
                f"[BEACON] color: {color_name} "
                f"({expected_rgb[0]},{expected_rgb[1]},{expected_rgb[2]})"
            )
            assert any(expected_line in line for line in color_lines), (
                f"Expected {expected_line!r}, got {color_lines}"
            )
            time.sleep(3.0)
            status = driver.lamp_status()
            assert status["lamp"] == "on"
            assert status["color"] == expected_rgb
            assert status["brightness"] == 100
            assert status["mode"] == "solid"

        soft.check(
            manual_check(
                f"Does the main Beacon lamp look steadily {color_name.upper()} "
                f"(expected RGB {expected_rgb})?"
            ),
            f"Physical Beacon color did not visually match {color_name.upper()} "
            f"(UART expected RGB {expected_rgb})",
        )
        soft.assert_all()

    @allure.story("LM-4 Physical breathe-mode verification")
    @allure.title("Physically verify Beacon breathe mode")
    @pytest.mark.interactive
    def test_lamp_breathe_mode_visual(
        self,
        authenticated_device: DeviceDriver,
        manual_prepare: Any,
        manual_check: Any,
        soft: SoftChecks,
    ) -> None:
        driver = authenticated_device
        prepare_observation(
            manual_prepare,
            action="Observe the main Beacon lamp while it runs in breathe mode.",
            expected="The lamp brightness visibly cycles smoothly up and down.",
            duration="~6 seconds",
        )
        with allure.step("Show breathe mode long enough for visual inspection"):
            driver.lamp_on()
            lines = driver.lamp_set_mode("breathe")
            assert any("[BEACON] mode: breathe" in line for line in lines), (
                f"Firmware did not confirm breathe mode: {lines}"
            )
            time.sleep(5.0)
            status = driver.lamp_status()
            assert status["lamp"] == "on"
            assert status["mode"] == "breathe"
            expected_rgb = status["color"]
            expected_color_name = next(
                (name.upper() for name, rgb in NAMED_COLORS if rgb == expected_rgb),
                None,
            )
            driver.lamp_off()

        expected_color = (
            f"{expected_color_name} (RGB {expected_rgb})"
            if expected_color_name
            else f"RGB {expected_rgb}"
        )
        soft.check(
            manual_check(
                "Did the Beacon lamp visibly breathe in its reported color "
                f"(expected {expected_color}) before it turned off?"
            ),
            "Physical Beacon breathe mode was not observed",
        )
        soft.assert_all()
