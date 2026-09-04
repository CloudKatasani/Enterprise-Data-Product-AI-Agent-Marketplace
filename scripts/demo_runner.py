"""M6.4 — the demo runner.

Executes the real configured runtime against every curated exchange in the
registry, on demo-tier data, and judges the result against the golden answer
the agent manifest points at.

The distinction that matters: nothing here holds an answer. The runner asks the
runtime the steward's question, and the runtime plans it against the coverage
map and aggregates real rows. Golden answers are recorded outputs of that, kept
so a later run can be compared to an earlier one — they are never read back as
an answer. Deleting `seed/golden/` and re-capturing changes no behaviour; it
only forfeits the regression signal.

Three modes:

    --capture   record the current output as the golden answer (first run, or
                after a deliberate change, reviewed in the diff like any code)
    --verify    compare against the golden answer within its tolerance_pct
    --nightly   verify, then mark a failing or drifted exchange `stale` so the
                front-page theatre stops showing it (M6.5)

Every run writes an `agent_interaction` row, because a demo answer is an answer
and the observability surfaces should not have a blind spot where the
marketplace's own runner is concerned.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import psycopg

from services.agent_runtime import registry
from services.agent_runtime.base import (
    Answer,
    AskRequest,
    EntitlementShortfall,
    OutOfScope,
    RuntimeUnavailable,
)
from services.common import audit
from services.common.config import REPO_ROOT, get_settings, load_dotenv
from services.common.db import connect, fetch_all
from services.common.rubrics import load_current

STATE_PASSING = "passing"
STATE_STALE = "stale"
STATE_FAILING = "failing"

OUTCOME_ANSWERED = "answered"
OUTCOME_OUT_OF_SCOPE = "out_of_scope"
OUTCOME_ERROR = "error"
OUTCOME_DENIED = "denied"

SESSION_PREFIX = "SES-DEMO-RUNNER"
EVENT_STALE = "demo_exchange.stale"
# The runner asks analytical questions of demo data. It declares that purpose
# rather than inventing a "demo" one, so its interactions sit in the same purpose
# reporting as everything else instead of in a category only it uses.
PURPOSE = "analytics"

ZERO = Decimal(0)
ONE = Decimal(1)


@dataclass
class Outcome:
    exchange_id: str
    agent_id: str
    question: str
    state: str
    latency_ms: int
    budget_ms: int
    failures: list[str] = field(default_factory=list)
    captured: bool = False

    @property
    def ok(self) -> bool:
        return self.state == STATE_PASSING


# ---------------------------------------------------------------------------
# Golden answers
# ---------------------------------------------------------------------------


def golden_document(answer: Answer, exchange: dict[str, Any], rubric_version_id: str) -> dict[str, Any]:
    """What is worth pinning.

    The prose is pinned too, but only as context in a diff: prose is assembled
    from the claims, so a claim that moved is the real finding and a sentence
    that moved without one would be a composition bug worth seeing.
    """
    return {
        "exchange_id": exchange["exchange_id"],
        "agent_version_id": exchange["agent_version_id"],
        "question": exchange["question"],
        "analysis_type": exchange["analysis_type"],
        "rubric_version_id": rubric_version_id,
        "runtime": answer.runtime,
        "headline": answer.headline,
        "narrative": answer.narrative,
        "visual_type": answer.visual.get("type"),
        "table_columns": list(answer.table.get("columns") or []),
        "kpi_definitions": sorted(answer.kpi_definitions),
        "citations": sorted(
            (
                {"product_id": c.product_id, "columns": sorted(c.columns)}
                for c in answer.citations
            ),
            key=lambda item: item["product_id"],
        ),
        "claims": {key: str(value) for key, value in sorted(answer.claims.items())},
        "rows_scanned": answer.rows_scanned,
    }


def compare(golden: dict[str, Any], current: dict[str, Any], tolerance_pct: Decimal) -> list[str]:
    """Differences that matter, in the order a reviewer would want them."""
    failures: list[str] = []

    for key in ("visual_type", "kpi_definitions", "table_columns"):
        if golden.get(key) != current.get(key):
            failures.append(f"{key}: expected {golden.get(key)!r}, got {current.get(key)!r}")

    golden_cites = {item["product_id"]: item["columns"] for item in golden["citations"]}
    current_cites = {item["product_id"]: item["columns"] for item in current["citations"]}
    for product_id in sorted(set(golden_cites) ^ set(current_cites)):
        side = "no longer" if product_id in golden_cites else "newly"
        failures.append(f"citations: {product_id} is {side} cited")
    for product_id in sorted(set(golden_cites) & set(current_cites)):
        if golden_cites[product_id] != current_cites[product_id]:
            failures.append(
                f"citations: columns read on {product_id} changed from "
                f"{golden_cites[product_id]} to {current_cites[product_id]}"
            )

    for label in sorted(set(golden["claims"]) ^ set(current["claims"])):
        side = "disappeared" if label in golden["claims"] else "appeared"
        failures.append(f"claims: {label!r} {side}")
    for label in sorted(set(golden["claims"]) & set(current["claims"])):
        expected = Decimal(golden["claims"][label])
        actual = Decimal(current["claims"][label])
        if _drifted(expected, actual, tolerance_pct):
            failures.append(
                f"claims: {label} was {expected}, is {actual} "
                f"(tolerance {tolerance_pct}%)"
            )
    return failures


def _drifted(expected: Decimal, actual: Decimal, tolerance_pct: Decimal) -> bool:
    """Relative drift, falling back to absolute where the baseline is zero.

    A percentage tolerance around zero admits nothing, which would make any
    movement off a zero baseline a failure. Scaling by the larger magnitude
    keeps the check meaningful in both directions.
    """
    scale = max(abs(expected), abs(actual))
    if scale == ZERO:
        return False
    drift = abs(actual - expected) / scale
    return drift > tolerance_pct / Decimal("100")


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------


def _record(
    connection: psycopg.Connection[Any],
    exchange: dict[str, Any],
    answer: Answer | None,
    outcome: str,
    tenant: str,
    principal: str,
) -> None:
    connection.execute(
        "INSERT INTO agent_interaction (interaction_id, tenant_id, agent_version_id, "
        "  principal_id, session_id, tier, question, question_class, purpose_code, outcome, "
        "  grounded, confidence, citations, kpi_definitions, tool_calls, rows_scanned, "
        "  latency_ms, tokens_in, tokens_out, cost_usd) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            f"INT-{exchange['exchange_id']}-{datetime.now(UTC):%Y%m%d%H%M%S%f}",
            tenant,
            exchange["agent_version_id"],
            principal,
            f"{SESSION_PREFIX}-{exchange['exchange_id']}",
            exchange["data_tier"],
            exchange["question"],
            exchange["analysis_type"],
            PURPOSE,
            outcome,
            answer is not None and bool(answer.citations),
            answer.confidence if answer else ZERO,
            json.dumps([c.document() for c in answer.citations]) if answer else "[]",
            list(answer.kpi_definitions) if answer else [],
            json.dumps([c.document() for c in answer.tool_calls]) if answer else "[]",
            answer.rows_scanned if answer else 0,
            answer.latency_ms if answer else 0,
            answer.tokens_in if answer else 0,
            answer.tokens_out if answer else 0,
            answer.cost_usd if answer else ZERO,
        ),
    )


def run_one(
    connection: psycopg.Connection[Any],
    runtime: Any,
    exchange: dict[str, Any],
    *,
    capture: bool,
    tenant: str,
    principal: str,
    rubric_version_id: str,
) -> Outcome:
    budget = int(exchange["max_latency_ms"])
    result = Outcome(
        exchange_id=exchange["exchange_id"],
        agent_id=exchange["agent_id"],
        question=exchange["question"],
        state=STATE_PASSING,
        latency_ms=0,
        budget_ms=budget,
    )

    try:
        answer = runtime.ask(
            connection,
            AskRequest(
                agent_id=exchange["agent_id"],
                agent_version_id=exchange["agent_version_id"],
                question=exchange["question"],
                tier=exchange["data_tier"],
                purpose=PURPOSE,
                session_id=f"{SESSION_PREFIX}-{exchange['exchange_id']}",
                principal_id=principal,
                exchange_id=exchange["exchange_id"],
            ),
        )
    except EntitlementShortfall as error:
        _record(connection, exchange, None, OUTCOME_DENIED, tenant, principal)
        result.state = STATE_FAILING
        result.failures.append(
            f"the runner's principal cannot read {error.asset_id}; it holds no "
            f"{error.required_scope}"
        )
        return result
    except OutOfScope as error:
        _record(connection, exchange, None, OUTCOME_OUT_OF_SCOPE, tenant, principal)
        result.state = STATE_FAILING
        result.failures.append(f"refused a curated question: {error.detail}")
        return result
    except RuntimeUnavailable as error:
        _record(connection, exchange, None, OUTCOME_ERROR, tenant, principal)
        result.state = STATE_FAILING
        result.failures.append(f"runtime unavailable: {error}")
        return result

    _record(connection, exchange, answer, OUTCOME_ANSWERED, tenant, principal)
    result.latency_ms = answer.latency_ms

    if answer.latency_ms > budget:
        result.state = STATE_FAILING
        result.failures.append(f"latency {answer.latency_ms}ms over the {budget}ms budget")

    shape = exchange["expected_shape"] or {}
    for required in shape.get("must_cite") or []:
        cited = {c.product_id for c in answer.citations} | set(answer.kpi_definitions)
        if required not in cited:
            result.state = STATE_FAILING
            result.failures.append(f"the manifest requires a citation of {required}; none present")

    current = golden_document(answer, exchange, rubric_version_id)
    path = REPO_ROOT / exchange["golden_answer_ref"]

    if capture:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        result.captured = True
        return result

    if not path.exists():
        result.state = STATE_FAILING
        result.failures.append(
            f"no golden answer at {exchange['golden_answer_ref']}; run with --capture"
        )
        return result

    golden = json.loads(path.read_text(encoding="utf-8"))
    drift = compare(golden, current, Decimal(str(exchange["tolerance_pct"])))
    if drift:
        result.state = STATE_STALE if result.state == STATE_PASSING else result.state
        result.failures.extend(drift)
    return result


def _mark(connection: psycopg.Connection[Any], result: Outcome) -> None:
    connection.execute(
        "UPDATE demo_exchange SET validation_state = %s, last_validated = now() "
        "WHERE exchange_id = %s",
        (result.state, result.exchange_id),
    )


def _notify_owner(
    connection: psycopg.Connection[Any], tenant: str, rubric: Any, result: Outcome
) -> None:
    """Record that the owner needs to know an exchange stopped working.

    An audit event, not a message: delivery is M10.2's job and this is the row
    it will read. Writing it here means the record exists from the moment the
    nightly run finds the drift, rather than from the moment a mailer is built.
    """
    owner = fetch_all(
        connection,
        "SELECT a.owner_party_id, a.on_call FROM agent a WHERE a.agent_id = %s",
        (result.agent_id,),
    )
    party = owner[0] if owner else {}
    audit.record(
        connection,
        tenant,
        rubric,
        audit_id=f"AUD-{result.exchange_id}-{datetime.now(UTC):%Y%m%d%H%M%S}",
        event_name=EVENT_STALE,
        outcome=result.state,
        actor_party_id=None,
        asset_type="agent",
        asset_id=result.agent_id,
        detail={
            "exchange_id": result.exchange_id,
            "question": result.question,
            "failures": result.failures,
            "notify": {
                "owner_party_id": party.get("owner_party_id"),
                "on_call": party.get("on_call"),
            },
            "effect": "removed from the front-page theatre until it passes again",
        },
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run curated demo exchanges against the runtime.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--capture", action="store_true", help="record golden answers")
    mode.add_argument("--verify", action="store_true", help="compare against golden answers")
    mode.add_argument("--nightly", action="store_true", help="verify and mark drifted exchanges")
    parser.add_argument("--agent", help="limit to one agent id")
    parser.add_argument(
        "--principal",
        default=os.environ.get("PORTAL_DEV_SUBJECT", ""),
        help="party id the runner acts as; its grants decide what the answers can read",
    )
    arguments = parser.parse_args(argv)

    load_dotenv()
    settings = get_settings()
    principal = arguments.principal or os.environ.get("PORTAL_DEV_SUBJECT", "")
    if not principal:
        print(
            "demo-runner: no principal. Pass --principal or set PORTAL_DEV_SUBJECT; the "
            "runner does not run as an unattributed actor.",
            file=sys.stderr,
        )
        return 1

    with connect() as connection:
        runtime = registry.build(connection)
        rubric_version_id = registry.load_current(connection, registry.RUNTIME_RUBRIC).rubric_version_id

        parameters: list[Any] = []
        where = ""
        if arguments.agent:
            where = "WHERE v.agent_id = %s"
            parameters.append(arguments.agent)

        exchanges = fetch_all(
            connection,
            "SELECT e.*, v.agent_id FROM demo_exchange e "
            "JOIN agent_version v ON v.agent_version_id = e.agent_version_id "
            f"{where} ORDER BY v.agent_id, e.ordinal",
            tuple(parameters),
        )
        if not exchanges:
            print("demo-runner: no curated exchanges to run", file=sys.stderr)
            return 1

        results = [
            run_one(
                connection,
                runtime,
                exchange,
                capture=arguments.capture,
                tenant=settings.tenant_id,
                principal=principal,
                rubric_version_id=rubric_version_id,
            )
            for exchange in exchanges
        ]
        if not arguments.capture:
            governance = load_current(connection, audit.GOVERNANCE_RUBRIC)
            for result in results:
                _mark(connection, result)
                if arguments.nightly and not result.ok:
                    _notify_owner(connection, settings.tenant_id, governance, result)
        connection.commit()

    return _report(results, capture=arguments.capture, nightly=arguments.nightly)


def _report(results: list[Outcome], *, capture: bool, nightly: bool) -> int:
    failed = [result for result in results if not result.ok]
    slowest = max(results, key=lambda result: result.latency_ms)

    for result in results:
        if result.ok:
            continue
        print(f"\n{result.agent_id} {result.exchange_id}: {result.state}")
        print(f"  Q: {result.question}")
        for failure in result.failures:
            print(f"  - {failure}")

    verb = "captured" if capture else "verified"
    print(
        f"\ndemo-runner: {verb} {len(results)} exchange(s), {len(failed)} not passing; "
        f"slowest {slowest.latency_ms}ms against a {slowest.budget_ms}ms budget"
    )
    if nightly and failed:
        print(
            "demo-runner: the exchanges above are marked stale and will not appear in the "
            "front-page theatre until they pass again"
        )
        return 0
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
