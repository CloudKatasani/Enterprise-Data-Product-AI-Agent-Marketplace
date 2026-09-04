"""`/api/v1/products` — catalog listing, detail and the per-tab endpoints.

The portal is a client of this API with no privileged path (section 10), so
everything the catalog page renders is reachable here, including the facet
counts and the partial-permission state.
"""

from __future__ import annotations

from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Query

from services.api.deps import request_connection, rubric_dependency, tenant
from services.catalog import detail, products
from services.common import http_status
from services.common.principal import Principal, current_principal
from services.common.problem import not_found
from services.common.rubrics import Rubric

router = APIRouter(prefix="/products", tags=["products"])

RankingRubric = Annotated[Rubric, Depends(rubric_dependency("catalog_ranking"))]
Connection = Annotated[psycopg.Connection[Any], Depends(request_connection)]
Caller = Annotated[Principal, Depends(current_principal)]
Tenant = Annotated[str, Depends(tenant)]


@router.get("", status_code=http_status.OK, summary="Search, filter and page the product catalog")
def list_products(
    connection: Connection,
    principal: Caller,
    tenant_id: Tenant,
    rubric: RankingRubric,
    industry: Annotated[list[str] | None, Query()] = None,
    domain: Annotated[list[str] | None, Query()] = None,
    archetype: Annotated[list[str] | None, Query()] = None,
    certification: Annotated[list[str] | None, Query()] = None,
    sensitivity: Annotated[list[str] | None, Query()] = None,
    tier: Annotated[list[str] | None, Query()] = None,
    owner: Annotated[list[str] | None, Query()] = None,
    endpoint: Annotated[list[str] | None, Query()] = None,
    kpi: Annotated[list[str] | None, Query()] = None,
    quality_band: Annotated[list[str] | None, Query()] = None,
    sort: str = products.DEFAULT_SORT,
    cursor: str | None = None,
    limit: int | None = None,
    featured: bool = False,
) -> dict[str, Any]:
    filters = products.ProductFilters(
        industry=industry, domain=domain, archetype=archetype, certification=certification,
        sensitivity=sensitivity, tier=tier, owner=owner, endpoint=endpoint, kpi=kpi,
        quality_band=quality_band,
    )
    page, facets = products.list_products(
        connection, tenant_id, principal, rubric, filters=filters, sort=sort, cursor=cursor,
        limit=limit, featured=featured,
    )
    return {
        **page.document(),
        "facets": [facet.document() for facet in facets],
        "sort": sort,
        "rubric_version_id": rubric.rubric_version_id,
    }


@router.get("/{product_id}", status_code=http_status.OK, summary="Full product listing")
def get_product(
    product_id: str,
    connection: Connection,
    principal: Caller,
    tenant_id: Tenant,
    rubric: RankingRubric,
) -> dict[str, Any]:
    card = products.get_card(connection, tenant_id, product_id, principal, rubric)
    if card is None:
        raise not_found("data product", product_id)
    return {"card": card, "tabs": detail.assemble(connection, product_id, principal)}


@router.get("/{product_id}/quality", status_code=http_status.OK,
            summary="Current composite, history and contributing rule results")
def get_quality(product_id: str, connection: Connection) -> dict[str, Any]:
    _assert_exists(connection, product_id)
    return detail.quality_tab(connection, product_id)


@router.get("/{product_id}/contract", status_code=http_status.OK,
            summary="Contract source, conformance history and version list")
def get_contract(product_id: str, connection: Connection) -> dict[str, Any]:
    _assert_exists(connection, product_id)
    return detail.contract_tab(connection, product_id)


@router.get("/{product_id}/schema", status_code=http_status.OK,
            summary="Column list with classification and masking state")
def get_schema(product_id: str, connection: Connection, principal: Caller) -> dict[str, Any]:
    from services.common.principal import effective_scopes

    _assert_exists(connection, product_id)
    return detail.schema_tab(connection, product_id, effective_scopes(connection, principal))


@router.get("/{product_id}/consumption", status_code=http_status.OK,
            summary="Usage and adoption within the caller's scope")
def get_consumption(product_id: str, connection: Connection, principal: Caller) -> dict[str, Any]:
    from services.common.principal import effective_scopes

    _assert_exists(connection, product_id)
    return detail.consumption_tab(
        connection, product_id, principal, effective_scopes(connection, principal)
    )


@router.get("/{product_id}/mesh", status_code=http_status.OK,
            summary="Mesh neighbourhood with strength, confidence and rationale")
def get_mesh(product_id: str, connection: Connection) -> dict[str, Any]:
    _assert_exists(connection, product_id)
    return detail.lineage_mesh_tab(connection, product_id)


@router.get("/{product_id}/lineage", status_code=http_status.OK,
            summary="Upstream and downstream lineage")
def get_lineage(product_id: str, connection: Connection) -> dict[str, Any]:
    _assert_exists(connection, product_id)
    return detail.lineage_mesh_tab(connection, product_id)


@router.get("/{product_id}/value", status_code=http_status.OK,
            summary="Value case, assumptions with sample sizes, and measurements")
def get_value(product_id: str, connection: Connection) -> dict[str, Any]:
    _assert_exists(connection, product_id)
    return detail.value_tab(connection, product_id)


@router.get("/{product_id}/endpoints", status_code=http_status.OK,
            summary="Consumption surfaces and whether the caller may use them")
def get_endpoints(product_id: str, connection: Connection, principal: Caller) -> dict[str, Any]:
    from services.common.principal import effective_scopes

    _assert_exists(connection, product_id)
    return detail.endpoints_tab(connection, product_id, effective_scopes(connection, principal))


def _assert_exists(connection: psycopg.Connection[Any], product_id: str) -> None:
    from services.common.db import fetch_one

    if fetch_one(
        connection, "SELECT product_id FROM data_product WHERE product_id = %s", (product_id,)
    ) is None:
        raise not_found("data product", product_id)
