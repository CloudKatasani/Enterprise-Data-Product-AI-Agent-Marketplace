"""gen:agentcard — an interop descriptor per agent.

The card is what another system reads to decide whether this agent can answer a
question, and what it must supply to ask. It carries the coverage map at KPI
grain and slice level, the declared boundary, the guardrail posture and the
budget — everything a caller needs to route correctly without reading the
manifest or trusting a prose description.

Section 15.3: an agent version is an immutable bundle. The card pins the model,
the prompt hash reference, the tool bindings and the contract versions it reads,
so two cards with the same bundle hash describe the same behaviour.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.generators._manifests import digest_of, load
from scripts.generators.header import content_digest, write_generated

VERSION = "1.0.0"


def _coverage(agent: dict[str, Any], kpis: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rendered = []
    for entry in agent["spec"]["kpi_coverage"]:
        kpi = kpis.get(entry["kpi_id"], {})
        metadata = kpi.get("metadata", {})
        rendered.append(
            {
                "kpi_id": entry["kpi_id"],
                "kpi_name": metadata.get("name"),
                "unit": kpi.get("spec", {}).get("unit"),
                "source_product": entry["source_product"],
                "grains": entry["grains"],
                "slices": entry["slices"],
                "analysis_depth": entry["analysis_depth"],
                "eval_accuracy_pct": entry.get("eval_accuracy"),
                "eval_sample_size": entry.get("eval_sample_size"),
            }
        )
    return rendered


def _bundle(agent: dict[str, Any], products: dict[str, dict[str, Any]]) -> dict[str, Any]:
    spec = agent["spec"]
    return {
        "model_provider": spec["runtime"]["model"]["provider"],
        "model_id": spec["runtime"]["model"]["id"],
        "model_params": {
            "temperature": spec["runtime"]["model"]["temperature"],
            "max_tokens": spec["runtime"]["model"]["max_tokens"],
        },
        "prompt_ref": spec["runtime"]["prompt_ref"],
        "tool_bindings": [
            {
                "tool": binding["tool"],
                "scope": binding["scope"],
                "cost_class": binding["cost_class"],
                "row_limit": binding.get("row_limit"),
            }
            for binding in spec["tool_bindings"]
        ],
        "upstream_contract_versions": {
            binding["product_id"]: products.get(binding["product_id"], {})
            .get("spec", {})
            .get("contract", {})
            .get("version")
            for binding in spec["data_products"]
        },
        "guardrails": spec["guardrails"],
    }


def _card(
    agent: dict[str, Any],
    kpis: dict[str, dict[str, Any]],
    products: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    metadata = agent["metadata"]
    spec = agent["spec"]
    bundle = _bundle(agent, products)
    return {
        "schema": "marketplace/agentcard/v1",
        "agent": {
            "id": metadata["id"],
            "name": metadata["name"],
            "industry": metadata["industry"],
            "domain": metadata["domain"],
            "autonomy_level": metadata["autonomy_level"],
            "certification": metadata["certification"],
            "owner": metadata["owner"],
        },
        "capability_statement": spec["capability_statement"],
        "business_value": spec["business_value_block"],
        "out_of_scope": spec["out_of_scope"],
        "coverage": _coverage(agent, kpis),
        "reads": [
            {
                "product_id": binding["product_id"],
                "columns": binding["columns"],
                "access": binding["access"],
                "required_scope": f"dp:{binding['product_id']}:read",
            }
            for binding in spec["data_products"]
        ],
        "invocation": {
            "endpoint": f"/api/v1/agents/{metadata['id']}/ask",
            "required_scope": f"agent:{metadata['id']}:invoke",
            "purpose_required": True,
            "effective_access": "intersection(agent scope, user entitlement)",
            "refusal": {
                "out_of_scope_status": 422,
                "ungrounded_status": 424,
                "entitlement_missing_status": 403,
            },
        },
        "budgets": spec["budgets"],
        "evaluation": {
            "suites": spec["evaluation"]["suites"],
            "pass_threshold_pct": spec["evaluation"]["pass_threshold_pct"],
        },
        "demo": {
            "exchange_count": len(spec["demo_exchanges"]),
            "questions": [exchange["question"] for exchange in spec["demo_exchanges"]],
        },
        "bundle": bundle,
        "bundle_hash": content_digest(json.dumps(bundle, sort_keys=True)),
    }


def generate(output_root: Path) -> list[Path]:
    agents = load("agents")
    if not agents:
        return []
    kpis = {document["metadata"]["id"]: document for _, document in load("kpis")}
    products = {document["metadata"]["id"]: document for _, document in load("products")}
    digest = digest_of([path for path, _ in agents])

    written: list[Path] = []
    for path, agent in agents:
        agent_id = agent["metadata"]["id"]
        source = f"manifests/agents/{path.name}"
        card = _card(agent, kpis, products)
        target = output_root / "agentcards" / f"{agent_id}.json"
        body = json.dumps(
            {
                "_generated": {
                    "from": source,
                    "by": "scripts/gen.py",
                    "generator_version": VERSION,
                    "manifest_hash": digest,
                    "warning": "DO NOT EDIT",
                },
                **card,
            },
            indent=2,
        )
        write_generated(
            target, body, source=source, version=VERSION, digest=digest, json_style=True
        )
        written.append(target)
    return written
