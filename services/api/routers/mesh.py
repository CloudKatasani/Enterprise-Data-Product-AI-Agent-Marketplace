"""`/api/v1/mesh` — both graphs, their modes, and the table behind each one.

Every response carries the rows the graph is drawn from, in the same order the
table renders them. That is not redundancy: M9.4 requires a keyboard-navigable
table equivalent for every mesh view, and the way to guarantee one exists is for
the graph and the table to be the same payload rather than two endpoints that
can drift.

Layout hints come from the rubric so the client paints a settled graph rather
than one that shuffles for two seconds after load.
"""

from __future__ import annotations

from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Query

from services.api.deps import request_connection, rubric_dependency, tenant
from services.common import http_status
from services.common.db import fetch_all
from services.common.principal import Principal, current_principal
from services.common.problem import bad_request
from services.common.rubrics import Rubric
from services.mesh import agents as agent_mesh
from services.mesh import data as data_mesh
from services.mesh import divergence

router = APIRouter(prefix="/mesh", tags=["mesh"])

Connection = Annotated[psycopg.Connection[Any], Depends(request_connection)]
Caller = Annotated[Principal, Depends(current_principal)]
Tenant = Annotated[str, Depends(tenant)]
MeshRubric = Annotated[Rubric, Depends(rubric_dependency("mesh_edges"))]

LAYOUT_KEYS = (
    "prewarm_ticks", "link_distance", "charge_strength", "collide_radius",
    "featured_node_cap",
)
# Geometry for the server-rendered diagram. Sent alongside the force parameters
# so a client draws the picture the server described rather than one of its own.
SVG_KEYS = (
    "viewbox", "centre", "radius", "node_radius", "label_offset",
    "min_edge_opacity", "max_edge_width", "start_angle_turns",
)

MODE_FORCE = "force"
MODE_DOMAIN = "domain"
MODE_SOURCE = "source"
MODE_DUPLICATION = "duplication"
MODE_GAP = "gap"
MODES = (MODE_FORCE, MODE_DOMAIN, MODE_SOURCE, MODE_DUPLICATION, MODE_GAP)

SCOPE_FEATURED = "featured"


def _layout(rubric: Rubric) -> dict[str, Any]:
    return {
        **{key: float(rubric.number(f"layout.{key}")) for key in LAYOUT_KEYS},
        "svg": {key: float(rubric.number(f"layout.svg.{key}")) for key in SVG_KEYS},
    }


