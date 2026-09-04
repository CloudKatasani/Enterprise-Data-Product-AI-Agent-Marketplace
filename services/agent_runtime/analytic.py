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

import re
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
    EntitlementShortfall,
    OutOfScope,
    ToolCall,
)
from services.agents.entitlement import Readable, readable_columns
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
COST_PRECISION_PATH = "presentation.cost_precision"
CONFIDENCE_PRECISION_PATH = "presentation.confidence_precision"
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
    readable: Readable


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

    version = fetch_one(
        connection,
        "SELECT autonomy_level, out_of_scope FROM agent_version WHERE agent_version_id = %s",
        (request.agent_version_id,),
    )
    if version is None:
        raise OutOfScope(f"no agent version {request.agent_version_id}")
    if exchange is None:
        # Curated exchanges are the steward's own questions and are not probed
        # for action intent; anything else is.
        _refuse_at_boundary(connection, request.question, version)

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
        coverage = _match_coverage(
            connection, request.question, coverage_rows, list(version["out_of_scope"])
        )

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

    machine = fetch_one(
        connection,
        "SELECT a.machine_identity FROM agent a "
        "JOIN agent_version v ON v.agent_id = a.agent_id WHERE v.agent_version_id = %s",
        (request.agent_version_id,),
    )
    readable = readable_columns(
        connection,
        principal_id=request.principal_id,
        product_id=coverage["source_product_id"],
        agent_identity=machine["machine_identity"] if machine else None,
    )
    if not readable.granted:
        raise EntitlementShortfall(
            f"this answer reads {coverage['source_product_id']}, which you hold no live "
            "grant on",
            asset_id=coverage["source_product_id"],
            required_scope=readable.scope,
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
        readable=readable,
    )


# These agents answer analytical questions about aggregates. Two kinds of
# request are refused before coverage is even consulted, because a coverage map
# that happens to mention "claims" must not make "is this claim covered?"
# answerable:
#
#   1. a request to *do* something, and
#   2. a request about one pointed-at or named record.
#
# Both are recognised lexically. That is a real limitation and worth stating: it
# is a vocabulary of action and of singularity, not an understanding of intent.
# It is extended when a boundary is declared that it does not yet catch, and the
# boundary probes in seed/eval/<agent>/boundary.yaml are what prove it still
# catches the ones already declared.
ACTION_VERBS = frozenset({
    "activate", "agree", "apply", "approve", "authorise", "authorize", "bind", "book",
    "cancel", "carry", "change", "close", "commit", "create", "credit", "delete",
    "disable", "dispatch", "draft", "drop", "enable", "execute", "extend", "file",
    "increase", "issue", "lower", "move", "open", "order", "place", "put", "raise",
    "reduce", "reroute", "reschedule", "retune", "revoke", "schedule", "send", "sent",
    "set", "sign", "split", "submit", "substitute", "switch", "turn", "update", "write",
})

# Words that make a question about one record rather than a population.
SINGULAR_MARKERS = frozenset({"individual", "named", "specific", "personally"})

# A request for the records themselves rather than a measure over them. Asking
# for record numbers is asking to re-identify, and it is refused whatever the
# caller's grant says, because the runtime has no shape of answer that returns
# rows of identifiers.
IDENTIFIER_NOUNS = frozenset({
    "address", "addresses", "email", "emails", "id", "identifier", "identifiers", "ids",
    "mrn", "mrns", "name", "names", "number", "numbers", "phone", "record", "records",
    "ssn",
})
LISTING_VERBS = frozenset({"give", "list", "return", "show", "tell"})

# "this week" is a period, not a record. Time nouns after "this"/"these" do not
# make a question singular.
PERIOD_NOUNS = frozenset({
    "week", "weeks", "month", "months", "quarter", "quarters", "year", "years",
    "day", "days", "period", "periods", "shift", "shifts", "season", "hour", "hours",
})

# Words that carry no signal when matching a question to a declared boundary.
STOPWORDS = frozenset({
    "a", "an", "and", "any", "are", "as", "at", "be", "by", "do", "for", "from", "give",
    "has", "have", "how", "in", "is", "it", "me", "my", "of", "on", "or", "our", "should",
    "that", "the", "their", "them", "there", "these", "this", "to", "us", "was", "we",
    "what", "when", "where", "which", "who", "will", "with", "without", "you", "your",
})

# Suffixes stripped before comparing a question to a declared boundary, so
# "file the SAR" reaches "Filing a suspicious activity report". Crude, and
# deliberately so: a stemmer that is wrong in an interesting way is worse here
# than one that is wrong in a boring way.
SUFFIXES = ("ing", "ies", "ed", "es", "s")


def _stem(word: str) -> str:
    for suffix in SUFFIXES:
        if len(word) > len(suffix) and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower()))


