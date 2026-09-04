"""The quality scoring engine (BUILD.md 15.1).

    criterion_score = normalise(rule_results)                      0..100
    dimension_score = weighted_sum(criterion_scores)               severity weights
    composite       = weighted_sum(dimension_scores)               archetype override applies
    apply hard_blockers (caps)                                     rubric data
    band            = resolve_band(composite)                      rubric data
    write quality_score_snapshot { rubric_version, evidence_ref }  immutable

Every number in that pipeline is a rubric value resolved at read time, and the
rubric version id is written into the snapshot. That is what makes a score
replayable: pin the evidence and the rubric version and the composite comes back
byte-identical, which is the M5 acceptance criterion and the golden suite's job.

Two judgement calls are made explicit rather than buried:

* **A rule's weight within its dimension is its severity.** A critical
  completeness rule and a low-severity one are not the same evidence.
* **A dimension nobody measured does not score zero.** Its weight is
  redistributed across the dimensions the product does declare, so a product is
  scored on the evidence it was asked for rather than punished for the rubric's
  shape. The rubric can turn this off.

The engine has no numeric literals. `Decimal` is used throughout: a composite
that differs in the last place from one computed a month ago is not replayable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

import psycopg

from services.common.db import fetch_all, fetch_one
from services.common.rubrics import Rubric

RUBRIC_CODE = "data_product_quality"

DIMENSIONS = (
    "completeness", "accuracy", "freshness", "consistency", "validity", "uniqueness",
)

# Scores are carried at this precision so a replayed composite matches exactly.
QUANTUM = Decimal("0.01")

# The identity element for a sum. The *scale* the scores sit on is rubric data
# (scale.minimum / scale.maximum), read wherever normalisation happens.
ZERO = Decimal(0)

BLOCKER_CRITICAL_RULE = "critical_rule_failed"
BLOCKER_UNPROTECTED_COLUMN = "classified_column_unprotected"

# Classifications that require a masking policy on the platform.
PROTECTED_CLASSIFICATIONS = ("pii", "phi", "pci", "credential")


class ScoringError(RuntimeError):
    """The evidence cannot produce a score. Never silently substituted."""


@dataclass(frozen=True)
class RuleResult:
    """One evaluation of one rule.

    A rule is measured one of three ways, and which one changes how it
    normalises: a percentage against a threshold where higher is better, a
    measure against a tolerance where lower is better (freshness lag), or a
    plain pass/fail with no scale to be partway along.
    """

    rule_id: str
    result_id: str
    dimension: str
    severity: str
    threshold_pct: Decimal | None
    tolerance: Decimal | None
    observed_pct: Decimal | None
    observed_value: Decimal | None
    passed: bool
    evaluated_at: datetime


@dataclass
class DimensionScore:
    dimension: str
    score: Decimal
    weight: Decimal
    rule_ids: tuple[str, ...]
    measured: bool


@dataclass
class Score:
    product_id: str
    composite: Decimal
    band: str
    dimensions: dict[str, DimensionScore]
    blocker_applied: str | None
    rubric_version_id: str
    evidence_ref: dict[str, Any]
    computed_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def _quantise(value: Decimal) -> Decimal:
    return value.quantize(QUANTUM, rounding=ROUND_HALF_EVEN)


def criterion_score(result: RuleResult, rubric: Rubric) -> Decimal:
    """One rule result, normalised onto the rubric's scale.

    A percentage rule scores its own observation: 99.7% completeness is 99.7.
    The threshold is what decides whether the rule *passed*, and passing or
    failing is what feeds severity and the hard blockers — it is not what the
    score measures. Scoring "did it clear the bar" instead would flatten every
    healthy product to full marks and throw away the difference between 99.7%
    and 100%, which is exactly the difference a consumer wants to see.

    A tolerance rule scores full marks inside tolerance and degrades in
    proportion outside it, because being early is not better than being on time.

    A rule with neither is pass or fail: there is no scale to be partway along.
    """
    floor = rubric.number("scale.minimum")
    ceiling = rubric.number("scale.maximum")

    if result.observed_pct is not None:
        return max(floor, min(ceiling, result.observed_pct))

    if result.tolerance is not None and result.observed_value is not None:
        # Lower is better: being inside the tolerance is full marks, and being
        # outside it degrades in proportion to how far outside.
        if result.observed_value <= result.tolerance:
            return ceiling
        if result.observed_value == ZERO:
            return ceiling
        ratio = (result.tolerance / result.observed_value) * ceiling
        return max(floor, min(ceiling, ratio))

    return ceiling if result.passed else floor


def dimension_score(results: list[RuleResult], rubric: Rubric) -> Decimal:
    """Severity-weighted mean of the criterion scores in one dimension."""
    if not results:
        raise ScoringError("a dimension with no rule results has no score")
    total_weight = ZERO
    accumulated = ZERO
    for result in results:
        weight = rubric.number(f"severity_weights.{result.severity}")
        total_weight += weight
        accumulated += weight * criterion_score(result, rubric)
    if total_weight == ZERO:
        raise ScoringError("every rule in this dimension carries zero severity weight")
    return accumulated / total_weight


def _dimension_weights(rubric: Rubric, archetype: str) -> dict[str, Decimal]:
    """Base weights, with the archetype override applied where one exists."""
    return {
        dimension: rubric.number(f"dimensions.{dimension}", scope=archetype)
        for dimension in DIMENSIONS
    }


def _redistribute(
    weights: dict[str, Decimal], measured: set[str], rubric: Rubric
) -> dict[str, Decimal]:
    """Spread the weight of unmeasured dimensions across the measured ones."""
    if not rubric.flag("redistribute_unmeasured_dimensions"):
        return weights
    measured_weight = sum((weights[d] for d in measured), start=ZERO)
    if measured_weight == ZERO:
        raise ScoringError(
            "every dimension this product measures carries zero weight in the rubric"
        )
    total = sum(weights.values(), start=ZERO)
    return {
        dimension: (weights[dimension] / measured_weight) * total
        for dimension in measured
    }


def _blockers(
    rubric: Rubric, results: list[RuleResult], unprotected_columns: list[str]
) -> list[tuple[str, Decimal]]:
    """Which hard blockers fired, and the cap each imposes."""
    fired: list[tuple[str, Decimal]] = []
    if any(result.severity == "critical" and not result.passed for result in results):
        fired.append(
            (BLOCKER_CRITICAL_RULE, rubric.number(f"hard_blockers.{BLOCKER_CRITICAL_RULE}"))
        )
    if unprotected_columns:
        fired.append(
            (
                BLOCKER_UNPROTECTED_COLUMN,
                rubric.number(f"hard_blockers.{BLOCKER_UNPROTECTED_COLUMN}"),
            )
        )
    return fired


def score_from_evidence(
    *,
    product_id: str,
    archetype: str,
    results: list[RuleResult],
    unprotected_columns: list[str],
    rubric: Rubric,
) -> Score:
    """Pure function: same evidence and same rubric, same composite. Always.

    Nothing here reads the clock or the database, which is what lets the golden
    suite pin a composite and replay it.
    """
    if not results:
        raise ScoringError(
            f"{product_id} has no rule results; a composite computed from no evidence "
            "would be a claim, not a measurement"
        )

    by_dimension: dict[str, list[RuleResult]] = {}
    for result in results:
        by_dimension.setdefault(result.dimension, []).append(result)

    weights = _dimension_weights(rubric, archetype)
    measured = {
        dimension for dimension in by_dimension if weights.get(dimension, ZERO) > ZERO
    }
    if not measured:
        raise ScoringError(
            f"{product_id} declares rules only for dimensions the rubric gives no weight"
        )
    effective = _redistribute(weights, measured, rubric)

    dimensions: dict[str, DimensionScore] = {}
    composite = ZERO
    total_weight = ZERO
    for dimension in DIMENSIONS:
        rows = sorted(by_dimension.get(dimension, []), key=lambda r: r.rule_id)
        if dimension not in measured:
            dimensions[dimension] = DimensionScore(
                dimension=dimension,
                score=ZERO,
                weight=ZERO,
                rule_ids=tuple(row.rule_id for row in rows),
                measured=False,
            )
            continue
        value = dimension_score(rows, rubric)
        weight = effective[dimension]
        dimensions[dimension] = DimensionScore(
            dimension=dimension,
            score=_quantise(value),
            weight=weight,
            rule_ids=tuple(row.rule_id for row in rows),
            measured=True,
        )
        composite += weight * value
        total_weight += weight

    composite = composite / total_weight if total_weight else ZERO

    fired = _blockers(rubric, results, unprotected_columns)
    blocker_applied: str | None = None
    if fired:
        # The strictest cap wins: two blockers do not cancel out.
        code, cap = min(fired, key=lambda item: item[1])
        if composite > cap:
            composite = cap
            blocker_applied = code

    composite = _quantise(composite)
    band = rubric.resolve_band(composite)

    evidence_ref = {
        "rubric_version_id": rubric.rubric_version_id,
        "rubric_semver": rubric.semver,
        "archetype": archetype,
        "rule_ids": sorted({result.rule_id for result in results}),
        "result_ids": sorted(result.result_id for result in results),
        "dimension_scores": {
            name: str(entry.score) for name, entry in sorted(dimensions.items())
            if entry.measured
        },
        "effective_weights": {
            name: str(entry.weight) for name, entry in sorted(dimensions.items())
            if entry.measured
        },
        "unmeasured_dimensions": sorted(
            name for name, entry in dimensions.items() if not entry.measured
        ),
        "blockers_fired": [code for code, _ in fired],
        "unprotected_columns": sorted(unprotected_columns),
    }

    return Score(
        product_id=product_id,
        composite=composite,
        band=band.code,
        dimensions=dimensions,
        blocker_applied=blocker_applied,
        rubric_version_id=rubric.rubric_version_id,
        evidence_ref=evidence_ref,
    )


# --- reading evidence and writing snapshots -------------------------------


LATEST_RESULTS_SQL = """
SELECT DISTINCT ON (r.rule_id)
       r.rule_id, r.result_id, q.dimension, q.severity, q.threshold_pct,
       q.tolerance_minutes, r.observed_pct, r.observed_value, r.passed, r.evaluated_at
