from __future__ import annotations

import logging
import re
import sys
import time
from dataclasses import dataclass
from typing import Any, Callable, Generator
from unittest.mock import Mock

import allure
import pytest
from drivers.device_driver import DeviceDriver
from manual_checks import SoftChecks, prepare_observation

REFERENCE_PLACEMENT_TOLERANCE_CM = 0.5
MINIMUM_STABLE_READINGS = 3
LOGGER = logging.getLogger(__name__)
DISTANCE_AVERAGE_PATTERN = re.compile(
    r"\[SONAR\]\s+avg\s+(\d+(?:\.\d+)?)\s+cm\s+\((\d+)/(\d+)\s+ok\)"
)
DISTANCE_READING_PATTERN = re.compile(
    r"\[SONAR\]\s+ping:\s+echo\s+(\d+(?:\.\d+)?)\s+cm"
)
COLLISION_PATTERN = re.compile(
    r"\[COLLISION\]\s*contact too close:\s*(\d+(?:\.\d+)?)\s*cm",
    re.IGNORECASE,
)
DISTANCE_ALERT_PATTERN = re.compile(
    r"\[CIC\s+#(\d+)\s+(?:INFO|WARNING|CRITICAL)\]\s+sonar:",
    re.IGNORECASE,
)

pytestmark = [
    allure.parent_suite("DZ17"),
    allure.suite("Active Sonar"),
    allure.epic("SENTRY SWM-2"),
    allure.feature("Active Sonar HC-SR04"),
]


@dataclass
class SonarTestResources:
    stream_active: bool = False
    relay_may_be_open: bool = False


@pytest.fixture
def sonar_test_resources(
    authenticated_device: DeviceDriver,
    request: pytest.FixtureRequest,
) -> Generator[SonarTestResources, None, None]:
    state = SonarTestResources()
    yield state

    failures: list[str] = []
    if state.stream_active:
        with allure.step("Teardown: stop the active sonar stream"):
            try:
                lines = authenticated_device.distance_stop()
                if not any(
                    "[SONAR] pinging stopped" in line or "W710" in line
                    for line in lines
                ):
                    failures.append(f"Could not confirm sonar stream stop: {lines}")
            except Exception as exc:
                failures.append(f"Could not stop sonar stream: {exc}")

    if state.relay_may_be_open:
        with allure.step("Teardown: close the relay and verify automation is off"):
            try:
                lines = authenticated_device.relay_off()
                status = authenticated_device.relay_status()
                if not any(
                    "[VALVE] CLOSED" in line or "W601" in line for line in lines
                ):
                    failures.append(f"Relay close was not confirmed: {lines}")
                if status["state"] != "CLOSED" or status["auto"] != "off":
                    failures.append(f"Unsafe relay state after cleanup: {status}")
            except Exception as exc:
                failures.append(f"Could not close relay: {exc}")

    if not failures:
        return

    summary = "\n".join(failures)
    allure.attach(
        summary,
        name="Sonar test cleanup failures",
        attachment_type=allure.attachment_type.TEXT,
    )
    if getattr(getattr(request.node, "rep_call", None), "failed", False):
        LOGGER.error("Sonar cleanup also failed after the test failure:\n%s", summary)
    else:
        pytest.fail("Sonar cleanup failed:\n" + summary, pytrace=False)


@pytest.fixture
def original_sonar_filter(
    authenticated_device: DeviceDriver,
    request: pytest.FixtureRequest,
) -> Generator[bool, None, None]:
    driver = authenticated_device
    stats = driver.distance_stats()
    if stats["filter"] is None or stats["alarm"] is None:
        relay_status = driver.relay_status()
        if relay_status["auto"] != "off":
            pytest.skip(
                "Cannot safely prime sonar filter configuration while relay "
                "automation is enabled; current relay status: "
                f"{relay_status['raw']}"
            )
        stats = _distance_stats_with_config(
            driver,
            expected_relay_state=relay_status["state"],
        )

    assert stats["filter"] in {0, 1, 5}, (
        "Cannot verify or restore the sonar filter because its initial state "
        f"was not reported: {stats['raw']}"
    )
    original_enabled = stats["filter"] != 0
    yield original_enabled

    try:
        with allure.step("Teardown: restore and verify the original sonar filter state"):
            driver.distance_filter(original_enabled)
            restored_stats = driver.distance_stats()
            assert restored_stats["filter"] is not None and (
                restored_stats["filter"] != 0
            ) == original_enabled, (
                f"Sonar filter restoration failed; expected enabled="
                f"{original_enabled}, got {restored_stats['raw']}"
            )
    except Exception as exc:
        message = f"Could not restore the original sonar filter state: {exc}"
        allure.attach(
            message,
            name="Sonar filter cleanup failure",
            attachment_type=allure.attachment_type.TEXT,
        )
        if getattr(getattr(request.node, "rep_call", None), "failed", False):
            LOGGER.error("%s", message)
        else:
            pytest.fail(message, pytrace=False)


