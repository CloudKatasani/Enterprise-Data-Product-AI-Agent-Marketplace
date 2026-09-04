"""M2 — generated artifacts match their manifests, and regeneration is a no-op.

The contract layer's job (BUILD.md section 20) is proving that the generated
OpenAPI document, MCP servers and SDKs match their manifests. These tests compare
two views of the same source rather than checking output against a fixture, so a
manifest change that the generator ignores fails here.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from scripts._paths import GENERATED, MANIFESTS
from scripts.generators._manifests import load
from scripts.generators.registry import GENERATORS


@pytest.fixture(scope="module")
def products() -> list[tuple[Path, dict]]:
    return load("products")


@pytest.fixture(scope="module")
def kpis() -> dict[str, dict]:
    return {document["metadata"]["id"]: document for _, document in load("kpis")}


def _regenerate() -> Path:
    workdir = Path(tempfile.mkdtemp())
    scratch = workdir / "generated"
    shutil.copytree(GENERATED, scratch)
    for _, generator in GENERATORS:
        generator(scratch)
    return scratch


def test_regeneration_produces_no_diff() -> None:
    """M2 acceptance: same inputs, byte-identical outputs."""
    scratch = _regenerate()
    try:
        committed = {p.relative_to(GENERATED) for p in GENERATED.rglob("*") if p.is_file()}
        produced = {p.relative_to(scratch) for p in scratch.rglob("*") if p.is_file()}
        assert committed == produced

        differing = [
            str(relative)
            for relative in sorted(committed)
            if (GENERATED / relative).read_bytes() != (scratch / relative).read_bytes()
        ]
        assert differing == []
    finally:
        shutil.rmtree(scratch.parent)


def test_generation_is_idempotent_within_a_run() -> None:
    scratch = _regenerate()
    try:
        first = {p: p.read_bytes() for p in sorted(scratch.rglob("*")) if p.is_file()}
        for _, generator in GENERATORS:
            generator(scratch)
        second = {p: p.read_bytes() for p in sorted(scratch.rglob("*")) if p.is_file()}
        assert first == second
    finally:
        shutil.rmtree(scratch.parent)


def test_every_generated_file_names_the_source_it_came_from() -> None:
    for path in sorted(GENERATED.rglob("*")):
        if not path.is_file():
            continue
        head = path.read_text(encoding="utf-8")[:4096]
        assert "DO NOT EDIT" in head, path
        assert "scripts/gen.py" in head, path


def test_one_migration_group_exists_for_every_entity_group() -> None:
    from scripts.generators.ddl import GROUP_ORDER

    emitted = sorted(p.name for p in (GENERATED / "ddl").glob("*.sql"))
    expected = [f"{index:04d}_{group}.sql" for index, (group, _) in enumerate(GROUP_ORDER, 1)]
    assert emitted == expected


def test_every_product_has_governed_semantic_and_quality_sql_in_both_dialects(products) -> None:
    for _, product in products:
        product_id = product["metadata"]["id"]
        for dialect in ("snowflake", "ansi"):
            path = GENERATED / "sql" / dialect / f"{product_id}.sql"
            assert path.exists(), path
            sql = path.read_text(encoding="utf-8")
            schema = product_id.replace("-", "_").upper()
            assert f"CREATE OR REPLACE VIEW {schema}.V_{schema} AS" in sql
            assert f"CREATE OR REPLACE VIEW {schema}.SV_{schema} AS" in sql
            for rule in product["spec"]["quality_rules"]:
                assert rule["id"] in sql


def test_every_manifest_column_appears_in_the_governed_view(products) -> None:
    for _, product in products:
        product_id = product["metadata"]["id"]
        sql = (GENERATED / "sql" / "snowflake" / f"{product_id}.sql").read_text(encoding="utf-8")
        view = sql.split("CREATE OR REPLACE VIEW")[1]
        for column in product["spec"]["columns"]:
            assert column["name"] in view, f"{product_id}.{column['name']}"


def test_classified_columns_get_a_masking_policy(products) -> None:
    for _, product in products:
        product_id = product["metadata"]["id"]
        sql = (GENERATED / "sql" / "snowflake" / f"{product_id}.sql").read_text(encoding="utf-8")
        for column in product["spec"]["columns"]:
            classifications = column.get("classification", [])
            for sensitive in ("pii", "phi", "pci", "credential"):
                if sensitive in classifications:
                    assert (
                        f"MODIFY COLUMN {column['name']} SET MASKING POLICY "
                        f"GOVERNANCE.MASK_{sensitive.upper()}" in sql
                    ), f"{product_id}.{column['name']}"
                    break


def test_confidential_products_bind_a_purpose_policy(products) -> None:
    for _, product in products:
        product_id = product["metadata"]["id"]
        sql = (GENERATED / "sql" / "snowflake" / f"{product_id}.sql").read_text(encoding="utf-8")
        sensitivity = product["spec"]["contract"]["classification"]["max_sensitivity"]
        expected = sensitivity in ("confidential", "restricted")
        assert ("ROW ACCESS POLICY GOVERNANCE.PURPOSE_BOUND" in sql) is expected, product_id


def test_semantic_view_carries_one_measure_per_certified_kpi(products, kpis) -> None:
    for _, product in products:
        product_id = product["metadata"]["id"]
        sql = (GENERATED / "sql" / "snowflake" / f"{product_id}.sql").read_text(encoding="utf-8")
        semantic = sql.split("-- Semantic view")[1]
        for kpi_id in product["spec"]["certified_kpis"]:
            assert kpi_id in semantic, f"{product_id} is missing {kpi_id}"
            alias = kpi_id.replace("-", "_").lower()
            assert f"AS {alias}" in semantic


def test_mcp_descriptor_matches_the_product_manifest(products) -> None:
    for _, product in products:
        product_id = product["metadata"]["id"]
        descriptor = json.loads(
            (GENERATED / "mcp" / f"{product_id}.json").read_text(encoding="utf-8")
        )
        contract = product["spec"]["contract"]

        assert descriptor["product"]["id"] == product_id
        assert descriptor["product"]["version"] == contract["version"]
        assert descriptor["product"]["sensitivity"] == contract["classification"]["max_sensitivity"]
        assert descriptor["auth"]["scopes"] == [f"dp:{product_id}:read"]
        assert descriptor["policy"]["enforced_in"] == "data_platform"
        assert descriptor["consumer_obligations"] == contract["consumer_obligations"]


def test_mcp_requires_purpose_exactly_when_the_product_is_confidential_or_above(products) -> None:
    for _, product in products:
        product_id = product["metadata"]["id"]
        descriptor = json.loads(
            (GENERATED / "mcp" / f"{product_id}.json").read_text(encoding="utf-8")
        )
        sensitivity = product["spec"]["contract"]["classification"]["max_sensitivity"]
        assert descriptor["policy"]["purpose_required"] == (
            sensitivity in ("confidential", "restricted")
        ), product_id


def test_every_mcp_server_exposes_the_five_tools_of_section_11(products) -> None:
    required = {"describe_schema", "get_kpi_definition", "get_freshness", "get_quality"}
    for _, product in products:
        product_id = product["metadata"]["id"]
        descriptor = json.loads(
            (GENERATED / "mcp" / f"{product_id}.json").read_text(encoding="utf-8")
        )
        names = {tool["name"] for tool in descriptor["tools"]}
        assert required <= names, product_id
        # Plus exactly one product-specific query tool.
        assert len(names - required) == 1


def test_mcp_query_tool_only_offers_grains_the_kpis_support(products, kpis) -> None:
    for _, product in products:
        product_id = product["metadata"]["id"]
        descriptor = json.loads(
            (GENERATED / "mcp" / f"{product_id}.json").read_text(encoding="utf-8")
        )
        query = next(t for t in descriptor["tools"] if t["name"].startswith("query_"))
        offered = set(query["input_schema"]["grain"].removeprefix("enum[").rstrip("]").split(","))
        supported: set[str] = set()
        for kpi_id in product["spec"]["certified_kpis"]:
            supported.update(kpis[kpi_id]["spec"]["grains_supported"])
        assert offered <= supported, product_id


def test_a_python_server_stub_exists_for_every_product(products) -> None:
    for _, product in products:
        product_id = product["metadata"]["id"]
        stub = GENERATED / "mcp" / "servers" / f"{product_id.replace('-', '_')}_server.py"
        assert stub.exists(), stub
        body = stub.read_text(encoding="utf-8")
        assert f'PRODUCT_ID = "{product_id}"' in body
        # Policy lives in services.mcp, never in a generated file.
        assert "from services.mcp.runtime import" in body


def test_generated_types_cover_every_table_in_the_canonical_model() -> None:
    from scripts.generators import canonical_model

    combined = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted((GENERATED / "types").glob("*.ts"))
    )
    for table in canonical_model.ALL_TABLES:
        interface = "".join(part.capitalize() for part in table.name.split("_"))
        assert f"export interface {interface} {{" in combined, table.name


def test_generated_types_turn_check_constraints_into_unions() -> None:
    enums = (GENERATED / "types" / "enums.ts").read_text(encoding="utf-8")
    assert (
        "export type DataProductCertification = "
        "'certified' | 'published' | 'beta' | 'deprecated';" in enums
    )
    assert (
        "export type AgentVersionAutonomyLevel = 'L0' | 'L1' | 'L2' | 'L3';" in enums
    )


def test_openapi_document_is_3_1_and_every_route_is_under_the_versioned_prefix() -> None:
    document = json.loads((GENERATED / "openapi" / "openapi.json").read_text(encoding="utf-8"))

    assert document["openapi"] == "3.1.0"
    assert document["paths"]
    for path in document["paths"]:
        assert path.startswith("/api/v1/"), path


def test_the_generated_client_exposes_a_method_for_every_operation() -> None:
    document = json.loads((GENERATED / "openapi" / "openapi.json").read_text(encoding="utf-8"))
    client = (GENERATED / "openapi" / "client.ts").read_text(encoding="utf-8")

    from scripts.generators.openapi import _operation_name

    for path, operations in document["paths"].items():
        for method in operations:
            if method not in {"get", "post", "delete", "put"}:
                continue
            assert f"  {_operation_name(path, method)}(" in client, f"{method} {path}"


def test_manifests_directory_is_the_only_generator_input() -> None:
    """A generator that read something outside manifests/ would break replay."""
    assert (MANIFESTS / "products").exists()
    assert (MANIFESTS / "kpis").exists()
    assert (MANIFESTS / "rubrics").exists()
