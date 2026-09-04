"""M1.3 — rubrics are data, resolved at read time by version id.

The M1 acceptance criterion is that changing a weight in quality.yaml and
re-seeding changes what consumers compute, with zero code changes. These tests
prove the two halves of that: the loader writes a new immutable version when the
YAML changes, and the resolver returns the new value while the old version stays
resolvable so a prior score can still be replayed.
"""

from __future__ import annotations

import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from scripts._paths import MANIFESTS
from scripts.seeders import kpis as kpi_seeder
from scripts.seeders import rubrics as rubric_seeder
from scripts.seeders import taxonomies, tenancy
from services.common.db import tenant_id
from services.common.rubrics import (
    CriterionNotFound,
    RubricNotFound,
    load_current,
    load_version,
)

# Reference ids (PTY-*, OU-*) are global primary keys, so the seeders run against
# the tenant this environment is configured for. Every test body runs inside the
# rolled-back transaction from the `db` fixture, so nothing it writes survives.
TENANT = tenant_id()


@pytest.fixture()
def manifests(tmp_path: Path, monkeypatch) -> Path:
    """A writable copy of manifests/ so a test can change a weight."""
    import scripts.seeders._base as base

    root = tmp_path / "manifests"
    shutil.copytree(MANIFESTS, root)
    monkeypatch.setattr(base, "MANIFESTS", root)
    return root


@pytest.fixture()
def seeded(db, manifests: Path):
    taxonomies.seed(db, TENANT)
    tenancy.seed(db, TENANT)
    rubric_seeder.seed(db, TENANT)
    return db


def _bump_version(manifests: Path, semver: str) -> None:
    path = manifests / "rubrics" / "quality.yaml"
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if line.startswith("version:"):
            lines[index] = f"version: {semver}"
            break
    else:
        raise AssertionError("quality.yaml declares no version")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _set_weight(manifests: Path, dimension: str, weight: str) -> None:
    path = manifests / "rubrics" / "quality.yaml"
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if line.strip().startswith(f"- {{ code: {dimension},"):
            prefix, _, _ = line.partition("weight:")
            lines[index] = f"{prefix}weight: {weight} }}"
            break
    else:
        raise AssertionError(f"no {dimension} dimension in quality.yaml")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_every_rubric_seeds_and_resolves(seeded) -> None:
    for code in (
        "data_product_quality",
        "catalog_ranking",
        "mesh_edges",
        "demand_scoring",
        "value_model",
        "finops",
        "agent_evaluation",
    ):
        rubric = load_current(seeded, code)
        assert rubric.rubric_version_id
        assert rubric.semver


def test_dimension_weights_resolve_from_the_manifest(seeded) -> None:
    quality = load_current(seeded, "data_product_quality")

    weights = quality.weights("dimensions")

    assert weights["freshness"] == Decimal("0.20")
    assert weights["uniqueness"] == Decimal("0.10")
    assert sum(weights.values()) == Decimal("1.00")


def test_archetype_overrides_resolve_by_scope_and_fall_back_to_the_base(seeded) -> None:
    quality = load_current(seeded, "data_product_quality")

    assert quality.number("dimensions.consistency") == Decimal("0.15")
    assert quality.number("dimensions.consistency", scope="document_corpus") == Decimal("0.00")
    # An archetype with no override resolves to the base weight rather than failing.
    assert quality.number("dimensions.consistency", scope="aggregate") == Decimal("0.15")


def test_bands_resolve_highest_first_and_map_a_score_to_a_band(seeded) -> None:
    quality = load_current(seeded, "data_product_quality")

    bands = quality.bands()

    assert [band.code for band in bands] == [
        "exemplary", "healthy", "watch", "at_risk", "unfit",
    ]
    assert quality.resolve_band(Decimal("94")).code == "exemplary"
    assert quality.resolve_band(Decimal("75")).code == "healthy"
    assert quality.resolve_band(Decimal("59.99")).code == "at_risk"
    assert quality.resolve_band(Decimal("0")).code == "unfit"
    assert quality.resolve_band(Decimal("90")).label == "Exemplary"


def test_thresholds_from_every_rubric_resolve_by_path(seeded) -> None:
    mesh = load_current(seeded, "mesh_edges")
    demand = load_current(seeded, "demand_scoring")
    finops = load_current(seeded, "finops")
    value = load_current(seeded, "value_model")
    ranking = load_current(seeded, "catalog_ranking")
    agent_eval = load_current(seeded, "agent_evaluation")

    assert mesh.number("render_threshold") == Decimal("0.25")
    assert mesh.number("review_required_below_confidence") == Decimal("0.80")
    assert demand.number("duplicate_detection.blocking_threshold") == Decimal("0.75")
    assert demand.number("theme_escalation.distinct_teams_min") == Decimal("5")
    assert finops.number("dormant_grant_days") == Decimal("60")
    assert finops.number("cost_classes.large") == Decimal("1000")
    assert value.number("deflection.loaded_analyst_rate_usd_hour") == Decimal("96")
    assert value.number(
        "deflection.avg_manual_minutes_by_question_class.driver_ranking.sample_size"
    ) == Decimal("34")
    assert ranking.number("fusion.k") == Decimal("60")
    assert ranking.number("certification_multiplier.deprecated") == Decimal("0")
    assert agent_eval.number("suites.groundedness.pass_threshold_pct") == Decimal("100")
    assert agent_eval.flag("suites.groundedness.blocking") is True
    assert agent_eval.flag("suites.consistency.blocking") is False