def _significant(text: str) -> set[str]:
    return {
        _stem(word)
        for word in re.findall(r"[a-z]+", text.lower())
        if word not in STOPWORDS
    }


def _nearest_boundary(question: str, boundaries: list[str]) -> str | None:
    """The declared boundary a refused question is closest to.

    Used only to write the refusal. Naming the limit the consumer hit is the
    difference between a refusal they can act on and a dead end.
    """
    words = _significant(question)
    best: tuple[int, str] | None = None
    for boundary in boundaries:
        overlap = len(words & _significant(boundary))
        if overlap and (best is None or overlap > best[0]):
            best = (overlap, boundary)
    return best[1] if best else None


def _asks_for_action(question: str) -> bool:
    return bool(set(re.findall(r"[a-z]+", question.lower())) & ACTION_VERBS)


def _asks_for_identifiers(question: str) -> bool:
    words = set(re.findall(r"[a-z]+", question.lower()))
    return bool(words & LISTING_VERBS and words & IDENTIFIER_NOUNS)


def _asks_about_one_record(question: str) -> bool:
    words = re.findall(r"[a-z]+", question.lower())
    if set(words) & SINGULAR_MARKERS:
        return True
    for index, word in enumerate(words[:-1]):
        if word in {"this", "these"} and words[index + 1] not in PERIOD_NOUNS:
            return True
    return False


def _refuse_at_boundary(
    connection: psycopg.Connection[Any], question: str, version: dict[str, Any]
) -> None:
    """Refuse an action or single-record request, naming the boundary it crosses."""
    if _asks_for_action(question):
        opening = (
            "That asks for something to be done. This agent explains what the data says; "
            "it does not carry anything out."
        )
    elif _asks_for_identifiers(question):
        opening = (
            "That asks for the records themselves. This agent returns measures over "
            "populations; it has no shape of answer that lists identifiers."
        )
    elif _asks_about_one_record(question):
        opening = (
            "That asks about one record. This agent answers on populations, using the "
            "certified measures it is bound to."
        )
    else:
        return

    boundaries = list(version["out_of_scope"])
    named = _nearest_boundary(question, boundaries)
    if named:
        opening += f' The boundary it crosses is "{named}".'
    elif boundaries:
        opening += " Its declared boundaries are: " + "; ".join(boundaries) + "."
    raise OutOfScope(opening, _covering_agents(connection, question))


def _covering_agents(connection: psycopg.Connection[Any], question: str) -> list[str]:
    """Other published agents whose capability statement matches the question.

    A refusal that names a route is worth more than a refusal that does not.
    """
    words = _significant(question)
    if not words:
        return []
    rows = fetch_all(
        connection,
        "SELECT a.agent_id, v.capability_statement FROM agent a "
        "JOIN agent_version v ON v.agent_version_id = a.current_version_id "
        "WHERE v.status = 'published'",
    )
    scored = sorted(
        
            (-len(words & _significant(row["capability_statement"])), row["agent_id"])
            for row in rows
        
    )
    return [agent_id for score, agent_id in scored if score]


