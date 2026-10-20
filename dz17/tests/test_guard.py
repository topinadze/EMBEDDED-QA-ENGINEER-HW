from __future__ import annotations

import re
from typing import Any

import allure
import pytest

from drivers.device_driver import DeviceDriver
from manual_checks import SoftChecks, prepare_observation


def _watch_guard_status(driver: DeviceDriver) -> tuple[str, int, float]:
    lines = driver.guard_status()
    for line in lines:
        match = re.search(
            r"\[WATCH\]\s*(disarmed|arming|armed|intrusion|alarm),\s*"
            r"zone\s*(\d+)\s*cm,\s*last distance\s*([-+]?\d+(?:\.\d+)?)\s*cm",
            line,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).casefold(), int(match.group(2)), float(match.group(3))
    raise AssertionError(f"Could not parse Guard state, zone, and distance: {lines!r}")


def _cleanup_guard_panic(
    driver: DeviceDriver,
    guard_pin: str,
    uart_mark: int,
    soft: SoftChecks,
) -> None:
    with allure.step("Disarm Guard and restore relay and system state"):
        try:
            guard_state, _, _ = _watch_guard_status(driver)
            disarm_lines = (
                driver.guard_disarm(guard_pin)
                if guard_state != "disarmed"
                else []
            )
            guard_state, _, _ = _watch_guard_status(driver)
            soft.check(
                guard_state == "disarmed"
                and (
                    not disarm_lines
                    or any("disarmed" in line.casefold() for line in disarm_lines)
                ),
                f"Could not disarm Guard: {disarm_lines}; status={guard_state}",
            )
        finally:
            try:
                close_lines = driver.relay_off()
                soft.check(
                    any("[VALVE] CLOSED" in line or "W601" in line for line in close_lines),
                    f"Could not close relay: {close_lines}",
                )
            finally:
                try:
                    if driver.get_state()[0] != 1:
                        reset_lines = driver.set_state(1)
                        soft.check(
                            any("NORMAL" in line.upper() for line in reset_lines),
                            f"Could not restore NORMAL state: {reset_lines}",
                        )
                finally:
                    try:
                        guard_state, _, _ = _watch_guard_status(driver)
                        soft.check(
                            guard_state == "disarmed",
                            f"Guard remains active after cleanup: {guard_state}",
                        )
                    finally:
                        try:
                            relay = driver.relay_status()
                            soft.check(
                                relay["state"] == "CLOSED",
                                f"Relay remains open after cleanup: {relay}",
                            )
                        finally:
                            try:
                                system_state = driver.get_state()
                                soft.check(
                                    system_state == (1, "NORMAL"),
                                    "System did not return to NORMAL: "
                                    f"{system_state}",
                                )
                            finally:
                                _acknowledge_guard_panic_alert(driver, uart_mark, soft)


def _acknowledge_guard_panic_alert(
    driver: DeviceDriver, uart_mark: int, soft: SoftChecks
) -> None:
    panic_output = "\n".join(driver.uart_log[uart_mark:])
    alert_match = re.search(
        r"\[CIC\s+#(\d+)\s+CRITICAL\]",
        panic_output,
        re.IGNORECASE,
    )
    if not alert_match:
        soft.check(
            "CRITICAL" not in panic_output.upper(),
            "Could not identify the critical alert ID for cleanup",
        )
        return

    alert_id = alert_match.group(1)
    listed_alerts = driver.alert_list()
    alert_id_pattern = re.compile(rf"(?<!\d)#{re.escape(alert_id)}(?!\d)")
    matching_alerts = [
        line for line in listed_alerts if alert_id_pattern.search(line)
    ]
    if not matching_alerts:
        soft.check(
            False,
            f"Critical alert #{alert_id} was not present during cleanup: {listed_alerts}",
        )
        return

    if any("*" in line for line in matching_alerts):
        pending_alert_lines = [
            line
            for line in listed_alerts
            if re.search(r"#\d+\b", line) and "*" in line
        ]
        latest_match = (
            re.search(r"#(\d+)\b", pending_alert_lines[-1])
            if pending_alert_lines
            else None
        )
        latest_pending_id = latest_match.group(1) if latest_match else None
        if latest_pending_id != alert_id:
            soft.check(
                False,
                "Cannot safely use ACK latest for Guard cleanup: "
                f"test alert is #{alert_id}, latest pending alert is "
                f"#{latest_pending_id}: {listed_alerts}",
            )
            return

        ack_lines = driver.alert_ack()
        soft.check(
            any(
                re.search(
                    rf"\[CIC\]\s+#?{re.escape(alert_id)}\s+acknowledged\b",
                    line,
                    re.IGNORECASE,
                )
                for line in ack_lines
            ),
            f"Latest ACK did not acknowledge critical alert #{alert_id}: {ack_lines}",
        )
        verified_alerts = driver.alert_list()
        remaining_alerts = [
            line
            for line in verified_alerts
            if f"#{alert_id}" in line and "*" in line
        ]
        soft.check(
            not remaining_alerts,
            f"Critical alert #{alert_id} remains unacknowledged: {remaining_alerts}",
        )


