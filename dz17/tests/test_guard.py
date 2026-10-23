from __future__ import annotations

import re
import time
from typing import Any, Iterator, Protocol

import allure
import pytest

from drivers.device_driver import DeviceDriver
from manual_checks import SoftChecks, prepare_observation

pytestmark = [
    allure.parent_suite("DZ17"),
    allure.suite("SENTRY Guard"),
    allure.epic("SENTRY SWM-2"),
    allure.feature("SENTRY Guard"),
]


class GuardStatusReader(Protocol):
    uart_log: list[str]

    def guard_status(self) -> list[str]: ...


def _watch_guard_status(driver: GuardStatusReader) -> tuple[str, int, float]:
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


def _distance_reading_cm(lines: list[str]) -> float | None:
    for line in lines:
        match = re.search(
            r"\[SONAR\]\s+ping:\s+echo\s+(\d+(?:\.\d+)?)\s+cm",
            line,
            re.IGNORECASE,
        )
        if match:
            return float(match.group(1))
    return None


@pytest.mark.guard
@pytest.mark.parametrize(
    ("lines", "expected"),
    [
        (["[SONAR] ping: echo 25.0 cm"], 25.0),
        (["E (123) sentry: E702 sonar: out of range"], None),
    ],
    ids=("valid-echo", "no-echo"),
)
@allure.sub_suite("Offline helper checks")
@allure.story("Guard sonar reading")
@allure.title("Parse Guard sonar echo: {param_id}")
def test_guard_sonar_distance_parser(
    lines: list[str], expected: float | None
) -> None:
    assert _distance_reading_cm(lines) == expected


def _wait_for_guard_armed(
    driver: GuardStatusReader, timeout: float
) -> tuple[str, int, float]:
    deadline = time.monotonic() + timeout
    last_status: tuple[str, int, float] | None = None
    while True:
        last_status = _watch_guard_status(driver)
        state, _, _ = last_status
        if state == "armed":
            return last_status
        if state != "arming":
            raise AssertionError(
                f"Expected Guard to remain arming until ARMED, got {last_status}; "
                f"recent UART: {driver.uart_log[-10:]}"
            )
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"Guard did not become ARMED within {timeout} seconds; "
                f"last status was {last_status}; recent UART: {driver.uart_log[-10:]}"
            )


@pytest.mark.guard
@allure.sub_suite("Offline helper checks")
@allure.story("Guard arming state validation")
@allure.title("Wait through the exit delay until Guard reports ARMED")
def test_wait_for_guard_armed_reads_until_exact_armed_state() -> None:
    class StatusDriver:
        uart_log: list[str] = []

        def __init__(self) -> None:
            self.states = iter(("arming", "armed"))
            self.status_reads = 0

        def guard_status(self) -> list[str]:
            self.status_reads += 1
            state = next(self.states)
            return [f"[WATCH] {state}, zone 20 cm, last distance 22.4 cm"]

    driver = StatusDriver()

    assert _wait_for_guard_armed(driver, timeout=1.0) == ("armed", 20, 22.4)
    assert driver.status_reads == 2


@pytest.mark.guard
@allure.sub_suite("Offline helper checks")
@allure.story("Guard arming state validation")
@allure.title("Reject an alarm transition while waiting for Guard to arm")
def test_wait_for_guard_armed_rejects_alarm_transition() -> None:
    class StatusDriver:
        uart_log: list[str] = []

        def __init__(self) -> None:
            self.states = iter(("arming", "alarm"))

        def guard_status(self) -> list[str]:
            state = next(self.states)
            return [f"[WATCH] {state}, zone 20 cm, last distance 19.2 cm"]

    with pytest.raises(AssertionError, match="remain arming until ARMED"):
        _wait_for_guard_armed(StatusDriver(), timeout=1.0)


def _disarm_guard_after_test(
    driver: DeviceDriver, guard_pin: str, soft: SoftChecks
) -> None:
    with allure.step("Verify Guard is disarmed after the alarm scenario"):
        state, _, _ = _watch_guard_status(driver)
        if state != "disarmed":
            lines = driver.guard_disarm(guard_pin)
            soft.check(
                any("disarmed" in line.casefold() for line in lines),
                f"Could not disarm Guard during cleanup: {lines}",
            )
        final_state, _, _ = _watch_guard_status(driver)
        soft.check(
            final_state == "disarmed",
            f"Guard remains active after cleanup: {final_state}",
        )


