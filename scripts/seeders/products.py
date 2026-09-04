"""Data products from their manifests into the canonical model.

The manifest is the contract: what the product promises. The connector harvest
is the observation: what the platform actually holds. Both write
``data_product_column``, and where they disagree the connector records drift
rather than silently overwriting — a column that gained a PII classification in
the platform but not in the manifest is a governance finding, not a merge.

Sensitivity is never written here: the trigger derives it from the columns (I5).
"""

from __future__ import annotations

from typing import Any

import psycopg

from scripts.seeders._base import load_directory


def _endpoint_uri(product_id: str, surface: str) -> str:
    schema = product_id.replace("-", "_").upper()
    return {
        "sql": f"snowflake://MARKETPLACE/{schema}/V_{schema}",
        "rest": f"/api/v1/products/{product_id}/data",
        "mcp": f"mcp://marketplace.${{TENANT}}.internal/dp/{product_id}",
        "stream": f"kafka://marketplace/{product_id.lower()}",
        "share": f"snowflake-share://MARKETPLACE/{schema}",
    }[surface]


def seed(connection: psycopg.Connection[Any], tenant: str) -> int:
    documents = load_directory("products")
    written = 0

    with connection.cursor() as cursor:
        for document in documents:
            metadata = document["metadata"]
            spec = document["spec"]
            product_id = metadata["id"]
            contract = spec["contract"]

            cursor.execute(
                """
                INSERT INTO data_product (
                  product_id, tenant_id, name, purpose, industry_code, domain_code,
                  archetype_code, sensitivity_tier, certification, owner_party_id,
                  current_version, grain, history_months, known_limitations, tier
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'public', %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (product_id) DO UPDATE SET
                  name = EXCLUDED.name, purpose = EXCLUDED.purpose,
                  industry_code = EXCLUDED.industry_code, domain_code = EXCLUDED.domain_code,
                  archetype_code = EXCLUDED.archetype_code,
                  certification = EXCLUDED.certification,
                  owner_party_id = EXCLUDED.owner_party_id,
                  current_version = EXCLUDED.current_version, grain = EXCLUDED.grain,
                  history_months = EXCLUDED.history_months,
                  known_limitations = EXCLUDED.known_limitations, tier = EXCLUDED.tier
                """,
                (product_id, tenant, metadata["name"], spec["purpose"], metadata["industry"],
                 metadata["domain"], metadata["archetype"], metadata["certification"],
                 metadata["owner"]["party_id"], contract["version"], spec["grain"],
                 spec["history_months"], spec["known_limitations"],
                 metadata.get("tier", "tier2")),
            )
            written += 1

            for ordinal, column in enumerate(spec["columns"], start=1):
                cursor.execute(
                    """
                    INSERT INTO data_product_column (
                      column_id, tenant_id, product_id, name, business_name, data_type,
                      nullable, classification, sensitivity_code, description, ordinal
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (product_id, name) DO UPDATE SET
                      business_name = EXCLUDED.business_name,
                      data_type = EXCLUDED.data_type, nullable = EXCLUDED.nullable,
                      classification = EXCLUDED.classification,
                      sensitivity_code = EXCLUDED.sensitivity_code,
                      description = EXCLUDED.description, ordinal = EXCLUDED.ordinal
                    """,
                    (f"COL-{product_id}-{column['name']}", tenant, product_id, column["name"],
                     column["business_name"], column["type"], column["nullable"],
                     column.get("classification", []),
                     column.get("sensitivity", "internal"), column["description"], ordinal),
                )
                written += 1

            cursor.execute(
                """
                INSERT INTO data_product_version (
                  product_version_id, tenant_id, product_id, semver, status, change_summary,
                  schema_stability, published_at, published_by
                ) VALUES (%s, %s, %s, %s, 'published', %s, %s, now(), %s)
                ON CONFLICT (product_version_id) DO UPDATE SET
                  status = EXCLUDED.status, change_summary = EXCLUDED.change_summary
                """,
                (f"DPV-{product_id}-{contract['version']}", tenant, product_id,
                 contract["version"], "Seeded from the product manifest.",
                 contract["schema_stability"], metadata["owner"]["party_id"]),
            )
            written += 1

            contract_version_id = f"DCV-{product_id}-{contract['version']}"
            classification = contract["classification"]
            cursor.execute(
                """
                INSERT INTO data_contract_version (
                  contract_version_id, tenant_id, product_id, semver, status,
                  schema_stability, deprecation_notice_days, minimum_parallel_run_days,
                  support_hours, p1_response_minutes, on_call, max_sensitivity, contains_pii,
                  residency, consumer_obligations, breach_process
                ) VALUES (%s, %s, %s, %s, 'active', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (contract_version_id) DO UPDATE SET
                  status = EXCLUDED.status,
                  consumer_obligations = EXCLUDED.consumer_obligations,
                  breach_process = EXCLUDED.breach_process
                """,
                (contract_version_id, tenant, product_id, contract["version"],
                 contract["schema_stability"], contract["deprecation_policy"]["notice_days"],
                 contract["deprecation_policy"]["minimum_parallel_run_days"],
                 contract["support"]["hours"], contract["support"]["p1_response_minutes"],
                 contract["support"]["on_call"], classification["max_sensitivity"],
                 classification["contains_pii"], classification["residency"],
                 contract["consumer_obligations"], contract["breach_process"]),
            )
            written += 1

            guarantees = contract["guarantees"]
            for dimension, target_text, numeric, unit, window, grain, reference in (
                ("freshness", guarantees["freshness"]["target"],
                 guarantees["freshness"]["p95_minutes"], "minutes", "daily",
                 guarantees["freshness"]["measured"], None),
                ("availability", f"{guarantees['availability']['target_pct']}%",
                 guarantees["availability"]["target_pct"], "percent",
                 guarantees["availability"]["window"], "service", None),
                ("completeness", f"{guarantees['completeness']['required_fields_pct']}%",
                 guarantees["completeness"]["required_fields_pct"], "percent", "daily",
                 "required_fields", None),
                ("accuracy",
                 f"variance <= {guarantees['accuracy']['reconciliation_variance_pct']}%",
                 guarantees["accuracy"]["reconciliation_variance_pct"], "percent", "daily",
                 "reconciliation", guarantees["accuracy"]["against"]),
            ):
                cursor.execute(
                    """
                    INSERT INTO contract_guarantee (
                      guarantee_id, tenant_id, contract_version_id, dimension, target_text,
                      target_numeric, unit, measurement_window, measured_at_grain,
                      reference_system
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (contract_version_id, dimension) DO UPDATE SET
                      target_text = EXCLUDED.target_text,
                      target_numeric = EXCLUDED.target_numeric
                    """,
                    (f"CG-{product_id}-{dimension}", tenant, contract_version_id, dimension,
                     target_text, numeric, unit, window, grain, reference),
                )
                written += 1

            for surface in spec["endpoints"]:
                cursor.execute(
                    """
                    INSERT INTO endpoint (
                      endpoint_id, tenant_id, product_id, surface, uri, auth_mode,
                      required_scope, row_limit, documentation_ref
                    ) VALUES (%s, %s, %s, %s, %s, 'oauth2', %s, %s, %s)
                    ON CONFLICT (product_id, surface) DO UPDATE SET
                      uri = EXCLUDED.uri, required_scope = EXCLUDED.required_scope
                    """,
                    (f"EP-{product_id}-{surface}", tenant, product_id, surface,
                     _endpoint_uri(product_id, surface), f"dp:{product_id}:read",
                     spec["demo_tier"]["rows_target"], f"/data-products/{product_id}#endpoints"),
                )
                written += 1

            for rule in spec["quality_rules"]:
                targets = [rule["column"]] if "column" in rule else rule.get("columns", [])
                cursor.execute(
                    """
                    INSERT INTO quality_rule (
                      rule_id, tenant_id, product_id, dimension, rule_type, target_columns,
                      threshold_pct, target_text, tolerance_minutes, severity
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (rule_id) DO UPDATE SET
                      dimension = EXCLUDED.dimension, rule_type = EXCLUDED.rule_type,
                      target_columns = EXCLUDED.target_columns,
                      threshold_pct = EXCLUDED.threshold_pct,
                      target_text = EXCLUDED.target_text,
                      tolerance_minutes = EXCLUDED.tolerance_minutes,
                      severity = EXCLUDED.severity
                    """,
                    (rule["id"], tenant, product_id, rule["dimension"], rule["rule"], targets,
                     rule.get("threshold_pct"), rule.get("target"),
                     rule.get("tolerance_minutes"), rule["severity"]),
                )
                written += 1

            written += _seed_value_case(cursor, tenant, product_id, spec["value_case"])

    return written


