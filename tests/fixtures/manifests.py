"""Minimal-but-valid manifests, used as the baseline that failure tests mutate.

Keeping one valid trio here means each test states exactly one thing: the
mutation it makes and the error it expects.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import yaml

VALID_KPI: dict[str, Any] = {
    "apiVersion": "marketplace/v1",
    "kind": "Kpi",
    "metadata": {
        "id": "KPI-CHURN-001",
        "name": "Churn Rate",
        "domain": "customer",
        "steward": "PTY-0031",
        "status": "certified",
    },
    "spec": {
        "business_definition": (
            "Share of subscribers active at period start who disconnected within the period."
        ),
        "numerator_expr": "count(distinct subscriber_id) filter (where churn_flag)",
        "denominator_expr": "count(distinct subscriber_id)",
        "grains_supported": ["day", "week", "month", "quarter"],
        "slices_supported": ["segment", "region"],
        "unit": "percent",
        "direction": "lower_is_better",
        "source_of_record": "DP-TEL-001",
        "last_reviewed": "2026-07-01",
        "review_months": 12,
        "synonyms": ["attrition rate"],
    },
}

VALID_PRODUCT: dict[str, Any] = {
    "apiVersion": "marketplace/v1",
    "kind": "DataProduct",
    "metadata": {
        "id": "DP-TEL-001",
        "name": "Subscriber Churn & Retention 360",
        "industry": "telecommunications",
        "domain": "customer",
        "archetype": "consumer_aligned",
        "tier": "tier1",
        "owner": {
            "party_id": "PTY-0031",
            "team": "Telecom Customer Domain",
            "escalation": "#dp-telecom",
        },
        "certification": "certified",
    },
    "spec": {
        "purpose": (
            "Unified view of subscriber state, tenure, plan, usage, service events and churn "
            "outcome for retention decisioning."
        ),
        "grain": "one row per subscriber per day",
        "history_months": 36,
        "known_limitations": (
            "Prepaid subscribers are excluded. Service events are joined on a four-hour lag."
        ),
        "upstream_sources": ["SRC-BILLING", "SRC-CRM"],
        "entities": ["subscriber", "account"],
        "certified_kpis": ["KPI-CHURN-001"],
        "columns": [
            {
                "name": "subscriber_id",
                "type": "string",
                "business_name": "Subscriber ID",
                "nullable": False,
                "classification": ["pii", "identifier"],
                "sensitivity": "confidential",
                "description": "Stable pseudonymous identifier for a subscriber line.",
            },
            {
                "name": "churn_flag",
                "type": "boolean",
                "business_name": "Churned in period",
                "nullable": False,
                "classification": [],
                "sensitivity": "internal",
                "description": "True when the subscriber disconnected within the period.",
            },
            {
                "name": "segment",
                "type": "string",
                "business_name": "Segment",
                "nullable": False,
                "classification": [],
                "sensitivity": "internal",
                "description": "Commercial segment assigned by the customer domain.",
            },
        ],
        "contract": {
            "version": "3.2.0",
            "schema_stability": "additive_only",
            "guarantees": {
                "freshness": {"target": "06:00 local", "p95_minutes": 45,
                              "measured": "per_partition"},
                "availability": {"target_pct": 99.5, "window": "monthly"},
                "completeness": {"required_fields_pct": 99.9},
                "accuracy": {"reconciliation_variance_pct": 0.5,
                             "against": "billing_system_of_record"},
            },
            "deprecation_policy": {"notice_days": 90, "minimum_parallel_run_days": 30},
            "support": {"hours": "24x5", "p1_response_minutes": 30,
                        "on_call": "pagerduty://telecom-dp"},
            "classification": {"max_sensitivity": "confidential", "contains_pii": True,
                               "residency": ["US", "EU"]},
            "consumer_obligations": ["No redistribution outside the granted purpose"],
            "breach_process": (
                "Auto-incident and consumer notification within 30 minutes of detection."
            ),
        },
        "quality_rules": [
            {"id": "QR-TEL-001-01", "dimension": "completeness", "column": "subscriber_id",
             "rule": "not_null", "threshold_pct": 100, "severity": "critical"},
            {"id": "QR-TEL-001-02", "dimension": "freshness", "rule": "partition_completion_by",
             "target": "06:00", "tolerance_minutes": 45, "severity": "high"},
            {"id": "QR-TEL-001-03", "dimension": "validity", "column": "segment",
             "rule": "in_reference_set", "threshold_pct": 99.5, "severity": "high"},
        ],
        "endpoints": ["sql", "rest", "mcp"],
        "demo_tier": {
            "synthetic": True,
            "rows_target": 250000,
            "preserve": ["distribution", "seasonality", "referential_integrity", "cardinality"],
        },
        "value_case": {
            "business_outcome": (
                "Retention teams target save offers at subscribers genuinely at risk."
            ),
            "baseline": {"method": "tenure-band targeting", "analyst_hours_month": 120,
                         "captured": "2026-02"},
            "benefit_model": (
                "save_offer_precision_uplift * contribution_margin_per_retained - offer_cost"
            ),
            "assumptions": [
                {"text": "contribution margin per retained subscriber", "value": 41.20,
                 "unit": "usd", "source": "finance FY26 model", "dated": "2026-03-01"}
            ],
            "attribution_confidence": "medium",
            "review": {"last_reviewed": "2026-07-14", "reviewer": "PTY-0031"},
        },
    },
}

VALID_AGENT: dict[str, Any] = {
    "apiVersion": "marketplace/v1",
    "kind": "Agent",
    "metadata": {
        "id": "AG-TEL-001",
        "name": "Churn Sentinel",
        "industry": "telecommunications",
        "domain": "customer",
        "owner": {"party_id": "PTY-0044", "team": "Telecom Analytics",
                  "on_call": "pagerduty://tel-agents"},
        "autonomy_level": "L1",
        "certification": "certified",
    },
    "spec": {
        "capability_statement": (
            "Answers questions about subscriber churn, retention performance and save-offer "
            "targeting, and explains what is driving churn."
        ),
        "business_value_block": {
            "analyses": ["trend_explanation", "driver_ranking"],
            "replaces": (
                "Manual pull-and-pivot cycles by the retention analytics team, two to three "
                "days per churn review."
            ),
            "personas": ["retention_manager"],
        },
        "out_of_scope": [
            "Individual subscriber credit decisions",
            "Pricing approval or plan change execution",
        ],
        "runtime": {
            "provider": "mock",
            "model": {"provider": "anthropic", "id": "test-model", "temperature": 0.0,
                      "max_tokens": 2000},
            "prompt_ref": "prompts/AG-TEL-001/system@v7",
        },
        "data_products": [
            {"product_id": "DP-TEL-001", "columns": ["subscriber_id", "churn_flag", "segment"],
             "access": "read"}
        ],
        "tool_bindings": [
            {"tool": "query_subscriber_churn", "endpoint": "mcp://local/dp/DP-TEL-001",
             "scope": "dp:DP-TEL-001:read", "cost_class": "small", "row_limit": 10000}
        ],
        "kpi_coverage": [
            {"kpi_id": "KPI-CHURN-001", "source_product": "DP-TEL-001",
             "columns_used": ["subscriber_id", "churn_flag", "segment"],
             "grains": ["month", "quarter"], "slices": ["segment"],
             "analysis_depth": "rank_drivers"}
        ],
        "guardrails": {
            "grounding": {"require_citation_on_numerics": True, "on_failure": "return_error"},
            "injection_defence": "v3",
            "output_filters": ["pii_pattern", "credential_pattern"],
            "refusal_policy": (
                "State the boundary, name the covering agent or product, offer a handoff."
            ),
        },
        "budgets": {"p95_latency_ms": 6000, "cost_per_answer_usd": 0.06},
        "demo_exchanges": [
            {
                "id": f"DEMO-AG-TEL-001-{ordinal:02d}",
                "ordinal": ordinal,
                "question": "What is our churn rate this quarter and how does it compare?",
                "kpi_class": "KPI-CHURN-001",
                "analysis_type": "period_comparison",
                "expected_shape": {
                    "headline": "current rate, delta against the prior period, and the "
                                "concentration driving it",
                    "visual": "line_with_delta_callout",
                    "table_columns": ["period", "churn_rate"],
                    "must_cite": ["DP-TEL-001", "KPI-CHURN-001"],
                },
                "data_tier": "demo",
                "max_latency_ms": 6000,
                "golden_answer_ref": f"seed/golden/AG-TEL-001/q{ordinal}.json",
                "tolerance_pct": 2.0,
            }
            for ordinal in range(1, 6)
        ],
        "evaluation": {
            "suites": ["golden_accuracy", "groundedness", "boundary_refusal", "entitlement"],
            "pass_threshold_pct": 92,
            "cases_ref": "seed/eval/AG-TEL-001/",
        },
        "value_case": {
            "benefit_model": (
                "answered_questions * acceptance_rate * avg_manual_minutes / 60 * rate"
            ),
            "assumptions": [
                {"text": "avg manual minutes per churn driver question", "value": 55,
                 "unit": "minutes", "sample_size": 34, "source": "analyst time study",
                 "dated": "2026-06-01"}
            ],
        },
    },
}


def write_tree(root: Path, *, products=None, agents=None, kpis=None) -> Path:
    """Write a manifests tree and the golden answers the agents reference."""
    for name in ("products", "agents", "kpis", "taxonomies", "rubrics"):
        (root / name).mkdir(parents=True, exist_ok=True)

    for document in products if products is not None else [VALID_PRODUCT]:
        path = root / "products" / f"{document['metadata']['id']}.yaml"
        path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    for index, document in enumerate(kpis if kpis is not None else [VALID_KPI]):
        name = f"{document['metadata']['id']}-{index}" if kpis else document["metadata"]["id"]
        (root / "kpis" / f"{name}.yaml").write_text(
            yaml.safe_dump(document, sort_keys=False), encoding="utf-8"
        )

    for document in agents if agents is not None else [VALID_AGENT]:
        path = root / "agents" / f"{document['metadata']['id']}.yaml"
        path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    return root


def write_golden_answers(repo_root: Path, agent_id: str = "AG-TEL-001", count: int = 5) -> None:
    directory = repo_root / "seed" / "golden" / agent_id
    directory.mkdir(parents=True, exist_ok=True)
    for ordinal in range(1, count + 1):
        (directory / f"q{ordinal}.json").write_text(json.dumps({"headline": "seed"}), "utf-8")


def clone(document: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(document)
