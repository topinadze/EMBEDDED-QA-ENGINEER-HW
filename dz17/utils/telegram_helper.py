from __future__ import annotations

import logging
import os
import re
import struct
import time
from collections.abc import Mapping, Sequence
from typing import Any, Protocol
import zlib

import allure
import requests

LOGGER = logging.getLogger(__name__)


class _TelegramUrlRedactionFilter(logging.Filter):
    _token_path = re.compile(r"(/bot)[^/\s\"']+(/)")

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = self._token_path.sub(r"\1[REDACTED]\2", message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


for _logger_name in (
    "urllib3.connectionpool",
    "requests.packages.urllib3.connectionpool",
    "http.client",
):
    logging.getLogger(_logger_name).addFilter(_TelegramUrlRedactionFilter())


class _ApiResponse(Protocol):
    def raise_for_status(self) -> None: ...

    def json(self) -> Any: ...


class _ApiSession(Protocol):
    def post(
        self,
        url: str,
        *,
        json: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        files: Mapping[str, tuple[str, bytes, str]] | None = None,
        timeout: float,
    ) -> _ApiResponse: ...


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    content = kind + data
    return struct.pack(">I", len(data)) + content + struct.pack(">I", zlib.crc32(content))


def _rgb_swatch_png(rgb: tuple[int, int, int]) -> bytes:
    if (
        len(rgb) != 3
        or any(not isinstance(channel, int) or isinstance(channel, bool) for channel in rgb)
        or any(channel < 0 or channel > 255 for channel in rgb)
    ):
        raise ValueError("RGB color must contain three integer channels from 0 to 255.")

    width, height = 160, 96
    row = b"\x00" + bytes(rgb) * width
    pixels = row * height
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(pixels))
        + _png_chunk(b"IEND", b"")
    )


