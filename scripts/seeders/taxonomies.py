"""M1.4 — taxonomies into the reference tables.

Reference vocabulary is shared across tenants by design: it is what every tenant
resolves its manifests against. Seeding is an upsert on ``code``, so a label or
description can be corrected without orphaning the rows that point at it.
"""

from __future__ import annotations

from typing import Any

import psycopg

from scripts.seeders._base import load_directory

TABLE_FOR_TAXONOMY = {
    "industry": "industry",
    "domain": "business_domain",
    "archetype": "product_archetype",
    "purpose": "purpose_category",
    "sensitivity": "sensitivity_tier",
    "source_system": "source_system",
}


def _row_for(taxonomy: str, entry: dict[str, Any]) -> dict[str, Any]:
    common = {
        "code": entry["code"],
        "label": entry["label"],
        "description": entry["description"],
    }
    if taxonomy == "sensitivity":
        return {
            **common,
            "rank_order": entry["rank_order"],
            "requires_purpose": entry["requires_purpose"],
        }
    if taxonomy == "source_system":
        # Source systems are tenant-scoped: which systems feed a marketplace is
        # a property of the deployment, not shared vocabulary.
        return {
            "source_id": entry["code"],
            "name": entry["label"],
            "platform": entry["platform"],
            "owner_team": entry["owner_team"],
            "criticality": entry["criticality"],
            "description": entry["description"],
        }
    if taxonomy == "purpose":
        return {
            **common,
            "requires_free_text": entry["requires_free_text"],
            "sort_order": entry["rank_order"],
        }
    return {**common, "sort_order": entry["rank_order"]}


def seed(connection: psycopg.Connection[Any], tenant: str) -> int:
    written = 0
    for document in load_directory("taxonomies"):
        taxonomy = document["taxonomy"]
        table = TABLE_FOR_TAXONOMY[taxonomy]
        key = "source_id" if taxonomy == "source_system" else "code"
        for entry in document["entries"]:
            row = _row_for(taxonomy, entry)
            if taxonomy == "source_system":
                row["tenant_id"] = tenant
            updates = {name: value for name, value in row.items() if name != key}
            assignments = ", ".join(f"{name} = EXCLUDED.{name}" for name in updates)
            placeholders = ", ".join(["%s"] * len(row))
            with connection.cursor() as cursor:
                cursor.execute(
                    f"INSERT INTO {table} ({', '.join(row)}) VALUES ({placeholders}) "
                    f"ON CONFLICT ({key}) DO UPDATE SET {assignments}",
                    tuple(row.values()),
                )
            written += 1
    return written
