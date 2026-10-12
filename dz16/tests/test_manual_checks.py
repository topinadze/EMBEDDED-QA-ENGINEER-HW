from __future__ import annotations

import builtins

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


def test_prepare_waits_for_enter(monkeypatch: pytest.MonkeyPatch) -> None:
    _provide_responses(monkeypatch, "")

    manual_checks.prepare_manually("Watch the LED.")


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
