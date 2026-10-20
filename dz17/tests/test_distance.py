from __future__ import annotations

import logging
import re
import sys
import time
from typing import Any, Callable
from unittest.mock import Mock

import allure
import pytest
from drivers.device_driver import DeviceDriver
from manual_checks import SoftChecks, prepare_observation

DISTANCE_MEASUREMENT_TOLERANCE_CM = 0.5
LOGGER = logging.getLogger(__name__)
DISTANCE_AVERAGE_PATTERN = re.compile(
    r"\[SONAR\]\s+avg\s+(\d+(?:\.\d+)?)\s+cm\s+\((\d+)/(\d+)\s+ok\)"
)
DISTANCE_READING_PATTERN = re.compile(
    r"\[SONAR\]\s+ping:\s+echo\s+(\d+(?:\.\d+)?)\s+cm"
)
DISTANCE_ALERT_PATTERN = re.compile(
    r"\[CIC\s+#(\d+)\s+(?:INFO|WARNING|CRITICAL)\]\s+sonar:",
    re.IGNORECASE,
)


def _distance_stats_with_config(
    driver: DeviceDriver,
    expected_relay_state: str,
) -> dict[str, Any]:
    stats = driver.distance_stats()
    if stats["filter"] is None or stats["alarm"] is None:
        relay_before = driver.relay_status()
        assert (
            relay_before["auto"] == "off"
            and relay_before["state"] == expected_relay_state
        ), (
            "Cannot safely prime sonar stats unless relay automation is off and "
            f"the relay state is unchanged: {relay_before}"
        )
        lines = driver.distance()
        output = "\n".join(lines)
        assert "[SONAR] ping: echo" in output, (
            "Could not prime sonar statistics to read back alarm/filter settings: "
            f"{lines}"
        )
        _assert_generated_alerts_listed(driver, _alert_ids(lines))
        relay_after = driver.relay_status()
        assert (
            relay_after["auto"] == "off"
            and relay_after["state"] == expected_relay_state
        ), (
            "Sonar setup measurement changed or unexpectedly enabled relay automation: "
            f"{relay_after}"
        )
        stats = driver.distance_stats()

    assert stats["filter"] is not None and stats["alarm"] is not None, (
        "Sonar alarm/filter settings were not present in the distance stats response: "
        f"{stats['raw']}"
    )
    assert stats["filter"] in {0, 1, 5}, (
        f"Unexpected sonar filter setting in distance stats: {stats['raw']}"
    )
    assert stats["alarm"] in {"on", "off"}, (
        f"Unexpected sonar alarm setting in distance stats: {stats['raw']}"
    )
    return stats


def _valid_average_cm(lines: list[str], sample_count: int) -> float | None:
    for line in lines:
        match = DISTANCE_AVERAGE_PATTERN.search(line)
        if (
            match
            and int(match.group(2)) == sample_count
            and int(match.group(3)) == sample_count
        ):
            return float(match.group(1))
    return None


def _distance_reading_cm(lines: list[str]) -> float | None:
    for line in lines:
        match = DISTANCE_READING_PATTERN.search(line)
        if match:
            return float(match.group(1))
    return None


def _alert_ids(lines: list[str]) -> set[str]:
    return {
        match.group(1)
        for line in lines
        if (match := DISTANCE_ALERT_PATTERN.search(line))
    }


def _listed_alert_ids(lines: list[str]) -> set[str]:
    ids: set[str] = set()
    for line in lines:
        payload = line.rsplit("sentry:", maxsplit=1)[-1].strip()
        fields = payload.split()
        if fields and (match := re.fullmatch(r"#(\d+)", fields[0])):
            ids.add(match.group(1))
    return ids


def _assert_generated_alerts_listed(
    driver: DeviceDriver, generated_alert_ids: set[str]
) -> None:
    if not generated_alert_ids:
        return
    listed = driver.alert_list()
    listed_ids = _listed_alert_ids(listed)
    missing_ids = generated_alert_ids - listed_ids
    assert not missing_ids, (
        f"Sonar-generated alert IDs {sorted(missing_ids)} were absent from "
        f"the alert list: {listed}"
    )


