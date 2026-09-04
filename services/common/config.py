"""Environment configuration.

Every variable in ``.env.example`` is required. The application refuses to boot
with a missing one — there is no permissive default (BUILD.md rule 7, fail closed).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

REQUIRED_VARS: tuple[str, ...] = (
    "PRODUCT_NAME",
    "TENANT_ID",
    "DATABASE_URL",
    "REDIS_URL",
    "OIDC_ISSUER",
    "OIDC_CLIENT_ID",
    "OIDC_CLIENT_SECRET",
    "SNOWFLAKE_ACCOUNT",
    "SNOWFLAKE_USER",
    "SNOWFLAKE_ROLE",
    "AGENT_RUNTIME",
    "MODEL_PROVIDER",
    "MODEL_ID",
    "MODEL_MAX_TOKENS",
    "DEMO_TIER_SCHEMA",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "FEATURE_FLAG_SOURCE",
    "WORKER_POLL_SECONDS",
)

# Variables that must be *present* but may legitimately be empty in a local run
# (a private key is not needed until a real connector session is opened).
MAY_BE_EMPTY: frozenset[str] = frozenset({"SNOWFLAKE_PRIVATE_KEY"})

VALID_AGENT_RUNTIMES: frozenset[str] = frozenset({"cortex", "mock"})
VALID_FLAG_SOURCES: frozenset[str] = frozenset({"env", "service"})


class ConfigurationError(RuntimeError):
    """Raised when the process environment cannot support a safe boot."""


def load_dotenv(path: Path | None = None) -> None:
    """Populate ``os.environ`` from a ``.env`` file without overriding real env vars."""
    env_path = path or REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


@dataclass(frozen=True)
class Settings:
    product_name: str
    tenant_id: str
    database_url: str
    redis_url: str
    oidc_issuer: str
    oidc_client_id: str
    oidc_client_secret: str
    snowflake_account: str
    snowflake_user: str
    snowflake_role: str
    snowflake_private_key: str
    agent_runtime: str
    model_provider: str
    model_id: str
    model_max_tokens: int
    demo_tier_schema: str
    otel_endpoint: str
    feature_flag_source: str
    worker_poll_seconds: int
    missing: tuple[str, ...] = field(default=())


def _missing_vars() -> tuple[str, ...]:
    missing = []
    for name in REQUIRED_VARS:
        value = os.environ.get(name)
        if value is None or (value.strip() == "" and name not in MAY_BE_EMPTY):
            missing.append(name)
    return tuple(missing)


def validate_environment() -> None:
    """Raise :class:`ConfigurationError` describing everything that is wrong at once."""
    load_dotenv()
    problems: list[str] = []

    missing = _missing_vars()
    if missing:
        problems.append(
            "missing required environment variables: "
            + ", ".join(missing)
            + " (copy .env.example to .env)"
        )

    runtime = os.environ.get("AGENT_RUNTIME", "")
    if runtime and runtime not in VALID_AGENT_RUNTIMES:
        problems.append(
            f"AGENT_RUNTIME={runtime!r} is not one of {sorted(VALID_AGENT_RUNTIMES)}"
        )

    flags = os.environ.get("FEATURE_FLAG_SOURCE", "")
    if flags and flags not in VALID_FLAG_SOURCES:
        problems.append(
            f"FEATURE_FLAG_SOURCE={flags!r} is not one of {sorted(VALID_FLAG_SOURCES)}"
        )

    for name in ("MODEL_MAX_TOKENS", "WORKER_POLL_SECONDS"):
        value = os.environ.get(name, "")
        if value and not value.isdigit():
            problems.append(f"{name}={value!r} is not a positive integer")

    if problems:
        raise ConfigurationError("; ".join(problems))


def get_settings() -> Settings:
    validate_environment()
    return Settings(
        product_name=os.environ["PRODUCT_NAME"],
        tenant_id=os.environ["TENANT_ID"],
        database_url=os.environ["DATABASE_URL"],
        redis_url=os.environ["REDIS_URL"],
        oidc_issuer=os.environ["OIDC_ISSUER"],
        oidc_client_id=os.environ["OIDC_CLIENT_ID"],
        oidc_client_secret=os.environ["OIDC_CLIENT_SECRET"],
        snowflake_account=os.environ["SNOWFLAKE_ACCOUNT"],
        snowflake_user=os.environ["SNOWFLAKE_USER"],
        snowflake_role=os.environ["SNOWFLAKE_ROLE"],
        snowflake_private_key=os.environ.get("SNOWFLAKE_PRIVATE_KEY", ""),
        agent_runtime=os.environ["AGENT_RUNTIME"],
        model_provider=os.environ["MODEL_PROVIDER"],
        model_id=os.environ["MODEL_ID"],
        model_max_tokens=int(os.environ["MODEL_MAX_TOKENS"]),
        demo_tier_schema=os.environ["DEMO_TIER_SCHEMA"],
        otel_endpoint=os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"],
        feature_flag_source=os.environ["FEATURE_FLAG_SOURCE"],
        worker_poll_seconds=int(os.environ["WORKER_POLL_SECONDS"]),
    )