class TelegramInteraction:
    """Synchronous, allow-listed Telegram Bot API client for manual checks."""

    def __init__(
        self,
        token: str,
        chat_id: int,
        timeout: int = 300,
        session: _ApiSession | None = None,
    ) -> None:
        if not token.strip():
            raise ValueError("TELEGRAM_BOT_TOKEN must not be empty.")
        if chat_id <= 0:
            raise ValueError("TELEGRAM_CHAT_ID must be a positive private-chat ID.")
        if timeout <= 0:
            raise ValueError("TELEGRAM_TIMEOUT must be a positive number of seconds.")

        self._base_url = f"https://api.telegram.org/bot{token}"
        self._token = token
        self._chat_id = chat_id
        self._timeout = timeout
        self._session = session or requests.Session()
        self._offset = 0

    @classmethod
    def from_environment(cls) -> TelegramInteraction:
        from config.test_config import resolve_telegram_credentials

        token, raw_chat_id = resolve_telegram_credentials()
        raw_timeout = os.environ.get("TELEGRAM_TIMEOUT", "300")

        if not token:
            raise ValueError(
                "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in "
                "config/secrets.py or the local environment."
            )
        try:
            chat_id = int(raw_chat_id)
        except ValueError as error:
            raise ValueError(
                "Set TELEGRAM_CHAT_ID to your numeric private-chat ID."
            ) from error
        try:
            timeout = int(raw_timeout)
        except ValueError as error:
            raise ValueError("TELEGRAM_TIMEOUT must be an integer.") from error
        return cls(token, chat_id, timeout)

    def send_message(
        self, text: str, buttons: Sequence[Sequence[Mapping[str, str]]] | None = None
    ) -> int:
        payload: dict[str, Any] = {"chat_id": self._chat_id, "text": text}
        if buttons is not None:
            payload["reply_markup"] = {"inline_keyboard": buttons}
        result = self._api("sendMessage", payload)
        if not isinstance(result, dict):
            raise RuntimeError("Telegram sendMessage returned an invalid result.")
        message_id = result.get("message_id")
        if not isinstance(message_id, int):
            raise RuntimeError("Telegram sendMessage returned no message ID.")
        return message_id

    def send_color_swatch(self, rgb: tuple[int, int, int], caption: str) -> int:
        image = _rgb_swatch_png(rgb)
        result = self._api(
            "sendPhoto",
            {"chat_id": self._chat_id, "caption": caption},
            files={"photo": ("expected-lamp-color.png", image, "image/png")},
        )
        if not isinstance(result, dict):
            raise RuntimeError("Telegram sendPhoto returned an invalid result.")
        message_id = result.get("message_id")
        if not isinstance(message_id, int):
            raise RuntimeError("Telegram sendPhoto returned no message ID.")
        allure.attach(
            image,
            name=f"Expected lamp color sample RGB {rgb}",
            attachment_type=allure.attachment_type.PNG,
        )
        return message_id

    def wait_for_choice(
        self, message_id: int, choices: set[str], timeout: int | None = None
    ) -> str:
        deadline = time.monotonic() + (timeout or self._timeout)
        while time.monotonic() < deadline:
            remaining = max(1, int(deadline - time.monotonic()))
            updates = self._get_updates(remaining)
            for update in updates:
                update_id = update.get("update_id")
                if isinstance(update_id, int):
                    self._offset = max(self._offset, update_id + 1)
                callback = update.get("callback_query")
                if not isinstance(callback, dict):
                    continue
                if not self._authorized_callback(callback, message_id):
                    continue
                callback_id = callback.get("id")
                self._answer_callback(callback_id)
                value = callback.get("data")
                if isinstance(value, str) and value in choices:
                    response_labels = {
                        "yes": "✅ YES",
                        "no": "↪️ FINISH",
                        "pass": "✅ PASS",
                        "fail": "❌ FAIL",
                        "ready": "✅ READY",
                    }
                    self._edit_message(
                        message_id,
                        f"{callback.get('message', {}).get('text', '')}\n\n"
                        f"🗳️ OPERATOR RESPONSE\n"
                        f"{response_labels.get(value, value)}",
                    )
                    return value
        raise TimeoutError("No authorized Telegram button response before timeout.")

    def wait_for_text(
        self,
        message_id: int,
        timeout: int | None = None,
        sent_after: int | None = None,
    ) -> str:
        deadline = time.monotonic() + (timeout or self._timeout)
        while time.monotonic() < deadline:
            remaining = max(1, int(deadline - time.monotonic()))
            updates = self._get_updates(remaining, allowed_updates=["message"])
            for update in updates:
                self._offset = max(self._offset, int(update["update_id"]) + 1)
                message = update.get("message")
                if not isinstance(message, dict) or not self._authorized_message(message):
                    continue
                text = message.get("text")
                if not isinstance(text, str):
                    continue
                response_message_id = message.get("message_id")
                if (
                    not isinstance(response_message_id, int)
                    or isinstance(response_message_id, bool)
                    or response_message_id <= message_id
                ):
                    continue
                reply = message.get("reply_to_message")
                if isinstance(reply, dict):
                    if reply.get("message_id") != message_id:
                        continue
                elif sent_after is not None:
                    message_date = message.get("date")
                    if not isinstance(message_date, int) or message_date < sent_after:
                        continue
                return text.strip()
        raise TimeoutError("No authorized Telegram text reply before timeout.")

    def edit_message(self, message_id: int, text: str) -> None:
        self._edit_message(message_id, text)

    def notify(self, text: str) -> None:
        self.send_message(text)

    def _get_updates(
        self, timeout: int, allowed_updates: list[str] | None = None
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "offset": self._offset,
            "timeout": min(5, timeout),
            "allowed_updates": allowed_updates or ["callback_query", "message"],
        }
        result = self._api(
            "getUpdates",
            payload,
            request_timeout=min(10, max(7, timeout + 2)),
        )
        updates = result
        if not isinstance(updates, list):
            raise RuntimeError("Telegram getUpdates returned an invalid result.")
        return [update for update in updates if isinstance(update, dict)]

    def _authorized_callback(self, callback: Mapping[str, Any], message_id: int) -> bool:
        message = callback.get("message")
        sender = callback.get("from")
        chat = message.get("chat") if isinstance(message, dict) else None
        return (
            isinstance(message, dict)
            and isinstance(sender, dict)
            and isinstance(chat, dict)
            and message.get("message_id") == message_id
            and chat.get("id") == self._chat_id
            and sender.get("id") == self._chat_id
        )

    def _authorized_message(self, message: Mapping[str, Any]) -> bool:
        sender = message.get("from")
        chat = message.get("chat")
        return (
            isinstance(sender, dict)
            and isinstance(chat, dict)
            and sender.get("id") == self._chat_id
            and chat.get("id") == self._chat_id
        )

    def _answer_callback(self, callback_id: object) -> None:
        if isinstance(callback_id, str) and callback_id:
            try:
                self._api("answerCallbackQuery", {"callback_query_id": callback_id})
            except RuntimeError as error:
                error_text = str(error)
                expired_callback = (
                    "HTTP 400 (answerCallbackQuery)" in error_text
                    and (
                        "query is too old" in error_text
                        or "query ID is invalid" in error_text
                    )
                )
                if not expired_callback:
                    raise
                LOGGER.debug(
                    "Telegram callback acknowledgement expired before it could be answered."
                )

    def _edit_message(self, message_id: int, text: str) -> None:
        self._api(
            "editMessageText",
            {"chat_id": self._chat_id, "message_id": message_id, "text": text},
        )

    def _api(
        self,
        method: str,
        payload: Mapping[str, Any],
        request_timeout: int = 10,
        files: Mapping[str, tuple[str, bytes, str]] | None = None,
    ) -> Any:
        try:
            request: dict[str, Any] = {"timeout": request_timeout}
            if files is None:
                request["json"] = payload
            else:
                request["data"] = payload
                request["files"] = files
            response = self._session.post(f"{self._base_url}/{method}", **request)
            response.raise_for_status()
            body = response.json()
        except requests.HTTPError as error:
            status_code = (
                error.response.status_code if error.response is not None else "unknown"
            )
            description = ""
            if error.response is not None:
                try:
                    body = error.response.json()
                except ValueError:
                    body = None
                if isinstance(body, dict) and isinstance(body.get("description"), str):
                    safe_description = body["description"].replace(
                        self._token, "[REDACTED]"
                    )
                    description = f": {safe_description}"
            raise RuntimeError(
                f"Telegram API returned HTTP {status_code} ({method}){description}."
            ) from None
        except requests.RequestException:
            raise RuntimeError(f"Telegram API request failed ({method}).") from None
        except ValueError:
            raise RuntimeError(f"Telegram API returned invalid JSON ({method}).") from None

        if not isinstance(body, dict) or body.get("ok") is not True:
            raise RuntimeError(f"Telegram API rejected the request ({method}).")
        return body.get("result")


