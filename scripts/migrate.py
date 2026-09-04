#!/usr/bin/env python3
"""Apply the generated migrations in generated/ddl in filename order.

Migrations are forward-only. Each applied file is recorded in ``schema_migration``
with the sha256 of its contents; a changed file that has already been applied is
an error, not a silent re-run.

Before the first tagged release the generated DDL is a *baseline* rather than a
history: the canonical model is still moving, and emitting a delta migration for
every column would produce a history nobody will ever replay. ``--reset`` drops
and rebuilds the schema, which is what a development database and CI use. Once
the schema is released the baseline is frozen and `gen:ddl` emits deltas; the
forward-only check below is what will enforce that.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts._paths import GENERATED  # noqa: E402
from services.common.config import load_dotenv  # noqa: E402

BOOTSTRAP = """
CREATE TABLE IF NOT EXISTS schema_migration (
  filename    TEXT PRIMARY KEY,
  sha256      TEXT NOT NULL,
  applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


RESET_FLAG = "--reset"

DROP_SCHEMA = """
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
GRANT ALL ON SCHEMA public TO public;
"""


def _application_login() -> tuple[str, str] | None:
    """The application's own login, parsed from ``APP_DATABASE_URL``.

    Returns ``None`` when the deployment has not declared one, which is the
    development default. Section 19 wants the application connecting as a role
    that row-level security actually applies to; PostgreSQL exempts superusers
    from RLS entirely, ``FORCE ROW LEVEL SECURITY`` included, so an application
    connecting as its schema owner has isolation switched off with nothing
    anywhere reporting it.
    """
    from urllib.parse import urlsplit

    url = os.environ.get("APP_DATABASE_URL", "").strip()
    if not url:
        return None
    parts = urlsplit(url)
    if not parts.username:
        return None
    return parts.username, parts.password or ""


def _ensure_application_role(conn) -> None:
    """Create or correct the application login, and grant it ``app_role``.

    Idempotent, and it *re-asserts* NOSUPERUSER and NOBYPASSRLS on every run
    rather than only on creation. A role that was granted those privileges by
    hand at some point is exactly the case this needs to catch, and it is a case
    that never shows up as an error.
    """
    login = _application_login()
    if login is None:
        print(
            "migrate: APP_DATABASE_URL is not set, so the application will connect as "
            "the schema owner. Row-level security does not apply to a superuser, and "
            "the security suite fails on that configuration."
        )
        return

    from psycopg import sql

    username, password = login
    # Neither a role name nor a password can be a bind parameter in a role
    # statement, so both are composed with psycopg's quoting rather than
    # interpolated into a string.
    role = sql.Identifier(username)
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (username,))
        if cur.fetchone() is None:
            cur.execute(sql.SQL("CREATE ROLE {} LOGIN").format(role))
        if password:
            cur.execute(
                sql.SQL("ALTER ROLE {} PASSWORD {}").format(role, sql.Literal(password))
            )
        cur.execute(
            sql.SQL("ALTER ROLE {} NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE")
            .format(role)
        )
        cur.execute(sql.SQL("GRANT app_role TO {}").format(role))
        cur.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
        # The generated DDL grants table privileges to app_role, but sequences
        # need saying separately or the application can read a table and not
        # insert into it.
        cur.execute(
            sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}")
            .format(role)
        )
    conn.commit()
    print(f"migrate: application role {username} — member of app_role, not a superuser")


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    reset = RESET_FLAG in argv
    load_dotenv()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("migrate: DATABASE_URL is not set", file=sys.stderr)
        return 1

    ddl_dir = GENERATED / "ddl"
    migrations = sorted(ddl_dir.glob("*.sql")) if ddl_dir.exists() else []
    if not migrations:
        print("migrate: no migrations in generated/ddl — run npm run gen first")
        return 0

    import psycopg

    applied = 0
    with psycopg.connect(database_url, autocommit=False) as conn:
        if reset:
            with conn.cursor() as cur:
                cur.execute(DROP_SCHEMA)
            conn.commit()
            print("migrate: schema dropped and recreated (--reset)")

        with conn.cursor() as cur:
            cur.execute(BOOTSTRAP)
        conn.commit()

        _ensure_application_role(conn)

        for path in migrations:
            sql = path.read_text(encoding="utf-8")
            digest = hashlib.sha256(sql.encode("utf-8")).hexdigest()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT sha256 FROM schema_migration WHERE filename = %s", (path.name,)
                )
                row = cur.fetchone()
            if row is not None:
                if row[0] != digest:
                    print(
                        f"migrate: {path.name} has changed since it was applied; "
                        "migrations are forward-only. Add a new migration, or rebuild a "
                        "development database with: npm run migrate -- --reset",
                        file=sys.stderr,
                    )
                    return 1
                continue

            with conn.cursor() as cur:
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO schema_migration (filename, sha256) VALUES (%s, %s)",
                    (path.name, digest),
                )
            conn.commit()
            applied += 1
            print(f"migrate: applied {path.name}")

    print(f"migrate: {applied} migration(s) applied, {len(migrations) - applied} already current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
