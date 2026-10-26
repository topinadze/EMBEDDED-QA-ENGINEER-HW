from __future__ import annotations

import builtins
import io
import re
import pytest
import manual_checks


def _provide_responses(monkeypatch: pytest.MonkeyPatch, *responses: str) -> None:
    answers = iter(responses)

    def fake_input(prompt: str) -> str:
        _ = prompt
        return next(answers)

    monkeypatch.setattr(builtins, "input", fake_input)


def test_manual_check_records_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    _provide_responses(monkeypatch, "y")
    assert manual_checks.verify_manually("LED shows red.") is True


def test_manual_check_records_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    _provide_responses(monkeypatch, "n")
    assert manual_checks.verify_manually("LED shows red.") is False


def test_destructive_action_requires_exact_console_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _provide_responses(monkeypatch, "ERASE NVS ON COM4")

    assert manual_checks.confirm_destructive_action(
        "Erase NVS on COM4.", "ERASE NVS ON COM4"
    )


def test_destructive_action_rejects_nonmatching_console_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _provide_responses(monkeypatch, "y")

    assert not manual_checks.confirm_destructive_action(
        "Erase NVS on COM4.", "ERASE NVS ON COM4"
    )


def test_destructive_action_requires_exact_telegram_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts: list[tuple[str, int]] = []

    def reply(prompt: str, timeout: int) -> str:
        prompts.append((prompt, timeout))
        return "ERASE NVS ON COM4"

    monkeypatch.setenv("INTERACTION_MODE", "telegram")
    monkeypatch.setenv("TELEGRAM_TIMEOUT", "25")
    monkeypatch.setattr(manual_checks, "telegram_text", reply)

    assert manual_checks.confirm_destructive_action(
        "Erase NVS on COM4.", "ERASE NVS ON COM4"
    )
    assert prompts == [
        (
            "Erase NVS on COM4.\n\n"
            "This action changes persistent device state. To authorize it, reply with "
            "exactly: ERASE NVS ON COM4\n"
            "Any other response cancels the action; no change will be made.",
            25,
        )
    ]


def test_manual_prepare_routes_to_telegram(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, list[tuple[str, str]], int]] = []

    def choose(instruction: str, choices: list[tuple[str, str]], timeout: int) -> str:
        calls.append((instruction, choices, timeout))
        return "ready"

    monkeypatch.setenv("INTERACTION_MODE", "telegram")
    monkeypatch.setenv("TELEGRAM_TIMEOUT", "25")
    monkeypatch.setattr(manual_checks, "telegram_choice", choose)

    manual_checks.prepare_manually("What to do: Watch the LED.")

    assert calls == [
        (
            "💡 STATUS INDICATOR\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🧰 GET READY\n\n"
            "➡️ ACTION: Watch the LED.\n\n"
            "Confirm with ✅ READY when prepared.",
            [("ready", "✅ READY")],
            25,
        )
    ]


