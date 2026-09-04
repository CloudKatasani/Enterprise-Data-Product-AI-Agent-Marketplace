"""`/api/v1/discover` — universal hybrid search across every asset type.

The response carries the ranking rubric version and, per result, why it ranked
where it did. A search that cannot explain itself cannot be tuned, and tuning is
a rubric change rather than a code change.

The empty state is never a dead end (section 12): when nothing matches, the
response carries the nearest semantic neighbours, related demand items, and a
pre-filled new-supply request, so a consumer who searched for something the
estate does not have leaves a signal rather than leaving.
"""

from __future__ import annotations

from typing import Annotated, Any
from urllib.parse import quote

import psycopg
from fastapi import APIRouter, Depends, Query

from services.api.deps import request_connection, rubric_dependency, tenant
from services.common import http_status
from services.common.db import fetch_all
from services.common.principal import Principal, current_principal
from services.common.rubrics import Rubric
from services.search import hybrid

router = APIRouter(prefix="/discover", tags=["discover"])

RankingRubric = Annotated[Rubric, Depends(rubric_dependency(hybrid.RUBRIC_CODE))]
Connection = Annotated[psycopg.Connection[Any], Depends(request_connection)]
Caller = Annotated[Principal, Depends(current_principal)]
Tenant = Annotated[str, Depends(tenant)]


@router.get("", status_code=http_status.OK, summary="Hybrid search across products, agents and KPIs")
def discover(
    connection: Connection,
    principal: Caller,
    tenant_id: Tenant,
    rubric: RankingRubric,
    q: str = Query(min_length=1, description="The consumer's query, in their own words"),
    asset_type: Annotated[list[str] | None, Query()] = None,
    limit: int | None = None,
) -> dict[str, Any]:
    del principal  # search is metadata-only; every authenticated caller may search
    results = hybrid.search(
        connection, tenant_id, q, rubric, asset_types=asset_type, limit=limit
    )
    document: dict[str, Any] = {
        "query": q,
        "rubric_version_id": results.rubric_version_id,
        "results": results.document(),
    }
    if not results.candidates:
        document["empty_state"] = _empty_state(connection, tenant_id, q, rubric)
    return document


def _empty_state(
    connection: psycopg.Connection[Any], tenant_id: str, query: str, rubric: Rubric
) -> dict[str, Any]:
    """Nearest neighbours, related demand, and a way to ask for what is missing."""
    neighbours = hybrid.search(
        connection, tenant_id, query, rubric,
        limit=int(rubric.number("page_size.facet_values")),
    )
    demand = fetch_all(
        connection,
        "SELECT d.demand_id, r.title, d.state, d.score, "
        "       (SELECT count(*) FROM demand_vote v WHERE v.demand_id = d.demand_id) AS votes "
        "FROM demand_item d JOIN request r ON r.request_id = d.request_id "
        "WHERE d.tenant_id = %s AND d.state <> 'declined' "
        "ORDER BY d.score DESC NULLS LAST LIMIT %s",
        (tenant_id, int(rubric.number("page_size.facet_values"))),
    )
    return {
        "message": (
            "Nothing in the catalog matches that yet. The closest assets are below, along "
            "with demand already on the board. If none of them cover it, file a new-supply "
            "request and the query is carried into it."
        ),
        "nearest": neighbours.document(),
        "related_demand": [
            {
                "demand_id": row["demand_id"],
                "title": row["title"],
                "state": row["state"],
                "score": float(row["score"]) if row["score"] is not None else None,
                "votes": int(row["votes"]),
            }
            for row in demand
        ],
        "file_supply_request_url": f"/requests/new/supply?query={quote(query)}",
    }
