from __future__ import annotations

import logging
import math
import os
import re
import sys
from collections.abc import Callable

import allure
import pytest
from utils.telegram_helper import (
    lamp_color_marker,
    telegram_choice,
    telegram_notify,
    telegram_text,
)

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
TELEGRAM_TIMEOUT_SECONDS = 300


def interaction_mode() -> str:
    mode = os.environ.get("INTERACTION_MODE", "console").strip().casefold()
    if mode not in {"console", "telegram"}:
        raise pytest.UsageError(
            "INTERACTION_MODE must be either 'console' or 'telegram'."
        )
    return mode


def _telegram_mode() -> bool:
    return interaction_mode() == "telegram"


def _telegram_timeout() -> int:
    raw_timeout = os.environ.get("TELEGRAM_TIMEOUT", str(TELEGRAM_TIMEOUT_SECONDS))
    try:
        timeout = int(raw_timeout)
    except ValueError as error:
        raise pytest.UsageError("TELEGRAM_TIMEOUT must be an integer.") from error
    if timeout <= 0:
        raise pytest.UsageError("TELEGRAM_TIMEOUT must be positive.")
    return timeout


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


def _rgb_color_chip(rgb: tuple[int, int, int]) -> str:
    red, green, blue = rgb
    if not _supports_color():
        return "[RGB sample]"
    return f"\033[48;2;{red};{green};{blue}m  \033[0m [sample]"


def _highlight_instruction(instruction: str, color_code: str) -> str:
    highlighted: list[str] = []
    for line in instruction.splitlines():
        match = re.match(
            r"^(➡️ ACTION:|👀 OBSERVE:|⏱ DURATION:|"
            r"What to do:|What to observe:|Duration:)(.*)$",
            line,
        )
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
    if re.search(r"\bK[1-4]\b", action, re.IGNORECASE):
        if re.search(r"\bwhile logged out\b", action, re.IGNORECASE):
            session_status = "🔓 LOGGED OUT"
        elif re.search(r"\blogs out\b", action, re.IGNORECASE):
            session_status = "🔐 LOGGED IN AT START"
        else:
            session_status = "🔐 LOGIN VERIFIED"
        action = f"👆 {session_status} — {action}"
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



def _telegram_topic(text: str) -> str:
    normalized = text.casefold()
    if re.search(r"clear(?:ing)? (?:the entire )?alert history|ack all", normalized):
        return "⚠️ ALERT HISTORY CLEANUP"
    if "alert" in normalized or "acknowledge" in normalized:
        return "🔔 ALERT CENTER"
    if any(word in normalized for word in ("guard", "panic", "intrusion", "alarm")):
        return "🚨 GUARD / ALARM"
    if any(word in normalized for word in ("wi-fi", "wifi", "access point", "router")):
        return "📶 WI-FI"
    if any(word in normalized for word in ("distance", "sonar", "target", "hc-sr04")):
        return "📏 DISTANCE / SONAR"
    if re.search(r"\bk[1-4]\b|button", normalized):
        return "🔘 BUTTONS"
    if any(word in normalized for word in ("relay", "valve", "gpio4")):
        return "🔌 RELAY"
    if any(word in normalized for word in ("lamp", "beacon", "rgb")):
        return "💡 LAMP / BEACON"
    if any(word in normalized for word in ("led", "status indicator")):
        return "💡 STATUS INDICATOR"
    return "🧪 DEVICE CHECK"


def _telegram_color_marker(text: str) -> str | None:
    matches = re.findall(
        r"\b(red|green|blue|yellow|purple|cyan|orange|white)\b",
        text,
        re.IGNORECASE,
    )
    return lamp_color_marker(matches[-1]) if matches else None


def _telegram_prepare_message(instruction: str, *, allow_skip: bool = False) -> str:
    topic = _telegram_topic(instruction)
    labels = (
        ("What to do:", "➡️ ACTION:"),
        ("What to observe:", "👀 OBSERVE:"),
        ("Duration:", "⏱ DURATION:"),
    )
    formatted = instruction
    for source, replacement in labels:
        formatted = re.sub(source, replacement, formatted, flags=re.IGNORECASE)
    if not re.search(r"➡️ ACTION:|👀 OBSERVE:|⏱ DURATION:", formatted):
        formatted = f"➡️ ACTION:\n{formatted}"
    closing = "Confirm with ✅ READY when prepared."
    if allow_skip:
        closing += "\nOr choose ⏭ SKIP TEST to skip this whole test."
    return (
        f"{topic}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🧰 GET READY\n\n"
        f"{formatted.strip()}\n\n"
        f"{closing}"
    )


