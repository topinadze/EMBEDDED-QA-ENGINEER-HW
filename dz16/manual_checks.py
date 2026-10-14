from __future__ import annotations

import logging
from collections.abc import Callable

import allure
import pytest

LOGGER = logging.getLogger(__name__)


def prepare_observation(
    prepare: Callable[[str], None],
    *,
    action: str,
    expected: str,
    duration: str,
) -> None:
    """Present a consistent operator-ready prompt before a physical observation."""
    prepare(
        f"What to do: {action}\n"
        f"What to observe: {expected}\n"
        f"Duration: {duration}."
    )


def wifi_indicator_color(is_connected: bool) -> str:
    """Return the expected status LED color for the observed Wi-Fi state."""
    return "dim green" if is_connected else "dim red"


def _attach_manual_feedback(
    instruction: str, result: str, comment: str | None = None
) -> None:
    lines = [f"Check: {instruction}", f"Result: {result}"]
    if comment:
        lines.append(f"Comment: {comment}")
    LOGGER.info("MANUAL CHECK | %s | result=%s | comment=%s", instruction, result, comment or "-")
    allure.attach(
        "\n".join(lines),
        name="Manual verification",
        attachment_type=allure.attachment_type.TEXT,
    )


class SoftChecks:
    """Collect failed checks so one failure does not hide the others."""

    def __init__(self) -> None:
        self.failures: list[str] = []

    def check(self, condition: object, message: str) -> bool:
        ok = bool(condition)
        if not ok:
            LOGGER.error("SOFT CHECK FAILED | %s", message)
            self.failures.append(message)
        with allure.step(f"{'PASS' if ok else 'FAIL'}: {message}"):
            pass
        return ok

    def assert_all(self) -> None:
        if self.failures:
            pytest.fail(
                f"{len(self.failures)} check(s) failed:\n- " + "\n- ".join(self.failures),
                pytrace=False,
            )


@allure.step("Manual preparation: {instruction}")
def prepare_manually(instruction: str) -> None:
    """Pause so the operator can watch the device before the next action."""
    print(f"\n{'=' * 60}")
    print("GET READY")
    print(instruction)
    print(f"{'=' * 60}")
    LOGGER.info("MANUAL PREPARE | %s", instruction)
    try:
        input("Press Enter when ready: ")
    except EOFError:
        pytest.fail("Manual input is unavailable; run pytest with -s in a terminal.")


@allure.step("Manual verification: {instruction}")
def verify_manually(instruction: str) -> bool:
    """Ask for an observed physical result; return False (not raise) on 'n'."""
    print(f"\n{'=' * 60}")
    print("MANUAL CHECK REQUIRED")
    print(instruction)
    print(f"{'=' * 60}")

    comment: str | None = None
    while True:
        try:
            response = input("Observed result? [y] pass / [n] fail / [c] add comment: ")
        except EOFError:
            _attach_manual_feedback(instruction, "NOT RECORDED (no interactive input)")
            pytest.fail("Manual input is unavailable; run pytest with -s in a terminal.")

        response = response.strip().casefold()
        if response in {"y", "n"}:
            passed = response == "y"
            result = "PASS" if passed else "FAIL"
            _attach_manual_feedback(instruction, result, comment)
            print(f"Manual check recorded: {result}")
            return passed
        if response == "c":
            try:
                comment = input("Add an observation or failure detail: ").strip()
            except EOFError:
                _attach_manual_feedback(
                    instruction, "NOT RECORDED (comment input unavailable)"
                )
                pytest.fail("Manual comment input is unavailable; run pytest with -s.")
            continue

        print("Enter y, n, or c.")
