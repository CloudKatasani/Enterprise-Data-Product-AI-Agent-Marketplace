"""gen:sql — product manifests to governed views, semantic views and DMF attachments.

Three artifacts per product, per platform:

* **governed view** — the consumption surface. Column masking is declared here so
  it is enforced *in the data platform* rather than in the application layer
  (section 19), and the view carries the contract version and sensitivity as
  comments so provenance travels with the object.
* **semantic view** — one measure per certified KPI, expressed from the KPI
  manifest's own numerator/denominator or expression. This is what makes
  "re-derived KPIs must cite the certified definition" enforceable rather than
  advisory: there is one place the measure is written.
* **quality attachments** — the product's quality rules as platform-native data
  metric functions, so results flow back into ``quality_result`` from the
  platform that actually holds the data.

Snowflake is the reference dialect. The ANSI variant is what a platform without
masking policies or DMFs gets, and it says so in the header rather than
pretending the guarantees are the same.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.generators._manifests import digest_of, load
from scripts.generators.header import write_generated

SOURCE = "manifests/products/*.yaml"
VERSION = "1.0.0"

# Masking is applied to any column carrying one of these classifications. The
# policy name is the classification, so a platform administrator can see which
# policy covers what without reading the generator.
MASKED_CLASSIFICATIONS = ("pii", "phi", "pci", "credential")


def _schema_for(product_id: str) -> str:
    return product_id.replace("-", "_").upper()


def _masking_policy(column: dict[str, Any]) -> str | None:
    for classification in MASKED_CLASSIFICATIONS:
        if classification in column.get("classification", []):
            return f"MASK_{classification.upper()}"
    return None


def _governed_view(product: dict[str, Any], *, dialect: str) -> str:
    metadata = product["metadata"]
    spec = product["spec"]
    schema = _schema_for(metadata["id"])
    contract = spec["contract"]

    lines = [
        f"-- Governed consumption view for {metadata['id']} — {metadata['name']}",
        f"-- contract {contract['version']}, "
        f"max sensitivity {contract['classification']['max_sensitivity']}, "
        f"contains PII: {str(contract['classification']['contains_pii']).lower()}",
        f"-- grain: {spec['grain']}",
        "--",
        "-- Row and column policy is enforced by the platform, never by the caller.",
        f"CREATE OR REPLACE VIEW {schema}.V_{schema} AS",
        "SELECT",
    ]

    # The separator sits before the comment, so a trailing comment never swallows
    # the comma that the next column depends on.
    rendered: list[str] = []
    columns = spec["columns"]
    for index, column in enumerate(columns):
        policy = _masking_policy(column)
        separator = "" if index == len(columns) - 1 else ","
        if policy and dialect == "snowflake":
            comment = f"  -- masking policy {policy} attached below"
        elif policy:
            comment = f"  -- {policy} unavailable on this platform; grant by column instead"
        else:
            comment = ""
        rendered.append(f"  {column['name']}{separator}{comment}")
    lines.append("\n".join(rendered))
    lines.append(f"FROM {schema}.T_{schema};")

    if dialect == "snowflake":
        lines.append("")
        lines.append("-- Column masking, applied in the platform.")
        for column in spec["columns"]:
            policy = _masking_policy(column)
            if policy:
                lines.append(
                    f"ALTER TABLE {schema}.T_{schema} MODIFY COLUMN {column['name']} "
                    f"SET MASKING POLICY GOVERNANCE.{policy};"
                )
        lines.append("")
        lines.append("-- Purpose binding is mandatory above Internal; the row access policy")
        lines.append("-- reads the session purpose set by the gateway and fails closed.")
        if contract["classification"]["max_sensitivity"] in ("confidential", "restricted"):
            lines.append(
                f"ALTER TABLE {schema}.T_{schema} ADD ROW ACCESS POLICY "
                f"GOVERNANCE.PURPOSE_BOUND ON (ALL);"
            )

    return "\n".join(lines)


def _semantic_view(
    product: dict[str, Any], kpis: dict[str, dict[str, Any]], *, dialect: str
) -> str:
    metadata = product["metadata"]
    spec = product["spec"]
    schema = _schema_for(metadata["id"])

    lines = [
        f"-- Semantic view for {metadata['id']} — one measure per certified KPI.",
        "-- Each measure is written exactly once, from the KPI manifest, so a re-derived",
        "-- figure can cite the certified definition rather than approximate it.",
        f"CREATE OR REPLACE VIEW {schema}.SV_{schema} AS",
        "SELECT",
    ]

    dimensions = [
        column["name"]
        for column in spec["columns"]
        if not column.get("classification")
        and column["type"] in ("string", "date", "timestamp", "boolean")
    ]
    measures: list[str] = []
    for kpi_id in spec["certified_kpis"]:
        kpi = kpis.get(kpi_id)
        if kpi is None:
            continue
        kpi_spec = kpi["spec"]
        alias = kpi_id.replace("-", "_").lower()
        if kpi_spec.get("expression"):
            expression = kpi_spec["expression"]
        else:
            numerator = kpi_spec["numerator_expr"]
            denominator = kpi_spec["denominator_expr"]
            scale = " * 100" if kpi_spec["unit"] == "percent" else ""
            expression = f"({numerator}) / NULLIF({denominator}, 0){scale}"
        measures.append(
            (
                f"  {expression} AS {alias}",
                f"  -- {kpi['metadata']['name']} ({kpi_id}), unit {kpi_spec['unit']}",
            )
        )

    projected: list[tuple[str, str]] = [(f"  {name}", "") for name in dimensions] + measures
    lines.append(
        "\n".join(
            expression + ("" if index == len(projected) - 1 else ",") + comment
            for index, (expression, comment) in enumerate(projected)
        )
    )
    lines.append(f"FROM {schema}.V_{schema}")
    if dimensions:
        lines.append("GROUP BY " + ", ".join(str(index) for index in range(1, len(dimensions) + 1)))
    lines[-1] += ";"
    if dialect != "snowflake":
        lines.insert(
            1,
            "-- ANSI dialect: no semantic layer object exists, so this is a plain view.",
        )
    return "\n".join(lines)


def _quality_attachments(product: dict[str, Any], *, dialect: str) -> str:
    metadata = product["metadata"]
    spec = product["spec"]
    schema = _schema_for(metadata["id"])

    lines = [
        f"-- Quality rule attachments for {metadata['id']}.",
        "-- Results land in quality_result and are the evidence a composite is computed from.",
    ]
    if dialect != "snowflake":
        lines.append("-- ANSI dialect: emitted as check queries for an external scheduler.")

    for rule in spec["quality_rules"]:
        target = rule.get("column") or ", ".join(rule.get("columns", []))
        lines.append("")
        lines.append(
            f"-- {rule['id']}: {rule['dimension']} / {rule['rule']} "
            f"(severity {rule['severity']})"
        )
        if dialect == "snowflake":
            lines.append(
                f"ALTER TABLE {schema}.T_{schema} ADD DATA METRIC FUNCTION "
                f"GOVERNANCE.DMF_{rule['rule'].upper()} ON ({target or '*'});"
            )
        else:
            lines.append(
                f"-- SELECT '{rule['id']}' AS rule_id, ... FROM {schema}.T_{schema};"
            )
    return "\n".join(lines)


def generate(output_root: Path) -> list[Path]:
    products = load("products")
    kpi_documents = {document["metadata"]["id"]: document for _, document in load("kpis")}
    if not products:
        return []

    digest = digest_of([path for path, _ in products])
    written: list[Path] = []

    for dialect in ("snowflake", "ansi"):
        for path, product in products:
            product_id = product["metadata"]["id"]
            body = "\n\n".join(
                [
                    _governed_view(product, dialect=dialect),
                    _semantic_view(product, kpi_documents, dialect=dialect),
                    _quality_attachments(product, dialect=dialect),
                ]
            )
            target = output_root / "sql" / dialect / f"{product_id}.sql"
            write_generated(
                target,
                body,
                source=f"manifests/products/{path.name}",
                version=VERSION,
                digest=digest,
            )
            written.append(target)

    return written