def _seed_value_case(
    cursor: psycopg.Cursor[Any], tenant: str, product_id: str, value_case: dict[str, Any]
) -> int:
    """The value case, its assumptions and the review clock.

    The rubric version is recorded on the case so a benefit figure can be
    replayed against the deflection model that was in force when it was written.
    """
    cursor.execute(
        "SELECT rv.rubric_version_id FROM rubric_version rv "
        "JOIN rubric r ON r.rubric_id = rv.rubric_id "
        "WHERE r.code = 'value_model' AND r.tenant_id = %s AND rv.superseded_at IS NULL "
        "ORDER BY rv.effective_from DESC LIMIT 1",
        (tenant,),
    )
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError(
            "the value_model rubric must be seeded before value cases; check the seeder order"
        )
    rubric_version_id = dict(row)["rubric_version_id"]

    cursor.execute(
        "SELECT numeric_value FROM rubric_criterion "
        "WHERE rubric_version_id = %s AND path = 'value_case_review_months'",
        (rubric_version_id,),
    )
    months_row = cursor.fetchone()
    review_months = int(dict(months_row)["numeric_value"]) if months_row else None
    if review_months is None:
        raise RuntimeError("the value_model rubric declares no value_case_review_months")

    review = value_case["review"]
    value_case_id = f"VC-data_product-{product_id}"
    cursor.execute(
        """
        INSERT INTO value_case (
          value_case_id, tenant_id, asset_type, asset_id, business_outcome, baseline_method,
          baseline_captured, benefit_model, attribution_confidence, rubric_version_id,
          last_reviewed, reviewer_party_id, review_due
        ) VALUES (%s, %s, 'data_product', %s, %s, %s, to_date(%s, 'YYYY-MM'), %s, %s, %s, %s,
                  %s, (to_date(%s, 'YYYY-MM-DD') + (%s || ' months')::interval)::date)
        ON CONFLICT (asset_type, asset_id) DO UPDATE SET
          business_outcome = EXCLUDED.business_outcome,
          benefit_model = EXCLUDED.benefit_model,
          attribution_confidence = EXCLUDED.attribution_confidence,
          rubric_version_id = EXCLUDED.rubric_version_id,
          last_reviewed = EXCLUDED.last_reviewed,
          review_due = EXCLUDED.review_due
        """,
        (value_case_id, tenant, product_id, value_case["business_outcome"],
         value_case["baseline"]["method"], value_case["baseline"]["captured"],
         value_case["benefit_model"], value_case["attribution_confidence"],
         rubric_version_id, review["last_reviewed"], review["reviewer"],
         review["last_reviewed"], review_months),
    )
    written = 1

    for index, assumption in enumerate(value_case["assumptions"]):
        cursor.execute(
            """
            INSERT INTO value_assumption (
              assumption_id, tenant_id, value_case_id, text, numeric_value, unit,
              sample_size, source, dated
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, to_date(%s, 'YYYY-MM-DD'))
            ON CONFLICT (assumption_id) DO UPDATE SET
              numeric_value = EXCLUDED.numeric_value, sample_size = EXCLUDED.sample_size,
              source = EXCLUDED.source, dated = EXCLUDED.dated
            """,
            (f"{value_case_id}-{index:02d}", tenant, value_case_id, assumption["text"],
             assumption["value"], assumption.get("unit", "unit"),
             assumption.get("sample_size"), assumption["source"], assumption["dated"]),
        )
        written += 1

    return written
