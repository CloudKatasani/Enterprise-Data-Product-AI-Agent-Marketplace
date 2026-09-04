"""M4.4 — all eight product detail tabs render from real metadata.

The acceptance criterion is that no tab shows placeholder content. A tab with
nothing to show returns ``empty`` and says what would produce the content, which
is a different thing from a blank panel: it tells the reader whether they are
looking at a gap in the estate or a gap in the page.
"""

from __future__ import annotations

import os

import pytest

from services.catalog import detail
from services.common.principal import Principal
from services.common.rubrics import load_current
from services.search import embedding
from services.search.index import reindex

TENANT = os.environ.get("TENANT_ID", "TEN-DEMO")
PRODUCT = "DP-TEL-001"

CONSUMER = Principal("PTY-0061", "Consumer", frozenset({"consumer"}))
OWNER = Principal("PTY-0031", "Owner", frozenset({"owner", "steward"}))


@pytest.fixture()
def catalog(db):
    from scripts.seeders import kpis, products, rubrics, taxonomies, tenancy

    taxonomies.seed(db, TENANT)
    tenancy.seed(db, TENANT)
    rubrics.seed(db, TENANT)
    kpis.seed(db, TENANT)
    products.seed(db, TENANT)
    kpis.backfill_source_of_record(db, TENANT)
    embedding.configure_from_rubric(load_current(db, embedding.RUBRIC_CODE))
    reindex(db, TENANT)
    return db


@pytest.fixture()
def harvested(catalog):
    """Usage, lineage and quality results, so the data-dependent tabs populate."""
    from connectors.snowflake import harvest
    from connectors.snowflake.session import SandboxSession

    session = SandboxSession(
        os.environ["DATABASE_URL"], os.environ["DEMO_TIER_SCHEMA"].lower()
    )
    try:
        rubric = load_current(catalog, harvest.RUBRIC_CODE)
        harvest.harvest_all(session, catalog, TENANT, rubric)
    finally:
        session.close()
    return catalog


def test_all_eight_tabs_are_assembled(catalog) -> None:
    tabs = detail.assemble(catalog, PRODUCT, CONSUMER)

    assert set(tabs) == set(detail.TABS)


def test_every_tab_declares_a_state_and_never_returns_a_placeholder(catalog) -> None:
    tabs = detail.assemble(catalog, PRODUCT, CONSUMER)

    for name, tab in tabs.items():
        assert tab["state"] in {"populated", "partial", "partial_permission", "empty"}, name
        if tab["state"] == "empty":
            # An empty tab must say what would fill it.
            assert tab.get("why"), name
            assert len(tab["why"]) > len("empty"), name
        else:
            assert tab["data"] is not None, name


def test_the_overview_tab_carries_the_governance_facts(catalog) -> None:
    tab = detail.overview_tab(catalog, PRODUCT)

    assert tab["state"] == "populated"
    data = tab["data"]
    assert data["known_limitations"]
    assert data["known_limitations"].lower() not in {"none", "n/a", "tbd"}
    assert data["owner"]["name"]
    assert data["certified_kpis"]
    assert data["grain"]


def test_the_schema_tab_lists_classified_columns_but_masks_them_for_a_consumer(
    catalog,
) -> None:
    tab = detail.schema_tab(catalog, PRODUCT, frozenset())

    assert tab["state"] == "partial_permission"
    assert tab["required_scope"] == f"dp:{PRODUCT}:read_pii"
    columns = {column["name"]: column for column in tab["data"]["columns"]}
    # The existence and classification of a PII column is visible; its values are not.
    assert columns["subscriber_id"]["classification"] == ["pii", "identifier"]
    assert columns["subscriber_id"]["masked_for_caller"] is True
    assert columns["segment"]["masked_for_caller"] is False


def test_the_schema_tab_unmasks_for_a_caller_holding_the_pii_scope(catalog) -> None:
    tab = detail.schema_tab(catalog, PRODUCT, frozenset({f"dp:{PRODUCT}:read_pii"}))

    assert tab["state"] == "populated"
    assert all(not column["masked_for_caller"] for column in tab["data"]["columns"])


