"""`/api/v1/landing` — the front page's data, and the event stream behind it.

Every route here serves an unauthenticated visitor, so none of them depends on a
principal. That is a deliberate boundary rather than an oversight: nothing the
front page shows may be anything a visitor is not entitled to see, and the way
to guarantee that is for these handlers to have no identity to widen. A signed-in
user gets a richer page from the ordinary catalog endpoints, which do check.

The stream is Server-Sent Events. It carries answer pulses for the hero
constellation and ticker updates, rate-limited by the motion layer's own budget
so the hero cannot strobe however busy the estate gets. It sends a comment
heartbeat rather than falling silent, because a stream that says nothing is
indistinguishable from one that has died — and the ticker's rule is that a dead
channel hides the band rather than freezing it.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from services.api.deps import request_connection, rubric_dependency, tenant
from services.common import http_status
from services.common.db import connect, fetch_all
from services.common.rubrics import Rubric
from services.landing import featured, layout, proof, pulse, theatre

router = APIRouter(prefix="/landing", tags=["landing"])
events_router = APIRouter(prefix="/events", tags=["landing"])

Connection = Annotated[psycopg.Connection[Any], Depends(request_connection)]
Tenant = Annotated[str, Depends(tenant)]
LandingRubric = Annotated[Rubric, Depends(rubric_dependency("landing"))]
MeshRubric = Annotated[Rubric, Depends(rubric_dependency("mesh_edges"))]
QualityRubric = Annotated[Rubric, Depends(rubric_dependency("data_product_quality"))]
RankingRubric = Annotated[Rubric, Depends(rubric_dependency("catalog_ranking"))]
GovernanceRubric = Annotated[Rubric, Depends(rubric_dependency("governance"))]

SSE_MEDIA_TYPE = "text/event-stream"
EVENT_PULSE = "pulse"
EVENT_HEARTBEAT = "heartbeat"

SYSTEM_SESSION_PREFIX = "SES-SYS-"


@router.get("/featured", status_code=http_status.OK, summary="The featured bands")
def featured_band(
    connection: Connection,
    landing: LandingRubric,
    quality: QualityRubric,
    ranking: RankingRubric,
    industry: str | None = Query(default=None),
) -> dict[str, Any]:
    """Bands 4 and 5, optionally narrowed to one vertical (M11.6).

    The industry selector filters this same ranking rather than applying a
    second one: a walkthrough tailored in one click should show the client the
    judgement the estate makes anyway, not a different one arranged for them.
    """
    window = int(ranking.number("adoption_window_days"))
    products = featured.rank(
        connection, landing, quality, industry=industry, window_days=window
    )
    per_row = int(landing.number("featured.products_per_row_max"))
    static_cards = int(landing.number("featured.static_grid_cards"))

    return {
        "industry": industry,
        "products": [item.document(int(landing.number("presentation.precision"))) for item in products[:per_row]],
        "agents": _agents(connection, landing, industry),
        "limits": {
            # The client needs the reduced-motion grid size and the ribbon's
            # row length; both are rubric data, so neither is a number the
            # component had to choose.
            "per_row_max": per_row,
            "per_row_min": int(landing.number("featured.products_per_row_min")),
            "static_grid_cards": static_cards,
            "refresh_seconds": int(landing.number("featured.refresh_seconds")),
        },
        "rubric_version_id": landing.rubric_version_id,
    }


AGENTS = """
SELECT a.agent_id, a.name, a.domain_code AS domain, a.industry_code AS industry,
       a.certification, v.autonomy_level, v.capability_statement, v.out_of_scope,
       (SELECT array_agg(DISTINCT b.product_id ORDER BY b.product_id)
          FROM agent_product_binding b
         WHERE b.agent_version_id = v.agent_version_id) AS products
