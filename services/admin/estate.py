"""Taxonomies, connectors, feature flags and tenancy (M12.2).

Four read-mostly surfaces with one thing in common: each shows what is
configured *and* what depends on it. A taxonomy entry with products behind it
cannot be deleted, a connector with a failing kill test is a security finding
rather than a status line, and a flag with no expiry is a permanent branch
somebody called temporary.

Nothing here can edit a record. An administrator has wide authority over what
the rules are and none at all over what happened, and the append-only triggers
enforce that whatever a console asks for.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import psycopg

from services.common import audit
from services.common.db import fetch_all, fetch_one
from services.common.rubrics import Rubric

EVENT_FLAG_CHANGED = "feature_flag.changed"

# Each vocabulary, the table it seeds, and the column that points back at it.
# Usage is what makes the table safe to read: a code with rows behind it is a
# code nobody can quietly retire.
TAXONOMIES = (
    ("industry", "industry", "data_product", "industry_code"),
    ("domain", "business_domain", "data_product", "domain_code"),
    ("archetype", "product_archetype", "data_product", "archetype_code"),
    ("sensitivity", "sensitivity_tier", "data_product", "sensitivity_tier"),
    ("purpose", "purpose_category", "entitlement_grant", "purpose_code"),
)


def taxonomies(connection: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for code, table, referencing, column in TAXONOMIES:
        rows = fetch_all(
            connection,
            f"SELECT t.code, t.label, "  # noqa: S608 - table names from a fixed tuple
            f"       (SELECT count(*) FROM {referencing} r WHERE r.{column} = t.code) AS uses "
            f"FROM {table} t ORDER BY t.code",
        )
        result.append(
            {
                "taxonomy": code,
                "table": table,
                "entries": [
                    {"code": row["code"], "label": row["label"], "uses": int(row["uses"])}
                    for row in rows
                ],
            }
        )
    return result


def connectors(connection: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    """Every source system, what it feeds and how recently it was harvested.

    The read-only guarantee is not reported from configuration. It is asserted
    by ``npm run test:kill``, which attempts a write on every supported platform
    on every build and requires all of them to fail. A console that read a flag
    called ``read_only`` would be reporting an intention.
    """
    return [
        {
            "source_id": row["source_id"],
            "name": row["name"],
            "platform": row["platform"],
            "owner_team": row["owner_team"],
            "criticality": row["criticality"],
            "products": int(row["products"]),
            "last_harvest": (
                row["last_harvest"].isoformat() if row["last_harvest"] else None
            ),
        }
        for row in fetch_all(
            connection,
            "SELECT s.source_id, s.name, s.platform, s.owner_team, s.criticality, "
            "       (SELECT count(DISTINCT l.downstream_id) FROM lineage_edge l "
            "         WHERE l.upstream_id = s.source_id "
            "           AND l.upstream_type = 'source_system') AS products, "
            "       (SELECT max(l.harvested_at) FROM lineage_edge l "
            "         WHERE l.upstream_id = s.source_id) AS last_harvest "
            "FROM source_system s ORDER BY s.source_id",
        )
    ]


def flags(connection: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    """Feature flags, with the one number that matters: how old they are.

    A flag past its expiry is not a flag, it is a branch in production that
    somebody described as temporary. The console shows the age so that fact is
    unavoidable rather than discoverable.
    """
    now = datetime.now(UTC)
    return [
        {
            "code": row["code"],
            "flag_type": row["flag_type"],
            "enabled": bool(row["enabled"]),
            "description": row["description"],
            "owner_party_id": row["owner_party_id"],
            "created_at": row["created_at"].isoformat(),
            "expires_at": row["expires_at"].isoformat() if row["expires_at"] else None,
            "expired": bool(row["expires_at"] and row["expires_at"] < now),
            "age_days": (now - row["created_at"]).days,
        }
        for row in fetch_all(
            connection,
            "SELECT code, flag_type, enabled, description, owner_party_id, created_at, "
            "       expires_at FROM feature_flag ORDER BY code",
        )
    ]


def set_flag(
    connection: psycopg.Connection[Any],
    tenant: str,
    governance: Rubric,
    *,
    code: str,
    enabled: bool,
    actor_party_id: str | None,
) -> dict[str, Any]:
    """Toggle a flag, and write who did it.

    Audited because a flag is a control: "it was on all along" and "somebody
    turned it on at 14:20" are different explanations for the same incident.
    """
    row = fetch_one(connection, "SELECT code FROM feature_flag WHERE code = %s", (code,))
    if row is None:
        raise LookupError(code)

    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE feature_flag SET enabled = %s WHERE code = %s", (enabled, code)
        )

    audit.record(
        connection,
        tenant,
        governance,
        audit_id=f"AUD-FLAG-{code}-{datetime.now(UTC):%Y%m%d%H%M%S%f}",
        event_name=EVENT_FLAG_CHANGED,
        outcome="enabled" if enabled else "disabled",
        actor_party_id=actor_party_id,
        asset_type="feature_flag",
        asset_id=code,
        detail={"enabled": enabled},
    )
    return {"code": code, "enabled": enabled}


def tenancy(connection: psycopg.Connection[Any]) -> dict[str, Any]:
    """The tenant, its org units and what is isolated by row-level security.

    The RLS count is read from the catalog rather than from a list in code. A
    table added without a policy is the failure this panel exists to make
    visible, and a hand-maintained list would not show it.
    """
    tenant = fetch_one(connection, "SELECT * FROM tenant LIMIT 1")
    # A table needs row-level security exactly when it carries a tenant. The
    # test derives that from the schema rather than from a list somebody
    # maintains: shared reference vocabulary has no tenant_id and is meant to be
    # readable across tenants, and a hand-written exception list would sooner or
    # later contain a table that should not be on it.
    rows = fetch_all(
        connection,
        "SELECT c.relname AS table_name, c.relrowsecurity AS enabled, "
        "       c.relforcerowsecurity AS forced, "
        "       EXISTS (SELECT 1 FROM information_schema.columns col "
        "                WHERE col.table_name = c.relname "
        "                  AND col.column_name = 'tenant_id') AS tenanted "
        "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND c.relkind = 'r' ORDER BY c.relname",
    )
    tenanted = [row for row in rows if row["tenanted"]]
    unprotected = [
        row["table_name"] for row in tenanted if not (row["enabled"] and row["forced"])
    ]
    return {
        "tenant": dict(tenant) if tenant else None,
        "org_units": fetch_all(
            connection,
            "SELECT org_unit_id, name, region FROM org_unit ORDER BY org_unit_id",
        ),
        "tables": len(rows),
        "tenanted_tables": len(tenanted),
        "shared_reference_tables": [
            row["table_name"] for row in rows if not row["tenanted"]
        ],
        "row_level_security": len(tenanted) - len(unprotected),
        # Named, not counted. A tenanted table without forced RLS is a
        # cross-tenant read waiting to happen, and an administrator needs to
        # know which one rather than that there is one.
        "unprotected_tables": unprotected,
    }
