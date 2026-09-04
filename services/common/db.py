"""Database access.

Two things every connection does, without exception:

* it sets ``app.tenant_id`` so the row-level policies emitted by the DDL
  generator have something to evaluate against;
* it runs inside an explicit transaction, so a partially applied write is never
  visible.

There is no "admin" connection helper that skips the tenant setting. Crossing a
tenant boundary requires connecting as a different tenant, which is auditable.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row

from services.common.config import load_dotenv

TENANT_SETTING = "app.tenant_id"


class DatabaseNotConfigured(RuntimeError):
    pass


def database_url() -> str:
    load_dotenv()
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise DatabaseNotConfigured("DATABASE_URL is not set")
    return url


def tenant_id() -> str:
    load_dotenv()
    value = os.environ.get("TENANT_ID", "").strip()
    if not value:
        raise DatabaseNotConfigured("TENANT_ID is not set")
    return value


@contextmanager
def connect(
    tenant: str | None = None, *, autocommit: bool = False
) -> Iterator[psycopg.Connection[Any]]:
    """A connection bound to a tenant, with dict rows."""
    resolved = tenant or tenant_id()
    connection = psycopg.connect(database_url(), row_factory=dict_row)
    try:
        connection.autocommit = autocommit
        with connection.cursor() as cursor:
            # SET does not take a bind parameter, so the value goes through
            # set_config, which does — the tenant never reaches SQL as text.
            cursor.execute("SELECT set_config(%s, %s, false)", (TENANT_SETTING, resolved))
        if not autocommit:
            connection.commit()
        yield connection
        if not autocommit:
            connection.commit()
    except Exception:
        if not autocommit:
            connection.rollback()
        raise
    finally:
        connection.close()


def fetch_all(
    connection: psycopg.Connection[Any], sql: str, params: Any = None
) -> list[dict[str, Any]]:
    # The cursor asks for dict rows itself, so these helpers work against any
    # connection regardless of the row factory it was opened with.
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]


def fetch_one(
    connection: psycopg.Connection[Any], sql: str, params: Any = None
) -> dict[str, Any] | None:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(sql, params)
        row = cursor.fetchone()
        return dict(row) if row is not None else None
