"""Enhancement requests and the public backlog (section 14.2).

Submitted -> Triaged -> Assessed -> {Accepted | Declined | Merged}
          -> Scheduled -> InProgress -> Delivered -> Verified

Two rules from the spec are the whole reason this is not a ticket queue.

**Declines are public and carry a controlled reason.** A backlog where things
quietly disappear teaches consumers that asking is pointless, and then the
backlog stops reflecting what people need. A controlled list makes declines
countable: "seventeen requests declined as source_unavailable" is a fact
somebody can act on; seventeen paragraphs of free text is not.

**Merging carries votes forward.** Two teams asking for the same thing is
evidence of twice the demand, and a merge that drops one team's votes turns
evidence into noise.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import psycopg

from services.common.db import fetch_all
from services.common.rubrics import Rubric
from services.workflow import engine

DECLINE_REASONS = frozenset(
    {"out_of_scope", "source_unavailable", "cost_prohibitive", "duplicate", "superseded",
     "security_constraint"}
)

TRIAGE_SLA_PATH = "sla_hours.enhancement_triage"
AUTO_CLOSE_DAYS = "auto_close_unverified_days"
ESCALATION_FRACTION_PATH = "sla_hours.escalation_at_fraction_of_sla"

FULLY_ELAPSED = 1.0

REQUEST_TYPE = "enhancement"


class EnhancementRefusedError(RuntimeError):
    """The move cannot be made as asked."""


def submit(
    connection: psycopg.Connection[Any],
    tenant: str,
    rubric: Rubric,
    *,
    request_id: str,
    requester_party_id: str,
    asset_type: str,
    asset_id: str,
    title: str,
    body: str,
) -> dict[str, Any]:
    hours = int(rubric.number(TRIAGE_SLA_PATH))
    connection.execute(
        "INSERT INTO request (request_id, tenant_id, request_type, state, requester_party_id, "
        "  title, body, sla_hours, sla_due_at, submitted_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now() + %s::interval, now()) "
        "ON CONFLICT (request_id) DO NOTHING",
        (request_id, tenant, REQUEST_TYPE, engine.ENH_SUBMITTED, requester_party_id,
         title, body, hours, f"{hours} hours"),
    )
    connection.execute(
        "INSERT INTO request_item (request_item_id, tenant_id, request_id, asset_type, "
        "  asset_id, access_level, columns_requested) "
        "VALUES (%s, %s, %s, %s, %s, 'read_metadata', '{}') "
        "ON CONFLICT (request_item_id) DO NOTHING",
        (f"RQI-{request_id}-{asset_id}", tenant, request_id, asset_type, asset_id),
    )
    engine.start(
        connection, tenant, workflow_type=engine.TYPE_ENHANCEMENT, subject_id=request_id,
        actor=requester_party_id, payload={"asset_id": asset_id, "title": title},
    )
    return {"request_id": request_id, "state": engine.ENH_SUBMITTED, "sla_hours": hours}


def advance(
    connection: psycopg.Connection[Any],
    tenant: str,
    *,
    request_id: str,
    to_state: str,
    actor: str,
    reason_code: str | None = None,
    reason_text: str | None = None,
    merge_into: str | None = None,
) -> dict[str, Any]:
    detail: dict[str, Any] = {}

    if to_state == engine.ENH_DECLINED:
        if reason_code not in DECLINE_REASONS:
            raise EnhancementRefusedError(
                f"{reason_code!r} is not a decline reason; declines are public and use one "
                "of " + ", ".join(sorted(DECLINE_REASONS))
            )
        if not (reason_text or "").strip():
            raise EnhancementRefusedError(
                "a decline needs free text alongside its code: the code makes it countable, "
                "the text makes it answerable"
            )
        detail = {"reason_code": reason_code, "reason_text": reason_text}

    if to_state == engine.ENH_MERGED:
        if not merge_into:
            raise EnhancementRefusedError("a merge must name the request it merges into")
        detail = {"merged_into": merge_into, "votes_carried": _carry_votes(
            connection, tenant, request_id, merge_into
        )}

    instance = engine.transition(
        connection, tenant, workflow_type=engine.TYPE_ENHANCEMENT, subject_id=request_id,
        to_state=to_state, actor=actor, detail=detail,
    )
    closed = to_state in engine.TERMINAL[engine.TYPE_ENHANCEMENT]
    connection.execute(
        "UPDATE request SET state = %s, closed_at = CASE WHEN %s THEN now() ELSE closed_at END "
        "WHERE request_id = %s",
        (to_state, closed, request_id),
    )
    return {"state": instance.state, **detail}


def _carry_votes(
    connection: psycopg.Connection[Any], tenant: str, source_id: str, target_id: str
) -> int:
    """Move votes to the surviving request, keeping each voter's use case.

    A voter who has already backed the target keeps their original use case: the
    first thing they said about why they need it is the more considered one.
    """
    moved = fetch_all(
        connection,
        "INSERT INTO demand_vote (vote_id, tenant_id, demand_id, voter_party_id, use_case, "
        "  org_unit_id) "
        "SELECT %s || voter_party_id, tenant_id, %s, voter_party_id, use_case, org_unit_id "
        "FROM demand_vote WHERE demand_id = %s "
        "ON CONFLICT (demand_id, voter_party_id) DO NOTHING RETURNING vote_id",
        (f"DVT-{target_id}-", target_id, source_id),
    )
    return len(moved)


def backlog(
    connection: psycopg.Connection[Any], *, asset_id: str | None = None
) -> list[dict[str, Any]]:
    """The public backlog. Declined items stay on it, with their reason.

    Hiding declines would make the backlog look healthier and make the estate
    less trustworthy, which is the wrong trade in both directions.
    """
    where = "AND i.asset_id = %s" if asset_id else ""
    return fetch_all(
        connection,
        "SELECT r.request_id, r.title, r.body, r.state, r.requester_party_id, "
        "       r.submitted_at, r.sla_due_at, r.closed_at, i.asset_type, i.asset_id, "
        "       (SELECT count(*) FROM demand_vote v WHERE v.demand_id = r.request_id) "
        "         AS votes, "
        "       (SELECT e.detail FROM workflow_event e "
        "        WHERE e.instance_id = 'WFI-enhancement-' || r.request_id "
        "          AND e.to_state = 'declined' ORDER BY e.occurred_at DESC LIMIT 1) "
        "         AS decline "
        "FROM request r "
        "LEFT JOIN request_item i ON i.request_id = r.request_id "
        f"WHERE r.request_type = 'enhancement' {where} "
        "ORDER BY votes DESC, r.submitted_at DESC",
        (asset_id,) if asset_id else (),
    )


def overdue(connection: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    """Requests past their triage SLA. The SLA board's contents."""
    return fetch_all(
        connection,
        "SELECT request_id, title, state, sla_due_at, requester_party_id "
        "FROM request WHERE request_type = %s AND closed_at IS NULL "
        "  AND sla_due_at IS NOT NULL AND sla_due_at < now() ORDER BY sla_due_at",
        (REQUEST_TYPE,),
    )


