"""`/api/v1/requests` and `/api/v1/demand` — the workflow rails (section 14).

The route that matters most is the one that runs *before* submission:
`POST /requests/access/evaluate` returns the path, the approvers, the SLA and
any block with its alternatives, and the form renders exactly that. The engine
runs the same evaluator at submission, so what the consumer was shown is what
happens.

Every state-changing route names its actor from the authenticated principal.
There is no route that accepts an actor in the body: a decision attributed to
whoever the caller says made it is not an audit record.
"""

from __future__ import annotations

from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Body, Depends, Query

from services.api.deps import request_connection, rubric_dependency, tenant
from services.common import http_status
from services.common.principal import Principal, current_principal
from services.common.problem import Problem, bad_request, not_found
from services.common.rubrics import Rubric
from services.search import embedding
from services.workflow import access, assessment, demand, engine, enhancement, policy

router = APIRouter(prefix="/requests", tags=["requests"])
demand_router = APIRouter(prefix="/demand", tags=["demand"])

Connection = Annotated[psycopg.Connection[Any], Depends(request_connection)]
Caller = Annotated[Principal, Depends(current_principal)]
Tenant = Annotated[str, Depends(tenant)]
Governance = Annotated[Rubric, Depends(rubric_dependency("governance"))]
DemandRubric = Annotated[Rubric, Depends(rubric_dependency("demand_scoring"))]
SearchRubric = Annotated[Rubric, Depends(rubric_dependency("semantic_search"))]


class WorkflowRefused(Problem):
    """A workflow rule stopped this. The detail is what the consumer reads."""

    def __init__(self, detail: str, **extra: Any) -> None:
        super().__init__(http_status.CONFLICT, "workflow_refused", detail, **extra)


def _required(body: dict[str, Any], *names: str) -> tuple[Any, ...]:
    missing = [name for name in names if not str(body.get(name) or "").strip()]
    if missing:
        raise bad_request("required: " + ", ".join(missing))
    return tuple(body[name] for name in names)


# ---------------------------------------------------------------------------
# Access
# ---------------------------------------------------------------------------


@router.post(
    "/access/evaluate",
    status_code=http_status.OK,
    summary="What will happen to this request, before it is submitted",
)
def evaluate_access(
    connection: Connection,
    principal: Caller,
    tenant_id: Tenant,
    body: Annotated[dict[str, Any], Body()],
) -> dict[str, Any]:
    asset_type, asset_id, purpose_code = _required(
        body, "asset_type", "asset_id", "purpose_code"
    )
    try:
        evaluation = policy.evaluate(
            connection,
            asset_type=asset_type,
            asset_id=asset_id,
            requester_party_id=principal.party_id,
            purpose_code=purpose_code,
        )
    except policy.PolicyUnavailableError as error:
        raise not_found("asset", str(asset_id)) from error
    return evaluation.document()


@router.post(
    "/access",
    status_code=http_status.CREATED,
    summary="Draft an access request; it is evaluated on creation",
)
def create_access(
    connection: Connection,
    principal: Caller,
    tenant_id: Tenant,
    body: Annotated[dict[str, Any], Body()],
) -> dict[str, Any]:
    asset_type, asset_id, purpose_code, purpose_text = _required(
        body, "asset_type", "asset_id", "purpose_code", "purpose_text"
    )
    request_id = str(body.get("request_id") or "").strip()
    if not request_id:
        raise bad_request("request_id is required")
    try:
        return access.create(
            connection,
            tenant_id,
            request_id=request_id,
            requester_party_id=principal.party_id,
            asset_type=asset_type,
            asset_id=asset_id,
            columns=list(body.get("columns") or []),
            purpose_code=purpose_code,
            purpose_text=purpose_text,
            title=body.get("title"),
        )
    except policy.PolicyUnavailableError as error:
        raise not_found("asset", str(asset_id)) from error


@router.post(
    "/access/{request_id}/submit",
    status_code=http_status.OK,
    summary="Submit an evaluated request; a blocked one is refused",
)
def submit_access(
    request_id: str,
    connection: Connection,
    principal: Caller,
    tenant_id: Tenant,
    governance: Governance,
) -> dict[str, Any]:
    try:
        return access.submit(
            connection, tenant_id, request_id=request_id, actor=principal.party_id,
            governance=governance,
        )
    except access.RequestRefusedError as error:
        raise WorkflowRefused(str(error)) from error
    except engine.WorkflowNotFoundError as error:
        raise not_found("request", request_id) from error


