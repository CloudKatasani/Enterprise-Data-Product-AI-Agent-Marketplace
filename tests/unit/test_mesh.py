"""M9 — both meshes and the three claims the milestone accepts on.

    every rendered edge has a rationale;
    edges below 0.80 confidence are held for review and do not render;
    blast-radius on a shared source returns the correct downstream set.

The third is checked against the lineage the harvest actually found, not against
a fixture, because the claim is about this deployment's data and a fixture would
prove only that the test agrees with itself.
"""

from __future__ import annotations

import os
from decimal import Decimal

import pytest

from services.common.rubrics import load_current
from services.mesh import agents as agent_mesh
from services.mesh import data as data_mesh
from services.mesh import divergence, factors
from services.search import embedding

TENANT = os.environ.get("TENANT_ID", "TEN-DEMO")


@pytest.fixture()
def rubric(db):
    embedding.configure_from_rubric(load_current(db, embedding.RUBRIC_CODE))
    return load_current(db, "mesh_edges")


@pytest.fixture()
def computed(db, rubric):
    return data_mesh.compute(db, rubric)


# ---------------------------------------------------------------------------
# I6 — every edge explains itself
# ---------------------------------------------------------------------------


def test_every_rendered_edge_has_a_rationale(db, rubric, computed) -> None:
    renderable, held = computed
    agent_edges, agent_held = agent_mesh.compute(db, rubric)

    for edge in [*renderable, *held, *agent_edges, *agent_held]:
        assert edge.rationale.strip(), edge
        # I6's database check is length > 10 after trimming. An edge whose
        # rationale would not survive the constraint must not be produced.
        assert len(edge.rationale.strip()) > _MIN_RATIONALE


_MIN_RATIONALE = 10


def test_a_rationale_names_the_signal_that_produced_the_edge(db, rubric, computed) -> None:
    """"strength 0.42" explains nothing. The reader needs to know which signal."""
    renderable, _ = computed
    for edge in renderable:
        assert edge.product_a in edge.rationale
        assert edge.product_b in edge.rationale or "built from" in edge.rationale


def test_every_edge_carries_all_five_factors(db, rubric, computed) -> None:
    """A reader has to be able to disagree with the edge, which needs the workings."""
    renderable, _ = computed
    for edge in renderable:
        assert set(edge.factors) == {
            data_mesh.FACTOR_SOURCE, data_mesh.FACTOR_ENTITY, data_mesh.FACTOR_KPI,
            data_mesh.FACTOR_SEMANTIC, data_mesh.FACTOR_CO_CONSUMPTION,
        }
        for value in edge.factors.values():
            assert {"value", "evidence", "detail"} == set(value)


# ---------------------------------------------------------------------------
# The confidence floor
# ---------------------------------------------------------------------------


def test_nothing_below_the_confidence_floor_is_returned_as_renderable(
    db, rubric, computed
) -> None:
    floor = float(rubric.number(data_mesh.CONFIDENCE_FLOOR))
    renderable, held = computed
    assert all(edge.confidence >= floor for edge in renderable)
    assert all(edge.confidence < floor for edge in held)


def test_the_table_refuses_a_low_confidence_edge_that_nobody_reviewed(db, rubric) -> None:
    """The floor is a database constraint, not a convention in the computation."""
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation), db.cursor() as cursor:
        cursor.execute(
            "INSERT INTO mesh_edge_data (edge_id, tenant_id, product_a, product_b, "
            "  edge_type, strength, factors, confidence, rationale) "
            "VALUES ('MED-TEST', %s, 'DP-BNK-001', 'DP-TEL-001', 'semantic', 0.5, "
            "        '{}'::jsonb, 0.10, 'a guess nobody has checked yet')",
            (TENANT,),
        )


def test_a_reviewed_edge_may_sit_below_the_floor(db, rubric) -> None:
    """Held for review means exactly that: a person can let one through."""
    with db.cursor() as cursor:
        cursor.execute(
            "INSERT INTO mesh_edge_data (edge_id, tenant_id, product_a, product_b, "
            "  edge_type, strength, factors, confidence, rationale, reviewed_by, "
            "  reviewed_at) VALUES ('MED-REVIEWED', %s, 'DP-BNK-001', 'DP-TEL-001', "
            "  'semantic', 0.5, '{}'::jsonb, 0.10, 'a steward looked and kept it', "
            "  'PTY-0031', now())",
            (TENANT,),
        )
        cursor.execute(
            "SELECT reviewed_by FROM mesh_edge_data WHERE edge_id = 'MED-REVIEWED'"
        )
        assert cursor.fetchone()["reviewed_by"] == "PTY-0031"


