from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

from utils import telegram_helper
from utils.telegram_helper import TelegramInteraction


class _Response:
    def __init__(self, result: object) -> None:
        self._result = result

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {"ok": True, "result": self._result}


def test_telegram_choice_edits_prompt_with_styled_operator_result() -> None:
    session = Mock()
    session.post.side_effect = [
        _Response(
            [
                {
                    "update_id": 5,
                    "callback_query": {
                        "id": "callback-1",
                        "data": "fail",
                        "from": {"id": 123},
                        "message": {
                            "message_id": 42,
                            "text": "🔌 RELAY\n👀 OBSERVE\nThe relay clicked.",
                            "chat": {"id": 123},
                        },
                    },
                }
            ]
        ),
        _Response(True),
        _Response(True),
    ]
    client = TelegramInteraction("test-token", 123, session=session)

    result = client.wait_for_choice(42, {"pass", "fail"}, timeout=5)

    assert result == "fail"
    edited_payload = session.post.call_args_list[2].kwargs["json"]
    assert edited_payload["text"] == (
        "🔌 RELAY\n👀 OBSERVE\nThe relay clicked.\n\n"
        "🗳️ OPERATOR RESPONSE\n❌ FAIL"
    )


def test_telegram_choice_ignores_callbacks_for_older_prompts() -> None:
    session = Mock()
    session.post.side_effect = [
        _Response(
            [
                {
                    "update_id": 5,
                    "callback_query": {
                        "id": "old-callback",
                        "data": "ready",
                        "from": {"id": 123},
                        "message": {
                            "message_id": 41,
                            "text": "Older prompt",
                            "chat": {"id": 123},
                        },
                    },
                }
            ]
        ),
        _Response(
            [
                {
                    "update_id": 6,
                    "callback_query": {
                        "id": "current-callback",
                        "data": "ready",
                        "from": {"id": 123},
                        "message": {
                            "message_id": 42,
                            "text": "Current prompt",
                            "chat": {"id": 123},
                        },
                    },
                }
            ]
        ),
        _Response(True),
        _Response(True),
    ]
    client = TelegramInteraction("test-token", 123, session=session)

    result = client.wait_for_choice(42, {"ready"}, timeout=5)

    assert result == "ready"
    assert [
        call.args[0].rsplit("/", 1)[-1] for call in session.post.call_args_list
    ] == [
        "getUpdates",
        "getUpdates",
        "answerCallbackQuery",
        "editMessageText",
    ]
    assert session.post.call_args_list[2].kwargs["json"] == {
        "callback_query_id": "current-callback"
    }


def test_telegram_text_ignores_stale_message_from_same_second_as_prompt() -> None:
    session = Mock()
    session.post.side_effect = [
        _Response(
            [
                {
                    "update_id": 5,
                    "message": {
                        "message_id": 41,
                        "date": 1_000,
                        "text": "stale answer",
                        "from": {"id": 123},
                        "chat": {"id": 123},
                    },
                }
            ]
        ),
        _Response(
            [
                {
                    "update_id": 6,
                    "message": {
                        "message_id": 43,
                        "date": 1_000,
                        "text": "current answer",
                        "from": {"id": 123},
                        "chat": {"id": 123},
                    },
                }
            ]
        ),
    ]
    client = TelegramInteraction("test-token", 123, session=session)

    result = client.wait_for_text(42, timeout=5, sent_after=1_000)

    assert result == "current answer"
    assert [
        call.args[0].rsplit("/", 1)[-1] for call in session.post.call_args_list
    ] == ["getUpdates", "getUpdates"]


def test_telegram_expired_callback_acknowledgement_does_not_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TelegramInteraction("test-token", 123, session=Mock())
    monkeypatch.setattr(
        client,
        "_api",
        Mock(
            side_effect=RuntimeError(
                "Telegram API returned HTTP 400 (answerCallbackQuery): "
                "Bad Request: query is too old and response timeout expired."
            )
        ),
    )

    client._answer_callback("expired-callback")


def test_telegram_callback_acknowledgement_reraises_unrelated_api_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TelegramInteraction("test-token", 123, session=Mock())
    monkeypatch.setattr(
        client,
        "_api",
        Mock(
            side_effect=RuntimeError(
                "Telegram API returned HTTP 401 (answerCallbackQuery): Unauthorized."
            )
        ),
    )

    with pytest.raises(RuntimeError, match="HTTP 401"):
        client._answer_callback("callback")


