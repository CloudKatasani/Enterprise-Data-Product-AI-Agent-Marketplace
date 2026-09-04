"""M12.1 — learning paths, modules and the glossary cards that link to them.

Module bodies live in the manifests rather than a content store, so what the
estate teaches arrives in a reviewable diff like everything else. What is seeded
here is the index — the path, its modules and their order — plus a ``body_ref``
pointing back at the manifest the body came from. The academy service resolves
the ref at read time, which means there is exactly one copy of every sentence
and no step that can leave the database and the manifest disagreeing.

Glossary terms are seeded from the KPI registry. Every certified KPI already has
a business definition written by its steward; copying it into a second place to
be edited separately is how a glossary starts contradicting the registry it was
built from.
"""

from __future__ import annotations

from typing import Any

import psycopg

from scripts.seeders._base import load_directory_with_paths, upsert

STATE_ENROLLED = "enrolled"
# The canonical model allows draft, approved and deprecated. A card indexed
# from a certified KPI is approved by construction: its definition has already
# been through the registry's own forum.
GLOSSARY_APPROVED = "approved"


def seed(connection: psycopg.Connection[Any], tenant: str) -> int:
    written = 0

    for path, document in load_directory_with_paths("academy"):
        spec = document["spec"]
        module_ids: list[str] = []
        relative = path.relative_to(path.parents[2])

        for order, module in enumerate(spec["modules"], start=1):
            upsert(
                connection,
                "academy_module",
                {"module_id": module["module_id"]},
                {
                    "tenant_id": tenant,
                    "title": module["title"],
                    "summary": module["summary"],
                    # The manifest and the module within it. Resolved at read
                    # time so the body has one home.
                    "body_ref": f"{relative}#{module['module_id']}",
                    "estimated_minutes": module["estimated_minutes"],
                    "asset_type": module.get("asset_type"),
                    "asset_id": module.get("asset_id"),
                    "sandbox_tier": module.get("sandbox_tier"),
                    "sort_order": order,
                },
            )
            module_ids.append(module["module_id"])
            written += 1

        upsert(
            connection,
            "learning_path",
            {"path_id": spec["path_id"]},
            {
                "tenant_id": tenant,
                "title": spec["title"],
                "persona": spec["persona"],
                "summary": spec["summary"],
                "module_ids": module_ids,
                "certification_code": spec["certification_code"],
            },
        )
        written += 1

    written += _glossary(connection, tenant)
    return written


def _glossary(connection: psycopg.Connection[Any], tenant: str) -> int:
    """One card per certified KPI, from the definition its steward wrote.

    Section 20.2 wants a plain-language card reachable wherever a term appears.
    The plain language already exists in the registry as the business
    definition, so this indexes it rather than restating it — a glossary that
    paraphrases the registry is a second definition, which is precisely what the
    registry exists to prevent.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT kpi_id, kpi_name, business_definition, domain_code, steward_party_id "
            "FROM kpi_definition WHERE status = 'certified' ORDER BY kpi_id"
        )
        rows = cursor.fetchall()

    for row in rows:
        upsert(
            connection,
            "glossary_term",
            {"term_id": f"TRM-{row['kpi_id']}"},
            {
                "tenant_id": tenant,
                "term": row["kpi_name"],
                "definition": row["business_definition"],
                "domain_code": row["domain_code"],
                "steward_party_id": row["steward_party_id"],
                "related_kpi_ids": [row["kpi_id"]],
                "status": GLOSSARY_APPROVED,
            },
        )
    return len(rows)
