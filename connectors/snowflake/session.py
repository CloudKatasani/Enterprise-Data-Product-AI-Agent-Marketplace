"""Snowflake sessions.

Three implementations of one protocol:

* :class:`SnowflakeSession` — key-pair authentication against a real account,
  used when ``snowflake-connector-python`` and credentials are present.
* :class:`SandboxSession` — serves the same result shapes from a local
  Postgres schema that mirrors the ACCOUNT_USAGE views the connector reads. It
  exists so the harvest path is exercised end to end without a Snowflake
  account, and so the kill test can attempt real writes somewhere safe.
* :class:`RefusingSession` — refuses everything. Used by the kill test to prove
  the guard fires before a driver is ever reached.

Every one of them routes through :func:`assert_read_only` first. The guard is
not the driver's job.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any

import psycopg
from psycopg.rows import dict_row

from connectors.base import ReadOnlyViolation, assert_read_only


class SnowflakeSession:
    """Read-only session against a Snowflake account, authenticated by key pair.

    The session sets the role from configuration and never issues ``USE ROLE``
    itself: switching role is a privilege operation and the guard refuses it.
    """

    platform = "snowflake"

    def __init__(self, account: str, user: str, role: str, private_key: str) -> None:
        if not private_key.strip():
            raise ReadOnlyViolation(
                "SNOWFLAKE_PRIVATE_KEY is empty; the connector refuses to fall back to "
                "password authentication"
            )
        try:
            import snowflake.connector
        except ImportError as error:  # pragma: no cover - exercised only with the driver present
            raise RuntimeError(
                "snowflake-connector-python is not installed; install the optional "
                "'snowflake' extra to harvest from a real account"
            ) from error

        self._connection = snowflake.connector.connect(
            account=account,
            user=user,
            role=role,
            private_key=private_key.encode("utf-8"),
            session_parameters={"QUERY_TAG": "marketplace-harvest"},
        )

    def query(self, statement: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
        assert_read_only(statement)
        cursor = self._connection.cursor()
        try:
            cursor.execute(statement, params or ())
            columns = [description[0].lower() for description in cursor.description]
            return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
        finally:
            cursor.close()

    def close(self) -> None:
        self._connection.close()


class SandboxSession:
    """The same read surface, served from a local schema shaped like ACCOUNT_USAGE.

    This is a stand-in *platform*, not a stand-in connector: the statements, the
    guard, the result shapes and the harvest code are the ones that run against a
    real account. Only where the rows come from differs.
    """

    platform = "snowflake-sandbox"

    def __init__(self, database_url: str, schema: str) -> None:
        self._schema = schema
        self._connection = psycopg.connect(database_url, row_factory=dict_row)
        with self._connection.cursor() as cursor:
            cursor.execute(f"SET search_path TO {schema}, public")
            # The stand-in platform enforces read-only the way MKT_READONLY does
            # on a real account, so the kill test proves two independent layers:
            # the guard in this process, and the platform behind it.
            cursor.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
        self._connection.commit()

    def query(self, statement: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
        assert_read_only(statement)
        translated = self._translate(statement)
        with self._connection.cursor() as cursor:
            cursor.execute(translated, tuple(params or ()))
            return [dict(row) for row in cursor.fetchall()]

    def _translate(self, statement: str) -> str:
        """Map Snowflake's namespaces onto the sandbox schema.

        Only namespaces are rewritten. The projection, predicates and ordering
        are exactly what runs against a real account, so a change to a harvest
        query is exercised here rather than silently diverging.
        """
        return (
            statement.replace("snowflake.account_usage.", f"{self._schema}.")
            .replace("snowflake.local.", f"{self._schema}.")
            .replace("information_schema.", f"{self._schema}.sf_")
        )

    def unguarded_execute(self, statement: str) -> None:
        """Submit a statement straight to the driver, bypassing the guard.

        Exists only for ``tests/kill``: it is how the test proves the *platform*
        refuses a write, independently of the in-process guard. Nothing in the
        harvest path calls it.
        """
        with self._connection.cursor() as cursor:
            cursor.execute(statement)  # type: ignore[arg-type]

    def close(self) -> None:
        self._connection.close()


class RefusingSession:
    """A session that refuses every statement, read or not.

    Used to assert that callers surface a refusal rather than silently
    continuing with an empty result.
    """

    platform = "refusing"

    def query(self, statement: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
        del params
        assert_read_only(statement)
        raise ReadOnlyViolation("this session refuses all statements by construction")

    def close(self) -> None:
        return None


def open_session() -> SnowflakeSession | SandboxSession:
    """Open whichever session the environment supports.

    A configured private key means a real account. Otherwise the sandbox, which
    is what `npm run dev` and CI use.
    """
    private_key = os.environ.get("SNOWFLAKE_PRIVATE_KEY", "").strip()
    if private_key:
        return SnowflakeSession(
            account=os.environ["SNOWFLAKE_ACCOUNT"],
            user=os.environ["SNOWFLAKE_USER"],
            role=os.environ["SNOWFLAKE_ROLE"],
            private_key=private_key,
        )
    return SandboxSession(
        database_url=os.environ["DATABASE_URL"],
        schema=os.environ["DEMO_TIER_SCHEMA"].lower(),
    )
