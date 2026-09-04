"""M5.1-M5.3 — rule evaluation, scoring, blockers, tier weighting and snapshots.

Table-driven where the behaviour is arithmetic, so a rubric change moves the
expected value rather than the test (BUILD.md section 20: "rubric-driven
calculations change when the rubric changes").
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal

import psycopg
import pytest

from services.common.rubrics import load_current, rubric_from_rows
from services.quality import engine
from services.quality.estate import score_estate

TENANT = os.environ.get("TENANT_ID", "TEN-DEMO")
PINNED = datetime(2026, 1, 1, tzinfo=UTC)


def _criteria(**overrides: str) -> list[dict]:
    base = {
        "scale.minimum": "0",
        "scale.maximum": "100",
        "dimensions.completeness": "0.20",
        "dimensions.accuracy": "0.20",
        "dimensions.freshness": "0.20",
        "dimensions.consistency": "0.15",
        "dimensions.validity": "0.15",
        "dimensions.uniqueness": "0.10",
        "severity_weights.critical": "3.0",
        "severity_weights.high": "2.0",
        "severity_weights.medium": "1.0",
        "severity_weights.low": "0.5",
        "hard_blockers.critical_rule_failed": "39",
        "hard_blockers.classified_column_unprotected": "49",
        "tier_weights.tier1": "5.0",
        "tier_weights.tier2": "2.0",
        "tier_weights.tier3": "1.0",
        "bands.exemplary.min": "90",
        "bands.healthy.min": "75",
        "bands.watch.min": "60",
        "bands.at_risk.min": "40",
        "bands.unfit.min": "0",
    }
    base.update(overrides)
    rows = [
        {"path": path, "kind": "weight", "numeric_value": value, "text_value": None,
         "scope": None}
        for path, value in base.items()
    ]
    rows += [
        {"path": f"bands.{code}.label", "kind": "band", "numeric_value": None,
         "text_value": code.title(), "scope": None}
        for code in ("exemplary", "healthy", "watch", "at_risk", "unfit")
    ]
    rows.append(
        {"path": "redistribute_unmeasured_dimensions", "kind": "flag", "numeric_value": None,
         "text_value": "true", "scope": None}
    )
    return rows


def _rubric(*, scoped: list[dict] | None = None, **overrides: str):
    return rubric_from_rows(
        {"rubric_version_id": "RV-TEST", "code": "data_product_quality", "semver": "1.0.0",
         "source_hash": "test", "payload": {}},
        _criteria(**overrides) + (scoped or []),
    )


def _result(
    rule_id: str, dimension: str, severity: str, *, threshold: str | None = "100",
    observed: str | None = "100", tolerance: str | None = None,
    observed_value: str | None = None, passed: bool = True,
) -> engine.RuleResult:
    return engine.RuleResult(
        rule_id=rule_id,
        result_id=f"RES-{rule_id}",
        dimension=dimension,
        severity=severity,
        threshold_pct=Decimal(threshold) if threshold is not None else None,
        tolerance=Decimal(tolerance) if tolerance is not None else None,
        observed_pct=Decimal(observed) if observed is not None else None,
        observed_value=Decimal(observed_value) if observed_value is not None else None,
        passed=passed,
        evaluated_at=PINNED,
    )


# --- criterion normalisation ---------------------------------------------


@pytest.mark.parametrize(
    ("observed", "expected"),
    [("100", "100"), ("99.7", "99.7"), ("50", "50"), ("0", "0")],
)
def test_a_percentage_rule_scores_its_own_observation(observed: str, expected: str) -> None:
    rubric = _rubric()
    result = _result("R1", "completeness", "high", observed=observed)

    assert engine.criterion_score(result, rubric) == Decimal(expected)


def test_a_percentage_above_the_scale_is_clamped() -> None:
    rubric = _rubric()

    score = engine.criterion_score(_result("R1", "accuracy", "low", observed="140"), rubric)

    assert score == Decimal("100")


@pytest.mark.parametrize(
    ("tolerance", "observed", "expected"),
    [
        ("45", "10", "100"),   # comfortably inside
        ("45", "45", "100"),   # exactly on time is full marks
        ("45", "90", "50"),    # twice the tolerance halves the score
        ("45", "180", "25"),
    ],
)
def test_a_tolerance_rule_scores_full_marks_inside_and_degrades_outside(
    tolerance: str, observed: str, expected: str
) -> None:
    rubric = _rubric()
    result = _result(
        "R1", "freshness", "high", threshold=None, observed=None,
        tolerance=tolerance, observed_value=observed,
    )

    assert engine.criterion_score(result, rubric) == Decimal(expected)


def test_a_rule_with_no_scale_is_pass_or_fail() -> None:
    rubric = _rubric()
    passed = _result("R1", "validity", "high", threshold=None, observed=None, passed=True)
    failed = _result("R2", "validity", "high", threshold=None, observed=None, passed=False)

    assert engine.criterion_score(passed, rubric) == Decimal("100")
    assert engine.criterion_score(failed, rubric) == Decimal("0")


# --- dimension and composite ---------------------------------------------


def test_a_dimension_weights_its_rules_by_severity() -> None:
    """A critical rule and a low-severity one are not the same evidence."""
    rubric = _rubric()
    results = [
        _result("R1", "completeness", "critical", observed="100"),
        _result("R2", "completeness", "low", observed="0", passed=False),
    ]

    # (3.0*100 + 0.5*0) / 3.5
    assert engine.dimension_score(results, rubric) == Decimal("300") / Decimal("3.5")


def test_changing_a_severity_weight_changes_the_dimension_score() -> None:
    results = [
        _result("R1", "completeness", "critical", observed="100"),
        _result("R2", "completeness", "low", observed="0", passed=False),
    ]

    before = engine.dimension_score(results, _rubric())
    after = engine.dimension_score(results, _rubric(**{"severity_weights.low": "3.0"}))

    assert after < before


def test_the_composite_is_the_weighted_sum_of_its_dimensions() -> None:
    rubric = _rubric()
    results = [
        _result("R1", "completeness", "high", observed="100"),
        _result("R2", "accuracy", "high", observed="90"),
        _result("R3", "freshness", "high", observed="80"),
        _result("R4", "consistency", "high", observed="70"),
        _result("R5", "validity", "high", observed="60"),
        _result("R6", "uniqueness", "high", observed="50"),
    ]

    score = engine.score_from_evidence(
        product_id="DP-X", archetype="aggregate", results=results,
        unprotected_columns=[], rubric=rubric,
    )

    expected = (
        Decimal("0.20") * Decimal("100") + Decimal("0.20") * Decimal("90")
        + Decimal("0.20") * Decimal("80") + Decimal("0.15") * Decimal("70")
        + Decimal("0.15") * Decimal("60") + Decimal("0.10") * Decimal("50")
    )
    assert score.composite == expected.quantize(Decimal("0.01"))


def test_an_archetype_override_changes_the_composite() -> None:
    """A document corpus is not scored on consistency (the rubric says so)."""
    scoped = [
        {"path": "dimensions.consistency", "kind": "weight", "numeric_value": "0.00",
         "text_value": None, "scope": "document_corpus"},
        {"path": "dimensions.completeness", "kind": "weight", "numeric_value": "0.30",
         "text_value": None, "scope": "document_corpus"},
    ]
    rubric = _rubric(scoped=scoped)
    results = [
        _result("R1", "completeness", "high", observed="100"),
        _result("R2", "consistency", "high", observed="0", passed=False),
        _result("R3", "accuracy", "high", observed="100"),
    ]

    generic = engine.score_from_evidence(
        product_id="DP-X", archetype="aggregate", results=results,
        unprotected_columns=[], rubric=rubric,
    )
    corpus = engine.score_from_evidence(
        product_id="DP-X", archetype="document_corpus", results=results,
        unprotected_columns=[], rubric=rubric,
    )

    assert corpus.composite > generic.composite
    assert corpus.dimensions["consistency"].measured is False


def test_an_unmeasured_dimension_does_not_score_zero() -> None:
    """A product is scored on the evidence it was asked for."""
    rubric = _rubric()
    results = [_result("R1", "completeness", "high", observed="80")]

    score = engine.score_from_evidence(
        product_id="DP-X", archetype="aggregate", results=results,
        unprotected_columns=[], rubric=rubric,
    )

    assert score.composite == Decimal("80.00")
    assert score.evidence_ref["unmeasured_dimensions"] == [
        "accuracy", "consistency", "freshness", "uniqueness", "validity",
    ]


def test_redistribution_can_be_turned_off_in_the_rubric() -> None:
    rows = _criteria()
    for row in rows:
        if row["path"] == "redistribute_unmeasured_dimensions":
            row["text_value"] = "false"
    rubric = rubric_from_rows(
        {"rubric_version_id": "RV-TEST", "code": "data_product_quality", "semver": "1.0.0",
         "source_hash": "test", "payload": {}},
        rows,
    )
    results = [_result("R1", "completeness", "high", observed="80")]

    score = engine.score_from_evidence(
        product_id="DP-X", archetype="aggregate", results=results,
        unprotected_columns=[], rubric=rubric,
    )

    # Only completeness is measured, so its own weight is the whole denominator.
    assert score.composite == Decimal("80.00")


# --- blockers -------------------------------------------------------------


def test_a_critical_rule_failure_caps_the_composite_at_the_rubric_value() -> None:
    rubric = _rubric()
    results = [
        _result("R1", "completeness", "critical", observed="99", passed=False),
        _result("R2", "accuracy", "high", observed="100"),
    ]

    score = engine.score_from_evidence(
        product_id="DP-X", archetype="aggregate", results=results,
        unprotected_columns=[], rubric=rubric,
    )

    assert score.composite == Decimal("39.00")
    assert score.blocker_applied == "critical_rule_failed"
    assert score.band == "unfit"


def test_the_cap_moves_when_the_rubric_moves() -> None:
    rubric = _rubric(**{"hard_blockers.critical_rule_failed": "25"})
    results = [_result("R1", "completeness", "critical", observed="99", passed=False)]

    score = engine.score_from_evidence(
        product_id="DP-X", archetype="aggregate", results=results,
        unprotected_columns=[], rubric=rubric,
    )

    assert score.composite == Decimal("25.00")


def test_an_unprotected_classified_column_caps_the_composite() -> None:
    rubric = _rubric()
    results = [_result("R1", "completeness", "high", observed="100")]

    score = engine.score_from_evidence(
        product_id="DP-X", archetype="aggregate", results=results,
        unprotected_columns=["subscriber_id"], rubric=rubric,
    )

    assert score.composite == Decimal("49.00")
    assert score.blocker_applied == "classified_column_unprotected"


def test_two_blockers_do_not_cancel_out_the_strictest_wins() -> None:
    rubric = _rubric()
    results = [_result("R1", "completeness", "critical", observed="95", passed=False)]

    score = engine.score_from_evidence(
        product_id="DP-X", archetype="aggregate", results=results,
        unprotected_columns=["subscriber_id"], rubric=rubric,
    )

    assert score.composite == Decimal("39.00")
    assert set(score.evidence_ref["blockers_fired"]) == {
        "critical_rule_failed", "classified_column_unprotected",
    }


def test_a_cap_never_raises_a_score() -> None:
    """A blocker is a ceiling, not a floor."""
    rubric = _rubric()
    results = [
        _result("R1", "completeness", "critical", observed="5", passed=False),
        _result("R2", "accuracy", "high", observed="5"),
    ]

    score = engine.score_from_evidence(
        product_id="DP-X", archetype="aggregate", results=results,
        unprotected_columns=[], rubric=rubric,
    )

    assert score.composite == Decimal("5.00")
    assert score.blocker_applied is None


def test_scoring_with_no_evidence_is_refused_rather_than_defaulted() -> None:
    with pytest.raises(engine.ScoringError) as excinfo:
        engine.score_from_evidence(
            product_id="DP-X", archetype="aggregate", results=[],
            unprotected_columns=[], rubric=_rubric(),
        )

    assert "no rule results" in str(excinfo.value)


# --- evidence and snapshots ----------------------------------------------


def test_the_evidence_ref_records_everything_needed_to_replay() -> None:
    rubric = _rubric()
    results = [
        _result("R1", "completeness", "high", observed="90"),
        _result("R2", "accuracy", "critical", observed="100"),
    ]

    score = engine.score_from_evidence(
        product_id="DP-X", archetype="aggregate", results=results,
        unprotected_columns=[], rubric=rubric,
    )

    assert score.evidence_ref["rubric_version_id"] == "RV-TEST"
    assert score.evidence_ref["rule_ids"] == ["R1", "R2"]
    assert score.evidence_ref["result_ids"] == ["RES-R1", "RES-R2"]
    assert score.evidence_ref["archetype"] == "aggregate"
    assert set(score.evidence_ref["dimension_scores"]) == {"completeness", "accuracy"}
    assert set(score.evidence_ref["effective_weights"]) == {"completeness", "accuracy"}


@pytest.fixture()
def scored(db):
    from connectors.snowflake import harvest
    from connectors.snowflake.session import SandboxSession
    from scripts.seeders import kpis, products, rubrics, taxonomies, tenancy

    tenancy.seed(db, TENANT)
    taxonomies.seed(db, TENANT)
    rubrics.seed(db, TENANT)
    kpis.seed(db, TENANT)
    products.seed(db, TENANT)
    session = SandboxSession(
        os.environ["DATABASE_URL"], os.environ["DEMO_TIER_SCHEMA"].lower()
    )
    try:
        harvest.harvest_metadata(
            session, db, TENANT, load_current(db, harvest.RUBRIC_CODE)
        )
        harvest.harvest_quality(session, db, TENANT, load_current(db, harvest.RUBRIC_CODE))
    finally:
        session.close()
    return db


def test_a_snapshot_is_written_and_is_immutable(scored) -> None:
    rubric = load_current(scored, engine.RUBRIC_CODE)
    score = engine.score_product(scored, "DP-TEL-001", rubric)

    snapshot_id = engine.write_snapshot(scored, TENANT, score)

    with scored.cursor() as cursor:
        cursor.execute(
            "SELECT composite, band, rubric_version_id FROM quality_score_snapshot "
            "WHERE snapshot_id = %s",
            (snapshot_id,),
        )
        row = cursor.fetchone()
    assert row["composite"] == score.composite
    assert row["rubric_version_id"] == rubric.rubric_version_id

    with scored.cursor() as cursor, pytest.raises(psycopg.errors.RestrictViolation):
        cursor.execute(
            "UPDATE quality_score_snapshot SET composite = 1 WHERE snapshot_id = %s",
            (snapshot_id,),
        )


def test_replaying_a_written_snapshot_reproduces_it_exactly(scored) -> None:
    """M5 acceptance, against the database rather than a fixture."""
    rubric = load_current(scored, engine.RUBRIC_CODE)
    original = engine.score_product(scored, "DP-BNK-001", rubric)
    snapshot_id = engine.write_snapshot(scored, TENANT, original)

    replayed = engine.replay(scored, snapshot_id)

    assert replayed.composite == original.composite
    assert replayed.band == original.band
    assert replayed.blocker_applied == original.blocker_applied


def test_scoring_every_seed_product_produces_a_band_from_the_rubric(scored) -> None:
    rubric = load_current(scored, engine.RUBRIC_CODE)
    band_codes = {band.code for band in rubric.bands()}

    with scored.cursor() as cursor:
        cursor.execute(
            "SELECT product_id FROM data_product WHERE tenant_id = %s ORDER BY product_id",
            (TENANT,),
        )
        product_ids = [row["product_id"] for row in cursor.fetchall()]

    for product_id in product_ids:
        score = engine.score_product(scored, product_id, rubric)
        assert score.band in band_codes, product_id
        assert Decimal("0") <= score.composite <= Decimal("100"), product_id


def test_the_seed_estate_demonstrates_both_hard_blockers(scored) -> None:
    """The blockers have real cases in the seed data, not only in tests."""
    rubric = load_current(scored, engine.RUBRIC_CODE)

    critical = engine.score_product(scored, "DP-HLT-002", rubric)
    unprotected = engine.score_product(scored, "DP-ENG-001", rubric)

    assert critical.blocker_applied == "critical_rule_failed"
    assert unprotected.blocker_applied == "classified_column_unprotected"


def _latest_snapshots(connection) -> list[dict]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT DISTINCT ON (s.product_id) s.product_id, s.composite, p.tier "
            "FROM quality_score_snapshot s JOIN data_product p ON p.product_id = s.product_id "
            "WHERE s.tenant_id = %s ORDER BY s.product_id, s.computed_at DESC",
            (TENANT,),
        )
        return [dict(row) for row in cursor.fetchall()]


def test_the_estate_score_is_the_tier_weighted_mean_of_the_latest_snapshots(scored) -> None:
    """15.1: a thousand hygienic sandbox tables cannot mask ungoverned crown jewels.

    The expectation is recomputed from whatever snapshots exist rather than
    pinned, so the test states the invariant instead of a fixture's arithmetic.
    """
    rubric = load_current(scored, engine.RUBRIC_CODE)
    for product_id in ("DP-TEL-001", "DP-HLT-002", "DP-HLT-001"):
        engine.write_snapshot(
            scored, TENANT, engine.score_product(scored, product_id, rubric)
        )

    rows = _latest_snapshots(scored)
    numerator = sum(
        (Decimal(str(row["composite"])) * rubric.number(f"tier_weights.{row['tier']}")
         for row in rows),
        start=Decimal("0"),
    )
    denominator = sum(
        (rubric.number(f"tier_weights.{row['tier']}") for row in rows), start=Decimal("0")
    )
    plain = sum((Decimal(str(row["composite"])) for row in rows), start=Decimal("0"))

    estate = score_estate(scored, TENANT, rubric)

    assert estate.scored_products == len(rows)
    assert estate.weighted_composite == (numerator / denominator).quantize(Decimal("0.01"))
    assert estate.unweighted_mean == (plain / len(rows)).quantize(Decimal("0.01"))
    assert estate.document()["rubric_version_id"] == rubric.rubric_version_id
    assert set(estate.by_band) <= {band.code for band in rubric.bands()}


def test_a_tier_one_product_moves_the_estate_more_than_a_lower_tier_one(scored) -> None:
    """The whole point of tier weighting: the crown jewels count for more."""
    rubric = load_current(scored, engine.RUBRIC_CODE)
    for product_id in ("DP-TEL-001", "DP-HLT-002"):
        engine.write_snapshot(
            scored, TENANT, engine.score_product(scored, product_id, rubric)
        )
    baseline = score_estate(scored, TENANT, rubric).weighted_composite

    def collapse(product_id: str, snapshot_id: str) -> None:
        with scored.cursor() as cursor:
            # Explicitly the newest snapshot: `now()` inside a transaction is the
            # transaction's start time, which can predate a snapshot written by
            # the engine a moment earlier.
            cursor.execute(
                "INSERT INTO quality_score_snapshot (snapshot_id, tenant_id, product_id, "
                "rubric_version_id, composite, band, evidence_ref, computed_at) "
                "VALUES (%s, %s, %s, %s, 0, 'unfit', '{}'::jsonb, "
                "        clock_timestamp() + interval '1 hour')",
                (snapshot_id, TENANT, product_id, rubric.rubric_version_id),
            )

    collapse("DP-HLT-002", "QS-TIER2-TEST")
    after_tier_two = score_estate(scored, TENANT, rubric).weighted_composite
    tier_two_impact = baseline - after_tier_two

    collapse("DP-TEL-001", "QS-TIER1-TEST")
    tier_one_impact = after_tier_two - score_estate(scored, TENANT, rubric).weighted_composite

    assert tier_one_impact > tier_two_impact
    assert rubric.number("tier_weights.tier1") > rubric.number("tier_weights.tier2")