def test_discard_pending_updates_confirms_queue_before_handover() -> None:
    session = Mock()
    session.post.side_effect = [
        _Response([{"update_id": 7, "message": {"text": "/run"}}]),
        _Response([]),
    ]
    client = TelegramInteraction("test-token", 123, session=session)

    client.discard_pending_updates()

    offsets = [call.kwargs["json"]["offset"] for call in session.post.call_args_list]
    assert offsets == [0, 8]


class _HttpErrorResponse:
    def __init__(self, status_code: int, body: dict[str, object]) -> None:
        self.status_code = status_code
        self._body = body

    def raise_for_status(self) -> None:
        raise requests.HTTPError(response=self)

    def json(self) -> dict[str, object]:
        return self._body


def test_telegram_api_waits_retry_after_on_rate_limit() -> None:
    session = Mock()
    session.post.side_effect = [
        _HttpErrorResponse(
            429,
            {
                "ok": False,
                "description": "Too Many Requests: retry after 5",
                "parameters": {"retry_after": 5},
            },
        ),
        _Response([]),
    ]
    delays: list[float] = []
    client = TelegramInteraction("test-token", 123, session=session, sleep=delays.append)

    assert client.poll_updates(5) == []
    assert delays == [5]


def test_telegram_api_gives_up_after_bounded_gateway_errors() -> None:
    session = Mock()
    session.post.side_effect = [
        _HttpErrorResponse(502, {"ok": False, "description": "Bad Gateway"})
    ] * 4
    delays: list[float] = []
    client = TelegramInteraction("test-token", 123, session=session, sleep=delays.append)

    with pytest.raises(RuntimeError, match=r"HTTP 502 \(editMessageText\): Bad Gateway"):
        client.edit_message(42, "hello")
    assert delays == [1, 2, 4]


def test_send_message_is_not_resent_after_gateway_error() -> None:
    # A 502 may still have delivered the prompt; resending would duplicate it.
    session = Mock()
    session.post.side_effect = [
        _HttpErrorResponse(502, {"ok": False, "description": "Bad Gateway"})
    ]
    delays: list[float] = []
    client = TelegramInteraction("test-token", 123, session=session, sleep=delays.append)

    with pytest.raises(RuntimeError, match=r"HTTP 502 \(sendMessage\)"):
        client.send_message("hello")
    assert session.post.call_count == 1
    assert delays == []


def test_send_message_is_retried_after_rate_limit() -> None:
    session = Mock()
    session.post.side_effect = [
        _HttpErrorResponse(
            429,
            {"ok": False, "description": "Too Many Requests", "parameters": {"retry_after": 3}},
        ),
        _Response({"message_id": 77}),
    ]
    delays: list[float] = []
    client = TelegramInteraction("test-token", 123, session=session, sleep=delays.append)

    assert client.send_message("hello") == 77
    assert delays == [3]


def test_telegram_api_does_not_retry_authorization_errors() -> None:
    session = Mock()
    session.post.side_effect = [
        _HttpErrorResponse(401, {"ok": False, "description": "Unauthorized"})
    ]
    delays: list[float] = []
    client = TelegramInteraction("test-token", 123, session=session, sleep=delays.append)

    with pytest.raises(RuntimeError, match="HTTP 401"):
        client.send_message("hello")
    assert delays == []


