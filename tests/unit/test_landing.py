"""M11 — the front page: what it promotes, what it may say, and where it settles.

Three properties are worth pinning, because all three fail silently:

    the constellation layout is deterministic, so the picture in a deck matches
    the picture on the page;

    the activity ticker never serves an event below the rubric's occurrence
    floor, so it cannot become a side channel onto one team's activity;

    the theatre replays only recorded traces that are still recent, so a stale
    answer cannot survive a regression on the marketing surface.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta

import pytest

from services.common.rubrics import load_current
from services.landing import featured, layout, proof, pulse, theatre

TENANT = os.environ.get("TENANT_ID", "TEN-DEMO")


@pytest.fixture()
def landing(db):
    return load_current(db, "landing")


@pytest.fixture()
def mesh(db):
    return load_current(db, "mesh_edges")


@pytest.fixture()
def simulation(mesh):
    return layout.Simulation.from_rubric(mesh)


NODES = ("DP-A", "DP-B", "DP-C", "DP-D", "DP-E")
EDGES = (("DP-A", "DP-B", 0.9), ("DP-B", "DP-C", 0.4), ("DP-D", "DP-E", 0.7))


# ---------------------------------------------------------------------------
# The layout
# ---------------------------------------------------------------------------


def test_the_layout_settles_to_the_same_picture_every_time(simulation) -> None:
    """A hero that rearranged itself between two loads would be decoration.

    Determinism is also what lets a screenshot in a deck be the same graph the
    client sees when they open the page.
    """
    first = layout.settle(NODES, EDGES, simulation)
    second = layout.settle(NODES, EDGES, simulation)
    assert [place.document(simulation.precision) for place in first] == [
        place.document(simulation.precision) for place in second
    ]


def test_the_layout_does_not_depend_on_the_order_nodes_arrive_in(simulation) -> None:
    """Row order is an artefact of a query plan, not a property of the estate."""
    forward = {
        place.node_id: place.document(simulation.precision)
        for place in layout.settle(NODES, EDGES, simulation)
    }
    backward = {
        place.node_id: place.document(simulation.precision)
        for place in layout.settle(tuple(reversed(NODES)), EDGES, simulation)
    }
    assert forward == backward


def test_every_node_lands_inside_the_viewbox(simulation) -> None:
    for place in layout.settle(NODES, EDGES, simulation):
        assert simulation.collide_radius <= place.x <= simulation.extent
        assert simulation.collide_radius <= place.y <= simulation.extent


def test_connected_nodes_settle_closer_than_unconnected_ones(simulation) -> None:
    """The spring is the only thing that should decide distance.

    If this stopped holding, the hero would still look like a graph and would
    have stopped saying anything about the estate.
    """
    at = {place.node_id: place for place in layout.settle(NODES, EDGES, simulation)}

    def gap(first: str, second: str) -> float:
        return (
            (at[first].x - at[second].x) ** 2 + (at[first].y - at[second].y) ** 2
        ) ** 0.5

    assert gap("DP-A", "DP-B") < gap("DP-A", "DP-D")


def test_an_agent_orbits_only_the_products_it_reads(simulation) -> None:
    places = layout.settle(NODES, EDGES, simulation)
    at = {place.node_id: place for place in places}
    paths = layout.orbits({"AG-1": ["DP-A"], "AG-2": ["DP-D", "DP-E"]}, places, simulation)
    by_agent = {orbit.agent_id: orbit for orbit in paths}

    assert by_agent["AG-1"].centre_x == pytest.approx(at["DP-A"].x)
    # A two-product agent traces an ellipse between them, which is what makes it
    # legible as a two-product agent without a legend.
    assert by_agent["AG-2"].radius_x > by_agent["AG-2"].radius_y


def test_an_agent_bound_to_nothing_on_the_graph_gets_no_orbit(simulation) -> None:
    places = layout.settle(NODES, EDGES, simulation)
    assert layout.orbits({"AG-9": ["DP-NOT-DRAWN"]}, places, simulation) == []


def test_satellites_do_not_march_in_step(simulation) -> None:
    places = layout.settle(NODES, EDGES, simulation)
    paths = layout.orbits(
        {"AG-1": ["DP-A"], "AG-2": ["DP-B"], "AG-3": ["DP-C"]}, places, simulation
    )
    phases = {orbit.phase_turns for orbit in paths}
    assert len(phases) == len(paths)


def test_orbit_speed_is_a_seed_not_a_rate(simulation) -> None:
    """How fast a satellite may turn is a motion token, not an API response.

    The server says which satellite sits where in that range; the range itself
    stays in the token layer, so the two can never disagree.
    """
    places = layout.settle(NODES, EDGES, simulation)
    for orbit in layout.orbits({"AG-1": ["DP-A"]}, places, simulation):
        assert 0.0 <= orbit.speed_seed < 1.0


# ---------------------------------------------------------------------------
# The ticker
# ---------------------------------------------------------------------------


def test_no_ticker_event_falls_below_the_occurrence_floor(db, landing) -> None:
    """13.5's suppression rule, asserted rather than trusted.

    An event derived from one occurrence tells a visitor that a specific thing
    happened to a specific team today. The floor is what stops the strip being
    a side channel, and it is worth a test that would fail loudly.
    """
    floor = int(landing.number("ticker.min_occurrences"))
    events = pulse.ticker(db, landing)
    assert events
    for event in events:
        assert event.occurrences >= floor


def test_the_ticker_names_no_person_and_no_asset_identifier(db, landing) -> None:
    identifiers = {row for row in _all_asset_ids(db)}
    for event in pulse.ticker(db, landing):
        for identifier in identifiers:
            assert identifier not in event.text


def _all_asset_ids(db) -> set[str]:
    from services.common.db import fetch_all

    rows = fetch_all(
        db,
        "SELECT product_id AS id FROM data_product "
        "UNION ALL SELECT agent_id FROM agent "
        "UNION ALL SELECT party_id FROM party "
        "UNION ALL SELECT display_name FROM party",
    )
    return {str(row["id"]) for row in rows}


def test_the_ticker_spreads_across_event_classes(db, landing) -> None:
    """A strip that says the same kind of thing twelve times has said one thing."""
    events = pulse.ticker(db, landing)
    codes = [event.code for event in events]
    assert len(set(codes[: len(set(codes))])) == len(set(codes))


def test_every_counter_reads_the_platform(db, landing) -> None:
    counters = {counter.code: counter for counter in pulse.counters(db, landing)}
    assert set(counters) == {"products", "agents", "kpis", "answers"}
    for counter in counters.values():
        assert counter.value >= 0
        assert counter.href.startswith("/")


# ---------------------------------------------------------------------------
# Featuring
# ---------------------------------------------------------------------------


def test_nothing_below_the_quality_floor_is_ever_promoted(db, landing) -> None:
    """Featuring an at-risk asset is a governance failure, not a ranking one."""
    quality = load_current(db, "data_product_quality")
    floor = float(landing.number("featured.min_quality_composite"))
    for item in featured.rank(db, landing, quality, window_days=90):
        assert item.quality is not None and item.quality >= floor


def test_every_featured_card_states_why_it_is_there(db, landing) -> None:
    quality = load_current(db, "data_product_quality")
    for item in featured.rank(db, landing, quality, window_days=90):
        assert item.why.strip()


def test_the_industry_filter_narrows_the_same_ranking(db, landing) -> None:
    """M11.6: a tailored walkthrough shows the estate's own judgement."""
    quality = load_current(db, "data_product_quality")
    everything = featured.rank(db, landing, quality, window_days=90)
    code = everything[0].industry
    narrowed = featured.rank(db, landing, quality, industry=code, window_days=90)
    assert [item.product_id for item in narrowed] == [
        item.product_id for item in everything if item.industry == code
    ]


