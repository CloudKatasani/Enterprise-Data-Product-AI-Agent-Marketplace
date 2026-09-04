"""M3.6 — the kill test. I8: connectors cannot write to any customer platform.

The proof has two independent layers, and the test exercises both:

1. **In-process guard.** Every statement is checked before it reaches a driver.
   A connector whose code tried to write would fail here even against a platform
   whose role grants were wrong.
2. **Platform refusal.** The statement is then submitted straight to the driver,
   bypassing the guard, and the platform itself rejects it. Against the local
   stand-in that is a read-only Postgres session; against a real account it is
   the MKT_READONLY role.

A test that only proved the first layer would be checking that we wrote an
``if`` statement. Both layers together are what makes the claim worth making.
"""

from __future__ import annotations

import os

import psycopg
import pytest

from connectors.base import (
    MUTATING_VERBS,
    READ_VERBS,
    ReadOnlyViolation,
    assert_read_only,
    load_permission_manifest,
)
from connectors.snowflake import queries
from connectors.snowflake.session import RefusingSession, SandboxSession
from services.common.config import load_dotenv

load_dotenv()

# One statement per way a connector could change a customer's platform.
WRITE_ATTEMPTS = [
    "INSERT INTO sf_tables VALUES ('x')",
    "UPDATE sf_tables SET table_name = 'x'",
    "DELETE FROM sf_tables",
    "MERGE INTO sf_tables USING sf_columns ON true WHEN MATCHED THEN DELETE",
    "TRUNCATE TABLE sf_tables",
    "CREATE TABLE evil (id INT)",
    "DROP TABLE sf_tables",
    "ALTER TABLE sf_tables ADD COLUMN evil TEXT",
    "GRANT SELECT ON sf_tables TO PUBLIC",
    "REVOKE SELECT ON sf_tables FROM PUBLIC",
    "COPY INTO @stage FROM sf_tables",
    "PUT file:///tmp/x @stage",
    "CALL system$do_something()",
    "COMMENT ON TABLE sf_tables IS 'x'",
    "USE ROLE ACCOUNTADMIN",
]


@pytest.fixture(scope="module")
def sandbox() -> SandboxSession:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        pytest.skip("DATABASE_URL is not set; the kill test needs a platform to attack")
    session = SandboxSession(
        database_url=database_url, schema=os.environ["DEMO_TIER_SCHEMA"].lower()
    )
    yield session
    session.close()


@pytest.mark.parametrize("statement", WRITE_ATTEMPTS)
def test_the_guard_refuses_every_write_attempt(statement: str) -> None:
    with pytest.raises(ReadOnlyViolation) as excinfo:
        assert_read_only(statement)

    assert "read-only" in str(excinfo.value) or "permitted" in str(excinfo.value)


@pytest.mark.parametrize("statement", WRITE_ATTEMPTS)
def test_the_session_refuses_every_write_attempt(sandbox: SandboxSession, statement: str) -> None:
    with pytest.raises(ReadOnlyViolation):
        sandbox.query(statement)


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO sf_tables VALUES ('x','y','z','t',1,'c',now(),now())",
        "UPDATE sf_tables SET table_name = 'x'",
        "DELETE FROM sf_tables",
        "CREATE TABLE evil (id INT)",
        "DROP TABLE IF EXISTS sf_columns",
    ],
)
def test_the_platform_itself_refuses_a_write_that_bypasses_the_guard(
    sandbox: SandboxSession, statement: str
) -> None:
    """The second layer: even with the guard removed, the platform says no."""
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        sandbox.unguarded_execute(statement)
    sandbox._connection.rollback()  # noqa: SLF001 — the test drove the failure


def test_a_batch_hiding_a_write_behind_a_read_is_refused() -> None:
    with pytest.raises(ReadOnlyViolation) as excinfo:
        assert_read_only("SELECT 1; DROP TABLE sf_tables")

    assert "one statement at a time" in str(excinfo.value)


def test_a_write_hidden_behind_a_comment_is_refused() -> None:
    with pytest.raises(ReadOnlyViolation):
        assert_read_only("-- SELECT 1\nDELETE FROM sf_tables")

    with pytest.raises(ReadOnlyViolation):
        assert_read_only("/* SELECT 1 */ UPDATE sf_tables SET x = 1")


def test_every_statement_the_connector_can_issue_is_a_read() -> None:
    """The connector's whole read surface, checked in one place."""
    for statement in queries.ALL_STATEMENTS:
        assert_read_only(statement)


def test_read_and_mutating_verbs_do_not_overlap() -> None:
    assert not (READ_VERBS & MUTATING_VERBS)


def test_the_published_permission_manifest_requests_no_write_privilege() -> None:
    manifest = load_permission_manifest("snowflake")

    assert manifest.role == "MKT_READONLY"
    assert manifest.write_privileges == ()
    for privilege in manifest.privileges:
        assert privilege.reason.strip(), privilege.privilege


def test_the_permission_manifest_names_the_privileges_it_refuses() -> None:
    manifest = load_permission_manifest("snowflake")
    refused = {entry.upper() for entry in manifest.refuses}

    for verb in ("INSERT", "UPDATE", "DELETE", "MERGE", "CREATE", "DROP", "ALTER", "GRANT"):
        assert verb in refused

    granted = {privilege.privilege.upper() for privilege in manifest.privileges}
    assert not (granted & refused)


def test_a_refusing_session_surfaces_the_refusal_rather_than_returning_nothing() -> None:
    with pytest.raises(ReadOnlyViolation):
        RefusingSession().query("SELECT 1")
