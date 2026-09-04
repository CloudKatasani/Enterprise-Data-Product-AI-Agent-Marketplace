"""M5.4 — a pinned rubric and a pinned evidence set reproduce a prior composite exactly.

BUILD.md section 20 asks the golden layer to prove that "pinned evidence + pinned
rubric reproduces a prior composite byte-identically (>= 3 snapshots)". These
fixtures replay without a database, so the rubric cannot have moved underneath
them: a change to the scoring engine surfaces here as a changed composite rather
than being absorbed by a re-read of current configuration.

Five snapshots are pinned, chosen to cover every path through the engine: a
healthy product, a very healthy one, a product capped by a critical rule
failure, a product capped by an unprotected classified column, and the weakest
healthy product in the estate.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from scripts._paths import SEED
from services.common.rubrics import rubric_from_rows
from services.quality.engine import RuleResult, score_from_evidence

GOLDEN_DIR = SEED / "golden" / "quality"


def _fixtures() -> list[Path]:
    return sorted(GOLDEN_DIR.glob("*.json"))


def _decimal(value: str | None) -> Decimal | None:
    return Decimal(value) if value is not None else None


def _rubric(fixture: dict):
    return rubric_from_rows(
        {
            "rubric_version_id": fixture["rubric"]["rubric_version_id"],
            "code": fixture["rubric"]["code"],
            "semver": fixture["rubric"]["semver"],
            "source_hash": fixture["rubric"]["source_hash"],
            "payload": {},
        },
        [
            {
                "path": row["path"],
                "kind": row["kind"],
                "numeric_value": row["numeric_value"],
                "text_value": row["text_value"],
                "scope": row["scope"],
            }
            for row in fixture["rubric"]["criteria"]
        ],
    )


def _results(fixture: dict) -> list[RuleResult]:
    from datetime import UTC, datetime

    pinned = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        RuleResult(
            rule_id=row["rule_id"],
            result_id=row["result_id"],
            dimension=row["dimension"],
            severity=row["severity"],
            threshold_pct=_decimal(row["threshold_pct"]),
            tolerance=_decimal(row["tolerance"]),
            observed_pct=_decimal(row["observed_pct"]),
            observed_value=_decimal(row["observed_value"]),
            passed=row["passed"],
            evaluated_at=pinned,
        )
        for row in fixture["results"]
    ]


def _replay(fixture: dict):
    return score_from_evidence(
        product_id=fixture["product_id"],
        archetype=fixture["archetype"],
        results=_results(fixture),
        unprotected_columns=fixture["unprotected_columns"],
        rubric=_rubric(fixture),
    )


def test_at_least_three_snapshots_are_pinned() -> None:
    assert len(_fixtures()) >= 3


@pytest.mark.parametrize("path", _fixtures(), ids=lambda p: p.stem)
def test_the_composite_reproduces_exactly(path: Path) -> None:
    fixture = json.loads(path.read_text(encoding="utf-8"))

    score = _replay(fixture)

    assert str(score.composite) == fixture["expected"]["composite"]


@pytest.mark.parametrize("path", _fixtures(), ids=lambda p: p.stem)
def test_the_band_and_blocker_reproduce(path: Path) -> None:
    fixture = json.loads(path.read_text(encoding="utf-8"))

    score = _replay(fixture)

    assert score.band == fixture["expected"]["band"]
    assert score.blocker_applied == fixture["expected"]["blocker_applied"]


@pytest.mark.parametrize("path", _fixtures(), ids=lambda p: p.stem)
def test_every_dimension_score_reproduces(path: Path) -> None:
    fixture = json.loads(path.read_text(encoding="utf-8"))

    score = _replay(fixture)

    measured = {
        name: str(entry.score) for name, entry in score.dimensions.items() if entry.measured
    }
    assert measured == fixture["expected"]["dimensions"]


@pytest.mark.parametrize("path", _fixtures(), ids=lambda p: p.stem)
def test_replay_is_stable_across_repeated_runs(path: Path) -> None:
    fixture = json.loads(path.read_text(encoding="utf-8"))

    first = _replay(fixture)
    second = _replay(fixture)

    assert first.composite == second.composite
    assert first.evidence_ref == second.evidence_ref


def test_a_critical_failure_caps_the_composite_at_the_rubric_value() -> None:
    """M5 acceptance: the cap is the rubric's number, not the engine's."""
    fixture = json.loads((GOLDEN_DIR / "DP-HLT-002.json").read_text(encoding="utf-8"))
    rubric = _rubric(fixture)

    score = _replay(fixture)

    assert score.blocker_applied == "critical_rule_failed"
    assert score.composite == rubric.number("hard_blockers.critical_rule_failed")
    assert any(not result["passed"] and result["severity"] == "critical"
               for result in fixture["results"])


def test_an_unprotected_classified_column_caps_the_composite() -> None:
    fixture = json.loads((GOLDEN_DIR / "DP-ENG-001.json").read_text(encoding="utf-8"))
    rubric = _rubric(fixture)

    score = _replay(fixture)

    assert score.blocker_applied == "classified_column_unprotected"
    assert score.composite == rubric.number("hard_blockers.classified_column_unprotected")
    assert fixture["unprotected_columns"]


def test_the_fixture_records_the_rubric_it_was_computed_under() -> None:
    for path in _fixtures():
        fixture = json.loads(path.read_text(encoding="utf-8"))
        assert fixture["rubric"]["rubric_version_id"]
        assert fixture["rubric"]["source_hash"]
        assert fixture["rubric"]["criteria"]


def test_changing_a_pinned_weight_changes_the_replayed_composite() -> None:
    """The fixture is load-bearing: it is not passing by coincidence."""
    fixture = json.loads((GOLDEN_DIR / "DP-TEL-001.json").read_text(encoding="utf-8"))
    original = _replay(fixture)

    for row in fixture["rubric"]["criteria"]:
        if row["path"] == "dimensions.freshness":
            row["numeric_value"] = "0.50"
        elif row["path"] == "dimensions.accuracy":
            row["numeric_value"] = "0.00"

    altered = _replay(fixture)

    assert altered.composite != original.composite