def _start_sonar_stream(
    driver: DeviceDriver, resource_state: SonarTestResources, interval_ms: int
) -> None:
    resource_state.stream_active = True
    lines = driver.distance_log(interval_ms)
    assert any("[SONAR] continuous pinging" in line for line in lines), (
        f"Could not start the sonar stream: {lines}"
    )


def _stop_sonar_stream(
    driver: DeviceDriver, resource_state: SonarTestResources
) -> None:
    lines = driver.distance_stop()
    assert any("[SONAR] pinging stopped" in line for line in lines), (
        f"Could not confirm sonar stream termination: {lines}"
    )
    resource_state.stream_active = False


def _observe_sonar_stream_phase(
    driver: DeviceDriver,
    *,
    duration_s: float,
    scenario: str,
) -> list[str]:
    uart_mark = driver.buffer_len()
    _observe_sonar_stream(driver, duration_s=duration_s, scenario=scenario)
    return driver.uart_log[uart_mark:]


def _capture_sonar_stream_phase(
    driver: DeviceDriver,
    resource_state: SonarTestResources,
    *,
    duration_s: float,
    scenario: str,
) -> list[str]:
    _start_sonar_stream(driver, resource_state, 500)
    captured = _observe_sonar_stream_phase(
        driver,
        duration_s=duration_s,
        scenario=scenario,
    )
    _stop_sonar_stream(driver, resource_state)
    return captured


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


def _assert_guard_disarmed_when_available(
    driver: DeviceDriver, firmware_version: str
) -> None:
    if firmware_version == "2.1.0":
        return

    lines = driver.guard_status()
    assert any(
        re.search(r"\[WATCH\]\s*disarmed\b", line, re.IGNORECASE) for line in lines
    ), f"Sonar target movement requires Guard disarmed, got: {lines}"


def _observe_sonar_stream(
    driver: DeviceDriver, duration_s: float, scenario: str
) -> None:
    deadline = time.monotonic() + duration_s
    print(
        f"\n{scenario}: sonar stream is active for about {duration_s:.0f} seconds. "
        "Move the target now; live sonar readings follow.",
        flush=True,
    )
    while (remaining := deadline - time.monotonic()) > 0:
        lines = driver.read_for(min(0.5, remaining))
        for line in lines:
            if "[SONAR]" in line or "[COLLISION]" in line or "E70" in line:
                print(f"UART: {line}", flush=True)


def _sonar_stream_readings(lines: list[str]) -> list[tuple[int, float]]:
    readings: list[tuple[int, float]] = []
    for index, line in enumerate(lines):
        match = DISTANCE_READING_PATTERN.search(line)
        if match:
            readings.append((index, float(match.group(1))))
    return readings


def _assert_collision_phase(
    lines: list[str], *, expected_events: int, phase: str
) -> None:
    events = [
        float(match.group(1))
        for line in lines
        if (match := COLLISION_PATTERN.search(line))
    ]
    assert len(events) == expected_events, (
        f"Expected {expected_events} collision event(s) during {phase}, "
        f"got {events}: {lines}"
    )
    assert all(distance < 20 for distance in events), (
        f"Collision events during {phase} must report distances below 20 cm: "
        f"{events}"
    )


def _assert_collision_approach(lines: list[str], phase: str) -> None:
    _assert_collision_phase(lines, expected_events=1, phase=phase)
    events = [
        index
        for index, line in enumerate(lines)
        if COLLISION_PATTERN.search(line)
    ]
    readings = _sonar_stream_readings(lines)
    _assert_minimum_readings(
        [distance for index, distance in readings if index < events[0]],
        lambda distance: distance > 25,
        f">25 cm before the collision event during {phase}",
    )
    _assert_minimum_readings(
        [distance for _, distance in readings],
        lambda distance: distance < 20,
        f"<20 cm during {phase}",
    )


def _assert_minimum_readings(
    readings: list[float],
    predicate: Callable[[float], bool],
    condition: str,
) -> None:
    matches = [distance for distance in readings if predicate(distance)]
    assert len(matches) >= MINIMUM_STABLE_READINGS, (
        f"Expected at least {MINIMUM_STABLE_READINGS} readings {condition}, "
        f"got {len(matches)} matching readings from {readings}"
    )


