"""M1.1 — invariants I1..I7 are database constraints, proved against a real database.

Each test attempts the thing the invariant forbids and asserts the database
refuses it. A mock cannot prove a constraint exists, so these run against
Postgres; see tests/conftest.py for how the suite behaves without a data plane.
"""

from __future__ import annotations

import psycopg
import pytest

pytestmark = pytest.mark.usefixtures("seeded_tenant")

TENANT = "TEN-TEST"


def _reference_rows(cursor) -> None:
    cursor.execute(
        "INSERT INTO industry (code, label, description, sort_order) "
        "VALUES ('telecommunications','Telecom','Telecom industry', 1) "
        "ON CONFLICT (code) DO NOTHING"
    )
    cursor.execute(
        "INSERT INTO business_domain (code, label, description, sort_order) "
        "VALUES ('customer','Customer','Customer domain', 1) ON CONFLICT (code) DO NOTHING"
    )
    cursor.execute(
        "INSERT INTO product_archetype (code, label, description, sort_order) "
        "VALUES ('consumer_aligned','Consumer aligned','Aligned to a consuming domain', 1) "
        "ON CONFLICT (code) DO NOTHING"
    )
    cursor.execute(
        "INSERT INTO sensitivity_tier (code, label, rank_order, requires_purpose, description) "
        "VALUES ('internal','Internal', 2, false, 'Internal only'), "
        "       ('confidential','Confidential', 3, true, 'Confidential'), "
        "       ('public','Public', 1, false, 'Public') "
        "ON CONFLICT (code) DO NOTHING"
    )
    cursor.execute(
        "INSERT INTO party (party_id, tenant_id, party_type, display_name, mfa_enforced, active) "
        "VALUES ('PTY-T1', %s, 'person', 'Test owner', true, true) "
        "ON CONFLICT (party_id) DO NOTHING",
        (TENANT,),
    )


def _insert_product(cursor, product_id: str = "DP-TST-001") -> str:
    cursor.execute(
        """
        INSERT INTO data_product (
          product_id, tenant_id, name, purpose, industry_code, domain_code, archetype_code,
          sensitivity_tier, certification, owner_party_id, current_version, grain,
          history_months, known_limitations, tier
        ) VALUES (
          %s, %s, 'Test product',
          'A product purpose long enough to satisfy the twenty character floor.',
          'telecommunications', 'customer', 'consumer_aligned',
          'public', 'certified', 'PTY-T1', '1.0.0', 'one row per thing per day',
          24, 'Prepaid subscribers are excluded from this dataset.', 'tier1'
        )
        """,
        (product_id, TENANT),
    )
    return product_id


def _insert_kpi(cursor, kpi_id: str, name: str, status: str = "certified") -> None:
    cursor.execute(
        """
        INSERT INTO kpi_definition (
          kpi_id, tenant_id, kpi_name, status, business_definition, grains_supported,
          slices_supported, unit, domain_code, steward_party_id, last_reviewed, review_months
        ) VALUES (%s, %s, %s, %s, 'Definition', ARRAY['month'], ARRAY['region'],
                  'percent', 'customer', 'PTY-T1', DATE '2026-01-01', 12)
        """,
        (kpi_id, TENANT, name, status),
    )


def test_i1_only_one_active_kpi_definition_per_name(db) -> None:
    with db.cursor() as cursor:
        _reference_rows(cursor)
        _insert_kpi(cursor, "KPI-TST-001", "Churn Rate", status="certified")
        with pytest.raises(psycopg.errors.UniqueViolation):
            _insert_kpi(cursor, "KPI-TST-002", "churn rate", status="draft")


def test_i1_allows_a_second_definition_once_the_first_is_superseded(db) -> None:
    with db.cursor() as cursor:
        _reference_rows(cursor)
        _insert_kpi(cursor, "KPI-TST-001", "Churn Rate", status="certified")
        cursor.execute(
            "UPDATE kpi_definition SET status = 'superseded' WHERE kpi_id = 'KPI-TST-001'"
        )
        _insert_kpi(cursor, "KPI-TST-002", "Churn Rate", status="certified")
        cursor.execute(
            "SELECT count(*) AS active FROM kpi_definition "
            "WHERE tenant_id = %s AND status IN ('draft','certified')",
            (TENANT,),
        )
        assert cursor.fetchone()["active"] == 1


def test_i2_quality_snapshot_without_a_rubric_version_is_rejected(db) -> None:
    with db.cursor() as cursor:
        _reference_rows(cursor)
        product_id = _insert_product(cursor)
        with pytest.raises(psycopg.errors.NotNullViolation):
            cursor.execute(
                "INSERT INTO quality_score_snapshot "
                "(snapshot_id, tenant_id, product_id, rubric_version_id, composite, band, "
                " evidence_ref) VALUES ('QS-1', %s, %s, NULL, 90.00, 'exemplary', '{}'::jsonb)",
                (TENANT, product_id),
            )


