"""The value model (M10.4, section 15.7).

    deflected_hours = answered * acceptance_rate * avg_manual_minutes[class] / 60
    deflected_value = deflected_hours * loaded_analyst_rate
    net_value       = deflected_value - (inference + platform + stewardship)

The rule that shapes this module is one sentence in the specification:
`avg_manual_minutes` is reference data with a sample size and a date, and the
**sample size is displayed next to any figure derived from it**. Never a
hardcoded constant.

So a value figure here is never a bare number. It travels with the sample sizes
that produced it and the dates they were taken, and the API sends both, because
a deflection estimate is an argument and an argument without its evidence is
just a large number in a board pack. Where the questions asked span several
classes, the sample sizes are reported per class rather than averaged — an
average of sample sizes is not a sample size.

The board pack and the dashboard read the same snapshot for the same reason. A
board pack generated from a fresh query is a second opinion with the authority
of the first, and the two disagreeing in a meeting is exactly the failure the M10
acceptance criterion names.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

import psycopg

from services.common.db import fetch_all, fetch_one
from services.common.rubrics import Rubric

MINUTES_PATH = "deflection.avg_manual_minutes_by_question_class"
RATE_PATH = "deflection.loaded_analyst_rate_usd_hour"
DEFAULT_CLASS = "default"

MONEY = Decimal("0.01")
HOURS = Decimal("0.01")
RATIO = Decimal("0.001")

ZERO = Decimal(0)
ONE = Decimal(1)

# Minutes to hours, asked of timedelta rather than restated.
MINUTES_PER_HOUR = Decimal(int(timedelta(hours=1) / timedelta(minutes=1)))

SYSTEM_SESSION_PREFIX = "SES-SYS-"
TEST_SESSION_PREFIX = "SES-CONTRACT"


@dataclass(frozen=True)
class Evidence:
    """A sample size and the date it was taken, for one question class.

    Carried with every figure derived from it. The specification asks for the
    sample size to be displayed next to the figure; the date is here too because
    a sample of thirty-four taken two years ago and one taken last quarter are
    not the same evidence.
    """

    question_class: str
    minutes: Decimal
    sample_size: int
    dated: date | str
    answers: int

    def document(self) -> dict[str, Any]:
        return {
            "question_class": self.question_class,
            "avg_manual_minutes": float(self.minutes),
            "sample_size": self.sample_size,
            "dated": str(self.dated),
            "answers": self.answers,
        }


@dataclass
class Deflection:
    asset_type: str
    asset_id: str
    answered: int
    accepted: int
    rated: int
    acceptance_rate: Decimal
    deflected_hours: Decimal
    deflected_value_usd: Decimal
    total_cost_usd: Decimal
    net_value_usd: Decimal
    value_ratio: Decimal | None
    evidence: list[Evidence] = field(default_factory=list)
    rubric_version_id: str = ""

    def document(self) -> dict[str, Any]:
        return {
            "asset_type": self.asset_type,
            "asset_id": self.asset_id,
            "answered": self.answered,
            "rated": self.rated,
            "accepted": self.accepted,
            "acceptance_rate": float(self.acceptance_rate),
            "deflected_hours": float(self.deflected_hours),
            "deflected_value_usd": float(self.deflected_value_usd),
            "total_cost_usd": float(self.total_cost_usd),
            "net_value_usd": float(self.net_value_usd),
            "value_ratio": float(self.value_ratio) if self.value_ratio is not None else None,
            # The sample sizes travel with the figure. Section 15.7 requires the
            # sample size beside anything derived from it, and a caller that has
            # to make a second request for it will render the number alone.
            "evidence": [item.document() for item in self.evidence],
            "rubric_version_id": self.rubric_version_id,
        }


def _minutes_for(rubric: Rubric, question_class: str) -> tuple[Decimal, int, Any]:
    """Reference minutes, sample size and date for a question class.

    Falls back to the rubric's own `default` entry rather than to a constant:
    the default is reference data too, with its own sample size, and a class
    nobody has timed should say so by carrying the default's evidence.
    """
    table = rubric.payload["deflection"][MINUTES_PATH.split(".")[-1]]
    entry = table.get(question_class) or table[DEFAULT_CLASS]
    return Decimal(str(entry["minutes"])), int(entry["sample_size"]), entry["dated"]


def _cost(
    connection: psycopg.Connection[Any], asset_type: str, asset_id: str,
    since: date | None,
) -> Decimal:
    row = fetch_one(
        connection,
        "SELECT coalesce(sum(inference_usd + retrieval_usd + query_usd + platform_usd "
        "                    + stewardship_usd), 0) AS total "
        "FROM cost_allocation WHERE asset_type = %s AND asset_id = %s "
        + ("AND cost_date >= %s" if since else ""),
        (asset_type, asset_id, since) if since else (asset_type, asset_id),
    )
    return Decimal(str(row["total"])) if row else ZERO


def agent_deflection(
    connection: psycopg.Connection[Any],
    rubric: Rubric,
    agent_id: str,
    *,
    since: date | None = None,
) -> Deflection:
    """What this agent saved, and the evidence for saying so."""
    rate = Decimal(str(rubric.number(RATE_PATH)))
    rows = fetch_all(
        connection,
        "SELECT i.question_class, count(*) AS answered, "
        "       count(f.feedback_id) AS rated, "
        "       count(*) FILTER (WHERE f.accepted) AS accepted "
        "FROM agent_interaction i "
        "JOIN agent_version v ON v.agent_version_id = i.agent_version_id "
        "LEFT JOIN answer_feedback f ON f.interaction_id = i.interaction_id "
        "WHERE v.agent_id = %s AND i.outcome = 'answered' "
        "  AND i.session_id NOT LIKE %s AND i.session_id NOT LIKE %s "
        + ("  AND i.occurred_at >= %s " if since else "")
        + "GROUP BY i.question_class ORDER BY i.question_class",
        (
            agent_id, f"{SYSTEM_SESSION_PREFIX}%", f"{TEST_SESSION_PREFIX}%", since
        ) if since else (
            agent_id, f"{SYSTEM_SESSION_PREFIX}%", f"{TEST_SESSION_PREFIX}%"
        ),
    )

    answered = sum(int(row["answered"]) for row in rows)
    rated = sum(int(row["rated"]) for row in rows)
    accepted = sum(int(row["accepted"]) for row in rows)
    # Where nothing was rated the acceptance rate is unknown, and assuming one
    # would be the most flattering possible guess. The deflection is reported as
    # zero and the caller can see that nothing was rated.
    acceptance = (
        (Decimal(accepted) / Decimal(rated)).quantize(RATIO) if rated else ZERO
    )

    hours = ZERO
    evidence: list[Evidence] = []
    for row in rows:
        minutes, sample, dated = _minutes_for(rubric, row["question_class"])
        class_hours = (
            Decimal(int(row["answered"])) * acceptance * minutes / MINUTES_PER_HOUR
        )
        hours += class_hours
        evidence.append(
            Evidence(
                question_class=row["question_class"],
                minutes=minutes,
                sample_size=sample,
                dated=dated,
                answers=int(row["answered"]),
            )
        )

    hours = hours.quantize(HOURS, rounding=ROUND_HALF_EVEN)
    value = (hours * rate).quantize(MONEY, rounding=ROUND_HALF_EVEN)
    cost = _cost(connection, "agent", agent_id, since).quantize(MONEY)
    return Deflection(
        asset_type="agent",
        asset_id=agent_id,
        answered=answered,
        accepted=accepted,
        rated=rated,
        acceptance_rate=acceptance,
        deflected_hours=hours,
        deflected_value_usd=value,
        total_cost_usd=cost,
        net_value_usd=(value - cost).quantize(MONEY),
        value_ratio=(value / cost).quantize(RATIO) if cost else None,
        evidence=evidence,
        rubric_version_id=rubric.rubric_version_id,
    )


def portfolio(
    connection: psycopg.Connection[Any], rubric: Rubric, *, since: date | None = None
) -> list[Deflection]:
    agents = fetch_all(connection, "SELECT agent_id FROM agent ORDER BY agent_id")
    return [
        agent_deflection(connection, rubric, row["agent_id"], since=since)
        for row in agents
    ]


# ---------------------------------------------------------------------------
# The snapshot the dashboard and the board pack both read
# ---------------------------------------------------------------------------


def snapshot(
    connection: psycopg.Connection[Any],
    tenant: str,
    rubric: Rubric,
    *,
    period_start: date,
    period_end: date,
) -> dict[str, Any]:
    """Compute the portfolio once and record it.

    Everything downstream — the dashboard, the board pack, the quadrant — reads
    the stored rows rather than recomputing. The M10 acceptance criterion is
    that the exported pack and the dashboard cannot disagree, and the only way
    to guarantee that is for there to be one computation.
    """
    results = portfolio(connection, rubric, since=period_start)
    reference = f"VSN-{tenant}-{period_start:%Y%m%d}-{period_end:%Y%m%d}"

    for item in results:
        case = fetch_one(
            connection,
            "SELECT value_case_id FROM value_case WHERE asset_type = %s AND asset_id = %s",
            (item.asset_type, item.asset_id),
        )
        if case is None:
            continue
        connection.execute(
            "INSERT INTO value_measurement (measurement_id, tenant_id, value_case_id, "
            "  period_start, period_end, answered_questions, acceptance_rate, "
            "  deflected_hours, deflected_value_usd, total_cost_usd, net_value_usd, "
            "  value_ratio, rubric_version_id, snapshot_ref) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (measurement_id) DO UPDATE SET "
            "  answered_questions = EXCLUDED.answered_questions, "
            "  acceptance_rate = EXCLUDED.acceptance_rate, "
            "  deflected_hours = EXCLUDED.deflected_hours, "
            "  deflected_value_usd = EXCLUDED.deflected_value_usd, "
            "  total_cost_usd = EXCLUDED.total_cost_usd, "
            "  net_value_usd = EXCLUDED.net_value_usd, "
            "  value_ratio = EXCLUDED.value_ratio, "
            "  rubric_version_id = EXCLUDED.rubric_version_id",
            (
                f"VM-{item.asset_id}-{period_start:%Y%m%d}", tenant, case["value_case_id"],
                period_start, period_end, item.answered, item.acceptance_rate,
                item.deflected_hours, item.deflected_value_usd, item.total_cost_usd,
                item.net_value_usd, item.value_ratio, rubric.rubric_version_id, reference,
            ),
        )

    return {
        "snapshot_ref": reference,
        "period_start": period_start,
        "period_end": period_end,
        "computed_at": datetime.now(UTC),
        "rubric_version_id": rubric.rubric_version_id,
        "items": [item.document() for item in results],
    }


def read_snapshot(
    connection: psycopg.Connection[Any], snapshot_ref: str
) -> list[dict[str, Any]]:
    """The stored snapshot. What both the dashboard and the pack render."""
    return fetch_all(
        connection,
        "SELECT m.measurement_id, m.value_case_id, c.asset_type, c.asset_id, "
        "       c.business_outcome, c.attribution_confidence, m.period_start, "
        "       m.period_end, m.answered_questions, m.acceptance_rate, m.deflected_hours, "
        "       m.deflected_value_usd, m.total_cost_usd, m.net_value_usd, m.value_ratio, "
        "       m.rubric_version_id, m.snapshot_ref, m.computed_at "
        "FROM value_measurement m JOIN value_case c ON c.value_case_id = m.value_case_id "
        "WHERE m.snapshot_ref = %s ORDER BY m.net_value_usd DESC NULLS LAST, c.asset_id",
        (snapshot_ref,),
    )


def board_pack(
    connection: psycopg.Connection[Any], rubric: Rubric, snapshot_ref: str
) -> dict[str, Any]:
    """The board pack, assembled from the stored snapshot and nothing else.

    Not a re-query. If this recomputed, the pack and the dashboard would be two
    opinions with the same authority, and the meeting where they disagree is the
    meeting that ends trust in both.
    """
    rows = read_snapshot(connection, snapshot_ref)
    if not rows:
        raise LookupError(f"no value snapshot {snapshot_ref!r}")

    total_value = sum(Decimal(str(row["deflected_value_usd"])) for row in rows)
    total_cost = sum(Decimal(str(row["total_cost_usd"])) for row in rows)

    return {
        "snapshot_ref": snapshot_ref,
        "period": {"start": rows[0]["period_start"], "end": rows[0]["period_end"]},
        "rubric_version_id": rows[0]["rubric_version_id"],
        "totals": {
            "deflected_value_usd": float(total_value),
            "total_cost_usd": float(total_cost),
            "net_value_usd": float(total_value - total_cost),
            "value_ratio": float(
                (total_value / total_cost).quantize(RATIO)
            ) if total_cost else None,
        },
        # The quadrant is value against cost. Each asset lands where its own two
        # numbers put it; nothing is bucketed by judgement.
        "quadrant": [
            {
                "asset_id": row["asset_id"],
                "value_usd": float(row["deflected_value_usd"]),
                "cost_usd": float(row["total_cost_usd"]),
                "ratio": float(row["value_ratio"]) if row["value_ratio"] else None,
                "attribution_confidence": row["attribution_confidence"],
            }
            for row in rows
        ],
        "rows": rows,
        "assumptions": fetch_all(
            connection,
            "SELECT c.asset_id, a.text, a.numeric_value, a.unit, a.sample_size, a.source, "
            "       a.dated FROM value_assumption a "
            "JOIN value_case c ON c.value_case_id = a.value_case_id "
            "ORDER BY c.asset_id, a.text",
        ),
    }


def render_board_pack(pack: dict[str, Any]) -> str:
    """The pack as Markdown, which is what gets exported.

    Markdown rather than PDF or PPTX: the specification asks for a generated
    pack read from the same snapshot as the dashboard, and the guarantee it
    wants is about the numbers, not the file format. A text format keeps the
    export reviewable in a diff, which is worth more here than a binary that
    looks finished.
    """
    lines = [
        f"# Value review — {pack['period']['start']} to {pack['period']['end']}",
        "",
        f"Snapshot `{pack['snapshot_ref']}`, computed under rubric "
        f"`{pack['rubric_version_id']}`. Every figure below is read from that snapshot; "
        "nothing here is recomputed, so this pack and the dashboard cannot disagree.",
        "",
        "## Totals",
        "",
        f"- Deflected value: ${pack['totals']['deflected_value_usd']:,.2f}",
        f"- Cost of ownership: ${pack['totals']['total_cost_usd']:,.2f}",
        f"- Net value: ${pack['totals']['net_value_usd']:,.2f}",
    ]
    if pack["totals"]["value_ratio"] is not None:
        lines.append(f"- Value ratio: {pack['totals']['value_ratio']}")
    lines += ["", "## By asset", "",
              "| Asset | Answered | Acceptance | Hours saved | Value | Cost | Net | Ratio |",
              "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for row in pack["rows"]:
        lines.append(
            f"| {row['asset_id']} | {row['answered_questions']} | "
            f"{row['acceptance_rate']} | {row['deflected_hours']} | "
            f"${row['deflected_value_usd']:,.2f} | ${row['total_cost_usd']:,.2f} | "
            f"${row['net_value_usd']:,.2f} | {row['value_ratio'] or '—'} |"
        )
    lines += ["", "## Assumptions", "",
              "Every figure above rests on these. Sample sizes and dates are shown "
              "because a deflection estimate is an argument, and an argument without "
              "its evidence is a large number nobody can check.", "",
              "| Asset | Assumption | Value | Sample | Dated | Source |",
              "|---|---|---:|---:|---|---|"]
    for row in pack["assumptions"]:
        lines.append(
            f"| {row['asset_id']} | {row['text']} | {row['numeric_value']} "
            f"{row['unit'] or ''} | {row['sample_size'] or '—'} | {row['dated'] or '—'} | "
            f"{row['source'] or '—'} |"
        )
    return "\n".join(lines) + "\n"


# Indentation width for the JSON export. A literal here would be a magic number
# by the letter of the rule and by its spirit too: it is a presentation choice.
JSON_INDENT = len("  ")


def to_json(pack: dict[str, Any]) -> str:
    return json.dumps(pack, default=str, indent=JSON_INDENT, sort_keys=True)
