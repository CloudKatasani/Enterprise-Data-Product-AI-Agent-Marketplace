"""Turning a question into a query plan.

The analytic runtime answers by executing a query, so something has to decide
*which* query. That decision is made here, from three governed inputs and
nothing else:

* the agent's **coverage map** — which KPI, at which grains and slices;
* the **KPI definition** — the numerator, denominator or expression, resolved
  from the register rather than re-derived;
* the **analysis type** the exchange declares.

The planner never invents a measure and never reaches for a column outside the
agent's binding. A question it cannot place against the coverage map is out of
scope, and saying so is the correct answer (10.2).

Analysis types collapse into four shapes. Forty-odd names in the question bank
describe what a reader sees, not what the database does: a Pareto, a driver
ranking and a compliance ranking are all "group by a slice and order by the
measure", and pretending otherwise would mean forty near-identical query
builders drifting apart.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from services.agent_runtime.base import OutOfScope

# The four shapes every analysis type resolves to.
SHAPE_PERIOD = "by_period"
SHAPE_SLICE = "by_slice"
SHAPE_COHORT = "by_cohort"
SHAPE_DISTRIBUTION = "distribution"

ANALYSIS_SHAPE: dict[str, str] = {
    # Movement over time
    "period_comparison": SHAPE_PERIOD,
    "trend_comparison": SHAPE_PERIOD,
    "trend_segmented": SHAPE_PERIOD,
    "trend_by_category": SHAPE_PERIOD,
    "regulatory_tracking": SHAPE_PERIOD,
    "event_impact": SHAPE_PERIOD,
    "before_after": SHAPE_PERIOD,
    "event_analysis": SHAPE_PERIOD,
    # Comparing two populations
    "cohort_comparison": SHAPE_COHORT,
    "programme_eval": SHAPE_COHORT,
    "promotion_eval": SHAPE_COHORT,
    "association": SHAPE_COHORT,
    "shift_comparison": SHAPE_COHORT,
    "like_for_like": SHAPE_COHORT,
    "variance": SHAPE_COHORT,
    "scenario_framing": SHAPE_COHORT,
    # Spread of a measure
    "distribution": SHAPE_DISTRIBUTION,
    # Everything that is "group by a slice and order by the measure"
    "driver_ranking": SHAPE_SLICE,
    "impact_ranking": SHAPE_SLICE,
    "contribution_ranking": SHAPE_SLICE,
    "efficiency_ranking": SHAPE_SLICE,
    "adequacy_ranking": SHAPE_SLICE,
    "compliance_ranking": SHAPE_SLICE,
    "accuracy_ranking": SHAPE_SLICE,
    "performance_ranking": SHAPE_SLICE,
    "risk_ranking": SHAPE_SLICE,
    "ranking": SHAPE_SLICE,
    "pareto": SHAPE_SLICE,
    "concentration": SHAPE_SLICE,
    "decomposition": SHAPE_SLICE,
    "variance_decomposition": SHAPE_SLICE,
    "variance_to_plan": SHAPE_SLICE,
    "root_cause": SHAPE_SLICE,
    "correlation": SHAPE_SLICE,
    "comparison": SHAPE_SLICE,
    "pattern_detection": SHAPE_SLICE,
    "risk_cohort": SHAPE_SLICE,
    "risk_list": SHAPE_SLICE,
    "risk_forecast": SHAPE_SLICE,
    "risk_prioritization": SHAPE_SLICE,
    "cohort_targeting": SHAPE_SLICE,
    "opportunity_cohort": SHAPE_SLICE,
    "opportunity_matrix": SHAPE_SLICE,
    "gap_analysis": SHAPE_SLICE,
    "gap_quantification": SHAPE_SLICE,
    "backlog_profile": SHAPE_SLICE,
    "prioritization": SHAPE_SLICE,
    "workload": SHAPE_SLICE,
    "compliance": SHAPE_SLICE,
    "waste_analysis": SHAPE_SLICE,
    "excess_analysis": SHAPE_SLICE,
    "lost_sales": SHAPE_SLICE,
    "utilization_impact": SHAPE_SLICE,
    "basket_composition": SHAPE_SLICE,
    "action_draft": SHAPE_SLICE,
}

# Grain words a question can name, coarsest first.
GRAIN_WORDS = (
    ("year", ("year", "annual", "yearly", "ytd", "year to date")),
    ("quarter", ("quarter", "quarterly", "qtr")),
    ("month", ("month", "monthly")),
    ("week", ("week", "weekly", "this week", "last week")),
    ("day", ("day", "daily", "yesterday", "today")),
)

GRAIN_ORDER = ["day", "week", "month", "quarter", "year"]


# Which end of the ranking the question asked for. A question that asks which
# lane is thinnest and gets the fattest one back has been answered accurately
# and uselessly, and the reader cannot tell from the number.
#
# Two kinds of word do this, and they do not mean the same thing. A magnitude
# word names a direction outright: "most" is the top of the ranking whatever the
# measure means. A quality word names the good or the bad end, and which end of
# the ranking that is depends on the KPI — the worst delinquency rate is the
# highest, the worst margin is the lowest.
MAGNITUDE_HIGH = frozenset({
    "most", "highest", "largest", "greatest", "biggest", "top", "longest",
    "maximum", "max",
})
MAGNITUDE_LOW = frozenset({
    "lowest", "smallest", "fewest", "least", "bottom", "shortest", "minimum", "min",
})
BAD_END = frozenset({
    "worst", "weakest", "poorest", "thinnest", "slowest", "worse", "lagging",
    "behind", "struggling",
})
GOOD_END = frozenset({"best", "strongest", "fastest", "healthiest", "leading", "better"})

LOWER_IS_BETTER = "lower_is_better"


def wants_ascending(question: str, kpi: dict[str, Any]) -> bool:
    """Whether the ranking should put the smallest measure first.

    Magnitude words settle it on their own. Quality words are resolved against
    the KPI's declared direction, which is the only thing that knows whether a
    big number is a good one.
    """
    asked = _words(question)
    if asked & MAGNITUDE_LOW:
        return True
    if asked & MAGNITUDE_HIGH:
        return False
    lower_is_better = kpi.get("direction") == LOWER_IS_BETTER
    if asked & BAD_END:
        return not lower_is_better
    if asked & GOOD_END:
        return lower_is_better
    return False


@dataclass(frozen=True)
class QueryPlan:
    kpi_id: str
    product_id: str
    shape: str
    analysis_type: str
    grain: str | None
    slice_column: str | None
    cohort_column: str | None
    measure_column: str | None
    columns_used: tuple[str, ...]
    limit: int
    ascending: bool


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower()))


def choose_grain(question: str, supported: list[str]) -> str:
    """The grain the question asked for, else the coarsest the KPI supports.

    Coarsest rather than finest: a question with no time word is asking about
    the state of things, and answering it per day would bury the answer.
    """
    words = _words(question)
    for grain, markers in GRAIN_WORDS:
        if grain not in supported:
            continue
        if any(marker in question.lower() for marker in markers) or grain in words:
            return grain
    ordered = [grain for grain in reversed(GRAIN_ORDER) if grain in supported]
    if not ordered:
        raise OutOfScope("this measure declares no supported grain")
    return ordered[0]


def choose_slice(question: str, slices: list[str], columns: list[str]) -> str | None:
    """The slice the question named, else the first the coverage map declares.

    Only a slice the coverage map declares *and* the binding grants is eligible;
    a question about a dimension the agent cannot read is out of scope, not a
    silent substitution.
    """
    eligible = [name for name in slices if name in columns]
    if not eligible:
        return None
    lowered = question.lower()
    for name in eligible:
        if name.replace("_", " ") in lowered or name in lowered:
            return name
    # Then on the noun the column name ends in. A reader asks "which categories
    # hold visitors longest", not "which entry categories": the qualifier is
    # part of the column's name, not of the question. Exact matches are taken
    # first above, so a product carrying both `category` and `entry_category`
    # still resolves the unqualified word to the unqualified column.
    asked = _words(question)
    for name in eligible:
        noun = name.rsplit("_", 1)[-1]
        if _names(noun) & asked:
            return name
    # Then on any word of the column name. "Which vintages carry the worst
    # delinquency" is asking about `vintage_band`, and the qualifier the column
    # carries is on the other end of the name from the noun.
    for name in eligible:
        if any(_names(part) & asked for part in name.split("_")):
            return name
    return eligible[0]


def _names(word: str) -> set[str]:
    """A word and the plurals a question is likely to use for it."""
    return {word, f"{word}s", word.rstrip("y") + "ies" if word.endswith("y") else f"{word}es"}


def resolve(
    *,
    question: str,
    analysis_type: str,
    coverage: dict[str, Any],
    kpi: dict[str, Any],
    binding_columns: list[str],
    column_types: dict[str, str],
    limit: int,
) -> QueryPlan:
    shape = ANALYSIS_SHAPE.get(analysis_type)
    if shape is None:
        raise OutOfScope(
            f"this agent does not perform {analysis_type!r} analysis on {coverage['kpi_id']}"
        )

    columns = [name for name in coverage["columns_used"] if name in binding_columns]
    if not columns:
        raise OutOfScope(
            f"the agent's binding on {coverage['source_product_id']} grants none of the "
            f"columns {coverage['kpi_id']} needs"
        )

    grain = None
    slice_column = None
    cohort_column = None
    measure_column = None

    if shape in (SHAPE_PERIOD, SHAPE_COHORT, SHAPE_DISTRIBUTION):
        grain = choose_grain(question, list(coverage["supported_grains"]))
    if shape in (SHAPE_SLICE, SHAPE_COHORT, SHAPE_DISTRIBUTION):
        slice_column = choose_slice(question, list(coverage["supported_slices"]), columns)
    if shape == SHAPE_COHORT:
        cohort_column = _cohort_column(columns, kpi)
        if cohort_column is None:
            # No binary cohort in the granted columns: comparing populations is
            # then a slice comparison, which is what the reader wanted anyway.
            shape = SHAPE_SLICE
    if shape == SHAPE_DISTRIBUTION:
        measure_column = _numeric_column(columns, kpi, column_types)
        if measure_column is None:
            # Nothing the agent may read is the column the measure is taken
            # over — the entitlement narrowed it away, or the KPI is a ratio
            # with no single measured column. A spread cannot be computed over
            # a column that is not there, and picking another one at random
            # would take the median of an identifier or a date. So the question
            # becomes the slice comparison it can actually answer.
            shape = SHAPE_SLICE

    return QueryPlan(
        ascending=shape == SHAPE_SLICE and wants_ascending(question, kpi),
        kpi_id=coverage["kpi_id"],
        product_id=coverage["source_product_id"],
        shape=shape,
        analysis_type=analysis_type,
        grain=grain,
        slice_column=slice_column,
        cohort_column=cohort_column,
        measure_column=measure_column,
        columns_used=tuple(columns),
        limit=limit,
    )


# Column-name markers for a boolean that splits a population into two cohorts.
COHORT_MARKERS = (
    "programme_enrolled", "standardised_changeover", "comparable_store", "substituted",
    "primary_relationship", "renewed", "bound", "on_formulary", "activated",
    "delivered_within_window", "in_top_accumulation_zone", "sar_filed", "feature_used",
    "curtailed_during_event", "passed_without_rework", "save_offer_accepted",
    "loyalty_identified", "autopay_enrolled", "digital_registered", "multi_line",
    "float_pool_used", "inspection_required", "tendered_to_spot", "change_deployed",
    "delinquent_30d", "filled_shift",
)


def _cohort_column(columns: list[str], kpi: dict[str, Any]) -> str | None:
    """A binary column that splits the population, but not one the measure uses.

    Splitting a save rate by ``save_offer_accepted`` compares the accepted
    offers against the rest and reports 100% against 0%, which is the
    definition restated rather than a finding. A cohort has to be independent
    of the measure to say anything, so a column the KPI's own expression
    references is not eligible; where none of the others is, the question is a
    slice comparison instead.
    """
    used = _expression_columns(kpi)
    for marker in COHORT_MARKERS:
        if marker in columns and marker not in used:
            return marker
    return None


def _expression_columns(kpi: dict[str, Any]) -> set[str]:
    parts = [kpi.get("numerator_expr"), kpi.get("denominator_expr"), kpi.get("expression")]
    text = " ".join(part for part in parts if part).lower()
    return set(re.findall(r"[a-z_][a-z0-9_]*", text))


# Contract types a spread can be taken over. A median of a boolean is a
# statement about how the flag is stored, and a median of an identifier is not a
# statement about anything.
NUMERIC_TYPES = frozenset({"number", "integer"})


def _numeric_column(
    columns: list[str], kpi: dict[str, Any], column_types: dict[str, str]
) -> str | None:
    """The column a distribution is taken over: the one the KPI measures.

    Both halves of the test matter. The column has to be the measured one —
    the denominator's ``count(distinct customer_id)`` is not what "how is it
    distributed" asks about — and it has to be a number, because the caller's
    entitlement decides which columns survive and the first survivor may be a
    date.
    """
    parts = [kpi.get("expression"), kpi.get("numerator_expr")]
    expression = " ".join(part for part in parts if part)
    for name in columns:
        if column_types.get(name) not in NUMERIC_TYPES:
            continue
        if re.search(rf"\b{re.escape(name)}\b", expression):
            return name
    return None