_CLIENT: TelegramInteraction | None = None


_LAMP_COLOR_MARKERS = {
    "white": "⚪",
    "red": "🔴",
    "green": "🟢",
    "blue": "🔵",
    "yellow": "🟡",
    "purple": "🟣",
    "cyan": "🔷",
    "orange": "🟠",
}


def lamp_color_marker(color_name: str | None) -> str:
    if color_name is None:
        return "🎨"
    return _LAMP_COLOR_MARKERS.get(color_name.casefold(), "🎨")


def telegram_client() -> TelegramInteraction:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = TelegramInteraction.from_environment()
    return _CLIENT


def telegram_notify(message: str) -> None:
    telegram_client().notify(message)


@allure.step("Wait for operator response in Telegram")
def telegram_choice(
    instruction: str,
    choices: Sequence[tuple[str, str]],
    timeout: int,
    *,
    expected_rgb: tuple[int, int, int] | None = None,
    expected_color: str | None = None,
) -> str:
    client = telegram_client()
    keyboard = [
        [{"text": label, "callback_data": key} for key, label in choices]
    ]
    if expected_rgb is not None:
        color_name = expected_color.upper() if expected_color else "CUSTOM COLOR"
        marker = lamp_color_marker(expected_color)
        client.send_color_swatch(
            expected_rgb,
            f"{marker} REFERENCE COLOR — {color_name}\n"
            f"🎨 RGB {expected_rgb[0]}, {expected_rgb[1]}, {expected_rgb[2]}\n"
            "👀 Compare with the lit Beacon.",
        )
    message_id = client.send_message(instruction, keyboard)
    try:
        return client.wait_for_choice(
            message_id, {key for key, _ in choices}, timeout=timeout
        )
    except TimeoutError:
        client.edit_message(
            message_id,
            f"{instruction}\n\n⌛ NO RESPONSE\nTimed out after {timeout}s.",
        )
        raise


@allure.step("Request operator text in Telegram")
def telegram_text(prompt: str, timeout: int) -> str:
    client = telegram_client()
    prompt_time = int(time.time())
    message_id = client.send_message(
        f"{prompt}\n\n"
        "📝 Reply to this prompt or send your answer as a new message."
    )
    return client.wait_for_text(
        message_id, timeout=timeout, sent_after=prompt_time
    )
