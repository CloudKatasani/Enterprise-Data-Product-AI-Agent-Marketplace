"""`/api/v1/kpis` — the certified KPI register.

One authoritative definition per name (I1), its version history, and every
consumer of it: the products that source it and the agents that answer on it.
Divergence detection lands in M9; the endpoint exists here so the register is
navigable from the first milestone that has one.
"""

from __future__ import annotations

from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Query

from services.api.deps import request_connection, rubric_dependency, tenant
from services.common import http_status
from services.common.db import fetch_all, fetch_one
from services.common.pagination import Cursor, Page
from services.common.problem import not_found
from services.common.rubrics import Rubric

router = APIRouter(prefix="/kpis", tags=["kpis"])

Connection = Annotated[psycopg.Connection[Any], Depends(request_connection)]
Tenant = Annotated[str, Depends(tenant)]
RankingRubric = Annotated[Rubric, Depends(rubric_dependency("catalog_ranking"))]


@router.get("", status_code=http_status.OK, summary="Certified KPI register with synonyms")
def list_kpis(
    connection: Connection,
    tenant_id: Tenant,
    rubric: RankingRubric,
    domain: Annotated[list[str] | None, Query()] = None,
    status: Annotated[list[str] | None, Query()] = None,
    cursor: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    page_size = limit if limit is not None else int(rubric.number("page_size.default"))
    predicates = ["k.tenant_id = %(tenant)s"]
    params: dict[str, Any] = {"tenant": tenant_id, "limit": page_size + 1}
    if domain:
        predicates.append("k.domain_code = ANY(%(domain)s)")
        params["domain"] = domain
    if status:
        predicates.append("k.status = ANY(%(status)s)")
        params["status"] = status
    if cursor:
        decoded = Cursor.decode(cursor)
        predicates.append("k.kpi_id > %(cursor_id)s")
        params["cursor_id"] = decoded.identifier

    rows = fetch_all(
        connection,
        "SELECT k.kpi_id, k.kpi_name, k.status, k.unit, k.direction, k.target, k.domain_code, "
        "       k.source_of_record, k.steward_party_id, k.last_reviewed, k.review_months, "
        "       k.grains_supported, k.slices_supported, "
        "       array_remove(array_agg(DISTINCT s.term), NULL) AS synonyms "
        "FROM kpi_definition k LEFT JOIN kpi_synonym s ON s.kpi_id = k.kpi_id "
        "WHERE " + " AND ".join(predicates) +
        " GROUP BY k.kpi_id ORDER BY k.kpi_id LIMIT %(limit)s",
        params,
    )
    has_more = len(rows) > page_size
    visible = rows[:page_size]
    next_cursor = (
        Cursor(sort_value=visible[-1]["kpi_id"], identifier=visible[-1]["kpi_id"]).encode()
        if has_more and visible
        else None
    )
    total = fetch_one(
        connection, "SELECT count(*) AS total FROM kpi_definition WHERE tenant_id = %s",
        (tenant_id,),
    )
    return Page(
        items=[_kpi(row) for row in visible],
        next_cursor=next_cursor,
        total=int(total["total"]) if total else None,
    ).document()


@router.get("/{kpi_id}", status_code=http_status.OK,
            summary="Definition, versions and every consumer of a KPI")
def get_kpi(kpi_id: str, connection: Connection) -> dict[str, Any]:
    row = fetch_one(
        connection,
        "SELECT k.*, array_remove(array_agg(DISTINCT s.term), NULL) AS synonyms "
        "FROM kpi_definition k LEFT JOIN kpi_synonym s ON s.kpi_id = k.kpi_id "
        "WHERE k.kpi_id = %s GROUP BY k.kpi_id",
        (kpi_id,),
    )
    if row is None:
        raise not_found("kpi", kpi_id)

    versions = fetch_all(
        connection,
        "SELECT kpi_version_id, semver, change_reason, approved_by, effective_from "
        "FROM kpi_definition_version WHERE kpi_id = %s ORDER BY effective_from DESC",
        (kpi_id,),
    )
    products = fetch_all(
        connection,
        "SELECT product_id, name, certification FROM data_product "
        "WHERE product_id IN (SELECT source_of_record FROM kpi_definition WHERE kpi_id = %s)",
        (kpi_id,),
    )
    agents = fetch_all(
        connection,
        "SELECT a.agent_id, a.name, c.analysis_depth, c.supported_grains, c.supported_slices, "
        "       c.eval_accuracy, c.eval_sample_size "
        "FROM agent_kpi_coverage c "
        "JOIN agent_version v ON v.agent_version_id = c.agent_version_id "
        "JOIN agent a ON a.current_version_id = v.agent_version_id "
        "WHERE c.kpi_id = %s ORDER BY a.agent_id",
        (kpi_id,),
    )
    return {
        "definition": _kpi(row) | {
            "business_definition": row["business_definition"],
            "numerator_expr": row["numerator_expr"],
            "denominator_expr": row["denominator_expr"],
            "expression": row["expression"],
            "inclusions": list(row["inclusions"]),
            "exclusions": list(row["exclusions"]),
            "forum_approved_at": row["forum_approved_at"].isoformat()
            if row["forum_approved_at"]
            else None,
            "superseded_by": row["superseded_by"],
        },
        "versions": [
            {
                "kpi_version_id": version["kpi_version_id"],
                "semver": version["semver"],
                "change_reason": version["change_reason"],
                "approved_by": version["approved_by"],
                "effective_from": version["effective_from"].isoformat(),
            }
            for version in versions
        ],
        "consumers": {
            "products": [dict(product) for product in products],
            "agents": [
                {
                    "agent_id": agent["agent_id"],
                    "name": agent["name"],
                    "analysis_depth": agent["analysis_depth"],
                    "grains": list(agent["supported_grains"]),
                    "slices": list(agent["supported_slices"]),
                    "eval_accuracy": float(agent["eval_accuracy"])
                    if agent["eval_accuracy"] is not None
                    else None,
                    "eval_sample_size": agent["eval_sample_size"],
                }
                for agent in agents
            ],
        },
    }


def _kpi(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "kpi_id": row["kpi_id"],
        "name": row["kpi_name"],
        "status": row["status"],
        "unit": row["unit"],
        "direction": row["direction"],
        "target": float(row["target"]) if row["target"] is not None else None,
        "domain": row["domain_code"],
        "source_of_record": row["source_of_record"],
        "steward_party_id": row["steward_party_id"],
        "grains_supported": list(row["grains_supported"]),
        "slices_supported": list(row["slices_supported"]),
        "synonyms": list(row["synonyms"]),
        "last_reviewed": row["last_reviewed"].isoformat(),
        "review_months": row["review_months"],
    }