def test_a_steady_product_scores_the_middle_of_the_velocity_range() -> None:
    """Velocity compares a product to its own past, not to other products."""
    steady = featured._velocity(10.0, 10.0, 100.0, 100.0)
    rising = featured._velocity(30.0, 10.0, 100.0, 100.0)
    fading = featured._velocity(2.0, 10.0, 100.0, 100.0)
    assert fading < steady < rising
    assert steady == pytest.approx(0.5)


def test_an_industry_tile_with_nothing_behind_it_is_not_offered(db, landing) -> None:
    minimum = int(landing.number("industries.min_products"))
    for tile in featured.industries(db, landing):
        assert tile["products"] >= minimum


# ---------------------------------------------------------------------------
# The theatre
# ---------------------------------------------------------------------------


def test_the_theatre_serves_recorded_traces_with_their_stamp(db, landing) -> None:
    governance = load_current(db, "governance")
    traces = theatre.traces(db, governance, landing)
    assert traces
    for trace in traces:
        document = trace.document()
        assert document["mode"] == theatre.MODE_RECORDED
        assert document["recorded_at"]
        # A replay without the trace is a screenshot. The rail is what makes
        # the claim checkable.
        assert document["trace"]["tool_calls"]
        assert document["citations"]


def test_a_trace_older_than_the_window_is_not_replayed(db, landing, tmp_path) -> None:
    """A stale trace on the front page outlives the regression that broke it."""
    governance = load_current(db, "governance")
    live = theatre.traces(db, governance, landing)
    assert live

    target = theatre.TRACE_DIR / live[0].agent_id / f"{live[0].exchange_id}.json"
    original = target.read_text(encoding="utf-8")
    body = json.loads(original)
    age = int(landing.number("theatre.max_trace_age_days"))
    body["recorded_at"] = (datetime.now(UTC) - timedelta(days=age + 1)).isoformat()
    target.write_text(json.dumps(body), encoding="utf-8")
    try:
        after = theatre.traces(db, governance, landing)
        assert live[0].exchange_id not in {trace.exchange_id for trace in after}
    finally:
        target.write_text(original, encoding="utf-8")


def test_the_theatre_shows_breadth_before_depth(db, landing) -> None:
    governance = load_current(db, "governance")
    traces = theatre.traces(db, governance, landing)
    agents = [trace.agent_id for trace in traces]
    assert len(set(agents)) == len(agents) or len(set(agents)) >= len(agents) // 2


# ---------------------------------------------------------------------------
# Value proof
# ---------------------------------------------------------------------------


def test_a_proof_tile_states_its_window_and_its_source(db, landing, mesh) -> None:
    tiles = proof.tiles(db, landing, mesh)
    assert tiles
    for tile in tiles:
        assert tile["detail"].strip()
        assert tile["unit"]
        # An estate that has not deflected an hour should not claim a zero as
        # an achievement; empty tiles are omitted rather than shown.
        assert tile["value"] > 0
