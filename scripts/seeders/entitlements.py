"""Seed access requests and the grants they produced.

A grant exists because a request was approved. That is not decoration: the
request is what carries the purpose, and a grant whose purpose cannot be named
is exactly the kind of standing access this marketplace is meant to replace. So
every grant here is written with the request that produced it.

Three consumer personas of deliberately different breadth, because the
entitlement evaluation suite needs at least three (section 15.4) and because the
partial-permission case is the common one, not the exception:

* **broad** sees every column the agent's binding allows;
* **standard** sees everything but the columns classed ``restricted``;
* **narrow** sees only ``internal`` columns.

Each agent's machine identity is granted exactly its binding. Effective access
for a delegated call is the intersection of the two (I12), so the narrow
persona asking through a broadly-scoped agent still gets the narrow answer.
"""

from __future__ import annotations

from typing import Any

import psycopg

from services.common.db import fetch_all

SCOPE_COLUMNS = "columns"
ACCESS_READ_DATA = "read_data"
ASSET_DATA_PRODUCT = "data_product"
ASSET_AGENT = "agent"
ACCESS_AGENT_INVOKE = "agent_invoke"
REQUEST_ACCESS = "access"
STATE_APPROVED = "approved"
PURPOSE = "analytics"

SENSITIVITY_RESTRICTED = "restricted"
SENSITIVITY_INTERNAL = "internal"

GRANT_MONTHS = "12 months"

# (party_id, label, the sensitivity classes the persona may read)
PERSONAS: list[tuple[str, str, frozenset[str]]] = [
    ("PTY-0061", "broad", frozenset({"internal", "confidential", "restricted"})),
    ("PTY-0062", "standard", frozenset({"internal", "confidential"})),
    ("PTY-0063", "narrow", frozenset({SENSITIVITY_INTERNAL})),
]

PERSONA_PURPOSE = {
    "broad": "Full analytical access for the marketplace demo estate.",
    "standard": "Analytical access excluding restricted columns.",
    "narrow": "Internal-only analytical access, for the least-privilege persona.",
}


def _scope_for(product_id: str) -> str:
    return f"dp:{product_id}:read"


def _invoke_scope(agent_id: str) -> str:
    return f"agent:{agent_id}:invoke"


