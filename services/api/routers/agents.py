"""`/api/v1/agents` — catalog, detail, the demo set, invocation and feedback.

The invocation route is the one the whole marketplace is judged by. Its four
outcomes are all part of the contract, not just the first:

* **200** an answer with its citations, its certified definitions and its trace;
* **403** the caller cannot invoke this agent, or cannot read what it needs —
  naming the missing scope and a pre-filled request;
* **422** out of scope, naming the boundary, the agents that do cover it, and a
  demand link;
* **424** the answer could not be grounded, so it was withheld.

Nothing here decides those; :mod:`services.agents.ask` does, and it does so in a
fixed order with grounding after the runtime and before serialisation.
"""

from __future__ import annotations

from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Body, Depends, Query

from services.agent_runtime import registry
from services.agents import ask as ask_service
from services.agents import catalog, feedback, theatre
from services.api.deps import request_connection, rubric_dependency, tenant
from services.common import http_status
from services.common.db import fetch_all, fetch_one
from services.common.principal import Principal, current_principal
from services.common.problem import bad_request, not_found, role_required
from services.common.rubrics import Rubric

router = APIRouter(prefix="/agents", tags=["agents"])

RankingRubric = Annotated[Rubric, Depends(rubric_dependency("catalog_ranking"))]
GovernanceRubric = Annotated[Rubric, Depends(rubric_dependency("governance"))]
Connection = Annotated[psycopg.Connection[Any], Depends(request_connection)]
Caller = Annotated[Principal, Depends(current_principal)]
Tenant = Annotated[str, Depends(tenant)]


def _version_id(connection: psycopg.Connection[Any], tenant_id: str, agent_id: str) -> str:
    from services.common.db import fetch_one

    row = fetch_one(
        connection,
        "SELECT current_version_id FROM agent WHERE agent_id = %s AND tenant_id = %s",
        (agent_id, tenant_id),
    )
    if row is None:
        raise not_found("agent", agent_id)
    return row["current_version_id"]


