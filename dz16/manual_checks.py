from __future__ import annotations

import logging
import os
import re
import sys
from collections.abc import Callable

import allure
import pytest

LOGGER = logging.getLogger(__name__)

COLOR_CODES = {
    "red": "91",
    "green": "92",
    "blue": "94",
    "yellow": "93",
    "purple": "95",
    "cyan": "96",
    "orange": "38;5;208",
    "white": "97",
}


def _supports_color() -> bool:
    return (
        sys.stdout.isatty()
        and "NO_COLOR" not in os.environ
        and os.environ.get("TERM", "").casefold() != "dumb"
    )


def _add_lamp_color_indicators(text: str) -> str:
    rgb_pattern = re.compile(
        r"(?<![\w])(?:RGB\s*)?"
        r"\(\s*(?P<red>\d{1,3})\s*,\s*(?P<green>\d{1,3})\s*,"
        r"\s*(?P<blue>\d{1,3})\s*\)(?!\w)",
        re.IGNORECASE,
    )

    def apply_rgb_color(match: re.Match[str]) -> str:
        red, green, blue = (int(match.group(channel)) for channel in ("red", "green", "blue"))
        if any(value > 255 for value in (red, green, blue)):
            return match.group(0)
        indicator = f"\033[1;38;2;{red};{green};{blue}m●\033[0m"
        return f"{indicator} {match.group(0)}"

    text = rgb_pattern.sub(apply_rgb_color, text)
    pattern = re.compile(
        r"\b(red|green|blue|yellow|purple|cyan|orange|white)\b"
        r"(?:\s+(?:lamp|led))?",
        re.IGNORECASE,
    )

    def apply_color(match: re.Match[str]) -> str:
        color = match.group(1).casefold()
        indicator = f"\033[{COLOR_CODES[color]}m●\033[0m"
        return f"{indicator} {match.group(0)}"

    return pattern.sub(apply_color, text)


def _print_manual_prompt(heading: str, instruction: str, color_code: str) -> None:
    if _supports_color():
        heading = f"\033[{color_code}m{heading}\033[0m"
        instruction = _add_lamp_color_indicators(instruction)

    separator = "=" * 60
    print(f"\n{separator}\n{heading}\n\n{instruction}\n{separator}\n")


def prepare_observation(
    prepare: Callable[[str], None],
    *,
    action: str,
    expected: str,
    duration: str,
) -> None:
    """Present a consistent operator-ready prompt before a physical observation."""
    prepare(
        f"What to do: {action}\n\n"
        f"What to observe: {expected}\n\n"
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
    _print_manual_prompt("GET READY - MANUAL PREPARE", instruction, "1;36")
    LOGGER.info("MANUAL PREPARE | Waiting for operator confirmation.")
    try:
        input("Press Enter when ready: ")
    except EOFError:
        pytest.fail("Manual input is unavailable; run pytest with -s in a terminal.")


@allure.step("Manual verification: {instruction}")
def verify_manually(instruction: str) -> bool:
    """Ask for an observed physical result; return False (not raise) on 'n'."""
    _print_manual_prompt("MANUAL CHECK", instruction, "1;33")

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
