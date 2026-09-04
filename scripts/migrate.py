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