def test_lost_prompt_is_marked_inactive(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Mock()
    client.send_message.return_value = 42
    client.wait_for_choice.side_effect = RuntimeError("HTTP 502 (getUpdates)")
    monkeypatch.setattr(telegram_helper, "_CLIENT", client)

    with pytest.raises(RuntimeError, match="502"):
        telegram_helper.telegram_choice("Ready?", [("ready", "READY")], timeout=5)

    edited_text = client.edit_message.call_args.args[1]
    assert "⚠️ TELEGRAM CONNECTION LOST" in edited_text


def _stop_tap(update_id: int, sender: int = 123, message_id: int = 7) -> dict[str, object]:
    return {
        "update_id": update_id,
        "callback_query": {
            "id": f"stop-{update_id}",
            "data": telegram_helper.STOP_RUN_CALLBACK,
            "from": {"id": sender},
            "message": {"message_id": message_id, "chat": {"id": sender}},
        },
    }


def test_stop_tap_on_status_message_interrupts_a_prompt_wait() -> None:
    session = Mock()
    session.post.side_effect = [_Response([_stop_tap(9)]), _Response(True)]
    client = TelegramInteraction("test-token", 123, session=session)

    with pytest.raises(telegram_helper.RunStopRequested):
        client.wait_for_choice(42, {"ready"}, timeout=5)

    assert session.post.call_args_list[1].args[0].endswith("/answerCallbackQuery")


def test_stop_tap_interrupts_a_text_reply_wait() -> None:
    session = Mock()
    session.post.side_effect = [_Response([_stop_tap(9)]), _Response(True)]
    client = TelegramInteraction("test-token", 123, session=session)

    with pytest.raises(telegram_helper.RunStopRequested):
        client.wait_for_text(42, timeout=5)

    allowed = session.post.call_args_list[0].kwargs["json"]["allowed_updates"]
    assert "callback_query" in allowed


def test_stop_tap_from_another_chat_is_ignored() -> None:
    session = Mock()
    session.post.side_effect = [_Response([_stop_tap(9, sender=999)])]
    client = TelegramInteraction("test-token", 123, session=session)

    client.check_stop_request()


def test_check_stop_request_raises_for_pending_stop_tap() -> None:
    session = Mock()
    session.post.side_effect = [_Response([_stop_tap(9)]), _Response(True)]
    client = TelegramInteraction("test-token", 123, session=session)

    with pytest.raises(telegram_helper.RunStopRequested):
        client.check_stop_request()


def test_stop_request_is_not_swallowed_by_except_exception() -> None:
    with pytest.raises(telegram_helper.RunStopRequested):
        try:
            raise telegram_helper.RunStopRequested()
        except Exception:  # noqa: BLE001 - mirrors cleanup blocks in hardware tests
            pytest.fail("RunStopRequested must behave like Ctrl+C")


def test_choice_prompt_has_no_stop_button_but_is_marked_when_stopped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Mock()
    client.send_message.return_value = 42
    client.wait_for_choice.side_effect = telegram_helper.RunStopRequested()
    monkeypatch.setattr(telegram_helper, "_CLIENT", client)

    with pytest.raises(telegram_helper.RunStopRequested):
        telegram_helper.telegram_choice("Ready?", [("ready", "READY")], timeout=5)

    keyboard = client.send_message.call_args.args[1]
    assert keyboard == [[{"text": "READY", "callback_data": "ready"}]]
    assert "⏹ RUN STOPPED BY OPERATOR" in client.edit_message.call_args.args[1]


def test_stop_request_ends_pytest_like_ctrl_c(tmp_path: Path) -> None:
    marker = tmp_path / "teardown-ran.txt"
    (tmp_path / "test_stop.py").write_text(
        "import pytest\n"
        "from utils.telegram_helper import RunStopRequested\n"
        "\n"
        "@pytest.fixture\n"
        "def device():\n"
        "    yield\n"
        f"    open({str(marker)!r}, 'w').close()\n"
        "\n"
        "def test_first(device):\n"
        "    try:\n"
        "        raise RunStopRequested()\n"
        "    except Exception:\n"
        "        pass\n"
        "\n"
        "def test_second():\n"
        "    pass\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_stop.py"],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == pytest.ExitCode.INTERRUPTED, result.stdout
    assert marker.exists()
    assert "1 passed" not in result.stdout


def _stop_command(update_id: int, text: str = "/stop_execution", sender: int = 123) -> dict[str, object]:
    return {
        "update_id": update_id,
        "message": {
            "message_id": 100 + update_id,
            "date": 0,
            "text": text,
            "from": {"id": sender},
            "chat": {"id": sender},
        },
    }


@pytest.mark.parametrize("text", ["/stop_execution", "/stop_execution@SentryBot", "/STOP_EXECUTION now"])
def test_stop_command_interrupts_a_text_reply_wait(text: str) -> None:
    session = Mock()
    session.post.side_effect = [_Response([_stop_command(9, text)])]
    client = TelegramInteraction("test-token", 123, session=session)

    with pytest.raises(telegram_helper.RunStopRequested):
        client.wait_for_text(42, timeout=5)


def test_stop_command_from_another_chat_is_not_a_stop() -> None:
    client = TelegramInteraction("test-token", 123, session=Mock())

    assert not client.is_stop_request(_stop_command(9, sender=999))
    assert not client.is_stop_request(_stop_command(9, text="/stop"))
    assert not client.is_stop_request(_stop_command(9, text="20.5"))


def test_discard_reports_a_queued_stop_request() -> None:
    session = Mock()
    session.post.side_effect = [
        _Response([_stop_command(9), {"update_id": 10, "message": {"text": "hi"}}]),
        _Response([]),
    ]
    client = TelegramInteraction("test-token", 123, session=session)

    assert client.discard_pending_updates() is True