def _bindings(connection: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    return fetch_all(
        connection,
        "SELECT DISTINCT b.product_id, v.agent_id, a.machine_identity "
        "FROM agent_product_binding b "
        "JOIN agent_version v ON v.agent_version_id = b.agent_version_id "
        "JOIN agent a ON a.agent_id = v.agent_id "
        "ORDER BY b.product_id, v.agent_id",
    )


def _columns_by_sensitivity(
    connection: psycopg.Connection[Any], product_id: str, allowed: frozenset[str]
) -> list[str]:
    rows = fetch_all(
        connection,
        "SELECT name FROM data_product_column WHERE product_id = %s "
        "AND sensitivity_code = ANY(%s) ORDER BY ordinal",
        (product_id, sorted(allowed)),
    )
    return [row["name"] for row in rows]


def _agent_columns(connection: psycopg.Connection[Any], agent_id: str, product_id: str) -> list[str]:
    rows = fetch_all(
        connection,
        "SELECT DISTINCT unnest(b.columns_allowed) AS name FROM agent_product_binding b "
        "JOIN agent_version v ON v.agent_version_id = b.agent_version_id "
        "WHERE v.agent_id = %s AND b.product_id = %s ORDER BY 1",
        (agent_id, product_id),
    )
    return [row["name"] for row in rows]


def _write(
    connection: psycopg.Connection[Any],
    tenant: str,
    *,
    grant_id: str,
    principal_id: str,
    product_id: str,
    purpose_text: str,
    columns: list[str],
) -> int:
    request_id = f"REQ-{grant_id}"
    connection.execute(
        "INSERT INTO request (request_id, tenant_id, request_type, state, requester_party_id, "
        "  title, body, purpose_code, purpose_text, policy_path, submitted_at, closed_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now()) "
        "ON CONFLICT (request_id) DO NOTHING",
        (
            request_id,
            tenant,
            REQUEST_ACCESS,
            STATE_APPROVED,
            principal_id,
            f"Read access to {product_id}",
            purpose_text,
            PURPOSE,
            purpose_text,
            "owner",
        ),
    )
    connection.execute(
        "INSERT INTO entitlement_grant (grant_id, tenant_id, request_id, principal_id, "
        "  asset_type, asset_id, access_level, purpose_code, purpose_text, platform_role, "
        "  oauth_scopes, granted_at, expires_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now() + %s::interval) "
        # A grant's terms are immutable — the append-only trigger on this table
        # enforces it, and re-seeding must not try to talk its way past that.
        # Changing what a principal may read means revoking and issuing anew.
        "ON CONFLICT (grant_id) DO NOTHING",
        (
            grant_id,
            tenant,
            request_id,
            principal_id,
            ASSET_DATA_PRODUCT,
            product_id,
            ACCESS_READ_DATA,
            PURPOSE,
            purpose_text,
            f"MKT_{product_id.replace('-', '_')}_READ",
            [_scope_for(product_id)],
            GRANT_MONTHS,
        ),
    )
    connection.execute(
        "INSERT INTO grant_scope (scope_id, tenant_id, grant_id, scope_kind, expression, "
        "  applied_in_platform) VALUES (%s, %s, %s, %s, %s, true) "
        "ON CONFLICT (scope_id) DO NOTHING",
        (f"SCP-{grant_id}-COLS", tenant, grant_id, SCOPE_COLUMNS, ",".join(columns)),
    )
    return 1


def seed(connection: psycopg.Connection[Any], tenant: str) -> int:
    written = 0
    products = sorted({row["product_id"] for row in _bindings(connection)})

    for party_id, label, sensitivities in PERSONAS:
        for product_id in products:
            columns = _columns_by_sensitivity(connection, product_id, sensitivities)
            if not columns:
                # A persona with nothing readable on a product holds no grant on
                # it. An empty grant and no grant are the same access; only one
                # of them is honest about it.
                continue
            written += _write(
                connection,
                tenant,
                grant_id=f"GRT-{party_id}-{product_id}",
                principal_id=party_id,
                product_id=product_id,
                purpose_text=PERSONA_PURPOSE[label],
                columns=columns,
            )

    # Invoking an agent is a grant of its own. Holding the data the agent reads
    # does not imply permission to ask the agent, and the reverse is exactly the
    # partial-permission case the catalog is built to show: an agent you may
    # invoke, on data you may only partly see, gives you the part you may see.
    for agent in fetch_all(
        connection, "SELECT agent_id FROM agent ORDER BY agent_id"
    ):
        for party_id, label, _sensitivities in PERSONAS:
            grant_id = f"GRT-{party_id}-{agent['agent_id']}"
            request_id = f"REQ-{grant_id}"
            purpose_text = PERSONA_PURPOSE[label]
            connection.execute(
                "INSERT INTO request (request_id, tenant_id, request_type, state, "
                "  requester_party_id, title, body, purpose_code, purpose_text, policy_path, "
                "  submitted_at, closed_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now()) "
                "ON CONFLICT (request_id) DO NOTHING",
                (request_id, tenant, REQUEST_ACCESS, STATE_APPROVED, party_id,
                 f"Invoke {agent['agent_id']}", purpose_text, PURPOSE, purpose_text, "owner"),
            )
            connection.execute(
                "INSERT INTO entitlement_grant (grant_id, tenant_id, request_id, "
                "  principal_id, asset_type, asset_id, access_level, purpose_code, "
                "  purpose_text, platform_role, oauth_scopes, granted_at, expires_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), "
                "        now() + %s::interval) ON CONFLICT (grant_id) DO NOTHING",
                (grant_id, tenant, request_id, party_id, ASSET_AGENT, agent["agent_id"],
                 ACCESS_AGENT_INVOKE, PURPOSE, purpose_text,
                 f"MKT_{agent['agent_id'].replace('-', '_')}_INVOKE",
                 [_invoke_scope(agent["agent_id"])], GRANT_MONTHS),
            )
            written += 1

    for row in _bindings(connection):
        columns = _agent_columns(connection, row["agent_id"], row["product_id"])
        if not columns:
            continue
        written += _write(
            connection,
            tenant,
            grant_id=f"GRT-{row['machine_identity']}-{row['product_id']}",
            principal_id=row["machine_identity"],
            product_id=row["product_id"],
            purpose_text=f"Machine identity for {row['agent_id']}, scoped to its binding.",
            columns=columns,
        )
    return written
