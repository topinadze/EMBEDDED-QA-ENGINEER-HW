from __future__ import annotations

import re
import time
from typing import Any
from unittest.mock import Mock

import allure
import pytest

from drivers.device_driver import DeviceDriver
from manual_checks import SoftChecks, prepare_observation


ALERT_PATTERN = re.compile(
    r"\[CIC\s+#(\d+)\s+(INFO|WARNING|CRITICAL)\]",
    re.IGNORECASE,
)
ACKNOWLEDGEMENT_PATTERN = re.compile(
    r"\[CIC\]\s+#?(\d+)\s+acknowledged\b",
    re.IGNORECASE,
)
ALREADY_ACKNOWLEDGED_PATTERN = re.compile(r"\bW852\b", re.IGNORECASE)
ALERT_LIST_ID_PATTERN = re.compile(r"#(\d+)")
ALERT_LIST_SUMMARY_PATTERN = re.compile(
    r"\[CIC\]\s+(\d+)\s+alerts?,\s+(\d+)\s+unacknowledged\b",
    re.IGNORECASE,
)


def test_alert_list_parser_matches_complete_id() -> None:
    lines = [
        "[CIC] 10 alerts, 1 unacknowledged:",
        "#10 20:24:45 INFO test alert",
    ]

    assert TestAlertCenter._listed_alert(lines, "1") is None
    assert TestAlertCenter._listed_alert(lines, "10") == (
        False,
        "#10 20:24:45 INFO test alert",
    )


def test_alert_list_parser_reads_pending_marker_column() -> None:
    pending = "I (6935570) sentry:   #13 20:25:00 INFO * test test alert"
    acknowledged = "I (6935580) sentry:   #12 20:24:56 INFO test test alert"

    assert TestAlertCenter._listed_alert([pending], "13") == (True, pending)
    assert TestAlertCenter._listed_alert([acknowledged], "12") == (
        False,
        acknowledged,
    )


def test_alert_list_parser_extracts_summary_and_pending_ids_from_uart_lines() -> None:
    lines = [
        "I (6935520) sentry: [CIC] 20 alerts, 2 unacknowledged:",
        "I (6935530) sentry:   #19 20:56:15 INFO     * test    test alert",
        "I (6935540) sentry:   #20 20:56:16 WARNING  * test    test alert",
    ]

    assert TestAlertCenter._alert_list_summary(lines) == (20, 2)
    assert TestAlertCenter._pending_alert_ids(lines) == ["19", "20"]


def test_alert_list_parser_snapshots_acknowledgement_state() -> None:
    lines = [
        "I (6935520) sentry: [CIC] 2 alerts, 1 unacknowledged:",
        "I (6935530) sentry:   #19 20:56:15 INFO     * test    test alert",
        "I (6935540) sentry:   #20 20:56:16 WARNING    test    test alert",
    ]

    assert TestAlertCenter._alert_list_entries(lines) == {
        "19": (True, lines[1]),
        "20": (False, lines[2]),
    }


@pytest.mark.parametrize(
    "after",
    [
        {"19": (True, "pending #19")},
        {
            "19": (False, "acknowledged #19"),
            "20": (False, "acknowledged #20"),
        },
    ],
    ids=["removed-entry", "changed-pending-state"],
)
def test_alert_clear_guard_rejects_changed_history_entries(
    after: dict[str, tuple[bool, str]],
) -> None:
    before = {
        "19": (True, "pending #19"),
        "20": (False, "acknowledged #20"),
    }

    with pytest.raises(AssertionError, match="changed or removed"):
        TestAlertCenter._assert_alert_entries_preserved(before, after)


def test_full_history_clear_prompt_shows_list_before_operator_approval() -> None:
    initial_list = [
        "I (6935520) sentry: [CIC] 2 alerts, 1 unacknowledged:",
        "I (6935530) sentry: #19 20:56:15 INFO * test test alert",
        "I (6935540) sentry: #20 20:56:16 WARNING test test alert",
    ]
    acknowledged_list = [
        "I (6935550) sentry: [CIC] 2 alerts, 0 unacknowledged:",
        "I (6935560) sentry: #19 20:56:15 INFO test test alert",
        "I (6935570) sentry: #20 20:56:16 WARNING test test alert",
    ]
    empty_list = ["I (6935580) sentry: [CIC] 0 alerts, 0 unacknowledged:"]
    driver = Mock()
    driver.alert_list.side_effect = [initial_list, acknowledged_list, empty_list]
    driver.alert_ack.return_value = ["[CIC] all alerts acknowledged"]
    driver.alert_clear.return_value = ["[CIC] history cleared"]
    events: list[tuple[str, str]] = []

    def prepare(message: str) -> None:
        events.append(("prepare", message))

    def confirm(message: str) -> bool:
        events.append(("confirm", message))
        return True

    TestAlertCenter().test_alert_clear_all_history_on_explicit_operator_approval(
        driver,
        "2.3.0",
        prepare,
        confirm,
    )

    assert [event[0] for event in events] == ["prepare", "confirm"]
    assert all(line in events[0][1] for line in initial_list)
    assert "explicitly approve ACK ALL" in events[1][1]
    driver.alert_ack.assert_called_once_with("all")
    driver.alert_clear.assert_called_once_with()