@router.post(
    "/access/{request_id}/decide",
    status_code=http_status.OK,
    summary="Record one approver's decision",
)
def decide_access(
    request_id: str,
    connection: Connection,
    principal: Caller,
    tenant_id: Tenant,
    governance: Governance,
    body: Annotated[dict[str, Any], Body()],
) -> dict[str, Any]:
    outcome = str(body.get("outcome") or "").strip()
    if outcome not in {
        access.OUTCOME_APPROVED, access.OUTCOME_PARTIAL, access.OUTCOME_DECLINED
    }:
        raise bad_request(
            "outcome must be approve, partial or decline", outcome=outcome
        )
    try:
        return access.decide(
            connection, tenant_id, request_id=request_id,
            approver_party_id=principal.party_id, outcome=outcome,
            reason=str(body.get("reason") or ""),
            granted_columns=body.get("granted_columns"),
            governance=governance,
        )
    except access.RequestRefusedError as error:
        raise WorkflowRefused(str(error)) from error
    except engine.WorkflowNotFoundError as error:
        raise not_found("request", request_id) from error


@router.get(
    "/{request_id}/history",
    status_code=http_status.OK,
    summary="Every transition, in order, with its actor",
)
def request_history(
    request_id: str, connection: Connection, principal: Caller, tenant_id: Tenant,
    workflow: str = engine.TYPE_ACCESS,
) -> dict[str, Any]:
    if workflow not in engine.TRANSITIONS:
        raise bad_request(
            "workflow must be one of " + ", ".join(sorted(engine.TRANSITIONS))
        )
    try:
        instance = engine.load(connection, workflow, request_id)
    except engine.WorkflowNotFoundError as error:
        raise not_found("request", request_id) from error
    return {
        **instance.document(),
        "history": engine.history(connection, workflow, request_id),
    }


# ---------------------------------------------------------------------------
# The register and the audit export (M8.5)
# ---------------------------------------------------------------------------


@router.get(
    "/entitlements",
    status_code=http_status.OK,
    summary="The entitlement register: who holds what, for what, until when",
)
def entitlement_register(
    connection: Connection,
    principal: Caller,
    tenant_id: Tenant,
    governance: Governance,
    principal_id: str | None = None,
    mine: bool = False,
) -> dict[str, Any]:
    subject = principal.party_id if mine else principal_id
    rules = policy.load_rules(connection)[1]
    return {
        "grants": access.register(connection, principal_id=subject),
        "expiring": access.expiring(connection, rules),
        "expired": access.expired(connection),
        "dormant": access.dormant(connection, rules),
    }


@router.get(
    "/audit.ndjson",
    status_code=http_status.OK,
    summary="The audit trail as newline-delimited JSON",
)
def audit_export(
    connection: Connection,
    principal: Caller,
    tenant_id: Tenant,
    event: Annotated[list[str] | None, Query()] = None,
) -> dict[str, Any]:
    return {"ndjson": access.audit_export(connection, event_names=event)}


# ---------------------------------------------------------------------------
# Enhancement
# ---------------------------------------------------------------------------


@router.post(
    "/enhancement",
    status_code=http_status.CREATED,
    summary="Raise an enhancement request against an asset",
)
def create_enhancement(
    connection: Connection,
    principal: Caller,
    tenant_id: Tenant,
    rubric: DemandRubric,
    body: Annotated[dict[str, Any], Body()],
) -> dict[str, Any]:
    request_id, asset_id, title, description = _required(
        body, "request_id", "asset_id", "title", "body"
    )
    return enhancement.submit(
        connection, tenant_id, rubric, request_id=request_id,
        requester_party_id=principal.party_id,
        asset_type=str(body.get("asset_type") or "data_product"),
        asset_id=asset_id, title=title, body=description,
    )


@router.post(
    "/enhancement/{request_id}/advance",
    status_code=http_status.OK,
    summary="Move an enhancement request along its lifecycle",
)
def advance_enhancement(
    request_id: str,
    connection: Connection,
    principal: Caller,
    tenant_id: Tenant,
    body: Annotated[dict[str, Any], Body()],
) -> dict[str, Any]:
    to_state = str(body.get("to_state") or "").strip()
    if not to_state:
        raise bad_request("to_state is required")
    try:
        return enhancement.advance(
            connection, tenant_id, request_id=request_id, to_state=to_state,
            actor=principal.party_id, reason_code=body.get("reason_code"),
            reason_text=body.get("reason_text"), merge_into=body.get("merge_into"),
        )
    except (enhancement.EnhancementRefusedError, engine.IllegalTransitionError) as error:
        raise WorkflowRefused(str(error)) from error
    except engine.WorkflowNotFoundError as error:
        raise not_found("request", request_id) from error


@router.get(
    "/backlog",
    status_code=http_status.OK,
    summary="The public backlog, declines included with their reasons",
)
def public_backlog(
    connection: Connection,
    principal: Caller,
    tenant_id: Tenant,
    rubric: DemandRubric,
    asset_id: str | None = None,
) -> dict[str, Any]:
    return {
        "items": enhancement.backlog(connection, asset_id=asset_id),
        "overdue": enhancement.overdue(connection),
        "unverified": enhancement.unverified(connection, rubric),
        "sla": enhancement.sla_board(connection),
    }


# ---------------------------------------------------------------------------
# Demand
# ---------------------------------------------------------------------------


