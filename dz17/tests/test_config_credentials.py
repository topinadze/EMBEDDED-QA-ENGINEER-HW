from __future__ import annotations

import pytest

from config import test_config


def test_wifi_credentials_use_local_secrets_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(test_config, "DEFAULT_WIFI_SSID", "local_network")
    monkeypatch.setattr(test_config, "DEFAULT_WIFI_PASSWORD", "local_password")
    for name in (
        test_config.WIFI_SSID_ENV,
        test_config.WIFI_PASSWORD_ENV,
        test_config.ALT_WIFI_SSID_ENV,
        test_config.ALT_WIFI_PASSWORD_ENV,
    ):
        monkeypatch.delenv(name, raising=False)

    assert test_config.resolve_wifi_credentials() == (
        "local_network",
        "local_password",
    )


@pytest.mark.parametrize(
    ("ssid_env", "password_env"),
    [
        (test_config.WIFI_SSID_ENV, test_config.WIFI_PASSWORD_ENV),
        (test_config.ALT_WIFI_SSID_ENV, test_config.ALT_WIFI_PASSWORD_ENV),
    ],
    ids=("primary-environment", "alternate-environment"),
)
def test_wifi_environment_credentials_override_local_defaults(
    monkeypatch: pytest.MonkeyPatch,
    ssid_env: str,
    password_env: str,
) -> None:
    monkeypatch.setattr(test_config, "DEFAULT_WIFI_SSID", "local_network")
    monkeypatch.setattr(test_config, "DEFAULT_WIFI_PASSWORD", "local_password")
    for name in (
        test_config.WIFI_SSID_ENV,
        test_config.WIFI_PASSWORD_ENV,
        test_config.ALT_WIFI_SSID_ENV,
        test_config.ALT_WIFI_PASSWORD_ENV,
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(ssid_env, "environment_network")
    monkeypatch.setenv(password_env, "environment_password")

    assert test_config.resolve_wifi_credentials() == (
        "environment_network",
        "environment_password",
    )


def test_wifi_primary_environment_credentials_override_alternate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(test_config.WIFI_SSID_ENV, "primary_network")
    monkeypatch.setenv(test_config.WIFI_PASSWORD_ENV, "primary_password")
    monkeypatch.setenv(test_config.ALT_WIFI_SSID_ENV, "alternate_network")
    monkeypatch.setenv(test_config.ALT_WIFI_PASSWORD_ENV, "alternate_password")

    assert test_config.resolve_wifi_credentials() == (
        "primary_network",
        "primary_password",
    )


def test_explicit_wifi_credentials_override_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(test_config.WIFI_SSID_ENV, "environment_network")
    monkeypatch.setenv(test_config.WIFI_PASSWORD_ENV, "environment_password")

    assert test_config.resolve_wifi_credentials(
        ssid_override="run_network",
        password_override="run_password",
    ) == ("run_network", "run_password")


def test_account_credentials_use_local_secrets_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(test_config, "DEFAULT_APP_USER", "local_operator")
    monkeypatch.setattr(test_config, "DEFAULT_APP_PASSWORD", "local_password")
    monkeypatch.delenv("HW17_USER", raising=False)
    monkeypatch.delenv("HW17_PASSWORD", raising=False)
    monkeypatch.delenv("TEST_USER", raising=False)
    monkeypatch.delenv("TEST_PASSWORD", raising=False)

    assert test_config.resolve_account_credentials() == (
        "local_operator",
        "local_password",
    )


def test_telegram_credentials_use_local_secrets_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(test_config, "DEFAULT_TELEGRAM_BOT_TOKEN", "local-token")
    monkeypatch.setattr(test_config, "DEFAULT_TELEGRAM_CHAT_ID", "123456")
    monkeypatch.delenv(test_config.TELEGRAM_BOT_TOKEN_ENV, raising=False)
    monkeypatch.delenv(test_config.TELEGRAM_CHAT_ID_ENV, raising=False)

    assert test_config.resolve_telegram_credentials() == ("local-token", "123456")


def test_telegram_environment_credentials_override_local_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(test_config, "DEFAULT_TELEGRAM_BOT_TOKEN", "local-token")
    monkeypatch.setattr(test_config, "DEFAULT_TELEGRAM_CHAT_ID", "123456")
    monkeypatch.setenv(test_config.TELEGRAM_BOT_TOKEN_ENV, "environment-token")
    monkeypatch.setenv(test_config.TELEGRAM_CHAT_ID_ENV, "789012")

    assert test_config.resolve_telegram_credentials() == (
        "environment-token",
        "789012",
    )


def test_environment_account_credentials_override_local_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(test_config, "DEFAULT_APP_USER", "local_operator")
    monkeypatch.setattr(test_config, "DEFAULT_APP_PASSWORD", "local_password")
    monkeypatch.setenv("HW17_USER", "environment_operator")
    monkeypatch.setenv("HW17_PASSWORD", "environment_password")

    assert test_config.resolve_account_credentials() == (
        "environment_operator",
        "environment_password",
    )


def test_alternate_environment_account_credentials_are_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(test_config, "DEFAULT_APP_USER", "local_operator")
    monkeypatch.setattr(test_config, "DEFAULT_APP_PASSWORD", "local_password")
    monkeypatch.delenv(test_config.APP_USER_ENV, raising=False)
    monkeypatch.delenv(test_config.APP_PASSWORD_ENV, raising=False)
    monkeypatch.setenv(test_config.ALT_APP_USER_ENV, "alternate_operator")
    monkeypatch.setenv(test_config.ALT_APP_PASSWORD_ENV, "alternate_password")

    assert test_config.resolve_account_credentials() == (
        "alternate_operator",
        "alternate_password",
    )


def test_account_primary_environment_credentials_override_alternate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(test_config.APP_USER_ENV, "primary_operator")
    monkeypatch.setenv(test_config.APP_PASSWORD_ENV, "primary_password")
    monkeypatch.setenv(test_config.ALT_APP_USER_ENV, "alternate_operator")
    monkeypatch.setenv(test_config.ALT_APP_PASSWORD_ENV, "alternate_password")

    assert test_config.resolve_account_credentials() == (
        "primary_operator",
        "primary_password",
    )


def test_explicit_account_credentials_override_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HW17_USER", "environment_operator")
    monkeypatch.setenv("HW17_PASSWORD", "environment_password")

    assert test_config.resolve_account_credentials(
        user_override="run_operator",
        password_override="run_password",
    ) == ("run_operator", "run_password")


def test_guard_pin_uses_local_secrets_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(test_config, "DEFAULT_GUARD_PIN", "2468")
    monkeypatch.delenv(test_config.GUARD_PIN_ENV, raising=False)

    assert test_config.resolve_guard_pin() == "2468"


def test_environment_guard_pin_overrides_local_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(test_config, "DEFAULT_GUARD_PIN", "2468")
    monkeypatch.setenv(test_config.GUARD_PIN_ENV, "1357")

    assert test_config.resolve_guard_pin() == "1357"
