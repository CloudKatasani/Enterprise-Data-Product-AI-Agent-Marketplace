"""`/api/v1/observability` and `/api/v1/value` — the health and money planes.

The banner endpoint is the one every other surface depends on: a product page,
an agent page and the catalog card all ask it what must be shown, and upstream
trust propagates through it (M10.3). An agent whose data product is late is
banner-ed on its own listing, because a consumer reading the agent page is
relying on that product whether or not they know its name.

The board pack endpoint reads a stored snapshot and refuses to compute one. If
it recomputed, the pack and the dashboard would be two opinions with equal
authority, and the meeting where they disagree is the meeting that ends trust in
both.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Body, Depends, Query, Response

from services.api.deps import request_connection, rubric_dependency, tenant
from services.common import http_status
from services.common.principal import Principal, current_principal
from services.common.problem import bad_request, not_found
from services.common.rubrics import Rubric
from services.observability import incidents, signals
from services.value import finops, model

router = APIRouter(prefix="/observability", tags=["observability"])
value_router = APIRouter(prefix="/value", tags=["value"])

Connection = Annotated[psycopg.Connection[Any], Depends(request_connection)]
Caller = Annotated[Principal, Depends(current_principal)]
Tenant = Annotated[str, Depends(tenant)]
Watch = Annotated[Rubric, Depends(rubric_dependency("observability"))]
ValueRubric = Annotated[Rubric, Depends(rubric_dependency("value_model"))]
FinOps = Annotated[Rubric, Depends(rubric_dependency("finops"))]

WINDOW_PATH = "reporting.default_window_days"
MARKDOWN = "text/markdown; charset=utf-8"


@router.get("", status_code=http_status.OK, summary="The health plane")
def health_plane(
    connection: Connection, principal: Caller, tenant_id: Tenant, watch: Watch
) -> dict[str, Any]:
    findings = signals.scan(connection, watch)
    return {
        "findings": [finding.document() for finding in findings],
        "incidents": incidents.open_incidents(connection),
        "overdue_notifications": incidents.overdue_notifications(connection, watch),
        "signals": {
            "product": list(signals.PRODUCT_SIGNALS),
            "agent": list(signals.AGENT_SIGNALS),
        },
        "rubric_version_id": watch.rubric_version_id,
    }


@router.get(
    "/banners",
    status_code=http_status.OK,
    summary="What must be shown on this listing right now",
)
def listing_banners(
    connection: Connection,
    principal: Caller,
    tenant_id: Tenant,
    asset_type: str,
    asset_id: str,
) -> dict[str, Any]:
    if asset_type not in {signals.ASSET_PRODUCT, signals.ASSET_AGENT}:
        raise bad_request(
            f"asset_type must be {signals.ASSET_PRODUCT} or {signals.ASSET_AGENT}"
        )
    return {
        "asset_type": asset_type,
        "asset_id": asset_id,
        # Owners cannot suppress these. They appear because an incident is open
        # and they clear when it resolves.
        "banners": incidents.banners(connection, asset_type, asset_id),
    }


@router.post(
    "/scan",
    status_code=http_status.OK,
    summary="Run the detectors and raise incidents for what they find",
)
def scan_and_raise(
    connection: Connection,
    principal: Caller,
    tenant_id: Tenant,
    watch: Watch,
    only: Annotated[list[str] | None, Query()] = None,
) -> dict[str, Any]:
    findings = signals.scan(connection, watch, only=only)
    raised = [
        incidents.raise_incident(connection, tenant_id, watch, finding)
        for finding in findings
    ]
    return {
        "scanned": len(findings),
        "raised": raised,
        "findings": [finding.document() for finding in findings],
    }


@router.post(
    "/incidents/{incident_id}/context",
    status_code=http_status.OK,
    summary="Add owner context. It cannot suppress consumer notification.",
)
def add_context(
    incident_id: str,
    connection: Connection,
    principal: Caller,
    tenant_id: Tenant,
    body: Annotated[dict[str, Any], Body()],
) -> dict[str, Any]:
    try:
        return incidents.add_context(
            connection, incident_id=incident_id,
            owner_context=str(body.get("owner_context") or ""),
        )
    except incidents.IncidentRefusedError as error:
        raise bad_request(str(error)) from error


@router.post(
    "/incidents/{incident_id}/resolve",
    status_code=http_status.OK,
    summary="Resolve with a root cause. The cause is required.",
)
def resolve_incident(
    incident_id: str,
    connection: Connection,
    principal: Caller,
    tenant_id: Tenant,
    body: Annotated[dict[str, Any], Body()],
) -> dict[str, Any]:
    try:
        return incidents.resolve(
            connection, incident_id=incident_id,
            root_cause=str(body.get("root_cause") or ""),
        )
    except incidents.IncidentRefusedError as error:
        raise bad_request(str(error)) from error


# ---------------------------------------------------------------------------
# Value and FinOps
# ---------------------------------------------------------------------------


def _window(rubric: Rubric, days: int | None) -> date:
    """The reporting window. Its default is the rubric's, not the route's."""
    span = days or int(rubric.number(WINDOW_PATH))
    return (datetime.now(UTC) - timedelta(days=span)).date()


@value_router.get("", status_code=http_status.OK, summary="The value plane")
def value_plane(
    connection: Connection,
    principal: Caller,
    tenant_id: Tenant,
    rubric: ValueRubric,
    costs: FinOps,
    days: int | None = None,
) -> dict[str, Any]:
    since = _window(rubric, days)
    return {
        "since": since,
        "portfolio": [
            item.document() for item in model.portfolio(connection, rubric, since=since)
        ],
        "unit_economics": [
            item.document() for item in finops.unit_economics(connection, costs, since=since)
        ],
        "budgets": finops.budgets(connection, costs),
        "retirement_candidates": finops.retirement_candidates(connection, costs),
        "demo_tier_share": finops.demo_tier_share(connection, costs),
        "costs": finops.snapshot_costs(connection, since=since),
        "rubric_version_id": rubric.rubric_version_id,
    }


@value_router.post(
    "/snapshot",
    status_code=http_status.CREATED,
    summary="Compute the portfolio once and record it",
)
def take_snapshot(
    connection: Connection,
    principal: Caller,
    tenant_id: Tenant,
    rubric: ValueRubric,
    costs: FinOps,
    days: int | None = None,
) -> dict[str, Any]:
    since = _window(rubric, days)
    finops.attribute_agent_costs(connection, tenant_id, costs, since=since)
    return model.snapshot(
        connection, tenant_id, rubric,
        period_start=since, period_end=datetime.now(UTC).date(),
    )


@value_router.get(
    "/board-pack/{snapshot_ref}",
    status_code=http_status.OK,
    summary="The board pack, read from the stored snapshot and never recomputed",
)
def board_pack(
    snapshot_ref: str,
    connection: Connection,
    principal: Caller,
    tenant_id: Tenant,
    rubric: ValueRubric,
    fmt: str = "json",
) -> Any:
    try:
        pack = model.board_pack(connection, rubric, snapshot_ref)
    except LookupError as error:
        raise not_found("value snapshot", snapshot_ref) from error

    if fmt == "markdown":
        return Response(content=model.render_board_pack(pack), media_type=MARKDOWN)
    return pack
