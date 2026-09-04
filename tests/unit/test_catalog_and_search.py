"""M4 — catalog listing, faceting, cursor pagination and hybrid search.

The acceptance criterion this file exists for is the adversarial one: an exact
name match must never lose to a semantic neighbour. The rest covers the shapes
the portal depends on, including the partial-permission state, which is the
common case rather than an edge case.
"""

from __future__ import annotations

import os

import pytest

from services.common import http_status
from services.common.principal import Principal
from services.common.rubrics import load_current
from services.search import embedding, hybrid
from services.search.index import reindex

TENANT = os.environ.get("TENANT_ID", "TEN-DEMO")

CONSUMER = Principal(
    party_id="PTY-0061", display_name="Consumer", roles=frozenset({"consumer"})
)
OWNER = Principal(
    party_id="PTY-0031", display_name="Owner", roles=frozenset({"owner", "steward"})
)
# A consumer the entitlement seeder gives no grant to. The seeded personas all
# hold grants now, so proving the ungranted state needs someone who genuinely
# does not.
UNGRANTED = Principal(
    party_id="PTY-0064", display_name="Ungranted consumer", roles=frozenset({"consumer"})
)


@pytest.fixture()
def catalog(db):
    """A seeded catalog inside the rolled-back transaction."""
    from scripts.seeders import kpis, products, rubrics, taxonomies, tenancy

    tenancy.seed(db, TENANT)
    taxonomies.seed(db, TENANT)
    rubrics.seed(db, TENANT)
    kpis.seed(db, TENANT)
    products.seed(db, TENANT)
    kpis.backfill_source_of_record(db, TENANT)
    embedding.configure_from_rubric(load_current(db, embedding.RUBRIC_CODE))
    reindex(db, TENANT)
    return db


@pytest.fixture()
def ranking(catalog):
    return load_current(catalog, "catalog_ranking")


def _list(catalog, ranking, **kwargs):
    from services.catalog.products import list_products

    return list_products(catalog, TENANT, CONSUMER, ranking, **kwargs)


def test_the_catalog_lists_every_seeded_product(catalog, ranking) -> None:
    page, _ = _list(catalog, ranking, limit=int(ranking.number("page_size.max")))

    assert page.total == len(page.items)
    assert {item["product_id"] for item in page.items} >= {"DP-TEL-001", "DP-MFG-001"}


def test_the_card_has_its_twelve_elements_in_every_row(catalog, ranking) -> None:
    """Card anatomy is fixed so the grid stays scannable (section 12)."""
    page, _ = _list(catalog, ranking)

    required = {
        "product_id", "name", "purpose", "industry", "domain", "archetype", "certification",
        "sensitivity", "quality", "freshness", "owner", "adoption", "attached_agents",
        "certified_kpis", "endpoints", "access",
    }
    for item in page.items:
        assert required <= set(item), item["product_id"]
        assert set(item["quality"]) == {"composite", "band", "rubric_version_id", "computed_at"}
        assert set(item["adoption"]) == {"active_consumers", "distinct_teams"}


def test_a_consumer_without_a_grant_sees_the_asset_and_how_to_ask_for_it(
    catalog, ranking
) -> None:
    """Partial permission is the common case, not an error."""
    from services.catalog.products import list_products

    page, _ = list_products(catalog, TENANT, UNGRANTED, ranking)

    for item in page.items:
        assert item["access"]["granted"] is False
        assert item["access"]["required_scope"] == f"dp:{item['product_id']}:read"
        assert item["product_id"] in item["access"]["request_access_url"]
        # The metadata is still fully populated.
        assert item["purpose"]
        assert item["certified_kpis"]


def test_a_consumer_with_a_grant_is_shown_as_granted(catalog, ranking) -> None:
    """The other half of the same state: a live grant reads as granted.

    CONSUMER holds seeded grants on the products its agents read, so the card
    must say so — and must still carry the scope, because the card is the same
    card either way.
    """
    page, _ = _list(catalog, ranking)

    granted = [item for item in page.items if item["access"]["granted"]]
    assert granted, "the seeded consumer holds no grant; the entitlement seed did not run"
    for item in granted:
        assert item["access"]["required_scope"] == f"dp:{item['product_id']}:read"