@allure.epic("SENTRY SWM-2")
@allure.feature("CIC Alert Center")
@pytest.mark.alert
class TestAlertCenter:
    @staticmethod
    def _require_23(firmware_version: str) -> None:
        if firmware_version != "2.3.0":
            pytest.skip("CIC Alert Center functional behavior is available starting in firmware 2.3.0.")

    @staticmethod
    def _alert_id(lines: list[str], level: str) -> str:
        for line in lines:
            match = ALERT_PATTERN.search(line)
            if match and match.group(2).casefold() == level.casefold():
                return match.group(1)
        raise AssertionError(f"Could not find a {level.upper()} CIC alert in UART output: {lines!r}")

    @staticmethod
    def _listed_alert(
        lines: list[str], alert_id: str
    ) -> tuple[bool, str] | None:
        return TestAlertCenter._alert_list_entries(lines).get(alert_id)

    @staticmethod
    def _alert_list_entries(lines: list[str]) -> dict[str, tuple[bool, str]]:
        entries: dict[str, tuple[bool, str]] = {}
        for line in lines:
            fields = TestAlertCenter._alert_list_fields(line)
            if not fields:
                continue
            match = ALERT_LIST_ID_PATTERN.fullmatch(fields[0])
            if match is None:
                continue
            if len(fields) < 5 or fields[2].upper() not in {
                "INFO",
                "WARNING",
                "CRITICAL",
            }:
                raise AssertionError(f"Malformed alert list entry: {line!r}")
            entries[match.group(1)] = (fields[3] == "*", line)
        return entries

    @staticmethod
    def _pending_alert_ids(lines: list[str]) -> list[str]:
        return [
            alert_id
            for alert_id, (pending, _) in TestAlertCenter._alert_list_entries(
                lines
            ).items()
            if pending
        ]

    @staticmethod
    def _assert_alert_entries_preserved(
        before: dict[str, tuple[bool, str]],
        after: dict[str, tuple[bool, str]],
    ) -> None:
        changed_entries = {
            alert_id: (previous[0], after.get(alert_id))
            for alert_id, previous in before.items()
            if after.get(alert_id) is None or after[alert_id][0] != previous[0]
        }
        assert not changed_entries, (
            "Alert operation changed or removed existing history entries "
            f"(pending state before/after): {changed_entries}"
        )

    @staticmethod
    def _alert_list_fields(line: str) -> list[str]:
        payload = line.rsplit("sentry:", maxsplit=1)[-1]
        return payload.strip().split()

    @staticmethod
    def _alert_list_summary(lines: list[str]) -> tuple[int, int]:
        for line in lines:
            payload = line.rsplit("sentry:", maxsplit=1)[-1]
            match = ALERT_LIST_SUMMARY_PATTERN.search(payload)
            if match:
                return int(match.group(1)), int(match.group(2))
        raise AssertionError(f"Could not parse CIC alert-list summary: {lines}")

    @staticmethod
    def _assert_acknowledgement(lines: list[str], alert_id: str) -> None:
        assert any(
            (match := ACKNOWLEDGEMENT_PATTERN.search(line))
            and match.group(1) == alert_id
            for line in lines
        ), f"Expected a CIC acknowledgement response for alert #{alert_id}, got: {lines}"

    @staticmethod
    def _assert_alert_list_response(lines: list[str]) -> None:
        assert any("[CIC]" in line for line in lines), (
            f"Expected a CIC alert-list response, got: {lines}"
        )

    @classmethod
    def _acknowledge_test_alerts(
        cls, driver: DeviceDriver, alert_ids: list[str]
    ) -> None:
        generated_ids = set(alert_ids)
        while generated_ids:
            listed = driver.alert_list()
            cls._assert_alert_list_response(listed)
            before_entries = cls._alert_list_entries(listed)
            pending_ids = [
                alert_id
                for alert_id, (pending, _) in before_entries.items()
                if pending
            ]
            generated_pending = generated_ids.intersection(pending_ids)
            if not generated_pending:
                return

            latest_pending_id = pending_ids[-1]
            if latest_pending_id not in generated_ids:
                raise AssertionError(
                    "Cannot safely clean test alerts with `alert ack` (latest): "
                    f"newest pending alert #{latest_pending_id} is not owned by this "
                    f"test; generated pending IDs: {sorted(generated_pending)}"
                )

            lines = driver.alert_ack()
            if any(ALREADY_ACKNOWLEDGED_PATTERN.search(line) for line in lines):
                raise AssertionError(
                    f"ACK latest returned W852 while alert #{latest_pending_id} "
                    f"was listed pending: {lines}"
                )
            cls._assert_acknowledgement(lines, latest_pending_id)

            refreshed_list = driver.alert_list()
            cls._assert_alert_list_response(refreshed_list)
            after_entries = cls._alert_list_entries(refreshed_list)
            acknowledged_entry = after_entries.get(latest_pending_id)
            if acknowledged_entry is None or acknowledged_entry[0]:
                raise AssertionError(
                    f"ACK latest should clear generated alert #{latest_pending_id}, "
                    f"but it remains pending or missing: {refreshed_list}"
                )
            cls._assert_alert_entries_preserved(
                {
                    alert_id: entry
                    for alert_id, entry in before_entries.items()
                    if alert_id not in generated_ids
                },
                after_entries,
            )

    @allure.story("AL-1 / AL-2 Alert generation and listing")
    @allure.title("Create and list test {level} alert")
    @pytest.mark.positive
    @pytest.mark.persistent
    @pytest.mark.parametrize("level", ["info", "warning"], ids=["INFO", "WARNING"])
    def test_alert_test_generation_and_list(
        self,
        authenticated_device: DeviceDriver,
        firmware_version: str,
        level: str,
    ) -> None:
        self._require_23(firmware_version)
        driver = authenticated_device
        alert_id: str | None = None
        try:
            with allure.step(f"Create a test {level.upper()} alert"):
                lines = driver.alert_test(level)
                alert_id = self._alert_id(lines, level)

            with allure.step("Verify the new alert appears as unacknowledged"):
                listed = driver.alert_list()
                entry = self._listed_alert(listed, alert_id)
                assert entry is not None, (
                    f"Alert #{alert_id} was missing from alert list: {listed}"
                )
                assert entry[0], (
                    f"New alert #{alert_id} should be marked pending with '*': {entry[1]}"
                )
        finally:
            if alert_id is not None:
                with allure.step(f"Acknowledge test alert #{alert_id} if still pending"):
                    self._acknowledge_test_alerts(driver, [alert_id])

    @allure.story("AL-1 / AL-2 Alert Center availability")
    @allure.title("List alerts on 2.3.0 or return the planned response on 2.1.0")
    def test_alert_list_or_planned_response(
        self,
        authenticated_device: DeviceDriver,
        firmware_version: str,
    ) -> None:
        lines = authenticated_device.alert_list()
        if firmware_version == "2.1.0":
            assert any("E099" in line for line in lines), (
                f"Expected E099 for Alert Center on firmware 2.1.0, got: {lines}"
            )
            return
        assert not any("E099" in line or "E001" in line for line in lines), (
            f"Alert Center list command should be available on firmware 2.3.0: {lines}"
        )
        assert any("[CIC]" in line for line in lines), (
            f"Expected a CIC alert-list response (not only command echo): {lines}"
        )

    @allure.story("AL-3 Alert acknowledgement")
    @allure.title("Acknowledge the latest pending alert")
    @pytest.mark.negative
    @pytest.mark.persistent
    def test_alert_acknowledge_latest(
        self,
        authenticated_device: DeviceDriver,
        firmware_version: str,
    ) -> None:
        self._require_23(firmware_version)
        driver = authenticated_device
        alert_ids: list[str] = []
        try:
            older_id = self._alert_id(driver.alert_test("info"), "info")
            alert_ids.append(older_id)
            latest_id = self._alert_id(driver.alert_test("warning"), "warning")
            alert_ids.append(latest_id)
            listed = driver.alert_list()
            older_entry = self._listed_alert(listed, older_id)
            latest_entry = self._listed_alert(listed, latest_id)
            assert older_entry is not None and older_entry[0], (
                f"Older alert #{older_id} must be pending before latest ACK"
            )
            assert latest_entry is not None and latest_entry[0], (
                f"Latest alert #{latest_id} must be pending before latest ACK"
            )
            with allure.step("Acknowledge the latest unacknowledged alert"):
                latest_ack = driver.alert_ack()
                self._assert_acknowledgement(latest_ack, latest_id)
                listed = driver.alert_list()
                older_entry = self._listed_alert(listed, older_id)
                latest_entry = self._listed_alert(listed, latest_id)
                assert latest_entry is not None and not latest_entry[0], (
                    f"Latest alert #{latest_id} should no longer be pending: {listed}"
                )
                assert older_entry is not None and older_entry[0], (
                    f"Earlier alert #{older_id} must remain pending after latest ACK: {listed}"
                )
        finally:
            with allure.step("Acknowledge any generated test alerts still pending"):
                self._acknowledge_test_alerts(driver, alert_ids)

    @allure.story("AL-3 Alert acknowledgement")
    @allure.title("Verify numeric ACK targets the displayed ID, not the preceding alert")
    @pytest.mark.persistent
    @pytest.mark.xfail(
        reason=(
            "BUG-016: firmware 2.3.0 acknowledges the preceding displayed alert "
            "for numeric alert ack <id>; see REPORT.md"
        ),
        strict=True,
    )
    def test_alert_acknowledge_exact_id(
        self,
        authenticated_device: DeviceDriver,
        firmware_version: str,
    ) -> None:
        self._require_23(firmware_version)
        driver = authenticated_device
        alert_ids: list[str] = []
        try:
            preceding_id = self._alert_id(driver.alert_test("info"), "info")
            alert_ids.append(preceding_id)
            target_id = self._alert_id(driver.alert_test("warning"), "warning")
            alert_ids.append(target_id)
            if int(target_id) != int(preceding_id) + 1:
                pytest.skip(
                    "Cannot isolate numeric-ACK indexing because another alert was "
                    f"inserted between test alerts #{preceding_id} and #{target_id}."
                )

            listed = driver.alert_list()
            preceding_entry = self._listed_alert(listed, preceding_id)
            target_entry = self._listed_alert(listed, target_id)
            assert preceding_entry is not None and preceding_entry[0], (
                f"Preceding test alert #{preceding_id} must be pending before ACK"
            )
            assert target_entry is not None and target_entry[0], (
                f"Target test alert #{target_id} must be pending before numeric ACK"
            )
            before_ack_entries = self._alert_list_entries(listed)
            with allure.step(
                f"Acknowledge displayed alert #{target_id}, preserving #{preceding_id}"
            ):
                ack_lines = driver.alert_ack(target_id)
                self._assert_acknowledgement(ack_lines, target_id)
                listed = driver.alert_list()
                after_entries = self._alert_list_entries(listed)
                preceding_entry = after_entries.get(preceding_id)
                target_entry = self._listed_alert(listed, target_id)
                assert (
                    target_entry is not None
                    and not target_entry[0]
                    and preceding_entry is not None
                    and preceding_entry[0]
                ), (
                    f"Numeric ACK hypothesis check failed: expected #{target_id} "
                    f"acknowledged while preceding #{preceding_id} remains pending; "
                    f"observed #{preceding_id}={preceding_entry}, "
                    f"#{target_id}={target_entry}. A shift to #{int(target_id) - 1} "
                    f"would indicate a one-based/zero-based index mismatch. List: {listed}"
                )
                self._assert_alert_entries_preserved(
                    {
                        existing_id: existing_entry
                        for existing_id, existing_entry in before_ack_entries.items()
                        if existing_id not in alert_ids
                    },
                    after_entries,
                )
        finally:
            with allure.step("Acknowledge any generated test alerts still pending"):
                self._acknowledge_test_alerts(driver, alert_ids)

    @allure.story("AL-3 Alert acknowledgement")
    @allure.title("Return W852 for duplicate ACK after resolving BUG-016 ID offset")
    @pytest.mark.negative
    @pytest.mark.persistent
    def test_alert_duplicate_acknowledgement_returns_w852(
        self,
        authenticated_device: DeviceDriver,
        firmware_version: str,
    ) -> None:
        self._require_23(firmware_version)
        driver = authenticated_device
        alert_ids: list[str] = []
        try:
            preceding_id = self._alert_id(driver.alert_test("info"), "info")
            alert_ids.append(preceding_id)
            alert_id = self._alert_id(driver.alert_test("warning"), "warning")
            alert_ids.append(alert_id)
            following_id = self._alert_id(driver.alert_test("info"), "info")
            alert_ids.append(following_id)
            if (
                int(alert_id) != int(preceding_id) + 1
                or int(following_id) != int(alert_id) + 1
            ):
                pytest.skip(
                    "Cannot isolate numeric-ACK indexing because another alert was "
                    "inserted between the three test alerts "
                    f"#{preceding_id}, #{alert_id}, and #{following_id}."
                )

            listed = driver.alert_list()
            preceding_entry = self._listed_alert(listed, preceding_id)
            pending_entry = self._listed_alert(listed, alert_id)
            following_entry = self._listed_alert(listed, following_id)
            assert preceding_entry is not None and preceding_entry[0], (
                f"Preceding test alert #{preceding_id} must be pending before ACK"
            )
            assert pending_entry is not None and pending_entry[0], (
                f"Target test alert #{alert_id} must be pending before duplicate-ACK checks"
            )
            assert following_entry is not None and following_entry[0], (
                f"Following test alert #{following_id} must be pending before duplicate-ACK checks"
            )
            before_ack_entries = self._alert_list_entries(listed)
            with allure.step(f"Resolve numeric ACK addressing for alert #{alert_id}"):
                first_ack = driver.alert_ack(alert_id)
                self._assert_acknowledgement(first_ack, alert_id)
                listed = driver.alert_list()
                after_first_entries = self._alert_list_entries(listed)
                target_entry = after_first_entries.get(alert_id)
                preceding_entry = after_first_entries.get(preceding_id)
                following_entry = after_first_entries.get(following_id)

                if (
                    target_entry is not None
                    and not target_entry[0]
                    and preceding_entry is not None
                    and preceding_entry[0]
                ):
                    duplicate_selector = alert_id
                    expected_states = {
                        preceding_id: True,
                        alert_id: False,
                        following_id: True,
                    }
                elif (
                    target_entry is not None
                    and target_entry[0]
                    and preceding_entry is not None
                    and not preceding_entry[0]
                ):
                    duplicate_selector = following_id
                    with allure.step(
                        f"Verify one-ID offset reaches displayed alert #{alert_id}"
                    ):
                        shifted_ack = driver.alert_ack(duplicate_selector)
                        self._assert_acknowledgement(
                            shifted_ack, duplicate_selector
                        )
                        listed = driver.alert_list()
                        after_first_entries = self._alert_list_entries(listed)
                    expected_states = {
                        preceding_id: False,
                        alert_id: False,
                        following_id: True,
                    }
                else:
                    raise AssertionError(
                        "Numeric ACK produced neither the PRD exact-ID behavior nor "
                        "the observed BUG-016 preceding-ID shift. "
                        f"Observed #{preceding_id}={preceding_entry}, "
                        f"#{alert_id}={target_entry}, #{following_id}={following_entry}. "
                        f"List: {listed}"
                    )

                state_mismatches = {
                    generated_id: (
                        expected_states[generated_id],
                        after_first_entries.get(generated_id),
                    )
                    for generated_id in alert_ids
                    if after_first_entries.get(generated_id) is None
                    or after_first_entries[generated_id][0]
                    != expected_states[generated_id]
                }
                assert not state_mismatches, (
                    "Unexpected state after resolving the acknowledged alert: "
                    f"{state_mismatches}; list: {listed}"
                )
                self._assert_alert_entries_preserved(
                    {
                        existing_id: existing_entry
                        for existing_id, existing_entry in before_ack_entries.items()
                        if existing_id not in alert_ids
                    },
                    after_first_entries,
                )

            with allure.step(
                f"Reject duplicate acknowledgement using numeric selector "
                f"#{duplicate_selector}"
            ):
                before_duplicate_entries = after_first_entries
                repeated = driver.alert_ack(duplicate_selector)
                assert any("W852" in line for line in repeated), (
                    "Expected W852 when repeating the selector for the acknowledged "
                    f"test alert #{alert_id} (selector #{duplicate_selector}), got: "
                    f"{repeated}"
                )
                after_duplicate_entries = self._alert_list_entries(
                    driver.alert_list()
                )
                changed_states = {
                    existing_id: (
                        before_entry[0],
                        after_duplicate_entries.get(existing_id),
                    )
                    for existing_id, before_entry in before_duplicate_entries.items()
                    if existing_id in expected_states
                    and (
                        after_duplicate_entries.get(existing_id) is None
                        or after_duplicate_entries[existing_id][0]
                        != expected_states[existing_id]
                    )
                }
                assert not changed_states, (
                    f"Repeated ACK #{duplicate_selector} changed alert states "
                    f"after W852: {changed_states}; list: "
                    f"{driver.alert_list()}"
                )
                self._assert_alert_entries_preserved(
                    before_duplicate_entries,
                    after_duplicate_entries,
                )
        finally:
            with allure.step("Acknowledge generated test alerts using ACK latest"):
                self._acknowledge_test_alerts(driver, alert_ids)

    @allure.story("AL-3 Alert acknowledgement")
    @allure.title("Return E851 for an alert ID that does not exist")
    @pytest.mark.negative
    def test_alert_unknown_id_returns_e851(
        self,
        authenticated_device: DeviceDriver,
        firmware_version: str,
    ) -> None:
        self._require_23(firmware_version)
        driver = authenticated_device
        invalid_id = 999999999
        listed = driver.alert_list()
        assert self._listed_alert(listed, str(invalid_id)) is None, (
            f"Chosen invalid ID {invalid_id} unexpectedly exists: {listed}"
        )
        with allure.step(f"Reject unknown alert ID {invalid_id}"):
            unknown = driver.alert_ack(invalid_id)
            assert any("E851" in line for line in unknown), (
                f"Expected E851 for unknown alert ID {invalid_id}, got: {unknown}"
            )

    @allure.story("AL-4 Alert clearing")
    @allure.title("Require acknowledgement before clearing alerts")
    @pytest.mark.negative
    @pytest.mark.persistent
    def test_alert_clear_requires_acknowledgement(
        self,
        authenticated_device: DeviceDriver,
        firmware_version: str,
    ) -> None:
        self._require_23(firmware_version)
        driver = authenticated_device
        alert_id: str | None = None
        try:
            initial_list = driver.alert_list()
            self._assert_alert_list_response(initial_list)

            created = driver.alert_test("info")
            alert_id = self._alert_id(created, "info")
            with allure.step("Reject clearing while a test alert is unacknowledged"):
                before_clear_list = driver.alert_list()
                before_clear_entries = self._alert_list_entries(before_clear_list)
                before_clear = before_clear_entries.get(alert_id)
                assert before_clear is not None and before_clear[0], (
                    f"Test alert #{alert_id} must be pending before alert clear"
                )
                clear_lines = driver.alert_clear()
                assert any("E855" in line for line in clear_lines), (
                    f"Expected E855 while alert #{alert_id} remains pending, got: {clear_lines}"
                )
                listed = driver.alert_list()
                after_clear_entries = self._alert_list_entries(listed)
                after_clear = after_clear_entries.get(alert_id)
                assert after_clear is not None and after_clear[0], (
                    f"Alert clear removed the unacknowledged alert #{alert_id}: {listed}"
                )
                self._assert_alert_entries_preserved(
                    before_clear_entries,
                    after_clear_entries,
                )
        finally:
            if alert_id is not None:
                with allure.step(f"Acknowledge test alert #{alert_id} without clearing user history"):
                    self._acknowledge_test_alerts(driver, [alert_id])

    @allure.story("AL-3 / AL-4 Explicit alert history cleanup")
    @allure.title("Acknowledge pending alerts and clear all history only with operator approval")
    @pytest.mark.interactive
    @pytest.mark.persistent
    @pytest.mark.alert_cleanup
    def test_alert_clear_all_history_on_explicit_operator_approval(
        self,
        authenticated_device: DeviceDriver,
        firmware_version: str,
        manual_prepare: Any,
        manual_check: Any,
    ) -> None:
        self._require_23(firmware_version)
        driver = authenticated_device
        initial_list = driver.alert_list()
        self._assert_alert_list_response(initial_list)
        alert_count, pending_count = self._alert_list_summary(initial_list)
        pending_ids = self._pending_alert_ids(initial_list)

        prepare_observation(
            manual_prepare,
            action=(
                "Review the complete alert list included below. This cleanup acknowledges "
                "every pending alert and permanently deletes the entire alert history."
            ),
            expected=(
                f"Current list reports {alert_count} alerts and {pending_count} pending "
                f"(visible pending IDs: {pending_ids}). The operation affects all alert "
                "sources, not just autotest alerts.\n\nComplete alert list:\n"
                + "\n".join(initial_list)
            ),
            duration="~10 seconds to review the list",
        )
        if not manual_check(
            "I reviewed the alerts and explicitly approve ACK ALL pending alerts "
            "followed by permanently clearing the entire alert history."
        ):
            pytest.skip("Operator declined to acknowledge all alerts and clear history.")

        with allure.step("Acknowledge all pending alerts"):
            ack_lines = driver.alert_ack("all")
            if pending_count == 0:
                assert any("W853" in line for line in ack_lines), (
                    f"Expected W853 when no alerts are pending: {ack_lines}"
                )
            acknowledged_list = driver.alert_list()
            self._assert_alert_list_response(acknowledged_list)
            _, remaining_pending = self._alert_list_summary(acknowledged_list)
            assert remaining_pending == 0, (
                f"ACK ALL left {remaining_pending} alerts pending: {acknowledged_list}"
            )

        with allure.step("Clear all acknowledged alert history"):
            clear_lines = driver.alert_clear()
            assert not any(re.search(r"\bE\d{3}\b", line) for line in clear_lines), (
                f"Alert clear returned an error after ACK ALL: {clear_lines}"
            )
            cleared_list = driver.alert_list()
            self._assert_alert_list_response(cleared_list)
            summary = self._alert_list_summary(cleared_list)
            assert summary == (0, 0), (
                f"Expected an empty alert history after clear, got {summary}: {cleared_list}"
            )

    @allure.story("AL-1 / AL-2 / AL-5 Critical alert generation and effects")
    @allure.title("Critical {initial_state} test alert raises VERBOSE and opens relay")
    @pytest.mark.interactive
    @pytest.mark.persistent
    @pytest.mark.parametrize("initial_state", ["NORMAL", "DEBUG"], ids=["from-normal", "from-debug"])
    def test_alert_critical_effects(
        self,
        authenticated_device: DeviceDriver,
        firmware_version: str,
        initial_state: str,
        manual_prepare: Any,
        manual_check: Any,
        soft: SoftChecks,
    ) -> None:
        self._require_23(firmware_version)
        driver = authenticated_device
        relay = driver.relay_status()
        assert relay["state"] == "CLOSED" and relay["auto"] == "off", (
            f"Critical-alert test requires a closed relay and auto off: {relay}"
        )
        original_state = driver.get_state()
        assert original_state[0] != 4, (
            "Critical-alert test cannot start in EMERGENCY; reboot the device first."
        )

        alert_id: str | None = None
        critical_may_be_active = False
        state_may_need_restore = False
        try:
            requested_state = {"NORMAL": 1, "DEBUG": 2}[initial_state]
            if original_state[0] != requested_state:
                state_may_need_restore = True
                with allure.step(f"Set the precondition state to {initial_state}"):
                    driver.set_state(requested_state)
            assert driver.get_state() == (requested_state, initial_state), (
                f"Critical-alert test requires {initial_state} state"
            )

            prepare_observation(
                manual_prepare,
                action=(
                    "Observe the relay and the Beacon lamp (main lamp); "
                    "do not press any buttons."
                ),
                expected=(
                    f"Required AL-5 behavior: a CRITICAL alert changes {initial_state} "
                    "to VERBOSE and opens the relay. Also note whether the Beacon lamp "
                    "flashes purple; this is an additional observation, not an AL-5 criterion."
                ),
                duration="~5 seconds",
            )
            mark = driver.buffer_len()
            with allure.step("Create a CRITICAL test alert"):
                critical_may_be_active = True
                state_may_need_restore = True
                lines = driver.alert_test("critical", timeout=1.0)
                alert_match = next(
                    (
                        match
                        for line in lines
                        if (match := ALERT_PATTERN.search(line))
                        and match.group(2).casefold() == "critical"
                    ),
                    None,
                )
                soft.check(
                    alert_match is not None,
                    f"Expected a CRITICAL alert event in command response: {lines}",
                )
                if alert_match is not None:
                    alert_id = alert_match.group(1)

            with allure.step("Confirm the physical critical-alert relay effect"):
                relay_physical_confirmed = manual_check(
                    f"Did you hear the relay open after the CRITICAL alert changed "
                    f"{initial_state} to VERBOSE?"
                )
                soft.check(
                    relay_physical_confirmed,
                    "Operator did not confirm the physical critical-alert relay effect",
                )

            with allure.step("Record the additional purple Beacon observation"):
                manual_check(
                    "Additional observation only (not an AL-5 pass criterion): "
                    "Did the Beacon lamp flash purple?"
                )

            with allure.step("Verify the CRITICAL alert is listed as pending"):
                listed = driver.alert_list()
                soft.check(
                    any("[CIC]" in line for line in listed),
                    f"Expected a CIC alert-list response, got: {listed}",
                )
                if alert_id is not None and any("[CIC]" in line for line in listed):
                    entry = self._listed_alert(listed, alert_id)
                    soft.check(
                        entry is not None and entry[0],
                        f"Critical alert #{alert_id} should appear pending: {listed}",
                    )

            with allure.step("Verify the CRITICAL alert effects"):
                critical_event_seen = driver.wait_for(
                    "CRITICAL", timeout=2.0, since_index=mark
                )
                soft.check(
                    critical_event_seen,
                    f"CRITICAL alert was not captured: {driver.uart_log[mark:]}",
                )
                relay = driver.relay_status()
                state = driver.get_state()
                soft.check(
                    relay["state"] == "OPEN",
                    f"Critical alert should open the relay; got: {relay}",
                )
                soft.check(
                    state == (3, "VERBOSE"),
                    f"Critical alert should change {initial_state} to VERBOSE; got: {state}",
                )
            soft.assert_all()
        finally:
            if critical_may_be_active or state_may_need_restore:
                with allure.step("Restore relay and system state and acknowledge test alert"):
                    cleanup_failures: list[str] = []
                    try:
                        if critical_may_be_active:
                            time.sleep(0.55)
                            close_lines = driver.relay_off()
                            if not any(
                                "[VALVE] CLOSED" in line or "W601" in line
                                for line in close_lines
                            ):
                                cleanup_failures.append(
                                    f"Could not close relay: {close_lines}"
                                )
                    finally:
                        try:
                            if driver.get_state() != original_state:
                                state_lines = driver.set_state(original_state[0])
                                restored_state = driver.get_state()
                                if restored_state != original_state:
                                    cleanup_failures.append(
                                        f"Could not restore {original_state[1]} state: "
                                        f"{state_lines}; current state: {restored_state}"
                                    )
                        finally:
                            try:
                                if alert_id is not None:
                                    self._acknowledge_test_alerts(driver, [alert_id])
                            finally:
                                final_relay = driver.relay_status()
                                final_state = driver.get_state()
                                if final_relay["state"] != "CLOSED":
                                    cleanup_failures.append(
                                        f"Relay remains open after cleanup: {final_relay}"
                                    )
                                if final_state != original_state:
                                    cleanup_failures.append(
                                        f"System did not return to its initial state "
                                        f"{original_state}: {final_state}"
                                    )
                    assert not cleanup_failures, (
                        "Critical-alert cleanup failed:\n- "
                        + "\n- ".join(cleanup_failures)
                    )


