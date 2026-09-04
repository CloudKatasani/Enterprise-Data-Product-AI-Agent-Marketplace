"""Seeder registry.

Order matters and lives here rather than in each seeder: reference vocabulary
before anything that references it, rubrics before anything that scores against
one, and the KPI back-fill last because it closes the loop between the register
and the products that are its source of record.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any

import psycopg

from services.common.db import connect, tenant_id

Seeder = Callable[["psycopg.Connection[Any]", str], int]


def _seeders() -> list[tuple[str, Seeder]]:
    from scripts.seeders import kpis, products, rubrics, taxonomies, tenancy

    return [
        ("taxonomies", taxonomies.seed),
        ("tenancy", tenancy.seed),
        ("rubrics", rubrics.seed),
        ("kpis", kpis.seed),
        ("data products", products.seed),
        ("kpi source back-fill", kpis.backfill_source_of_record),
    ]


def run_all() -> int:
    tenant = tenant_id()
    try:
        with connect(tenant) as connection:
            for name, seeder in _seeders():
                count = seeder(connection, tenant)
                print(f"seed: {name} — {count} row(s)")
    except psycopg.Error as error:
        print(f"seed: failed — {error}", file=sys.stderr)
        return 1
    print(f"seed: complete for tenant {tenant}")
    return 0