def test_facet_counts_ignore_their_own_selection(catalog, ranking) -> None:
    """Selecting an industry must not collapse the industry list to one row."""
    from services.catalog.products import ProductFilters

    _, unfiltered = _list(catalog, ranking)
    industries = {f.code: f for f in unfiltered}["industry"]
    assert len(industries.values) > 1

    _, filtered = _list(
        catalog, ranking, filters=ProductFilters(industry=["telecommunications"])
    )
    by_code = {facet.code: facet for facet in filtered}

    assert len(by_code["industry"].values) == len(industries.values)
    assert any(value.selected for value in by_code["industry"].values)
    # Another facet is narrowed by the selection.
    assert {v.value for v in by_code["domain"].values} <= {"customer", "network_asset"}


def test_filters_narrow_the_result_set(catalog, ranking) -> None:
    from services.catalog.products import ProductFilters

    page, _ = _list(catalog, ranking, filters=ProductFilters(industry=["retail"]))

    assert {item["product_id"] for item in page.items} == {"DP-RTL-001", "DP-RTL-002"}


def test_an_endpoint_filter_does_not_duplicate_a_product(catalog, ranking) -> None:
    from services.catalog.products import ProductFilters

    page, _ = _list(catalog, ranking, filters=ProductFilters(endpoint=["sql", "mcp"]))

    ids = [item["product_id"] for item in page.items]
    assert len(ids) == len(set(ids))


def test_cursor_pagination_walks_every_row_exactly_once(catalog, ranking) -> None:
    seen: list[str] = []
    cursor = None
    while True:
        page, _ = _list(catalog, ranking, limit=4, cursor=cursor)
        seen.extend(item["product_id"] for item in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break

    assert len(seen) == len(set(seen))
    assert len(seen) == page.total


def test_a_malformed_cursor_is_a_bad_request_not_a_silent_restart(catalog, ranking) -> None:
    from services.common.problem import Problem

    with pytest.raises(Problem) as excinfo:
        _list(catalog, ranking, cursor="not-a-cursor")

    assert excinfo.value.status_code == http_status.BAD_REQUEST


def test_an_unknown_sort_is_refused_with_the_valid_options(catalog, ranking) -> None:
    from services.common.problem import Problem

    with pytest.raises(Problem) as excinfo:
        _list(catalog, ranking, sort="popularity")

    assert "expected one of" in excinfo.value.detail


def test_the_featured_band_only_promotes_certified_products_above_the_floor(
    catalog, ranking
) -> None:
    """A marketing surface that promotes an at-risk asset is a governance failure."""
    floor = float(ranking.number("featured_ranking.min_quality_composite"))

    page, _ = _list(catalog, ranking, featured=True, limit=100)

    for item in page.items:
        assert item["certification"] == "certified", item["product_id"]
        assert item["quality"]["composite"] is not None, item["product_id"]
        assert item["quality"]["composite"] >= floor, item["product_id"]


def test_an_unscored_product_is_never_featured(catalog, ranking) -> None:
    """The band would rather be short than promote an asset nobody has scored."""
    page, _ = _list(catalog, ranking, featured=True, limit=100)
    featured = {item["product_id"] for item in page.items}

    with catalog.cursor() as cursor:
        cursor.execute(
            "SELECT p.product_id FROM data_product p WHERE p.tenant_id = %s AND NOT EXISTS "
            "(SELECT 1 FROM quality_score_snapshot s WHERE s.product_id = p.product_id)",
            (TENANT,),
        )
        unscored = {row["product_id"] for row in cursor.fetchall()}

    assert featured & unscored == set()


# --- search ---------------------------------------------------------------


def _search(catalog, ranking, query: str, **kwargs):
    return hybrid.search(catalog, TENANT, query, ranking, **kwargs)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Subscriber Churn & Retention 360", "DP-TEL-001"),
        ("Network Experience & Fault Signal", "DP-TEL-002"),
        ("Omnichannel Sales & Basket Analytics", "DP-RTL-001"),
        ("Inventory Position & Replenishment Signal", "DP-RTL-002"),
        ("Grid Asset Health & Outage", "DP-UTL-001"),
        ("Claims Lifecycle & Loss Performance", "DP-INS-001"),
    ],
)
def test_an_exact_name_never_loses_to_a_semantic_neighbour(
    catalog, ranking, query: str, expected: str
) -> None:
    """M4 acceptance, with the adversarial cases that make it non-trivial.

    Each of these products has a near neighbour that shares most of its
    vocabulary — churn and retention, sales and inventory, outage and fault — so
    a purely semantic ranker would be free to prefer the wrong one.
    """
    results = _search(catalog, ranking, query)

    assert results.candidates
    assert results.candidates[0].asset_id == expected
    assert results.candidates[0].exact_name_match is True


