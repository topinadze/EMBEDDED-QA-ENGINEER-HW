from __future__ import annotations

import re
import time
from collections.abc import Callable, Generator
from typing import Any

import allure
import pytest

from drivers.device_driver import DeviceDriver
from manual_checks import SoftChecks, prepare_observation


def _relay_status(driver: DeviceDriver) -> dict[str, Any]:
    status = driver.relay_status()
    assert any(
        re.search(
            r"\[VALVE\]\s*(?:OPEN|closed),\s*auto\s*(?:on|off),\s*cycles\s*\d+",
            line,
            re.IGNORECASE,
        )
        for line in status["raw"]
    ), f"Expected a parsed relay status response, got: {status['raw']}"
    return status


def _respect_relay_rate_limit() -> None:
    time.sleep(0.55)


def _require_uart_event(
    expected: tuple[str, ...],
    lines: list[str],
    context: str,
) -> str:
    observed = next(
        (
            marker
            for marker in expected
            if any(marker.casefold() in line.casefold() for line in lines)
        ),
        None,
    )
    if observed is None:
        raise AssertionError(
            f"{context}: expected one of {expected}; received UART: {lines}"
        )
    return observed


def _attempt_cleanup(
    failures: list[str],
    description: str,
    operation: Callable[[], Any],
) -> Any | None:
    try:
        return operation()
    except Exception as exc:
        failures.append(f"{description}: {exc}")
        return None


@pytest.fixture(autouse=True)
def relay_safe_state(
    authenticated_device: DeviceDriver,
) -> Generator[None, None, None]:
    driver = authenticated_device
    initial = _relay_status(driver)
    assert initial["state"] == "CLOSED" and initial["auto"] == "off", (
        "Relay tests require the relay closed and automatic control disabled; "
        f"got {initial}"
    )
    yield

    with allure.step("Teardown: stop relay schedule and restore a safe relay state"):
        failures: list[str] = []

        def stop_schedule() -> None:
            lines = driver.relay_schedule_stop()
            _require_uart_event(
                ("[VALVE] schedule stopped", "W605"),
                lines,
                "Could not stop relay schedule",
            )

        _attempt_cleanup(failures, "Could not stop relay schedule", stop_schedule)
        current = _attempt_cleanup(
            failures, "Could not read relay state during cleanup", lambda: _relay_status(driver)
        )

        if current is None or current["auto"] != "off":
            def disable_auto() -> None:
                lines = driver.relay_auto(False)
                _require_uart_event(
                    ("[VALVE] auto off",),
                    lines,
                    "Could not disable automatic relay control",
                )

            _attempt_cleanup(
                failures, "Could not disable automatic relay control", disable_auto
            )

        if current is None or current["state"] != "CLOSED":
            _respect_relay_rate_limit()

            def close_relay() -> None:
                lines = driver.relay_off()
                _require_uart_event(
                    ("[VALVE] CLOSED", "W601"),
                    lines,
                    "Could not close relay",
                )

            _attempt_cleanup(failures, "Could not close relay", close_relay)

        final = _attempt_cleanup(
            failures, "Could not verify final relay state", lambda: _relay_status(driver)
        )
        if final is not None and (
            final["state"] != "CLOSED" or final["auto"] != "off"
        ):
            failures.append(f"Relay fixture did not restore safe state: {final}")

        if failures:
            raise AssertionError("Relay cleanup failed:\n- " + "\n- ".join(failures))


@pytest.fixture
def relay_sonar_alarm_state(
    relay_safe_state: None,
    authenticated_device: DeviceDriver,
) -> Generator[dict[str, Any], None, None]:
    driver = authenticated_device
    state: dict[str, Any] = {
        "initial_alarm": None,
        "alarm_modified": False,
        "auto_may_be_enabled": False,
        "stream_may_be_active": False,
    }
    yield state

    with allure.step("Teardown: stop sonar stream and disable test-owned automation"):
        failures: list[str] = []

        if state["stream_may_be_active"]:
            def stop_stream() -> None:
                lines = driver.distance_stop()
                _require_uart_event(
                    ("[SONAR] pinging stopped", "W710"),
                    lines,
                    "Could not confirm sonar stream termination",
                )

            _attempt_cleanup(
                failures, "Could not stop sonar stream", stop_stream
            )

        if state["auto_may_be_enabled"]:
            def disable_auto() -> None:
                lines = driver.relay_auto(False)
                _require_uart_event(
                    ("[VALVE] auto off",),
                    lines,
                    "Could not disable automatic relay control",
                )

            _attempt_cleanup(
                failures, "Could not disable automatic relay control", disable_auto
            )

        if state["alarm_modified"]:
            def disable_alarm() -> None:
                lines = driver.distance_alarm("off")
                _require_uart_event(
                    ("[SONAR] alarm off",),
                    lines,
                    "Could not disable the sonar proximity alarm",
                )

            _attempt_cleanup(
                failures, "Could not disable the sonar proximity alarm", disable_alarm
            )

        if failures:
            raise AssertionError("Sonar relay cleanup failed:\n- " + "\n- ".join(failures))