def _assert_proximity_reading_progression(lines: list[str]) -> None:
    readings = [distance for _, distance in _sonar_stream_readings(lines)]
    far_indices = [
        index for index, distance in enumerate(readings) if distance > 25
    ]
    _assert_minimum_readings(
        readings,
        lambda distance: distance > 25,
        "above 25 cm at the start",
    )

    third_far_index = far_indices[MINIMUM_STABLE_READINGS - 1]
    approach_indices = [
        index
        for index, distance in enumerate(readings)
        if index > third_far_index and 10 <= distance < 20
    ]
    _assert_minimum_readings(
        readings[third_far_index + 1 :],
        lambda distance: 10 <= distance < 20,
        "between 10 and 20 cm after the initial >25 cm reading",
    )

    third_approach_index = approach_indices[MINIMUM_STABLE_READINGS - 1]
    _assert_minimum_readings(
        readings[third_approach_index + 1 :],
        lambda distance: distance < 10,
        "below 10 cm after the 10–20 cm approach reading",
    )


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
    ids=["all-samples-valid", "incomplete-sample-set", "out-of-range"],
)
@allure.sub_suite("Offline helper checks")
@allure.story("Sonar response parsing")
@allure.title("Accept an averaged reading only when all samples are valid")
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
    ids=["single-echo-reading", "out-of-range", "average-is-not-single-echo"],
)
@allure.sub_suite("Offline helper checks")
@allure.story("Sonar response parsing")
@allure.title("Parse a single sonar echo: {param_id}")
def test_distance_reading_cm_requires_single_echo(
    lines: list[str], expected: float | None
) -> None:
    assert _distance_reading_cm(lines) == expected


@pytest.mark.parametrize(
    ("lines", "expected_events", "valid"),
    [
        (["[COLLISION] contact too close: 19.5 cm"], 1, True),
        (["[COLLISION] contact too close: 18.0 cm"] * 2, 1, False),
        (["[SONAR] ping: echo 30.0 cm"], 0, True),
    ],
    ids=["one-expected-event", "duplicate-event-rejected", "no-event-expected"],
)
@allure.sub_suite("Offline helper checks")
@allure.story("Collision event validation")
@allure.title("Validate collision event count: {param_id}")
def test_collision_phase_checks_exact_event_count(
    lines: list[str], expected_events: int, valid: bool
) -> None:
    if valid:
        _assert_collision_phase(
            lines,
            expected_events=expected_events,
            phase="test phase",
        )
    else:
        with pytest.raises(AssertionError, match="Expected"):
            _assert_collision_phase(
                lines,
                expected_events=expected_events,
                phase="test phase",
            )


@pytest.mark.parametrize(
    ("lines", "valid"),
    [
        (
            [
                "[SONAR] ping: echo 30.0 cm",
                "[SONAR] ping: echo 29.8 cm",
                "[SONAR] ping: echo 30.2 cm",
                "[SONAR] ping: echo 15.0 cm",
                "[SONAR] ping: echo 15.2 cm",
                "[SONAR] ping: echo 14.8 cm",
                "[SONAR] ping: echo 9.0 cm",
                "[SONAR] ping: echo 9.2 cm",
                "[SONAR] ping: echo 8.8 cm",
            ],
            True,
        ),
        (
            [
                "[SONAR] ping: echo 15.0 cm",
                "[SONAR] ping: echo 15.0 cm",
                "[SONAR] ping: echo 9.0 cm",
                "[SONAR] ping: echo 9.0 cm",
                "[SONAR] ping: echo 9.0 cm",
                "[SONAR] ping: echo 30.0 cm",
                "[SONAR] ping: echo 30.0 cm",
                "[SONAR] ping: echo 30.0 cm",
                "[SONAR] ping: echo 9.0 cm",
                "[SONAR] ping: echo 8.8 cm",
            ],
            False,
        ),
        (
            [
                "[SONAR] ping: echo 30.0 cm",
                "[SONAR] ping: echo 15.0 cm",
                "[SONAR] ping: echo 9.0 cm",
                "[SONAR] ping: echo 9.0 cm",
                "[SONAR] ping: echo 9.0 cm",
                "[SONAR] ping: echo 11.0 cm",
            ],
            False,
        ),
        (
            [
                "[SONAR] ping: echo 30.0 cm",
                "[SONAR] ping: echo 30.0 cm",
                "[SONAR] ping: echo 30.0 cm",
                "[SONAR] ping: echo 15.0 cm",
                "[SONAR] ping: echo 15.0 cm",
                "[SONAR] ping: echo 15.0 cm",
                "[SONAR] ping: echo 9.0 cm",
                "[SONAR] ping: echo 9.0 cm",
                "[SONAR] ping: echo 9.0 cm",
                "[SONAR] ping: echo 14.3 cm",
                "[SONAR] ping: echo 14.3 cm",
                "[SONAR] ping: echo 14.3 cm",
            ],
            True,
        ),
    ],
    ids=[
        "ordered-zones-and-stable-near-readings",
        "zone-order-reset-rejected",
        "insufficient-near-readings",
        "farther-target-resets-near-reading-count",
    ],
)
@allure.sub_suite("Offline helper checks")
@allure.story("Proximity reading validation")
@allure.title("Validate proximity-zone progression: {param_id}")
def test_proximity_readings_require_ordered_zones_and_three_near_readings(
    lines: list[str], valid: bool
) -> None:
    if valid:
        _assert_proximity_reading_progression(lines)
    else:
        with pytest.raises(AssertionError):
            _assert_proximity_reading_progression(lines)


