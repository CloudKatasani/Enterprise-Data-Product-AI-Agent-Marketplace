"""M1.1 — the canonical model covers section 6.1 and carries its guarantees structurally."""

from __future__ import annotations

import re

from scripts.generators import canonical_model as model
from scripts.generators.model import TENANT_SETTING

# BUILD.md section 6.1, verbatim.
EXPECTED_ENTITIES = {
    "reference": {
        "tenant", "industry", "business_domain", "product_archetype", "sensitivity_tier",
        "purpose_category", "source_system",
    },
    "identity": {"party", "org_unit", "role_assignment"},
    "supply_data": {
        "data_product", "data_product_version", "data_product_column",
        "data_contract_version", "contract_guarantee", "endpoint",
    },
    "semantics": {"kpi_definition", "kpi_definition_version", "glossary_term", "kpi_synonym"},
    "supply_agents": {
        "agent", "agent_version", "agent_kpi_coverage", "agent_product_binding",
        "agent_tool_binding", "demo_exchange", "evaluation_case", "evaluation_run",
        "prompt_artifact",
    },
    "quality": {
        "quality_rule", "quality_result", "quality_score_snapshot", "incident",
        "incident_impact",
    },
    "lineage_mesh": {"lineage_edge", "mesh_edge_data", "mesh_edge_agent"},
    "demand_workflow": {
        "request", "request_item", "approval_step", "decision", "demand_vote",
        "demand_theme", "enhancement",
    },
    "entitlement": {"entitlement_grant", "grant_scope", "purpose_binding", "revocation"},
    "telemetry": {
        "usage_event", "usage_daily_agg", "agent_interaction", "answer_feedback",
        "cost_allocation",
    },
    "value": {"value_case", "value_assumption", "value_measurement"},
    "config": {
        "rubric", "rubric_version", "rubric_criterion", "policy", "policy_version",
        "feature_flag",
    },
    "academy": {
        "academy_module", "learning_path", "enrollment", "assessment_result", "certification",
    },
    "audit": {"audit_event", "publication_snapshot"},
}

APPEND_ONLY = {
    "quality_score_snapshot", "publication_snapshot", "audit_event", "entitlement_grant",
}

# Reference and configuration vocabulary is shared across tenants by design.
GLOBAL_TABLES = {
    "tenant", "industry", "business_domain", "product_archetype", "sensitivity_tier",
    "purpose_category",
}


def _by_name() -> dict[str, object]:
    return {table.name: table for table in model.ALL_TABLES}


def test_every_entity_group_in_section_6_1_is_present() -> None:
    tables = _by_name()
    missing = {
        group: sorted(names - tables.keys()) for group, names in EXPECTED_ENTITIES.items()
    }
    assert {group: names for group, names in missing.items() if names} == {}


def test_entities_are_declared_in_their_stated_group() -> None:
    tables = _by_name()
    misplaced = {
        name: tables[name].group
        for group, names in EXPECTED_ENTITIES.items()
        for name in names
        if tables[name].group != group
    }
    assert misplaced == {}


def test_table_names_are_unique() -> None:
    names = [table.name for table in model.ALL_TABLES]
    assert len(names) == len(set(names))


def test_every_tenant_scoped_table_carries_tenant_id() -> None:
    offenders = [
        table.name
        for table in model.ALL_TABLES
        if table.tenant_scoped
        and not any(column.name == "tenant_id" for column in table.all_columns())
    ]
    assert offenders == []


def test_only_shared_vocabulary_is_tenant_independent() -> None:
    unscoped = {table.name for table in model.ALL_TABLES if not table.tenant_scoped}
    assert unscoped == GLOBAL_TABLES


def test_append_only_tables_are_exactly_the_four_named_in_rule_6() -> None:
    declared = {table.name for table in model.ALL_TABLES if table.append_only}
    assert declared == APPEND_ONLY


def test_foreign_keys_reference_declared_tables() -> None:
    tables = _by_name()
    unresolved: list[str] = []
    for table in model.ALL_TABLES:
        for column in table.all_columns():
            if column.references is None:
                continue
            target = column.references.split("(", maxsplit=1)[0]
            if target not in tables:
                unresolved.append(f"{table.name}.{column.name} -> {target}")
    assert unresolved == []


def test_every_table_has_exactly_one_primary_key() -> None:
    offenders = [
        table.name
        for table in model.ALL_TABLES
        if len([c for c in table.all_columns() if c.primary_key]) != 1
    ]
    assert offenders == []


def test_kpi_definition_declares_the_i1_partial_unique_index() -> None:
    kpi = _by_name()["kpi_definition"]
    index = next(i for i in kpi.indexes if i.name == "kpi_one_active")
    assert index.unique is True
    assert index.columns == "tenant_id, lower(kpi_name)"
    assert index.where == "status IN ('draft','certified')"


def test_quality_snapshot_requires_a_rubric_version() -> None:
    snapshot = _by_name()["quality_score_snapshot"]
    column = next(c for c in snapshot.columns if c.name == "rubric_version_id")
    assert column.null is False
    assert column.references == "rubric_version(rubric_version_id)"


def test_mesh_edges_require_confidence_and_a_rationale() -> None:
    for name in ("mesh_edge_data", "mesh_edge_agent"):
        table = _by_name()[name]
        confidence = next(c for c in table.columns if c.name == "confidence")
        rationale = next(c for c in table.columns if c.name == "rationale")
        assert confidence.null is False
        assert rationale.null is False
        assert rationale.check == "length(trim(rationale)) > 10"
        assert "confidence >= 0.80 OR reviewed_by IS NOT NULL" in table.table_checks


def test_agent_version_requires_a_non_empty_out_of_scope() -> None:
    column = next(
        c for c in _by_name()["agent_version"].columns if c.name == "out_of_scope"
    )
    assert column.null is False
    assert column.check == "array_length(out_of_scope,1) >= 1"


def test_coverage_rows_cite_a_real_kpi() -> None:
    column = next(
        c for c in _by_name()["agent_kpi_coverage"].columns if c.name == "kpi_id"
    )
    assert column.references == "kpi_definition(kpi_id)"
    assert column.null is False


def test_emitted_ddl_enables_rls_and_a_policy_for_every_tenant_scoped_table() -> None:
    from scripts.generators.ddl import GROUP_ORDER, _group_body

    sql = "\n".join(_group_body(group) for group, _ in GROUP_ORDER)
    for table in model.ALL_TABLES:
        if not table.tenant_scoped:
            continue
        assert f"ALTER TABLE {table.name} ENABLE ROW LEVEL SECURITY;" in sql
        assert f"CREATE POLICY {table.name}_tenant_isolation ON {table.name}" in sql
    assert TENANT_SETTING in sql


def test_emitted_ddl_revokes_write_verbs_on_append_only_tables() -> None:
    from scripts.generators.ddl import GROUP_ORDER, _group_body

    sql = "\n".join(_group_body(group) for group, _ in GROUP_ORDER)
    for name in APPEND_ONLY:
        assert re.search(rf"REVOKE UPDATE, DELETE ON {name} FROM app_role;", sql)


def test_generated_ddl_is_deterministic() -> None:
    from scripts.generators.ddl import GROUP_ORDER, _group_body, _model_digest

    first = [_group_body(group) for group, _ in GROUP_ORDER]
    second = [_group_body(group) for group, _ in GROUP_ORDER]
    assert first == second
    assert _model_digest() == _model_digest()
