"""Executing a question, and deciding whether the answer may be sent.

This is where the marketplace's central promise is either kept or broken, so the
order of operations is the design:

1. resolve the caller and the agent version;
2. check the caller may invoke this agent at all — 403, naming the scope;
3. ask the runtime;
4. **validate grounding** — 424, and the answer is dropped, not annotated;
5. record the interaction;
6. only then serialise.

Step 4 is after the runtime and before serialisation because that is the only
placement that holds whichever runtime answered. It is also the only placement
where withholding is still possible: an answer already streamed to a client
cannot be unsent.

The refusals are as much a product as the answers. An out-of-scope refusal names
the boundary crossed, the agents that do cover the question, and a pre-filled
demand link, because a consumer who has been told "no" needs to know where "yes"
lives (section 10.2).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg

from services.agent_runtime.base import (
    Answer,
    AskRequest,
    EntitlementShortfall,
    OutOfScope,
    RuntimeUnavailable,
)
from services.agents import grounding
from services.common import http_status
from services.common.db import connect, fetch_all, fetch_one
from services.common.principal import Principal, held_scopes
from services.common.problem import (
    Problem,
    entitlement_missing,
    not_found,
    out_of_scope,
    ungrounded_answer,
)

INVOKE_SCOPE = "agent:{agent_id}:invoke"
SURFACE = "agent"
DEMAND_URL = "/requests/new/supply?question={question}&declined_by={agent_id}"

TIER_DEMO = "demo"
TIER_LIVE = "live"
TIERS = (TIER_DEMO, TIER_LIVE)

OUTCOME_ANSWERED = "answered"
OUTCOME_OUT_OF_SCOPE = "out_of_scope"
OUTCOME_UNGROUNDED = "ungrounded"
OUTCOME_DENIED = "denied"
OUTCOME_ERROR = "error"

EFFECTIVE_INTERSECTION = "intersection"
EFFECTIVE_DIRECT = "direct"


class RuntimeRefused(Problem):
    """The configured runtime could not answer, and nothing stood in for it."""

    def __init__(self, detail: str) -> None:
        super().__init__(
            http_status.SERVICE_UNAVAILABLE,
            "runtime_unavailable",
            detail,
        )


@dataclass(frozen=True)
class Asked:
    """An answer that has passed grounding, with the trace that produced it."""

    answer: Answer
    interaction_id: str
    tier: str
    agent_identity: str | None
    on_behalf_of: str | None

    def document(self) -> dict[str, Any]:
        body = self.answer.document()
        body["interaction_id"] = self.interaction_id
        body["grounded"] = True
        body["tier"] = self.tier
        body["scope"] = {
            "agent_identity": self.agent_identity,
            "on_behalf_of": self.on_behalf_of,
            "effective_scope": (
                EFFECTIVE_INTERSECTION if self.agent_identity else EFFECTIVE_DIRECT
            ),
        }
        return body


def _interaction_id(version_id: str) -> str:
    return f"INT-{version_id}-{datetime.now(UTC):%Y%m%d%H%M%S%f}"


def _record(
    tenant: str,
    *,
    interaction_id: str,
    version_id: str,
    request: AskRequest,
    question_class: str,
    outcome: str,
    answer: Answer | None,
    grounded: bool,
) -> None:
    # Telemetry is written on its own autocommit connection, deliberately.
    # A refused request rolls its transaction back — that is what a 403, a 422
    # or a 424 should do to any business write it attempted — and an interaction
    # recorded inside that transaction would roll back with it. The record of
    # what happened must outlive the outcome, or the owner cannot count the
    # answers that were withheld, which are the ones most worth counting.
    with connect(tenant, autocommit=True) as telemetry:
        telemetry.execute(
            "INSERT INTO agent_interaction (interaction_id, tenant_id, agent_version_id, "
            "  principal_id, session_id, tier, question, question_class, purpose_code, "
            "  outcome, grounded, confidence, citations, kpi_definitions, tool_calls, "
            "  rows_scanned, latency_ms, tokens_in, tokens_out, cost_usd) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "        %s, %s, %s)",
            (
                interaction_id, tenant, version_id, request.principal_id, request.session_id,
                request.tier, request.question, question_class, request.purpose, outcome,
                grounded,
                answer.confidence if answer else None,
                json.dumps([c.document() for c in answer.citations]) if answer else "[]",
                list(answer.kpi_definitions) if answer else [],
                json.dumps([c.document() for c in answer.tool_calls]) if answer else "[]",
                answer.rows_scanned if answer else 0,
                answer.latency_ms if answer else 0,
                answer.tokens_in if answer else 0,
                answer.tokens_out if answer else 0,
                answer.cost_usd if answer else 0,
            ),
        )


def _covering(connection: psycopg.Connection[Any], agent_ids: list[str]) -> list[str]:
    if not agent_ids:
        return []
    rows = fetch_all(
        connection,
        "SELECT agent_id FROM agent WHERE agent_id = ANY(%s) ORDER BY agent_id",
        (agent_ids,),
    )
    return [row["agent_id"] for row in rows]


def ask(
    connection: psycopg.Connection[Any],
    tenant: str,
    runtime: Any,
    principal: Principal,
    agent_id: str,
    *,
    question: str,
    tier: str,
    purpose: str,
    session_id: str,
    exchange_id: str | None = None,
) -> Asked:
    version = fetch_one(
        connection,
        "SELECT a.agent_id, a.machine_identity, v.agent_version_id, v.analyses "
        "FROM agent a JOIN agent_version v ON v.agent_version_id = a.current_version_id "
        "WHERE a.agent_id = %s AND a.tenant_id = %s",
        (agent_id, tenant),
    )
    if version is None:
        raise not_found("agent", agent_id)

    scope = INVOKE_SCOPE.format(agent_id=agent_id)
    if scope not in held_scopes(connection, principal.party_id):
        raise entitlement_missing(scope, asset_id=agent_id, surface=SURFACE)

    version_id = version["agent_version_id"]
    interaction_id = _interaction_id(version_id)
    request = AskRequest(
        agent_id=agent_id,
        agent_version_id=version_id,
        question=question,
        tier=tier,
        purpose=purpose,
        session_id=session_id,
        principal_id=principal.party_id,
        on_behalf_of=principal.on_behalf_of,
        exchange_id=exchange_id,
    )
    question_class = exchange_id or "ad_hoc"

    try:
        answer = runtime.ask(connection, request)
    except OutOfScope as refusal:
        _record(
            tenant, interaction_id=interaction_id, version_id=version_id,
            request=request, question_class=question_class, outcome=OUTCOME_OUT_OF_SCOPE,
            answer=None, grounded=False,
        )
        raise out_of_scope(
            refusal.detail,
            suggested_agents=_covering(connection, refusal.suggested_agents),
            file_demand_url=DEMAND_URL.format(question=question, agent_id=agent_id),
        ) from refusal
    except EntitlementShortfall as refusal:
        _record(
            tenant, interaction_id=interaction_id, version_id=version_id,
            request=request, question_class=question_class, outcome=OUTCOME_DENIED,
            answer=None, grounded=False,
        )
        raise entitlement_missing(
            refusal.required_scope, asset_id=refusal.asset_id, surface=SURFACE
        ) from refusal
    except RuntimeUnavailable as failure:
        _record(
            tenant, interaction_id=interaction_id, version_id=version_id,
            request=request, question_class=question_class, outcome=OUTCOME_ERROR,
            answer=None, grounded=False,
        )
        raise RuntimeRefused(str(failure)) from failure

    # Step 4. Nothing below this line runs on an answer that fails.
    verdict = grounding.check(answer)
    _record(
        tenant, interaction_id=interaction_id, version_id=version_id,
        request=request, question_class=question_class,
        outcome=OUTCOME_ANSWERED if verdict.grounded else OUTCOME_UNGROUNDED,
        answer=answer, grounded=verdict.grounded,
    )
    if not verdict.grounded:
        # The interaction is recorded and the answer is discarded. An ungrounded
        # answer that nobody can see is still something the owner must be able
        # to count.
        raise ungrounded_answer(verdict.uncited_count)

    return Asked(
        answer=answer,
        interaction_id=interaction_id,
        tier=tier,
        agent_identity=version["machine_identity"] if principal.is_delegated else None,
        on_behalf_of=principal.on_behalf_of,
    )
