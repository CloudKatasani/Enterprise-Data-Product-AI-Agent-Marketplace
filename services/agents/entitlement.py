"""What a caller may actually read, resolved fresh on every call.

Two rules, and they are the whole module.

**Fail closed.** No live grant on a product means no columns on that product,
not "all of them". A grant that carries no columns scope means every column the
asset publishes — the scope narrows a grant, it does not constitute one.

**Intersect, never union (I12).** A delegated call carries a user and an agent
machine identity. What it may read is what *both* hold. An agent cannot widen
the user it acts for, and a broadly-scoped agent asked a question by a narrowly
entitled user returns the narrow answer.

Refusals here deliberately do not name the columns the caller is missing. A
message reading "you cannot see patient_mrn" tells the caller that
``patient_mrn`` exists, which is the leak the entitlement suite exists to catch.
The caller is told which asset and which scope, and pointed at the request form.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg

from services.common.db import fetch_all

SCOPE_COLUMNS = "columns"


@dataclass(frozen=True)
class Readable:
    """The columns a principal may read on one product, and why."""

    product_id: str
    columns: frozenset[str]
    scope: str
    granted: bool

    def permits(self, wanted: list[str] | tuple[str, ...]) -> bool:
        return self.granted and set(wanted) <= self.columns


def _grants(
    connection: psycopg.Connection[Any], principal_id: str, product_id: str
) -> list[dict[str, Any]]:
    return fetch_all(
        connection,
        "SELECT g.grant_id, "
        "       (SELECT array_agg(s.expression) FROM grant_scope s "
        "        WHERE s.grant_id = g.grant_id AND s.scope_kind = %s) AS column_scopes "
        "FROM entitlement_grant g "
        "WHERE g.principal_id = %s AND g.asset_id = %s "
        "  AND g.revoked_at IS NULL AND g.expires_at > now()",
        (SCOPE_COLUMNS, principal_id, product_id),
    )


def _published_columns(connection: psycopg.Connection[Any], product_id: str) -> frozenset[str]:
    rows = fetch_all(
        connection, "SELECT name FROM data_product_column WHERE product_id = %s", (product_id,)
    )
    return frozenset(row["name"] for row in rows)


def _for_one(
    connection: psycopg.Connection[Any], principal_id: str, product_id: str
) -> frozenset[str] | None:
    """Columns this principal may read, or None where it holds no grant at all."""
    grants = _grants(connection, principal_id, product_id)
    if not grants:
        return None
    readable: set[str] = set()
    for grant in grants:
        scopes = grant["column_scopes"]
        if not scopes:
            # A grant with no columns scope is unnarrowed: it reaches whatever
            # the product publishes.
            return _published_columns(connection, product_id)
        for expression in scopes:
            readable.update(name.strip() for name in expression.split(",") if name.strip())
    return frozenset(readable)


def readable_columns(
    connection: psycopg.Connection[Any],
    *,
    principal_id: str,
    product_id: str,
    agent_identity: str | None = None,
) -> Readable:
    scope = f"dp:{product_id}:read"
    held = _for_one(connection, principal_id, product_id)
    if held is None:
        return Readable(product_id, frozenset(), scope, granted=False)

    if agent_identity:
        agent_held = _for_one(connection, principal_id=agent_identity, product_id=product_id)
        if agent_held is None:
            return Readable(product_id, frozenset(), scope, granted=False)
        held = held & agent_held

    return Readable(product_id, held, scope, granted=True)