def _match_coverage(
    connection: psycopg.Connection[Any],
    question: str,
    coverage_rows: list[dict[str, Any]],
    boundaries: list[str],
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
        # A word-level fallback so "churn" finds "Churn Rate". Words are taken
        # with the same regex the boundary matcher uses, not by splitting on
        # whitespace: "churn?" is the word "churn" with a question mark, and a
        # split that keeps the punctuation matches nothing.
        asked = _words(lowered)
        score += sum(
            1 for term in candidates if term and (_words(term) & asked)
        )
        if score and (best is None or score > best[0]):
            best = (score, row)

    if best is None:
        named = _nearest_boundary(question, boundaries)
        detail = "This agent does not cover that question. It answers on: " + ", ".join(
            sorted(row["kpi_id"] for row in coverage_rows)
        ) + "."
        if named:
            detail += f' It has also declared "{named}" out of scope.'
        raise OutOfScope(detail, _covering_agents(connection, question))
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


DEFAULT_GRAIN = "month"

# date_trunc accepts "quarter"; interval arithmetic does not. One period at each
# grain, spelled the way Postgres will take it.
GRAIN_INTERVAL = {
    "hour": "1 hour",
    "day": "1 day",
    "week": "1 week",
    "month": "1 month",
    "quarter": "3 months",
    "year": "1 year",
}

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
    covers: Any
    grain: str


# A certified measure is normally an aggregate. A few are per-row window
# expressions — a propensity decile, for instance — which cannot appear beside a
# GROUP BY. Those are computed row by row in a subquery and averaged over the
# group, so the register keeps one definition and the runtime does not need a
# second one for the grouped case.
WINDOW_MARKER = " over ("
WINDOWED_MEASURE = "window_measure"

DISTINCT_COLUMN = re.compile(r"count\s*\(\s*distinct\s+([a-z_][a-z0-9_]*)", re.IGNORECASE)


def _distinct_keys(kpi: dict[str, Any]) -> list[str]:
    parts = [kpi["numerator_expr"], kpi["denominator_expr"], kpi["expression"]]
    return sorted({
        match.lower()
        for part in parts
        if part
        for match in DISTINCT_COLUMN.findall(part)
    })


def _needs_single_period(
    connection: psycopg.Connection[Any], kpi: dict[str, Any], table: str
) -> bool:
    """Whether this measure may be pooled across periods, decided from the data.

    A distinct count is not additive, but that only matters when the thing being
    counted recurs. ``count(distinct transaction_id)`` over two months is the
    number of transactions in both, because a transaction happens once. But
    ``count(distinct subscriber_id) filter (where churn_flag)`` over thirty-six
    months counts everyone who ever churned against everyone who was ever
    active, which is a lifetime attrition figure wearing a monthly rate's name —
    and it is out by two orders of magnitude.

    So the question is not "is there a DISTINCT" but "does this key recur", and
    the data answers it: a key whose distinct count is below the row count
    appears in more than one period. Where it does, the measure is computed
    inside a single period and the answer says which.
    """
    keys = _distinct_keys(kpi)
    if not keys:
        return False
    projections = ", ".join(
        f"count(DISTINCT {key}) < count(*) AS recurs_{index}"
        for index, key in enumerate(keys)
    )
    row = fetch_one(connection, f"SELECT {projections} FROM {table}")
    return row is not None and any(row.values())


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
    grain = plan.grain or DEFAULT_GRAIN
    if grain not in GRAIN_INTERVAL:
        raise OutOfScope(
            f"{grain!r} is not a grain this runtime can compute at; it supports "
            + ", ".join(sorted(GRAIN_INTERVAL))
        )
    period = f"date_trunc('{grain}', {time_column})"

    if plan.shape == planner.SHAPE_PERIOD:
        dimension = period
        label = "period"
        order = "1"
    elif plan.shape == planner.SHAPE_COHORT:
        dimension = f"{plan.cohort_column}::text"
        label = "cohort"
        order = "1"
    elif plan.shape == planner.SHAPE_DISTRIBUTION:
        dimension = plan.slice_column or period
        label = plan.slice_column or "period"
        order = "1"
    else:
        dimension = plan.slice_column or period
        label = plan.slice_column or "period"
        order = "2 DESC NULLS LAST"

    # Grouping by period already isolates each one; the other shapes collapse
    # the time axis, and a non-additive measure cannot survive that.
    restrict = ""
    scanned_where = ""
    covers: Any = None
    if plan.shape != planner.SHAPE_PERIOD and _needs_single_period(
        connection, context.kpi, table
    ):
        # The *latest complete* period, not simply the latest. A load that ended
        # one day into September makes September a period with one day in it,
        # and a rate computed over one day of a month is not a monthly rate. A
        # period counts as complete when the data reaches its final day.
        latest_complete = (
            f"(SELECT coalesce(max(p.period) FILTER (WHERE p.last >= "
            f"   p.period + '{GRAIN_INTERVAL[grain]}'::interval - '1 day'::interval), "
            f"   max(p.period)) "
            f" FROM (SELECT {period} AS period, max({time_column}) AS last "
            f"       FROM {table} GROUP BY 1) p)"
        )
        restrict = f" WHERE {period} = {latest_complete}"
        scanned_where = restrict
        latest = fetch_one(connection, f"SELECT {latest_complete} AS covers")
        covers = latest["covers"] if latest else None

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
            f"(SELECT {dimension} AS {label}, {measure} AS {WINDOWED_MEASURE} "
            f"FROM {table}{restrict}) w"
        )
        restrict = ""
        grouped_by = label
        aggregate = f"avg({WINDOWED_MEASURE}) AS measure"
    else:
        aggregate = f"{measure} AS measure"

    sql = (
        f"SELECT {grouped_by} AS {label}, {aggregate}, count(*) AS observations "
        f"FROM {source}{restrict} GROUP BY 1 HAVING count(*) > 0 "
        f"ORDER BY {order} LIMIT %(limit)s"
    )
    arguments = {"limit": plan.limit}
    rows = fetch_all(connection, sql, arguments)

    # What was actually read, not what the table holds. A restricted query that
    # reported the whole table would overstate its own evidence, and the
    # thin-evidence check reads this number.
    scanned = fetch_one(connection, f"SELECT count(*) AS rows FROM {table}{scanned_where}")
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
            "grain": grain,
            "period": _label(covers) if covers is not None else "all periods",
        },
        rows_scanned=int(scanned["rows"]) if scanned else 0,
        duration_ms=duration_ms,
        as_of=as_of["as_of"] if as_of else None,
        covers=covers,
        grain=grain,
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
        # Quantised in the KPI's own unit, not in percentage points: the claim
        # and the sentence have to be the same number, and the sentence prints
        # whatever the unit's precision is.
        gap = _quantise(top - bottom, unit) if top is not None and bottom is not None else None
        if gap is not None:
            claims["cohort_gap"] = gap
        headline = (
            f"{name} is {_format(top, unit)} where {label} is {_label(top_label)} against "
            f"{_format(bottom, unit)} where it is {_label(bottom_label)}"
            + (f", a gap of {_format(gap, unit)}." if gap is not None else ".")
        )
        claims["cohort_high_observations"] = Decimal(top_count)
        claims["cohort_low_observations"] = Decimal(bottom_count)
        narrative = (
            f"Both cohorts are drawn from {context.product['product_id']} over the same "
            f"period: {top_count:,} observations against {bottom_count:,}."
            + _coverage_note(executed)
        )
    elif plan.shape == planner.SHAPE_DISTRIBUTION:
        top_label, median, observations = values[0]
        claims["median"] = median if median is not None else Decimal(0)
        tail = _quantise(rows[0].get("tail"), unit)
        # "p90", not "90%": the percentile is a label for the statistic, and a
        # bare 90 in the prose would read as a claim the answer has to cite.
        tail_name = "p" + format(
            rubric.number(TAIL_FRACTION_PATH) * rubric.number(PERCENT_SCALE_PATH), "f"
        ).rstrip("0").rstrip(".")
        if tail is not None:
            claims["tail"] = tail
        headline = (
            f"Median {name.lower()} is {_format(median, unit)} for {_label(top_label)}, "
            f"with {tail_name} at {_format(tail, unit)}."
        )
        claims["observations"] = Decimal(observations)
        narrative = (
            f"Across {observations:,} observations in {context.product['product_id']}; "
            f"the spread, not the mean, is what the question asked about."
            + _coverage_note(executed)
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
            + _coverage_note(executed)
        )

    # The prose states how much was read and how many groups came back. Those
    # are assertions like any other, so they are claimed like any other — the
    # groundedness suite is right to demand it.
    claims["rows_scanned"] = Decimal(executed.rows_scanned)
    claims["groups"] = Decimal(len(values))

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


