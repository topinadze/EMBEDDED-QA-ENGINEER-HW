from __future__ import annotations

import re
import time
from typing import Any

import allure
import pytest

from drivers.device_driver import DeviceDriver
from manual_checks import SoftChecks, prepare_observation


@allure.epic("SENTRY SWM-2")
@allure.feature("Valve Relay")
@pytest.mark.relay
@pytest.mark.persistent
class TestRelay:
    @staticmethod
    def _status(driver: DeviceDriver) -> dict[str, Any]:
        status = driver.relay_status()
        assert any(
            re.search(
                r"\[VALVE\]\s*(?:OPEN|closed),\s*auto\s*(?:on|off),\s*cycles\s*\d+",
                line,
                re.IGNORECASE,
            )
            for line in status["raw"]
        ), (
            f"Expected a parsed relay status response, got: {status['raw']}"
        )
        return status

    @staticmethod
    def _stream_stopped(lines: list[str]) -> bool:
        return any(
            "[SONAR] pinging stopped" in line or "W710" in line
            for line in lines
        )

    @allure.story("RL-1 / RL-2 Relay state and cycle accounting")
    @allure.title("Relay commands change state and count actual transitions")
    @pytest.mark.positive
    def test_relay_commands_and_cycle_count(
        self,
        authenticated_device: DeviceDriver,
        firmware_version: str,
    ) -> None:
        driver = authenticated_device
        initial = self._status(driver)
        assert initial["state"] == "CLOSED", (
            f"Start with the relay closed before testing; got {initial}"
        )
        assert initial["auto"] == "off", (
            f"Start with automatic relay control disabled; got {initial}"
        )
        initial_cycles = initial["cycles"]

        try:
            with allure.step("Open the relay and verify state and cycle count"):
                opened = driver.relay_on()
                assert any("[VALVE] OPEN" in line for line in opened), (
                    f"Expected an OPEN acknowledgement, got: {opened}"
                )
                open_status = self._status(driver)
                assert open_status["state"] == "OPEN"
                actual_cycles = open_status["cycles"]

            with allure.step("Verify repeated OPEN is rejected without changing the count"):
                repeated_on = driver.relay_on()
                assert any("W601" in line for line in repeated_on), (
                    f"Expected W601 for repeated relay on, got: {repeated_on}"
                )
                assert self._status(driver)["cycles"] == actual_cycles

            if firmware_version == "2.1.0" and actual_cycles == initial_cycles + 2:
                pytest.xfail(
                    "BUG-004: firmware 2.1.0 increments relay cycles twice per transition; "
                    "see dz17/REPORT.md"
                )
            assert actual_cycles == initial_cycles + 1, (
                f"One relay transition should add one cycle: "
                f"before={initial_cycles}, after={actual_cycles}"
            )

            time.sleep(0.55)
            with allure.step("Close the relay and verify state"):
                closed = driver.relay_off()
                assert any("[VALVE] CLOSED" in line for line in closed), (
                    f"Expected a CLOSED acknowledgement, got: {closed}"
                )
                closed_status = self._status(driver)
                assert closed_status["state"] == "CLOSED"
                assert closed_status["cycles"] == actual_cycles + 1

            with allure.step("Verify repeated CLOSE is rejected without changing the count"):
                repeated_off = driver.relay_off()
                assert any("W601" in line for line in repeated_off), (
                    f"Expected W601 for repeated relay off, got: {repeated_off}"
                )
                assert self._status(driver)["cycles"] == closed_status["cycles"]

            time.sleep(0.55)
            with allure.step("Toggle the relay open, then leave it closed"):
                toggled = driver.relay_toggle()
                assert any("[VALVE] OPEN" in line for line in toggled), (
                    f"Expected toggle to open relay, got: {toggled}"
                )
                toggle_status = self._status(driver)
                assert toggle_status["state"] == "OPEN"
                assert toggle_status["cycles"] == closed_status["cycles"] + 1
        finally:
            time.sleep(0.55)
            driver.relay_off()
            final_status = self._status(driver)
            assert final_status["state"] == "CLOSED", (
                f"Relay cleanup did not leave it closed: {final_status}"
            )

    @allure.story("RL-3 Relay pulse bounds")
    @allure.title("Accept relay pulse durations {duration_ms} ms")
    @pytest.mark.positive
    @pytest.mark.parametrize("duration_ms", [100, 10000], ids=["minimum", "maximum"])
    def test_relay_pulse_duration_boundaries(
        self,
        authenticated_device: DeviceDriver,
        duration_ms: int,
    ) -> None:
        driver = authenticated_device
        initial = self._status(driver)
        assert initial["state"] == "CLOSED" and initial["auto"] == "off", (
            f"Relay pulse requires closed relay and auto mode off; got {initial}"
        )
        try:
            with allure.step(f"Pulse relay for the valid boundary {duration_ms} ms"):
                lines = driver.relay_pulse(duration_ms)
                assert any("[VALVE] OPEN (pulse)" in line for line in lines), (
                    f"Expected pulse to open relay, got: {lines}"
                )
                assert any("[VALVE] CLOSED (pulse end)" in line for line in lines), (
                    f"Expected pulse to close relay, got: {lines}"
                )
                assert self._status(driver)["state"] == "CLOSED"
        finally:
            time.sleep(0.55)
            driver.relay_off()
            assert self._status(driver)["state"] == "CLOSED", (
                "Pulse boundary cleanup did not leave the relay closed"
            )

    @allure.story("RL-3 Relay pulse bounds")
    @allure.title("Reject relay pulse duration {duration_ms} ms with E603")
    @pytest.mark.negative
    @pytest.mark.parametrize("duration_ms", [99, 10001], ids=["below-minimum", "above-maximum"])
    def test_relay_pulse_rejects_out_of_range_duration(
        self,
        authenticated_device: DeviceDriver,
        firmware_version: str,
        duration_ms: int,
    ) -> None:
        driver = authenticated_device
        initial = self._status(driver)
        assert initial["state"] == "CLOSED" and initial["auto"] == "off", (
            f"Invalid pulse check requires closed relay and auto mode off; got {initial}"
        )
        try:
            with allure.step(f"Reject pulse duration {duration_ms} ms"):
                lines = driver.relay_pulse(duration_ms, timeout=2.0)
                if (
                    duration_ms == 99
                    and firmware_version == "2.1.0"
                    and any("[VALVE] OPEN (pulse)" in line for line in lines)
                ):
                    pytest.xfail(
                        "BUG-006: firmware 2.1.0 accepts a 99 ms pulse; "
                        "see dz17/REPORT.md"
                    )
                assert any("E603" in line for line in lines), (
                    f"Expected E603 for invalid pulse duration {duration_ms} ms, got: {lines}"
                )
                assert self._status(driver)["state"] == "CLOSED"
        finally:
            time.sleep(0.55)
            driver.relay_off()
            assert self._status(driver)["state"] == "CLOSED", (
                "Invalid pulse cleanup did not leave the relay closed"
            )

    @allure.story("RL-3 Relay pulse behavior")
    @allure.title("Reject a pulse while the relay is already open with E604")
    @pytest.mark.negative
    def test_relay_pulse_rejected_when_already_open(
        self,
        authenticated_device: DeviceDriver,
    ) -> None:
        driver = authenticated_device
        initial = self._status(driver)
        assert initial["state"] == "CLOSED" and initial["auto"] == "off", (
            f"Already-open pulse check requires a closed relay and auto mode off; got {initial}"
        )
        try:
            opened = driver.relay_on()
            assert any("[VALVE] OPEN" in line for line in opened), (
                f"Expected relay to open before pulse rejection, got: {opened}"
            )
            time.sleep(0.55)
            lines = driver.relay_pulse(100)
            assert any("E604" in line for line in lines), (
                f"Expected E604 when pulsing an already-open relay, got: {lines}"
            )
        finally:
            time.sleep(0.55)
            driver.relay_off()
            assert self._status(driver)["state"] == "CLOSED", (
                "Already-open pulse cleanup did not leave the relay closed"
            )

    @allure.story("RL-4 Relay schedule bounds")
    @allure.title("Reject relay schedule durations outside 2-3600 seconds")
    @pytest.mark.negative
    @pytest.mark.parametrize(
        ("on_seconds", "off_seconds"),
        [(1, 2), (2, 1), (3601, 2), (2, 3601)],
        ids=["on-below-minimum", "off-below-minimum", "on-above-maximum", "off-above-maximum"],
    )
    def test_relay_schedule_rejects_out_of_range_durations(
        self,
        authenticated_device: DeviceDriver,
        on_seconds: int,
        off_seconds: int,
    ) -> None:
        driver = authenticated_device
        initial = self._status(driver)
        assert initial["state"] == "CLOSED" and initial["auto"] == "off", (
            f"Invalid schedule check requires a closed relay and auto mode off; got {initial}"
        )
        try:
            lines = driver.relay_schedule(on_seconds, off_seconds)
            assert any("E606" in line for line in lines), (
                f"Expected E606 for schedule {on_seconds}/{off_seconds} s, got: {lines}"
            )
            after = self._status(driver)
            assert after["state"] == initial["state"] and after["cycles"] == initial["cycles"], (
                f"Rejected schedule changed relay state or cycle count: before={initial}, after={after}"
            )
        finally:
            driver.relay_schedule_stop()
            time.sleep(0.55)
            driver.relay_off()
            assert self._status(driver)["state"] == "CLOSED", (
                "Invalid schedule cleanup did not leave the relay closed"
            )

    @allure.story("RL-4 Relay schedule stop")
    @allure.title("Warn when stopping an inactive relay schedule")
    @pytest.mark.negative
    def test_relay_schedule_stop_when_inactive(
        self,
        authenticated_device: DeviceDriver,
    ) -> None:
        driver = authenticated_device
        initial = self._status(driver)
        assert initial["auto"] == "off", (
            f"Inactive-schedule check requires automatic control disabled; got {initial}"
        )
        try:
            setup_lines = driver.relay_schedule_stop()
            assert any(
                "[VALVE] schedule stopped" in line or "W605" in line
                for line in setup_lines
            ), f"Could not ensure schedule is inactive before test: {setup_lines}"
            lines = driver.relay_schedule_stop()
            assert any("W605" in line for line in lines), (
                f"Expected W605 for stopping an inactive schedule, got: {lines}"
            )
        finally:
            time.sleep(0.55)
            driver.relay_off()
            final_status = self._status(driver)
            assert final_status["state"] == "CLOSED" and final_status["auto"] == "off", (
                f"Schedule stop cleanup did not leave relay closed with auto off: {final_status}"
            )

    @allure.story("RL-4 Relay schedule behavior")
    @allure.title("Run and stop a minimum-duration relay schedule")
    @pytest.mark.positive
    def test_relay_schedule_minimum_durations(
        self,
        authenticated_device: DeviceDriver,
    ) -> None:
        driver = authenticated_device
        initial = self._status(driver)
        assert initial["state"] == "CLOSED" and initial["auto"] == "off", (
            f"Schedule test requires a closed relay and auto mode off; got {initial}"
        )
        mark = driver.buffer_len()
        try:
            with allure.step("Start a 2-second on / 2-second off relay schedule"):
                lines = driver.relay_schedule(2, 2)
                assert any("[VALVE] schedule: 2 s on / 2 s off" in line for line in lines), (
                    f"Expected schedule acceptance, got: {lines}"
                )
                assert driver.wait_for(
                    "[VALVE] OPEN (schedule)", timeout=2.0, since_index=mark
                ), "Schedule did not open the relay"
                assert driver.wait_for(
                    "[VALVE] CLOSED (schedule)", timeout=3.0, since_index=mark
                ), "Schedule did not close the relay"
        finally:
            with allure.step("Stop the schedule and leave the relay closed"):
                stop_lines = driver.relay_schedule_stop()
                time.sleep(0.55)
                off_lines = driver.relay_off()
                final_status = self._status(driver)
                assert any(
                    "[VALVE] schedule stopped" in line or "W605" in line
                    for line in stop_lines
                ), f"Expected schedule stop or inactive warning, got: {stop_lines}"
                assert any("[VALVE] CLOSED" in line or "W601" in line for line in off_lines), (
                    f"Expected relay-off cleanup acknowledgement, got: {off_lines}"
                )
                assert final_status["state"] == "CLOSED", (
                    f"Schedule cleanup did not leave relay closed: {final_status}"
                )

    @allure.story("RL-6 Relay health")
    @allure.title("Read relay wear and solenoid health")
    @pytest.mark.positive
    def test_relay_health_reports_wear_and_solenoid(
        self,
        authenticated_device: DeviceDriver,
    ) -> None:
        lines = authenticated_device.relay_health()
        output = "\n".join(lines).casefold()
        assert "seal:" in output and "cycles" in output, (
            f"Expected relay wear/cycle health fields, got: {lines}"
        )
        assert "solenoid:" in output and "contact resistance:" in output, (
            f"Expected solenoid and contact-resistance fields, got: {lines}"
        )

    @allure.story("RL-5 Automatic relay control")
    @allure.title("Enable and disable sonar-driven automatic relay control")
    @pytest.mark.positive
    def test_relay_auto_control(
        self,
        authenticated_device: DeviceDriver,
    ) -> None:
        driver = authenticated_device
        initial = self._status(driver)
        assert initial["state"] == "CLOSED" and initial["auto"] == "off", (
            f"Automatic-control test requires a closed relay with auto off; got {initial}"
        )
        try:
            enabled = driver.relay_auto(True)
            assert any("[VALVE] auto on" in line for line in enabled), (
                f"Expected auto-on acknowledgement, got: {enabled}"
            )
            assert self._status(driver)["auto"] == "on"
        finally:
            disabled = driver.relay_auto(False)
            assert any("[VALVE] auto off" in line for line in disabled), (
                f"Expected auto-off cleanup acknowledgement, got: {disabled}"
            )
            time.sleep(0.55)
            driver.relay_off()
            final_status = self._status(driver)
            assert final_status["auto"] == "off" and final_status["state"] == "CLOSED", (
                f"Automatic relay cleanup did not restore safe state: {final_status}"
            )

    @allure.story("RL-5 Automatic relay control")
    @allure.title("Crossing the sonar alarm threshold automatically opens the relay")
    @pytest.mark.interactive
    def test_relay_auto_opens_on_sonar_alarm(
        self,
        authenticated_device: DeviceDriver,
        manual_prepare: Any,
        manual_check: Any,
    ) -> None:
        driver = authenticated_device
        initial = self._status(driver)
        assert initial["state"] == "CLOSED" and initial["auto"] == "off", (
            f"Threshold-crossing test requires a closed relay with auto off; got {initial}"
        )

        stream_may_be_active = False
        mark = driver.buffer_len()
        try:
            prepare_observation(
                manual_prepare,
                action=(
                    "Place a flat target about 40 cm from the sonar sensor and keep the "
                    "sensor path clear. After the stream starts, move the target to about "
                    "20 cm, then back beyond 35 cm."
                ),
                expected=(
                    "UART reports the proximity alarm and automatic relay opening as the "
                    "target approaches, then reports the alarm clearing as it retreats."
                ),
                duration="~10 seconds",
            )

            with allure.step("Set a 30 cm proximity alarm and enable automatic relay control"):
                alarm_lines = driver.distance_alarm(30)
                assert any("[SONAR] alarm at 30 cm" in line for line in alarm_lines), (
                    f"Expected the 30 cm alarm acknowledgement, got: {alarm_lines}"
                )
                auto_lines = driver.relay_auto(True)
                assert any("[VALVE] auto on" in line for line in auto_lines), (
                    f"Expected automatic relay acknowledgement, got: {auto_lines}"
                )

            with allure.step("Stream sonar readings while the target crosses the threshold"):
                stream_may_be_active = True
                start_lines = driver.distance_log(500, timeout=1.0)
                assert any("[SONAR] continuous pinging" in line for line in start_lines), (
                    f"Expected the sonar stream to start, got: {start_lines}"
                )
                time.sleep(10.0)

            with allure.step("Stop the sonar stream before checking the captured events"):
                stop_lines = driver.distance_stop()
                stream_may_be_active = not self._stream_stopped(stop_lines)
                assert not stream_may_be_active, (
                    f"Expected a sonar stream stop acknowledgement, got: {stop_lines}"
                )

            with allure.step("Verify an above-threshold reading, alarm crossing, and relay opening"):
                captured = driver.uart_log[mark:]
                alarm_index = next(
                    (
                        index
                        for index, line in enumerate(captured)
                        if "[SONAR] PROXIMITY ALARM" in line
                    ),
                    None,
                )
                assert alarm_index is not None, (
                    f"No proximity alarm crossing was captured: {captured}"
                )
                readings: list[tuple[int, float]] = []
                for index, line in enumerate(captured[:alarm_index]):
                    match = re.search(
                        r"\[SONAR\]\s+ping:\s*echo\s*(\d+(?:\.\d+)?)\s*cm",
                        line,
                        re.IGNORECASE,
                    )
                    if match:
                        readings.append((index, float(match.group(1))))

                above_threshold = [index for index, value in readings if value > 35]
                at_or_below_threshold = [index for index, value in readings if value <= 30]
                assert above_threshold, (
                    f"Expected an initial reading above the 30 cm threshold plus 5 cm "
                    f"hysteresis, got: {readings}"
                )
                assert at_or_below_threshold, (
                    f"No at-or-below-threshold reading preceded the alarm: {readings}"
                )
                assert above_threshold[0] < at_or_below_threshold[0] < alarm_index, (
                    f"Expected target readings to cross from above 35 cm to at most 30 cm "
                    f"before the alarm event, got: {readings}"
                )
                open_index = next(
                    (
                        index
                        for index, line in enumerate(captured)
                        if "[VALVE] OPEN (distance alarm)" in line
                    ),
                    None,
                )
                assert open_index is not None and open_index > alarm_index, (
                    f"Automatic relay opening did not follow the sonar alarm: {captured}"
                )
                clear_index = next(
                    (
                        index
                        for index, line in enumerate(captured)
                        if "[SONAR] proximity alarm cleared" in line
                    ),
                    None,
                )
                assert clear_index is not None and clear_index > open_index, (
                    f"Expected the proximity alarm to clear after retreat: {captured}"
                )
                clear_match = re.search(
                    r"proximity alarm cleared\s*\((\d+(?:\.\d+)?)\s*cm\)",
                    captured[clear_index],
                    re.IGNORECASE,
                )
                assert clear_match and float(clear_match.group(1)) > 35, (
                    f"Expected the alarm to clear beyond 35 cm, got: {captured[clear_index]}"
                )

                status = self._status(driver)
                assert status["state"] == "OPEN" and status["auto"] == "on", (
                    f"Expected the relay to remain open in automatic mode after the alarm, got {status}"
                )

            with allure.step("Confirm the physical relay actuated"):
                assert manual_check(
                    "Did you hear or observe the relay open as the target crossed inside 30 cm?"
                ), "Operator did not confirm the physical relay actuation"
        finally:
            with allure.step("Stop the stream and restore relay automation and alarm state"):
                cleanup_failures: list[str] = []
                try:
                    if stream_may_be_active:
                        stop_lines = driver.distance_stop()
                        stream_may_be_active = not self._stream_stopped(stop_lines)
                        if stream_may_be_active:
                            retry_lines = driver.distance_stop()
                            stream_may_be_active = not self._stream_stopped(retry_lines)
                            if stream_may_be_active:
                                cleanup_failures.append(
                                    "Could not confirm sonar stream termination after retry: "
                                    f"{stop_lines}; retry: {retry_lines}"
                                )
                finally:
                    try:
                        auto_off_lines = driver.relay_auto(False)
                        if not any("[VALVE] auto off" in line for line in auto_off_lines):
                            cleanup_failures.append(
                                f"Could not disable automatic relay control: {auto_off_lines}"
                            )
                    finally:
                        try:
                            alarm_off_lines = driver.distance_alarm("off")
                            if not any("[SONAR] alarm off" in line for line in alarm_off_lines):
                                cleanup_failures.append(
                                    f"Could not disable the proximity alarm: {alarm_off_lines}"
                                )
                        finally:
                            try:
                                time.sleep(0.55)
                                relay_off_lines = driver.relay_off()
                                if not any(
                                    "[VALVE] CLOSED" in line or "W601" in line
                                    for line in relay_off_lines
                                ):
                                    cleanup_failures.append(
                                        f"Could not leave the relay closed: {relay_off_lines}"
                                    )
                            finally:
                                final_status = self._status(driver)
                                if (
                                    final_status["auto"] != "off"
                                    or final_status["state"] != "CLOSED"
                                ):
                                    cleanup_failures.append(
                                        "Automatic-control cleanup did not restore safe state: "
                                        f"{final_status}"
                                    )
                assert not cleanup_failures, (
                    "Relay test cleanup failed:\n- " + "\n- ".join(cleanup_failures)
                )

    @allure.story("RL-1 Relay indicator")
    @allure.title("Verify the GPIO4 indicator follows the relay state")
    @pytest.mark.interactive
    def test_relay_gpio4_indicator(
        self,
        authenticated_device: DeviceDriver,
        firmware_version: str,
        manual_prepare: Any,
        manual_check: Any,
        soft: SoftChecks,
    ) -> None:
        driver = authenticated_device
        initial = self._status(driver)
        assert initial["state"] == "CLOSED" and initial["auto"] == "off", (
            f"Indicator check requires a closed relay with auto off; got {initial}"
        )
        mark = driver.buffer_len()

        try:
            prepare_observation(
                manual_prepare,
                action=(
                    "Observe the separate GPIO4 indicator while the test opens and closes "
                    "the relay; do not press any hardware buttons."
                ),
                expected="GPIO4 indicator is lit while the relay is OPEN and off while CLOSED",
                duration="~5 seconds per relay state",
            )

            with allure.step("Open the relay and verify UART state"):
                opened = driver.relay_on()
                assert any("[VALVE] OPEN" in line for line in opened), (
                    f"Expected relay-open UART evidence, got: {opened}"
                )
                assert driver.wait_for("[VALVE] OPEN", timeout=2.0, since_index=mark), (
                    "Relay-open event was not captured in the UART transcript"
                )

            with allure.step("Record the physical GPIO4 indication while relay is open"):
                open_indicator_correct = manual_check(
                    "Was the separate GPIO4 indicator LED lit while the relay was OPEN?"
                )
                soft.check(
                    open_indicator_correct,
                    "GPIO4 relay-open indicator did not match the PRD",
                )

            time.sleep(0.55)
            with allure.step("Close the relay and verify UART state"):
                closed = driver.relay_off()
                assert any("[VALVE] CLOSED" in line for line in closed), (
                    f"Expected relay-closed UART evidence, got: {closed}"
                )

            with allure.step("Record the physical GPIO4 indication while relay is closed"):
                closed_indicator_correct = manual_check(
                    "Was the separate GPIO4 indicator LED off while the relay was CLOSED?"
                )
                soft.check(
                    closed_indicator_correct,
                    "GPIO4 relay-closed indicator did not match the PRD",
                )
            if (
                firmware_version == "2.1.0"
                and not open_indicator_correct
                and not closed_indicator_correct
            ):
                pytest.xfail(
                    "BUG-005: observed GPIO4 indicator is inverted on firmware 2.1.0; "
                    "see dz17/REPORT.md"
                )
            soft.assert_all()
        finally:
            time.sleep(0.55)
            driver.relay_off()
            final_status = self._status(driver)
            assert final_status["state"] == "CLOSED", (
                f"Indicator-test cleanup did not leave relay closed: {final_status}"
            )
