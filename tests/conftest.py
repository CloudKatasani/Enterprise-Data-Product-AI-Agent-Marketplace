"""Shared fixtures.

Database-backed tests run against a real Postgres, never a mock: the invariants
in BUILD.md section 2 are database constraints, and a mock cannot prove a
constraint exists. When ``DATABASE_URL`` is unset the suite skips (a developer
without a data plane still gets the pure-logic tests); when it is set the suite
fails rather than skips if the database is unreachable, so CI cannot go green on
a database that never came up.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from services.common.config import load_dotenv

load_dotenv()

TEST_TENANT = "TEN-TEST"


def _database_url() -> str | None:
    url = os.environ.get("DATABASE_URL")
    return url if url and url.strip() else None


@pytest.fixture(scope="session")
def database_url() -> str:
    url = _database_url()
    if url is None:
        pytest.skip("DATABASE_URL is not set; database-backed tests need a data plane")
    return url


@pytest.fixture()
def db(database_url: str) -> Iterator[object]:
    """A transaction that is always rolled back, so tests cannot leak into each other."""
    import psycopg
    from psycopg.rows import dict_row

    # dict rows, exactly as services.common.db.connect opens them, so a test and
    # the code it exercises see the same shape.
    connection = psycopg.connect(database_url, row_factory=dict_row)
    try:
        connection.autocommit = False
        with connection.cursor() as cursor:
            # Mirror the production connection: every session carries the tenant
            # the row-level policies evaluate against.
            cursor.execute(
                "SELECT set_config('app.tenant_id', %s, false)",
                (os.environ.get("TENANT_ID", TEST_TENANT),),
            )
        yield connection
    finally:
        connection.rollback()
        connection.close()


@pytest.fixture()
def seeded_tenant(db) -> str:
    with db.cursor() as cursor:
        cursor.execute(
            "INSERT INTO tenant (tenant_id, name, deployment_mode, residency_regions) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (tenant_id) DO NOTHING",
            (TEST_TENANT, "Test tenant", "multi_tenant", ["US"]),
        )
    return TEST_TENANT