@allure.epic("SENTRY SWM-2")
@allure.feature("Valve Relay")
@pytest.mark.relay
@pytest.mark.persistent
class TestRelay:
    @staticmethod
    def _status(driver: DeviceDriver) -> dict[str, Any]:
        return _relay_status(driver)

    @allure.story("RL-1 / RL-2 Relay state and cycle accounting")
    @allure.title("Relay commands change state and count actual transitions")
    @pytest.mark.positive
    def test_relay_commands_and_cycle_count(
        self,
        authenticated_device: DeviceDriver,
        firmware_version: str,
    ) -> None:
        driver = authenticated_device
        initial = _relay_status(driver)
        assert initial["state"] == "CLOSED", (
            f"Start with the relay closed before testing; got {initial}"
        )
        assert initial["auto"] == "off", (
            f"Start with automatic relay control disabled; got {initial}"
        )
        initial_cycles = initial["cycles"]

        with allure.step("Open the relay and verify state and cycle count"):
            opened = driver.relay_on()
            assert any("[VALVE] OPEN" in line for line in opened), (
                f"Expected an OPEN acknowledgement, got: {opened}"
            )
            open_status = _relay_status(driver)
            assert open_status["state"] == "OPEN"
            actual_cycles = open_status["cycles"]

        with allure.step("Verify repeated OPEN is rejected without changing the count"):
            repeated_on = driver.relay_on()
            assert any("W601" in line for line in repeated_on), (
                f"Expected W601 for repeated relay on, got: {repeated_on}"
            )
            assert _relay_status(driver)["cycles"] == actual_cycles

        if firmware_version == "2.1.0" and actual_cycles == initial_cycles + 2:
            pytest.xfail(
                "BUG-004: firmware 2.1.0 increments relay cycles twice per transition; "
                "see dz17/REPORT.md"
            )
        assert actual_cycles == initial_cycles + 1, (
            f"One relay transition should add one cycle: "
            f"before={initial_cycles}, after={actual_cycles}"
        )

        _respect_relay_rate_limit()
        with allure.step("Close the relay and verify state"):
            closed = driver.relay_off()
            assert any("[VALVE] CLOSED" in line for line in closed), (
                f"Expected a CLOSED acknowledgement, got: {closed}"
            )
            closed_status = _relay_status(driver)
            assert closed_status["state"] == "CLOSED"
            assert closed_status["cycles"] == actual_cycles + 1

        with allure.step("Verify repeated CLOSE is rejected without changing the count"):
            repeated_off = driver.relay_off()
            assert any("W601" in line for line in repeated_off), (
                f"Expected W601 for repeated relay off, got: {repeated_off}"
            )
            assert _relay_status(driver)["cycles"] == closed_status["cycles"]

        _respect_relay_rate_limit()
        with allure.step("Toggle the relay open; the fixture will close it after the test"):
            toggled = driver.relay_toggle()
            assert any("[VALVE] OPEN" in line for line in toggled), (
                f"Expected toggle to open relay, got: {toggled}"
            )
            toggle_status = _relay_status(driver)
            assert toggle_status["state"] == "OPEN"
            assert toggle_status["cycles"] == closed_status["cycles"] + 1

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
        with allure.step(f"Pulse relay for the valid boundary {duration_ms} ms"):
            lines = driver.relay_pulse(duration_ms)
            assert any("[VALVE] OPEN (pulse)" in line for line in lines), (
                f"Expected pulse to open relay, got: {lines}"
            )
            assert any("[VALVE] CLOSED (pulse end)" in line for line in lines), (
                f"Expected pulse to close relay, got: {lines}"
            )
            assert self._status(driver)["state"] == "CLOSED"

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
        with allure.step(f"Reject pulse duration {duration_ms} ms with an explicit UART error"):
            lines = driver.relay_pulse(duration_ms, timeout=2.0)
            if (
                duration_ms == 99
                and firmware_version in {"2.1.0", "2.3.0"}
                and any("[VALVE] OPEN (pulse)" in line for line in lines)
            ):
                assert any("[VALVE] CLOSED (pulse end)" in line for line in lines), (
                    f"Known invalid pulse did not report its completion, got: {lines}"
                )
                pytest.xfail(
                    f"BUG-006: firmware {firmware_version} accepts and actuates a "
                    "99 ms pulse; see dz17/REPORT.md"
                )
            assert any("E603" in line for line in lines), (
                f"Expected E603 for invalid pulse duration {duration_ms} ms, got: {lines}"
            )
            assert self._status(driver)["state"] == "CLOSED"

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
        opened = driver.relay_on()
        assert any("[VALVE] OPEN" in line for line in opened), (
            f"Expected relay to open before pulse rejection, got: {opened}"
        )
        lines = driver.relay_pulse(100)
        assert any("E604" in line for line in lines), (
            f"Expected E604 when pulsing an already-open relay, got: {lines}"
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
        lines = driver.relay_schedule(on_seconds, off_seconds)
        assert any("E606" in line for line in lines), (
            f"Expected E606 for schedule {on_seconds}/{off_seconds} s, got: {lines}"
        )
        after = self._status(driver)
        assert after["state"] == initial["state"] and after["cycles"] == initial["cycles"], (
            f"Rejected schedule changed relay state or cycle count: before={initial}, after={after}"
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
        setup_lines = driver.relay_schedule_stop()
        assert any(
            "[VALVE] schedule stopped" in line or "W605" in line
            for line in setup_lines
        ), f"Could not ensure schedule is inactive before test: {setup_lines}"
        lines = driver.relay_schedule_stop()
        assert any("W605" in line for line in lines), (
            f"Expected W605 for stopping an inactive schedule, got: {lines}"
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
        with allure.step("Start a 2-second on / 2-second off relay schedule"):
            lines = driver.relay_schedule(2, 2)
            assert any("[VALVE] schedule: 2 s on / 2 s off" in line for line in lines), (
                f"Expected schedule acceptance, got: {lines}"
            )
            assert driver.wait_for(
                "[VALVE] OPEN (schedule)", timeout=8.0, since_index=mark
            ), "Schedule did not open the relay"
            assert driver.wait_for(
                "[VALVE] CLOSED (schedule)", timeout=8.0, since_index=mark
            ), "Schedule did not close the relay"

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
        enabled = driver.relay_auto(True)
        assert any("[VALVE] auto on" in line for line in enabled), (
            f"Expected auto-on acknowledgement, got: {enabled}"
        )
        assert self._status(driver)["auto"] == "on"

    @allure.story("RL-5 Automatic relay control")
    @allure.title("Crossing the sonar alarm threshold automatically opens the relay")
    @pytest.mark.interactive
    def test_relay_auto_opens_on_sonar_alarm(
        self,
        authenticated_device: DeviceDriver,
        relay_sonar_alarm_state: dict[str, Any],
        manual_prepare: Any,
        manual_check: Any,
    ) -> None:
        driver = authenticated_device
        prepare_observation(
            manual_prepare,
            action=(
                "Place a flat target about 40 cm from the sonar sensor and keep the path clear. "
                "Avoid placing it within 20 cm; a close reading can create a persistent CIC "
                "collision warning. If the initial reading is not above 35 cm, the scenario "
                "will stop before changing the alarm threshold or relay automation. "
                "This test overwrites the stored sonar alarm threshold to 30 cm, then disables "
                "the alarm; the previous threshold cannot be read or restored by the current "
                "device interface."
            ),
            expected=(
                "The initial one-shot measurement and subsequent sonar stream should "
                "report readings greater than 35 cm in UART."
            ),
            duration=(
                "Place the target before confirming; allow up to 15 seconds for valid "
                "stream readings after setup."
            ),
        )
        with allure.step("Prime sonar measurements before querying persisted alarm configuration"):
            prime_lines = driver.distance()
            initial_reading = next(
                (
                    float(match.group(1))
                    for line in prime_lines
                    if (
                        match := re.search(
                            r"(?:\[SONAR\]\s*ping:\s*echo|sonar:\s*contact at)\s*"
                            r"(\d+(?:\.\d+)?)\s*cm",
                            line,
                            re.IGNORECASE,
                        )
                    )
                ),
                None,
            )
            if initial_reading is None or initial_reading <= 35:
                alert_note = (
                    " The measurement also emitted a CIC warning; review the pending alert "
                    "before retrying."
                    if any("[CIC #" in line for line in prime_lines)
                    else ""
                )
                pytest.skip(
                    "Sonar precondition not met: the target must produce an initial "
                    f"reading above 35 cm, got {initial_reading}; move it farther away "
                    "and rerun. No alarm configuration or relay automation was changed. "
                    f"{alert_note} UART: {prime_lines}"
                )
            initial_stats = driver.distance_stats()
            relay_sonar_alarm_state["initial_alarm"] = initial_stats["alarm"]
            assert initial_stats["alarm"] in {"on", "off"}, (
                "Could not determine the existing sonar alarm state after a successful "
                f"measurement: {initial_stats['raw']}"
            )
        assert relay_sonar_alarm_state["initial_alarm"] == "off", (
            "This test requires the sonar alarm to be off before it changes the persistent "
            f"threshold; got {relay_sonar_alarm_state['initial_alarm']!r}"
        )
        initial = self._status(driver)
        assert initial["state"] == "CLOSED" and initial["auto"] == "off", (
            f"Threshold-crossing test requires a closed relay with auto off; got {initial}"
        )
        mark = driver.buffer_len()

        with allure.step("Set a 30 cm proximity alarm and enable automatic relay control"):
            relay_sonar_alarm_state["alarm_modified"] = True
            alarm_lines = driver.distance_alarm(30)
            assert any("[SONAR] alarm at 30 cm" in line for line in alarm_lines), (
                f"Expected the 30 cm alarm acknowledgement, got: {alarm_lines}"
            )
            relay_sonar_alarm_state["auto_may_be_enabled"] = True
            auto_lines = driver.relay_auto(True)
            assert any("[VALVE] auto on" in line for line in auto_lines), (
                f"Expected automatic relay acknowledgement, got: {auto_lines}"
            )

        with allure.step("Start sonar streaming and wait for an above-threshold UART reading"):
            relay_sonar_alarm_state["stream_may_be_active"] = True
            start_lines = driver.distance_log(500)
            assert any("[SONAR] continuous pinging" in line for line in start_lines), (
                f"Expected the sonar stream to start, got: {start_lines}"
            )
            assert driver.wait_for(
                "[SONAR] ping: echo", timeout=15.0, since_index=mark
            ), "No sonar reading arrived from the active stream"
            captured = driver.uart_log[mark:]
            first_reading = next(
                (
                    float(match.group(1))
                    for line in captured
                    if (
                        match := re.search(
                            r"\[SONAR\]\s+ping:\s*echo\s*(\d+(?:\.\d+)?)\s*cm",
                            line,
                            re.IGNORECASE,
                        )
                    )
                ),
                None,
            )
            assert first_reading is not None and first_reading > 35, (
                f"Expected the initial target position to read above 35 cm, got {first_reading}; "
                f"UART: {captured}"
            )

        prepare_observation(
            manual_prepare,
            action=(
                "Move the target from about 40 cm to about 25 cm from the sonar sensor. "
                "Keep the measured gap above 20 cm; closer readings can create a persistent "
                "CIC collision warning."
            ),
            expected=(
                "UART reports a reading greater than 20 cm and at or below 30 cm, then "
                "the proximity alarm and relay-open event."
            ),
            duration="Allow up to 45 seconds for the threshold crossing.",
        )
        with allure.step("Wait for UART evidence of alarm crossing and automatic relay opening"):
            alarm_mark = driver.buffer_len()
            assert driver.wait_for(
                "[SONAR] PROXIMITY ALARM", timeout=45.0, since_index=alarm_mark
            ), "No UART proximity-alarm event followed the target movement"
            assert driver.wait_for(
                "[VALVE] OPEN (distance alarm)", timeout=5.0, since_index=alarm_mark
            ), "No UART relay-open event followed the proximity alarm"

        prepare_observation(
            manual_prepare,
            action="Move the target back beyond 35 cm from the sonar sensor.",
            expected="UART reports the proximity alarm clearing above 35 cm.",
            duration="Allow up to 45 seconds for the alarm-clear event.",
        )
        with allure.step("Wait for the UART proximity-alarm clear event"):
            clear_mark = driver.buffer_len()
            assert driver.wait_for(
                "[SONAR] proximity alarm cleared",
                timeout=45.0,
                since_index=clear_mark,
            ), "No UART proximity-alarm clear event followed the target retreat"

        with allure.step(
            "Stop the sonar stream before checking relay status or operator observation"
        ):
            stop_lines = driver.distance_stop()
            _require_uart_event(
                ("[SONAR] pinging stopped", "W710"),
                stop_lines,
                "UART did not confirm that the sonar stream stopped",
            )
            relay_sonar_alarm_state["stream_may_be_active"] = False

        with allure.step("Verify threshold crossing and relay/alarm event order in UART"):
            captured = driver.uart_log[mark:]
            alarm_index = next(
                (
                    index
                    for index, line in enumerate(captured)
                    if "[SONAR] PROXIMITY ALARM" in line
                ),
                None,
            )
            readings: list[tuple[int, float]] = []
            for index, line in enumerate(captured):
                match = re.search(
                    r"\[SONAR\]\s+ping:\s*echo\s*(\d+(?:\.\d+)?)\s*cm",
                    line,
                    re.IGNORECASE,
                )
                if match:
                    readings.append((index, float(match.group(1))))
            above_threshold = [index for index, value in readings if value > 35]
            near_threshold = [
                index for index, value in readings if 20 < value <= 30
            ]
            too_close = [
                (index, value) for index, value in readings if value <= 20
            ]
            assert alarm_index is not None, f"No proximity alarm event in UART: {captured}"
            assert not too_close, (
                "Sonar readings at or below 20 cm can create a persistent CIC collision "
                f"warning; keep the target farther away: {too_close}; UART: {captured}"
            )
            assert above_threshold and near_threshold, (
                f"Expected UART readings above 35 cm and between 20 and 30 cm: {readings}"
            )
            assert above_threshold[0] < near_threshold[0] < alarm_index, (
                f"Expected far-to-near readings before the alarm event: {readings}"
            )
            open_index = next(
                (
                    index
                    for index, line in enumerate(captured)
                    if "[VALVE] OPEN (distance alarm)" in line
                ),
                None,
            )
            clear_index = next(
                (
                    index
                    for index, line in enumerate(captured)
                    if "[SONAR] proximity alarm cleared" in line
                ),
                None,
            )
            assert open_index is not None and open_index > alarm_index, (
                f"Automatic relay opening did not follow the alarm: {captured}"
            )
            assert clear_index is not None and clear_index > open_index, (
                f"Expected alarm clear after relay opening: {captured}"
            )
            clear_match = re.search(
                r"proximity alarm cleared\s*\((\d+(?:\.\d+)?)\s*cm\)",
                captured[clear_index],
                re.IGNORECASE,
            )
            assert clear_match and float(clear_match.group(1)) > 35, (
                f"Expected alarm to clear above 35 cm: {captured[clear_index]}"
            )
            status = self._status(driver)
            assert status["state"] == "OPEN" and status["auto"] == "on", (
                f"Expected relay to remain open in automatic mode: {status}"
            )

        with allure.step("Confirm the physical relay actuated"):
            assert manual_check(
                "Did you hear or observe the relay open as the target crossed inside 30 cm?"
            ), "Operator did not confirm the physical relay actuation"

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
        prepare_observation(
            manual_prepare,
            action="Observe the separate GPIO4 indicator; the test will open the relay.",
            expected="The GPIO4 indicator is lit while UART reports the relay OPEN.",
            duration="Observe for about 5 seconds.",
        )
        with allure.step("Open the relay and verify the UART acknowledgement"):
            opened = driver.relay_on()
            assert any("[VALVE] OPEN" in line for line in opened), (
                f"Expected relay-open UART evidence, got: {opened}"
            )
        with allure.step("Record the physical GPIO4 indication while relay is open"):
            open_indicator_correct = manual_check(
                "Was the separate GPIO4 indicator LED lit while UART reported relay OPEN?"
            )
            soft.check(
                open_indicator_correct,
                "GPIO4 relay-open indicator did not match the PRD",
            )

        _respect_relay_rate_limit()
        prepare_observation(
            manual_prepare,
            action="The test will close the relay; continue observing the separate GPIO4 indicator.",
            expected="The GPIO4 indicator turns off while UART reports the relay CLOSED.",
            duration="Observe for about 5 seconds.",
        )
        with allure.step("Close the relay and verify the UART acknowledgement"):
            closed = driver.relay_off()
            assert any("[VALVE] CLOSED" in line for line in closed), (
                f"Expected relay-closed UART evidence, got: {closed}"
            )
        with allure.step("Record the physical GPIO4 indication while relay is closed"):
            closed_indicator_correct = manual_check(
                "Was the separate GPIO4 indicator LED off while UART reported relay CLOSED?"
            )
            soft.check(
                closed_indicator_correct,
                "GPIO4 relay-closed indicator did not match the PRD",
            )
        if firmware_version in {"2.1.0", "2.3.0"} and (
            not open_indicator_correct or not closed_indicator_correct
        ):
            pytest.xfail(
                "BUG-005: GPIO4 relay indicator did not match the expected relay "
                f"state on firmware {firmware_version}; see dz17/REPORT.md"
            )
        soft.assert_all()
