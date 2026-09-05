# AUTO-GENERATED FROM manifests/products/DP-MFG-003.yaml BY scripts/gen.py — DO NOT EDIT
# generator_version: 1.0.0  manifest_hash: 0c3198c3ee40134cbb187b05e5dbb00d74d7c572396ee69c86940cc6744f0d95  generated_at: 2026-09-05T23:26:01+00:00

"""MCP server for DP-MFG-003 — Equipment Reliability & Maintenance.

Generated from the product manifest. The handlers below do routing and typing
only: policy, provenance and audit live in ``services.mcp`` so that a generated
file can never become the place a rule is enforced.
"""

from __future__ import annotations

from typing import Any

from services.mcp.runtime import ProductServer, ToolRequest, ToolResponse

PRODUCT_ID = "DP-MFG-003"
CONTRACT_VERSION = "1.0.0"
PURPOSE_REQUIRED = False

server = ProductServer(
    product_id=PRODUCT_ID,
    contract_version=CONTRACT_VERSION,
    purpose_required=PURPOSE_REQUIRED,
    certified_kpis=['KPI-MTBF-108', 'KPI-MTTREPAIR-109', 'KPI-PMADHERE-110', 'KPI-UNPLANNED-111', 'KPI-SPARESAVAIL-112'],
    sliceable_columns=['plant', 'line', 'asset_class', 'criticality', 'failure_mode', 'crew'],
    supported_grains=['month', 'quarter', 'year'],
    row_limit=21600,
)


@server.tool("query_work_order_network_asset")
def query_work_order_network_asset(request: ToolRequest) -> ToolResponse:
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
