from __future__ import annotations

from unittest.mock import Mock

import pytest

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