@pytest.mark.parametrize(
    ("lines", "expected"),
    [
        (["[SONAR] avg 19.0 cm (5/5 ok)"], 19.0),
        (["[SONAR] avg 19.0 cm (4/5 ok)"], None),
        (["E (123) sentry: E702 out of range"], None),
    ],
)
def test_valid_average_cm_requires_all_samples(
    lines: list[str], expected: float | None
) -> None:
    assert _valid_average_cm(lines, sample_count=5) == expected


@pytest.mark.parametrize(
    ("lines", "expected"),
    [
        (["[SONAR] ping: echo 19.5 cm"], 19.5),
        (["E (123) sentry: E702 sonar: out of range"], None),
        (["[SONAR] avg 19.5 cm (5/5 ok)"], None),
    ],
)
def test_distance_reading_cm_requires_single_echo(
    lines: list[str], expected: float | None
) -> None:
    assert _distance_reading_cm(lines) == expected


def test_alert_id_parsers_scope_to_sonar_source_and_listed_ids() -> None:
    generated = [
        "I (100) sentry: [CIC #5 WARNING] sonar: collision risk",
        "I (110) sentry: [CIC #6 INFO] guard: state changed",
    ]
    listed = [
        "I (120) sentry: [CIC] 2 alerts, 1 unacknowledged:",
        "I (130) sentry: #4 12:00:00 WARNING * prior alert",
        "I (140) sentry: #5 12:00:01 WARNING * sonar collision",
        "I (150) sentry: #6 12:00:02 INFO guard: state changed",
    ]

    assert _alert_ids(generated) == {"5"}
    assert _listed_alert_ids(listed) == {"4", "5", "6"}


def test_generated_alert_verification_ignores_unrelated_history() -> None:
    driver = Mock()
    driver.alert_list.return_value = [
        "I (120) sentry: [CIC] 2 alerts, 2 unacknowledged:",
        "I (130) sentry: #4 12:00:00 WARNING * unrelated alert",
        "I (140) sentry: #5 12:00:01 WARNING * sonar collision",
    ]

    _assert_generated_alerts_listed(driver, {"5"})

    driver.alert_list.assert_called_once_with()
    driver.alert_ack.assert_not_called()


def test_generated_alert_verification_fails_when_own_id_is_missing() -> None:
    driver = Mock()
    driver.alert_list.return_value = [
        "I (120) sentry: [CIC] 2 alerts, 2 unacknowledged:",
        "I (130) sentry: #4 12:00:00 WARNING * unrelated alert",
    ]

    with pytest.raises(AssertionError, match="Sonar-generated alert IDs"):
        _assert_generated_alerts_listed(driver, {"5"})

    driver.alert_ack.assert_not_called()


def test_distance_stats_primes_missing_config_only_with_safe_relay_state() -> None:
    driver = Mock()
    driver.distance_stats.side_effect = [
        {"filter": None, "alarm": None, "raw": ["no measurements yet"]},
        {"filter": 5, "alarm": "on", "raw": ["filter median 5, alarm on"]},
    ]
    driver.distance.return_value = ["[SONAR] ping: echo 20.0 cm"]
    driver.relay_status.side_effect = [
        {"auto": "off", "state": "CLOSED"},
        {"auto": "off", "state": "CLOSED"},
    ]

    stats = _distance_stats_with_config(driver, expected_relay_state="CLOSED")

    assert stats["filter"] == 5
    assert stats["alarm"] == "on"
    driver.distance.assert_called_once_with()
    assert driver.relay_status.call_count == 2


def test_distance_stats_does_not_prime_when_relay_automation_is_on() -> None:
    driver = Mock()
    driver.distance_stats.return_value = {
        "filter": None,
        "alarm": None,
        "raw": ["no measurements yet"],
    }
    driver.relay_status.return_value = {"auto": "on", "state": "CLOSED"}

    with pytest.raises(AssertionError, match="Cannot safely prime sonar stats"):
        _distance_stats_with_config(driver, expected_relay_state="CLOSED")

    driver.distance.assert_not_called()


