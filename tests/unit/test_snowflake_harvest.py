"""M3.2-M3.5 — the harvest passes, run against the stand-in platform.

These run the real statements through the real read-only guard and the real
mapping into the canonical model. Only where the rows come from differs from a
Snowflake account, so a change to a harvest query is exercised here rather than
silently diverging.
"""

from __future__ import annotations

import os
from decimal import Decimal

import pytest

from connectors.snowflake import harvest
from connectors.snowflake.session import SandboxSession
from scripts.seeders import kpis, products, rubrics, taxonomies, tenancy
from services.common.db import tenant_id
from services.common.rubrics import load_current

TENANT = tenant_id()
PRODUCT = "DP-TEL-001"


@pytest.fixture(scope="module")
def platform() -> SandboxSession:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        pytest.skip("DATABASE_URL is not set")
    session = SandboxSession(database_url, os.environ["DEMO_TIER_SCHEMA"].lower())
    yield session
    session.close()


@pytest.fixture()
def seeded(db):
    tenancy.seed(db, TENANT)
    taxonomies.seed(db, TENANT)
    rubrics.seed(db, TENANT)
    kpis.seed(db, TENANT)
    products.seed(db, TENANT)
    return db


@pytest.fixture()
def rubric(seeded):
    return load_current(seeded, harvest.RUBRIC_CODE)


def _one(db, sql: str, params: tuple) -> dict:
    with db.cursor() as cursor:
        cursor.execute(sql, params)
        row = cursor.fetchone()
    assert row is not None
    return dict(row)


def test_metadata_harvest_writes_columns_with_classification_and_sensitivity(
    seeded, platform, rubric
) -> None:
    result = harvest.harvest_metadata(platform, seeded, TENANT, rubric)

    assert result.counts["data_product_column"] > 0
    row = _one(
        seeded,
        "SELECT classification, sensitivity_code, data_type, nullable FROM data_product_column "
        "WHERE product_id = %s AND name = 'subscriber_id'",
        (PRODUCT,),
    )
    assert sorted(row["classification"]) == ["identifier", "pii"]
    assert row["sensitivity_code"] == "confidential"
    assert row["nullable"] is False


def test_harvested_columns_drive_the_derived_sensitivity(seeded, platform, rubric) -> None:
    """I5 end to end: classification tags on the platform set the product tier."""
    harvest.harvest_metadata(platform, seeded, TENANT, rubric)

    row = _one(
        seeded, "SELECT sensitivity_tier FROM data_product WHERE product_id = %s", (PRODUCT,)
    )
    assert row["sensitivity_tier"] == "confidential"


def test_lineage_harvest_distinguishes_declared_from_inferred(seeded, platform, rubric) -> None:
    harvest.harvest_lineage(platform, seeded, TENANT, rubric)

    with seeded.cursor() as cursor:
        cursor.execute(
            "SELECT relationship, confidence, rationale, harvested_from FROM lineage_edge "
            "WHERE downstream_id = %s ORDER BY relationship",
            (PRODUCT,),
        )
        edges = [dict(row) for row in cursor.fetchall()]

    assert edges
    declared = [edge for edge in edges if edge["relationship"] == "derives_from"]
    assert declared
    assert all(edge["confidence"] == Decimal("1.000") for edge in declared)
    assert all("dependency graph" in edge["rationale"] for edge in declared)

    inferred = [edge for edge in edges if edge["relationship"] == "reads"]
    if inferred:
        assert all(edge["confidence"] < Decimal("1.000") for edge in inferred)
        assert all("Inferred from access history" in edge["rationale"] for edge in inferred)


def test_every_lineage_edge_carries_a_rationale(seeded, platform, rubric) -> None:
    """Rule 4: every inference carries confidence and rationale."""
    harvest.harvest_lineage(platform, seeded, TENANT, rubric)

    with seeded.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) AS bad FROM lineage_edge "
            "WHERE tenant_id = %s AND (rationale IS NULL OR length(trim(rationale)) <= 10)",
            (TENANT,),
        )
        assert cursor.fetchone()["bad"] == 0


def test_usage_harvest_records_events_and_daily_aggregates(seeded, platform, rubric) -> None:
    result = harvest.harvest_usage(platform, seeded, TENANT, rubric)

    assert result.counts["usage_event"] > 0
    assert result.counts["usage_daily_agg"] > 0
    row = _one(
        seeded,
        "SELECT active_consumers, query_count, denied_count FROM usage_daily_agg "
        "WHERE asset_id = %s ORDER BY activity_date DESC LIMIT 1",
        (PRODUCT,),
    )
    assert row["active_consumers"] > 0
    assert row["query_count"] >= row["active_consumers"]


