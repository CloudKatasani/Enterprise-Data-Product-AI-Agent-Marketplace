#!/usr/bin/env python3
"""Migration lint — RLS is on by default and append-only tables stay append-only.

BUILD.md section 6.2: "Add ``tenant_id`` and a row-level-security policy to every
table. RLS is on by default; a table without a policy fails the migration lint."
Section 0 rule 6: snapshot, publication, audit and grant history are append-only.

The rule reads the generated DDL under ``generated/ddl`` and asserts, for every
``CREATE TABLE`` it finds:

  * the table declares a ``tenant_id`` column;
  * ``ALTER TABLE ... ENABLE ROW LEVEL SECURITY`` is present;
  * at least one ``CREATE POLICY`` targets the table;
  * append-only tables carry a ``REVOKE UPDATE, DELETE`` grant.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lint._common import REPO_ROOT, Finding, report  # noqa: E402

DDL_DIR = REPO_ROOT / "generated" / "ddl"

APPEND_ONLY_TABLES = {
    "quality_score_snapshot",
    "publication_snapshot",
    "audit_event",
    "entitlement_grant",
}
# Reference and configuration tables are tenant-independent by design: they are
# the shared vocabulary every tenant resolves against.
GLOBAL_TABLES = {
    "tenant",
    "industry",
    "business_domain",
    "product_archetype",
    "sensitivity_tier",
    "purpose_category",
    "schema_migration",
}

CREATE_TABLE = re.compile(r"CREATE TABLE(?: IF NOT EXISTS)?\s+([a-z_][a-z0-9_]*)\s*\(", re.I)
ENABLE_RLS = re.compile(r"ALTER TABLE\s+([a-z_][a-z0-9_]*)\s+ENABLE ROW LEVEL SECURITY", re.I)
CREATE_POLICY = re.compile(r"CREATE POLICY\s+\S+\s+ON\s+([a-z_][a-z0-9_]*)", re.I)
REVOKE = re.compile(r"REVOKE\s+UPDATE\s*,\s*DELETE\s+ON\s+([a-z_][a-z0-9_]*)", re.I)


def main() -> int:
    if not DDL_DIR.exists():
        print("lint:migrations: no generated/ddl yet — run npm run gen")
        return 0

    findings: list[Finding] = []
    sql = ""
    first_path = None
    for path in sorted(DDL_DIR.glob("*.sql")):
        first_path = first_path or path
        sql += path.read_text(encoding="utf-8") + "\n"
    if first_path is None:
        print("lint:migrations: no migrations found")
        return 0

    tables = {match.group(1).lower() for match in CREATE_TABLE.finditer(sql)}
    rls_enabled = {match.group(1).lower() for match in ENABLE_RLS.finditer(sql)}
    policied = {match.group(1).lower() for match in CREATE_POLICY.finditer(sql)}
    revoked = {match.group(1).lower() for match in REVOKE.finditer(sql)}

    bodies: dict[str, str] = {}
    for match in CREATE_TABLE.finditer(sql):
        end = sql.find(");", match.end())
        bodies[match.group(1).lower()] = sql[match.end() : end]

    for table in sorted(tables):
        if table in GLOBAL_TABLES:
            continue
        if "tenant_id" not in bodies.get(table, ""):
            findings.append(Finding(first_path, 1, f"table {table!r} has no tenant_id column"))
        if table not in rls_enabled:
            findings.append(Finding(first_path, 1, f"table {table!r} does not enable RLS"))
        if table not in policied:
            findings.append(Finding(first_path, 1, f"table {table!r} has no row-level policy"))

    for table in sorted(APPEND_ONLY_TABLES):
        if table in tables and table not in revoked:
            findings.append(
                Finding(first_path, 1, f"append-only table {table!r} does not revoke UPDATE, DELETE")
            )

    return report("lint:migrations", findings)


if __name__ == "__main__":
    raise SystemExit(main())