def _close_relay_after_test(driver: DeviceDriver, soft: SoftChecks) -> None:
    with allure.step("Verify relay is closed after the alarm scenario"):
        relay = driver.relay_status()
        if relay["state"] != "CLOSED":
            lines = driver.relay_off()
            soft.check(
                any("[VALVE] CLOSED" in line for line in lines),
                f"Could not close relay during cleanup: {lines}",
            )
        final_relay = driver.relay_status()
        soft.check(
            final_relay["state"] == "CLOSED",
            f"Relay remains open after cleanup: {final_relay}",
        )


def _restore_normal_after_test(driver: DeviceDriver, soft: SoftChecks) -> None:
    with allure.step("Verify system state is NORMAL after the alarm scenario"):
        state = driver.get_state()
        if state != (1, "NORMAL"):
            lines = driver.set_state(1)
            soft.check(
                any("NORMAL" in line.upper() for line in lines),
                f"Could not restore NORMAL state during cleanup: {lines}",
            )
        final_state = driver.get_state()
        soft.check(
            final_state == (1, "NORMAL"),
            f"System did not return to NORMAL: {final_state}",
        )


@pytest.fixture
def guard_zone_baseline(
    authenticated_device: DeviceDriver,
    firmware_version: str,
) -> Iterator[tuple[DeviceDriver, int]]:
    if firmware_version != "2.3.0":
        pytest.skip("Guard zone boundaries are available starting in firmware 2.3.0.")

    driver = authenticated_device
    with allure.step("Capture the original disarmed Guard zone"):
        initial_state, initial_zone, _ = _watch_guard_status(driver)
        assert initial_state == "disarmed", (
            f"Guard zone test requires DISARMED state, got {initial_state}"
        )

    yield driver, initial_zone

    with allure.step(f"Restore the original Guard zone {initial_zone} cm"):
        state, current_zone, _ = _watch_guard_status(driver)
        assert state == "disarmed", (
            f"Guard must remain disarmed for zone cleanup, got {state}"
        )
        if current_zone != initial_zone:
            lines = driver.guard_set_zone(initial_zone)
            assert any(
                str(initial_zone) in line and "zone" in line.casefold()
                for line in lines
            ), f"Could not restore original Guard zone: {lines}"
        final_state, final_zone, _ = _watch_guard_status(driver)
        assert final_state == "disarmed" and final_zone == initial_zone, (
            f"Guard zone cleanup failed; expected DISARMED/{initial_zone} cm, "
            f"got {final_state}/{final_zone} cm"
        )


@pytest.fixture
def guard_zone_rejection_baseline(
    authenticated_device: DeviceDriver,
    firmware_version: str,
) -> Iterator[tuple[DeviceDriver, tuple[str, int] | None]]:
    driver = authenticated_device
    initial: tuple[str, int] | None = None
    if firmware_version == "2.3.0":
        with allure.step("Capture the original disarmed Guard zone for rejection checks"):
            state, zone_cm, _ = _watch_guard_status(driver)
            assert state == "disarmed", (
                f"Guard zone rejection test requires DISARMED state, got {state}"
            )
            initial = state, zone_cm

    yield driver, initial

    if initial is not None:
        initial_state, initial_zone = initial
        with allure.step(f"Restore Guard zone {initial_zone} cm after rejection check"):
            state, current_zone, _ = _watch_guard_status(driver)
            assert state == "disarmed", (
                f"Guard must remain disarmed during zone cleanup, got {state}"
            )
            if current_zone != initial_zone:
                lines = driver.guard_set_zone(initial_zone)
                assert any(
                    str(initial_zone) in line and "zone" in line.casefold()
                    for line in lines
                ), f"Could not restore Guard zone {initial_zone} cm: {lines}"
            final_state, final_zone, _ = _watch_guard_status(driver)
            assert (final_state, final_zone) == (initial_state, initial_zone), (
                "Guard zone rejection cleanup failed; "
                f"expected {(initial_state, initial_zone)}, "
                f"got {(final_state, final_zone)}"
            )


@pytest.fixture
def guard_safety_session(
    request: pytest.FixtureRequest,
    authenticated_device: DeviceDriver,
    firmware_version: str,
    guard_pin: str,
    soft: SoftChecks,
) -> DeviceDriver:
    if firmware_version != "2.3.0":
        pytest.skip("Guard state-transition tests are available starting in firmware 2.3.0.")

    driver = authenticated_device
    with allure.step("Verify Guard DISARMED, relay CLOSED/auto off, and system NORMAL"):
        guard_state, _, _ = _watch_guard_status(driver)
        relay = driver.relay_status()
        system_state = driver.get_state()
        assert guard_state == "disarmed", (
            f"Guard alarm test requires DISARMED state, got {guard_state}"
        )
        assert relay["state"] == "CLOSED" and relay["auto"] == "off", (
            f"Guard alarm test requires relay CLOSED with auto off, got {relay}"
        )
        assert system_state == (1, "NORMAL"), (
            f"Guard alarm test requires NORMAL state, got {system_state}"
        )

    request.addfinalizer(soft.assert_all)
    request.addfinalizer(lambda: _restore_normal_after_test(driver, soft))
    request.addfinalizer(lambda: _close_relay_after_test(driver, soft))
    request.addfinalizer(lambda: _disarm_guard_after_test(driver, guard_pin, soft))
    return driver