def test_permission_denied_queries_become_the_leading_indicator(seeded, platform, rubric) -> None:
    """15.6: permission-denied rate is a leading indicator of entitlement gaps."""
    harvest.harvest_usage(platform, seeded, TENANT, rubric)

    with seeded.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) AS denied FROM usage_event "
            "WHERE tenant_id = %s AND outcome = 'denied'",
            (TENANT,),
        )
        assert cursor.fetchone()["denied"] > 0


def test_usage_events_carry_the_purpose_the_query_declared(seeded, platform, rubric) -> None:
    harvest.harvest_usage(platform, seeded, TENANT, rubric)

    row = _one(
        seeded,
        "SELECT purpose_code FROM usage_event WHERE asset_id = %s AND purpose_code IS NOT NULL "
        "LIMIT 1",
        (PRODUCT,),
    )
    assert row["purpose_code"] == "analytics"


def test_cost_harvest_apportions_credits_and_records_the_method(seeded, platform, rubric) -> None:
    harvest.harvest_usage(platform, seeded, TENANT, rubric)
    result = harvest.harvest_cost(platform, seeded, TENANT, rubric)

    assert result.counts["cost_allocation"] > 0
    row = _one(
        seeded,
        "SELECT query_usd, source, tier FROM cost_allocation WHERE asset_id = %s LIMIT 1",
        (PRODUCT,),
    )
    assert row["query_usd"] > 0
    assert "apportioned by bytes_scanned" in row["source"]
    assert row["tier"] == "live"


def test_apportioned_cost_never_exceeds_the_metered_credits(seeded, platform, rubric) -> None:
    harvest.harvest_usage(platform, seeded, TENANT, rubric)
    harvest.harvest_cost(platform, seeded, TENANT, rubric)

    rate = load_current(seeded, harvest.RUBRIC_CODE).number("cost.credit_rate_usd")
    metered = platform.query(harvest.queries.WAREHOUSE_METERING, (harvest._since(30),))
    ceiling = sum(Decimal(str(row["credits_used"])) for row in metered) * rate

    with seeded.cursor() as cursor:
        cursor.execute(
            "SELECT coalesce(sum(query_usd), 0) AS spent FROM cost_allocation "
            "WHERE tenant_id = %s",
            (TENANT,),
        )
        spent = cursor.fetchone()["spent"]

    assert spent <= ceiling


def test_quality_harvest_matches_results_to_declared_rules_only(seeded, platform, rubric) -> None:
    result = harvest.harvest_quality(platform, seeded, TENANT, rubric)

    assert result.counts["quality_result"] > 0
    with seeded.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) AS orphaned FROM quality_result r "
            "LEFT JOIN quality_rule q ON q.rule_id = r.rule_id "
            "WHERE r.tenant_id = %s AND q.rule_id IS NULL",
            (TENANT,),
        )
        assert cursor.fetchone()["orphaned"] == 0


def test_quality_results_are_judged_against_the_rules_threshold(seeded, platform, rubric) -> None:
    harvest.harvest_quality(platform, seeded, TENANT, rubric)

    with seeded.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) AS wrong FROM quality_result r "
            "JOIN quality_rule q ON q.rule_id = r.rule_id "
            "WHERE r.tenant_id = %s AND q.threshold_pct IS NOT NULL "
            "AND r.passed <> (r.observed_pct >= q.threshold_pct)",
            (TENANT,),
        )
        assert cursor.fetchone()["wrong"] == 0


def test_a_full_harvest_writes_into_every_expected_table(seeded, platform, rubric) -> None:
    """M3 acceptance, harvest half: one product harvested end to end."""
    result = harvest.harvest_all(platform, seeded, TENANT, rubric)

    assert set(result.counts) == {
        "data_product_column",
        "lineage_edge",
        "usage_event",
        "usage_daily_agg",
        "cost_allocation",
        "quality_result",
    }
    assert all(count > 0 for count in result.counts.values())


def test_the_harvest_is_idempotent(seeded, platform, rubric) -> None:
    harvest.harvest_all(platform, seeded, TENANT, rubric)

    with seeded.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) AS n FROM data_product_column WHERE tenant_id = %s", (TENANT,)
        )
        first = cursor.fetchone()["n"]

    harvest.harvest_all(platform, seeded, TENANT, rubric)

    with seeded.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) AS n FROM data_product_column WHERE tenant_id = %s", (TENANT,)
        )
        assert cursor.fetchone()["n"] == first
