from __future__ import annotations

from config import test_config


def test_account_credentials_use_local_secrets_defaults(monkeypatch) -> None:
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


def test_environment_account_credentials_override_local_defaults(monkeypatch) -> None:
    monkeypatch.setattr(test_config, "DEFAULT_APP_USER", "local_operator")
    monkeypatch.setattr(test_config, "DEFAULT_APP_PASSWORD", "local_password")
    monkeypatch.setenv("HW17_USER", "environment_operator")
    monkeypatch.setenv("HW17_PASSWORD", "environment_password")

    assert test_config.resolve_account_credentials() == (
        "environment_operator",
        "environment_password",
    )


def test_explicit_account_credentials_override_environment(monkeypatch) -> None:
    monkeypatch.setenv("HW17_USER", "environment_operator")
    monkeypatch.setenv("HW17_PASSWORD", "environment_password")

    assert test_config.resolve_account_credentials(
        user_override="run_operator",
        password_override="run_password",
    ) == ("run_operator", "run_password")
