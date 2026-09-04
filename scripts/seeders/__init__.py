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
    from scripts.seeders import (
        agent_usage,
        agents,
        entitlements,
        kpis,
        policies,
        products,
        rubrics,
        taxonomies,
        tenancy,
    )

    return [
        # Tenancy first: the source-system taxonomy is tenant-scoped, so the
        # tenant row has to exist before any vocabulary that references it.
        ("tenancy", tenancy.seed),
        ("taxonomies", taxonomies.seed),
        ("rubrics", rubrics.seed),
        ("policies", policies.seed),
        ("kpis", kpis.seed),
        ("data products", products.seed),
        ("agents", agents.seed),
        # After agents: a grant is scoped to a binding, so the bindings have to exist.
        ("entitlements", entitlements.seed),
        ("kpi source back-fill", kpis.backfill_source_of_record),
        # After agents and their demo exchanges: usage references both.
        ("agent usage", agent_usage.seed),
        ("search index", _reindex),
    ]


def _reindex(connection: psycopg.Connection[Any], tenant: str) -> int:
    """Rebuild the hybrid search index. Runs last: it reads everything else."""
    from services.common.rubrics import load_current
    from services.search import embedding
    from services.search.index import reindex

    embedding.configure_from_rubric(load_current(connection, embedding.RUBRIC_CODE))
    counts = reindex(connection, tenant)
    return sum(counts.values())


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
