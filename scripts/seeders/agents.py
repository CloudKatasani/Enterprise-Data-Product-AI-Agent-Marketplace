"""M6.1 — agents, versions, coverage maps and bindings from their manifests.

An agent version is an immutable bundle (15.4): it pins the model, its
parameters, the prompt hash, the tool bindings and the upstream contract
versions it reads. Seeding writes the bundle in `draft`; only the publish gate
moves it to `published`, and it does that by writing a publication snapshot
rather than by flipping a column.

Machine identity is separate from the owner (section 19): each agent gets its
own party, so effective access can be the intersection of the agent's scope and
the user's entitlement (I12).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import psycopg

from scripts._paths import SEED
from scripts.seeders._base import load_directory
from scripts.seeders.parties import machine_party_for


def _prompt_body(agent_id: str) -> str:
    path = SEED / "prompts" / agent_id / "system.md"
    if not path.exists():
        raise FileNotFoundError(
            f"{agent_id} has no system prompt at {path}; run scripts/author_prompts.py"
        )
    return path.read_text(encoding="utf-8")


def _contract_versions(
    cursor: psycopg.Cursor[Any], product_ids: list[str]
) -> dict[str, str]:
    cursor.execute(
        "SELECT product_id, semver FROM data_contract_version "
        "WHERE product_id = ANY(%s) AND status = 'active'",
        (product_ids,),
    )
    return {row["product_id"]: row["semver"] for row in cursor.fetchall()}


def seed(connection: psycopg.Connection[Any], tenant: str) -> int:
    documents = load_directory("agents")
    written = 0

    with connection.cursor() as cursor:
        for document in documents:
            metadata = document["metadata"]
            spec = document["spec"]
            agent_id = metadata["id"]
            version_id = f"AGV-{agent_id}-1.0.0"

            body = _prompt_body(agent_id)
            prompt_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
            cursor.execute(
                "INSERT INTO prompt_artifact (prompt_hash, tenant_id, agent_id, label, body) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (prompt_hash) DO NOTHING",
                (prompt_hash, tenant, agent_id, spec["runtime"]["prompt_ref"], body),
            )
            written += 1

            cursor.execute(
                """
                INSERT INTO agent (
                  agent_id, tenant_id, name, industry_code, domain_code, owner_party_id,
                  machine_identity, on_call, escalation_path, certification
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (agent_id) DO UPDATE SET
                  name = EXCLUDED.name, industry_code = EXCLUDED.industry_code,
                  domain_code = EXCLUDED.domain_code, owner_party_id = EXCLUDED.owner_party_id,
                  on_call = EXCLUDED.on_call, escalation_path = EXCLUDED.escalation_path,
                  certification = EXCLUDED.certification
                """,
                (agent_id, tenant, metadata["name"], metadata["industry"], metadata["domain"],
                 metadata["owner"]["party_id"], machine_party_for(agent_id),
                 metadata["owner"]["on_call"],
                 f"{metadata['owner']['team']} -> domain steward -> architect",
                 metadata["certification"]),
            )
            written += 1

            product_ids = [binding["product_id"] for binding in spec["data_products"]]
            contracts = _contract_versions(cursor, product_ids)

            cursor.execute(
                """
                INSERT INTO agent_version (
                  agent_version_id, tenant_id, agent_id, semver, status, autonomy_level,
                  capability_statement, business_value_block, out_of_scope, personas, analyses,
                  replaces, model_provider, model_id, model_params, prompt_hash,
                  guardrail_config, budget_p95_latency_ms, budget_cost_per_answer_usd
                ) VALUES (%s, %s, %s, '1.0.0', 'draft', %s, %s, %s, %s, %s, %s, %s, %s, %s,
                          %s, %s, %s, %s, %s)
                ON CONFLICT (agent_version_id) DO UPDATE SET
                  capability_statement = EXCLUDED.capability_statement,
                  business_value_block = EXCLUDED.business_value_block,
                  out_of_scope = EXCLUDED.out_of_scope, personas = EXCLUDED.personas,
                  analyses = EXCLUDED.analyses, replaces = EXCLUDED.replaces,
                  model_params = EXCLUDED.model_params, prompt_hash = EXCLUDED.prompt_hash,
                  guardrail_config = EXCLUDED.guardrail_config,
                  budget_p95_latency_ms = EXCLUDED.budget_p95_latency_ms,
                  budget_cost_per_answer_usd = EXCLUDED.budget_cost_per_answer_usd
                """,
                (
                    version_id, tenant, agent_id, metadata["autonomy_level"],
                    spec["capability_statement"].strip(),
                    "; ".join(spec["business_value_block"]["analyses"]),
                    spec["out_of_scope"], spec["business_value_block"]["personas"],
                    spec["business_value_block"]["analyses"],
                    spec["business_value_block"]["replaces"].strip(),
                    spec["runtime"]["model"]["provider"], spec["runtime"]["model"]["id"],
                    json.dumps(
                        {
                            "temperature": spec["runtime"]["model"]["temperature"],
                            "max_tokens": spec["runtime"]["model"]["max_tokens"],
                            "runtime_provider": spec["runtime"]["provider"],
                        },
                        sort_keys=True,
                    ),
                    prompt_hash, json.dumps(spec["guardrails"], sort_keys=True),
                    spec["budgets"]["p95_latency_ms"], spec["budgets"]["cost_per_answer_usd"],
                ),
            )
            written += 1

            cursor.execute(
                "UPDATE agent SET current_version_id = %s WHERE agent_id = %s",
                (version_id, agent_id),
            )

            for binding in spec["data_products"]:
                cursor.execute(
                    """
                    INSERT INTO agent_product_binding (
                      binding_id, tenant_id, agent_version_id, product_id, columns_allowed,
                      access_level, contract_version_pinned
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (agent_version_id, product_id) DO UPDATE SET
                      columns_allowed = EXCLUDED.columns_allowed,
                      access_level = EXCLUDED.access_level,
                      contract_version_pinned = EXCLUDED.contract_version_pinned
                    """,
                    (f"BND-{version_id}-{binding['product_id']}", tenant, version_id,
                     binding["product_id"], binding["columns"], binding["access"],
                     contracts.get(binding["product_id"], "unpinned")),
                )
                written += 1

            for tool in spec["tool_bindings"]:
                cursor.execute(
                    """
                    INSERT INTO agent_tool_binding (
                      tool_binding_id, tenant_id, agent_version_id, tool_name, endpoint_uri,
                      required_scope, cost_class, row_limit
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (agent_version_id, tool_name) DO UPDATE SET
                      endpoint_uri = EXCLUDED.endpoint_uri,
                      required_scope = EXCLUDED.required_scope,
                      cost_class = EXCLUDED.cost_class, row_limit = EXCLUDED.row_limit
                    """,
                    (f"TB-{version_id}-{tool['tool']}", tenant, version_id, tool["tool"],
                     tool.get("endpoint", f"internal://{tool['tool']}"), tool["scope"],
                     tool["cost_class"], tool.get("row_limit")),
                )
                written += 1

            for entry in spec["kpi_coverage"]:
                cursor.execute(
                    """
                    INSERT INTO agent_kpi_coverage (
                      coverage_id, tenant_id, agent_version_id, kpi_id, source_product_id,
                      columns_used, supported_grains, supported_slices, analysis_depth
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (agent_version_id, kpi_id) DO UPDATE SET
                      source_product_id = EXCLUDED.source_product_id,
                      columns_used = EXCLUDED.columns_used,
                      supported_grains = EXCLUDED.supported_grains,
                      supported_slices = EXCLUDED.supported_slices,
                      analysis_depth = EXCLUDED.analysis_depth
                    """,
                    (f"COV-{version_id}-{entry['kpi_id']}", tenant, version_id,
                     entry["kpi_id"], entry["source_product"], entry["columns_used"],
                     entry["grains"], entry["slices"], entry["analysis_depth"]),
                )
                written += 1

            for exchange in spec["demo_exchanges"]:
                cursor.execute(
                    """
                    INSERT INTO demo_exchange (
                      exchange_id, tenant_id, agent_version_id, ordinal, question, kpi_class,
                      analysis_type, expected_shape, data_tier, max_latency_ms,
                      golden_answer_ref, tolerance_pct, validation_state
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'stale')
                    ON CONFLICT (exchange_id) DO UPDATE SET
                      question = EXCLUDED.question, kpi_class = EXCLUDED.kpi_class,
                      analysis_type = EXCLUDED.analysis_type,
                      expected_shape = EXCLUDED.expected_shape,
                      max_latency_ms = EXCLUDED.max_latency_ms,
                      golden_answer_ref = EXCLUDED.golden_answer_ref,
                      tolerance_pct = EXCLUDED.tolerance_pct
                    """,
                    (exchange["id"], tenant, version_id, exchange["ordinal"],
                     exchange["question"], exchange["kpi_class"], exchange["analysis_type"],
                     json.dumps(exchange["expected_shape"], sort_keys=True),
                     exchange["data_tier"], exchange["max_latency_ms"],
                     exchange["golden_answer_ref"], exchange["tolerance_pct"]),
                )
                written += 1

            written += _seed_agent_value_case(cursor, tenant, agent_id, spec["value_case"])

    return written


def _seed_agent_value_case(
    cursor: psycopg.Cursor[Any], tenant: str, agent_id: str, value_case: dict[str, Any]
) -> int:
    cursor.execute(
        "SELECT rv.rubric_version_id FROM rubric_version rv "
        "JOIN rubric r ON r.rubric_id = rv.rubric_id "
        "WHERE r.code = 'value_model' AND r.tenant_id = %s AND rv.superseded_at IS NULL "
        "ORDER BY rv.effective_from DESC LIMIT 1",
        (tenant,),
    )
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError("the value_model rubric must be seeded before agent value cases")
    rubric_version_id = row["rubric_version_id"]

    review = value_case["review"]
    value_case_id = f"VC-agent-{agent_id}"
    cursor.execute(
        """
        INSERT INTO value_case (
          value_case_id, tenant_id, asset_type, asset_id, business_outcome, baseline_method,
          baseline_captured, benefit_model, attribution_confidence, rubric_version_id,
          last_reviewed, reviewer_party_id, review_due
        ) VALUES (%s, %s, 'agent', %s, %s, %s, to_date(%s, 'YYYY-MM'), %s, %s, %s, %s, %s,
                  (to_date(%s, 'YYYY-MM-DD') + interval '6 months')::date)
        ON CONFLICT (asset_type, asset_id) DO UPDATE SET
          benefit_model = EXCLUDED.benefit_model,
          attribution_confidence = EXCLUDED.attribution_confidence,
          rubric_version_id = EXCLUDED.rubric_version_id,
          last_reviewed = EXCLUDED.last_reviewed
        """,
        (value_case_id, tenant, agent_id,
         value_case.get("business_outcome",
                        "Questions this agent answers are answered without an analyst cycle."),
         value_case.get("baseline", {}).get("method", "manual analyst cycle"),
         value_case.get("baseline", {}).get("captured", "2026-01"),
         value_case["benefit_model"], value_case.get("attribution_confidence", "medium"),
         rubric_version_id, review["last_reviewed"], review["reviewer"],
         review["last_reviewed"]),
    )
    written = 1
    for index, assumption in enumerate(value_case["assumptions"]):
        cursor.execute(
            """
            INSERT INTO value_assumption (
              assumption_id, tenant_id, value_case_id, text, numeric_value, unit, sample_size,
              source, dated
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, to_date(%s, 'YYYY-MM-DD'))
            ON CONFLICT (assumption_id) DO UPDATE SET
              numeric_value = EXCLUDED.numeric_value, sample_size = EXCLUDED.sample_size
            """,
            (f"{value_case_id}-{index:02d}", tenant, value_case_id, assumption["text"],
             assumption["value"], assumption.get("unit", "unit"),
             assumption.get("sample_size"), assumption["source"], assumption["dated"]),
        )
        written += 1
    return written