@allure.epic("SENTRY SWM-2")
@allure.feature("SENTRY Guard")
@pytest.mark.guard
class TestGuard:
    @staticmethod
    def _require_23(firmware_version: str) -> None:
        if firmware_version != "2.3.0":
            pytest.skip("SENTRY Guard functional behavior is available starting in firmware 2.3.0.")

    @staticmethod
    def _watch_status(driver: DeviceDriver) -> tuple[str, int, float]:
        return _watch_guard_status(driver)

    @allure.story("GD-1 Guard status")
    @allure.title("Report Guard disarmed state and configured zone")
    def test_guard_status_or_planned_response(
        self,
        authenticated_device: DeviceDriver,
        firmware_version: str,
    ) -> None:
        driver = authenticated_device
        lines = driver.guard_status()
        if firmware_version == "2.1.0":
            assert any("E099" in line for line in lines), (
                f"Expected E099 for Guard command on firmware 2.1.0, got: {lines}"
            )
            return

        state, zone, last_distance = self._watch_status(driver)
        assert state == "disarmed", f"Guard should start disarmed; got: {lines}"
        assert 10 <= zone <= 200, f"Guard zone must be in 10-200 cm; got: {zone}"
        assert last_distance >= -1, f"Unexpected last distance value: {last_distance}"

    @allure.story("GD-2 Guard zone limits")
    @allure.title("Reject Guard zones outside 10-200 cm: {zone_cm} cm")
    @pytest.mark.negative
    @pytest.mark.parametrize("zone_cm", [9, 201], ids=["below-minimum", "above-maximum"])
    def test_guard_rejects_out_of_range_zone(
        self,
        authenticated_device: DeviceDriver,
        firmware_version: str,
        zone_cm: int,
    ) -> None:
        driver = authenticated_device
        lines = driver.guard_set_zone(zone_cm)
        if firmware_version == "2.1.0":
            assert any("E099" in line for line in lines), (
                f"Expected E099 for Guard command on firmware 2.1.0, got: {lines}"
            )
            return
        assert any("E808" in line for line in lines), (
            f"Expected E808 for Guard zone {zone_cm} cm, got: {lines}"
        )

    @allure.story("GD-2 Guard zone boundaries")
    @allure.title("Accept Guard zone boundaries and restore prior zone")
    @pytest.mark.positive
    @pytest.mark.persistent
    def test_guard_accepts_zone_boundaries(
        self,
        authenticated_device: DeviceDriver,
        firmware_version: str,
    ) -> None:
        self._require_23(firmware_version)
        driver = authenticated_device
        initial_state, initial_zone, _ = self._watch_status(driver)
        assert initial_state == "disarmed", (
            f"Guard zone boundary test requires disarmed state, got {initial_state}"
        )
        try:
            for zone_cm in (10, 200):
                with allure.step(f"Set and read back the valid {zone_cm} cm zone boundary"):
                    lines = driver.guard_set_zone(zone_cm)
                    assert any(str(zone_cm) in line and "zone" in line.casefold() for line in lines), (
                        f"Expected acknowledgement for Guard zone {zone_cm} cm, got: {lines}"
                    )
                    state, actual_zone, _ = self._watch_status(driver)
                    assert state == "disarmed" and actual_zone == zone_cm, (
                        f"Expected disarmed zone {zone_cm} cm; got {state}, {actual_zone} cm"
                    )
        finally:
            with allure.step(f"Restore original Guard zone {initial_zone} cm"):
                restore_lines = driver.guard_set_zone(initial_zone)
                assert not any("E808" in line for line in restore_lines), (
                    f"Could not restore original Guard zone: {restore_lines}"
                )
                final_state, final_zone, _ = self._watch_status(driver)
                assert final_state == "disarmed" and final_zone == initial_zone, (
                    f"Guard zone cleanup failed; expected {initial_zone} cm, "
                    f"got {final_state}, {final_zone} cm"
                )

    @allure.story("GD-1 Guard arming and disarming")
    @allure.title("Arm Guard after exit delay and disarm with the configured PIN")
    @pytest.mark.interactive
    @pytest.mark.persistent
    def test_guard_arm_exit_delay_and_disarm(
        self,
        authenticated_device: DeviceDriver,
        firmware_version: str,
        guard_pin: str,
        manual_prepare: Any,
        soft: SoftChecks,
    ) -> None:
        self._require_23(firmware_version)
        driver = authenticated_device
        initial_state, _, _ = self._watch_status(driver)
        assert initial_state == "disarmed", (
            f"Guard arming test requires a disarmed Guard, got {initial_state}"
        )

        arm_may_be_active = False
        try:
            prepare_observation(
                manual_prepare,
                action=(
                    "Keep the sonar field clear and do not approach the sensor while the "
                    "Guard arms for 10 seconds."
                ),
                expected=(
                    "UART reports the arming countdown followed by ARMED, with no intrusion "
                    "or alarm."
                ),
                duration="~12 seconds",
            )
            with allure.step("Start Guard arming and wait for the 10-second exit delay"):
                mark = driver.buffer_len()
                arm_may_be_active = True
                lines = driver.guard_arm(timeout=0.8)
                soft.check(
                    any(
                        re.search(r"arming in\s+10\s*s", line, re.IGNORECASE)
                        for line in lines
                    ),
                    f"Expected the 10-second Guard arming countdown, got: {lines}",
                )
                armed_reported = driver.wait_for(
                    "ARMED", timeout=12.0, since_index=mark
                )
                soft.check(
                    armed_reported,
                    "Guard did not report ARMED after the exit delay: "
                    f"{driver.uart_log[mark:]}",
                )
                state, _, _ = self._watch_status(driver)
                soft.check(state == "armed", f"Expected Guard ARMED state, got: {state}")

            with allure.step("Disarm Guard using the locally configured PIN"):
                lines = driver.guard_disarm(guard_pin)
                soft.check(
                    any("disarmed" in line.casefold() for line in lines),
                    f"Expected Guard disarm acknowledgement, got: {lines}",
                )
                state, _, _ = self._watch_status(driver)
                soft.check(
                    state == "disarmed",
                    f"Guard did not return to disarmed: {state}",
                )
                arm_may_be_active = state != "disarmed"
        finally:
            if arm_may_be_active:
                with allure.step("Disarm Guard during failure cleanup"):
                    lines = driver.guard_disarm(guard_pin)
                    disarmed = any("disarmed" in line.casefold() for line in lines)
                    state, _, _ = self._watch_status(driver)
                    soft.check(
                        disarmed and state == "disarmed",
                        f"Guard cleanup could not disarm the system: {lines}; "
                        f"final state={state}",
                    )
        soft.assert_all()

    @allure.story("GD-3 Guard panic alarm and AL-5 critical effects")
    @allure.title("Guard panic raises a critical alert and opens the relay")
    @pytest.mark.interactive
    @pytest.mark.persistent
    def test_guard_panic_raises_alarm_and_critical_effects(
        self,
        authenticated_device: DeviceDriver,
        firmware_version: str,
        guard_pin: str,
        manual_prepare: Any,
        manual_check: Any,
        soft: SoftChecks,
    ) -> None:
        self._require_23(firmware_version)
        driver = authenticated_device
        guard_state, _, _ = self._watch_status(driver)
        relay = driver.relay_status()
        system_state = driver.get_state()
        assert guard_state == "disarmed", f"Start with Guard disarmed, got {guard_state}"
        assert relay["state"] == "CLOSED" and relay["auto"] == "off", (
            f"Start with relay closed and auto off, got {relay}"
        )
        assert system_state == (1, "NORMAL"), (
            f"Critical-effect test requires NORMAL state, got {system_state}"
        )

        alarm_may_be_active = False
        uart_mark: int | None = None
        try:
            prepare_observation(
                manual_prepare,
                action="Observe the relay and built-in RGB LED; do not press any buttons.",
                expected=(
                    "Guard panic raises ALARM and a CRITICAL CIC alert, opens the relay, "
                    "and changes NORMAL to VERBOSE; observe the relay and red/blue alarm LED."
                ),
                duration="~5 seconds",
            )
            uart_mark = driver.buffer_len()
            with allure.step("Trigger the Guard panic alarm"):
                alarm_may_be_active = True
                lines = driver.guard_panic(timeout=1.0)
                soft.check(
                    any("ALARM" in line.upper() for line in lines),
                    f"Expected Guard alarm acknowledgement, got: {lines}",
                )

            with allure.step("Verify the critical alert, relay, and system-state effects"):
                critical_reported = driver.wait_for(
                    "CRITICAL", timeout=2.0, since_index=uart_mark
                )
                soft.check(
                    critical_reported,
                    "Guard panic did not create a CRITICAL alert: "
                    f"{driver.uart_log[uart_mark:]}",
                )
                guard_state, _, _ = self._watch_status(driver)
                relay = driver.relay_status()
                system_state = driver.get_state()
                soft.check(
                    guard_state == "alarm",
                    f"Expected Guard ALARM state, got {guard_state}",
                )
                soft.check(
                    relay["state"] == "OPEN",
                    f"Expected relay OPEN during alarm, got {relay}",
                )
                soft.check(
                    system_state == (3, "VERBOSE"),
                    f"Critical alert should change NORMAL to VERBOSE, got {system_state}",
                )

            with allure.step("Confirm physical relay and alarm indication"):
                soft.check(
                    manual_check(
                        "Did you hear the relay open and observe the built-in LED's "
                        "red/blue alarm indication?"
                    ),
                    "Operator did not confirm the physical alarm effects",
                )
        finally:
            if alarm_may_be_active and uart_mark is not None:
                _cleanup_guard_panic(driver, guard_pin, uart_mark, soft)
        soft.assert_all()

    @allure.story("§12 K4 hold / GD-3 Guard panic alarm")
    @allure.title("Hold K4 for 1.5 seconds to trigger Guard PANIC")
    @pytest.mark.buttons
    @pytest.mark.interactive
    @pytest.mark.persistent
    def test_k4_hold_triggers_panic_alarm(
        self,
        authenticated_device: DeviceDriver,
        firmware_version: str,
        guard_pin: str,
        manual_prepare: Any,
        manual_check: Any,
        soft: SoftChecks,
    ) -> None:
        self._require_23(firmware_version)
        driver = authenticated_device
        guard_state, _, _ = self._watch_status(driver)
        relay = driver.relay_status()
        system_state = driver.get_state()
        assert guard_state == "disarmed", (
            f"K4 PANIC test requires Guard disarmed, got {guard_state}"
        )
        assert relay["state"] == "CLOSED" and relay["auto"] == "off", (
            f"K4 PANIC test requires relay closed with auto off, got {relay}"
        )
        assert system_state == (1, "NORMAL"), (
            f"K4 PANIC test requires NORMAL system state, got {system_state}"
        )

        alarm_may_be_active = False
        uart_mark: int | None = None
        try:
            prepare_observation(
                manual_prepare,
                action="Press and hold physical button K4 for at least 1.5 seconds, then release.",
                expected=(
                    "UART reports the K4 press and a CRITICAL alert; Guard enters ALARM, "
                    "the relay opens, and system state changes to VERBOSE. Observe the "
                    "relay click and the built-in LED's red/blue alarm indication."
                ),
                duration="Hold K4 for 1.5 seconds; observe alarm effects for ~5 seconds.",
            )
            uart_mark = driver.buffer_len()
            with allure.step("Wait for the physical K4 hold and PANIC alert"):
                alarm_may_be_active = True
                button_events = driver.wait_for_all(
                    ("[BTN] K4 pressed", "CRITICAL"),
                    timeout=15.0,
                    since_index=uart_mark,
                )
                soft.check(
                    button_events["[BTN] K4 pressed"],
                    "Physical K4 press was not detected in UART: "
                    f"{driver.uart_log[uart_mark:]}",
                )
                soft.check(
                    button_events["CRITICAL"],
                    "K4 hold did not produce a CRITICAL alert: "
                    f"{driver.uart_log[uart_mark:]}",
                )
                alert_match = re.search(
                    r"\[CIC\s+#(\d+)\s+CRITICAL\]",
                    "\n".join(driver.uart_log[uart_mark:]),
                    re.IGNORECASE,
                )
                soft.check(
                    alert_match is not None,
                    "Could not identify the CRITICAL alert created by K4 PANIC: "
                    f"{driver.uart_log[uart_mark:]}",
                )

            with allure.step("Verify Guard alarm and critical-alert effects"):
                guard_state, _, _ = self._watch_status(driver)
                relay = driver.relay_status()
                system_state = driver.get_state()
                soft.check(
                    guard_state == "alarm",
                    f"Expected Guard ALARM after K4 hold, got {guard_state}",
                )
                soft.check(
                    relay["state"] == "OPEN",
                    f"Expected relay OPEN during K4 PANIC, got {relay}",
                )
                soft.check(
                    system_state == (3, "VERBOSE"),
                    "K4 PANIC critical alert should change NORMAL to VERBOSE, "
                    f"got {system_state}",
                )
                if alert_match is not None:
                    alert_id = alert_match.group(1)
                    alerts = driver.alert_list()
                    matching_alerts = [
                        line
                        for line in alerts
                        if re.search(rf"(?<!\d)#{re.escape(alert_id)}(?!\d)", line)
                    ]
                    soft.check(
                        matching_alerts
                        and any("*" in line for line in matching_alerts),
                        f"CRITICAL alert #{alert_id} should be listed as pending: {alerts}",
                    )

            with allure.step("Confirm physical relay and alarm indication"):
                soft.check(
                    manual_check(
                        "Did you hear the relay open and observe the built-in LED's "
                        "red/blue alarm indication?"
                    ),
                    "Operator did not confirm the physical K4 PANIC effects",
                )
        finally:
            if alarm_may_be_active and uart_mark is not None:
                _cleanup_guard_panic(driver, guard_pin, uart_mark, soft)
        soft.assert_all()