@router.get("", status_code=http_status.OK, summary="Filter and page the agent catalog")
def list_agents(
    connection: Connection,
    principal: Caller,
    tenant_id: Tenant,
    rubric: RankingRubric,
    industry: Annotated[list[str] | None, Query()] = None,
    domain: Annotated[list[str] | None, Query()] = None,
    autonomy: Annotated[list[str] | None, Query()] = None,
    certification: Annotated[list[str] | None, Query()] = None,
    kpi: Annotated[list[str] | None, Query()] = None,
    product: Annotated[list[str] | None, Query()] = None,
    sort: str = catalog.DEFAULT_SORT,
    cursor: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    page = catalog.list_agents(
        connection, tenant_id, principal, rubric,
        filters=catalog.AgentFilters(
            industry=industry, domain=domain, autonomy=autonomy,
            certification=certification, kpi=kpi, product=product,
        ),
        sort=sort, cursor=cursor, limit=limit,
    )
    return {**page.document(), "sort": sort, "sorts": sorted(catalog.SORTS)}


@router.get("/{agent_id}", status_code=http_status.OK, summary="Full agent listing")
def get_agent(
    agent_id: str, connection: Connection, principal: Caller, tenant_id: Tenant
) -> dict[str, Any]:
    card = catalog.get_agent(connection, tenant_id, agent_id, principal)
    if card is None:
        raise not_found("agent", agent_id)
    return {"card": card}


@router.get(
    "/{agent_id}/coverage",
    status_code=http_status.OK,
    summary="KPI coverage with evaluation accuracy and sample size",
)
def get_coverage(
    agent_id: str, connection: Connection, principal: Caller, tenant_id: Tenant
) -> dict[str, Any]:
    version_id = _version_id(connection, tenant_id, agent_id)
    return {
        "agent_id": agent_id,
        "agent_version_id": version_id,
        "coverage": catalog.coverage(connection, version_id),
    }


@router.get(
    "/{agent_id}/demo",
    status_code=http_status.OK,
    summary="Curated exchanges and their validation state",
)
def get_demo(
    agent_id: str,
    connection: Connection,
    principal: Caller,
    tenant_id: Tenant,
    governance: GovernanceRubric,
) -> dict[str, Any]:
    _version_id(connection, tenant_id, agent_id)
    exchanges = theatre.eligible(connection, governance, agent_id=agent_id)
    return {
        "agent_id": agent_id,
        "exchanges": [
            {
                "exchange_id": row["exchange_id"],
                "ordinal": row["ordinal"],
                "question": row["question"],
                "kpi_class": row["kpi_class"],
                "analysis_type": row["analysis_type"],
                "expected_shape": row["expected_shape"],
                "last_validated": row["last_validated"],
            }
            for row in exchanges
        ],
        # Stale exchanges are absent, not hidden: the count says how many the
        # agent has, so the page can say why fewer are playable.
        "eligible": len(exchanges),
        "max_validation_age_days": int(governance.number(theatre.MAX_AGE_PATH)),
    }


@router.post(
    "/{agent_id}/ask",
    status_code=http_status.OK,
    summary="Ask the agent a question and receive an answer with its trace",
)
def ask_agent(
    agent_id: str,
    connection: Connection,
    principal: Caller,
    tenant_id: Tenant,
    body: Annotated[dict[str, Any], Body()],
) -> dict[str, Any]:
    question = str(body.get("question") or "").strip()
    if not question:
        raise bad_request("question is required")
    tier = str(body.get("tier") or ask_service.TIER_DEMO)
    if tier not in ask_service.TIERS:
        raise bad_request(
            f"tier must be one of {', '.join(ask_service.TIERS)}", tier=tier
        )
    purpose = str(body.get("purpose") or "").strip()
    if not purpose:
        # Fail closed on a missing purpose (rule 7, section 11). A question with
        # no stated purpose cannot be audited afterwards.
        raise bad_request("purpose is required; an unattributable question is not answered")
    session_id = str(body.get("session_id") or "").strip()
    if not session_id:
        raise bad_request("session_id is required")

    result = ask_service.ask(
        connection,
        tenant_id,
        registry.build(connection),
        principal,
        agent_id,
        question=question,
        tier=tier,
        purpose=purpose,
        session_id=session_id,
        exchange_id=body.get("exchange_id"),
    )
    return result.document()


@router.post(
    "/{agent_id}/feedback",
    status_code=http_status.CREATED,
    summary="Accept or reject an answer; a rejected defect becomes an evaluation case",
)
def submit_feedback(
    agent_id: str,
    connection: Connection,
    principal: Caller,
    tenant_id: Tenant,
    body: Annotated[dict[str, Any], Body()],
) -> dict[str, Any]:
    interaction_id = str(body.get("interaction_id") or "").strip()
    if not interaction_id:
        raise bad_request("interaction_id is required")
    if "accepted" not in body:
        raise bad_request("accepted is required")

    recorded = feedback.record(
        connection,
        tenant_id,
        agent_id=agent_id,
        interaction_id=interaction_id,
        party_id=principal.party_id,
        accepted=bool(body["accepted"]),
        reason_code=str(body.get("reason_code") or "other"),
        reason_text=body.get("reason_text"),
    )
    return recorded.document()


@router.get(
    "/{agent_id}/evaluation",
    status_code=http_status.OK,
    summary="Suite results, pass rate and regression history",
)
def get_evaluation(
    agent_id: str, connection: Connection, principal: Caller, tenant_id: Tenant
) -> dict[str, Any]:
    from services.common.db import fetch_all

    _version_id(connection, tenant_id, agent_id)
    runs = fetch_all(
        connection,
        "SELECT eval_run_id, agent_version_ref, suite_results, pass_rate_pct, "
        "       groundedness_pct, threshold_pct, passed, started_at, finished_at "
        "FROM evaluation_run WHERE agent_id = %s ORDER BY finished_at DESC",
        (agent_id,),
    )
    return {
        "agent_id": agent_id,
        "current": runs[0] if runs else None,
        # History, oldest last: a pass rate means little without the run before it.
        "history": runs,
    }


# ---------------------------------------------------------------------------
# Release (M12.3)
# ---------------------------------------------------------------------------

EvaluationRubric = Annotated[Rubric, Depends(rubric_dependency("agent_evaluation"))]
ROLE_RELEASE = ("owner", "architect", "administrator")


def _releaser(principal: Caller) -> Principal:
    """Who may move a version between states.

    Deliberately narrower than who may read the registry and wider than the
    administrator role: an agent's owner releases their own agent, and an
    architect or administrator can act during an incident when the owner is
    asleep. A rollback nobody on call can perform is a rollback that does not
    happen.
    """
    if not principal.has_role(*ROLE_RELEASE):
        raise role_required(*ROLE_RELEASE)
    return principal


Releaser = Annotated[Principal, Depends(_releaser)]


@router.get(
    "/{agent_id}/release",
    status_code=http_status.OK,
    summary="What is live, what is in canary, and what a rollback would restore",
)
def release_state(
    connection: Connection, principal: Caller, agent_id: str, evaluation: EvaluationRubric
) -> dict[str, Any]:
    from services.agents import release

    live_id = _version_id(connection, tenant(), agent_id)
    live = release.bundle(connection, live_id)
    canaries = [
        release.bundle(connection, row["agent_version_id"]).document()
        for row in fetch_all(
            connection,
            "SELECT agent_version_id FROM agent_version "
            "WHERE agent_id = %s AND status = 'canary' ORDER BY semver",
            (agent_id,),
        )
    ]
    return {
        "agent_id": agent_id,
        "live": live.document(),
        "canaries": [
            {
                **canary,
                "evidence": release.canary_evidence(
                    connection, evaluation, agent_version_id=canary["agent_version_id"]
                ),
            }
            for canary in canaries
        ],
        # What a rollback would actually restore, before anyone asks for one.
        # "Roll back" is not a decision somebody should make without seeing the
        # bundle on the other side of it.
        "rollback_target": _rollback_target(connection, agent_id, live_id),
    }


def _rollback_target(
    connection: psycopg.Connection[Any], agent_id: str, live_id: str
) -> dict[str, Any] | None:
    from services.agents import release

    row = fetch_one(
        connection,
        "SELECT agent_version_id FROM agent_version "
        "WHERE agent_id = %s AND agent_version_id <> %s AND status IN ('retired', 'published') "
        "ORDER BY retired_at DESC NULLS LAST, published_at DESC NULLS LAST LIMIT 1",
        (agent_id, live_id),
    )
    if row is None:
        return None
    target = release.bundle(connection, row["agent_version_id"])
    live = release.bundle(connection, live_id)
    return {**target.document(), "changes": target.differences(live)}


@router.post(
    "/{agent_id}/rollback",
    status_code=http_status.OK,
    summary="Restore the previous bundle",
)
def rollback(
    connection: Connection,
    principal: Releaser,
    tenant_id: Tenant,
    governance: GovernanceRubric,
    agent_id: str,
    reason: Annotated[str, Body(embed=True)],
) -> dict[str, Any]:
    """One call. The previous bundle, entire, in one transaction.

    A reason is required and is not a formality: "rolled back" in an incident
    review is a fact with no cause, and the next person to ship that version
    will ship it for the reason nobody wrote down.
    """
    from services.agents import release

    try:
        return release.rollback(
            connection, tenant_id, governance,
            agent_id=agent_id, reason=reason, actor_party_id=principal.party_id,
        )
    except release.ReleaseRefused as error:
        raise bad_request(str(error), agent_id=agent_id) from None