def test_a_reviewed_edge_survives_a_recompute(db, rubric) -> None:
    """A full replace must not throw away the one thing a person decided."""
    with db.cursor() as cursor:
        cursor.execute(
            "INSERT INTO mesh_edge_data (edge_id, tenant_id, product_a, product_b, "
            "  edge_type, strength, factors, confidence, rationale, reviewed_by, "
            "  reviewed_at) VALUES ('MED-KEEP', %s, 'DP-BNK-001', 'DP-TEL-001', "
            "  'semantic', 0.5, '{}'::jsonb, 0.10, 'a steward looked and kept it', "
            "  'PTY-0031', now())",
            (TENANT,),
        )
    renderable, _ = data_mesh.compute(db, rubric)
    data_mesh.persist(db, TENANT, renderable)
    with db.cursor() as cursor:
        cursor.execute("SELECT count(*) AS n FROM mesh_edge_data WHERE edge_id = 'MED-KEEP'")
        assert cursor.fetchone()["n"] == 1


def test_confidence_falls_when_a_signal_had_nothing_to_compare(db, rubric) -> None:
    """An edge assembled from one usable signal is reported as the weak claim it is."""
    weights = {"a": 0.5, "b": 0.5}
    signals = {
        "a": factors.scalar_factor("a", 0.9, detail="x", evidence=1.0),
        "b": factors.scalar_factor("b", 0.0, detail="y", evidence=0.0),
    }
    assert factors.confidence(signals, weights) == pytest.approx(0.5)
    assert factors.confidence(
        {"a": signals["a"], "b": factors.scalar_factor("b", 0.0, detail="y")}, weights
    ) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Blast radius
# ---------------------------------------------------------------------------


def test_blast_radius_returns_the_products_the_lineage_says_are_downstream(db) -> None:
    with db.cursor() as cursor:
        cursor.execute(
            "SELECT upstream_id, count(*) AS n FROM lineage_edge "
            "WHERE upstream_type = 'source_system' AND downstream_type = 'data_product' "
            "GROUP BY 1 HAVING count(*) > 1 ORDER BY n DESC LIMIT 1"
        )
        row = cursor.fetchone()
    if row is None:
        pytest.skip("no source system feeds more than one product")
    source = row["upstream_id"]

    with db.cursor() as cursor:
        # DISTINCT here too: the lineage records both "derives from" and
        # "reads" between the same pair, and a blast radius listing a product
        # once per relationship would overstate its reach.
        cursor.execute(
            "SELECT DISTINCT downstream_id FROM lineage_edge WHERE upstream_id = %s "
            "AND upstream_type = 'source_system' AND downstream_type = 'data_product' "
            "ORDER BY downstream_id",
            (source,),
        )
        expected = [item["downstream_id"] for item in cursor.fetchall()]

    result = data_mesh.blast_radius(db, source)
    listed = [product["product_id"] for product in result["products"]]
    assert listed == expected
    assert len(listed) == len(set(listed)), "a product appears once, whatever the lineage"
    assert result["source_id"] == source


def test_blast_radius_reaches_past_products_to_agents_and_grants(db) -> None:
    """The question is who finds out the hard way, and that is people, not tables."""
    with db.cursor() as cursor:
        cursor.execute(
            "SELECT e.upstream_id FROM lineage_edge e "
            "JOIN agent_product_binding b ON b.product_id = e.downstream_id "
            "WHERE e.upstream_type = 'source_system' LIMIT 1"
        )
        row = cursor.fetchone()
    if row is None:
        pytest.skip("no source feeds a product an agent is bound to")

    result = data_mesh.blast_radius(db, row["upstream_id"])
    assert result["agents"], "a source feeding a bound product must report its agents"
    downstream = {product["product_id"] for product in result["products"]}
    assert all(agent["product_id"] in downstream for agent in result["agents"])


def test_an_unknown_source_has_an_empty_blast_radius(db) -> None:
    result = data_mesh.blast_radius(db, "SRC-DOES-NOT-EXIST")
    assert result["products"] == []
    assert result["consumer_count"] == 0


# ---------------------------------------------------------------------------
# The signals themselves
# ---------------------------------------------------------------------------


def test_overlap_is_symmetric(db) -> None:
    """A mesh edge claims two assets are alike, and alike is symmetric."""
    left, right = {"a", "b", "c"}, {"a", "b"}
    assert factors.jaccard(left, right) == factors.jaccard(right, left)


def test_an_empty_side_is_no_information_not_zero_similarity(db) -> None:
    empty = factors.overlap_factor(
        "x", set(), {"a"}, noun=factors.Noun("thing", "things"),
        names=("A", "B"), listed_items=3,
    )
    assert empty.value == 0
    assert empty.evidence == 0, "nothing to compare is not evidence of difference"


