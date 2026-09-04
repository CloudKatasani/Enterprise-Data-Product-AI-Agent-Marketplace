"""M1.4 — the certified KPI register.

I1 is a partial unique index on ``(tenant_id, lower(kpi_name))`` where status is
draft or certified, so a second active definition of a name is rejected by the
database. The manifest validator catches the same thing earlier, with a
side-by-side diff; this is the backstop that holds even if a row arrives by
another route.

``source_of_record`` points at a data product, and products are seeded from
their own manifests. When a KPI is seeded before its source product exists the
reference is left null and back-filled by the product seeder, so seeding order
is not load-bearing.
"""

from __future__ import annotations

from typing import Any

import psycopg

from scripts.seeders._base import load_directory


def seed(connection: psycopg.Connection[Any], tenant: str) -> int:
    documents = load_directory("kpis")
    written = 0

    with connection.cursor() as cursor:
        cursor.execute("SELECT product_id FROM data_product WHERE tenant_id = %s", (tenant,))
        known_products = {row["product_id"] for row in cursor.fetchall()}

        for document in documents:
            metadata = document["metadata"]
            spec = document["spec"]
            source = spec.get("source_of_record")
            cursor.execute(
                """
                INSERT INTO kpi_definition (
                  kpi_id, tenant_id, kpi_name, status, business_definition, numerator_expr,
                  denominator_expr, expression, grains_supported, slices_supported,
                  inclusions, exclusions, unit, direction, target, domain_code,
                  source_of_record, steward_party_id, forum_approved_at, superseded_by,
                  last_reviewed, review_months
                ) VALUES (
                  %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                  %s, %s, %s, %s
                )
                ON CONFLICT (kpi_id) DO UPDATE SET
                  kpi_name = EXCLUDED.kpi_name,
                  status = EXCLUDED.status,
                  business_definition = EXCLUDED.business_definition,
                  numerator_expr = EXCLUDED.numerator_expr,
                  denominator_expr = EXCLUDED.denominator_expr,
                  expression = EXCLUDED.expression,
                  grains_supported = EXCLUDED.grains_supported,
                  slices_supported = EXCLUDED.slices_supported,
                  inclusions = EXCLUDED.inclusions,
                  exclusions = EXCLUDED.exclusions,
                  unit = EXCLUDED.unit,
                  direction = EXCLUDED.direction,
                  target = EXCLUDED.target,
                  domain_code = EXCLUDED.domain_code,
                  source_of_record = EXCLUDED.source_of_record,
                  steward_party_id = EXCLUDED.steward_party_id,
                  forum_approved_at = EXCLUDED.forum_approved_at,
                  last_reviewed = EXCLUDED.last_reviewed,
                  review_months = EXCLUDED.review_months
                """,
                (
                    metadata["id"], tenant, metadata["name"], metadata["status"],
                    spec["business_definition"], spec.get("numerator_expr"),
                    spec.get("denominator_expr"), spec.get("expression"),
                    spec["grains_supported"], spec["slices_supported"],
                    spec.get("inclusions", []), spec.get("exclusions", []),
                    spec["unit"], spec.get("direction"), spec.get("target"),
                    metadata["domain"],
                    source if source in known_products else None,
                    metadata["steward"], spec.get("forum_approved_at"),
                    metadata.get("superseded_by"),
                    spec["last_reviewed"], spec["review_months"],
                ),
            )
            for term in spec.get("synonyms", []):
                cursor.execute(
                    "INSERT INTO kpi_synonym (synonym_id, tenant_id, kpi_id, term, source) "
                    "VALUES (%s, %s, %s, %s, 'steward') ON CONFLICT (kpi_id, term) DO NOTHING",
                    (f"SYN-{metadata['id']}-{abs(hash(term)) % 100000:05d}", tenant,
                     metadata["id"], term),
                )
            written += 1

    return written


def backfill_source_of_record(connection: psycopg.Connection[Any], tenant: str) -> int:
    """Point KPIs at their source product once products exist."""
    updated = 0
    with connection.cursor() as cursor:
        for document in load_directory("kpis"):
            source = document["spec"].get("source_of_record")
            if source is None:
                continue
            cursor.execute(
                "UPDATE kpi_definition SET source_of_record = %s "
                "WHERE kpi_id = %s AND tenant_id = %s "
                "AND EXISTS (SELECT 1 FROM data_product WHERE product_id = %s)",
                (source, document["metadata"]["id"], tenant, source),
            )
            updated += cursor.rowcount
    return updated
