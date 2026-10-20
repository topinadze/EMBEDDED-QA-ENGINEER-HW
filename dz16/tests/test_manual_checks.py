from __future__ import annotations

import builtins
import io

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


def test_manual_check_records_comment_then_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _provide_responses(monkeypatch, "c", "LED looked purple.", "n")

    assert manual_checks.verify_manually("LED shows red.") is False


def test_prepare_waits_for_enter_and_displays_clear_phase(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    _provide_responses(monkeypatch, "")

    manual_checks.prepare_manually("Watch the LED.")

    output = capsys.readouterr().out
    assert output.startswith("\n")
    assert "GET READY - MANUAL PREPARE\n\nWatch the LED." in output
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
        "Inspect the Blue lamp, RGB (0, 128, 255), and invalid RGB (300, 0, 0)."
    )

    prompt = output.getvalue()
    assert "\033[1;36mGET READY - MANUAL PREPARE\033[0m" in prompt
    assert "\033[94m●\033[0m Blue lamp" in prompt
    assert "\033[1;38;2;0;128;255m●\033[0m RGB (0, 128, 255)" in prompt
    assert "invalid RGB (300, 0, 0)" in prompt
    assert "\033[38;2;300;0;0m" not in prompt


def test_manual_check_displays_separate_phase(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _provide_responses(monkeypatch, "y")

    assert manual_checks.verify_manually("LED shows red.") is True

    output = capsys.readouterr().out
    assert output.startswith("\n")
    assert "MANUAL CHECK\n\nLED shows red." in output
    assert "\033[" not in output

def test_prepare_observation_formats_action_expectation_and_duration() -> None:
    prompts: list[str] = []

    manual_checks.prepare_observation(
        prompts.append,
        action="press K3 once",
        expected="the LED shows dim red",
        duration="5 seconds",
    )

    assert prompts == [
        "What to do: press K3 once\n\n"
        "What to observe: the LED shows dim red\n\n"
        "Duration: 5 seconds."
    ]


@pytest.mark.parametrize(
    ("is_connected", "expected"),
    ((True, "dim green"), (False, "dim red")),
)
def test_wifi_indicator_color_matches_connection_state(
    is_connected: bool, expected: str
) -> None:
    assert manual_checks.wifi_indicator_color(is_connected) == expected


def test_soft_checks_collect_all_failures() -> None:
    soft = manual_checks.SoftChecks()
    soft.check(False, "first")
    soft.check(True, "ok")
    soft.check(False, "second")

    with pytest.raises(pytest.fail.Exception, match=r"(?s)2 check.*first.*second"):
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
