"""Resolve test settings from local defaults, environment, and run overrides."""

from __future__ import annotations

import os

WIFI_SSID_ENV = "HW17_WIFI_SSID"
WIFI_PASSWORD_ENV = "HW17_WIFI_PASSWORD"
WIFI_WRONG_PASSWORD_ENV = "HW17_WIFI_WRONG_PASSWORD"
WIFI_MISSING_SSID_ENV = "HW17_WIFI_MISSING_SSID"

ALT_WIFI_SSID_ENV = "TEST_WIFI_SSID"
ALT_WIFI_PASSWORD_ENV = "TEST_WIFI_PASSWORD"
ALT_WIFI_WRONG_PASSWORD_ENV = "TEST_WIFI_WRONG_PASSWORD"
ALT_WIFI_MISSING_SSID_ENV = "TEST_WIFI_MISSING_SSID"

APP_USER_ENV = "HW17_USER"
APP_PASSWORD_ENV = "HW17_PASSWORD"
ALT_APP_USER_ENV = "TEST_USER"
ALT_APP_PASSWORD_ENV = "TEST_PASSWORD"
GUARD_PIN_ENV = "HW17_GUARD_PIN"
TELEGRAM_BOT_TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID_ENV = "TELEGRAM_CHAT_ID"

try:
    from config import secrets
except ModuleNotFoundError as error:
    if error.name not in {"config.secrets", "secrets"}:
        raise
    secrets = None

DEFAULT_WIFI_SSID = getattr(secrets, "DEFAULT_WIFI_SSID", "")
DEFAULT_WIFI_PASSWORD = getattr(secrets, "DEFAULT_WIFI_PASSWORD", "")
DEFAULT_WIFI_WRONG_PASSWORD = "WrongPassword123"
DEFAULT_WIFI_MISSING_SSID = "HW17-NONEXISTENT-NETWORK"

DEFAULT_APP_USER = getattr(secrets, "DEFAULT_APP_USER", "sentry_op")
DEFAULT_APP_PASSWORD = getattr(secrets, "DEFAULT_APP_PASSWORD", "")
DEFAULT_GUARD_PIN = getattr(secrets, "DEFAULT_GUARD_PIN", "")
DEFAULT_TELEGRAM_BOT_TOKEN = getattr(secrets, "TELEGRAM_BOT_TOKEN", "")
DEFAULT_TELEGRAM_CHAT_ID = getattr(secrets, "TELEGRAM_CHAT_ID", "")


def _configured_value(
    default: str,
    primary_env: str,
    alternate_env: str,
    override: str | None = None,
) -> str:
    if override is not None:
        return override
    return (
        os.environ.get(primary_env)
        or os.environ.get(alternate_env)
        or default
    )


def resolve_wifi_credentials(
    ssid_override: str | None = None,
    password_override: str | None = None,
) -> tuple[str, str]:
    """Resolve defaults < environment variables < per-run test overrides."""
    return (
        _configured_value(
            DEFAULT_WIFI_SSID,
            WIFI_SSID_ENV,
            ALT_WIFI_SSID_ENV,
            ssid_override,
        ),
        _configured_value(
            DEFAULT_WIFI_PASSWORD,
            WIFI_PASSWORD_ENV,
            ALT_WIFI_PASSWORD_ENV,
            password_override,
        ),
    )


def resolve_account_credentials(
    user_override: str | None = None,
    password_override: str | None = None,
) -> tuple[str, str]:
    """Resolve account username and password for SENTRY SWM-2."""
    return (
        _configured_value(
            DEFAULT_APP_USER,
            APP_USER_ENV,
            ALT_APP_USER_ENV,
            user_override,
        ),
        _configured_value(
            DEFAULT_APP_PASSWORD,
            APP_PASSWORD_ENV,
            ALT_APP_PASSWORD_ENV,
            password_override,
        ),
    )


def resolve_guard_pin() -> str:
    """Resolve the Guard PIN from the environment, falling back to local secrets."""
    return os.environ.get(GUARD_PIN_ENV) or DEFAULT_GUARD_PIN


def resolve_telegram_credentials() -> tuple[str, str]:
    """Resolve Telegram bot token and private-chat ID from env or local secrets."""
    return (
        os.environ.get(TELEGRAM_BOT_TOKEN_ENV) or DEFAULT_TELEGRAM_BOT_TOKEN,
        os.environ.get(TELEGRAM_CHAT_ID_ENV) or DEFAULT_TELEGRAM_CHAT_ID,
    )


WIFI_SSID, WIFI_PASSWORD = resolve_wifi_credentials()
WIFI_WRONG_PASSWORD = (
    os.environ.get(WIFI_WRONG_PASSWORD_ENV)
    or os.environ.get(ALT_WIFI_WRONG_PASSWORD_ENV)
    or DEFAULT_WIFI_WRONG_PASSWORD
)
WIFI_MISSING_SSID = (
    os.environ.get(WIFI_MISSING_SSID_ENV)
    or os.environ.get(ALT_WIFI_MISSING_SSID_ENV)
    or DEFAULT_WIFI_MISSING_SSID
)

APP_USER, APP_PASSWORD = resolve_account_credentials()