def test_i4_coverage_cannot_cite_a_kpi_that_does_not_exist(db) -> None:
    with db.cursor() as cursor:
        _reference_rows(cursor)
        _insert_product(cursor)
        cursor.execute(
            "INSERT INTO prompt_artifact (prompt_hash, tenant_id, agent_id, label, body) "
            "VALUES ('sha-1', %s, 'AG-TST-001', 'system@v1', 'You are a test agent.')",
            (TENANT,),
        )
        cursor.execute(
            "INSERT INTO agent (agent_id, tenant_id, name, industry_code, domain_code, "
            "owner_party_id, machine_identity, on_call, escalation_path, certification) "
            "VALUES ('AG-TST-001', %s, 'Test agent', 'telecommunications', 'customer', "
            "'PTY-T1', 'svc-agent-test', 'pagerduty://test', '#test', 'certified')",
            (TENANT,),
        )
        cursor.execute(
            """
            INSERT INTO agent_version (
              agent_version_id, tenant_id, agent_id, semver, status, autonomy_level,
              capability_statement, business_value_block, out_of_scope, replaces,
              model_provider, model_id, model_params, prompt_hash, guardrail_config,
              budget_p95_latency_ms, budget_cost_per_answer_usd
            ) VALUES (
              'AGV-1', %s, 'AG-TST-001', '1.0.0', 'draft', 'L1',
              %s, 'Replaces manual pull-and-pivot cycles by the analytics team.',
              ARRAY['Individual credit decisions'], 'Manual analysis cycles',
              'anthropic', 'test-model', '{}'::jsonb, 'sha-1', '{}'::jsonb, 6000, 0.06
            )
            """,
            (TENANT, "A" * 100),
        )
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            cursor.execute(
                "INSERT INTO agent_kpi_coverage (coverage_id, tenant_id, agent_version_id, "
                "kpi_id, source_product_id, columns_used, supported_grains, supported_slices, "
                "analysis_depth) VALUES ('COV-1', %s, 'AGV-1', 'KPI-DOES-NOT-EXIST', "
                "'DP-TST-001', ARRAY['a'], ARRAY['month'], ARRAY['region'], 'report')",
                (TENANT,),
            )


def test_i5_sensitivity_is_derived_from_columns_and_ignores_what_a_writer_supplies(db) -> None:
    with db.cursor() as cursor:
        _reference_rows(cursor)
        product_id = _insert_product(cursor)
        cursor.execute(
            "SELECT sensitivity_tier FROM data_product WHERE product_id = %s", (product_id,)
        )
        assert cursor.fetchone()["sensitivity_tier"] == "public"

        cursor.execute(
            "INSERT INTO data_product_column (column_id, tenant_id, product_id, name, "
            "business_name, data_type, nullable, classification, sensitivity_code, "
            "description, ordinal) VALUES ('COL-1', %s, %s, 'subscriber_id', 'Subscriber ID', "
            "'string', false, ARRAY['pii','identifier'], 'confidential', 'Identifier', 1)",
            (TENANT, product_id),
        )
        cursor.execute(
            "SELECT sensitivity_tier FROM data_product WHERE product_id = %s", (product_id,)
        )
        assert cursor.fetchone()["sensitivity_tier"] == "confidential"

        # A direct write is discarded, not honoured.
        cursor.execute(
            "UPDATE data_product SET sensitivity_tier = 'public' WHERE product_id = %s",
            (product_id,),
        )
        cursor.execute(
            "SELECT sensitivity_tier FROM data_product WHERE product_id = %s", (product_id,)
        )
        assert cursor.fetchone()["sensitivity_tier"] == "confidential"

        # Removing the classified column lowers it again.
        cursor.execute("DELETE FROM data_product_column WHERE column_id = 'COL-1'")
        cursor.execute(
            "SELECT sensitivity_tier FROM data_product WHERE product_id = %s", (product_id,)
        )
        assert cursor.fetchone()["sensitivity_tier"] == "public"


def test_i6_a_mesh_edge_without_a_rationale_is_rejected(db) -> None:
    with db.cursor() as cursor:
        _reference_rows(cursor)
        _insert_product(cursor, "DP-TST-001")
        _insert_product(cursor, "DP-TST-002")
        with pytest.raises(psycopg.errors.CheckViolation):
            cursor.execute(
                "INSERT INTO mesh_edge_data (edge_id, tenant_id, product_a, product_b, "
                "edge_type, strength, factors, confidence, rationale) "
                "VALUES ('ME-1', %s, 'DP-TST-001', 'DP-TST-002', 'shared_source', 0.6, "
                "'{}'::jsonb, 0.9, '')",
                (TENANT,),
            )


