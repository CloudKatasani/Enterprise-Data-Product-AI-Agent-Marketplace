"""M0 — the application refuses to boot with a missing environment variable."""

from __future__ import annotations

import pytest

from services.common.config import (
    REQUIRED_VARS,
    ConfigurationError,
    get_settings,
    validate_environment,
)


def _complete_environment() -> dict[str, str]:
    return {
        "PRODUCT_NAME": "Test Marketplace",
        "TENANT_ID": "TEN-TEST",
        "DATABASE_URL": "postgresql://u:p@localhost:5432/db",
        "REDIS_URL": "redis://localhost:6379/0",
        "OIDC_ISSUER": "https://issuer.invalid",
        "OIDC_CLIENT_ID": "client",
        "OIDC_CLIENT_SECRET": "secret",
        "SNOWFLAKE_ACCOUNT": "acct",
        "SNOWFLAKE_USER": "user",
        "SNOWFLAKE_ROLE": "MKT_READONLY",
        "SNOWFLAKE_PRIVATE_KEY": "",
        "AGENT_RUNTIME": "mock",
        "MODEL_PROVIDER": "anthropic",
        "MODEL_ID": "model",
        "MODEL_MAX_TOKENS": "2000",
        "DEMO_TIER_SCHEMA": "MARKETPLACE_DEMO",
        "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318",
        "FEATURE_FLAG_SOURCE": "env",
    }


@pytest.fixture()
def clean_env(monkeypatch):
    for name in REQUIRED_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("services.common.config.load_dotenv", lambda path=None: None)
    return monkeypatch


def test_complete_environment_boots(clean_env) -> None:
    for key, value in _complete_environment().items():
        clean_env.setenv(key, value)

    settings = get_settings()

    assert settings.product_name == "Test Marketplace"
    assert settings.model_max_tokens == int("2000")


@pytest.mark.parametrize("dropped", sorted(set(REQUIRED_VARS)))
def test_every_required_variable_is_required(clean_env, dropped: str) -> None:
    for key, value in _complete_environment().items():
        clean_env.setenv(key, value)
    clean_env.delenv(dropped, raising=False)

    with pytest.raises(ConfigurationError) as excinfo:
        validate_environment()

    assert dropped in str(excinfo.value)


def test_unknown_agent_runtime_is_rejected(clean_env) -> None:
    for key, value in _complete_environment().items():
        clean_env.setenv(key, value)
    clean_env.setenv("AGENT_RUNTIME", "whatever")

    with pytest.raises(ConfigurationError) as excinfo:
        validate_environment()

    assert "AGENT_RUNTIME" in str(excinfo.value)


def test_private_key_may_be_empty_but_must_be_present(clean_env) -> None:
    for key, value in _complete_environment().items():
        clean_env.setenv(key, value)
    clean_env.setenv("SNOWFLAKE_PRIVATE_KEY", "")

    validate_environment()