@demand_router.post(
    "/check",
    status_code=http_status.OK,
    summary="Does the estate already supply this? Run before submitting.",
)
def check_demand(
    connection: Connection,
    principal: Caller,
    tenant_id: Tenant,
    rubric: DemandRubric,
    search: SearchRubric,
    body: Annotated[dict[str, Any], Body()],
) -> dict[str, Any]:
    text = str(body.get("text") or "").strip()
    if not text:
        raise bad_request("text is required")
    embedding.configure_from_rubric(search)
    return demand.check_duplicates(
        connection, rubric, request_text=text,
        entities=body.get("entities"), sources=body.get("sources"),
        kpis=body.get("kpis"),
    ).document()


@demand_router.post(
    "/assess",
    status_code=http_status.OK,
    summary="Can the estate already answer this? Run before filing new demand.",
)
def assess_demand(
    connection: Connection,
    principal: Caller,
    tenant_id: Tenant,
    rubric: DemandRubric,
    search: SearchRubric,
    body: Annotated[dict[str, Any], Body()],
) -> dict[str, Any]:
    """Coverage, candidates and a recommendation, from the KPIs and questions asked.

    Distinct from ``/check``, which asks whether a request *reads like* something
    that exists. This asks whether the estate can already *answer* it, which is a
    fact about the coverage map rather than a similarity between two texts. Both
    run before anything is filed, and the intake shows them together.
    """
    kind = str(body.get("kind") or assessment.KIND_PRODUCT).strip()
    if kind not in assessment.KINDS:
        raise bad_request(f"kind must be one of {', '.join(assessment.KINDS)}")
    text = str(body.get("text") or "").strip()

    embedding.configure_from_rubric(search)
    verdict = assessment.assess(
        connection, rubric, kind=kind,
        kpis=body.get("kpis"), questions=body.get("questions"),
    )
    duplicates = (
        demand.check_duplicates(
            connection, rubric, request_text=text,
            entities=body.get("entities"), sources=body.get("sources"),
            kpis=body.get("kpis"), kind=kind,
        ).document()
        if text
        else None
    )
    return {"assessment": verdict.document(), "duplicates": duplicates}


@demand_router.post(
    "", status_code=http_status.CREATED, summary="File new-supply demand"
)
def submit_demand(
    connection: Connection,
    principal: Caller,
    tenant_id: Tenant,
    rubric: DemandRubric,
    search: SearchRubric,
    body: Annotated[dict[str, Any], Body()],
) -> dict[str, Any]:
    demand_id, request_id, title, description = _required(
        body, "demand_id", "request_id", "title", "body"
    )
    embedding.configure_from_rubric(search)
    return demand.submit(
        connection, tenant_id, rubric, demand_id=demand_id, request_id=request_id,
        requester_party_id=principal.party_id, title=title, body=description,
        entities=body.get("entities"), sources=body.get("sources"),
        kpis=body.get("kpis"),
    )


@demand_router.post(
    "/{demand_id}/vote",
    status_code=http_status.CREATED,
    summary="Vote, with the one-line use case that makes it countable",
)
def vote_demand(
    demand_id: str,
    connection: Connection,
    principal: Caller,
    tenant_id: Tenant,
    body: Annotated[dict[str, Any], Body()],
) -> dict[str, Any]:
    try:
        return demand.vote(
            connection, tenant_id, demand_id=demand_id,
            voter_party_id=principal.party_id,
            use_case=str(body.get("use_case") or ""),
        )
    except demand.DemandRefusedError as error:
        raise bad_request(str(error)) from error


@demand_router.get(
    "", status_code=http_status.OK, summary="The public demand board"
)
def demand_board(
    connection: Connection, principal: Caller, tenant_id: Tenant, rubric: DemandRubric
) -> dict[str, Any]:
    from services.common.db import fetch_all

    items = fetch_all(
        connection,
        "SELECT d.demand_id, d.state, d.score, d.score_breakdown, d.theme_id, "
        "       d.decline_reason_public, r.title, r.body, r.requester_party_id, "
        "       r.submitted_at, "
        "       count(v.vote_id) AS votes, count(DISTINCT v.org_unit_id) AS teams "
        "FROM demand_item d JOIN request r ON r.request_id = d.request_id "
        "LEFT JOIN demand_vote v ON v.demand_id = d.demand_id "
        "GROUP BY d.demand_id, d.state, d.score, d.score_breakdown, d.theme_id, "
        "         d.decline_reason_public, r.title, r.body, r.requester_party_id, "
        "         r.submitted_at "
        "ORDER BY votes DESC, d.score DESC NULLS LAST, r.submitted_at DESC",
    )
    themes = fetch_all(
        connection,
        "SELECT theme_id, label, summary, distinct_team_count, escalated_at, confidence, "
        "       rationale FROM demand_theme ORDER BY distinct_team_count DESC, label",
    )
    return {"items": items, "themes": themes}