def test_a_dependency_overrides_whatever_else_two_products_share(db, rubric) -> None:
    """Where one product is built from another, that is the relationship."""
    with db.cursor() as cursor:
        cursor.execute(
            "INSERT INTO lineage_edge (lineage_id, tenant_id, upstream_type, upstream_id, "
            "  downstream_type, downstream_id, relationship, harvested_from, confidence, "
            "  rationale) VALUES ('LIN-TEST', %s, 'data_product', 'DP-BNK-001', "
            "  'data_product', 'DP-BNK-002', 'derives_from', 'test', 1.0, "
            "  'planted by a test to prove dependency wins')",
            (TENANT,),
        )
    renderable, _ = data_mesh.compute(db, rubric)
    edge = next(
        item for item in renderable
        if {item.product_a, item.product_b} == {"DP-BNK-001", "DP-BNK-002"}
    )
    assert edge.edge_type == data_mesh.TYPE_DEPENDENCY


def test_the_marketplaces_own_test_runs_are_not_counted_as_usage(db, rubric) -> None:
    """The demo runner asking fourteen agents in ten seconds is not adoption.

    Tested by adding system-session interactions and asserting the co-usage
    signal does not move. Anything weaker would pass on data that happens not to
    contain any.
    """
    session_minutes = int(rubric.number(agent_mesh.SESSION_MINUTES))
    before = agent_mesh._co_usage(db, session_minutes)

    with db.cursor() as cursor:
        cursor.execute(
            "SELECT agent_version_id FROM agent_version "
            "WHERE agent_version_id IN (SELECT current_version_id FROM agent) "
            "ORDER BY agent_version_id LIMIT 2"
        )
        versions = [row["agent_version_id"] for row in cursor.fetchall()]
        for version in versions:
            cursor.execute(
                "INSERT INTO agent_interaction (interaction_id, tenant_id, "
                "  agent_version_id, principal_id, session_id, tier, question, "
                "  question_class, outcome, grounded, kpi_definitions, rows_scanned, "
                "  latency_ms, tokens_in, tokens_out, cost_usd, occurred_at) "
                "VALUES (%s, %s, %s, 'PTY-0061', %s, 'demo', 'q', 'ad_hoc', 'answered', "
                "        true, '{}', 0, 1, 0, 0, 0, now())",
                (
                    f"INT-SYSTEST-{version}", TENANT, version,
                    f"{agent_mesh.SYSTEM_SESSION_PREFIX}TEST",
                ),
            )

    after = agent_mesh._co_usage(db, session_minutes)
    assert after == before, (
        "co-usage moved when the marketplace's own runs were added; they are being "
        "counted as consumer usage"
    )


# ---------------------------------------------------------------------------
# Divergence (M9.5)
# ---------------------------------------------------------------------------


def test_shared_coverage_finds_kpis_more_than_one_agent_answers(db) -> None:
    shared = divergence.shared_coverage(db)
    for row in shared:
        assert len(row["agents"]) > 1


def test_two_agents_disagreeing_beyond_tolerance_is_a_divergence(db, rubric) -> None:
    shared = divergence.shared_coverage(db)
    if not shared:
        pytest.skip("no KPI is covered by more than one agent")
    row = shared[0]
    left, right = row["agents"][0], row["agents"][1]

    agreed = divergence.compare(
        db, rubric,
        {(left, row["kpi_id"]): Decimal("10.00"),
         (right, row["kpi_id"]): Decimal("10.01")},
    )
    assert agreed and not agreed[0].diverged

    apart = divergence.compare(
        db, rubric,
        {(left, row["kpi_id"]): Decimal("10.00"),
         (right, row["kpi_id"]): Decimal("18.00")},
    )
    assert apart and apart[0].diverged
    assert left in apart[0].document()["detail"]
    assert right in apart[0].document()["detail"]


def test_a_divergence_names_both_agents_not_one(db, rubric) -> None:
    """There is no way to tell from outside which is wrong.

    Section 15.5 raises the incident against both, and naming one would imply
    the other is right.
    """
    shared = divergence.shared_coverage(db)
    if not shared:
        pytest.skip("no KPI is covered by more than one agent")
    row = shared[0]
    result = divergence.compare(
        db, rubric,
        {(row["agents"][0], row["kpi_id"]): Decimal("1"),
         (row["agents"][1], row["kpi_id"]): Decimal("2")},
    )
    assert result[0].document()["agents"] == [row["agents"][0], row["agents"][1]]