def _telegram_manual_check_message(
    instruction: str,
    *,
    expected_rgb: tuple[int, int, int] | None = None,
    expected_color: str | None = None,
) -> str:
    if expected_rgb is not None:
        marker = lamp_color_marker(expected_color)
        color_name = expected_color.upper() if expected_color else "CUSTOM COLOR"
        return (
            f"{marker} LAMP COLOR CHECK — {color_name}\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "👀 OBSERVE\n"
            f"Does the lit Beacon look {color_name}?\n"
            f"🎨 Expected RGB: {expected_rgb[0]}, "
            f"{expected_rgb[1]}, {expected_rgb[2]}\n\n"
            "Choose the result that matches what you saw."
        )

    topic = _telegram_topic(instruction)
    marker = _telegram_color_marker(instruction)
    color_label = f" {marker}" if marker else ""
    warning = (
        "\n⚠️ This action permanently deletes alert history."
        if topic == "⚠️ ALERT HISTORY CLEANUP"
        else ""
    )
    return (
        f"{topic}{color_label}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"👀 OBSERVE\n{instruction.strip()}{warning}\n\n"
        "Choose the result that matches what you saw."
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


def _skip_test_by_operator(instruction: str) -> None:
    _attach_manual_feedback(instruction, "SKIPPED BY OPERATOR (at first preparation)")
    LOGGER.info("MANUAL PREPARE | Operator skipped the test before preparation.")
    pytest.skip("Operator skipped this test at the first preparation prompt.")


@allure.step("Manual preparation: {instruction}")
def prepare_manually(instruction: str, *, allow_skip: bool = False) -> None:
    """Pause so the operator can prepare and watch the device before the next action.

    With ``allow_skip`` the operator may skip the whole test instead of preparing;
    the test is then reported as skipped, never as passed.
    """
    if _telegram_mode():
        choices = [("ready", "✅ READY")]
        if allow_skip:
            choices.append(("skip", "⏭ SKIP TEST"))
        try:
            telegram_instruction = _telegram_prepare_message(
                instruction, allow_skip=allow_skip
            )
            response = telegram_choice(
                telegram_instruction,
                choices,
                _telegram_timeout(),
            )
        except TimeoutError:
            _attach_manual_feedback(
                instruction, "NOT RECORDED (Telegram preparation timeout)"
            )
            pytest.fail("Operator did not confirm preparation in Telegram before timeout.")
        if allow_skip and response == "skip":
            _skip_test_by_operator(instruction)
        LOGGER.info("MANUAL PREPARE | Operator confirmed readiness via Telegram.")
        allure.attach(
            f"Operator confirmed readiness.\n{instruction}",
            name="Telegram preparation confirmation",
            attachment_type=allure.attachment_type.TEXT,
        )
        return

    console_instruction = instruction.replace(
        "What to do:", "➡️ ACTION:"
    ).replace("What to observe:", "👀 OBSERVE:").replace(
        "Duration:", "⏱ DURATION:"
    )
    _print_manual_prompt("🧰 GET READY", console_instruction, PREPARE_COLOR)
    LOGGER.info("MANUAL PREPARE | Waiting for operator confirmation.")
    prompt = (
        "Press Enter when ready, or type s to skip this test:"
        if allow_skip
        else "Press Enter when ready:"
    )
    while True:
        try:
            response = input(_input_prompt(prompt, PREPARE_COLOR))
        except EOFError:
            pytest.fail("Manual input is unavailable; run pytest with -s in a terminal.")
        if not allow_skip:
            return
        response = response.strip().casefold()
        if response in {"s", "skip"}:
            _skip_test_by_operator(instruction)
        if not response:
            return
        _print_manual_notice("Invalid response. Press Enter when ready, or type s to skip.")


@allure.step("Confirm destructive action: {action}")
def confirm_destructive_action(action: str, confirmation_phrase: str) -> bool:
    prompt = (
        f"{action}\n\n"
        "This action changes persistent device state. To authorize it, reply with "
        f"exactly: {confirmation_phrase}\n"
        "Any other response cancels the action; no change will be made."
    )

    if _telegram_mode():
        try:
            response = telegram_text(prompt, _telegram_timeout())
        except TimeoutError:
            _attach_manual_feedback(action, "NOT RECORDED (Telegram consent timeout)")
            pytest.fail(
                "Operator did not explicitly authorize the destructive action "
                "before timeout."
            )
    else:
        _print_manual_prompt("DESTRUCTIVE ACTION CONSENT", prompt, FAIL_COLOR)
        try:
            response = input(
                _input_prompt(
                    f"Type exactly {confirmation_phrase!r} to authorize:",
                    FAIL_COLOR,
                )
            )
        except EOFError:
            _attach_manual_feedback(action, "NOT RECORDED (no consent input)")
            pytest.fail(
                "Manual input is unavailable; run pytest with -s in a terminal."
            )

    authorized = response.strip() == confirmation_phrase
    result = "CONSENT GIVEN" if authorized else "DECLINED; NO ACTION PERFORMED"
    _attach_manual_feedback(action, result)
    LOGGER.info("MANUAL CONSENT | %s", result)
    return authorized


@allure.step("Record measured reference distance: {label}")
def enter_reference_distance(label: str) -> float:
    """Collect and record the operator-measured target distance in centimeters."""
    while True:
        if _telegram_mode():
            try:
                response = telegram_text(
                    "📏 DISTANCE / SONAR\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                    f"📐 Enter the ruler-measured distance for {label} "
                    "in centimeters.",
                    _telegram_timeout(),
                )
            except TimeoutError:
                _attach_manual_feedback(label, "NOT RECORDED (Telegram input timeout)")
                pytest.fail("Operator did not enter a distance in Telegram before timeout.")
        else:
            try:
                response = input(_input_prompt(f"{label} (cm):", PREPARE_COLOR)).strip()
            except EOFError:
                _attach_manual_feedback(label, "NOT RECORDED (no interactive input)")
                pytest.fail(
                    "Manual input is unavailable; run pytest with -s in a terminal."
                )

        try:
            distance_cm = float(response.replace(",", "."))
        except ValueError:
            notice = "Enter a numeric distance in centimeters, for example 20 or 20.5."
            if _telegram_mode():
                telegram_notify(f"⚠️ INVALID DISTANCE\n\n{notice}")
            else:
                _print_manual_notice(notice)
            continue

        if not math.isfinite(distance_cm) or distance_cm <= 0:
            notice = "Distance must be a finite value greater than 0 cm."
            if _telegram_mode():
                telegram_notify(f"⚠️ INVALID DISTANCE\n\n{notice}")
            else:
                _print_manual_notice(notice)
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
        if _telegram_mode():
            try:
                answer = telegram_choice(
                    "📏 DISTANCE / SONAR\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                    "Measure another target position?",
                    [("yes", "➕ Measure again"), ("no", "✅ Finish")],
                    _telegram_timeout(),
                )
            except TimeoutError:
                _attach_manual_feedback(
                    "Continue the distance measurement series",
                    "NOT RECORDED (Telegram response timeout)",
                )
                pytest.fail("Operator did not respond in Telegram before timeout.")
            response = "yes" if answer == "yes" else "no"
        else:
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
                pytest.fail(
                    "Manual input is unavailable; run pytest with -s in a terminal."
                )

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

        notice = "Enter y to measure another position or n to finish."
        if _telegram_mode():
            telegram_notify(f"⚠️ INVALID RESPONSE\n\n{notice}")
        else:
            _print_manual_notice(notice)


@allure.step("Manual verification: {instruction}")
def verify_manually(
    instruction: str,
    *,
    expected_rgb: tuple[int, int, int] | None = None,
    expected_color: str | None = None,
) -> bool:
    """Ask for an observed physical result; return False (not raise) on 'n'."""
    if _telegram_mode():
        try:
            choices = [
                ("pass", "✅ PASS"),
                ("fail", "❌ FAIL"),
                ("comment", "📝 ADD NOTE"),
            ]
            prompt = _telegram_manual_check_message(
                instruction,
                expected_rgb=expected_rgb,
                expected_color=expected_color,
            )
            if expected_rgb is None:
                response = telegram_choice(prompt, choices, _telegram_timeout())
            else:
                response = telegram_choice(
                    prompt,
                    choices,
                    _telegram_timeout(),
                    expected_rgb=expected_rgb,
                    expected_color=expected_color,
                )
            comment: str | None = None
            if response == "comment":
                comment = telegram_text(
                    "📝 ADD AN OBSERVATION\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                    "Describe what you saw. Do not enter passwords, tokens, or secrets.",
                    _telegram_timeout(),
                )
                comment_prompt = _telegram_manual_check_message(
                    instruction,
                    expected_rgb=expected_rgb,
                    expected_color=expected_color,
                )
                response = telegram_choice(
                    f"{comment_prompt}\n\n"
                    f"📝 NOTE: {_redact_sensitive_comment(comment)}",
                    [("pass", "✅ PASS"), ("fail", "❌ FAIL")],
                    _telegram_timeout(),
                )
        except TimeoutError:
            _attach_manual_feedback(
                instruction, "NOT RECORDED (Telegram response timeout)"
            )
            pytest.fail("Operator did not complete the Telegram check before timeout.")

        passed = response == "pass"
        result = "PASS" if passed else "FAIL"
        _attach_manual_feedback(instruction, result, comment)
        LOGGER.info("MANUAL RESULT | %s via Telegram", result)
        return passed

    display_instruction = instruction
    heading = "👀 MANUAL CHECK"
    if expected_rgb is not None:
        marker = lamp_color_marker(expected_color)
        color_name = expected_color.upper() if expected_color else "CUSTOM COLOR"
        heading = f"{marker} LAMP COLOR CHECK — {color_name}"
        display_instruction = (
            f"Does the lit Beacon look {color_name}?\n"
            f"Reference: {_rgb_color_chip(expected_rgb)}\n"
            f"Expected RGB: {expected_rgb[0]}, {expected_rgb[1]}, {expected_rgb[2]}"
        )
    _print_manual_prompt(heading, display_instruction, CHECK_COLOR)

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
            _print_manual_result(result, display_instruction, comment)
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
