# AUTO-GENERATED FROM manifests/products/DP-BNK-003.yaml BY scripts/gen.py — DO NOT EDIT
# generator_version: 1.0.0  manifest_hash: 8582ee023574045c153f6206c9f567f1bd8bf26f280d60891b3220444572dc41  generated_at: 2026-09-04T21:35:53+00:00

"""MCP server for DP-BNK-003 — Lending & Credit Portfolio.

Generated from the product manifest. The handlers below do routing and typing
only: policy, provenance and audit live in ``services.mcp`` so that a generated
file can never become the place a rule is enforced.
"""

from __future__ import annotations

from typing import Any

from services.mcp.runtime import ProductServer, ToolRequest, ToolResponse

PRODUCT_ID = "DP-BNK-003"
CONTRACT_VERSION = "1.0.0"
PURPOSE_REQUIRED = True

server = ProductServer(
    product_id=PRODUCT_ID,
    contract_version=CONTRACT_VERSION,
    purpose_required=PURPOSE_REQUIRED,
    certified_kpis=['KPI-PORTYIELD-078', 'KPI-DELINQ-079', 'KPI-NPL-080', 'KPI-PROVCOV-081', 'KPI-LTV-082'],
    sliceable_columns=['product_type', 'segment', 'channel', 'vintage_band'],
    supported_grains=['month', 'quarter', 'year'],
    row_limit=48000,
)


@server.tool("query_loan_account_finance")
def query_loan_account_finance(request: ToolRequest) -> ToolResponse:
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