FROM quality_result r
JOIN quality_rule q ON q.rule_id = r.rule_id
WHERE r.product_id = %s AND q.enabled
ORDER BY r.rule_id, r.evaluated_at DESC
"""

UNPROTECTED_COLUMNS_SQL = """
SELECT name FROM data_product_column
WHERE product_id = %s
  AND classification && %s::text[]
  AND (masking_policy IS NULL OR masking_policy = '')
ORDER BY name
"""


def _decimal_or_none(value: Any) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def _rule_result(row: dict[str, Any]) -> RuleResult:
    return RuleResult(
        rule_id=row["rule_id"],
        result_id=row["result_id"],
        dimension=row["dimension"],
        severity=row["severity"],
        threshold_pct=_decimal_or_none(row["threshold_pct"]),
        tolerance=_decimal_or_none(row["tolerance_minutes"]),
        observed_pct=_decimal_or_none(row["observed_pct"]),
        observed_value=_decimal_or_none(row["observed_value"]),
        passed=row["passed"],
        evaluated_at=row["evaluated_at"],
    )


def load_evidence(
    connection: psycopg.Connection[Any], product_id: str
) -> tuple[list[RuleResult], list[str]]:
    """The most recent result per enabled rule, plus any unprotected column."""
    rows = fetch_all(connection, LATEST_RESULTS_SQL, (product_id,))
    results = [_rule_result(row) for row in rows]
    unprotected = [
        row["name"]
        for row in fetch_all(
            connection, UNPROTECTED_COLUMNS_SQL, (product_id, list(PROTECTED_CLASSIFICATIONS))
        )
    ]
    return results, unprotected


def score_product(
    connection: psycopg.Connection[Any], product_id: str, rubric: Rubric
) -> Score:
    product = fetch_one(
        connection,
        "SELECT archetype_code FROM data_product WHERE product_id = %s",
        (product_id,),
    )
    if product is None:
        raise ScoringError(f"no data product {product_id!r}")
    results, unprotected = load_evidence(connection, product_id)
    return score_from_evidence(
        product_id=product_id,
        archetype=product["archetype_code"],
        results=results,
        unprotected_columns=unprotected,
        rubric=rubric,
    )


def write_snapshot(
    connection: psycopg.Connection[Any], tenant: str, score: Score
) -> str:
    """Append an immutable snapshot. The table refuses UPDATE and DELETE (rule 6)."""
    import json

    snapshot_id = f"QS-{score.product_id}-{score.computed_at.strftime('%Y%m%dT%H%M%S%f')}"
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO quality_score_snapshot (
              snapshot_id, tenant_id, product_id, rubric_version_id, composite,
              completeness, accuracy, freshness, consistency, validity, uniqueness,
              band, blocker_applied, evidence_ref, computed_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                snapshot_id, tenant, score.product_id, score.rubric_version_id,
                score.composite,
                *[
                    score.dimensions[dimension].score
                    if score.dimensions[dimension].measured
                    else None
                    for dimension in DIMENSIONS
                ],
                score.band, score.blocker_applied,
                json.dumps(score.evidence_ref, sort_keys=True), score.computed_at,
            ),
        )
    return snapshot_id


def replay(
    connection: psycopg.Connection[Any], snapshot_id: str
) -> Score:
    """Recompute a historical snapshot from its own evidence and rubric version.

    This is the M5 acceptance criterion made executable: the returned composite
    must equal the stored one exactly.
    """
    from services.common.rubrics import load_version

    snapshot = fetch_one(
        connection,
        "SELECT product_id, rubric_version_id, evidence_ref FROM quality_score_snapshot "
        "WHERE snapshot_id = %s",
        (snapshot_id,),
    )
    if snapshot is None:
        raise ScoringError(f"no snapshot {snapshot_id!r}")

    evidence = snapshot["evidence_ref"]
    rubric = load_version(connection, snapshot["rubric_version_id"])
    rows = fetch_all(
        connection,
        "SELECT r.rule_id, r.result_id, q.dimension, q.severity, q.threshold_pct, "
        "       q.tolerance_minutes, r.observed_pct, r.observed_value, r.passed, "
        "       r.evaluated_at "
        "FROM quality_result r JOIN quality_rule q ON q.rule_id = r.rule_id "
        "WHERE r.result_id = ANY(%s) ORDER BY r.rule_id",
        (evidence["result_ids"],),
    )
    results = [_rule_result(row) for row in rows]
    return score_from_evidence(
        product_id=snapshot["product_id"],
        archetype=evidence["archetype"],
        results=results,
        unprotected_columns=evidence["unprotected_columns"],
        rubric=rubric,
    )