@allure.sub_suite("Device Guard scenarios")
@pytest.mark.guard
class TestGuard:
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
        assert last_distance == -1 or last_distance >= 0, (
            f"Expected no sample (-1 cm) or a non-negative distance, got {last_distance}"
        )

    @allure.story("GD-2 Guard zone limits")
    @allure.title("Reject Guard zones outside 10-200 cm: {zone_cm} cm")
    @pytest.mark.negative
    @pytest.mark.parametrize("zone_cm", [9, 201], ids=["below-minimum", "above-maximum"])
    def test_guard_rejects_out_of_range_zone(
        self,
        guard_zone_rejection_baseline: tuple[
            DeviceDriver, tuple[str, int] | None
        ],
        firmware_version: str,
        zone_cm: int,
    ) -> None:
        driver, baseline = guard_zone_rejection_baseline
        lines = driver.guard_set_zone(zone_cm)
        if firmware_version == "2.1.0":
            assert any("E099" in line for line in lines), (
                f"Expected E099 for Guard command on firmware 2.1.0, got: {lines}"
            )
            return
        assert any("E808" in line for line in lines), (
            f"Expected E808 for Guard zone {zone_cm} cm, got: {lines}"
        )
        assert baseline is not None
        final_state, final_zone, _ = self._watch_status(driver)
        assert (final_state, final_zone) == baseline, (
            "Rejected Guard zone input must not change state or configured zone; "
            f"before={baseline}, after={(final_state, final_zone)}"
        )

    @allure.story("GD-2 Guard zone boundaries")
    @allure.title("Accept Guard zone boundary {zone_cm} cm and restore prior zone")
    @pytest.mark.positive
    @pytest.mark.persistent
    @pytest.mark.parametrize("zone_cm", [10, 200], ids=["minimum", "maximum"])
    def test_guard_accepts_zone_boundaries(
        self,
        guard_zone_baseline: tuple[DeviceDriver, int],
        zone_cm: int,
    ) -> None:
        driver, _ = guard_zone_baseline
        with allure.step(f"Set and read back the valid {zone_cm} cm zone boundary"):
            lines = driver.guard_set_zone(zone_cm)
            assert any(
                str(zone_cm) in line and "zone" in line.casefold()
                for line in lines
            ), f"Expected acknowledgement for Guard zone {zone_cm} cm, got: {lines}"
            state, actual_zone, _ = self._watch_status(driver)
            assert state == "disarmed" and actual_zone == zone_cm, (
                f"Expected disarmed zone {zone_cm} cm; got {state}, {actual_zone} cm"
            )

    @allure.story("GD-1 Guard arming and disarming")
    @allure.title("Arm Guard after exit delay and disarm with the configured PIN")
    @pytest.mark.interactive
    @pytest.mark.persistent
    def test_guard_arm_exit_delay_and_disarm(
        self,
        guard_safety_session: DeviceDriver,
        guard_pin: str,
        manual_prepare: Any,
    ) -> None:
        driver = guard_safety_session
        initial_state, zone_cm, _ = _watch_guard_status(driver)
        assert initial_state == "disarmed", (
            f"Guard arming test requires DISARMED state, got {initial_state}"
        )
        prepare_observation(
            manual_prepare,
            action=(
                f"Before pressing Enter, move every object outside the {zone_cm} cm "
                "Guard zone. Keep the sonar field clear and do not approach the sensor "
                "while Guard arms for 10 seconds."
            ),
            expected=(
                "UART reports the arming countdown followed by ARMED, with no intrusion "
                "or alarm."
            ),
            duration="~12 seconds",
        )
        with allure.step("Verify the sonar confirms the Guard zone is clear"):
            lines = driver.distance()
            reading_cm = _distance_reading_cm(lines)
            if reading_cm is None:
                pytest.skip(
                    "Could not verify a sonar echo before arming; "
                    f"expected a clear reading at or beyond {zone_cm} cm, got: {lines}"
                )
            if reading_cm < zone_cm:
                pytest.skip(
                    f"Sonar precondition not met: measured {reading_cm:.1f} cm "
                    f"inside the {zone_cm} cm Guard zone; move the target away and "
                    "rerun. Guard arming was not started."
                )

        with allure.step("Start Guard arming and wait for the 10-second exit delay"):
            lines = driver.guard_arm(timeout=0.8)
            assert any(
                re.search(r"arming in\s+10\s*s", line, re.IGNORECASE)
                for line in lines
            ), f"Expected the 10-second Guard arming countdown, got: {lines}"
            with allure.step("Read Guard status until ARMED or the 12-second deadline"):
                state, _, _ = _wait_for_guard_armed(driver, timeout=12.0)
                assert state == "armed", (
                    f"Expected Guard ARMED state after exit delay, got: {state}"
                )

        with allure.step("Disarm Guard using the locally configured PIN"):
            lines = driver.guard_disarm(guard_pin)
            assert any("disarmed" in line.casefold() for line in lines), (
                f"Expected Guard disarm acknowledgement, got: {lines}"
            )
            state, _, _ = self._watch_status(driver)
            assert state == "disarmed", (
                f"Guard did not return to disarmed: {state}"
            )

    @allure.story("GD-3 Guard panic alarm and AL-5 critical effects")
    @allure.title("Guard panic raises a critical alert and opens the relay")
    @pytest.mark.interactive
    @pytest.mark.persistent
    def test_guard_panic_raises_alarm_and_critical_effects(
        self,
        guard_safety_session: DeviceDriver,
        manual_prepare: Any,
        manual_check: Any,
        soft: SoftChecks,
    ) -> None:
        driver = guard_safety_session
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
            lines = driver.guard_panic(timeout=1.0)
            soft.check(
                any(
                    "[WATCH] !!! GENERAL ALARM: PANIC command !!!" in line
                    for line in lines
                ),
                "Expected the explicit PANIC-command alarm event, "
                f"got: {lines}",
            )

        with allure.step("Verify the critical alert, relay, and system-state effects"):
            critical_reported = driver.wait_for(
                "[CIC #", timeout=2.0, since_index=uart_mark
            )
            soft.check(
                critical_reported,
                "Guard panic did not create a CRITICAL alert: "
                f"{driver.uart_log[uart_mark:]}",
            )
            alert_match = re.search(
                r"\[CIC\s+#(\d+)\s+CRITICAL\]\s+watch:",
                "\n".join(driver.uart_log[uart_mark:]),
                re.IGNORECASE,
            )
            soft.check(
                alert_match is not None,
                "Guard panic did not emit a CRITICAL CIC alert with an ID: "
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
            if alert_match is not None:
                alert_id = alert_match.group(1)
                alerts = driver.alert_list()
                matching_alerts = [
                    line for line in alerts
                    if re.search(rf"(?<!\d)#{re.escape(alert_id)}(?!\d)", line)
                ]
                soft.check(
                    matching_alerts and any("*" in line for line in matching_alerts),
                    f"CRITICAL alert #{alert_id} should be pending: {alerts}",
                )

        with allure.step("Confirm physical relay and alarm indication"):
            soft.check(
                manual_check(
                    "Did you hear the relay open and observe the built-in LED's "
                    "red/blue alarm indication?"
                ),
                "Operator did not confirm the physical alarm effects",
            )

    @allure.story("§12 K4 hold / GD-3 Guard panic alarm")
    @allure.title("Hold K4 for 1.5 seconds to trigger Guard PANIC")
    @pytest.mark.buttons
    @pytest.mark.interactive
    @pytest.mark.persistent
    def test_k4_hold_triggers_panic_alarm(
        self,
        guard_safety_session: DeviceDriver,
        manual_prepare: Any,
        manual_check: Any,
        soft: SoftChecks,
    ) -> None:
        driver = guard_safety_session
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
            button_events = driver.wait_for_all(
                (
                    "[BTN] K4 long press",
                    "[WATCH] PANIC button (K4)",
                    "CRITICAL",
                ),
                timeout=15.0,
                since_index=uart_mark,
            )
            soft.check(
                button_events["[BTN] K4 long press"],
                "UART did not report the K4 long-press event: "
                f"{driver.uart_log[uart_mark:]}",
            )
            soft.check(
                button_events["[WATCH] PANIC button (K4)"],
                "UART did not associate the PANIC trigger with physical K4: "
                f"{driver.uart_log[uart_mark:]}",
            )
            soft.check(
                button_events["CRITICAL"],
                "K4 hold did not produce a CRITICAL alert: "
                f"{driver.uart_log[uart_mark:]}",
            )
            alert_match = re.search(
                r"\[CIC\s+#(\d+)\s+CRITICAL\]\s+watch:",
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