@allure.epic("SENTRY SWM-2")
@allure.feature("Active Sonar HC-SR04")
@pytest.mark.distance
class TestDistance:

    @allure.story("DS-1 Single distance measurement")
    @allure.title("Single distance ping returns echo reading in cm")
    @pytest.mark.positive
    @pytest.mark.smoke
    def test_distance_single(self, authenticated_device: DeviceDriver) -> None:
        driver = authenticated_device
        with allure.step("Issue 'distance' command"):
            lines = driver.distance()
            output = "\n".join(lines)
            assert "[SONAR] ping: echo" in output or "sonar: contact at" in output, (
                f"Unexpected single distance response: {lines}"
            )

    @allure.story("DS-1 Averaged distance measurements")
    @allure.title("Distance averaging with sample count N={count}")
    @pytest.mark.positive
    @pytest.mark.parametrize("count", [1, 5, 10, 19])
    def test_distance_averaging_valid(
        self,
        authenticated_device: DeviceDriver,
        count: int,
    ) -> None:
        driver = authenticated_device
        with allure.step(f"Issue 'distance {count}'"):
            lines = driver.distance(count=count)
            output = "\n".join(lines)
            assert f"[SONAR] avg" in output and f"({count}/{count} ok)" in output, (
                f"Expected average summary for {count} samples, got: {lines}"
            )

    @allure.story("DS-1 Upper boundary sample count (N=20)")
    @allure.title("Distance averaging with maximum valid sample count N=20")
    @pytest.mark.positive
    def test_distance_averaging_max_boundary_20(
        self,
        authenticated_device: DeviceDriver,
    ) -> None:
        driver = authenticated_device
        with allure.step("Issue 'distance 20'"):
            lines = driver.distance(count=20)
            output = "\n".join(lines)
            if "E704" in output:
                pytest.xfail(
                    "BUG-008: 'distance 20' rejects the maximum valid DS-1 sample count "
                    "on firmware 2.1.0 and 2.3.0; see dz17/REPORT.md"
                )
            assert "[SONAR] avg" in output and "(20/20 ok)" in output

    @allure.story("DS-1 Negative sample count bounds")
    @allure.title("Reject invalid sample counts N={count} with error E704")
    @pytest.mark.negative
    @pytest.mark.parametrize("count", [0, 21, 100])
    def test_distance_invalid_sample_counts(
        self,
        authenticated_device: DeviceDriver,
        count: int,
    ) -> None:
        driver = authenticated_device
        with allure.step(f"Issue 'distance {count}'"):
            lines = driver.distance(count=count)
            output = "\n".join(lines)
            assert "E704" in output, f"Expected E704 for count={count}, got: {lines}"

    @allure.story("DS-2 Continuous distance stream and stop")
    @allure.title("Continuous distance stream 100 ms, E711 busy check, and distance stop")
    @pytest.mark.positive
    def test_distance_stream_and_stop(
        self,
        authenticated_device: DeviceDriver,
    ) -> None:
        driver = authenticated_device
        stream_may_be_active = False
        try:
            with allure.step("Start continuous stream: 'distance log 100'"):
                stream_may_be_active = True
                start_lines = driver.distance_log(100)
                started = any("[SONAR] continuous pinging" in line for line in start_lines)
                assert started, f"Failed to start distance stream: {start_lines}"

            time.sleep(0.5)

            with allure.step("Verify new measurement is rejected with E711 while stream is active"):
                busy_lines = driver.distance()
                assert any("E711" in line for line in busy_lines), (
                    f"Expected E711 while distance stream running, got: {busy_lines}"
                )

            with allure.step("Stop distance stream"):
                stop_lines = driver.distance_stop()
                assert any("[SONAR] pinging stopped" in line for line in stop_lines)
                stream_may_be_active = False
                has_w710 = any("W710" in line for line in stop_lines)
                if not has_w710:
                    pytest.xfail(
                        "BUG-009: 'distance stop' omits the documented W710 response "
                        "on firmware 2.1.0 and 2.3.0; see dz17/REPORT.md"
                    )
                assert has_w710
        finally:
            if stream_may_be_active:
                with allure.step("Teardown: stop active distance stream"):
                    driver.distance_stop()

    @allure.story("DS-2 Stream interval bounds validation")
    @allure.title("Reject out-of-range stream intervals with error E705")
    @pytest.mark.negative
    @pytest.mark.parametrize("interval", [50, 99, 5001, 10000])
    def test_distance_stream_invalid_interval(
        self,
        authenticated_device: DeviceDriver,
        interval: int,
    ) -> None:
        driver = authenticated_device
        lines = driver.distance_log(interval)
        assert any("E705" in line for line in lines), (
            f"Expected E705 for invalid interval {interval}, got: {lines}"
        )

    @allure.story("DS-5 Sonar statistics and median filter")
    @allure.title("Query sonar statistics and toggle median filter")
    @pytest.mark.positive
    def test_distance_stats_and_filter(
        self,
        authenticated_device: DeviceDriver,
    ) -> None:
        driver = authenticated_device
        with allure.step("Query 'distance stats'"):
            stats = driver.distance_stats()
            assert stats["filter"] in {0, 1, 5}
            assert stats["alarm"] in {"on", "off"}

        original_filter = stats["filter"]
        try:
            with allure.step("Toggle median filter OFF"):
                off_lines = driver.distance_filter(False)
                assert any("filter: off" in line.casefold() or "filter off" in line.casefold() for line in off_lines)

            with allure.step("Toggle median filter ON"):
                on_lines = driver.distance_filter(True)
                assert any("filter: on" in line.casefold() or "filter on" in line.casefold() or "median" in line.casefold() for line in on_lines)
        finally:
            with allure.step("Restore the original median filter state"):
                driver.distance_filter(original_filter != 0)

    @allure.story("DS-3 Calibration bounds validation")
    @allure.title("Reject out-of-bounds calibration distances with error E706")
    @pytest.mark.negative
    @pytest.mark.parametrize("ref_dist", [4, 301])
    def test_distance_calibration_out_of_bounds(
        self,
        authenticated_device: DeviceDriver,
        ref_dist: int,
    ) -> None:
        driver = authenticated_device
        lines = driver.distance_calibrate(ref_dist)
        assert any("E706" in line for line in lines), (
            f"Expected E706 for reference distance {ref_dist}, got: {lines}"
        )

    @allure.story("DS-1 Access control - login required")
    @allure.title("Distance command without login returns error E003")
    @pytest.mark.negative
    def test_distance_logged_out_blocked(
        self,
        device_driver: DeviceDriver,
        ensure_wifi_connected: Callable[[DeviceDriver], None],
        ensure_authenticated_device: Callable[[DeviceDriver], None],
    ) -> None:
        driver = device_driver
        try:
            ensure_wifi_connected(driver)

            with allure.step("Ensure Wi-Fi is up and the test session is logged out"):
                identity_mark = len(driver.uart_log)
                driver.send_command_nowait("whoami")
                identity = driver.wait_for_any(
                    ("not logged in", ", access:"),
                    timeout=2.0,
                    since_index=identity_mark,
                )
                assert identity is not None, "Timed out waiting for UART identity response"
                if identity != "not logged in":
                    driver.logout()
                    logged_out_mark = len(driver.uart_log)
                    driver.send_command_nowait("whoami")
                    assert driver.wait_for(
                        "not logged in",
                        timeout=2.0,
                        since_index=logged_out_mark,
                    ), "Could not confirm logout before testing the login requirement"

            with allure.step("Attempt distance command while logged out"):
                lines = driver.distance()
                assert any("E003" in line for line in lines), (
                    f"Expected E003 for distance command while logged out, got: {lines}"
                )
        finally:
            primary_error = sys.exc_info()[1]
            try:
                with allure.step("Restore the configured Wi-Fi and account session"):
                    ensure_authenticated_device(driver)
            except Exception as cleanup_error:
                if primary_error is None:
                    raise
                allure.attach(
                    f"Session restoration failed after the primary test failure: "
                    f"{cleanup_error}",
                    name="Authentication cleanup failure",
                    attachment_type=allure.attachment_type.TEXT,
                )

    @allure.story("DS-5 Settings persistence across reboot")
    @allure.title("Median filter and alarm-enabled state retained across reboot")
    @pytest.mark.persistent
    def test_distance_persistence_after_reboot(
        self,
        authenticated_device: DeviceDriver,
        ensure_authenticated_device: Callable[[DeviceDriver], None],
    ) -> None:
        driver = authenticated_device
        initial_relay = driver.relay_status()
        if initial_relay["auto"] != "off":
            pytest.skip(
                "Sonar persistence readback requires relay automation to be off; "
                f"current relay status: {initial_relay['raw']}"
            )

        initial_stats = _distance_stats_with_config(
            driver, expected_relay_state=initial_relay["state"]
        )
        initial_filter_enabled = initial_stats["filter"] != 0
        initial_alarm = initial_stats["alarm"]
        if initial_alarm != "on":
            pytest.skip(
                "The sonar alarm must already be enabled to verify its reboot "
                "persistence safely. The test does not change an unknown saved "
                "threshold; enable it manually at a known safe threshold first."
            )
        authenticated_after_reboot = True
        try:
            with allure.step("Configure median filter on"):
                driver.distance_filter(True)

            with allure.step("Reboot device"):
                authenticated_after_reboot = False
                assert driver.reboot(timeout=30.0), "Device failed to reboot"

            with allure.step("Restore Wi-Fi and configured account session"):
                ensure_authenticated_device(driver)
                authenticated_after_reboot = True

            with allure.step("Verify median filter and alarm-enabled state persisted"):
                stats = _distance_stats_with_config(
                    driver, expected_relay_state=initial_relay["state"]
                )
                assert stats["alarm"] == "on"
                assert stats["filter"] == 5, (
                    f"Expected median filter to persist after reboot, got: {stats.get('filter')}"
                )
        finally:
            primary_error = sys.exc_info()[1]
            if authenticated_after_reboot:
                try:
                    with allure.step("Restore the filter and verify the alarm state"):
                        driver.distance_filter(initial_filter_enabled)
                        restored_stats = driver.distance_stats()
                        assert restored_stats["alarm"] == initial_alarm, (
                            "Expected the test to restore the initial alarm state "
                            f"{initial_alarm!r}, got: {restored_stats}"
                        )
                        assert restored_stats["filter"] is not None and (
                            restored_stats["filter"] != 0
                        ) == initial_filter_enabled, (
                            "Expected filter enabled="
                            f"{initial_filter_enabled}, got: {restored_stats}"
                        )
                        restored_relay = driver.relay_status()
                        assert (
                            restored_relay["auto"] == "off"
                            and restored_relay["state"] == initial_relay["state"]
                        ), (
                            "Sonar persistence test changed relay state: "
                            f"{restored_relay}"
                        )
                except Exception as cleanup_error:
                    if primary_error is None:
                        raise
                    allure.attach(
                        f"Cleanup failed after the primary test failure: {cleanup_error}",
                        name="Post-reboot cleanup failure",
                        attachment_type=allure.attachment_type.TEXT,
                    )
            else:
                allure.attach(
                    "Post-reboot authentication was not confirmed, so authenticated "
                    "cleanup commands were skipped. The test did not modify the "
                    f"initially-on alarm or its threshold. After restoring login "
                    f"manually, restore the median filter to "
                    f"{'on' if initial_filter_enabled else 'off'}. "
                    "Verify relay auto remains off and its state remains "
                    f"{initial_relay['state']}.",
                    name="Post-reboot cleanup not run",
                    attachment_type=allure.attachment_type.TEXT,
                )

    @allure.story("DS-1 Interactive distance measurement accuracy")
    @allure.title("Collect sonar readings at operator-selected measured distances")
    @pytest.mark.interactive
    def test_distance_interactive_measurement(
        self,
        authenticated_device: DeviceDriver,
        manual_prepare: Any,
        manual_continue: Callable[[], bool],
        manual_distance: Callable[[str], float],
        soft: SoftChecks,
    ) -> None:
        driver = authenticated_device
        with allure.step("Confirm valve automation is disabled before sonar measurements"):
            initial_relay_status = driver.relay_status()
            if initial_relay_status["auto"] != "off":
                pytest.skip(
                    "Sonar accuracy measurements may trigger the configured proximity "
                    "alarm. Relay automation must be off to avoid an unintended valve "
                    f"state change; current relay status: {initial_relay_status['raw']}"
                )
            initial_relay_state = initial_relay_status["state"]

        stats = driver.distance_stats()
        allure.attach(
            "Initial calibration offset: "
            f"{stats['calibration'] if stats['calibration'] is not None else 'not reported'} cm\n"
            f"Median filter setting: {stats['filter']}",
            name="Sonar measurement configuration before accuracy sweep",
            attachment_type=allure.attachment_type.TEXT,
        )

        measurements: list[tuple[float, float | None]] = []
        while True:
            if not manual_continue():
                break

            reference_distance_cm = manual_distance(
                "Enter the ruler-measured gap from the sensor face to the target"
            )
            prepare_observation(
                manual_prepare,
                action=(
                    f"Place a flat target exactly {reference_distance_cm:.2f} cm from "
                    "the front face of the HC-SR04 sensor, based on the distance you "
                    "just measured with a ruler."
                ),
                expected=(
                    "The console reports one sonar echo in centimeters. Keep the "
                    "target still until the command completes. Sonar alerts may be "
                    "added to persistent history; this test will not acknowledge or "
                    "delete alert records."
                ),
                duration="~1 second for the one-shot measurement",
            )

            with allure.step(
                f"Measure one sonar echo at reference distance {reference_distance_cm:.2f} cm"
            ):
                lines = driver.distance()
                output = "\n".join(lines)
                reading_cm = _distance_reading_cm(lines)
                measurements.append((reference_distance_cm, reading_cm))
                allure.attach(
                    output or "No UART response captured for the one-shot measurement.",
                    name=f"Sonar readings at {reference_distance_cm:.2f} cm",
                    attachment_type=allure.attachment_type.TEXT,
                )

                relay_after_measurement = driver.relay_status()
                if (
                    relay_after_measurement["auto"] != "off"
                    or relay_after_measurement["state"] != initial_relay_state
                ):
                    pytest.fail(
                        "Valve relay state changed during the sonar accuracy measurement "
                        "despite relay automation being disabled. Check the valve "
                        f"immediately; before={initial_relay_status['raw']}, "
                        f"after={relay_after_measurement['raw']}"
                    )

                has_valid_reading = reading_cm is not None
                soft.check(
                    has_valid_reading,
                    (
                        f"Expected one valid sonar echo at reference "
                        f"{reference_distance_cm:.2f} cm; UART response: {output}"
                    ),
                )
                if reading_cm is not None:
                    error_cm = abs(reading_cm - reference_distance_cm)
                    within_tolerance = error_cm <= DISTANCE_MEASUREMENT_TOLERANCE_CM
                    comparison = (
                        f"Reference: {reference_distance_cm:.2f} cm\n"
                        f"Sonar reading: {reading_cm:.2f} cm\n"
                        f"Absolute error: {error_cm:.2f} cm\n"
                        f"Acceptance tolerance: ±{DISTANCE_MEASUREMENT_TOLERANCE_CM:.2f} cm\n"
                        f"Result: {'PASS' if within_tolerance else 'FAIL'}"
                    )
                    allure.attach(
                        comparison,
                        name=f"Distance comparison at {reference_distance_cm:.2f} cm",
                        attachment_type=allure.attachment_type.TEXT,
                    )
                    soft.check(
                        within_tolerance,
                        (
                            f"At reference {reference_distance_cm:.2f} cm, sonar reading "
                            f"was {reading_cm:.2f} cm (absolute error {error_cm:.2f} cm; "
                            f"allowed ±{DISTANCE_MEASUREMENT_TOLERANCE_CM:.2f} cm)"
                        ),
                    )

                generated_alert_ids = _alert_ids(lines)
                if generated_alert_ids:
                    with allure.step(
                        "Verify only sonar alert IDs emitted by this measurement are listed"
                    ):
                        try:
                            _assert_generated_alerts_listed(driver, generated_alert_ids)
                        except AssertionError as exc:
                            soft.check(False, str(exc))

        with allure.step("Summarize all measurements and evaluate the completed series"):
            summary_lines = [
                "Index | Reference (cm) | Reading (cm) | Error (cm) | Result",
                "--- | ---: | ---: | ---: | ---",
            ]
            for index, (reference_cm, reading_cm) in enumerate(measurements, start=1):
                if reading_cm is None:
                    summary_lines.append(
                        f"{index} | {reference_cm:.2f} | no valid echo | n/a | FAIL"
                    )
                    continue
                error_cm = reading_cm - reference_cm
                result = (
                    "PASS"
                    if abs(error_cm) <= DISTANCE_MEASUREMENT_TOLERANCE_CM
                    else "FAIL"
                )
                summary_lines.append(
                    f"{index} | {reference_cm:.2f} | {reading_cm:.2f} | "
                    f"{error_cm:+.2f} | {result}"
                )

            summary = "\n".join(summary_lines)
            allure.attach(
                summary,
                name="Completed sonar measurement series",
                attachment_type=allure.attachment_type.TEXT,
            )
            soft.check(
                bool(measurements),
                "At least one reference-distance measurement must be collected "
                "before finishing the series.",
            )
            LOGGER.info("DISTANCE SERIES SUMMARY\n%s", summary)
        soft.assert_all()
