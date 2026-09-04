"""gen:mcp — one MCP server definition and Python stub per data product.

Section 11: tools are typed and derived from the contract, policy is enforced
server-side in the data platform, every response carries provenance, purpose is
mandatory above Internal, and delegated identity is preserved with both
identities logged.

The generator emits two files per product:

* ``generated/mcp/<id>.json`` — the server descriptor a client reads;
* ``generated/mcp/servers/<id>_server.py`` — a Python stub whose handlers call
  into ``services.mcp`` for policy, provenance and audit, so the generated code
  contains routing and typing but no policy of its own.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.generators._manifests import digest_of, load
from scripts.generators.header import write_generated

VERSION = "1.0.0"

# Grains a query tool accepts, derived from the KPI manifests a product certifies.
GRAIN_ORDER = ["day", "week", "month", "quarter", "year"]

# Sensitivity tiers that require a bound purpose before any row is returned.
PURPOSE_REQUIRED = ("confidential", "restricted")


def _tool_name(product: dict[str, Any]) -> str:
    entity = product["spec"]["entities"][0]
    domain = product["metadata"]["domain"]
    return f"query_{entity}_{domain}".replace("-", "_")


def _slice_columns(product: dict[str, Any]) -> list[str]:
    """Columns a caller may slice by: low-cardinality, unclassified descriptors."""
    return [
        column["name"]
        for column in product["spec"]["columns"]
        if column["type"] == "string" and not column.get("classification")
    ]


def _grains(product: dict[str, Any], kpis: dict[str, dict[str, Any]]) -> list[str]:
    supported: set[str] = set()
    for kpi_id in product["spec"]["certified_kpis"]:
        kpi = kpis.get(kpi_id)
        if kpi is not None:
            supported.update(kpi["spec"]["grains_supported"])
    return [grain for grain in GRAIN_ORDER if grain in supported]


def _row_limit(product: dict[str, Any]) -> int:
    """The row limit a tool advertises, taken from the product's own contract."""
    return product["spec"]["demo_tier"]["rows_target"] // 25


def _descriptor(product: dict[str, Any], kpis: dict[str, dict[str, Any]]) -> dict[str, Any]:
    metadata = product["metadata"]
    spec = product["spec"]
    contract = spec["contract"]
    classification = contract["classification"]
    product_id = metadata["id"]
    query_tool = _tool_name(product)

    return {
        "server": f"mcp://marketplace.${{TENANT}}.internal/dp/{product_id}",
        "product": {
            "id": product_id,
            "name": metadata["name"],
            "version": contract["version"],
            "sensitivity": classification["max_sensitivity"],
            "contains_pii": classification["contains_pii"],
            "grain": spec["grain"],
        },
        "auth": {
            "type": "oauth2",
            "flow": "client_credentials",
            "scopes": [f"dp:{product_id}:read"],
            "identity": "agent",
            "delegation": "on_behalf_of_required",
        },
        "tools": [
            {
                "name": query_tool,
                "description": (
                    f"Return certified measures for {metadata['name']} by period and slice."
                ),
                "input_schema": {
                    "period": "string",
                    "grain": "enum[" + ",".join(_grains(product, kpis)) + "]",
                    "slices": "array[enum[" + ",".join(_slice_columns(product)) + "]]",
                    "kpi_ids": "array[enum[" + ",".join(spec["certified_kpis"]) + "]]",
                    "purpose": "string",
                },
                "returns": "rows + certified KPI definition IDs + freshness_as_of",
                "row_limit": _row_limit(product),
                "cost_class": "small",
            },
            {
                "name": "describe_schema",
                "description": "Columns, types and classifications for this product.",
                "input_schema": {},
                "returns": "column list with classification and masking state",
                "cost_class": "trivial",
            },
            {
                "name": "get_kpi_definition",
                "description": "Authoritative definition by KPI ID.",
                "input_schema": {"kpi_id": "string"},
                "returns": "certified definition, version, grains, slices, steward",
                "cost_class": "trivial",
            },
            {
                "name": "get_freshness",
                "description": "Load state against the contract freshness guarantee.",
                "input_schema": {},
                "returns": "as_of, target, p95_minutes, breach state",
                "cost_class": "trivial",
            },
            {
                "name": "get_quality",
                "description": "Current composite and dimension scores.",
                "input_schema": {},
                "returns": "composite, dimensions, band, rubric_version_id, computed_at",
                "cost_class": "trivial",
            },
        ],
        "policy": {
            "row_filters_applied": True,
            "column_masking_applied": True,
            "purpose_required": classification["max_sensitivity"] in PURPOSE_REQUIRED,
            "max_rows_per_call": _row_limit(product),
            "audit": "agent_id, user_on_behalf_of, purpose, columns_returned",
            "enforced_in": "data_platform",
        },
        "provenance": {
            "product_id": product_id,
            "contract_version": contract["version"],
            "includes": ["freshness_as_of", "quality_composite", "kpi_definition_ids"],
        },
        "consumer_obligations": contract["consumer_obligations"],
    }


SERVER_TEMPLATE = '''"""MCP server for {product_id} — {product_name}.

Generated from the product manifest. The handlers below do routing and typing
only: policy, provenance and audit live in ``services.mcp`` so that a generated
file can never become the place a rule is enforced.
"""

from __future__ import annotations

from typing import Any

from services.mcp.runtime import ProductServer, ToolRequest, ToolResponse

PRODUCT_ID = "{product_id}"
CONTRACT_VERSION = "{contract_version}"
PURPOSE_REQUIRED = {purpose_required}

server = ProductServer(
    product_id=PRODUCT_ID,
    contract_version=CONTRACT_VERSION,
    purpose_required=PURPOSE_REQUIRED,
    certified_kpis={certified_kpis!r},
    sliceable_columns={sliceable!r},
    supported_grains={grains!r},
    row_limit={row_limit},
)


@server.tool("{query_tool}")
def {query_tool}(request: ToolRequest) -> ToolResponse:
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
'''


def generate(output_root: Path) -> list[Path]:
    products = load("products")
    if not products:
        return []
    kpis = {document["metadata"]["id"]: document for _, document in load("kpis")}
    digest = digest_of([path for path, _ in products])
    written: list[Path] = []

    for path, product in products:
        product_id = product["metadata"]["id"]
        descriptor = _descriptor(product, kpis)
        source = f"manifests/products/{path.name}"

        json_path = output_root / "mcp" / f"{product_id}.json"
        body = json.dumps(
            {
                "_generated": {
                    "from": source,
                    "by": "scripts/gen.py",
                    "generator_version": VERSION,
                    "manifest_hash": digest,
                    "warning": "DO NOT EDIT",
                },
                **descriptor,
            },
            indent=2,
            sort_keys=False,
        )
        write_generated(
            json_path, body, source=source, version=VERSION, digest=digest, json_style=True
        )
        written.append(json_path)

        stub_path = output_root / "mcp" / "servers" / f"{product_id.replace('-', '_')}_server.py"
        write_generated(
            stub_path,
            SERVER_TEMPLATE.format(
                product_id=product_id,
                product_name=product["metadata"]["name"],
                contract_version=product["spec"]["contract"]["version"],
                purpose_required=descriptor["policy"]["purpose_required"],
                certified_kpis=product["spec"]["certified_kpis"],
                sliceable=_slice_columns(product),
                grains=_grains(product, kpis),
                row_limit=_row_limit(product),
                query_tool=_tool_name(product),
            ),
            source=source,
            version=VERSION,
            digest=digest,
        )
        written.append(stub_path)

    return written