def test_the_quality_tab_is_empty_but_explains_itself_before_scoring(catalog) -> None:
    tab = detail.quality_tab(catalog, PRODUCT)

    assert tab["state"] == "empty"
    assert "scoring job" in tab["why"]
    # The rules are still listed: the reader can see what will be measured.
    assert tab["data"]["rules"]


def test_the_quality_tab_shows_contributing_results_once_harvested(harvested) -> None:
    tab = detail.quality_tab(harvested, PRODUCT)

    assert tab["data"]["contributing_results"]
    for result in tab["data"]["contributing_results"]:
        assert result["rule_id"]
        assert result["dimension"]
        assert result["source"] == "dmf"


def test_the_contract_tab_carries_all_four_guarantees_and_the_obligations(catalog) -> None:
    tab = detail.contract_tab(catalog, PRODUCT)

    assert tab["state"] == "populated"
    dimensions = {g["dimension"] for g in tab["data"]["guarantees"]}
    assert dimensions == {"freshness", "availability", "completeness", "accuracy"}
    assert tab["data"]["active"]["consumer_obligations"]
    assert tab["data"]["active"]["breach_process"]
    assert tab["data"]["active"]["classification"]["max_sensitivity"]


def test_the_endpoints_tab_lists_surfaces_and_whether_the_caller_may_use_them(
    catalog,
) -> None:
    tab = detail.endpoints_tab(catalog, PRODUCT, frozenset())

    assert tab["state"] == "partial_permission"
    surfaces = {endpoint["surface"] for endpoint in tab["data"]["endpoints"]}
    assert surfaces == {"sql", "rest", "mcp"}
    assert all(endpoint["granted"] is False for endpoint in tab["data"]["endpoints"])
    assert PRODUCT in tab["request_access_url"]


def test_the_lineage_tab_shows_harvested_upstreams_with_their_rationale(harvested) -> None:
    tab = detail.lineage_mesh_tab(harvested, PRODUCT)

    assert tab["state"] == "populated"
    assert tab["data"]["upstream"]
    for edge in tab["data"]["upstream"]:
        assert edge["rationale"]
        assert edge["confidence"] is not None


def test_the_consumption_tab_shows_the_estate_to_an_owner_and_not_to_a_consumer(
    harvested,
) -> None:
    as_consumer = detail.consumption_tab(harvested, PRODUCT, CONSUMER, frozenset())
    as_owner = detail.consumption_tab(harvested, PRODUCT, OWNER, frozenset())

    assert as_consumer["data"]["scope"] == "caller"
    assert "top_consumers" not in as_consumer["data"]
    assert as_owner["data"]["scope"] == "estate"
    assert "top_consumers" in as_owner["data"]


def test_the_consumption_tab_reports_denied_queries(harvested) -> None:
    tab = detail.consumption_tab(harvested, PRODUCT, OWNER, frozenset())

    assert any(day["denied_count"] > 0 for day in tab["data"]["daily"])


def test_the_value_tab_shows_every_assumption_with_its_sample_size_and_date(catalog) -> None:
    tab = detail.value_tab(catalog, PRODUCT)

    assert tab["state"] == "partial"
    assert "no measurement period has closed" in tab["why"]
    assert tab["data"]["case"]["attribution_confidence"] in {"high", "medium", "low"}
    for assumption in tab["data"]["assumptions"]:
        assert assumption["source"]
        assert assumption["dated"]
        assert assumption["value"] is not None


def test_every_seed_product_assembles_all_eight_tabs(catalog) -> None:
    with catalog.cursor() as cursor:
        cursor.execute("SELECT product_id FROM data_product WHERE tenant_id = %s", (TENANT,))
        product_ids = [row["product_id"] for row in cursor.fetchall()]

    assert len(product_ids) == 15
    for product_id in product_ids:
        tabs = detail.assemble(catalog, product_id, CONSUMER)
        assert set(tabs) == set(detail.TABS), product_id
        assert tabs["overview"]["state"] == "populated", product_id
        assert tabs["contract"]["state"] == "populated", product_id
        assert tabs["schema"]["state"] in {"populated", "partial_permission"}, product_id