@pytest.mark.parametrize(
    ("lines", "valid"),
    [
        (
            [
                "[SONAR] ping: echo 30.0 cm",
                "[SONAR] ping: echo 30.0 cm",
                "[SONAR] ping: echo 30.0 cm",
                "[SONAR] ping: echo 30.0 cm",
                "[SONAR] ping: echo 30.0 cm",
                "[SONAR] ping: echo 30.0 cm",
                "[SONAR] ping: echo 30.0 cm",
                "[SONAR] ping: echo 30.0 cm",
                "[SONAR] ping: echo 30.0 cm",
                "[SONAR] ping: echo 19.0 cm",
                "[SONAR] ping: echo 19.0 cm",
                "[SONAR] ping: echo 19.0 cm",
                "[SONAR] ping: echo 18.0 cm",
                "[SONAR] ping: echo 17.0 cm",
                "[SONAR] ping: echo 16.0 cm",
                "[COLLISION] contact too close: 19.5 cm",
            ],
            True,
        ),
        (
            [
                "[SONAR] ping: echo 30.0 cm",
                "[SONAR] ping: echo 30.0 cm",
                "[COLLISION] contact too close: 19.5 cm",
                "[SONAR] ping: echo 19.0 cm",
                "[SONAR] ping: echo 18.0 cm",
                "[SONAR] ping: echo 17.0 cm",
            ],
            False,
        ),
        (
            ["[COLLISION] contact too close: 19.5 cm"],
            False,
        ),
    ],
    ids=[
        "clear-readings-before-collision",
        "collision-before-approach-rejected",
        "missing-clear-readings-rejected",
    ],
)
@allure.sub_suite("Offline helper checks")
@allure.story("Collision approach validation")
@allure.title("Validate collision approach sequence: {param_id}")
def test_collision_approach_requires_clear_reading_before_event(
    lines: list[str], valid: bool
) -> None:
    if valid:
        _assert_collision_approach(lines, "test approach")
    else:
        with pytest.raises(AssertionError, match="at least 3 readings"):
            _assert_collision_approach(lines, "test approach")


@allure.sub_suite("Offline helper checks")
@allure.story("Sonar alert verification")
@allure.title("Match only sonar-generated alert IDs present in alert history")
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


@allure.sub_suite("Offline helper checks")
@allure.story("Sonar alert verification")
@allure.title("Ignore unrelated alert history when verifying sonar-generated alerts")
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


@allure.sub_suite("Offline helper checks")
@allure.story("Sonar alert verification")
@allure.title("Fail verification when a generated sonar alert is missing")
def test_generated_alert_verification_fails_when_own_id_is_missing() -> None:
    driver = Mock()
    driver.alert_list.return_value = [
        "I (120) sentry: [CIC] 2 alerts, 2 unacknowledged:",
        "I (130) sentry: #4 12:00:00 WARNING * unrelated alert",
    ]

    with pytest.raises(AssertionError, match="Sonar-generated alert IDs"):
        _assert_generated_alerts_listed(driver, {"5"})

    driver.alert_ack.assert_not_called()


@allure.sub_suite("Offline helper checks")
@allure.story("Sonar configuration safety")
@allure.title("Prime missing sonar settings only with automation disabled and relay closed")
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


@allure.sub_suite("Offline helper checks")
@allure.story("Sonar configuration safety")
@allure.title("Do not prime sonar settings while relay automation is enabled")
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


