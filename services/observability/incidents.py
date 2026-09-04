"""The incident lifecycle (M10.2, section 15.6).

    detect -> compute severity from blast radius -> notify owner and affected
    consumers -> banner every affected listing -> track to resolution ->
    publish root cause -> link permanently to the asset's quality history

Two rules carry the weight.

**Severity is computed, never chosen.** The inputs are downstream consumer
count, sensitivity rank and whether a stated guarantee broke — three facts about
the estate rather than three judgements about the incident. An owner deciding
how bad their own outage is has an obvious incentive, and a severity anybody can
argue down is a severity nobody acts on. The inputs are stored with the
incident so the number can be checked.

**Owners cannot suppress consumer notification.** They can add context, and the
context is shown alongside the notification rather than instead of it. There is
no code path in this module that skips notifying, and no field an owner can set
that would. That is a design decision more than a technical one: a marketplace
where an owner can quietly decide their consumers do not need to know is a
marketplace whose banners nobody believes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from services.common.db import fetch_all, fetch_one
from services.common.rubrics import Rubric
from services.observability.signals import ASSET_AGENT, ASSET_PRODUCT, Finding

STATUS_OPEN = "open"
STATUS_MITIGATING = "mitigating"
STATUS_RESOLVED = "resolved"
STATUS_CLOSED = "closed"

OPEN_STATUSES = (STATUS_OPEN, STATUS_MITIGATING)

SEVERITY_BANDS_PATH = "severity.bands"
ESCALATE_PATH = "severity.guarantee_breach_escalates_bands"
DEADLINE_PATH = "notification.consumer_deadline_minutes"
BANNER_PATH = "notification.banner_while_open"


class IncidentRefusedError(RuntimeError):
    """The operation is not one this lifecycle permits."""


@dataclass(frozen=True)
class BlastRadius:
    """Who is downstream, and how exposed the data is."""

    consumers: int
    sensitivity_rank: int
    products: tuple[str, ...]
    agents: tuple[str, ...]

    def document(self) -> dict[str, Any]:
        return {
            "consumers": self.consumers,
            "sensitivity_rank": self.sensitivity_rank,
            "products": list(self.products),
            "agents": list(self.agents),
        }


def blast_radius(
    connection: psycopg.Connection[Any], asset_type: str, asset_id: str
) -> BlastRadius:
    """Everything that would notice, and how sensitive the data is.

    For a product: the agents bound to it and the principals holding live
    grants. For an agent: the people who have asked it something, plus the
    sensitivity of the most sensitive product it reads — an agent is exactly as
    exposed as the data behind it.
    """
    if asset_type == ASSET_PRODUCT:
        row = fetch_one(
            connection,
            "SELECT coalesce(t.rank_order, 0) AS rank, "
            "       (SELECT count(DISTINCT g.principal_id) FROM entitlement_grant g "
            "        WHERE g.asset_id = p.product_id AND g.revoked_at IS NULL "
            "          AND g.expires_at > now()) AS consumers, "
            "       (SELECT coalesce(array_agg(DISTINCT a.agent_id), '{}') "
            "        FROM agent_product_binding b "
            "        JOIN agent_version v ON v.agent_version_id = b.agent_version_id "
            "        JOIN agent a ON a.current_version_id = v.agent_version_id "
            "        WHERE b.product_id = p.product_id) AS agents "
            "FROM data_product p "
            "LEFT JOIN sensitivity_tier t ON t.code = p.sensitivity_tier "
            "WHERE p.product_id = %s",
            (asset_id,),
        )
        if row is None:
            raise IncidentRefusedError(f"no data product {asset_id}")
        return BlastRadius(
            consumers=int(row["consumers"]),
            sensitivity_rank=int(row["rank"]),
            products=(asset_id,),
            agents=tuple(row["agents"]),
        )

    row = fetch_one(
        connection,
        "SELECT coalesce(max(t.rank_order), 0) AS rank, "
        "       coalesce(array_agg(DISTINCT b.product_id) "
        "                FILTER (WHERE b.product_id IS NOT NULL), '{}') AS products, "
        "       (SELECT count(DISTINCT i.principal_id) FROM agent_interaction i "
        "        WHERE i.agent_version_id = v.agent_version_id) AS consumers "
        "FROM agent a "
        "JOIN agent_version v ON v.agent_version_id = a.current_version_id "
        "LEFT JOIN agent_product_binding b ON b.agent_version_id = v.agent_version_id "
        "LEFT JOIN data_product p ON p.product_id = b.product_id "
        "LEFT JOIN sensitivity_tier t ON t.code = p.sensitivity_tier "
        "WHERE a.agent_id = %s GROUP BY v.agent_version_id",
        (asset_id,),
    )
    if row is None:
        raise IncidentRefusedError(f"no agent {asset_id}")
    return BlastRadius(
        consumers=int(row["consumers"]),
        sensitivity_rank=int(row["rank"]),
        products=tuple(row["products"]),
        agents=(asset_id,),
    )


def compute_severity(
    rubric: Rubric, radius: BlastRadius, *, guarantee_breached: str | None
) -> tuple[str, dict[str, Any]]:
    """The band, and the inputs that produced it.

    Bands are ordered most severe first and the first whose floors are all met
    wins. A breached guarantee escalates by the configured number of bands: a
    promise broken is worse than a number moving, and the estate said so in the
    contract before anything went wrong.
    """
    bands = rubric.payload["severity"]["bands"]
    index = len(bands) - 1
    for position, band in enumerate(bands):
        if (
            radius.consumers >= band["min_consumers"]
            and radius.sensitivity_rank >= band["min_sensitivity_rank"]
        ):
            index = position
            break

    escalated = index
    if guarantee_breached:
        escalated = max(0, index - int(rubric.number(ESCALATE_PATH)))

    chosen = bands[escalated]
    return chosen["code"], {
        "consumers": radius.consumers,
        "sensitivity_rank": radius.sensitivity_rank,
        "guarantee_breached": guarantee_breached,
        "band_before_escalation": bands[index]["code"],
        "band": chosen["code"],
        "response_minutes": chosen["response_minutes"],
        "rubric_version_id": rubric.rubric_version_id,
    }


def _incident_id(finding: Finding, at: datetime) -> str:
    return f"INC-{finding.asset_id}-{finding.signal}-{at:%Y%m%d}"


def _write_impacts(
    connection: psycopg.Connection[Any],
    tenant: str,
    incident_id: str,
    radius: BlastRadius,
    *,
    banner: bool,
    at: datetime,
    refresh: bool,
) -> None:
    """Record one impact row per affected asset, notified and bannered.

    ``refresh`` decides what happens to a row that is already there: on a fresh
    raise the notification is restated, and on a re-raise of an incident that is
    already open it is left alone, so only consumers that were not there before
    are notified now.
    """
    conflict = (
        "ON CONFLICT (impact_id) DO UPDATE SET notified_at = EXCLUDED.notified_at, "
        "  banner_active = EXCLUDED.banner_active"
        if refresh
        else "ON CONFLICT (impact_id) DO NOTHING"
    )
    for asset_type, assets in (
        (ASSET_PRODUCT, radius.products), (ASSET_AGENT, radius.agents)
    ):
        for affected in assets:
            connection.execute(
                "INSERT INTO incident_impact (impact_id, tenant_id, incident_id, "
                "  affected_asset_type, affected_asset_id, consumer_count, notified_at, "
                "  banner_active) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) " + conflict,
                (
                    f"IMP-{incident_id}-{affected}", tenant, incident_id, asset_type,
                    affected, radius.consumers, at, banner,
                ),
            )


def raise_incident(
    connection: psycopg.Connection[Any],
    tenant: str,
    rubric: Rubric,
    finding: Finding,
    *,
    at: datetime | None = None,
) -> dict[str, Any]:
    """Open an incident from a finding, notify, and banner. In one transaction.

    Notification is not a separate step a caller can forget: an incident that
    exists without its consumers knowing is the failure mode this whole surface
    is built against, so the row and the notification are written together.
    """
    now = at or datetime.now(UTC)
    radius = blast_radius(connection, finding.asset_type, finding.asset_id)
    severity, inputs = compute_severity(
        rubric, radius, guarantee_breached=finding.guarantee_breached
    )
    incident_id = _incident_id(finding, now)

    existing = fetch_one(
        connection,
        "SELECT incident_id, status, severity, notified_at FROM incident "
        "WHERE incident_id = %s",
        (incident_id,),
    )
    banner = bool(rubric.flag(BANNER_PATH))

    if existing is not None and existing["status"] in OPEN_STATUSES:
        # The same signal on the same asset on the same day is one incident.
        # Raising a second would split the consumer notifications and make the
        # count of open incidents a measure of how often the scanner ran.
        #
        # The blast radius is still re-read and any consumer missing from it is
        # notified now: an agent bound to the product after the incident opened
        # is reading the same broken data as the rest, and the payload already
        # names it as impacted. Consumers already notified keep their original
        # timestamp, because the deadline runs from when they were first told.
        _write_impacts(
            connection, tenant, incident_id, radius, banner=banner, at=now, refresh=False
        )
        #
        # The same shape comes back either way. A caller that gets a thinner
        # payload on the second call has to branch on whether it was first,
        # which is a distinction it should not have to care about.
        return {
            "incident_id": incident_id,
            "severity": existing["severity"],
            "severity_inputs": inputs,
            "notified_at": existing["notified_at"],
            "impacted": [*radius.products, *radius.agents],
            "reopened": False,
            "already_open": True,
        }

    connection.execute(
        "INSERT INTO incident (incident_id, tenant_id, asset_type, asset_id, signal, "
        "  guarantee_breached, severity, severity_inputs, status, detected_at, notified_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (incident_id) DO UPDATE SET status = %s, resolved_at = NULL",
        (
            incident_id, tenant, finding.asset_type, finding.asset_id, finding.signal,
            finding.guarantee_breached, severity,
            json.dumps({**inputs, "finding": finding.document()}, default=str),
            STATUS_OPEN, now, now, STATUS_OPEN,
        ),
    )

    _write_impacts(connection, tenant, incident_id, radius, banner=banner, at=now, refresh=True)

    return {
        "incident_id": incident_id,
        "severity": severity,
        "severity_inputs": inputs,
        "notified_at": now,
        "impacted": [*radius.products, *radius.agents],
        "reopened": existing is not None,
        "already_open": False,
    }


def add_context(
    connection: psycopg.Connection[Any], *, incident_id: str, owner_context: str
) -> dict[str, Any]:
    """An owner's note, added alongside the notification — never instead of it.

    There is deliberately no parameter here that could clear `notified_at` or
    lower `banner_active`. Section 15.6: owners cannot suppress consumer
    notification; they can only add context.
    """
    if not owner_context.strip():
        raise IncidentRefusedError("context cannot be empty")
    connection.execute(
        "UPDATE incident SET owner_context = %s WHERE incident_id = %s",
        (owner_context, incident_id),
    )
    return {"incident_id": incident_id, "owner_context": owner_context}


def resolve(
    connection: psycopg.Connection[Any],
    *,
    incident_id: str,
    root_cause: str,
    at: datetime | None = None,
) -> dict[str, Any]:
    """Close an incident with its root cause. The cause is required.

    An incident resolved without one teaches the estate nothing, and the whole
    point of linking incidents permanently to an asset's quality history is that
    a consumer reading it later learns what happened and why.
    """
    if not root_cause.strip():
        raise IncidentRefusedError(
            "a root cause is required: an incident closed without one leaves the next "
            "reader of this asset's history none the wiser"
        )
    now = at or datetime.now(UTC)
    connection.execute(
        "UPDATE incident SET status = %s, resolved_at = %s, root_cause = %s "
        "WHERE incident_id = %s",
        (STATUS_RESOLVED, now, root_cause, incident_id),
    )
    connection.execute(
        "UPDATE incident_impact SET banner_active = false WHERE incident_id = %s",
        (incident_id,),
    )
    return {"incident_id": incident_id, "status": STATUS_RESOLVED, "resolved_at": now}


def open_incidents(
    connection: psycopg.Connection[Any], *, asset_id: str | None = None
) -> list[dict[str, Any]]:
    where = "AND i.asset_id = %s" if asset_id else ""
    return fetch_all(
        connection,
        "SELECT i.incident_id, i.asset_type, i.asset_id, i.signal, i.severity, "
        "       i.severity_inputs, i.status, i.guarantee_breached, i.detected_at, "
        "       i.notified_at, i.owner_context, "
        "       (SELECT count(*) FROM incident_impact m WHERE m.incident_id = i.incident_id) "
        "         AS impacted "
        f"FROM incident i WHERE i.status = ANY(%s) {where} "
        "ORDER BY i.severity, i.detected_at DESC",
        (list(OPEN_STATUSES), asset_id) if asset_id else (list(OPEN_STATUSES),),
    )


def banners(
    connection: psycopg.Connection[Any], asset_type: str, asset_id: str
) -> list[dict[str, Any]]:
    """What must be shown on this listing right now (M10.3).

    Upstream trust propagates: an incident on a product banners every agent
    bound to it, because a consumer reading the agent's page is relying on that
    product whether or not they know its name.
    """
    return fetch_all(
        connection,
        "SELECT i.incident_id, i.asset_type AS origin_type, i.asset_id AS origin_id, "
        "       i.signal, i.severity, i.guarantee_breached, i.detected_at, "
        "       i.owner_context, i.status "
        "FROM incident_impact m JOIN incident i ON i.incident_id = m.incident_id "
        "WHERE m.affected_asset_type = %s AND m.affected_asset_id = %s "
        "  AND m.banner_active AND i.status = ANY(%s) "
        "ORDER BY i.severity, i.detected_at DESC",
        (asset_type, asset_id, list(OPEN_STATUSES)),
    )


def overdue_notifications(
    connection: psycopg.Connection[Any], rubric: Rubric, *, at: datetime | None = None
) -> list[dict[str, Any]]:
    """Incidents whose consumers were not told inside the deadline.

    The M10 acceptance criterion is a time: a simulated freshness breach
    notifies consumers and banners every affected listing within five minutes.
    This is what makes that measurable rather than asserted.
    """
    deadline = int(rubric.number(DEADLINE_PATH))
    cutoff = (at or datetime.now(UTC)) - timedelta(minutes=deadline)
    return fetch_all(
        connection,
        "SELECT incident_id, asset_id, detected_at, notified_at FROM incident "
        "WHERE detected_at < %s AND (notified_at IS NULL OR notified_at > detected_at + "
        "      %s::interval) ORDER BY detected_at",
        (cutoff, f"{deadline} minutes"),
    )
