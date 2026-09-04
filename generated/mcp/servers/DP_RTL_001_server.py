# AUTO-GENERATED FROM manifests/products/DP-RTL-001.yaml BY scripts/gen.py — DO NOT EDIT
# generator_version: 1.0.0  manifest_hash: e3907c67cfe5f6a0bf970d3e3e080796aefa5731f02cd93c3c8cb9c4c93a5cbe  generated_at: 2026-09-04T15:57:42+00:00

"""MCP server for DP-RTL-001 — Omnichannel Sales & Basket Analytics.

Generated from the product manifest. The handlers below do routing and typing
only: policy, provenance and audit live in ``services.mcp`` so that a generated
file can never become the place a rule is enforced.
"""

from __future__ import annotations

from typing import Any

from services.mcp.runtime import ProductServer, ToolRequest, ToolResponse

PRODUCT_ID = "DP-RTL-001"
CONTRACT_VERSION = "6.2.0"
PURPOSE_REQUIRED = False

server = ProductServer(
    product_id=PRODUCT_ID,
    contract_version=CONTRACT_VERSION,
    purpose_required=PURPOSE_REQUIRED,
    certified_kpis=['KPI-COMPSALES-046', 'KPI-BASKET-047', 'KPI-GMRATE-049', 'KPI-PROMOLIFT-050'],
    sliceable_columns=['category', 'channel', 'store_format', 'promotion'],
    supported_grains=['day', 'week', 'month', 'quarter', 'year'],
    row_limit=32000,
)


@server.tool("query_transaction_customer")
def query_transaction_customer(request: ToolRequest) -> ToolResponse:
    """Return certified measures by period and slice."""
    return server.query_measures(request)


@server.tool("describe_schema")
def describe_schema(request: ToolRequest) -> ToolResponse:
    """Columns, types and classifications, filtered to the caller's scope."""
    return server.describe_schema(request)


@server.tool("get_kpi_definition")
def get_kpi_definition(request: ToolRequest) -> ToolResponse:
    """Authoritative definition by KPI ID."""
    return server.get_kpi_definition(request)


@server.tool("get_freshness")
def get_freshness(request: ToolRequest) -> ToolResponse:
    """Load state against the contract freshness guarantee."""
    return server.get_freshness(request)


@server.tool("get_quality")
def get_quality(request: ToolRequest) -> ToolResponse:
    """Current composite and dimension scores with the rubric version."""
    return server.get_quality(request)


def handlers() -> dict[str, Any]:
    return server.handlers
