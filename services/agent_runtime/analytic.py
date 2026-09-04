"""The deterministic analytical runtime.

This is a real agent runtime, not a stub: it resolves the question against the
agent's coverage map, builds a query from the certified KPI definition, executes
it against the demo tier, and composes the answer from the rows that came back.
Every number in an answer is computed from data the agent is granted, and every
one of them is cited.

Two things it deliberately does not do. It does not call a language model, so it
reports zero tokens rather than inventing a plausible count — a trace that lies
about what happened is worse than no trace. And it does not hold a single
canned answer: give it a different demo tier and it returns different numbers,
which is what "no mocked answers exist" (M6 acceptance) has to mean.

The narrative it writes is assembled from the computed rows, so a claim in prose
and a number in the table cannot disagree.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

import psycopg

from services.agent_runtime import planner
from services.agent_runtime.base import (
    Answer,
    AskRequest,
    Citation,
    OutOfScope,
    ToolCall,
)
from services.common.db import fetch_all, fetch_one
from services.common.rubrics import Rubric
from services.common.timing import elapsed_ms

RUNTIME_NAME = "analytic"

MONEY = Decimal("0.000001")
MEASURE = Decimal("0.0001")
PERCENT_POINTS = Decimal("0.01")

# Rubric paths this runtime resolves. Nothing here is a literal.
COST_CLASS_PATH = "cost_classes.{cost_class}"
COST_UNIT_PATH = "cost_per_relative_unit_usd"
ROW_LIMIT_PATH = "answer_row_limit"
CONFIDENCE_FULL_PATH = "answer_confidence.complete"
CONFIDENCE_THIN_PATH = "answer_confidence.thin_evidence"
THIN_EVIDENCE_ROWS_PATH = "answer_confidence.thin_evidence_rows"
PERCENT_SCALE_PATH = "presentation.percent_scale"
MEDIAN_FRACTION_PATH = "distribution.median_fraction"
TAIL_FRACTION_PATH = "distribution.tail_fraction"


@dataclass
class _Context:
    agent_id: str
    agent_version_id: str
    coverage: dict[str, Any]
    kpi: dict[str, Any]
    binding: dict[str, Any]
    product: dict[str, Any]
    exchange: dict[str, Any] | None
    demo_schema: str


def _demo_table(schema: str, product_id: str) -> str:
    return f"{schema}.t_{product_id.replace('-', '_').lower()}"


def _measure_sql(kpi: dict[str, Any]) -> str:
    """The certified measure, written once, from the register.

    A percentage KPI is scaled here rather than in the definition, so the
    register stores the ratio and every consumer agrees on the presentation.
    """
    if kpi["expression"]:
        return f"({kpi['expression']})"
    numerator = kpi["numerator_expr"]
    denominator = kpi["denominator_expr"]
    scale = " * 100" if kpi["unit"] == "percent" else ""
    return f"(({numerator})::numeric / NULLIF(({denominator})::numeric, 0){scale})"


# Logical types from the data contract. A column is a time column because the
# contract says so, never because its name ends in "_start": `active_at_period_start`
# is a boolean, and date_trunc on it is a crash rather than a wrong answer only
# by luck.
TEMPORAL_TYPES = frozenset({"date", "timestamp", "timestamptz", "datetime"})


def _time_column(column_types: dict[str, str], coverage_columns: list[str]) -> str:
    """The time column the agent may read, preferring one the KPI already uses."""
    temporal = [name for name, kind in column_types.items() if kind in TEMPORAL_TYPES]
    if not temporal:
        raise OutOfScope("this product publishes no time column the agent can read")
    for name in coverage_columns:
        if name in temporal:
            return name
    return temporal[0]


def _load_context(
    connection: psycopg.Connection[Any], request: AskRequest, demo_schema: str
) -> _Context:
    exchange = None
    if request.exchange_id:
        exchange = fetch_one(
            connection,
            "SELECT * FROM demo_exchange WHERE exchange_id = %s AND agent_version_id = %s",
            (request.exchange_id, request.agent_version_id),
        )
        if exchange is None:
            raise OutOfScope(f"no curated exchange {request.exchange_id} for this agent version")

    coverage_rows = fetch_all(
        connection,
        "SELECT * FROM agent_kpi_coverage WHERE agent_version_id = %s ORDER BY kpi_id",
        (request.agent_version_id,),
    )
    if not coverage_rows:
        raise OutOfScope("this agent version declares no coverage map")

    if exchange is not None:
        coverage = next(
            (row for row in coverage_rows if row["kpi_id"] == exchange["kpi_class"]), None
        )
        if coverage is None:
            raise OutOfScope(
                f"the exchange cites {exchange['kpi_class']}, which this version does not cover"
            )
    else:
        coverage = _match_coverage(connection, request.question, coverage_rows)

    kpi = fetch_one(
        connection, "SELECT * FROM kpi_definition WHERE kpi_id = %s", (coverage["kpi_id"],)
    )
    if kpi is None:
        raise OutOfScope(f"{coverage['kpi_id']} is not in the certified register")

    binding = fetch_one(
        connection,
        "SELECT * FROM agent_product_binding WHERE agent_version_id = %s AND product_id = %s",
        (request.agent_version_id, coverage["source_product_id"]),
    )
    if binding is None:
        raise OutOfScope(
            f"this agent version is not bound to {coverage['source_product_id']}"
        )

    product = fetch_one(
        connection,
        "SELECT p.product_id, p.name, c.semver AS contract_version, "
        "       array_agg(col.name ORDER BY col.ordinal) AS columns, "
        "       jsonb_object_agg(col.name, col.data_type) AS column_types "
        "FROM data_product p "
        "JOIN data_contract_version c ON c.product_id = p.product_id AND c.status = 'active' "
        "JOIN data_product_column col ON col.product_id = p.product_id "
        "WHERE p.product_id = %s GROUP BY p.product_id, c.semver",
        (coverage["source_product_id"],),
    )
    if product is None:
        raise OutOfScope(f"{coverage['source_product_id']} has no active contract")

    return _Context(
        agent_id=request.agent_id,
        agent_version_id=request.agent_version_id,
        coverage=coverage,
        kpi=kpi,
        binding=binding,
        product=product,
        exchange=exchange,
        demo_schema=demo_schema,
    )


def _match_coverage(
    connection: psycopg.Connection[Any], question: str, coverage_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """Place a free-form question against the coverage map, or refuse.

    Matching is on the KPI's registered name and synonyms — the steward's words,
    not the agent's guess. A question that matches nothing is out of scope, and
    the refusal names the agents that do cover it.
    """
    lowered = question.lower()
    names = fetch_all(
        connection,
        "SELECT k.kpi_id, lower(k.kpi_name) AS name, "
        "       coalesce(array_agg(lower(s.term)) FILTER (WHERE s.term IS NOT NULL), '{}') "
        "         AS synonyms "
        "FROM kpi_definition k LEFT JOIN kpi_synonym s ON s.kpi_id = k.kpi_id "
        "WHERE k.kpi_id = ANY(%s) GROUP BY k.kpi_id, k.kpi_name",
        ([row["kpi_id"] for row in coverage_rows],),
    )
    by_id = {row["kpi_id"]: row for row in names}

    best: tuple[int, dict[str, Any]] | None = None
    for row in coverage_rows:
        terms = by_id.get(row["kpi_id"], {"name": "", "synonyms": []})
        candidates = [terms["name"], *terms["synonyms"]]
        score = sum(1 for term in candidates if term and term in lowered)
        # A word-level fallback so "churn" finds "Churn Rate".
        score += sum(
            1 for term in candidates if term and any(
                word in lowered.split() for word in term.split()
            )
        )
        if score and (best is None or score > best[0]):
            best = (score, row)

    if best is None:
        raise OutOfScope(
            "This agent does not cover that question. It answers on: "
            + ", ".join(sorted(row["kpi_id"] for row in coverage_rows))
            + "."
        )
    return best[1]


def _quantise(value: Any, unit: str) -> Decimal | None:
    if value is None:
        return None
    number = Decimal(str(value))
    if unit == "currency":
        return number.quantize(MONEY, rounding=ROUND_HALF_EVEN)
    if unit == "percent":
        return number.quantize(PERCENT_POINTS, rounding=ROUND_HALF_EVEN)
    return number.quantize(MEASURE, rounding=ROUND_HALF_EVEN)


# ---------------------------------------------------------------------------
# Query execution
# ---------------------------------------------------------------------------


@dataclass
class _Executed:
    columns: list[str]
    rows: list[dict[str, Any]]
    sql: str
    arguments: dict[str, Any]
    rows_scanned: int
    duration_ms: int
    as_of: Any


# A certified measure is normally an aggregate. A few are per-row window
# expressions — a propensity decile, for instance — which cannot appear beside a
# GROUP BY. Those are computed row by row in a subquery and averaged over the
# group, so the register keeps one definition and the runtime does not need a
# second one for the grouped case.
WINDOW_MARKER = " over ("
WINDOWED_MEASURE = "window_measure"


def _is_windowed(kpi: dict[str, Any]) -> bool:
    return WINDOW_MARKER in (kpi["expression"] or "").lower()


def _run(
    connection: psycopg.Connection[Any],
    context: _Context,
    plan: planner.QueryPlan,
    table: str,
    time_column: str,
    rubric: Rubric,
) -> _Executed:
    measure = _measure_sql(context.kpi)
    started = time.perf_counter()

    if plan.shape == planner.SHAPE_PERIOD:
        dimension = f"date_trunc('{plan.grain}', {time_column})"
        label = "period"
        order = "1"
    elif plan.shape == planner.SHAPE_COHORT:
        dimension = f"{plan.cohort_column}::text"
        label = "cohort"
        order = "1"
    elif plan.shape == planner.SHAPE_DISTRIBUTION:
        dimension = plan.slice_column or f"date_trunc('{plan.grain}', {time_column})"
        label = plan.slice_column or "period"
        order = "1"
    else:
        dimension = plan.slice_column or f"date_trunc('{plan.grain or 'month'}', {time_column})"
        label = plan.slice_column or "period"
        order = "2 DESC NULLS LAST"

    source = table
    grouped_by = dimension
    if plan.shape == planner.SHAPE_DISTRIBUTION and plan.measure_column:
        aggregate = (
            f"percentile_cont({rubric.number(MEDIAN_FRACTION_PATH)}) WITHIN GROUP "
            f"(ORDER BY {plan.measure_column}) AS measure, "
            f"percentile_cont({rubric.number(TAIL_FRACTION_PATH)}) WITHIN GROUP "
            f"(ORDER BY {plan.measure_column}) AS tail"
        )
    elif _is_windowed(context.kpi):
        source = (
            f"(SELECT {dimension} AS {label}, {measure} AS {WINDOWED_MEASURE} FROM {table}) w"
        )
        grouped_by = label
        aggregate = f"avg({WINDOWED_MEASURE}) AS measure"
    else:
        aggregate = f"{measure} AS measure"

    sql = (
        f"SELECT {grouped_by} AS {label}, {aggregate}, count(*) AS observations "
        f"FROM {source} GROUP BY 1 HAVING count(*) > 0 ORDER BY {order} LIMIT %(limit)s"
    )
    arguments = {"limit": plan.limit}
    rows = fetch_all(connection, sql, arguments)

    scanned = fetch_one(connection, f"SELECT count(*) AS rows FROM {table}")
    as_of = fetch_one(connection, f"SELECT max({time_column}) AS as_of FROM {table}")
    duration_ms = elapsed_ms(started)

    return _Executed(
        columns=[label, "measure", "observations"],
        rows=rows,
        sql=sql,
        arguments={
            **arguments,
            "table": table,
            "measure": measure,
            "group_by": label,
            "grain": plan.grain,
        },
        rows_scanned=int(scanned["rows"]) if scanned else 0,
        duration_ms=duration_ms,
        as_of=as_of["as_of"] if as_of else None,
    )


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------

VISUAL_FOR_SHAPE = {
    planner.SHAPE_PERIOD: "line",
    planner.SHAPE_SLICE: "bar",
    planner.SHAPE_COHORT: "comparison_bars",
    planner.SHAPE_DISTRIBUTION: "histogram",
}


def _unit_suffix(unit: str) -> str:
    return {
        "percent": "%", "currency": "", "days": " days", "hours": " hours",
        "minutes": " minutes", "count": "", "ratio": "", "index": "", "rate": "",
        "score": "", "weeks": " weeks",
    }.get(unit, "")


def _format(value: Decimal | None, unit: str) -> str:
    if value is None:
        return "no value"
    prefix = "$" if unit == "currency" else ""
    return f"{prefix}{value:,}{_unit_suffix(unit)}"


def _compose(
    context: _Context, plan: planner.QueryPlan, executed: _Executed, rubric: Rubric
) -> tuple[str, str, dict[str, Any], dict[str, Any], dict[str, Decimal], list[str]]:
    unit = context.kpi["unit"]
    label = executed.columns[0]
    name = context.kpi["kpi_name"]
    rows = executed.rows
    notes: list[str] = []
    claims: dict[str, Decimal] = {}

    if not rows:
        raise OutOfScope(
            f"{context.product['product_id']} holds no rows the agent can read for "
            f"{context.kpi['kpi_id']}"
        )

    values = [(row[label], _quantise(row["measure"], unit), row["observations"]) for row in rows]
    total = sum((value for _, value, _ in values if value is not None), start=Decimal(0))

    if plan.shape == planner.SHAPE_PERIOD:
        latest_label, latest, _ = values[-1]
        previous = values[-2] if len(values) > 1 else None
        claims["current"] = latest if latest is not None else Decimal(0)
        movement = ""
        if previous and previous[1] is not None and latest is not None:
            delta = (latest - previous[1]).quantize(PERCENT_POINTS)
            claims["delta"] = delta
            direction = "up" if delta > 0 else ("down" if delta < 0 else "flat")
            movement = (
                f", {direction} {_format(abs(delta), unit)} on the prior {plan.grain}"
                if direction != "flat"
                else f", flat on the prior {plan.grain}"
            )
        headline = (
            f"{name} is {_format(latest, unit)} for the {plan.grain} ending "
            f"{_label(latest_label)}{movement}."
        )
        narrative = (
            f"Computed from {context.product['product_id']} under the certified definition "
            f"{context.kpi['kpi_id']}, across {len(values)} {plan.grain}s and "
            f"{executed.rows_scanned:,} rows."
        )
    elif plan.shape == planner.SHAPE_COHORT:
        ordered = sorted(values, key=lambda item: (item[1] is None, item[1]), reverse=True)
        top_label, top, top_count = ordered[0]
        bottom_label, bottom, bottom_count = ordered[-1]
        claims["cohort_high"] = top if top is not None else Decimal(0)
        claims["cohort_low"] = bottom if bottom is not None else Decimal(0)
        gap = (top - bottom) if top is not None and bottom is not None else None
        if gap is not None:
            claims["cohort_gap"] = gap.quantize(PERCENT_POINTS)
        headline = (
            f"{name} is {_format(top, unit)} where {label} is {_label(top_label)} against "
            f"{_format(bottom, unit)} where it is {_label(bottom_label)}"
            + (f", a gap of {_format(gap, unit)}." if gap is not None else ".")
        )
        narrative = (
            f"Both cohorts are drawn from {context.product['product_id']} over the same "
            f"period: {top_count:,} observations against {bottom_count:,}."
        )
    elif plan.shape == planner.SHAPE_DISTRIBUTION:
        top_label, median, observations = values[0]
        claims["median"] = median if median is not None else Decimal(0)
        tail = _quantise(rows[0].get("tail"), unit)
        tail_name = format(rubric.number(TAIL_FRACTION_PATH), ".0%")
        if tail is not None:
            claims["tail"] = tail
        headline = (
            f"Median {name.lower()} is {_format(median, unit)} for {_label(top_label)}, "
            f"with the {tail_name} percentile at {_format(tail, unit)}."
        )
        narrative = (
            f"Across {observations:,} observations in {context.product['product_id']}; "
            f"the spread, not the mean, is what the question asked about."
        )
    else:
        top_label, top, top_count = values[0]
        claims["top"] = top if top is not None else Decimal(0)
        share = None
        if total and top is not None:
            share = (top / total * rubric.number(PERCENT_SCALE_PATH)).quantize(PERCENT_POINTS)
            claims["top_share"] = share
        headline = (
            f"{_label(top_label)} leads on {name.lower()} at {_format(top, unit)}"
            + (f", {share}% of the total across {len(values)} {label.replace('_', ' ')}s."
               if share is not None else f" across {len(values)} groups.")
        )
        narrative = (
            f"Ranked by the certified definition {context.kpi['kpi_id']} over "
            f"{executed.rows_scanned:,} rows in {context.product['product_id']}."
        )

    thin = int(rubric.number(THIN_EVIDENCE_ROWS_PATH))
    if executed.rows_scanned < thin:
        notes.append(
            f"Fewer than {thin:,} rows were available, so this answer is thinner evidence "
            "than usual."
        )

    table = {
        "columns": [label, context.kpi["kpi_id"], "observations"],
        "rows": [
            [_label(row_label), float(value) if value is not None else None, int(count)]
            for row_label, value, count in values
        ],
    }
    visual = {
        "type": VISUAL_FOR_SHAPE[plan.shape],
        "spec": {
            "x": label,
            "y": context.kpi["kpi_id"],
            "unit": unit,
            "direction": context.kpi["direction"],
            "target": float(context.kpi["target"]) if context.kpi["target"] is not None else None,
        },
    }
    return headline, narrative, visual, table, claims, notes


def _label(value: Any) -> str:
    if hasattr(value, "date"):
        return value.date().isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


# ---------------------------------------------------------------------------
# The runtime
# ---------------------------------------------------------------------------


class AnalyticRuntime:
    """Answers by executing the certified measure against the demo tier."""

    name = RUNTIME_NAME

    def __init__(self, rubric: Rubric, finops: Rubric, demo_schema: str) -> None:
        self._rubric = rubric
        self._finops = finops
        self._demo_schema = demo_schema

    def ask(self, connection: psycopg.Connection[Any], request: AskRequest) -> Answer:
        started = time.perf_counter()
        context = _load_context(connection, request, self._demo_schema)

        analysis_type = (
            context.exchange["analysis_type"] if context.exchange else "ranking"
        )
        plan = planner.resolve(
            question=request.question,
            analysis_type=analysis_type,
            coverage=context.coverage,
            kpi=context.kpi,
            binding_columns=list(context.binding["columns_allowed"]),
            limit=int(self._rubric.number(ROW_LIMIT_PATH)),
        )

        table = _demo_table(self._demo_schema, plan.product_id)
        time_column = _time_column(
            dict(context.product["column_types"]), list(plan.columns_used)
        )
        executed = _run(connection, context, plan, table, time_column, self._rubric)

        headline, narrative, visual, table_payload, claims, notes = _compose(
            context, plan, executed, self._rubric
        )

        tool_name = f"query_{plan.product_id.replace('-', '_').lower()}"
        cost_class = self._tool_cost_class(connection, request.agent_version_id, tool_name)
        relative = self._finops.number(COST_CLASS_PATH.format(cost_class=cost_class))
        cost = (relative * self._rubric.number(COST_UNIT_PATH)).quantize(MONEY)

        call = ToolCall(
            tool=tool_name,
            arguments=executed.arguments,
            rows_returned=len(executed.rows),
            rows_scanned=executed.rows_scanned,
            duration_ms=executed.duration_ms,
            cost_class=cost_class,
        )
        citation = Citation(
            product_id=plan.product_id,
            contract_version=context.product["contract_version"],
            columns=plan.columns_used,
            as_of=executed.as_of,
        )
        thin = int(self._rubric.number(THIN_EVIDENCE_ROWS_PATH))
        confidence = self._rubric.number(
            CONFIDENCE_THIN_PATH if executed.rows_scanned < thin else CONFIDENCE_FULL_PATH
        )

        return Answer(
            headline=headline,
            narrative=narrative,
            visual=visual,
            table=table_payload,
            citations=[citation],
            kpi_definitions=[plan.kpi_id],
            tool_calls=[call],
            rows_scanned=executed.rows_scanned,
            latency_ms=elapsed_ms(started),
            # No model is called, so no tokens are consumed. Reporting a
            # plausible count would make the trace a fiction.
            tokens_in=0,
            tokens_out=0,
            cost_usd=cost,
            confidence=confidence,
            runtime=self.name,
            claims=claims,
            notes=notes,
        )

    def _tool_cost_class(
        self, connection: psycopg.Connection[Any], agent_version_id: str, tool_name: str
    ) -> str:
        row = fetch_one(
            connection,
            "SELECT cost_class FROM agent_tool_binding "
            "WHERE agent_version_id = %s AND tool_name = %s",
            (agent_version_id, tool_name),
        )
        if row is None:
            raise OutOfScope(
                f"this agent version has no binding for the tool {tool_name!r}; "
                "a query it is not granted is not run"
            )
        return str(row["cost_class"])
