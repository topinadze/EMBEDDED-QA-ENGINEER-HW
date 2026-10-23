from __future__ import annotations

import re
import sys
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

pytestmark = [
    allure.parent_suite("DZ17"),
    allure.suite("Operator Panel Buttons"),
    allure.epic("SENTRY SWM-2"),
    allure.feature("Operator Panel Buttons"),
]


@allure.sub_suite("Button interaction scenarios")
@pytest.mark.buttons
@pytest.mark.interactive
class TestButtons:
    @staticmethod
    def _alert_lines_for_id(lines: list[str], alert_id: str) -> list[str]:
        alert_id_pattern = re.compile(rf"(?<!\d)#{re.escape(alert_id)}(?!\d)")
        return [line for line in lines if alert_id_pattern.search(line)]

    @allure.story("§12 Login prerequisite for buttons")
    @allure.title("Verify button action is rejected when logged out")
    def test_button_unauthenticated_blocked(
        self,
        authenticated_device: DeviceDriver,
        ensure_authenticated_device: Callable[[DeviceDriver], None],
        manual_prepare: Any,
        manual_check: Any,
        soft: SoftChecks,
    ) -> None:
        driver = authenticated_device
        try:
            self._verify_unauthenticated_button_rejection(
                driver, manual_prepare, manual_check, soft
            )
        finally:
            primary_error = sys.exc_info()[1]
            try:
                with allure.step("Restore authenticated session"):
                    ensure_authenticated_device(driver)
            except Exception as cleanup_error:
                if primary_error is None:
                    raise
                allure.attach(
                    f"Authentication restoration failed after the primary test failure: "
                    f"{cleanup_error}",
                    name="Authentication cleanup failure",
                    attachment_type=allure.attachment_type.TEXT,
                )

    @allure.step("Verify button rejection while logged out")
    def _verify_unauthenticated_button_rejection(
        self,
        driver: DeviceDriver,
        manual_prepare: Any,
        manual_check: Any,
        soft: SoftChecks,
    ) -> None:
        wifi_status = driver.wifi_status()
        link_lines = [
            line.casefold()
            for line in wifi_status["raw"]
            if "link:" in line.casefold()
        ]
        assert link_lines, (
            f"Could not determine Wi-Fi state before logout: {wifi_status['raw']}"
        )
        latest_link = link_lines[-1]
        connected = "buoy link '" in latest_link or "connected (" in latest_link
        disconnected = "buoy link down" in latest_link
        assert connected != disconnected, (
            f"Unrecognized Wi-Fi link response: {link_lines}"
        )
        assert wifi_status["connected"] is connected, (
            f"Wi-Fi status parser disagrees with its latest link response: "
            f"{wifi_status}"
        )
        lamp_status = driver.lamp_status()
        assert lamp_status["lamp"] == "off", (
            "Turn the main Beacon lamp OFF before checking its status LED; "
            f"got: {lamp_status}"
        )
        expected_status = status_indicator_description(
            is_connected=wifi_status["connected"],
            is_logged_in=False,
        )

        prepare_observation(
            manual_prepare,
            action=(
                "Watch the built-in RGB status LED. This test logs out, then asks "
                "you to press K1 once briefly."
            ),
            expected=(
                f"{STATUS_INDICATOR_LEGEND} After logout, the status LED should "
                f"show {expected_status}. The rejected K1 press should leave it "
                "unchanged; UART emits 'E003 login required'."
            ),
            duration="~5 seconds",
        )

        with allure.step("Log out of current session"):
            driver.logout()
            identity = driver.whoami()
            logged_out_confirmed = any(
                "not logged in" in line.casefold() for line in identity["raw"]
            )
            assert logged_out_confirmed and not identity["logged_in"], (
                f"Logout did not take effect: {identity}"
            )
            post_logout_wifi = driver.wifi_status()
            assert post_logout_wifi["connected"] is wifi_status["connected"], (
                "Wi-Fi connection changed during logout: "
                f"before={wifi_status}, after={post_logout_wifi}"
            )

        soft.check(
            manual_check(
                f"{STATUS_INDICATOR_LEGEND} After logout, does the built-in RGB "
                f"status LED show {expected_status}?"
            ),
            f"Status LED was not physically observed as "
            f"{expected_status} after logout",
        )

        prepare_observation(
            manual_prepare,
            action="Press button K1 once briefly while logged out.",
            expected=(
                f"{STATUS_INDICATOR_LEGEND} UART emits 'E003 login required'; "
                f"the status LED remains {expected_status}."
            ),
            duration="~5 seconds",
        )

        mark = len(driver.uart_log)
        with allure.step("Wait for button press and E003 rejection in UART"):
            pressed = driver.wait_for("[BTN] K1 pressed", timeout=10.0, since_index=mark)
            assert pressed, "Button K1 press event not detected in UART"
            e003_seen = driver.wait_for("E003", timeout=2.0, since_index=mark)
            assert e003_seen, "Expected error E003 for button press while logged out"

        soft.check(
            manual_check(
                f"{STATUS_INDICATOR_LEGEND} After the rejected K1 press, does "
                f"the status LED still show {expected_status}?"
            ),
            "Status LED color changed after the unauthenticated K1 press",
        )
        soft.assert_all()

    @allure.story("§12 K1 Button Tap - Lamp toggle")
    @allure.title("K1 tap toggles Beacon lamp on and off")
    def test_button_k1_tap_toggle_lamp(
        self,
        authenticated_device: DeviceDriver,
        manual_prepare: Any,
        manual_check: Any,
        soft: SoftChecks,
    ) -> None:
        driver = authenticated_device
        initial_status = driver.lamp_status()
        expected_next = "on" if initial_status["lamp"] == "off" else "off"

        mark = len(driver.uart_log)
        prepare_observation(
            manual_prepare,
            action="Press button K1 once briefly",
            expected=f"Beacon lamp physically turns {expected_next.upper()}",
            duration="~5 seconds",
        )

        with allure.step(f"Wait for K1 press and Beacon {expected_next} in UART"):
            pressed = driver.wait_for("[BTN] K1 pressed", timeout=12.0, since_index=mark)
            assert pressed, "Button K1 press event was not detected in UART"
            beacon_toggled = driver.wait_for(f"[BEACON] {expected_next}", timeout=3.0, since_index=mark)
            assert beacon_toggled, f"Expected '[BEACON] {expected_next}' in UART"
            status = driver.lamp_status()
            assert status["lamp"] == expected_next, (
                f"Expected Beacon lamp status {expected_next}, got: {status}"
            )
            expected_rgb = status["color"]

        soft.check(
            manual_check(
                f"Did the Beacon lamp physically turn {expected_next.upper()}? "
                f"Expected lamp color: RGB {expected_rgb}."
            ),
            f"Physical Beacon lamp did not switch to {expected_next}",
        )
        soft.assert_all()

    @allure.story("§12 K1 Button Hold - Next color")
    @allure.title("K1 tap turns lamp on; three holds advance Beacon color")
    def test_button_k1_hold_next_color(
        self,
        authenticated_device: DeviceDriver,
        manual_prepare: Any,
        manual_check: Any,
        soft: SoftChecks,
    ) -> None:
        driver = authenticated_device
        with allure.step("Set a known color and switch Beacon lamp OFF"):
            color_lines = driver.lamp_set_color("blue")
            assert any("color: blue" in line.casefold() for line in color_lines), (
                f"Could not set Beacon lamp to blue: {color_lines}"
            )
            driver.lamp_off()
            initial_status = driver.lamp_status()
            assert initial_status["lamp"] == "off", (
                f"Could not confirm Beacon lamp is off before K1 tap: {initial_status}"
            )
            assert initial_status["color"] == (0, 0, 255), (
                f"Could not confirm blue starting color before K1 tap: {initial_status}"
            )

        prepare_observation(
            manual_prepare,
            action="Press button K1 once briefly to turn the Beacon lamp ON.",
            expected="The Beacon lamp turns ON and remains blue (RGB 0, 0, 255).",
            duration="~5 seconds",
        )

        mark = len(driver.uart_log)
        with allure.step("Verify brief K1 press turns the Beacon lamp ON"):
            pressed = driver.wait_for("[BTN] K1 pressed", timeout=12.0, since_index=mark)
            assert pressed, "K1 press event was not detected in UART"
            turned_on = driver.wait_for("[BEACON] on (K1)", timeout=3.0, since_index=mark)
            assert turned_on, "UART did not report Beacon lamp turning on from K1"
            status = driver.lamp_status()
            assert status["lamp"] == "on" and status["color"] == (0, 0, 255), (
                "Brief K1 press should turn on the blue Beacon lamp; "
                f"got: {status}"
            )

        soft.check(
            manual_check(
                "Did the Beacon lamp physically turn ON and show blue "
                "(RGB 0, 0, 255)?",
                expected_rgb=(0, 0, 255),
                expected_color="blue",
            ),
            "Beacon lamp did not physically turn on blue after the brief K1 press",
        )

        previous_color = status["color"]
        for press_number in range(1, 4):
            prepare_observation(
                manual_prepare,
                action=(
                    f"Press and HOLD button K1 for 1.5 to 2 seconds, then release "
                    f"(color-cycle press {press_number} of 3)."
                ),
                expected=(
                    "The Beacon lamp stays ON and advances to a color different "
                    "from its previous color."
                ),
                duration="~5 seconds",
            )

            mark = len(driver.uart_log)
            with allure.step(
                f"Verify K1 color-cycle press {press_number} changes Beacon color"
            ):
                long_pressed = driver.wait_for(
                    "[BTN] K1 long press", timeout=12.0, since_index=mark
                )
                assert long_pressed, (
                    f"K1 long-press event {press_number} was not detected in UART"
                )
                color_changed = driver.wait_for("by K1", timeout=3.0, since_index=mark)
                assert color_changed, (
                    f"UART did not report a Beacon color change on K1 hold "
                    f"{press_number}"
                )
                color_events = [
                    line
                    for line in driver.uart_log[mark:]
                    if "[BEACON] color:" in line and "by K1" in line
                ]
                assert color_events, (
                    f"UART did not provide a K1 Beacon color event for hold "
                    f"{press_number}"
                )
                status = driver.lamp_status()
                assert status["lamp"] == "on", (
                    f"Beacon lamp should remain on after K1 hold {press_number}: "
                    f"{status}"
                )
                reported_rgb = (
                    f"({status['color'][0]},{status['color'][1]},"
                    f"{status['color'][2]})"
                )
                assert any(reported_rgb in line for line in color_events), (
                    f"K1 UART color event does not match lamp status after hold "
                    f"{press_number}: event={color_events}, status={status}"
                )
                assert status["color"] != previous_color, (
                    f"Beacon color did not change on K1 hold {press_number}: "
                    f"before={previous_color}, after={status['color']}"
                )
                expected_rgb = status["color"]

            soft.check(
                manual_check(
                    "Did the Beacon lamp physically change to its reported next "
                    f"color (RGB {expected_rgb}) after K1 hold {press_number}?",
                    expected_rgb=expected_rgb,
                ),
                f"Physical Beacon lamp did not change color on K1 hold {press_number}",
            )
            previous_color = expected_rgb

        soft.assert_all()

    @allure.story("§12 K2 Button Tap - Relay toggle")
    @allure.title("K2 tap toggles Valve relay open and closed")
    @pytest.mark.persistent
    def test_button_k2_tap_toggle_relay(
        self,
        authenticated_device: DeviceDriver,
        manual_prepare: Any,
        manual_check: Any,
        soft: SoftChecks,
    ) -> None:
        driver = authenticated_device
        initial_status = driver.relay_status()
        initial_state = initial_status["state"]
        assert initial_state in {"OPEN", "CLOSED"}, (
            f"Could not determine initial relay state: {initial_status}"
        )
        assert initial_status["auto"] == "off", (
            f"K2 relay toggle requires automatic relay control off: {initial_status}"
        )
        expected_state = "OPEN" if initial_status["state"] == "CLOSED" else "CLOSED"

        try:
            mark = len(driver.uart_log)
            prepare_observation(
                manual_prepare,
                action="Press button K2 once briefly",
                expected=f"Relay clicks and switches state to {expected_state}",
                duration="~5 seconds",
            )

            with allure.step(f"Wait for K2 press and [VALVE] {expected_state} in UART"):
                pressed = driver.wait_for("[BTN] K2 pressed", timeout=12.0, since_index=mark)
                assert pressed, "Button K2 press event was not detected in UART"
                valve_toggled = driver.wait_for(
                    f"[VALVE] {expected_state} (K2)", timeout=3.0, since_index=mark
                )
                assert valve_toggled, f"Expected '[VALVE] {expected_state} (K2)' in UART"

            soft.check(
                manual_check(f"Did you hear/observe the relay switch to {expected_state}?"),
                f"Physical relay did not switch to {expected_state}",
            )
            soft.assert_all()
        finally:
            with allure.step("Restore the relay's initial state"):
                time.sleep(0.55)
                current_status = driver.relay_status()
                if current_status["state"] != initial_state:
                    if initial_state == "OPEN":
                        restore_lines = driver.relay_on()
                    else:
                        restore_lines = driver.relay_off()
                    assert any(
                        f"[VALVE] {initial_state}" in line or "W601" in line
                        for line in restore_lines
                    ), f"Could not restore relay state to {initial_state}: {restore_lines}"
                restored_status = driver.relay_status()
                assert restored_status["state"] == initial_state, (
                    f"Relay state was not restored: expected {initial_state}, got {restored_status}"
                )

    @allure.story("§12 K2 Button Hold - Relay pulse 1s")
    @allure.title("K2 hold (1.5 s) pulses Valve relay for 1 second")
    def test_button_k2_hold_pulse_relay(
        self,
        authenticated_device: DeviceDriver,
        manual_prepare: Any,
        manual_check: Any,
        soft: SoftChecks,
    ) -> None:
        driver = authenticated_device
        with allure.step("Ensure relay is CLOSED"):
            driver.relay_off()

        mark = len(driver.uart_log)
        prepare_observation(
            manual_prepare,
            action="Press and HOLD button K2 for at least 1.5 to 2 seconds, then release",
            expected="Relay opens for 1 second then automatically closes (two audible clicks ~1s apart)",
            duration="~6 seconds",
        )

        with allure.step("Wait for K2 long press and pulse events in UART"):
            long_pressed = driver.wait_for("[BTN] K2 long press", timeout=12.0, since_index=mark)
            assert long_pressed, "K2 long press event was not detected in UART"
            pulse_opened = driver.wait_for("[VALVE] OPEN (K2 pulse)", timeout=3.0, since_index=mark)
            assert pulse_opened, "Expected '[VALVE] OPEN (K2 pulse)' in UART"
            pulse_closed = driver.wait_for("[VALVE] CLOSED (pulse end)", timeout=3.0, since_index=mark)
            assert pulse_closed, "Expected '[VALVE] CLOSED (pulse end)' in UART"

        soft.check(
            manual_check("Did the relay click OPEN and then click CLOSED after 1 second?"),
            "Physical relay 1-second pulse not observed",
        )
        soft.assert_all()

    @allure.story("§12 K3 Button Tap - Sonar 30s stream start and stop")
    @allure.title("K3 starts active sonar sampling and second press stops it")
    def test_button_k3_sonar_stream(
        self,
        authenticated_device: DeviceDriver,
        manual_prepare: Any,
    ) -> None:
        driver = authenticated_device

        mark = len(driver.uart_log)
        prepare_observation(
            manual_prepare,
            action="Press button K3 once to start distance sampling, observe stream in console, then press K3 again to stop",
            expected="Sonar starts active pinging every 500 ms; second K3 press stops pinging",
            duration="~10 seconds",
        )

        stream_may_be_active = True
        try:
            with allure.step("Wait for K3 stream start in UART"):
                started = driver.wait_for(
                    "[SONAR] active pinging for 30 s", timeout=12.0, since_index=mark
                )
                assert started, "Sonar stream did not start on K3 press"

            with allure.step("Wait for second K3 press and stream termination"):
                stopped = driver.wait_for(
                    "[SONAR] pinging stopped (K3)", timeout=15.0, since_index=mark
                )
                assert stopped, "Sonar stream did not stop on second K3 press"
                stream_may_be_active = False
        finally:
            if stream_may_be_active:
                with allure.step("Teardown: stop a possibly active K3 sonar stream"):
                    stop_lines = driver.distance_stop()
                    assert any(
                        "[SONAR] pinging stopped" in line or "W710" in line
                        for line in stop_lines
                    ), f"Could not verify sonar stream teardown: {stop_lines}"

    @allure.story("§12 K4 Button - Alert acknowledgement")
    @allure.title("K4 tap acknowledges latest alert on 2.3.0; returns E099 on 2.1.0")
    @pytest.mark.persistent
    def test_button_k4_tap_acknowledges_latest_alert_or_returns_e099(
        self,
        authenticated_device: DeviceDriver,
        firmware_version: str,
        manual_prepare: Any,
    ) -> None:
        driver = authenticated_device
        alert_id: str | None = None
        try:
            if firmware_version == "2.1.0":
                prepare_observation(
                    manual_prepare,
                    action="Press button K4 once briefly.",
                    expected="UART reports 'E099 K4: perimeter watch is planned in v2.3.0'.",
                    duration="~5 seconds",
                )
                mark = len(driver.uart_log)
                with allure.step("Verify K4 returns the planned E099 response"):
                    pressed = driver.wait_for(
                        "[BTN] K4 pressed", timeout=12.0, since_index=mark
                    )
                    assert pressed, "Button K4 press was not detected in UART"
                    e099_seen = driver.wait_for(
                        "E099", timeout=3.0, since_index=mark
                    )
                    assert e099_seen, (
                        "Expected 'E099' planned response for K4 on v2.1.0"
                    )
                    expected_response = (
                        "E099 K4: perimeter watch is planned in v2.3.0"
                    )
                    assert any(
                        expected_response.casefold() in line.casefold()
                        for line in driver.uart_log[mark:]
                    ), (
                        "Expected the documented K4 planned response "
                        f"{expected_response!r} in UART: {driver.uart_log[mark:]}"
                    )
                return

            assert firmware_version == "2.3.0", (
                f"K4 behavior is not defined for firmware {firmware_version}"
            )
            with allure.step("Create a test alert for the K4 acknowledgement"):
                created = driver.alert_test("info")
                for line in created:
                    match = re.search(r"\[CIC\s+#(\d+)\s+INFO\]", line, re.I)
                    if match:
                        alert_id = match.group(1)
                        break
                assert alert_id is not None, (
                    f"Could not identify the created INFO alert: {created}"
                )
                listed = driver.alert_list()
                pending = [
                    line
                    for line in self._alert_lines_for_id(listed, alert_id)
                    if "*" in line
                ]
                assert pending, (
                    f"Test alert #{alert_id} was not listed as unacknowledged: {listed}"
                )

            prepare_observation(
                manual_prepare,
                action="Press button K4 once briefly to acknowledge the latest alert.",
                expected=(
                    f"UART reports the K4 press; test alert #{alert_id} is "
                    "acknowledged and no longer has the pending '*' marker."
                ),
                duration="~5 seconds",
            )
            mark = len(driver.uart_log)
            with allure.step("Verify K4 acknowledges the latest CIC alert"):
                pressed = driver.wait_for(
                    "[BTN] K4 pressed", timeout=12.0, since_index=mark
                )
                assert pressed, "Button K4 press was not detected in UART"
                listed = driver.alert_list()
                matching = self._alert_lines_for_id(listed, alert_id)
                assert matching and not any("*" in line for line in matching), (
                    f"K4 did not acknowledge test alert #{alert_id}: {listed}"
                )
        finally:
            if alert_id is not None:
                with allure.step(f"Ensure test alert #{alert_id} is acknowledged"):
                    listed = driver.alert_list()
                    matching = self._alert_lines_for_id(listed, alert_id)
                    pending = [line for line in matching if "*" in line]
                    if pending:
                        all_pending = [
                            line
                            for line in listed
                            if re.search(r"#\d+\b", line) and "*" in line
                        ]
                        latest_pending_match = (
                            re.search(r"#(\d+)\b", all_pending[-1])
                            if all_pending
                            else None
                        )
                        latest_pending_id = (
                            latest_pending_match.group(1)
                            if latest_pending_match
                            else None
                        )
                        assert latest_pending_id == alert_id, (
                            f"Cannot safely use ACK latest for test alert "
                            f"#{alert_id}; latest pending alert is "
                            f"#{latest_pending_id}: {listed}"
                        )
                        ack_lines = driver.alert_ack()
                        assert not any("E851" in line for line in ack_lines), (
                            f"Could not acknowledge test alert #{alert_id}: {ack_lines}"
                        )
                        assert any(
                            re.search(
                                rf"\[CIC\]\s+#?{re.escape(alert_id)}\s+acknowledged\b",
                                line,
                                re.IGNORECASE,
                            )
                            for line in ack_lines
                        ), (
                            f"Latest ACK did not acknowledge test alert #{alert_id}: "
                            f"{ack_lines}"
                        )
                        listed = driver.alert_list()
                        matching = self._alert_lines_for_id(listed, alert_id)
                    assert matching and not any(
                        "*" in line for line in matching
                    ), f"Test alert #{alert_id} remains pending after cleanup: {listed}"

    @allure.story("§12 Button Pairs - State transitions")
    @allure.title("Button pairs K2+K3 (DEBUG) and K1+K2 (NORMAL)")
    def test_button_pairs_debug_and_normal(
        self,
        authenticated_device: DeviceDriver,
        manual_prepare: Any,
        manual_check: Any,
        soft: SoftChecks,
    ) -> None:
        driver = authenticated_device

        try:
            # Step 1: K2+K3 held for 2s -> state 2 DEBUG
            mark1 = len(driver.uart_log)
            prepare_observation(
                manual_prepare,
                action="Press and HOLD buttons K2 and K3 simultaneously for 2 seconds",
                expected="System transitions to 2 DEBUG state (RGB LED blinks blue)",
                duration="~6 seconds",
            )

            with allure.step("Wait for K2+K3 pair event and transition to DEBUG"):
                debug_entered = driver.wait_for("1 NORMAL -> 2 DEBUG (by buttons)", timeout=15.0, since_index=mark1)
                assert debug_entered, "Did not detect transition to 2 DEBUG on K2+K3 hold"
                state_num, state_name = driver.get_state()
                assert state_num == 2 and state_name == "DEBUG"

            soft.check(
                manual_check("Did the device enter DEBUG state (RGB LED blinking blue)?"),
                "Physical DEBUG indication not observed",
            )

            # Step 2: K1+K2 held for 2s -> state 1 NORMAL
            mark2 = len(driver.uart_log)
            prepare_observation(
                manual_prepare,
                action="Press and HOLD buttons K1 and K2 simultaneously for 2 seconds",
                expected="System transitions back to 1 NORMAL state",
                duration="~6 seconds",
            )

            with allure.step("Wait for K1+K2 pair event and transition to NORMAL"):
                normal_entered = driver.wait_for("[BTN] K1+K2 held 2 s -> state 1", timeout=15.0, since_index=mark2)
                assert normal_entered, "Did not detect transition to 1 NORMAL on K1+K2 hold"
                time.sleep(1.0)
                state_num, state_name = driver.get_state()
                assert state_num == 1 and state_name == "NORMAL"

            soft.check(
                manual_check("Did the device return to NORMAL state?"),
                "Device did not return to NORMAL state",
            )
            soft.assert_all()
        finally:
            with allure.step("Ensure device restored to 1 NORMAL"):
                try:
                    cur_state, _ = driver.get_state()
                    if cur_state != 1:
                        driver.set_state(1)
                except Exception:
                    pass

    @allure.story("§12 / ST-2 Button Pairs - Invalid emergency transition")
    @allure.title("Button pair K4+K1 rejected from NORMAL with error E302")
    def test_button_pair_k4_k1_rejected_from_normal(
        self,
        authenticated_device: DeviceDriver,
        manual_prepare: Any,
    ) -> None:
        driver = authenticated_device
        state_num, _ = driver.get_state()
        assert state_num == 1, "Test precondition requires state 1 NORMAL"

        mark = len(driver.uart_log)
        prepare_observation(
            manual_prepare,
            action="Press and HOLD buttons K4 and K1 simultaneously for 2 seconds",
            expected="Firmware rejects the transition with 'E302 EMERGENCY can be entered only from 3 VERBOSE'",
            duration="~6 seconds",
        )

        with allure.step("Wait for E302 rejection in UART"):
            rejected = driver.wait_for("E302", timeout=15.0, since_index=mark)
            assert rejected, "Expected E302 rejection for K4+K1 from NORMAL"

        with allure.step("Verify state remained 1 NORMAL"):
            state_num_after, state_name_after = driver.get_state()
            assert state_num_after == 1 and state_name_after == "NORMAL"
