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
    """The URL the application connects on.

    Two URLs, deliberately. ``DATABASE_URL`` owns the schema: it creates
    extensions, tables and policies, and it needs privileges the application
    must never hold. ``APP_DATABASE_URL`` is the application's own login — a
    member of ``app_role``, not a superuser, not ``BYPASSRLS`` — and every
    row-level policy in this system is written against it.

    That distinction is not decoration. PostgreSQL exempts superusers from
    row-level security entirely, `FORCE ROW LEVEL SECURITY` included, so an
    application connecting as the owner of its own schema has RLS switched off
    and no error anywhere says so. The security suite asserts the connection
    this function returns cannot bypass RLS.

    Falling back to ``DATABASE_URL`` keeps a fresh checkout working before
    ``npm run migrate`` has created the application role. It is not a safe
    production configuration and the security suite fails on it.
    """
    load_dotenv()
    url = os.environ.get("APP_DATABASE_URL", "").strip()
    if url:
        return url
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise DatabaseNotConfigured("DATABASE_URL is not set")
    return url


def owner_url() -> str:
    """The URL that owns the schema. Migrations only."""
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
    tenant: str | None = None, *, autocommit: bool = False, as_owner: bool = False
) -> Iterator[psycopg.Connection[Any]]:
    """A connection bound to a tenant, with dict rows.

    ``as_owner`` is for the tools that create schemas — the demo tier and the
    platform sandbox — which need privileges the application deliberately does
    not have. Everything that serves a request uses the default, and the
    security suite asserts that connection cannot bypass row-level security.
    """
    resolved = tenant or tenant_id()
    connection = psycopg.connect(
        owner_url() if as_owner else database_url(), row_factory=dict_row
    )
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


APP_ROLE = "app_role"


def grant_read(connection: psycopg.Connection[Any], schema: str) -> None:
    """Let the application read a schema its owner just created.

    The generated DDL grants on ``public``; a schema created at seed time —
    the demo tier, the platform sandbox — has to say so itself. Without this the
    application connects as a role that cannot see the demo data, which shows up
    as an agent failing to answer rather than as a permissions error anyone
    reads.
    """
    from psycopg import sql

    name = sql.Identifier(schema)
    role = sql.Identifier(APP_ROLE)
    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(name, role))
        cursor.execute(
            sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}").format(name, role)
        )
        # And on what is created next: the demo tier writes a table per product
        # after this runs.
        cursor.execute(
            sql.SQL("ALTER DEFAULT PRIVILEGES IN SCHEMA {} GRANT SELECT ON TABLES TO {}")
            .format(name, role)
        )
