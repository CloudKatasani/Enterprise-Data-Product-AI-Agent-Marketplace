"""Canary release and rollback (M12.3, section 29).

The acceptance criterion is one sentence: a rollback restores the previous
bundle in one action. Both halves of that are load-bearing.

**The previous bundle**, not the previous prompt. A version here is the whole
configuration — prompt artifact, model provider and id, model parameters,
guardrails, coverage map, product and tool bindings, budgets and the evaluation
run that cleared it. Restoring a subset of those restores a version that never
existed, and an agent running last week's prompt against this week's bindings is
a configuration nobody has ever evaluated.

**One action**, because a rollback happens during an incident. Anything that
needs three steps in order will be done in the wrong order at 3am by somebody
reading a runbook on a phone.

Both follow from versions being immutable. The previous bundle is still sitting
there as rows; rolling back is pointing at it again, which is why it can be
atomic and why nothing has to be reconstructed.

Promotion is the opposite of urgent and is treated accordingly. A canary is
promoted on evidence from real traffic — a minimum number of answers over a
minimum number of hours — and a request to promote early is refused with what is
still missing rather than a warning somebody clicks through.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import psycopg

from services.common import audit
from services.common.db import fetch_all, fetch_one
from services.common.rubrics import Rubric
from services.common.timing import HOUR

STATUS_DRAFT = "draft"
STATUS_CANARY = "canary"
STATUS_PUBLISHED = "published"
STATUS_RETIRED = "retired"

EVENT_CANARY = "agent_version.canary"
EVENT_PROMOTED = "agent_version.promoted"
EVENT_ROLLED_BACK = "agent_version.rolled_back"

TRAFFIC_PATH = "canary.traffic_pct"
MIN_ANSWERS_PATH = "canary.min_answers"
MIN_HOURS_PATH = "canary.min_hours"

ZERO = Decimal(0)


class ReleaseRefused(RuntimeError):
    """A release step that cannot be taken, with what is missing."""


@dataclass(frozen=True)
class Bundle:
    """Everything a version is. Restored together or not at all."""

    agent_version_id: str
    agent_id: str
    semver: str
    status: str
    model_provider: str
    model_id: str
    model_params: dict[str, Any]
    prompt_hash: str
    guardrail_config: dict[str, Any]
    autonomy_level: str
    budget_p95_latency_ms: int
    budget_cost_per_answer_usd: Decimal
    eval_run_id: str | None
    coverage: tuple[str, ...]
    products: tuple[str, ...]
    tools: tuple[str, ...]

    def document(self) -> dict[str, Any]:
        return {
            "agent_version_id": self.agent_version_id,
            "agent_id": self.agent_id,
            "semver": self.semver,
            "status": self.status,
            "model": {
                "provider": self.model_provider,
                "id": self.model_id,
                "params": self.model_params,
            },
            "prompt_hash": self.prompt_hash,
            "guardrails": self.guardrail_config,
            "autonomy_level": self.autonomy_level,
            "budgets": {
                "p95_latency_ms": self.budget_p95_latency_ms,
                "cost_per_answer_usd": float(self.budget_cost_per_answer_usd),
            },
            "eval_run_id": self.eval_run_id,
            "coverage": list(self.coverage),
            "products": list(self.products),
            "tools": list(self.tools),
        }

    def differences(self, other: Bundle) -> list[str]:
        """What changed between two bundles, in the words an operator needs.

        Shown on a rollback so the record says what was actually restored — not
        "rolled back to 1.0.0", which is true and tells an incident review
        nothing.
        """
        changes: list[str] = []
        if (self.model_provider, self.model_id) != (other.model_provider, other.model_id):
            changes.append(
                f"model {other.model_provider}/{other.model_id} → "
                f"{self.model_provider}/{self.model_id}"
            )
        if self.model_params != other.model_params:
            changes.append("model parameters")
        if self.prompt_hash != other.prompt_hash:
            changes.append(f"prompt {other.prompt_hash[:len('0123456789ab')]} → "
                           f"{self.prompt_hash[:len('0123456789ab')]}")
        if self.guardrail_config != other.guardrail_config:
            changes.append("guardrails")
        if self.autonomy_level != other.autonomy_level:
            changes.append(f"autonomy {other.autonomy_level} → {self.autonomy_level}")
        if set(self.coverage) != set(other.coverage):
            changes.append("coverage map")
        if set(self.products) != set(other.products):
            changes.append("product bindings")
        if set(self.tools) != set(other.tools):
            changes.append("tool bindings")
        if (self.budget_p95_latency_ms, self.budget_cost_per_answer_usd) != (
            other.budget_p95_latency_ms, other.budget_cost_per_answer_usd
        ):
            changes.append("budgets")
        return changes


def bundle(connection: psycopg.Connection[Any], agent_version_id: str) -> Bundle:
    row = fetch_one(
        connection,
        "SELECT * FROM agent_version WHERE agent_version_id = %s", (agent_version_id,)
    )
    if row is None:
        raise ReleaseRefused(f"no agent version {agent_version_id}")

    coverage = tuple(
        entry["kpi_id"]
        for entry in fetch_all(
            connection,
            "SELECT kpi_id FROM agent_kpi_coverage WHERE agent_version_id = %s "
            "ORDER BY kpi_id",
            (agent_version_id,),
        )
    )
    products = tuple(
        entry["product_id"]
        for entry in fetch_all(
            connection,
            "SELECT product_id FROM agent_product_binding WHERE agent_version_id = %s "
            "ORDER BY product_id",
            (agent_version_id,),
        )
    )
    tools = tuple(
        entry["tool_name"]
        for entry in fetch_all(
            connection,
            "SELECT tool_name FROM agent_tool_binding WHERE agent_version_id = %s "
            "ORDER BY tool_name",
            (agent_version_id,),
        )
    )
    return Bundle(
        agent_version_id=row["agent_version_id"],
        agent_id=row["agent_id"],
        semver=row["semver"],
        status=row["status"],
        model_provider=row["model_provider"],
        model_id=row["model_id"],
        model_params=row["model_params"] or {},
        prompt_hash=row["prompt_hash"],
        guardrail_config=row["guardrail_config"] or {},
        autonomy_level=row["autonomy_level"],
        budget_p95_latency_ms=int(row["budget_p95_latency_ms"]),
        budget_cost_per_answer_usd=Decimal(str(row["budget_cost_per_answer_usd"])),
        eval_run_id=row["eval_run_id"],
        coverage=coverage,
        products=products,
        tools=tools,
    )


# Columns copied verbatim when a version is cloned. Listed rather than
# `SELECT *` so a new column is a compile-time decision: a bundle that silently
# gained a field the clone did not copy is a version that differs from its
# parent in a way nobody chose.
CLONED_COLUMNS = (
    "agent_id", "autonomy_level", "capability_statement", "business_value_block",
    "out_of_scope", "personas", "analyses", "replaces", "model_provider", "model_id",
    "model_params", "prompt_hash", "guardrail_config", "budget_p95_latency_ms",
    "budget_cost_per_answer_usd", "eval_suites", "eval_threshold_pct", "eval_run_id",
)


JSONB_COLUMNS = frozenset({"model_params", "guardrail_config"})


def _jsonb_columns(connection: psycopg.Connection[Any], table: str) -> frozenset[str]:
    """Which of a table's columns are jsonb.

    Asked of the catalog rather than listed, because a clone that stopped
    copying a new jsonb column correctly would fail on the day of a drill, which
    is the day nobody wants to debug an INSERT.
    """
    return frozenset(
        row["column_name"]
        for row in fetch_all(
            connection,
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = %s AND data_type = 'jsonb'",
            (table,),
        )
    )


def _adapt(name: str, value: Any) -> Any:
    return json.dumps(value) if name in JSONB_COLUMNS and value is not None else value


def clone(
    connection: psycopg.Connection[Any],
    tenant: str,
    *,
    agent_version_id: str,
    semver: str,
) -> str:
    """A new draft carrying the same bundle, for a release rehearsal.

    Everything is copied: the version row, the coverage map, the product
    bindings and the tool bindings. A clone that copied the row and not the
    bindings would produce a version that has never been evaluated, which is
    exactly the failure mode the bundle idea exists to prevent.
    """
    source = fetch_one(
        connection, "SELECT * FROM agent_version WHERE agent_version_id = %s",
        (agent_version_id,),
    )
    if source is None:
        raise ReleaseRefused(f"no agent version {agent_version_id}")

    new_id = f"AGV-{source['agent_id']}-{semver}"
    columns = ", ".join(CLONED_COLUMNS)
    # jsonb columns come back as dicts and go out as json. Named explicitly so
    # a new jsonb column on the version table is a decision rather than a
    # runtime surprise on the day somebody runs a drill.
    placeholders = ", ".join(
        "%s::jsonb" if name in JSONB_COLUMNS else "%s" for name in CLONED_COLUMNS
    )
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO agent_version (agent_version_id, tenant_id, semver, status, "  # noqa: S608 - fixed column tuple
            f"  {columns}) VALUES (%s, %s, %s, %s, {placeholders}) "
            "ON CONFLICT (agent_version_id) DO NOTHING",
            (new_id, tenant, semver, STATUS_DRAFT,
             *[_adapt(name, source[name]) for name in CLONED_COLUMNS]),
        )
        for table, key in (
            ("agent_kpi_coverage", "coverage_id"),
            ("agent_product_binding", "binding_id"),
            ("agent_tool_binding", "tool_binding_id"),
            # The curated exchanges come too. The publish gate requires five of
            # them, and a clone without them is a version that could never be
            # released — which would make a drill rehearse a path production
            # never takes.
            ("demo_exchange", "exchange_id"),
        ):
            rows = fetch_all(
                connection,
                f"SELECT * FROM {table} WHERE agent_version_id = %s",  # noqa: S608
                (agent_version_id,),
            )
            jsonb = _jsonb_columns(connection, table)
            for row in rows:
                copied = dict(row)
                copied[key] = f"{copied[key]}-{semver}"
                copied["agent_version_id"] = new_id
                names = ", ".join(copied)
                marks = ", ".join(
                    "%s::jsonb" if name in jsonb else "%s" for name in copied
                )
                cursor.execute(
                    f"INSERT INTO {table} ({names}) VALUES ({marks}) "  # noqa: S608
                    f"ON CONFLICT ({key}) DO NOTHING",
                    tuple(
                        json.dumps(value) if name in jsonb and value is not None else value
                        for name, value in copied.items()
                    ),
                )
    return new_id


def discard(connection: psycopg.Connection[Any], agent_version_id: str) -> None:
    """Remove a draft nothing has ever served. Refuses anything else.

    A drill creates a version and must be able to remove it, but only while it
    is a draft with no interactions behind it. A version that has answered a
    question is part of the record and stays.
    """
    row = fetch_one(
        connection,
        "SELECT status, (SELECT count(*) FROM agent_interaction i "
        "                 WHERE i.agent_version_id = v.agent_version_id) AS answers "
        "FROM agent_version v WHERE agent_version_id = %s",
        (agent_version_id,),
    )
    if row is None:
        return
    if row["status"] not in (STATUS_DRAFT, STATUS_RETIRED) or int(row["answers"]):
        raise ReleaseRefused(
            f"{agent_version_id} is {row['status']} with {row['answers']} answer(s); "
            "a version that has served is part of the record"
        )
    with connection.cursor() as cursor:
        for table in ("agent_kpi_coverage", "agent_product_binding", "agent_tool_binding"):
            cursor.execute(
                f"DELETE FROM {table} WHERE agent_version_id = %s",  # noqa: S608
                (agent_version_id,),
            )
        cursor.execute(
            "DELETE FROM agent_version WHERE agent_version_id = %s", (agent_version_id,)
        )


def _current(connection: psycopg.Connection[Any], agent_id: str) -> str:
    row = fetch_one(
        connection, "SELECT current_version_id FROM agent WHERE agent_id = %s", (agent_id,)
    )
    if row is None:
        raise ReleaseRefused(f"no agent {agent_id}")
    return str(row["current_version_id"])


def start_canary(
    connection: psycopg.Connection[Any],
    tenant: str,
    governance: Rubric,
    evaluation: Rubric,
    *,
    agent_version_id: str,
    actor_party_id: str | None,
) -> dict[str, Any]:
    """Put a version into canary at the rubric's traffic share.

    The gate runs first. A version that could not be published cannot be
    canaried either: a canary is production traffic on a smaller share, not a
    softer bar.
    """
    from services.agents import publish_gate

    candidate = bundle(connection, agent_version_id)
    if candidate.status != STATUS_DRAFT:
        raise ReleaseRefused(
            f"{agent_version_id} is {candidate.status}; only a draft enters canary"
        )

    result = publish_gate.evaluate(connection, agent_version_id, evaluation)
    if not result.publishable:
        raise ReleaseRefused(
            f"{agent_version_id} does not clear the publish gate: "
            + "; ".join(result.shortfalls)
        )

    traffic = Decimal(str(evaluation.number(TRAFFIC_PATH)))
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE agent_version SET status = %s, canary_traffic_pct = %s "
            "WHERE agent_version_id = %s",
            (STATUS_CANARY, traffic, agent_version_id),
        )

    audit.record(
        connection, tenant, governance,
        audit_id=f"AUD-CANARY-{agent_version_id}-{datetime.now(UTC):%Y%m%d%H%M%S}",
        event_name=EVENT_CANARY,
        outcome=STATUS_CANARY,
        actor_party_id=actor_party_id,
        asset_type="agent",
        asset_id=candidate.agent_id,
        detail={"agent_version_id": agent_version_id, "traffic_pct": float(traffic)},
    )
    return {
        "agent_version_id": agent_version_id,
        "status": STATUS_CANARY,
        "traffic_pct": float(traffic),
        "live_version_id": _current(connection, candidate.agent_id),
    }


def canary_evidence(
    connection: psycopg.Connection[Any], evaluation: Rubric, *, agent_version_id: str
) -> dict[str, Any]:
    """What real traffic has said about a canary so far.

    Two numbers and both are required: answers and hours. A canary that took a
    thousand answers in twenty minutes has been asked one kind of question by
    one shift, and promoting on that is promoting on a sample nobody chose.
    """
    minimum_answers = int(evaluation.number(MIN_ANSWERS_PATH))
    minimum_hours = int(evaluation.number(MIN_HOURS_PATH))
    row = fetch_one(
        connection,
        "SELECT count(*) AS answers, min(occurred_at) AS first_seen, "
        "       count(*) FILTER (WHERE NOT grounded) AS ungrounded, "
        "       count(*) FILTER (WHERE outcome = 'error') AS errors "
        "FROM agent_interaction WHERE agent_version_id = %s",
        (agent_version_id,),
    )
    answers = int(row["answers"]) if row else 0
    hours = ZERO
    if row and row["first_seen"] is not None:
        hours = Decimal((datetime.now(UTC) - row["first_seen"]) / HOUR)

    missing: list[str] = []
    if answers < minimum_answers:
        missing.append(f"{minimum_answers - answers} more answers")
    if hours < minimum_hours:
        missing.append(f"{minimum_hours - int(hours)} more hours of traffic")
    # I11 does not soften for a canary. One ungrounded answer is a failure
    # whatever share of traffic produced it.
    ungrounded = int(row["ungrounded"]) if row else 0
    if ungrounded:
        missing.append(f"{ungrounded} ungrounded answer(s) to explain")

    return {
        "agent_version_id": agent_version_id,
        "answers": answers,
        "hours": float(hours),
        "ungrounded": ungrounded,
        "errors": int(row["errors"]) if row else 0,
        "min_answers": minimum_answers,
        "min_hours": minimum_hours,
        "ready": not missing,
        "missing": missing,
    }


def promote(
    connection: psycopg.Connection[Any],
    tenant: str,
    governance: Rubric,
    evaluation: Rubric,
    *,
    agent_version_id: str,
    actor_party_id: str,
) -> dict[str, Any]:
    """Promote a canary to published, on evidence, in one transaction."""
    if not actor_party_id:
        raise ReleaseRefused("a promotion names who promoted it")
    candidate = bundle(connection, agent_version_id)
    if candidate.status != STATUS_CANARY:
        raise ReleaseRefused(
            f"{agent_version_id} is {candidate.status}; only a canary is promoted"
        )

    evidence = canary_evidence(connection, evaluation, agent_version_id=agent_version_id)
    if not evidence["ready"]:
        raise ReleaseRefused(
            f"{agent_version_id} has not earned promotion yet: "
            + ", ".join(evidence["missing"])
        )

    previous_id = _current(connection, candidate.agent_id)
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE agent_version SET status = %s, retired_at = now() "
            "WHERE agent_version_id = %s AND agent_version_id <> %s",
            (STATUS_RETIRED, previous_id, agent_version_id),
        )
        cursor.execute(
            "UPDATE agent_version SET status = %s, published_at = now(), published_by = %s, "
            "  canary_traffic_pct = NULL WHERE agent_version_id = %s",
            (STATUS_PUBLISHED, actor_party_id, agent_version_id),
        )
        cursor.execute(
            "UPDATE agent SET current_version_id = %s WHERE agent_id = %s",
            (agent_version_id, candidate.agent_id),
        )

    audit.record(
        connection, tenant, governance,
        audit_id=f"AUD-PROMOTE-{agent_version_id}-{datetime.now(UTC):%Y%m%d%H%M%S}",
        event_name=EVENT_PROMOTED,
        outcome=STATUS_PUBLISHED,
        actor_party_id=actor_party_id,
        asset_type="agent",
        asset_id=candidate.agent_id,
        detail={"agent_version_id": agent_version_id, "replaces": previous_id,
                "evidence": evidence},
    )
    return {"agent_version_id": agent_version_id, "status": STATUS_PUBLISHED,
            "replaced": previous_id, "evidence": evidence}


EVENT_CANARY_ABANDONED = "agent_version.canary_abandoned"
EVENT_PUBLISHED = "agent_version.published"


def publish(
    connection: psycopg.Connection[Any],
    tenant: str,
    governance: Rubric,
    evaluation: Rubric,
    *,
    agent_version_id: str,
    actor_party_id: str,
) -> dict[str, Any]:
    """Publish a draft straight to live, through the gate.

    The path an estate uses to release its first version of anything, and the
    path a version takes when the canary window is not what is wanted. It is not
    a shortcut past the gate — the gate runs here exactly as it runs for a
    canary — it is a shortcut past the *waiting*, which is a decision for whoever
    is releasing rather than a property of the code.

    The previously live version is retired in the same transaction, so there is
    never a moment where two versions of one agent are published.
    """
    from services.agents import publish_gate

    if not actor_party_id:
        # The same rule the publish script enforces: an unattributed
        # publication is not a publication. Somebody decided this version was
        # ready and the record has to say who.
        raise ReleaseRefused("a publication names its publisher")

    candidate = bundle(connection, agent_version_id)
    if candidate.status == STATUS_PUBLISHED:
        return {"agent_version_id": agent_version_id, "status": STATUS_PUBLISHED,
                "replaced": None, "already": True}

    result = publish_gate.evaluate(connection, agent_version_id, evaluation)
    if not result.publishable:
        raise ReleaseRefused(
            f"{agent_version_id} does not clear the publish gate: "
            + "; ".join(result.shortfalls)
        )

    previous_id = _current(connection, candidate.agent_id)
    with connection.cursor() as cursor:
        if previous_id != agent_version_id:
            cursor.execute(
                "UPDATE agent_version SET status = %s, retired_at = now() "
                "WHERE agent_version_id = %s",
                (STATUS_RETIRED, previous_id),
            )
        cursor.execute(
            "UPDATE agent_version SET status = %s, published_at = now(), published_by = %s, "
            "  canary_traffic_pct = NULL, retired_at = NULL WHERE agent_version_id = %s",
            (STATUS_PUBLISHED, actor_party_id, agent_version_id),
        )
        cursor.execute(
            "UPDATE agent SET current_version_id = %s WHERE agent_id = %s",
            (agent_version_id, candidate.agent_id),
        )

    audit.record(
        connection, tenant, governance,
        audit_id=f"AUD-PUB-{agent_version_id}-{datetime.now(UTC):%Y%m%d%H%M%S%f}",
        event_name=EVENT_PUBLISHED,
        outcome=STATUS_PUBLISHED,
        actor_party_id=actor_party_id,
        asset_type="agent",
        asset_id=candidate.agent_id,
        detail={"agent_version_id": agent_version_id, "replaces": previous_id,
                "gate": result.document()},
    )
    return {"agent_version_id": agent_version_id, "status": STATUS_PUBLISHED,
            "replaced": previous_id, "already": False}


def abandon_canary(
    connection: psycopg.Connection[Any],
    tenant: str,
    governance: Rubric,
    *,
    agent_version_id: str,
    reason: str,
    actor_party_id: str | None,
) -> dict[str, Any]:
    """Drop a canary. The live bundle was never replaced, so nothing is restored.

    This is the other half of rollback and the half that happens more often. A
    canary carries a share of traffic beside the live version rather than
    instead of it, so pulling it is one update and the estate is already back on
    a bundle that has been serving all along.

    It is recorded as loudly as a rollback. A canary that was pulled is evidence
    about a version somebody will otherwise try again next quarter.
    """
    if not reason.strip():
        raise ReleaseRefused("a canary is pulled for a reason; record it")

    candidate = bundle(connection, agent_version_id)
    if candidate.status != STATUS_CANARY:
        raise ReleaseRefused(
            f"{agent_version_id} is {candidate.status}; only a canary is abandoned"
        )

    live_id = _current(connection, candidate.agent_id)
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE agent_version SET status = %s, canary_traffic_pct = NULL, "
            "  retired_at = now() WHERE agent_version_id = %s",
            (STATUS_RETIRED, agent_version_id),
        )

    audit.record(
        connection, tenant, governance,
        audit_id=f"AUD-CANARY-OFF-{agent_version_id}-{datetime.now(UTC):%Y%m%d%H%M%S%f}",
        event_name=EVENT_CANARY_ABANDONED,
        outcome=STATUS_RETIRED,
        actor_party_id=actor_party_id,
        asset_type="agent",
        asset_id=candidate.agent_id,
        detail={"agent_version_id": agent_version_id, "reason": reason,
                "live_version_id": live_id},
    )
    return {
        "agent_id": candidate.agent_id,
        "abandoned": agent_version_id,
        "live_version_id": live_id,
        "reason": reason,
    }


def rollback(
    connection: psycopg.Connection[Any],
    tenant: str,
    governance: Rubric,
    *,
    agent_id: str,
    reason: str,
    actor_party_id: str | None,
) -> dict[str, Any]:
    """Restore the previous bundle. One call, one transaction.

    A reason is required. "Rolled back" in an incident review is a fact without
    a cause, and the next person to ship that version will ship it for the same
    reason nobody wrote down.
    """
    if not reason.strip():
        raise ReleaseRefused("a rollback records why; a rollback with no reason is a mystery")

    live_id = _current(connection, agent_id)
    live = bundle(connection, live_id)

    previous = fetch_one(
        connection,
        "SELECT agent_version_id FROM agent_version "
        "WHERE agent_id = %s AND agent_version_id <> %s AND status IN (%s, %s) "
        "ORDER BY retired_at DESC NULLS LAST, published_at DESC NULLS LAST LIMIT 1",
        (agent_id, live_id, STATUS_RETIRED, STATUS_PUBLISHED),
    )
    if previous is None:
        raise ReleaseRefused(
            f"{agent_id} has no earlier published version to restore; there is nothing "
            "to roll back to"
        )

    restored = bundle(connection, previous["agent_version_id"])
    with connection.cursor() as cursor:
        # One statement each, one transaction. The bundle is the version, so
        # pointing at the previous version restores the prompt, the model, the
        # coverage map, the bindings and the budgets together — there is no
        # sequence here that can be interrupted half way and leave a
        # configuration nobody evaluated.
        cursor.execute(
            "UPDATE agent_version SET status = %s, retired_at = now() "
            "WHERE agent_version_id = %s",
            (STATUS_RETIRED, live_id),
        )
        cursor.execute(
            "UPDATE agent_version SET status = %s, retired_at = NULL "
            "WHERE agent_version_id = %s",
            (STATUS_PUBLISHED, restored.agent_version_id),
        )
        cursor.execute(
            "UPDATE agent SET current_version_id = %s WHERE agent_id = %s",
            (restored.agent_version_id, agent_id),
        )

    changes = restored.differences(live)
    audit.record(
        connection, tenant, governance,
        audit_id=f"AUD-ROLLBACK-{agent_id}-{datetime.now(UTC):%Y%m%d%H%M%S%f}",
        event_name=EVENT_ROLLED_BACK,
        outcome=STATUS_PUBLISHED,
        actor_party_id=actor_party_id,
        asset_type="agent",
        asset_id=agent_id,
        detail={"from": live_id, "to": restored.agent_version_id,
                "reason": reason, "restored": changes},
    )
    return {
        "agent_id": agent_id,
        "rolled_back_from": live.document(),
        "restored": restored.document(),
        # What actually came back, not just which version number. "Rolled back
        # to 1.0.0" is true and tells an incident review nothing.
        "changes": changes,
        "reason": reason,
    }
