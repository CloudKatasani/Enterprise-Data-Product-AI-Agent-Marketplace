# AUTO-GENERATED FROM manifests/products/DP-INS-003.yaml BY scripts/gen.py — DO NOT EDIT
# generator_version: 1.0.0  manifest_hash: 8582ee023574045c153f6206c9f567f1bd8bf26f280d60891b3220444572dc41  generated_at: 2026-09-04T21:35:53+00:00

"""MCP server for DP-INS-003 — Policyholder & Distribution 360.

Generated from the product manifest. The handlers below do routing and typing
only: policy, provenance and audit live in ``services.mcp`` so that a generated
file can never become the place a rule is enforced.
"""

from __future__ import annotations

from typing import Any

from services.mcp.runtime import ProductServer, ToolRequest, ToolResponse

PRODUCT_ID = "DP-INS-003"
CONTRACT_VERSION = "1.0.0"
PURPOSE_REQUIRED = True

server = ProductServer(
    product_id=PRODUCT_ID,
    contract_version=CONTRACT_VERSION,
    purpose_required=PURPOSE_REQUIRED,
    certified_kpis=['KPI-POLPERCUST-103', 'KPI-MULTILINE-104', 'KPI-DIGITAL-105', 'KPI-XSELL-106', 'KPI-COMPLAINT-107'],
    sliceable_columns=['segment', 'distribution_channel', 'tenure_band'],
    supported_grains=['month', 'quarter', 'year'],
    row_limit=39200,
)


@server.tool("query_customer_customer")
def query_customer_customer(request: ToolRequest) -> ToolResponse:
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
