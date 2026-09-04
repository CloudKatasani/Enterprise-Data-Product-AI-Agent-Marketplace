"""Writing audit events.

One function, and the discipline is in what it insists on. An audit event names
an actor, and where the call was delegated it names both identities (section
19). Its retention is resolved from the governance rubric at write time and
stored on the row, so a later change of policy does not silently re-date records
already written.

The table is append-only, enforced by a trigger. Nothing here updates.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import psycopg

from services.common.rubrics import Rubric

RETENTION_YEARS_PATH = "audit.retention_years"
GOVERNANCE_RUBRIC = "governance"

def retain_until(rubric: Rubric, *, at: datetime | None = None) -> datetime:
    """The same calendar date, N years on.

    Calendar years, not 365-day years: a retention obligation is expressed in
    years and an audit record kept a day short of one is a record kept a day
    short. The one date that has no counterpart, 29 February, falls back to the
    28th rather than rolling into March.
    """
    moment = at or datetime.now(UTC)
    years = int(rubric.number(RETENTION_YEARS_PATH))
    try:
        return moment.replace(year=moment.year + years)
    except ValueError:
        return moment.replace(year=moment.year + years, day=moment.day - 1)


def record(
    connection: psycopg.Connection[Any],
    tenant: str,
    rubric: Rubric,
    *,
    audit_id: str,
    event_name: str,
    outcome: str,
    detail: dict[str, Any],
    actor_party_id: str | None = None,
    on_behalf_of: str | None = None,
    asset_type: str | None = None,
    asset_id: str | None = None,
    purpose_code: str | None = None,
) -> str:
    connection.execute(
        "INSERT INTO audit_event (audit_id, tenant_id, event_name, actor_party_id, "
        "  on_behalf_of, asset_type, asset_id, purpose_code, outcome, detail, retain_until) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (audit_id) DO NOTHING",
        (
            audit_id, tenant, event_name, actor_party_id, on_behalf_of, asset_type,
            asset_id, purpose_code, outcome, json.dumps(detail, sort_keys=True, default=str),
            retain_until(rubric),
        ),
    )
    return audit_id