@allure.sub_suite("Device sonar scenarios")
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

    @allure.story("DS-6 Collision detection and re-arm")
    @allure.title("Emit one collision event per approach, re-arming only beyond 25 cm")
    @pytest.mark.interactive
    def test_distance_collision_rearms_after_target_retreats(
        self,
        authenticated_device: DeviceDriver,
        sonar_test_resources: SonarTestResources,
        firmware_version: str,
        manual_prepare: Any,
    ) -> None:
        driver = authenticated_device
        _assert_guard_disarmed_when_available(driver, firmware_version)
        initial_relay = driver.relay_status()
        assert initial_relay["state"] == "CLOSED" and initial_relay["auto"] == "off", (
            "Collision re-arm test requires a closed relay and relay automation off: "
            f"{initial_relay}"
        )

        phases = (
            (
                "first approach",
                "Keep the target farther than 25 cm until a >25 cm reading appears "
                "three times in the live console. Then move it smoothly (not in a "
                "quick flick) from beyond 25 cm to below 20 cm over about 2-3 seconds. "
                "Hold it below 20 cm for at least 2 seconds and until three readings "
                "below 20 cm appear.",
                1,
                8.0,
            ),
            (
                "re-arm retreat",
                "Move the target smoothly away from the sensor to beyond 25 cm over "
                "about 2-3 seconds; do not pull it away in one quick motion. Hold it "
                "there for at least 2 seconds and until three readings above 25 cm "
                "appear.",
                0,
                8.0,
            ),
            (
                "second approach",
                "Wait for three >25 cm readings in the live console, then move the "
                "target smoothly below 20 cm over about 2-3 seconds. Hold it there "
                "for at least 2 seconds and until three readings below 20 cm appear.",
                1,
                8.0,
            ),
        )
        first_phase, first_action, first_expected_events, first_duration = phases[0]
        prepare_observation(
            manual_prepare,
            action=(
                "Do not move the target until you press Enter and the test prints "
                "the phase-capture start message; UART readings are not displayed "
                "while this readiness prompt is open. " + first_action
            ),
            expected=(
                f"After capture starts, during the {first_phase}, the UART should "
                f"show exactly "
                f"{first_expected_events} collision event reporting below "
                "20 cm, after a >25 cm reading."
            ),
            duration=f"~{first_duration:.0f} seconds after readiness confirmation",
        )
        with allure.step("Start one continuous sonar stream for all collision phases"):
            _start_sonar_stream(driver, sonar_test_resources, 500)

        for phase_index, (phase, action, expected_events, duration_s) in enumerate(
            phases
        ):
            if phase_index > 0:
                prepare_observation(
                    manual_prepare,
                    action=(
                        "Do not move the target until you press Enter and the test "
                        "resumes live UART capture; readings are not displayed "
                        "while this readiness prompt is open. " + action
                    ),
                    expected=(
                        f"After capture resumes, during the {phase}, the UART "
                        f"should show exactly "
                        f"{expected_events} collision event(s), each below 20 cm."
                        if expected_events
                        else "After capture resumes, the UART should show a "
                        "distance above 25 cm and no collision event while the "
                        "target remains there."
                    ),
                    duration=(
                        f"~{duration_s:.0f} seconds after readiness confirmation"
                    ),
                )
            with allure.step(f"Capture the DS-6 {phase} phase"):
                captured = _observe_sonar_stream_phase(
                    driver,
                    duration_s=duration_s,
                    scenario=f"DS-6 {phase}",
                )
                allure.attach(
                    "\n".join(captured),
                    name=f"DS-6 {phase} UART evidence",
                    attachment_type=allure.attachment_type.TEXT,
                )
                if expected_events:
                    _assert_collision_approach(captured, phase)
                else:
                    _assert_collision_phase(
                        captured,
                        expected_events=expected_events,
                        phase=phase,
                    )
                    readings = [
                        distance
                        for _, distance in _sonar_stream_readings(captured)
                    ]
                    _assert_minimum_readings(
                        readings,
                        lambda distance: distance > 25,
                        "above 25 cm during the re-arm retreat",
                    )

        with allure.step("Stop the continuous stream after all collision phases"):
            _stop_sonar_stream(driver, sonar_test_resources)

        final_relay = driver.relay_status()
        assert final_relay["state"] == "CLOSED" and final_relay["auto"] == "off", (
            "Collision test unexpectedly changed relay state or automation: "
            f"{final_relay}"
        )

    @allure.story("DS-6 Out-of-range indication")
    @allure.title("Out-of-range sonar response E702 displays the red LED for two seconds")
    @pytest.mark.interactive
    @pytest.mark.long_range
    def test_distance_out_of_range_shows_red_led(
        self,
        authenticated_device: DeviceDriver,
        manual_prepare: Any,
        manual_check: Any,
    ) -> None:
        driver = authenticated_device
        prepare_observation(
            manual_prepare,
            action=(
                "This test needs a clear path with at least 4.1 m between the "
                "HC-SR04 sensor face and a flat target. If that space is unavailable "
                "on this bench, do not run this test; use the regular distance suite "
                "without the optional long-range case. If available, place the target "
                "at least 4.1 m away and look directly at the device LED."
            ),
            expected=(
                "The next one-shot measurement returns E702 specifically because "
                "the target exceeds the approximately 4 m sonar range, and the "
                "device LED lights RED for about two seconds. This does not test "
                "the separate E701 no-echo condition."
            ),
            duration=(
                "Allow ~2 seconds immediately after the one-shot measurement; "
                "the physical setup needs at least 4.1 m of clear space"
            ),
        )

        with allure.step("Issue one sonar measurement with the target out of range"):
            print(
                "\nReadiness confirmed; issuing one sonar measurement now.",
                flush=True,
            )
            uart_mark = driver.buffer_len()
            driver.send_command_nowait("distance")
            got_out_of_range = driver.wait_for(
                "E702",
                timeout=1.2,
                since_index=uart_mark,
            )
            captured = driver.uart_log[uart_mark:]
            output = "\n".join(captured)
            print(output or "UART: no response received.", flush=True)
            assert got_out_of_range, (
                f"Expected E702 for a target beyond the sensor range, got: {captured}"
            )
            allure.attach(
                output,
                name="DS-6 out-of-range UART response",
                attachment_type=allure.attachment_type.TEXT,
            )

        with allure.step("Confirm the physical out-of-range LED indication"):
            assert manual_check(
                "Did the device LED light RED for about two seconds immediately after "
                "the E702 response?"
            ), "Operator did not observe the required two-second red LED indication"

    @allure.story("DS-7 Distance proximity indicator")
    @allure.title("Proximity indicator blinks faster near the target and stays lit below 10 cm")
    @pytest.mark.interactive
    @pytest.mark.persistent
    def test_distance_proximity_indicator_tracks_target(
        self,
        authenticated_device: DeviceDriver,
        sonar_test_resources: SonarTestResources,
        firmware_version: str,
        manual_prepare: Any,
        manual_check: Any,
        soft: SoftChecks,
    ) -> None:
        driver = authenticated_device
        _assert_guard_disarmed_when_available(driver, firmware_version)
        initial_relay = driver.relay_status()
        assert initial_relay["state"] == "CLOSED" and initial_relay["auto"] == "off", (
            "DS-7 requires a closed relay and relay automation off before setup: "
            f"{initial_relay}"
        )

        prepare_observation(
            manual_prepare,
            action=(
                "Place a flat target about 30 cm from the front face of the HC-SR04 "
                "sensor and hold it still. The test will then open the relay and run "
                "a separate sonar stream for each distance zone. Opening the relay "
                "increments its persistent cycle counter; this test is marked "
                "persistent and requires explicit opt-in."
            ),
            expected=(
                "First observe the proximity indicator with the target held around "
                "30 cm. Later prompts will ask you to move to ~15 cm and then ~8 cm. "
                "At each phase, watch both the live readings and the diode while the "
                "relay is OPEN and the stream is running. The diode should blink "
                "faster near the target and stay lit below 10 cm."
            ),
            duration=(
                "~4 seconds for the initial ~30 cm phase; each later phase has its "
                "own prompt and 7-second stream window"
            ),
        )

        with allure.step("Open the relay for the DS-7 indicator condition"):
            sonar_test_resources.relay_may_be_open = True
            open_lines = driver.relay_on()
            assert any("[VALVE] OPEN" in line for line in open_lines), (
                f"Could not open the relay for DS-7: {open_lines}"
            )
            relay_status = driver.relay_status()
            assert relay_status["state"] == "OPEN" and relay_status["auto"] == "off", (
                f"DS-7 requires relay OPEN with automation off: {relay_status}"
            )
            assert manual_check(
                "Did you hear the relay click OPEN before sonar streaming started?"
            ), "Operator did not confirm the physical relay opening"

        captured_phases: list[str] = []

        with allure.step("Observe and capture the target in the far zone (~30 cm)"):
            far_lines = _capture_sonar_stream_phase(
                driver,
                sonar_test_resources,
                duration_s=4.0,
                scenario="DS-7 far zone (~30 cm)",
            )
            captured_phases.extend(far_lines)
            allure.attach(
                "\n".join(far_lines),
                name="DS-7 far-zone UART evidence",
                attachment_type=allure.attachment_type.TEXT,
            )
            far_readings = [
                distance for _, distance in _sonar_stream_readings(far_lines)
            ]
            _assert_minimum_readings(
                far_readings,
                lambda distance: distance > 25,
                "above 25 cm in the far zone",
            )
        with allure.step("Confirm the physical far-zone indicator behavior"):
            soft.check(
                manual_check(
                    "While the target was held around 30 cm and the stream was "
                    "active, did the proximity diode show its slower/far-distance "
                    "blink?"
                ),
                "Operator did not confirm the far-zone indicator behavior",
            )

        prepare_observation(
            manual_prepare,
            action=(
                "Move the target smoothly from ~30 cm to ~15 cm over about 3 seconds "
                "(not a quick flick), then hold it still at 15 cm for at least "
                "2 seconds. Keep it at 10–20 cm for the full 7-second stream."
            ),
            expected=(
                "The live sonar console should show at least three readings between "
                "10 cm and 20 cm. Watch whether the proximity diode blinks faster "
                "than it did in the ~30 cm phase."
            ),
            duration="~7 seconds of streaming, including the 3-second move and hold",
        )
        with allure.step("Observe and capture the middle zone (~15 cm)"):
            middle_lines = _capture_sonar_stream_phase(
                driver,
                sonar_test_resources,
                duration_s=7.0,
                scenario="DS-7 middle zone (~15 cm)",
            )
            captured_phases.extend(middle_lines)
            allure.attach(
                "\n".join(middle_lines),
                name="DS-7 middle-zone UART evidence",
                attachment_type=allure.attachment_type.TEXT,
            )
            middle_readings = [
                distance for _, distance in _sonar_stream_readings(middle_lines)
            ]
            _assert_minimum_readings(
                middle_readings,
                lambda distance: 10 <= distance < 20,
                "between 10 and 20 cm in the middle zone",
            )
        with allure.step("Confirm the physical middle-zone indicator behavior"):
            soft.check(
                manual_check(
                    "While the target was held around 15 cm and the stream was "
                    "active, did the proximity diode blink faster than in the "
                    "~30 cm phase?"
                ),
                "Operator did not observe a faster blink in the middle zone",
            )

        prepare_observation(
            manual_prepare,
            action=(
                "Move the target smoothly from ~15 cm to about 8 cm over 1-2 seconds "
                "(do not jerk or sweep it quickly). Hold it still at ~8 cm for at "
                "least 3 seconds and until three sonar readings below 10 cm appear."
            ),
            expected=(
                "The live sonar console should show at least three readings below "
                "10 cm during this phase. While those readings arrive, observe "
                "whether the proximity diode remains continuously lit."
            ),
            duration="~7 seconds of streaming, including the move and at least 3-second hold",
        )
        with allure.step("Observe and capture the near zone (~8 cm)"):
            near_lines = _capture_sonar_stream_phase(
                driver,
                sonar_test_resources,
                duration_s=7.0,
                scenario="DS-7 near zone (~8 cm)",
            )
            captured_phases.extend(near_lines)
            allure.attach(
                "\n".join(near_lines),
                name="DS-7 near-zone UART evidence",
                attachment_type=allure.attachment_type.TEXT,
            )
            near_readings = [
                distance for _, distance in _sonar_stream_readings(near_lines)
            ]
            _assert_minimum_readings(
                near_readings,
                lambda distance: distance < 10,
                "below 10 cm in the near zone",
            )
        near_indicator_failure = (
            "Operator did not observe a continuously lit diode below 10 cm"
        )
        with allure.step("Confirm the physical near-zone indicator behavior"):
            near_indicator_ok = soft.check(
                manual_check(
                    "While the target was held around 8 cm (<10 cm) and the stream "
                    "was active, did the proximity diode stay continuously lit?"
                ),
                near_indicator_failure,
            )

        allure.attach(
            "\n".join(captured_phases),
            name="DS-7 ordered target-zone UART evidence",
            attachment_type=allure.attachment_type.TEXT,
        )
        _assert_proximity_reading_progression(captured_phases)
        final_relay = driver.relay_status()
        assert final_relay["state"] == "OPEN" and final_relay["auto"] == "off", (
            "Relay must remain OPEN with automation off throughout DS-7: "
            f"{final_relay}"
        )

        if near_indicator_ok is False:
            soft.failures.remove(near_indicator_failure)
            if not soft.failures:
                pytest.xfail(
                    "BUG-007: DS-7 proximity indicator did not stay continuously "
                    "lit below 10 cm; reproduced on firmware 2.1.0 and 2.3.0. "
                    "See dz17/REPORT.md, BUG-007."
                )

        soft.assert_all()

    @allure.story("DS-5 Sonar statistics and median filter")
    @allure.title("Query sonar statistics and toggle median filter")
    @pytest.mark.positive
    def test_distance_stats_and_filter(
        self,
        authenticated_device: DeviceDriver,
        original_sonar_filter: bool,
    ) -> None:
        driver = authenticated_device
        with allure.step("Verify reported sonar statistics and filter state"):
            stats = driver.distance_stats()
            assert stats["filter"] in {0, 1, 5}, (
                f"Unexpected sonar filter setting: {stats['raw']}"
            )
            assert stats["alarm"] in {"on", "off"}, (
                f"Unexpected sonar alarm setting: {stats['raw']}"
            )

        with allure.step("Toggle median filter OFF and verify the reported state"):
            driver.distance_filter(False)
            off_stats = driver.distance_stats()
            assert off_stats["filter"] == 0, (
                f"Expected filter off in distance stats: {off_stats['raw']}"
            )

        with allure.step("Toggle median filter ON and verify the reported state"):
            driver.distance_filter(True)
            on_stats = driver.distance_stats()
            assert on_stats["filter"] in {1, 5}, (
                f"Expected filter on in distance stats: {on_stats['raw']}"
            )

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

    @allure.story("DS-1 Interactive distance measurement characterization")
    @allure.title("Record sonar readings with target-placement tolerance")
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
            if measurements and not manual_continue():
                break

            reference_distance_cm = manual_distance(
                "Measure the gap from the sensor face to the target with a ruler "
                "and enter that distance in centimeters"
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
                    "target still until the command completes. The entered ruler "
                    "distance allows ±"
                    f"{REFERENCE_PLACEMENT_TOLERANCE_CM:.2f} cm for target placement "
                    "uncertainty; this is not a PRD-defined sensor accuracy claim. "
                    "Sonar alerts may be added to persistent history; this test will "
                    "not acknowledge or delete alert records."
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
                    signed_delta_cm = reading_cm - reference_distance_cm
                    within_placement_tolerance = (
                        abs(signed_delta_cm) <= REFERENCE_PLACEMENT_TOLERANCE_CM
                    )
                    comparison = (
                        f"Reference: {reference_distance_cm:.2f} cm\n"
                        f"Sonar reading: {reading_cm:.2f} cm\n"
                        f"Signed difference (reading - reference): "
                        f"{signed_delta_cm:+.2f} cm\n"
                        "Target placement uncertainty allowance: "
                        f"±{REFERENCE_PLACEMENT_TOLERANCE_CM:.2f} cm\n"
                        "Within placement allowance: "
                        f"{'YES' if within_placement_tolerance else 'NO'}\n"
                        "This allowance is not a PRD-defined sensor accuracy spec."
                    )
                    allure.attach(
                        comparison,
                        name=f"Distance comparison at {reference_distance_cm:.2f} cm",
                        attachment_type=allure.attachment_type.TEXT,
                    )
                    soft.check(
                        within_placement_tolerance,
                        (
                            f"At ruler reference {reference_distance_cm:.2f} cm, "
                            f"reading was {reading_cm:.2f} cm (difference "
                            f"{signed_delta_cm:+.2f} cm); target placement allowance "
                            f"is ±{REFERENCE_PLACEMENT_TOLERANCE_CM:.2f} cm"
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
                "Index | Reference (cm) | Reading (cm) | Signed difference (cm) | Placement allowance",
                "--- | ---: | ---: | ---: | ---",
            ]
            for index, (reference_cm, reading_cm) in enumerate(measurements, start=1):
                if reading_cm is None:
                    summary_lines.append(
                        f"{index} | {reference_cm:.2f} | no valid echo | n/a | NO VALID ECHO"
                    )
                    continue
                signed_delta_cm = reading_cm - reference_cm
                result = (
                    "WITHIN"
                    if abs(signed_delta_cm) <= REFERENCE_PLACEMENT_TOLERANCE_CM
                    else "OUTSIDE"
                )
                summary_lines.append(
                    f"{index} | {reference_cm:.2f} | {reading_cm:.2f} | "
                    f"{signed_delta_cm:+.2f} | {result} ±"
                    f"{REFERENCE_PLACEMENT_TOLERANCE_CM:.2f} cm"
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