def _product_nodes(connection: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    return fetch_all(
        connection,
        "SELECT p.product_id AS id, p.name, p.domain_code AS domain, "
        "       p.industry_code AS industry, p.sensitivity_tier AS sensitivity, "
        "       p.certification, p.tier, "
        "       (SELECT s.composite FROM quality_score_snapshot s "
        "        WHERE s.product_id = p.product_id ORDER BY s.computed_at DESC LIMIT 1) "
        "         AS quality, "
        "       (SELECT s.band FROM quality_score_snapshot s "
        "        WHERE s.product_id = p.product_id ORDER BY s.computed_at DESC LIMIT 1) "
        "         AS band "
        "FROM data_product p ORDER BY p.product_id",
    )


def _agent_nodes(connection: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    return fetch_all(
        connection,
        "SELECT a.agent_id AS id, a.name, a.domain_code AS domain, "
        "       a.industry_code AS industry, a.certification, v.autonomy_level, "
        "       v.status "
        "FROM agent a JOIN agent_version v ON v.agent_version_id = a.current_version_id "
        "ORDER BY a.agent_id",
    )


def _edges(connection: psycopg.Connection[Any], table: str) -> list[dict[str, Any]]:
    left, right = ("product_a", "product_b") if table.endswith("data") else (
        "agent_a", "agent_b"
    )
    return [
        {
            "edge_id": row["edge_id"],
            "source": row[left],
            "target": row[right],
            "edge_type": row["edge_type"],
            "strength": float(row["strength"]),
            "confidence": float(row["confidence"]),
            "factors": row["factors"],
            "rationale": row["rationale"],
            "reviewed_by": row["reviewed_by"],
        }
        for row in fetch_all(
            connection,
            f"SELECT edge_id, {left}, {right}, edge_type, strength, confidence, factors, "
            f"rationale, reviewed_by FROM {table} ORDER BY strength DESC, edge_id",
        )
    ]


@router.get("/data", status_code=http_status.OK, summary="The data product mesh")
def data_graph(
    connection: Connection,
    principal: Caller,
    tenant_id: Tenant,
    rubric: MeshRubric,
    mode: str = MODE_FORCE,
    scope: str | None = None,
    domain: Annotated[list[str] | None, Query()] = None,
    min_strength: float | None = None,
) -> dict[str, Any]:
    if mode not in MODES:
        raise bad_request("mode must be one of " + ", ".join(MODES), mode=mode)

    nodes = _product_nodes(connection)
    edges = _edges(connection, "mesh_edge_data")

    if mode == MODE_DUPLICATION:
        candidates = data_mesh.duplication_candidates(connection, rubric)
        keep = {candidate["edge_id"] for candidate in candidates}
        edges = [edge for edge in edges if edge["edge_id"] in keep]
    if domain:
        allowed = {node["id"] for node in nodes if node["domain"] in domain}
        nodes = [node for node in nodes if node["id"] in allowed]
        edges = [
            edge for edge in edges
            if edge["source"] in allowed and edge["target"] in allowed
        ]
    if min_strength is not None:
        edges = [edge for edge in edges if edge["strength"] >= min_strength]
    if scope == SCOPE_FEATURED:
        cap = int(rubric.number("layout.featured_node_cap"))
        nodes = nodes[:cap]
        allowed = {node["id"] for node in nodes}
        edges = [
            edge for edge in edges
            if edge["source"] in allowed and edge["target"] in allowed
        ]

    return {
        "mode": mode,
        "nodes": nodes,
        "edges": edges,
        "layout": _layout(rubric),
        "rubric_version_id": rubric.rubric_version_id,
        # M9.4: the table is the same payload, not a second endpoint that can
        # drift from the graph it is meant to be equivalent to.
        "table": _table_rows(edges, nodes),
        "modes": list(MODES),
    }


@router.get("/agents", status_code=http_status.OK, summary="The agent mesh")
def agent_graph(
    connection: Connection,
    principal: Caller,
    tenant_id: Tenant,
    rubric: MeshRubric,
    mode: str = MODE_FORCE,
    domain: Annotated[list[str] | None, Query()] = None,
    min_strength: float | None = None,
) -> dict[str, Any]:
    if mode not in MODES:
        raise bad_request("mode must be one of " + ", ".join(MODES), mode=mode)

    nodes = _agent_nodes(connection)
    edges = _edges(connection, "mesh_edge_agent")

    if mode == MODE_DUPLICATION:
        candidates = agent_mesh.consolidation_candidates(connection, rubric)
        keep = {candidate["edge_id"] for candidate in candidates}
        edges = [edge for edge in edges if edge["edge_id"] in keep]
    if domain:
        allowed = {node["id"] for node in nodes if node["domain"] in domain}
        nodes = [node for node in nodes if node["id"] in allowed]
        edges = [
            edge for edge in edges
            if edge["source"] in allowed and edge["target"] in allowed
        ]
    if min_strength is not None:
        edges = [edge for edge in edges if edge["strength"] >= min_strength]

    return {
        "mode": mode,
        "nodes": nodes,
        "edges": edges,
        "layout": _layout(rubric),
        "rubric_version_id": rubric.rubric_version_id,
        "table": _table_rows(edges, nodes),
        "modes": list(MODES),
    }


def _table_rows(
    edges: list[dict[str, Any]], nodes: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The graph as rows, in the order the graph ranks them.

    Names as well as ids: a table equivalent that lists DP-TEL-001 twice per row
    is technically equivalent and practically useless.
    """
    names = {node["id"]: node["name"] for node in nodes}
    return [
        {
            "source": edge["source"],
            "source_name": names.get(edge["source"], edge["source"]),
            "target": edge["target"],
            "target_name": names.get(edge["target"], edge["target"]),
            "edge_type": edge["edge_type"],
            "strength": edge["strength"],
            "confidence": edge["confidence"],
            "rationale": edge["rationale"],
        }
        for edge in edges
    ]


@router.get(
    "/data/blast-radius",
    status_code=http_status.OK,
    summary="Everything downstream of one source system",
)
def blast_radius(
    connection: Connection,
    principal: Caller,
    tenant_id: Tenant,
    source: str,
) -> dict[str, Any]:
    if not source.strip():
        raise bad_request("source is required")
    return data_mesh.blast_radius(connection, source)


@router.get(
    "/divergence",
    status_code=http_status.OK,
    summary="KPIs more than one agent answers on, and whether they agree",
)
def kpi_divergence(
    connection: Connection, principal: Caller, tenant_id: Tenant, rubric: MeshRubric
) -> dict[str, Any]:
    return {
        "shared_coverage": divergence.shared_coverage(connection),
        "cross_product": divergence.cross_product(connection),
    }


@router.get(
    "/sources",
    status_code=http_status.OK,
    summary="Source systems, for the source-anchored layout",
)
def sources(
    connection: Connection, principal: Caller, tenant_id: Tenant
) -> dict[str, Any]:
    return {
        "sources": fetch_all(
            connection,
            "SELECT s.source_id, s.name, s.platform, s.criticality, "
            "       count(DISTINCT e.downstream_id) AS downstream_products "
            "FROM source_system s "
            "LEFT JOIN lineage_edge e ON e.upstream_id = s.source_id "
            "  AND e.upstream_type = 'source_system' "
            "GROUP BY s.source_id, s.name, s.platform, s.criticality "
            "ORDER BY downstream_products DESC, s.source_id",
        )
    }
