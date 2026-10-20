from __future__ import annotations

import logging
import math
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
PREPARE_COLOR = "1;36"
CHECK_COLOR = "1;33"
PASS_COLOR = "1;32"
FAIL_COLOR = "1;31"


def _supports_color() -> bool:
    return (
        sys.stdout.isatty()
        and "NO_COLOR" not in os.environ
        and os.environ.get("TERM", "").casefold() != "dumb"
    )


def _style(text: str, color_code: str) -> str:
    if not _supports_color():
        return text
    return f"\033[{color_code}m{text}\033[0m"


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


def _highlight_instruction(instruction: str, color_code: str) -> str:
    highlighted: list[str] = []
    for line in instruction.splitlines():
        match = re.match(r"^(What to do:|What to observe:|Duration:)(.*)$", line)
        if match:
            label = _style(match.group(1), color_code)
            highlighted.append(f"  {label}{match.group(2)}")
        elif line:
            highlighted.append(f"  {_style(line, color_code)}")
        else:
            highlighted.append("")
    text = "\n".join(highlighted)
    return _add_lamp_color_indicators(text) if _supports_color() else text


def _print_manual_prompt(heading: str, instruction: str, color_code: str) -> None:
    content = _highlight_instruction(instruction, color_code)
    separator = "=" * 70
    title = _style(heading, color_code)
    print(f"\n{_style(separator, color_code)}\n{title}\n{content}\n{_style(separator, color_code)}\n")


def _input_prompt(prompt: str, color_code: str) -> str:
    return f"{_style('>>', color_code)} {_style(prompt, color_code)}"


def _redact_sensitive_comment(comment: str) -> str:
    return re.sub(
        r"(?i)\b(password|passwd|pwd|token|secret|api[_-]?key)\b"
        r"((?:\s+is)?\s*[:=]\s*|(?:\s+is)?\s+)"
        r"(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)",
        r"\1\2[REDACTED]",
        comment,
    )


def _print_manual_result(result: str, instruction: str, comment: str | None = None) -> None:
    color_code = PASS_COLOR if result == "PASS" else FAIL_COLOR
    detail = instruction
    if comment:
        detail = f"{detail}\nComment: {_redact_sensitive_comment(comment)}"
    _print_manual_prompt(f"MANUAL RESULT - {result}", detail, color_code)


def _print_manual_notice(message: str) -> None:
    _print_manual_prompt("MANUAL INPUT NEEDED", message, FAIL_COLOR)


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


def status_indicator_color(is_connected: bool, is_logged_in: bool) -> str:
    """Return the observed LM-8 RGB LED status color mapping."""
    if not is_connected:
        return "red"
    return "green" if is_logged_in else "orange"


def status_indicator_description(is_connected: bool, is_logged_in: bool) -> str:
    """Describe the expected status LED color and its Wi-Fi/login meaning."""
    if not is_connected:
        return "RED (Wi-Fi disconnected)"
    if is_logged_in:
        return "GREEN (Wi-Fi connected and logged in)"
    return "ORANGE (Wi-Fi connected, logged out)"


STATUS_INDICATOR_LEGEND = (
    "Status LED guide: RED = Wi-Fi disconnected; "
    "ORANGE = Wi-Fi connected, logged out; "
    "GREEN = Wi-Fi connected, logged in."
)



def _attach_manual_feedback(
    instruction: str, result: str, comment: str | None = None
) -> None:
    lines = [f"Check: {instruction}", f"Result: {result}"]
    if comment:
        comment = _redact_sensitive_comment(comment)
        lines.append(f"Comment: {comment}")
    LOGGER.info(
        "MANUAL CHECK | %s | result=%s | comment=%s",
        instruction,
        result,
        comment or "-",
    )
    allure.attach(
        "\n".join(lines),
        name="Manual verification",
        attachment_type=allure.attachment_type.TEXT,
    )