def _fixed(value: Decimal, places: Decimal) -> str:
    """A decimal rendered to a rubric-chosen number of places."""
    return f"{value:.{int(places)}f}"


def _money(value: Decimal, places: Decimal) -> str:
    return f"${_fixed(value, places)}"


def _coverage_note(executed: _Executed) -> str:
    """Say which period the measure covers, when it covers only one.

    An answer restricted to the latest period and an answer pooled over the
    whole window are different numbers, and the reader cannot tell them apart
    from the figure alone. So the answer says which it is, in the sentence
    rather than in a footnote.
    """
    if executed.covers is None:
        return ""
    return (
        f" Computed within the {executed.grain} beginning {_label(executed.covers)}, "
        "because this measure counts entities that recur and cannot be pooled "
        "across periods."
    )


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
        # I12: the agent's binding intersected with the caller's grant. The
        # planner only ever sees columns both sides hold — and an empty
        # intersection is an entitlement shortfall, not a coverage gap. Letting
        # the planner refuse here would tell the caller the agent does not do
        # this, when in truth they are not allowed to see it.
        readable_binding = sorted(
            set(context.binding["columns_allowed"]) & context.readable.columns
        )
        if not readable_binding:
            raise EntitlementShortfall(
                f"your grant on {context.binding['product_id']} covers none of what this "
                "agent reads",
                asset_id=context.binding["product_id"],
                required_scope=context.readable.scope,
            )

        plan = planner.resolve(
            question=request.question,
            analysis_type=analysis_type,
            coverage=context.coverage,
            kpi=context.kpi,
            # I12: the agent's binding intersected with the caller's grant. The
            # planner only ever sees columns both sides hold.
            binding_columns=readable_binding,
            limit=int(self._rubric.number(ROW_LIMIT_PATH)),
        )

        if not context.readable.permits(plan.columns_used):
            raise EntitlementShortfall(
                f"answering this needs more of {plan.product_id} than your grant covers",
                asset_id=plan.product_id,
                required_scope=context.readable.scope,
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
            cost_display=_money(cost, self._rubric.number(COST_PRECISION_PATH)),
            confidence_display=_fixed(
                confidence, self._rubric.number(CONFIDENCE_PRECISION_PATH)
            ),
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