def test_an_exact_kpi_name_beats_its_own_synonym_holder(catalog, ranking) -> None:
    results = _search(catalog, ranking, "Churn Rate", asset_types=["kpi"])

    assert results.candidates[0].asset_id == "KPI-CHURN-001"


def test_a_synonym_finds_the_kpi_that_declares_it(catalog, ranking) -> None:
    results = _search(catalog, ranking, "attrition rate", asset_types=["kpi"])

    assert "KPI-CHURN-001" in [candidate.asset_id for candidate in results.candidates]


def test_a_conceptual_query_finds_the_right_product_without_naming_it(
    catalog, ranking
) -> None:
    results = _search(catalog, ranking, "which subscribers are about to leave us")

    assert "DP-TEL-001" in [candidate.asset_id for candidate in results.candidates]


def test_every_result_explains_its_own_rank(catalog, ranking) -> None:
    results = _search(catalog, ranking, "inventory availability")

    for candidate in results.candidates:
        explanation = candidate.explanation()
        assert set(explanation["signals"]) == {
            "semantic_match", "quality_normalized", "active_consumers_90d_normalized",
            "certification_multiplier", "peer_affinity", "staleness_penalty",
        }
        assert explanation["lexical_rank"] or explanation["semantic_rank"]


def test_the_ranking_rubric_version_travels_with_the_results(catalog, ranking) -> None:
    results = _search(catalog, ranking, "churn")

    assert results.rubric_version_id == ranking.rubric_version_id


def test_a_deprecated_asset_scores_zero_because_its_multiplier_is_zero(
    catalog, ranking
) -> None:
    with catalog.cursor() as cursor:
        cursor.execute(
            "UPDATE data_product SET certification = 'deprecated' WHERE product_id = 'DP-MFG-001'"
        )

    results = _search(catalog, ranking, "manufacturing yield equipment effectiveness")

    scores = {c.asset_id: c.score for c in results.candidates}
    assert scores.get("DP-MFG-001", 0) == 0


def test_changing_a_ranking_weight_changes_the_order_with_no_code_change(
    catalog, ranking
) -> None:
    """The rubric is the ranking. Nothing here is a constant."""
    baseline = [c.asset_id for c in _search(catalog, ranking, "customer data").candidates]

    with catalog.cursor() as cursor:
        cursor.execute(
            "UPDATE rubric_criterion SET numeric_value = 0 "
            "WHERE rubric_version_id = %s AND path = 'weights.semantic_match'",
            (ranking.rubric_version_id,),
        )
    reranked = load_current(catalog, "catalog_ranking")
    altered = [c.asset_id for c in _search(catalog, reranked, "customer data").candidates]

    assert baseline != altered


def test_search_is_deterministic(catalog, ranking) -> None:
    first = [c.asset_id for c in _search(catalog, ranking, "claims leakage").candidates]
    second = [c.asset_id for c in _search(catalog, ranking, "claims leakage").candidates]

    assert first == second