def unverified(
    connection: psycopg.Connection[Any], rubric: Rubric
) -> list[dict[str, Any]]:
    """Delivered work nobody has verified.

    Section 14.2 auto-closes these as delivered with a note. The note matters:
    an item closed without verification is a weaker claim than one verified, and
    a backlog that does not distinguish them overstates what was actually
    landed.
    """
    days = int(rubric.number(f"sla_hours.{AUTO_CLOSE_DAYS}"))
    return fetch_all(
        connection,
        "SELECT w.subject_id AS request_id, w.state, r.title, "
        "       (SELECT max(e.occurred_at) FROM workflow_event e "
        "        WHERE e.instance_id = w.instance_id AND e.to_state = 'delivered') "
        "         AS delivered_at "
        "FROM workflow_instance w JOIN request r ON r.request_id = w.subject_id "
        "WHERE w.workflow_type = %s AND w.state = %s "
        "  AND (SELECT max(e.occurred_at) FROM workflow_event e "
        "       WHERE e.instance_id = w.instance_id AND e.to_state = 'delivered') "
        "      < now() - %s::interval "
        "ORDER BY 4",
        (engine.TYPE_ENHANCEMENT, engine.ENH_DELIVERED, f"{days} days"),
    )


def sla_board(connection: psycopg.Connection[Any]) -> dict[str, Any]:
    """Every open request against its clock, whatever its type."""
    rows = fetch_all(
        connection,
        "SELECT request_type, state, count(*) AS open, "
        "       count(*) FILTER (WHERE sla_due_at < now()) AS breached, "
        "       count(*) FILTER (WHERE sla_due_at >= now()) AS in_time "
        "FROM request WHERE closed_at IS NULL GROUP BY 1, 2 ORDER BY 1, 2",
    )
    return {
        "rows": rows,
        "breached": sum(int(row["breached"]) for row in rows),
        "open": sum(int(row["open"]) for row in rows),
    }


def triage_due(connection: psycopg.Connection[Any], rubric: Rubric) -> list[dict[str, Any]]:
    """Requests approaching their SLA, so escalation happens before breach."""
    fraction = float(rubric.number(ESCALATION_FRACTION_PATH))
    return [
        row
        for row in fetch_all(
            connection,
            "SELECT request_id, title, state, submitted_at, sla_due_at, sla_hours "
            "FROM request WHERE closed_at IS NULL AND sla_due_at IS NOT NULL "
            "ORDER BY sla_due_at",
        )
        if _elapsed_fraction(row) >= fraction
    ]


def _elapsed_fraction(row: dict[str, Any]) -> float:
    """How far through its SLA a request is. Zero-length SLAs are already due."""
    total = (row["sla_due_at"] - row["submitted_at"]).total_seconds()
    if total <= 0:
        return FULLY_ELAPSED
    elapsed = (datetime.now(UTC) - row["submitted_at"]).total_seconds()
    return elapsed / total
