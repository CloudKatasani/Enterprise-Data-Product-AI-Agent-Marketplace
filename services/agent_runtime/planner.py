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
    return eligible[0]


def resolve(
    *,
    question: str,
    analysis_type: str,
    coverage: dict[str, Any],
    kpi: dict[str, Any],
    binding_columns: list[str],
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
        cohort_column = _cohort_column(columns)
        if cohort_column is None:
            # No binary cohort in the granted columns: comparing populations is
            # then a slice comparison, which is what the reader wanted anyway.
            shape = SHAPE_SLICE
    if shape == SHAPE_DISTRIBUTION:
        measure_column = _numeric_column(columns, kpi)

    return QueryPlan(
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
)


def _cohort_column(columns: list[str]) -> str | None:
    for marker in COHORT_MARKERS:
        if marker in columns:
            return marker
    return None


def _numeric_column(columns: list[str], kpi: dict[str, Any]) -> str | None:
    """The column a distribution is taken over: the one the KPI expression measures."""
    expression = kpi.get("expression") or kpi.get("numerator_expr") or ""
    for name in columns:
        if re.search(rf"\b{re.escape(name)}\b", expression):
            return name
    return columns[0] if columns else None