FROM agent a
JOIN agent_version v ON v.agent_version_id = a.current_version_id
WHERE v.status = 'published'
ORDER BY a.agent_id
"""


def _agents(
    connection: psycopg.Connection[Any], landing: Rubric, industry: str | None
) -> list[dict[str, Any]]:
    rows = fetch_all(connection, AGENTS)
    if industry:
        rows = [row for row in rows if row["industry"] == industry]
    limit = int(landing.number("featured.agents_in_carousel"))
    return [
        {
            "agent_id": row["agent_id"],
            "name": row["name"],
            "domain": row["domain"],
            "industry": row["industry"],
            "certification": row["certification"],
            "autonomy_level": row["autonomy_level"],
            "capability_statement": row["capability_statement"],
            "out_of_scope": row["out_of_scope"],
            "products": list(row["products"] or []),
        }
        for row in rows[:limit]
    ]


@router.get("/industries", status_code=http_status.OK, summary="The industry selector")
def industry_tiles(connection: Connection, landing: LandingRubric) -> dict[str, Any]:
    return {
        "industries": featured.industries(connection, landing),
        "rubric_version_id": landing.rubric_version_id,
    }


@router.get("/counters", status_code=http_status.OK, summary="Trust strip and ticker")
def counters(connection: Connection, landing: LandingRubric) -> dict[str, Any]:
    return {
        "counters": [counter.document() for counter in pulse.counters(connection, landing)],
        "ticker": [event.document() for event in pulse.ticker(connection, landing)],
        "refresh_seconds": int(landing.number("counters.refresh_seconds")),
        # Carried so a reader can check the suppression rule was applied rather
        # than trusting that it was.
        "ticker_min_occurrences": int(landing.number("ticker.min_occurrences")),
        "rubric_version_id": landing.rubric_version_id,
    }


NODES = """
SELECT p.product_id AS id, p.name, p.domain_code AS domain,
       p.industry_code AS industry, p.certification,
       (SELECT s.composite FROM quality_score_snapshot s
         WHERE s.product_id = p.product_id ORDER BY s.computed_at DESC LIMIT 1) AS quality,
       (SELECT s.band FROM quality_score_snapshot s
         WHERE s.product_id = p.product_id ORDER BY s.computed_at DESC LIMIT 1) AS band,
       coalesce((SELECT max(u.active_consumers) FROM usage_daily_agg u
                  WHERE u.asset_id = p.product_id AND u.asset_type = 'data_product'
                    AND u.activity_date > current_date - %(window)s::int), 0) AS consumers,
       EXISTS (SELECT 1 FROM incident i
                WHERE i.asset_id = p.product_id AND i.resolved_at IS NULL) AS incident
FROM data_product p
WHERE p.certification <> 'deprecated'
ORDER BY p.product_id
"""

EDGES = """
SELECT product_a AS source, product_b AS target, strength, edge_type
FROM mesh_edge_data WHERE strength >= %(floor)s ORDER BY strength DESC, edge_id
"""

BINDINGS = """
SELECT a.agent_id, b.product_id
FROM agent a
JOIN agent_version v ON v.agent_version_id = a.current_version_id
JOIN agent_product_binding b ON b.agent_version_id = v.agent_version_id
WHERE v.status = 'published'
ORDER BY a.agent_id, b.product_id
"""


@router.get("/hero", status_code=http_status.OK, summary="The settled constellation")
def hero(
    connection: Connection,
    landing: LandingRubric,
    mesh: MeshRubric,
    ranking: RankingRubric,
) -> dict[str, Any]:
    """Real identifiers, real edges, and coordinates that have already settled.

    The client paints this frame immediately and drifts from it. It never runs
    the layout itself: a client-side simulation would produce a different
    picture from the one the API described, and the hero and the mesh explorer
    would then disagree about the shape of the same estate.
    """
    window = int(ranking.number("adoption_window_days"))
    cap = int(mesh.number("layout.featured_node_cap"))
    floor = float(mesh.number("render_threshold"))

    nodes = fetch_all(connection, NODES, {"window": window})[:cap]
    allowed = {node["id"] for node in nodes}
    edges = [
        edge for edge in fetch_all(connection, EDGES, {"floor": floor})
        if edge["source"] in allowed and edge["target"] in allowed
    ]

    simulation = layout.Simulation.from_rubric(mesh)
    placements = layout.settle(
        [node["id"] for node in nodes],
        [(edge["source"], edge["target"], float(edge["strength"])) for edge in edges],
        simulation,
    )

    consumption: dict[str, list[str]] = {}
    for row in fetch_all(connection, BINDINGS):
        if row["product_id"] in allowed:
            consumption.setdefault(row["agent_id"], []).append(row["product_id"])

    return {
        "nodes": [
            {
                "id": node["id"],
                "name": node["name"],
                "domain": node["domain"],
                "industry": node["industry"],
                "certification": node["certification"],
                "quality": None if node["quality"] is None else float(node["quality"]),
                "band": node["band"],
                "consumers": int(node["consumers"]),
                "incident": bool(node["incident"]),
            }
            for node in nodes
        ],
        "edges": [
            {
                "source": edge["source"],
                "target": edge["target"],
                "strength": float(edge["strength"]),
                "edge_type": edge["edge_type"],
            }
            for edge in edges
        ],
        "placements": [placement.document(simulation.precision) for placement in placements],
        # The box the settled graph actually occupies. A client that fits this
        # rather than the full extent draws the estate at a readable size
        # whatever the simulation happened to leave empty, and still never runs
        # a layout of its own.
        "bounds": _bounds(placements, simulation),
        "orbits": [
            orbit.document(simulation.precision)
            for orbit in layout.orbits(consumption, placements, simulation)
        ],
        "viewbox": simulation.extent,
        "opacity": float(landing.number("hero.constellation_opacity")),
        "rubric_version_id": mesh.rubric_version_id,
    }


@router.get("/theatre", status_code=http_status.OK, summary="Recorded exchanges to replay")
def theatre_traces(
    connection: Connection,
    landing: LandingRubric,
    governance: GovernanceRubric,
    agent: str | None = Query(default=None),
) -> dict[str, Any]:
    traces = theatre.traces(connection, governance, landing, agent_id=agent)
    return {
        "traces": [trace.document() for trace in traces],
        "mode": theatre.MODE_RECORDED,
        "rubric_version_id": landing.rubric_version_id,
    }


@router.get("/proof", status_code=http_status.OK, summary="The value-proof tiles")
def value_proof(
    connection: Connection, landing: LandingRubric, mesh: MeshRubric
) -> dict[str, Any]:
    return {
        "tiles": proof.tiles(connection, landing, mesh),
        "rubric_version_id": landing.rubric_version_id,
    }


RECENT = """
SELECT i.interaction_id, v.agent_id, i.question_class, i.occurred_at,
       (SELECT array_agg(DISTINCT b.product_id ORDER BY b.product_id)
          FROM agent_product_binding b
         WHERE b.agent_version_id = i.agent_version_id) AS products
