from __future__ import annotations

import time
from typing import Any, Callable

import allure
import pytest
from drivers.device_driver import DeviceDriver
from manual_checks import (
    STATUS_INDICATOR_LEGEND,
    SoftChecks,
    prepare_observation,
    status_indicator_description,
)
from tests.lamp_test_helpers import (
    LampState,
    assert_lamp_status as _assert_lamp_status,
    assert_lamp_timer_active as _assert_lamp_timer_active,
    configure_lamp_output as _configure_lamp_output,
    establish_status_led_state as _establish_status_led_state,
    ensure_lamp_power as _ensure_lamp_power,
    lamp_led_off_status_expectation,
    lamp_led_off_status_question,
    lamp_led_power_cycle_expectation,
    turn_lamp_off_from_on as _turn_lamp_off_from_on,
)

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

@allure.epic("SENTRY SWM-2")
@allure.feature("Beacon Lamp")
@pytest.mark.lamp
@pytest.mark.usefixtures("lamp_state")
class TestLamp:

    @allure.story("LM-5 Auto-off timer unit text")
    @allure.title("Physically verify Beacon stays on during timer unit check")
    @pytest.mark.positive
    @pytest.mark.interactive
    @pytest.mark.persistent
    def test_lamp_timer_unit_text(
        self,
        authenticated_device: DeviceDriver,
        firmware_version: str,
        manual_prepare: Any,
        manual_check: Any,
        soft: SoftChecks,
    ) -> None:
        driver = authenticated_device
        prepare_observation(
            manual_prepare,
            action=(
                "The test ensures the Beacon is lit, then starts a 60-second "
                "auto-off timer and checks the timer confirmation text."
            ),
            expected=(
                "The Beacon stays physically lit after the timer starts. The "
                "firmware confirmation should use seconds ('s')."
            ),
            duration="~5 seconds",
        )
        with allure.step("Confirm Beacon is ON before starting its timer"):
            _ensure_lamp_power(driver, "on")
        with allure.step("Set timer to 60 seconds"):
            lines = driver.lamp_set_timer(60)
            has_seconds_unit = any("[BEACON] auto-off in 60 s" in line for line in lines)
            has_ms_unit = any("[BEACON] auto-off in 60 ms" in line for line in lines)
            assert has_seconds_unit or has_ms_unit, (
                f"Expected timer confirmation, got: {lines}"
            )
            _assert_lamp_timer_active(driver)
        soft.check(
            manual_check("After starting the timer, is the main Beacon still lit?"),
            "Beacon was not physically lit after timer start.",
        )
        soft.assert_all()
        with allure.step("Verify timer confirmation uses seconds"):
            if firmware_version == "2.1.0" and not has_seconds_unit and has_ms_unit:
                pytest.xfail("BUG-003: Lamp timer-start message reports milliseconds instead of seconds")
            assert has_seconds_unit, (
                f"Expected '[BEACON] auto-off in 60 s' in output, got: {lines}"
            )

    @allure.story("LM-6 Scenes")
    @allure.title("Save, restore, and physically verify scene output")
    @pytest.mark.positive
    @pytest.mark.interactive
    @pytest.mark.persistent
    def test_lamp_scenes(
        self,
        authenticated_device: DeviceDriver,
        manual_prepare: Any,
        manual_check: Any,
        soft: SoftChecks,
    ) -> None:
        driver = authenticated_device
        prepare_observation(
            manual_prepare,
            action=(
                "The test will set and save scene 1 as BLUE/100%/solid, change "
                "the lit Beacon to YELLOW/50%/blink, then load scene 1. Scene 1 "
                "will be permanently overwritten; its previous contents cannot "
                "be restored. Observe each lit state when prompted."
            ),
            expected=(
                "First BLUE/100%/solid, then YELLOW/50%/blink, then restored "
                "BLUE/100%/solid."
            ),
            duration="~5 seconds per observation",
        )
        with allure.step("Confirm Beacon is ON before configuring scene 1"):
            _configure_lamp_output(driver, "blue", (0, 0, 255), 100, "solid")

        time.sleep(2.0)
        soft.check(
            manual_check(
                "Before saving scene 1, does the lit Beacon look BLUE at 100% "
                "brightness in solid mode?"
            ),
            "Scene 1 source output did not physically appear BLUE/100%/solid.",
        )

        with allure.step("Save scene 1"):
            lines = driver.lamp_save_scene(1)
            assert any("[BEACON] scene 1 saved" in line for line in lines)

        with allure.step("Change current settings to yellow, 50%, blink"):
            _configure_lamp_output(
                driver, "yellow", (255, 180, 0), 50, "blink"
            )

        time.sleep(3.0)
        soft.check(
            manual_check(
                "Before loading scene 1, does the lit Beacon look YELLOW at "
                "50% brightness and visibly blink?"
            ),
            "The changed scene output did not physically appear YELLOW/50%/blink.",
        )

        with allure.step("Load scene 1 while Beacon is ON"):
            lines_load = driver.lamp_load_scene(1)
            assert any("[BEACON] scene 1 loaded" in line for line in lines_load)

        with allure.step("Verify restored settings"):
            status = driver.lamp_status()
            _assert_lamp_status(
                driver,
                {
                    "color": (0, 0, 255),
                    "brightness": 100,
                    "mode": "solid",
                    "lamp": "on",
                },
                status=status,
                context="Loaded scene 1",
            )

        with allure.step("Verify the restored scene while Beacon remains ON"):
            time.sleep(3.0)
            status = driver.lamp_status()
            _assert_lamp_status(
                driver,
                {
                    "lamp": "on",
                    "color": (0, 0, 255),
                    "brightness": 100,
                    "mode": "solid",
                },
                status=status,
                context="Scene 1 output after settling",
            )

        soft.check(
            manual_check(
                "After loading scene 1, does the main Beacon look steadily "
                "BLUE at 100% brightness in solid mode?"
            ),
            "The saved scene did not look physically BLUE, full-brightness, "
            "and steady.",
        )
        soft.assert_all()

    @allure.story("LM-1 to LM-6 Negative input validation")
    @allure.title("Reject invalid lamp commands without changing Beacon output")
    @pytest.mark.negative
    @pytest.mark.interactive
    @pytest.mark.persistent
    def test_lamp_negative_inputs(
        self,
        authenticated_device: DeviceDriver,
        manual_prepare: Any,
        manual_check: Any,
        soft: SoftChecks,
    ) -> None:
        invalid_commands = [
            ("lamp color fozzy", "E503"),
            ("lamp color 256 0 0", "E502"),
            ("lamp color -1 0 0", "E502"),
            ("lamp color 0 256 0", "E502"),
            ("lamp color 0 -1 0", "E502"),
            ("lamp color 0 0 256", "E502"),
            ("lamp color 0 0 -1", "E502"),
            ("lamp brightness 101", "E504"),
            ("lamp brightness -1", "E504"),
            ("lamp mode breath", "E505"),
            ("lamp scene save 4", "E508"),
            ("lamp scene save 0", "E508"),
            ("lamp scene load 4", "E508"),
            ("lamp scene load 0", "E508"),
        ]
        driver = authenticated_device
        prepare_observation(
            manual_prepare,
            action=(
                "The test ensures the Beacon is lit, then sends invalid color, "
                "brightness, mode, and scene-index commands. Watch the main "
                "Beacon for any unexpected visible change."
            ),
            expected=(
                "The Beacon remains lit with its original visible output after "
                "all invalid commands are rejected."
            ),
            duration="~15 seconds",
        )
        with allure.step("Confirm Beacon is ON before checking rejected input"):
            _ensure_lamp_power(driver, "on")
        state_before_invalid = _assert_lamp_status(
            driver,
            {"lamp": "on"},
            context="Beacon before invalid input",
        )
        time.sleep(2.0)
        soft.check(
            manual_check(
                "Before invalid commands are sent, is the main Beacon visibly lit?"
            ),
            "The Beacon was not physically lit before invalid-input checks.",
        )

        for cmd, expected_code in invalid_commands:
            with allure.step(f"Reject invalid command: {cmd}"):
                lines = driver.send_command(cmd)
                soft.check(
                    any(expected_code in line for line in lines),
                    f"Expected error code '{expected_code}' for {cmd!r}, got: {lines}",
                )

                with allure.step("Verify rejected command preserves Beacon settings"):
                    status = driver.lamp_status()
                    unchanged_fields = (
                        "lamp",
                        "color",
                        "brightness",
                        "mode",
                        "timer_s",
                    )
                    unchanged = all(
                        status.get(field) == state_before_invalid[field]
                        for field in unchanged_fields
                    )
                    soft.check(
                        unchanged,
                        f"Beacon state changed after invalid command {cmd!r}: "
                        f"before={state_before_invalid}, after={status}",
                    )

        time.sleep(2.0)
        soft.check(
            manual_check(
                "After all invalid commands, is the main Beacon still visibly "
                "lit with the same output as before?"
            ),
            "Invalid commands changed the Beacon's visible output.",
        )
        soft.assert_all()

    @allure.story("LM-5 Timer boundaries")
    @allure.title("Reject out-of-range timer values without changing Beacon output")
    @pytest.mark.negative
    @pytest.mark.interactive
    @pytest.mark.persistent
    def test_lamp_timer_rejects_out_of_range(
        self,
        authenticated_device: DeviceDriver,
        manual_prepare: Any,
        manual_check: Any,
        soft: SoftChecks,
    ) -> None:
        driver = authenticated_device
        invalid_timer_values = [-1, 3601]
        prepare_observation(
            manual_prepare,
            action=(
                "The test ensures the Beacon is lit and tries timer values "
                "-1 and 3601 seconds. Watch the Beacon while both are rejected."
            ),
            expected=(
                "Both commands return E506 and the Beacon remains lit with its "
                "timer inactive."
            ),
            duration="~5 seconds",
        )
        with allure.step("Confirm Beacon is ON before testing invalid timer"):
            _ensure_lamp_power(driver, "on")
        status_before_invalid = _assert_lamp_status(
            driver,
            {"lamp": "on"},
            context="Beacon before invalid timer",
        )
        time.sleep(2.0)
        soft.check(
            manual_check("Before invalid timers are sent, is the Beacon visibly lit?"),
            "The Beacon was not physically lit before invalid timer checks.",
        )
        for seconds in invalid_timer_values:
            with allure.step(f"Reject invalid {seconds}-second timer"):
                lines = driver.lamp_set_timer(seconds)
                soft.check(
                    any("E506" in line for line in lines),
                    f"Expected E506 for timer {seconds}, got: {lines}",
                )
                _assert_lamp_status(
                    driver,
                    {
                        "lamp": status_before_invalid["lamp"],
                        "timer_s": status_before_invalid["timer_s"],
                    },
                    context=f"Beacon after invalid {seconds}s timer",
                )
        time.sleep(2.0)
        soft.check(
            manual_check(
                "After both invalid timer commands, is the Beacon still lit "
                "with no timer running?"
            ),
            "An invalid timer command changed the Beacon's visible state.",
        )
        soft.assert_all()

    @allure.story("LM-5 Timer boundaries")
    @allure.title("Accept maximum timer boundary: 3600 seconds")
    @pytest.mark.positive
    @pytest.mark.interactive
    @pytest.mark.persistent
    def test_lamp_timer_accepts_boundary_values(
        self,
        authenticated_device: DeviceDriver,
        firmware_version: str,
        manual_prepare: Any,
        manual_check: Any,
        soft: SoftChecks,
    ) -> None:
        driver = authenticated_device
        prepare_observation(
            manual_prepare,
            action=(
                "The test ensures the Beacon is lit, then starts the maximum "
                "3600-second auto-off timer."
            ),
            expected=(
                "The maximum timer is accepted and the Beacon remains visibly lit."
            ),
            duration="~5 seconds",
        )
        with allure.step("Confirm Beacon is ON before starting boundary timer"):
            _ensure_lamp_power(driver, "on")
        _assert_lamp_status(
            driver,
            {"timer_s": 0},
            context="Beacon before boundary timer",
        )
        lines = driver.lamp_set_timer(3600)
        expected_seconds = "[BEACON] auto-off in 3600 s"
        expected_known_2_1_0_bug = "[BEACON] auto-off in 3600 ms"
        assert any(expected_seconds in line for line in lines) or (
            firmware_version == "2.1.0"
            and any(expected_known_2_1_0_bug in line for line in lines)
        ), f"3600-second timer boundary was not accepted: {lines}"

        status = driver.lamp_status()
        _assert_lamp_timer_active(driver, status=status)
        assert 0 < status["timer_s"] <= 3600, (
            f"Expected active 3600-second timer, got: {status}"
        )
        soft.check(
            manual_check(
                "After accepting the maximum timer, is the main Beacon still lit?"
            ),
            "The Beacon was not physically lit with the maximum timer active.",
        )
        soft.assert_all()

    @allure.story("LM-5 Timer off-state guard")
    @allure.title("Reject starting auto-off timer while Beacon is off")
    @pytest.mark.negative
    @pytest.mark.interactive
    @pytest.mark.persistent
    def test_lamp_timer_rejected_while_off(
        self,
        authenticated_device: DeviceDriver,
        manual_prepare: Any,
        manual_check: Any,
        soft: SoftChecks,
    ) -> None:
        driver = authenticated_device
        prepare_observation(
            manual_prepare,
            action=(
                "The test sets the Beacon to BLUE/100%/solid, turns its lamp "
                "output off from a confirmed ON state, then attempts to start "
                "a 5-second timer."
            ),
            expected=lamp_led_off_status_expectation(
                "GREEN", "Wi-Fi connected and user logged in"
            ),
            duration="~5 seconds",
        )
        with allure.step("Turn Beacon OFF before checking the E507 guard"):
            _turn_lamp_off_from_on(driver)
        soft.check(
            manual_check(
                lamp_led_off_status_question(
                    "GREEN", "Wi-Fi connected and user logged in"
                )
            ),
            "The lamp LED did not show the GREEN connected/logged-in status "
            "before the E507 timer check.",
        )

        with allure.step("Reject timer start while Beacon is confirmed OFF"):
            lines = driver.lamp_set_timer(5)
            assert any("E507" in line for line in lines), (
                f"Expected E507 when starting a timer with Beacon OFF, got: {lines}"
            )
            _assert_lamp_status(
                driver,
                {"lamp": "off", "timer_s": 0},
                context="Beacon after rejected off-state timer",
            )
        soft.check(
            manual_check(
                lamp_led_off_status_question(
                    "GREEN", "Wi-Fi connected and user logged in"
                )
            ),
            "Rejected timer command changed the lamp LED's connected/logged-in "
            "status indication.",
        )
        soft.assert_all()

    @allure.story("LM-1 Logout and subsequent login")
    @allure.title("Logout turns Beacon off and login does not turn it back on")
    @pytest.mark.positive
    @pytest.mark.interactive
    @pytest.mark.persistent
    def test_lamp_logout_and_relogin_keeps_beacon_off(
        self,
        authenticated_device: DeviceDriver,
        ensure_authenticated_device: Callable[[DeviceDriver], None],
        manual_prepare: Any,
        manual_check: Any,
        soft: SoftChecks,
    ) -> None:
        driver = authenticated_device
        prepare_observation(
            manual_prepare,
            action=(
                "The test sets the lamp LED to BLUE/100%/solid, confirms that "
                "lamp output is lit, then logs out and logs in again. Observe "
                "the same LED before logout, after logout, and after login."
            ),
            expected=(
                "Before logout the LED shows the BLUE lamp output. "
                + lamp_led_off_status_expectation(
                    "ORANGE", "Wi-Fi connected and user logged out"
                )
                + " After login the lamp output remains OFF. "
                + lamp_led_off_status_expectation(
                    "GREEN", "Wi-Fi connected and user logged in"
                )
            ),
            duration="~5 seconds per observation",
        )
        with allure.step("Turn Beacon ON with a known blue output"):
            _configure_lamp_output(driver, "blue", (0, 0, 255), 100, "solid")
        time.sleep(2.0)
        soft.check(
            manual_check(
                "Before logout, does the lamp LED show the BLUE lamp output?"
            ),
            "Lamp LED did not show BLUE before logout.",
        )

        with allure.step("Logout and verify firmware turns Beacon off"):
            logout_mark = len(driver.uart_log)
            logout_lines = driver.logout()
            assert driver.wait_for(
                "[BEACON] off (logout)",
                timeout=2.0,
                since_index=logout_mark,
            ), (
                "Expected logout to turn Beacon off; "
                f"got: {logout_lines}"
            )
            identity = driver.whoami()
            assert not identity["logged_in"], (
                f"Expected logged-out identity after logout: {identity}"
            )
        soft.check(
            manual_check(
                lamp_led_off_status_question(
                    "ORANGE", "Wi-Fi connected and user logged out"
                )
            ),
            "After logout, the lamp LED did not show the expected ORANGE "
            "connected/logged-out status indication.",
        )

        with allure.step("Login again and verify Beacon remains off"):
            ensure_authenticated_device(driver)
            _assert_lamp_status(
                driver,
                {"lamp": "off"},
                context="Beacon after login",
            )
        soft.check(
            manual_check(
                lamp_led_off_status_question(
                    "GREEN", "Wi-Fi connected and user logged in"
                )
            ),
            "After login, the lamp LED did not show the expected GREEN "
            "connected/logged-in status indication.",
        )
        soft.assert_all()

    @allure.story("LM-8 Observed lamp LED status mapping (not a PRD color contract)")
    @allure.title("Verify lamp LED status indication for {state_id}")
    @pytest.mark.interactive
    @pytest.mark.parametrize(
        "connected,logged_in,expected_color,state_id",
        [
            (True, True, "GREEN", "connected-logged-in"),
            (True, False, "ORANGE", "connected-logged-out"),
            (False, True, "RED", "disconnected-logged-in"),
            (False, False, "RED", "disconnected-logged-out"),
        ],
        ids=[
            "connected-logged-in",
            "connected-logged-out",
            "disconnected-logged-in",
            "disconnected-logged-out",
        ],
    )
    def test_lamp_status_led_connection_login_mapping(
        self,
        authenticated_device: DeviceDriver,
        firmware_version: str,
        manual_prepare: Any,
        manual_check: Any,
        soft: SoftChecks,
        connected: bool,
        logged_in: bool,
        expected_color: str,
        state_id: str,
    ) -> None:
        driver = authenticated_device
        expected_description = status_indicator_description(connected, logged_in)
        status_meaning = (
            f"Wi-Fi {'connected' if connected else 'disconnected'} and "
            f"user {'logged in' if logged_in else 'logged out'}"
        )
        prepare_observation(
            manual_prepare,
            action=(
                "The test switches the lamp output OFF (not brightness 0; "
                "turning it off only if needed) before configuring "
                f"Wi-Fi {'connected' if connected else 'disconnected'} and "
                f"session {'logged in' if logged_in else 'logged out'}. "
                "Confirm the board is in NORMAL with Guard disarmed and no higher-"
                "priority status indication active, then observe the same RGB "
                "LED that provides the lamp output."
            ),
            expected=(
                lamp_led_off_status_expectation(expected_color, status_meaning)
                + f" {STATUS_INDICATOR_LEGEND} For this observed mapping, "
                f"expect {expected_description}. This mapping is not a "
                "PRD-defined color contract; higher-priority system indications "
                "must be inactive."
            ),
            duration="~5 seconds per status",
        )

        _ensure_lamp_power(driver, "off")

        with allure.step("Set and verify the requested connection/login state"):
            _establish_status_led_state(
                driver,
                connected=connected,
                logged_in=logged_in,
                firmware_version=firmware_version,
            )

        soft.check(
            manual_check(
                lamp_led_off_status_question(expected_color, status_meaning)
            ),
            f"Lamp RGB LED did not show {expected_color} status for {state_id}",
        )
        soft.assert_all()

    @allure.story("LM-7 Persistence across reboot")
    @allure.title("Physically verify lamp settings and scene persistence after reboot")
    @pytest.mark.interactive
    @pytest.mark.persistent
    def test_lamp_persistence_after_reboot(
        self,
        authenticated_device: DeviceDriver,
        lamp_state: LampState,
        ensure_authenticated_device: Callable[[DeviceDriver], None],
        manual_prepare: Any,
        manual_check: Any,
        soft: SoftChecks,
    ) -> None:
        driver = authenticated_device
        prepare_observation(
            manual_prepare,
            action=(
                "The test will permanently overwrite saved scene 2 and show the "
                "Beacon in yellow/50%/blink, then purple/75%/breathe, before "
                "rebooting. After a "
                "successful reboot and session recovery, teardown restores the "
                "pre-test lamp settings; the previous scene 2 contents cannot be "
                "restored. Watch the Beacon after startup; it should remain OFF "
                "until the test turns it on briefly for the visual check."
            ),
            expected=(
                "Before reboot, observe YELLOW/50%/blink and PURPLE/75%/breathe. "
                "After reboot, the lamp output is OFF and the same RGB LED "
                "shows GREEN status for Wi-Fi connected/user logged in. "
                "After scene 2 load and the lamp is switched ON, observe "
                "YELLOW/50%/blink again. "
                "Teardown restores the "
                "pre-test lamp state after successful device and session recovery."
            ),
            duration="Reboot may take up to 30 seconds; ~5 seconds per observation",
        )

        post_reboot_status: dict[str, Any] | None = None
        with allure.step("Save a distinct scene 2 (yellow, 50%, blink)"):
            _configure_lamp_output(
                driver, "yellow", (255, 180, 0), 50, "blink"
            )
            time.sleep(3.0)
            soft.check(
                manual_check(
                    "Before saving scene 2, does the lit Beacon look YELLOW at "
                    "50% brightness and visibly blink?"
                ),
                "Scene 2 source output did not physically appear YELLOW/50%/blink.",
            )
            scene_lines = driver.lamp_save_scene(2)
            assert any("[BEACON] scene 2 saved" in line for line in scene_lines)

        with allure.step("Set current persistent parameters (purple, 75%, breathe)"):
            _configure_lamp_output(
                driver, "purple", (160, 0, 255), 75, "breathe"
            )
            time.sleep(5.0)
            soft.check(
                manual_check(
                    "Before reboot, does the lit Beacon look PURPLE at 75% "
                    "brightness and visibly breathe?"
                ),
                "Pre-reboot output did not physically appear PURPLE/75%/breathe.",
            )

        with allure.step("Reboot device and wait for the ready response"):
            lamp_state.restore_after_test = False
            lamp_state.cleanup_skip_reason = (
                "Reboot completion and authenticated-session recovery were not "
                "confirmed; cleanup commands must not be sent to an unavailable device."
            )
            assert driver.reboot(timeout=30.0), (
                "Device failed to reboot and return to ready prompt"
            )

        with allure.step("Restore Wi-Fi and configured account session"):
            ensure_authenticated_device(driver)
            lamp_state.restore_after_test = True
            lamp_state.cleanup_skip_reason = None

        with allure.step("Verify persisted settings and OFF state after reboot"):
            post_reboot_status = driver.lamp_status()
            _assert_lamp_status(
                driver,
                {
                    "lamp": "off",
                    "color": (160, 0, 255),
                    "brightness": 75,
                    "mode": "breathe",
                },
                status=post_reboot_status,
                context="Persisted Beacon settings after reboot",
            )
            soft.check(
                manual_check(
                    lamp_led_off_status_question(
                        "GREEN", "Wi-Fi connected and user logged in"
                    )
                ),
                "After reboot, the lamp LED did not show the expected GREEN "
                "connected/logged-in status indication.",
            )

        with allure.step("Load and verify saved scene 2"):
            load_lines = driver.lamp_load_scene(2)
            assert any("[BEACON] scene 2 loaded" in line for line in load_lines)
            status = driver.lamp_status()
            _assert_lamp_status(
                driver,
                {
                    "color": (255, 180, 0),
                    "brightness": 50,
                    "mode": "blink",
                },
                status=status,
                context="Loaded scene 2",
            )

        with allure.step("Turn Beacon ON briefly to verify restored scene physically"):
            on_lines = driver.lamp_on()
            assert any("[BEACON] on" in line for line in on_lines), (
                f"Firmware did not confirm Beacon ON: {on_lines}"
            )
            time.sleep(5.0)
            status = driver.lamp_status()
            _assert_lamp_status(
                driver,
                {
                    "lamp": "on",
                    "color": (255, 180, 0),
                    "brightness": 50,
                    "mode": "blink",
                },
                status=status,
                context="Beacon output while verifying loaded scene",
            )

        soft.check(
            manual_check(
                "After reboot and scene 2 load, did the main Beacon visibly "
                "blink YELLOW at 50% brightness?"
            ),
            "Saved scene 2 was not physically observed as yellow blinking at 50%.",
        )
        soft.assert_all()

    @allure.story("LM-2 Physical named-color verification")
    @allure.title("Beacon lamp displays {color_name}")
    @pytest.mark.interactive
    @pytest.mark.persistent
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


        prepare_observation(
            manual_prepare,
            action=(
                f"The test ensures the Beacon is ON, then sets it to "
                f"{color_name.upper()} while lit; no auto-off timer is active."
            ),
            expected=(
                f"The lamp shows {color_name.upper()} steadily; "
                f"expected RGB values are {expected_rgb}."
            ),
            duration="~5 seconds",
        )

        with allure.step(f"Set Beacon lamp to {color_name}"):
            _configure_lamp_output(
                driver, color_name, expected_rgb, 100, "solid"
            )
            time.sleep(3.0)

        soft.check(
            manual_check(
                f"Does the main Beacon lamp look steadily {color_name.upper()} "
                f"(expected RGB {expected_rgb})?",
                expected_rgb=expected_rgb,
                expected_color=color_name,
            ),
            f"Physical Beacon color did not visually match {color_name.upper()} "
            f"(UART expected RGB {expected_rgb})",
        )
        soft.assert_all()

    @allure.story("LM-1 Physical command verification")
    @allure.title("Physically verify Beacon on, off, and toggle commands")
    @pytest.mark.interactive
    @pytest.mark.persistent
    def test_lamp_commands_visual(
        self,
        authenticated_device: DeviceDriver,
        manual_prepare: Any,
        manual_check: Any,
        soft: SoftChecks,
    ) -> None:
        driver = authenticated_device

        prepare_observation(
            manual_prepare,
            action=(
                "The test will turn the Beacon on, set blue/solid/100% while it is lit, "
                "turn its lamp output off, then issue lamp on, lamp off, lamp toggle "
                "(on), and lamp toggle (off). When the lamp output is off, observe "
                "the status color shown by that same RGB LED."
            ),
            expected=lamp_led_power_cycle_expectation(
                "BLUE",
                "GREEN",
                "Wi-Fi connected and user logged in",
            ),
            duration="~5 seconds per observation",
        )

        with allure.step("Set blue/solid/100% while Beacon is confirmed ON"):
            _configure_lamp_output(driver, "blue", (0, 0, 255), 100, "solid")

        time.sleep(2.0)
        soft.check(
            manual_check(
                "Before the command sequence, does the lamp LED show BLUE "
                "lamp output at full brightness in solid mode?"
            ),
            "Beacon did not physically show the configured blue output.",
        )

        with allure.step("Establish OFF before the command transition sequence"):
            _turn_lamp_off_from_on(driver)
        soft.check(
            manual_check(
                lamp_led_off_status_question(
                    "GREEN", "Wi-Fi connected and user logged in"
                )
            ),
            "The lamp LED did not show the expected GREEN status before the command sequence.",
        )

        transitions = [
            (
                "Turn Beacon on",
                driver.lamp_on,
                "on",
                "Does the lamp LED show BLUE lamp output?",
            ),
            (
                "Turn Beacon off",
                driver.lamp_off,
                "off",
                lamp_led_off_status_question(
                    "GREEN", "Wi-Fi connected and user logged in"
                ),
            ),
            (
                "Toggle Beacon on",
                driver.lamp_toggle,
                "on",
                "Does the lamp LED show BLUE lamp output?",
            ),
            (
                "Toggle Beacon off",
                driver.lamp_toggle,
                "off",
                lamp_led_off_status_question(
                    "GREEN", "Wi-Fi connected and user logged in"
                ),
            ),
        ]
        for step_name, command, expected_state, observation in transitions:
            with allure.step(step_name):
                lines = command()
                assert any(
                    f"[BEACON] {expected_state}" in line for line in lines
                ), f"Expected Beacon {expected_state} response, got: {lines}"
                status = driver.lamp_status()
                _assert_lamp_status(
                    driver,
                    {"lamp": expected_state},
                    status=status,
                    context=f"Beacon after {step_name.casefold()}",
                )
                soft.check(
                    manual_check(
                        observation
                    ),
                    f"Lamp LED did not show the expected {expected_state} state",
                )
                if step_name == "Turn Beacon on":
                    with allure.step("Verify duplicate ON does not change Beacon state"):
                        duplicate_lines = driver.lamp_on()
                        assert any("W510" in line for line in duplicate_lines), (
                            f"Expected W510 for duplicate ON, got: {duplicate_lines}"
                        )
                        _assert_lamp_status(
                            driver,
                            {"lamp": "on"},
                            context="Beacon after duplicate ON",
                        )
        soft.assert_all()

    @allure.story("LM-2 Physical custom RGB verification")
    @allure.title("Physically verify custom RGB color: {rgb}")
    @pytest.mark.interactive
    @pytest.mark.persistent
    @pytest.mark.parametrize(
        "rgb,color_name",
        [
            ((255, 0, 0), "red"),
            ((0, 255, 0), "green"),
            ((0, 0, 255), "blue"),
            ((224, 0, 0), "warm red"),
            ((0, 255, 255), "cyan"),
            ((255, 255, 255), "white"),
        ],
        ids=[
            "primary-red",
            "primary-green",
            "primary-blue",
            "custom-warm-red",
            "custom-cyan",
            "custom-white",
        ],
    )
    def test_lamp_rgb_color_visual(
        self,
        authenticated_device: DeviceDriver,
        manual_prepare: Any,
        manual_check: Any,
        soft: SoftChecks,
        rgb: tuple[int, int, int],
        color_name: str,
    ) -> None:
        driver = authenticated_device
        prepare_observation(
            manual_prepare,
            action=(
                "The test ensures the main Beacon is ON before applying a custom "
                f"RGB value {rgb} at full brightness in solid mode."
            ),
            expected=f"The lamp visibly shows {color_name.upper()}.",
            duration="~5 seconds",
        )

        with allure.step(f"Apply custom RGB value {rgb}"):
            _configure_lamp_output(driver, rgb, rgb, 100, "solid")
            time.sleep(2.0)

        soft.check(
            manual_check(
                f"Does the main Beacon visibly show {color_name.upper()} "
                f"for custom RGB {rgb}?"
            ),
            f"Custom RGB {rgb} did not physically appear {color_name}",
        )
        soft.assert_all()

    @allure.story("LM-3 Physical brightness verification")
    @allure.title("Physically compare Beacon brightness at 100%, 50%, and 0%")
    @pytest.mark.interactive
    @pytest.mark.persistent
    def test_lamp_brightness_visual(
        self,
        authenticated_device: DeviceDriver,
        manual_prepare: Any,
        manual_check: Any,
        soft: SoftChecks,
    ) -> None:
        driver = authenticated_device
        prepare_observation(
            manual_prepare,
            action=(
                "The test ensures the Beacon is ON, sets blue/solid mode while lit, "
                "then changes brightness through 100%, 50%, and 0%."
            ),
            expected=(
                "At 100% it is brightly lit; at 50% it is visibly dimmer; "
                "at 0% it emits no visible Beacon light while UART still reports "
                "the lamp ON."
            ),
            duration="~12 seconds total",
        )

        with allure.step("Set known blue/solid output while Beacon is ON"):
            _configure_lamp_output(driver, "blue", (0, 0, 255), 100, "solid")

        observations = [
            (100, "brightly lit"),
            (50, "visibly dimmer than at 100%"),
            (0, "emit no visible Beacon light"),
        ]
        for level, expected_observation in observations:
            with allure.step(f"Set and observe brightness {level}%"):
                lines = driver.lamp_set_brightness(level)
                assert any(
                    f"[BEACON] brightness: {level}%" in line for line in lines
                ), f"Expected brightness {level}% response, got: {lines}"
                status = driver.lamp_status()
                _assert_lamp_status(
                    driver,
                    {"lamp": "on", "brightness": level},
                    status=status,
                    context=f"Physical brightness {level}% UART result",
                )
                soft.check(
                    manual_check(
                        f"At {level}% brightness, does the blue Beacon "
                        f"{expected_observation}?"
                    ),
                    f"Physical Beacon brightness did not match {level}%",
                )
        soft.assert_all()

    @allure.story("LM-4 Physical operating-mode verification")
    @allure.title("Physically verify Beacon mode: {mode}")
    @pytest.mark.interactive
    @pytest.mark.persistent
    @pytest.mark.parametrize(
        "mode,expected_observation",
        [
            ("solid", "remain steadily lit blue"),
            ("blink", "repeatedly switch between lit and dark"),
            ("breathe", "cycle smoothly between dim and bright"),
            ("rainbow", "visibly cycle through changing colors"),
        ],
        ids=["solid", "blink", "breathe", "rainbow"],
    )
    def test_lamp_mode_visual(
        self,
        authenticated_device: DeviceDriver,
        manual_prepare: Any,
        manual_check: Any,
        soft: SoftChecks,
        mode: str,
        expected_observation: str,
    ) -> None:
        driver = authenticated_device
        prepare_observation(
            manual_prepare,
            action=(
                f"The test ensures the main Beacon is ON, then applies {mode} mode "
                "while lit."
            ),
            expected=f"The lamp should {expected_observation}.",
            duration="~8 seconds",
        )

        with allure.step(f"Show Beacon {mode} mode for visual inspection"):
            _configure_lamp_output(driver, "blue", (0, 0, 255), 100, mode)
            time.sleep(6.0)

        soft.check(
            manual_check(
                f"Did the Beacon {mode} mode physically {expected_observation}?"
            ),
            f"Physical Beacon {mode} behavior was not observed",
        )
        soft.assert_all()

    @allure.story("LM-5 Physical auto-off verification")
    @allure.title("Observe lamp LED status after {seconds}-second auto-off timer")
    @pytest.mark.interactive
    @pytest.mark.persistent
    @pytest.mark.parametrize(
        "seconds",
        [1, 5],
        ids=["minimum-1-second", "standard-5-seconds"],
    )
    def test_lamp_timer_auto_off_visual(
        self,
        authenticated_device: DeviceDriver,
        firmware_version: str,
        manual_prepare: Any,
        manual_check: Any,
        soft: SoftChecks,
        seconds: int,
    ) -> None:
        driver = authenticated_device
        prepare_observation(
            manual_prepare,
            action=(
                "The test configures the same RGB LED for BLUE lamp output "
                "and ensures the lamp output is ON before starting a "
                f"{seconds}-second auto-off countdown."
            ),
            expected=(
                "The lamp LED shows BLUE lamp output while the timer is active. "
                f"When the {seconds}-second timer expires, "
                + lamp_led_off_status_expectation(
                    "GREEN", "Wi-Fi connected and user logged in"
                )
            ),
            duration=f"~{max(seconds + 3, 5)} seconds",
        )

        with allure.step(f"Configure and start the {seconds}-second Beacon timer"):
            _configure_lamp_output(driver, "blue", (0, 0, 255), 100, "solid")
            time.sleep(2.0)
            soft.check(
                manual_check(
                    f"Before the {seconds}-second countdown, does the same "
                    "RGB LED show BLUE lamp output?"
                ),
                "The lamp LED did not show BLUE lamp output before timer expiry.",
            )
            mark = len(driver.uart_log)
            timer_lines = driver.lamp_set_timer(seconds)
            has_seconds_unit = any(
                f"[BEACON] auto-off in {seconds} s" in line
                for line in timer_lines
            )
            has_known_2_1_0_unit_bug = (
                firmware_version == "2.1.0"
                and any(
                    f"[BEACON] auto-off in {seconds} ms" in line
                    for line in timer_lines
                )
            )
            assert has_seconds_unit or has_known_2_1_0_unit_bug, (
                f"Expected the {seconds}-second timer confirmation; "
                f"got: {timer_lines}"
            )
            status = driver.lamp_status()
            if seconds == 1 and status["timer_s"] == 0:
                assert driver.wait_for(
                    "[BEACON] off (timer expired)",
                    timeout=3.0,
                    since_index=mark,
                ), "One-second timer reached zero without an expiry event"
                _assert_lamp_status(
                    driver,
                    {"lamp": "off"},
                    status=driver.lamp_status(),
                    context="Beacon after one-second visual timer expiry",
                )
            else:
                _assert_lamp_timer_active(driver, status=status)

        with allure.step("Wait for UART confirmation that the timer expired"):
            expired = driver.wait_for(
                "[BEACON] off (timer expired)",
                timeout=float(seconds + 3),
                since_index=mark,
            )
            assert expired, (
                f"Beacon timer did not expire within {seconds + 3} seconds"
            )
            status = driver.lamp_status()
            _assert_lamp_status(
                driver,
                {"lamp": "off"},
                status=status,
                context="Beacon after visual timer expiry",
            )

        soft.check(
            manual_check(
                lamp_led_off_status_question(
                    "GREEN", "Wi-Fi connected and user logged in"
                )
            ),
            "The lamp LED did not show the expected GREEN status after timer expiry.",
        )
        soft.assert_all()

    @allure.story("LM-5 Physical timer-cancellation verification")
    @allure.title("Physically verify Beacon remains on after timer cancellation")
    @pytest.mark.interactive
    @pytest.mark.persistent
    def test_lamp_timer_cancel_visual(
        self,
        authenticated_device: DeviceDriver,
        firmware_version: str,
        manual_prepare: Any,
        manual_check: Any,
        soft: SoftChecks,
    ) -> None:
        driver = authenticated_device
        prepare_observation(
            manual_prepare,
            action=(
                "The test ensures the blue Beacon is ON before starting a 5-second auto-off "
                "timer, waits about 1 second, cancels it, and observes for a "
                "further 5 seconds."
            ),
            expected=(
                "The Beacon stays lit after cancellation and remains lit beyond "
                "the original timer's expiry time."
            ),
            duration="~8 seconds",
        )

        with allure.step("Start a 5-second timer on a known blue Beacon output"):
            _configure_lamp_output(driver, "blue", (0, 0, 255), 100, "solid")
            time.sleep(2.0)
            soft.check(
                manual_check(
                    "Before starting the timer, is the main Beacon visibly lit BLUE?"
                ),
                "Beacon was not physically lit before timer cancellation.",
            )
            mark = len(driver.uart_log)
            timer_lines = driver.lamp_set_timer(5)
            has_seconds_unit = any(
                "[BEACON] auto-off in 5 s" in line for line in timer_lines
            )
            has_known_2_1_0_unit_bug = firmware_version == "2.1.0" and any(
                "[BEACON] auto-off in 5 ms" in line for line in timer_lines
            )
            assert has_seconds_unit or has_known_2_1_0_unit_bug, (
                f"Expected the 5-second timer confirmation, got: {timer_lines}"
            )
            _assert_lamp_timer_active(driver)

        with allure.step("Cancel the timer before it expires"):
            time.sleep(1.0)
            cancel_lines = driver.lamp_set_timer(0)
            assert any("[BEACON] timer cancelled" in line for line in cancel_lines), (
                f"Expected timer cancellation confirmation, got: {cancel_lines}"
            )
            status = driver.lamp_status()
            _assert_lamp_status(
                driver,
                {"lamp": "on", "timer_s": 0},
                status=status,
                context="Beacon after timer cancellation",
            )

        with allure.step("Observe beyond the original timer deadline"):
            expired = driver.wait_for(
                "[BEACON] off (timer expired)",
                timeout=5.0,
                since_index=mark,
            )
            assert not expired, "Beacon timer expired after cancellation"
            status = driver.lamp_status()
            _assert_lamp_status(
                driver,
                {"lamp": "on", "timer_s": 0},
                status=status,
                context="Beacon after cancelled-timer deadline",
            )

        soft.check(
            manual_check(
                "Did the main Beacon remain visibly lit throughout the "
                "5-second observation after timer cancellation?"
            ),
            "Beacon did not remain physically lit after timer cancellation",
        )
        soft.assert_all()
