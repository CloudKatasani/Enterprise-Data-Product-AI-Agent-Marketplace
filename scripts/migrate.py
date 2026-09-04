#!/usr/bin/env python3
"""Apply the generated migrations in generated/ddl in filename order.

Migrations are forward-only. Each applied file is recorded in ``schema_migration``
with the sha256 of its contents; a changed file that has already been applied is
an error, not a silent re-run.
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


def main() -> int:
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
                        "migrations are forward-only — add a new migration instead",
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
    raise SystemExit(main())
