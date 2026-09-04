# AUTO-GENERATED FROM manifests/products/DP-UTL-001.yaml BY scripts/gen.py — DO NOT EDIT
# generator_version: 1.0.0  manifest_hash: 6b3bdcc61fdf1bdb94713ea967b74622e853f598a88b9678a925458dc60bbc6c  generated_at: 2026-09-04T02:51:21+00:00

"""MCP server for DP-UTL-001 — Grid Asset Health & Outage.

Generated from the product manifest. The handlers below do routing and typing
only: policy, provenance and audit live in ``services.mcp`` so that a generated
file can never become the place a rule is enforced.
"""

from __future__ import annotations

from typing import Any

from services.mcp.runtime import ProductServer, ToolRequest, ToolResponse

PRODUCT_ID = "DP-UTL-001"
CONTRACT_VERSION = "3.7.0"
PURPOSE_REQUIRED = False

server = ProductServer(
    product_id=PRODUCT_ID,
    contract_version=CONTRACT_VERSION,
    purpose_required=PURPOSE_REQUIRED,
    certified_kpis=['KPI-SAIDI-061', 'KPI-SAIFI-062', 'KPI-AHI-063', 'KPI-RESTORE-064', 'KPI-PMCOMP-065'],
    sliceable_columns=['feeder', 'asset_class', 'vintage_band', 'cause_class', 'crew'],
    supported_grains=['month', 'quarter', 'year'],
    row_limit=16800,
)


@server.tool("query_asset_network_asset")
def query_asset_network_asset(request: ToolRequest) -> ToolResponse:
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