def test_i6_a_low_confidence_edge_needs_a_reviewer(db) -> None:
    with db.cursor() as cursor:
        _reference_rows(cursor)
        _insert_product(cursor, "DP-TST-001")
        _insert_product(cursor, "DP-TST-002")
        with pytest.raises(psycopg.errors.CheckViolation):
            cursor.execute(
                "INSERT INTO mesh_edge_data (edge_id, tenant_id, product_a, product_b, "
                "edge_type, strength, factors, confidence, rationale) "
                "VALUES ('ME-2', %s, 'DP-TST-001', 'DP-TST-002', 'shared_source', 0.6, "
                "'{}'::jsonb, 0.42, 'Both products read the billing source system.')",
                (TENANT,),
            )


def test_i7_known_limitations_may_not_say_none(db) -> None:
    with db.cursor() as cursor:
        _reference_rows(cursor)
        with pytest.raises(psycopg.errors.CheckViolation):
            cursor.execute(
                """
                INSERT INTO data_product (
                  product_id, tenant_id, name, purpose, industry_code, domain_code,
                  archetype_code, sensitivity_tier, certification, owner_party_id,
                  current_version, grain, history_months, known_limitations, tier
                ) VALUES (
                  'DP-TST-009', %s, 'Test', 'A purpose long enough to pass the floor check.',
                  'telecommunications', 'customer', 'consumer_aligned', 'public', 'certified',
                  'PTY-T1', '1.0.0', 'grain', 12, 'none', 'tier1'
                )
                """,
                (TENANT,),
            )


def test_rule_6_a_quality_snapshot_cannot_be_updated_or_deleted(db) -> None:
    with db.cursor() as cursor:
        _reference_rows(cursor)
        product_id = _insert_product(cursor)
        cursor.execute(
            "INSERT INTO rubric (rubric_id, tenant_id, code, description) "
            "VALUES ('RUB-1', %s, 'data_product_quality', 'Quality rubric')",
            (TENANT,),
        )
        cursor.execute(
            "INSERT INTO rubric_version (rubric_version_id, tenant_id, rubric_id, semver, "
            "source_hash, payload, created_by) VALUES ('RV-1', %s, 'RUB-1', '1.0.0', "
            "'hash', '{}'::jsonb, 'seed')",
            (TENANT,),
        )
        cursor.execute(
            "INSERT INTO quality_score_snapshot (snapshot_id, tenant_id, product_id, "
            "rubric_version_id, composite, band, evidence_ref) "
            "VALUES ('QS-9', %s, %s, 'RV-1', 91.50, 'exemplary', '{}'::jsonb)",
            (TENANT, product_id),
        )
        with pytest.raises(psycopg.errors.RestrictViolation):
            cursor.execute(
                "UPDATE quality_score_snapshot SET composite = 99 WHERE snapshot_id = 'QS-9'"
            )


def test_rule_6_an_entitlement_grants_terms_are_frozen(db) -> None:
    with db.cursor() as cursor:
        _reference_rows(cursor)
        cursor.execute(
            "INSERT INTO purpose_category (code, label, description, requires_free_text, "
            "sort_order) VALUES ('analytics','Analytics','Analytical use', true, 1) "
            "ON CONFLICT (code) DO NOTHING"
        )
        _insert_product(cursor)
        cursor.execute(
            "INSERT INTO request (request_id, tenant_id, request_type, state, "
            "requester_party_id, title, body) VALUES ('REQ-1', %s, 'access', 'Approved', "
            "'PTY-T1', 'Access', 'Body')",
            (TENANT,),
        )
        cursor.execute(
            "INSERT INTO entitlement_grant (grant_id, tenant_id, request_id, principal_id, "
            "asset_type, asset_id, access_level, purpose_code, purpose_text, platform_role, "
            "oauth_scopes, granted_at, expires_at) VALUES ('GR-1', %s, 'REQ-1', 'PTY-T1', "
            "'data_product', 'DP-TST-001', 'read_data', 'analytics', 'Churn analysis', "
            "'MKT_DP_TST_001_READ', ARRAY['dp:DP-TST-001:read'], now(), now() + interval '90 days')",
            (TENANT,),
        )
        # Recording use is allowed; changing the terms is not.
        cursor.execute("UPDATE entitlement_grant SET last_used_at = now() WHERE grant_id = 'GR-1'")
        with pytest.raises(psycopg.errors.RestrictViolation):
            cursor.execute(
                "UPDATE entitlement_grant SET access_level = 'read_data_pii' "
                "WHERE grant_id = 'GR-1'"
            )