class SoftChecks:
    """Collect failed checks so one failure does not hide the others."""

    def __init__(self) -> None:
        self.failures: list[str] = []

    def check(self, condition: object, message: str) -> bool | None:
        if condition is None:
            LOGGER.info("MANUAL CHECK | NOT RUN (UART-only mode) | %s", message)
            with allure.step(f"NOT RUN (UART-only mode): {message}"):
                pass
            return None

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
    """Pause so the operator can prepare and watch the device before the next action."""
    _print_manual_prompt("GET READY - MANUAL PREPARE", instruction, PREPARE_COLOR)
    LOGGER.info("MANUAL PREPARE | Waiting for operator confirmation.")
    try:
        input(_input_prompt("Press Enter when ready:", PREPARE_COLOR))
    except EOFError:
        pytest.fail("Manual input is unavailable; run pytest with -s in a terminal.")


@allure.step("Record measured reference distance: {label}")
def enter_reference_distance(label: str) -> float:
    """Collect and record the operator-measured target distance in centimeters."""
    while True:
        try:
            response = input(_input_prompt(f"{label} (cm):", PREPARE_COLOR)).strip()
        except EOFError:
            _attach_manual_feedback(label, "NOT RECORDED (no interactive input)")
            pytest.fail("Manual input is unavailable; run pytest with -s in a terminal.")

        try:
            distance_cm = float(response.replace(",", "."))
        except ValueError:
            _print_manual_notice("Enter a numeric distance in centimeters, for example 20 or 20.5.")
            continue

        if not math.isfinite(distance_cm) or distance_cm <= 0:
            _print_manual_notice("Distance must be a finite value greater than 0 cm.")
            continue

        recorded = f"{label}: {distance_cm:.2f} cm"
        LOGGER.info("MANUAL INPUT | %s", recorded)
        allure.attach(
            recorded,
            name="Operator-measured reference distance",
            attachment_type=allure.attachment_type.TEXT,
        )
        return distance_cm


@allure.step("Ask whether to measure another target distance")
def ask_to_continue_measurements() -> bool:
    """Ask the operator whether another physical target position should be measured."""
    while True:
        try:
            response = input(
                _input_prompt(
                    "Measure another target position? [y] yes / [n] finish:",
                    PREPARE_COLOR,
                )
            ).strip().casefold()
        except EOFError:
            _attach_manual_feedback(
                "Continue the distance measurement series",
                "NOT RECORDED (no interactive input)",
            )
            pytest.fail("Manual input is unavailable; run pytest with -s in a terminal.")

        if response in {"y", "yes"}:
            LOGGER.info("MANUAL INPUT | Continue distance measurements: yes")
            allure.attach(
                "Operator chose to continue the distance measurement series.",
                name="Distance measurement session decision",
                attachment_type=allure.attachment_type.TEXT,
            )
            return True
        if response in {"n", "no"}:
            LOGGER.info("MANUAL INPUT | Continue distance measurements: no")
            allure.attach(
                "Operator chose to finish the distance measurement series.",
                name="Distance measurement session decision",
                attachment_type=allure.attachment_type.TEXT,
            )
            return False

        _print_manual_notice("Enter y to measure another position or n to finish.")


@allure.step("Manual verification: {instruction}")
def verify_manually(instruction: str) -> bool:
    """Ask for an observed physical result; return False (not raise) on 'n'."""
    _print_manual_prompt("MANUAL CHECK", instruction, CHECK_COLOR)

    comment: str | None = None
    while True:
        try:
            response = input(
                _input_prompt(
                    "Observed result? [y] pass / [n] fail / [c] add comment:",
                    CHECK_COLOR,
                )
            )
        except EOFError:
            _attach_manual_feedback(instruction, "NOT RECORDED (no interactive input)")
            pytest.fail("Manual input is unavailable; run pytest with -s in a terminal.")

        response = response.strip().casefold()
        if response in {"y", "n"}:
            passed = response == "y"
            result = "PASS" if passed else "FAIL"
            _attach_manual_feedback(instruction, result, comment)
            _print_manual_result(result, instruction, comment)
            return passed
        if response == "c":
            try:
                comment = input(
                    _input_prompt(
                        "Add a non-sensitive observation or failure detail "
                        "(do not enter passwords, tokens, or secrets):",
                        CHECK_COLOR,
                    )
                ).strip()
            except EOFError:
                _attach_manual_feedback(
                    instruction, "NOT RECORDED (comment input unavailable)"
                )
                pytest.fail("Manual comment input is unavailable; run pytest with -s.")
            continue

        _print_manual_notice("Invalid response. Enter y, n, or c.")