def test_alert_cleanup_uses_latest_ack_without_numeric_id() -> None:
    header_pending = "I (6935520) sentry: [CIC] 2 alerts, 2 unacknowledged:"
    older_pending = "I (6935530) sentry: #13 20:25:00 INFO * test test alert"
    generated_pending = "I (6935540) sentry: #14 20:25:01 WARNING * test test alert"
    header_after = "I (6935550) sentry: [CIC] 2 alerts, 1 unacknowledged:"
    older_unchanged = "I (6935560) sentry: #13 20:25:00 INFO * test test alert"
    generated_acknowledged = "I (6935570) sentry: #14 20:25:01 WARNING test test alert"
    driver = Mock()
    driver.alert_list.side_effect = [
        [header_pending, older_pending, generated_pending],
        [header_after, older_unchanged, generated_acknowledged],
    ]
    driver.alert_ack.return_value = ["[CIC] #14 acknowledged (command)"]

    TestAlertCenter._acknowledge_test_alerts(driver, ["14"])

    driver.alert_ack.assert_called_once_with()
    assert driver.alert_list.call_count == 2


def test_alert_cleanup_refuses_to_acknowledge_an_unowned_latest_alert() -> None:
    header = "I (6935520) sentry: [CIC] 1 alerts, 1 unacknowledged:"
    other_pending = "I (6935530) sentry: #13 20:25:00 INFO * user alert"
    generated_acknowledged = "I (6935540) sentry: #14 20:25:01 INFO test test alert"
    driver = Mock()
    driver.alert_list.return_value = [header, other_pending, generated_acknowledged]

    with pytest.raises(AssertionError, match="not owned by this test"):
        TestAlertCenter._acknowledge_test_alerts(driver, ["14"])

    driver.alert_ack.assert_not_called()
    assert driver.alert_list.call_count == 1


def test_alert_cleanup_rejects_latest_ack_that_leaves_generated_alert_pending() -> None:
    header = "I (6935520) sentry: [CIC] 1 alerts, 1 unacknowledged:"
    pending = "I (6935530) sentry: #13 20:25:00 INFO * test test alert"
    driver = Mock()
    driver.alert_list.side_effect = [[header, pending], [header, pending]]
    driver.alert_ack.return_value = ["[CIC] #13 acknowledged"]

    with pytest.raises(AssertionError, match="remained pending after ACK"):
        TestAlertCenter._acknowledge_test_alerts(driver, ["13"])

    driver.alert_ack.assert_called_once_with()
    assert driver.alert_list.call_count == 2