def test_manual_check_routes_pass_and_comment_to_telegram(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    choices = iter(["comment", "pass"])
    prompts: list[str] = []
    texts: list[str] = []

    def choose(
        instruction: str, buttons: list[tuple[str, str]], timeout: int
    ) -> str:
        prompts.append(instruction)
        return next(choices)

    monkeypatch.setenv("INTERACTION_MODE", "telegram")
    monkeypatch.setattr(manual_checks, "telegram_choice", choose)
    monkeypatch.setattr(
        manual_checks,
        "telegram_text",
        lambda prompt, timeout: texts.append(prompt) or "Observed green.",
    )

    assert manual_checks.verify_manually("The status LED is green.") is True
    assert texts == [
        "📝 ADD AN OBSERVATION\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Describe what you saw. Do not enter passwords, tokens, or secrets."
    ]
    assert "💡 STATUS INDICATOR 🟢" in prompts[0]
    assert "📝 NOTE: Observed green." in prompts[1]


def test_manual_check_sends_expected_rgb_to_telegram(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[
        tuple[
            str,
            list[tuple[str, str]],
            int,
            tuple[int, int, int] | None,
            str | None,
        ]
    ] = []

    def choose(
        instruction: str,
        buttons: list[tuple[str, str]],
        timeout: int,
        *,
        expected_rgb: tuple[int, int, int] | None = None,
        expected_color: str | None = None,
    ) -> str:
        calls.append((instruction, buttons, timeout, expected_rgb, expected_color))
        return "pass"

    monkeypatch.setenv("INTERACTION_MODE", "telegram")
    monkeypatch.setattr(manual_checks, "telegram_choice", choose)

    assert manual_checks.verify_manually(
        "Does the lamp match yellow?",
        expected_rgb=(255, 180, 0),
        expected_color="yellow",
    )
    assert calls == [
        (
            "🟡 LAMP COLOR CHECK — YELLOW\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "👀 OBSERVE\n"
            "Does the lit Beacon look YELLOW?\n"
            "🎨 Expected RGB: 255, 180, 0\n\n"
            "Choose the result that matches what you saw.",
            [
                ("pass", "✅ PASS"),
                ("fail", "❌ FAIL"),
                ("comment", "📝 ADD NOTE"),
            ],
            300,
            (255, 180, 0),
            "yellow",
        )
    ]
    assert "🟡 LAMP COLOR CHECK — YELLOW" in calls[0][0]
    assert "Expected RGB: 255, 180, 0" in calls[0][0]


@pytest.mark.parametrize(
    ("instruction", "expected_topic"),
    [
        ("Press button K2 once and listen for the relay.", "🔘 BUTTONS"),
        ("Observe the relay switch OPEN.", "🔌 RELAY"),
        ("Observe Wi-Fi reconnect and status LED.", "📶 WI-FI"),
        ("Move the target to 20 cm from the sonar.", "📏 DISTANCE / SONAR"),
        ("Hold K4 to trigger Guard panic alarm.", "🚨 GUARD / ALARM"),
        ("Review and permanently clear the entire alert history.", "⚠️ ALERT HISTORY CLEANUP"),
        ("Did the Beacon lamp turn orange?", "💡 LAMP / BEACON"),
    ],
)
def test_telegram_manual_prompt_identifies_test_category(
    instruction: str, expected_topic: str
) -> None:
    prompt = manual_checks._telegram_manual_check_message(instruction)

    assert expected_topic in prompt
    assert "👀 OBSERVE" in prompt
    assert "Choose the result that matches what you saw." in prompt


def test_telegram_preparation_keeps_action_observation_and_duration() -> None:
    message = manual_checks._telegram_prepare_message(
        "What to do: Press K1 once.\n"
        "What to observe: The Beacon turns blue.\n"
        "Duration: ~5 seconds."
    )

    assert "🔘 BUTTONS" in message
    assert "➡️ ACTION: Press K1 once." in message
    assert "👀 OBSERVE: The Beacon turns blue." in message
    assert "⏱ DURATION: ~5 seconds." in message
    assert message.endswith("Confirm with ✅ READY when prepared.")


def test_manual_distance_routes_text_to_telegram(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INTERACTION_MODE", "telegram")
    monkeypatch.setattr(manual_checks, "telegram_text", lambda prompt, timeout: "20,5")

    assert manual_checks.enter_reference_distance("Measured target") == 20.5


def test_manual_continue_routes_choice_to_telegram(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INTERACTION_MODE", "telegram")
    monkeypatch.setattr(
        manual_checks,
        "telegram_choice",
        lambda instruction, choices, timeout: "no",
    )

    assert manual_checks.ask_to_continue_measurements() is False


def test_manual_check_records_comment_then_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _provide_responses(monkeypatch, "c", "Observed color was cyan.", "n")
    assert manual_checks.verify_manually("LED shows blue.") is False


def test_manual_check_redacts_secret_like_comment(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _provide_responses(
        monkeypatch,
        "c",
        "Password is hunter2; token=abc123 API_KEY 'secret-value'",
        "y",
    )

    assert manual_checks.verify_manually("Physical observation recorded.") is True

    assert "hunter2" not in caplog.text
    assert "abc123" not in caplog.text
    assert "secret-value" not in caplog.text
    assert "[REDACTED]" in caplog.text
    output = capsys.readouterr().out
    assert "hunter2" not in output
    assert "abc123" not in output
    assert "secret-value" not in output
    assert "[REDACTED]" in output


def test_prepare_waits_for_enter_and_displays_clear_phase(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    _provide_responses(monkeypatch, "")
    manual_checks.prepare_manually("Watch the LED.")

    output = capsys.readouterr().out
    assert output.startswith("\n")
    assert "=" * 70 in output
    assert "+" not in output
    assert "|" not in output
    assert "🧰 GET READY" in output
    assert "  Watch the LED." in output
    assert "\033[" not in output
    assert "MANUAL PREPARE | Waiting for operator confirmation." in caplog.text
    assert "MANUAL PREPARE | Watch the LED." not in caplog.text


def test_prepare_uses_color_on_interactive_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TTYOutput(io.StringIO):
        def isatty(self) -> bool:
            return True

    output = TTYOutput()
    monkeypatch.setattr(manual_checks.sys, "stdout", output)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("TERM", raising=False)
    _provide_responses(monkeypatch, "")

    manual_checks.prepare_manually(
        "What to do: Inspect the Blue lamp.\n"
        "What to observe: RGB (0, 128, 255), not invalid RGB (300, 0, 0).\n"
        "Duration: 5 seconds."
    )

    prompt = output.getvalue()
    assert "\033[1;36m" + "=" * 70 + "\033[0m" in prompt
    assert "+-" not in prompt
    assert "🧰 GET READY" in prompt
    assert "\033[94m●\033[0m Blue lamp" in prompt
    assert "\033[1;38;2;0;128;255m●\033[0m RGB (0, 128, 255)" in prompt
    assert "\033[1;36m👀 OBSERVE:\033[0m" in prompt
    assert "\033[1;36m➡️ ACTION:\033[0m" in prompt
    assert "\033[1;36m⏱ DURATION:\033[0m" in prompt
    assert "invalid RGB (300, 0, 0)" in prompt
    assert "\033[38;2;300;0;0m" not in prompt


def test_manual_check_displays_separate_phase(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _provide_responses(monkeypatch, "y")

    assert manual_checks.verify_manually("LED shows red.") is True

    output = capsys.readouterr().out
    assert output.startswith("\n")
    assert "=" * 70 in output
    assert "+" not in output
    assert "|" not in output
    assert "MANUAL CHECK" in output
    assert "  LED shows red." in output
    assert "MANUAL RESULT - PASS" in output
    assert "Manual check recorded: PASS" not in output
    assert "\033[" not in output


def test_manual_check_highlights_failure_result_and_invalid_response(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _provide_responses(monkeypatch, "invalid", "n")

    assert manual_checks.verify_manually("Relay opens.") is False

    output = capsys.readouterr().out
    assert "Invalid response. Enter y, n, or c." in output
    assert "MANUAL RESULT - FAIL" in output
    assert "Relay opens." in output


def test_manual_check_colorizes_input_and_result_notifications(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TTYOutput(io.StringIO):
        def isatty(self) -> bool:
            return True

    output = TTYOutput()
    prompts: list[str] = []
    monkeypatch.setattr(manual_checks.sys, "stdout", output)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("TERM", raising=False)

    def fake_input(prompt: str) -> str:
        prompts.append(prompt)
        return "y"

    monkeypatch.setattr(builtins, "input", fake_input)
    assert manual_checks.verify_manually("Relay opens.") is True

    assert "\033[1;33m>>\033[0m" in prompts[0]
    assert "\033[1;33mObserved result?" in prompts[0]
    monkeypatch.setattr(manual_checks.sys, "stdout", output)
    manual_checks._print_manual_result("PASS", "Relay opens.")
    assert "\033[1;32mMANUAL RESULT - PASS\033[0m" in output.getvalue()
    assert "MANUAL RESULT - PASS" in output.getvalue()


def test_manual_lamp_check_shows_rgb_color_sample_in_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TTYOutput(io.StringIO):
        def isatty(self) -> bool:
            return True

    output = TTYOutput()
    monkeypatch.setattr(manual_checks.sys, "stdout", output)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("TERM", raising=False)
    _provide_responses(monkeypatch, "y")

    assert manual_checks.verify_manually(
        "Long legacy prompt should not be shown.",
        expected_rgb=(255, 80, 0),
        expected_color="orange",
    )

    rendered = output.getvalue()
    plain_text = re.sub(r"\033\[[0-9;]*m", "", rendered)
    assert "🟠 LAMP COLOR CHECK — ORANGE" in plain_text
    assert "Does the lit Beacon look" in plain_text
    assert "ORANGE?" in plain_text
    assert "[sample]" in plain_text
    assert "\033[48;2;255;80;0m  \033[0m" in rendered
    assert "Expected RGB: 255, 80, 0" in plain_text
    assert "Long legacy prompt should not be shown." not in plain_text


def test_manual_lamp_check_remains_clear_without_terminal_color(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    _provide_responses(monkeypatch, "y")

    assert manual_checks.verify_manually(
        "Long legacy prompt should not be shown.",
        expected_rgb=(255, 80, 0),
        expected_color="orange",
    )

    rendered = capsys.readouterr().out
    assert "🟠 LAMP COLOR CHECK — ORANGE" in rendered
    assert "[RGB sample]" in rendered
    assert "Expected RGB: 255, 80, 0" in rendered
    assert "\033[" not in rendered
    assert "Long legacy prompt should not be shown." not in rendered


def test_prepare_observation_formats_action_expectation_and_duration() -> None:
    prompts: list[str] = []
    manual_checks.prepare_observation(
        prompts.append,
        action="press K1 once",
        expected="the Beacon lamp turns on",
        duration="5 seconds",
    )
    assert prompts == [
        "What to do: 👆 🔐 LOGIN VERIFIED — press K1 once\n\n"
        "What to observe: the Beacon lamp turns on\n\n"
        "Duration: 5 seconds."
    ]


def test_prepare_observation_does_not_add_button_icon_to_non_button_action() -> None:
    prompts: list[str] = []
    manual_checks.prepare_observation(
        prompts.append,
        action="Watch the status LED",
        expected="The LED stays orange",
        duration="5 seconds",
    )

    assert prompts == [
        "What to do: Watch the status LED\n\n"
        "What to observe: The LED stays orange\n\n"
        "Duration: 5 seconds."
    ]


@pytest.mark.parametrize(
    ("action", "expected_status"),
    [
        ("Press button K1 once", "🔐 LOGIN VERIFIED"),
        ("This test logs out, then asks you to press K1", "🔐 LOGGED IN AT START"),
        ("Press button K1 once while logged out", "🔓 LOGGED OUT"),
    ],
)
def test_button_action_shows_required_session_in_telegram_preparation_message(
    action: str, expected_status: str
) -> None:
    prompts: list[str] = []
    manual_checks.prepare_observation(
        prompts.append,
        action=action,
        expected="The Beacon lamp turns on",
        duration="5 seconds",
    )

    message = manual_checks._telegram_prepare_message(prompts[0])

    assert "🔘 BUTTONS" in message
    assert f"➡️ ACTION: 👆 {expected_status} — {action}" in message


@pytest.mark.parametrize(
    ("is_connected", "is_logged_in", "expected"),
    [
        (True, True, "green"),
        (True, False, "orange"),
        (False, True, "red"),
        (False, False, "red"),
    ],
)
def test_status_indicator_color(is_connected: bool, is_logged_in: bool, expected: str) -> None:
    assert manual_checks.status_indicator_color(is_connected, is_logged_in) == expected


@pytest.mark.parametrize(
    ("is_connected", "is_logged_in", "expected"),
    [
        (True, True, "GREEN (Wi-Fi connected and logged in)"),
        (True, False, "ORANGE (Wi-Fi connected, logged out)"),
        (False, True, "RED (Wi-Fi disconnected)"),
        (False, False, "RED (Wi-Fi disconnected)"),
    ],
)
def test_status_indicator_description(
    is_connected: bool, is_logged_in: bool, expected: str
) -> None:
    assert (
        manual_checks.status_indicator_description(is_connected, is_logged_in)
        == expected
    )


def test_soft_checks_collect_all_failures() -> None:
    soft = manual_checks.SoftChecks()
    soft.check(False, "first failure")
    soft.check(True, "passing check")
    soft.check(False, "second failure")

    with pytest.raises(pytest.fail.Exception, match=r"(?s)2 check.*first.*second"):
        soft.assert_all()


def test_soft_checks_report_manual_check_as_not_run_without_failing() -> None:
    soft = manual_checks.SoftChecks()

    assert soft.check(None, "Beacon visibly shows blue") is None
    soft.assert_all()


def test_manual_check_rejects_unavailable_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_input(prompt: str) -> str:
        _ = prompt
        raise EOFError

    monkeypatch.setattr(builtins, "input", no_input)
    with pytest.raises(pytest.fail.Exception, match="run pytest with -s"):
        manual_checks.verify_manually("LED shows red.")


def test_manual_distance_accepts_decimal_comma(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _provide_responses(monkeypatch, "20,5")

    assert manual_checks.enter_reference_distance("Measured target distance") == 20.5
    assert "MANUAL INPUT | Measured target distance: 20.50 cm" in caplog.text


def test_manual_distance_retries_invalid_values(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _provide_responses(monkeypatch, "about 20", "nan", "0", "-1", "20.5")

    assert manual_checks.enter_reference_distance("Measured target distance") == 20.5

    output = capsys.readouterr().out
    assert output.count("MANUAL INPUT NEEDED") == 4
    assert "Enter a numeric distance in centimeters" in output
    assert "Distance must be a finite value greater than 0 cm." in output


def test_manual_distance_rejects_unavailable_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_input(prompt: str) -> str:
        _ = prompt
        raise EOFError

    monkeypatch.setattr(builtins, "input", no_input)
    with pytest.raises(pytest.fail.Exception, match="run pytest with -s"):
        manual_checks.enter_reference_distance("Measured target distance")


@pytest.mark.parametrize(
    ("response", "expected"),
    [("y", True), ("yes", True), ("n", False), ("no", False)],
)
def test_manual_continue_records_yes_or_no(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    response: str,
    expected: bool,
) -> None:
    _provide_responses(monkeypatch, response)

    assert manual_checks.ask_to_continue_measurements() is expected
    assert f"Continue distance measurements: {'yes' if expected else 'no'}" in caplog.text


def test_manual_continue_retries_invalid_response(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _provide_responses(monkeypatch, "maybe", "y")

    assert manual_checks.ask_to_continue_measurements() is True
    assert (
        "Enter y to measure another position or n to finish."
        in capsys.readouterr().out
    )


def test_manual_continue_rejects_unavailable_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_input(prompt: str) -> str:
        _ = prompt
        raise EOFError

    monkeypatch.setattr(builtins, "input", no_input)
    with pytest.raises(pytest.fail.Exception, match="run pytest with -s"):
        manual_checks.ask_to_continue_measurements()
