"""gen:ddl — the canonical model definition -> generated/ddl/NNNN_*.sql.

Migrations are grouped by entity group so a reviewer reads them in the same order
as BUILD.md section 6.1. Within a group, tables emit in declaration order, and
each table emits its columns, table checks, unique constraints and indexes in
declaration order; that fixed ordering is what makes regeneration byte-identical
(I9).

Two properties are structural rather than remembered:

  * every tenant-scoped table gets ``tenant_id``, ``ENABLE ROW LEVEL SECURITY``
    and a policy keyed on the ``app.tenant_id`` session setting;
  * every append-only table gets ``REVOKE UPDATE, DELETE``.

``scripts/lint/migrations.py`` re-checks both against the emitted SQL, so a table
added without them fails the build rather than shipping.
"""

from __future__ import annotations

from pathlib import Path

from scripts.generators import canonical_model as model
from scripts.generators.header import content_digest, write_generated
from scripts.generators.model import APP_ROLE, TENANT_SETTING, RawBlock, Table

SOURCE = "scripts/generators/canonical_model.py"

GROUP_ORDER: list[tuple[str, str]] = [
    ("bootstrap", "extensions and the application role"),
    ("reference", "reference taxonomies and tenancy"),
    ("identity", "parties, org units and role assignments"),
    ("supply_data", "data products, versions, columns, contracts and endpoints"),
    ("semantics", "KPI register, versions, synonyms and glossary"),
    ("config", "rubrics, policies and feature flags"),
    ("supply_agents", "agents, versions, coverage, bindings, demos and evaluation"),
    ("quality", "rules, results, immutable score snapshots and incidents"),
    ("lineage_mesh", "lineage, both meshes and the search indexes"),
    ("demand_workflow", "requests, approvals, decisions, demand and durable workflow"),
    ("entitlement", "grants, scopes, purpose bindings, revocations and drift"),
    ("telemetry", "usage, agent interactions, feedback and cost"),
    ("value", "value cases, assumptions and measurements"),
    ("academy", "modules, paths, enrollments, assessments and certifications"),
    ("audit", "immutable audit events and publication snapshots"),
    ("constraints", "derived columns, search maintenance and append-only enforcement"),
]


def _render_table(table: Table) -> str:
    lines: list[str] = []
    lines.append(f"-- {table.name}: {table.purpose}")
    if table.invariants:
        lines.append(f"-- invariants: {', '.join(table.invariants)}")
    lines.append(f"CREATE TABLE {table.name} (")

    body: list[str] = []
    for column in table.all_columns():
        rendered = f"  {column.render()}"
        if column.comment:
            rendered += f"  -- {column.comment}"
        body.append(rendered)

    for check in table.table_checks:
        body.append(f"  CHECK ({check})")
    for combination in table.unique_together:
        body.append(f"  UNIQUE ({', '.join(combination)})")

    # Trailing commas belong to every line but the last; comments sit after them.
    for index, line in enumerate(body):
        is_last = index == len(body) - 1
        if "  -- " in line:
            code, _, comment = line.partition("  -- ")
            body[index] = code + ("" if is_last else ",") + "  -- " + comment
        else:
            body[index] = line + ("" if is_last else ",")

    lines.extend(body)
    lines.append(");")

    for ordinal, index_def in enumerate(table.indexes, start=1):
        lines.append(index_def.render(table.name, ordinal))

    if table.tenant_scoped:
        lines.append(f"ALTER TABLE {table.name} ENABLE ROW LEVEL SECURITY;")
        lines.append(f"ALTER TABLE {table.name} FORCE ROW LEVEL SECURITY;")
        lines.append(
            f"CREATE POLICY {table.name}_tenant_isolation ON {table.name}\n"
            f"  USING (tenant_id = current_setting('{TENANT_SETTING}', true))\n"
            f"  WITH CHECK (tenant_id = current_setting('{TENANT_SETTING}', true));"
        )

    if table.append_only:
        verbs = "DELETE" if table.stamped_in_place else "UPDATE, DELETE"
        lines.append(
            f"-- rule 6: append-only. History is written, never rewritten.\n"
            f"REVOKE {verbs} ON {table.name} FROM {APP_ROLE};"
        )

    lines.append(f"GRANT SELECT, INSERT ON {table.name} TO {APP_ROLE};")
    if not table.append_only:
        lines.append(f"GRANT UPDATE, DELETE ON {table.name} TO {APP_ROLE};")
    elif table.stamped_in_place:
        # The trigger, not the grant, is what makes this table history: it
        # freezes every term and permits only the columns that record what
        # happened to the grant afterwards.
        lines.append(f"GRANT UPDATE ON {table.name} TO {APP_ROLE};")

    return "\n".join(lines)


def _render_raw(block: RawBlock) -> str:
    header = f"-- {block.name}: {block.purpose}"
    if block.invariants:
        header += f"\n-- invariants: {', '.join(block.invariants)}"
    return f"{header}\n{block.sql}"


def _group_body(group: str) -> str:
    chunks: list[str] = []
    if group == "bootstrap":
        chunks.append(_render_raw(model.EXTENSIONS))
    for table in model.ALL_TABLES:
        if table.group == group:
            chunks.append(_render_table(table))
    for block in model.RAW_BLOCKS:
        if block.group == group:
            chunks.append(_render_raw(block))
    return "\n\n".join(chunks)


def _model_digest() -> str:
    """Hash the model's rendered content, not the source file, so a comment change
    in the generator does not restamp every migration."""
    parts = [_group_body(group) for group, _ in GROUP_ORDER]
    return content_digest(*parts)


def generate(output_root: Path) -> list[Path]:
    digest = _model_digest()
    written: list[Path] = []
    ddl_dir = output_root / "ddl"

    for ordinal, (group, description) in enumerate(GROUP_ORDER, start=1):
        body = _group_body(group)
        if not body:
            continue
        filename = f"{ordinal:04d}_{group}.sql"
        path = ddl_dir / filename
        preamble = f"-- {description}\n\n"
        write_generated(
            path,
            preamble + body,
            source=SOURCE,
            version=model.GENERATOR_VERSION,
            digest=digest,
        )
        written.append(path)

    return written