def test_an_unknown_path_raises_rather_than_defaulting(seeded) -> None:
    quality = load_current(seeded, "data_product_quality")

    with pytest.raises(CriterionNotFound) as excinfo:
        quality.number("dimensions.timeliness")

    assert "timeliness" in str(excinfo.value)


def test_an_unknown_rubric_raises(seeded) -> None:
    with pytest.raises(RubricNotFound):
        load_current(seeded, "not_a_rubric")


def test_reseeding_unchanged_yaml_is_a_no_op(seeded, manifests: Path) -> None:
    before = load_current(seeded, "data_product_quality")

    assert rubric_seeder.seed(seeded, TENANT) == 0

    after = load_current(seeded, "data_product_quality")
    assert after.rubric_version_id == before.rubric_version_id


def test_changing_a_weight_and_reseeding_changes_what_consumers_resolve(
    seeded, manifests: Path
) -> None:
    """M1 acceptance, with no code change anywhere between the two assertions."""
    original = load_current(seeded, "data_product_quality")
    assert original.number("dimensions.freshness") == Decimal("0.20")

    _set_weight(manifests, "freshness", "0.40")
    _set_weight(manifests, "accuracy", "0.00")
    _bump_version(manifests, "1.1.0")
    rubric_seeder.seed(seeded, TENANT)

    updated = load_current(seeded, "data_product_quality")

    assert updated.rubric_version_id != original.rubric_version_id
    assert updated.number("dimensions.freshness") == Decimal("0.40")
    assert updated.number("dimensions.accuracy") == Decimal("0.00")


def test_a_superseded_version_stays_resolvable_so_a_score_can_be_replayed(
    seeded, manifests: Path
) -> None:
    original = load_current(seeded, "data_product_quality")

    _set_weight(manifests, "freshness", "0.40")
    _bump_version(manifests, "1.1.0")
    rubric_seeder.seed(seeded, TENANT)

    replayed = load_version(seeded, original.rubric_version_id)

    assert replayed.number("dimensions.freshness") == Decimal("0.20")
    assert replayed.source_hash == original.source_hash


def test_a_weighted_composite_moves_when_the_rubric_moves(seeded, manifests: Path) -> None:
    """The consumer-side half of the acceptance: same code, different answer."""

    def composite(rubric, dimension_scores: dict[str, Decimal]) -> Decimal:
        weights = rubric.weights("dimensions")
        return sum(weights[code] * score for code, score in dimension_scores.items())

    scores = {
        "completeness": Decimal("100"), "accuracy": Decimal("100"), "freshness": Decimal("50"),
        "consistency": Decimal("100"), "validity": Decimal("100"), "uniqueness": Decimal("100"),
    }

    before = composite(load_current(seeded, "data_product_quality"), scores)

    _set_weight(manifests, "freshness", "0.40")
    _set_weight(manifests, "accuracy", "0.00")
    _bump_version(manifests, "1.1.0")
    rubric_seeder.seed(seeded, TENANT)

    after = composite(load_current(seeded, "data_product_quality"), scores)

    assert before == Decimal("90.00")
    assert after == Decimal("80.00")
    assert after != before


def test_the_kpi_register_seeds_every_manifest(db, manifests: Path) -> None:
    taxonomies.seed(db, TENANT)
    tenancy.seed(db, TENANT)

    count = kpi_seeder.seed(db, TENANT)

    manifest_count = len(list((manifests / "kpis").glob("*.yaml")))
    assert count == manifest_count
    with db.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM kpi_definition WHERE tenant_id = %s", (TENANT,))
        assert cursor.fetchone()[0] == manifest_count


def test_i1_rejects_a_second_active_definition_of_a_seeded_name(db, manifests: Path) -> None:
    import psycopg

    taxonomies.seed(db, TENANT)
    tenancy.seed(db, TENANT)
    kpi_seeder.seed(db, TENANT)

    with db.cursor() as cursor, pytest.raises(psycopg.errors.UniqueViolation):
        cursor.execute(
            "INSERT INTO kpi_definition (kpi_id, tenant_id, kpi_name, status, "
            "business_definition, grains_supported, slices_supported, unit, domain_code, "
            "steward_party_id, last_reviewed, review_months) "
            "VALUES ('KPI-DUP-999', %s, 'churn rate', 'draft', 'A rival definition', "
            "ARRAY['month'], ARRAY['region'], 'percent', 'customer', 'PTY-0031', "
            "DATE '2026-01-01', 12)",
            (TENANT,),
        )


def test_changing_content_without_bumping_the_version_is_refused(seeded, manifests: Path) -> None:
    """A rubric version is immutable: two different rubrics cannot share a name."""
    _set_weight(manifests, "freshness", "0.40")

    with pytest.raises(rubric_seeder.RubricVersionConflict) as excinfo:
        rubric_seeder.seed(seeded, TENANT)

    message = str(excinfo.value)
    assert "version: 1.0.0" in message
    assert "Bump 'version'" in message