FROM agent_interaction i
JOIN agent_version v ON v.agent_version_id = i.agent_version_id
WHERE i.outcome = 'answered' AND i.grounded
  AND i.session_id NOT LIKE %(system)s
  AND i.occurred_at > %(after)s
ORDER BY i.occurred_at, i.interaction_id
LIMIT %(limit)s
"""


def _pulses(after: Any, limit: int) -> tuple[list[dict[str, Any]], Any]:
    """Answer pulses since a watermark, and the new watermark.

    Opened on its own connection: the stream outlives the request-scoped one,
    and holding a transaction open for the life of an SSE connection would pin
    a snapshot for as long as a visitor leaves the tab open.
    """
    with connect(tenant()) as connection:
        rows = fetch_all(
            connection, RECENT,
            {"system": f"{SYSTEM_SESSION_PREFIX}%", "after": after, "limit": limit},
        )
    events = [
        {
            "agent_id": row["agent_id"],
            "products": list(row["products"] or []),
            "question_class": row["question_class"],
            "at": row["occurred_at"].isoformat(),
        }
        for row in rows
    ]
    watermark = rows[-1]["occurred_at"] if rows else after
    return events, watermark


def _frame(name: str, payload: dict[str, Any]) -> str:
    return f"event: {name}\ndata: {json.dumps(payload)}\n\n"


@events_router.get("/stream", summary="Answer pulses for the hero")
async def stream(
    connection: Connection, landing: LandingRubric
) -> StreamingResponse:
    """One pulse per grounded answer, capped at the motion layer's rate.

    The cap is the hero's, not the estate's: however many answers a busy minute
    produces, the constellation animates at most this many pulses a second, so
    the page cannot strobe. Answers beyond the cap are not queued for later —
    a pulse two minutes after its answer would be telling the visitor something
    untrue about when it happened.

    On the demo tier this is a replay of the recorded interaction stream, which
    is what section 13.3 asks for. It is the same query either way: the demo
    estate's answers are real answers, produced by the same runtime, and there
    is no branch here that would let a synthetic pulse in.
    """
    rate = int(landing.number("hero.max_pulses_per_second"))
    interval = float(landing.number("hero.stream_interval_seconds"))
    watermark = _now(connection)

    async def frames() -> AsyncIterator[str]:
        nonlocal watermark
        while True:
            events, watermark = await asyncio.to_thread(_pulses, watermark, rate)
            if events:
                for event in events:
                    yield _frame(EVENT_PULSE, event)
            else:
                # A heartbeat, so a client can tell a quiet estate from a dead
                # channel. The ticker hides on a dead one.
                yield _frame(EVENT_HEARTBEAT, {"at": watermark.isoformat()})
            await asyncio.sleep(interval)

    return StreamingResponse(
        frames(),
        media_type=SSE_MEDIA_TYPE,
        headers={"cache-control": "no-store", "x-accel-buffering": "no"},
    )


def _bounds(
    placements: list[layout.Placement], simulation: layout.Simulation
) -> dict[str, float]:
    if not placements:
        return {"x": 0.0, "y": 0.0, "width": simulation.extent, "height": simulation.extent}
    margin = simulation.collide_radius + simulation.orbit_radius
    left = min(placement.x for placement in placements) - margin
    right = max(placement.x for placement in placements) + margin
    top = min(placement.y for placement in placements) - margin
    bottom = max(placement.y for placement in placements) + margin
    return {
        "x": round(left, simulation.precision),
        "y": round(top, simulation.precision),
        "width": round(right - left, simulation.precision),
        "height": round(bottom - top, simulation.precision),
    }


def _now(connection: psycopg.Connection[Any]) -> Any:
    from services.common.db import fetch_one

    row = fetch_one(connection, "SELECT clock_timestamp() AS at")
    return row["at"] if row else None
