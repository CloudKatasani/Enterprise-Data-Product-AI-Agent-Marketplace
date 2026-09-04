"""M6.2 — the publish gate, as executable tests.

BUILD.md section 15.3 lists eight blocking checks. Each one gets a test that
constructs the shortfall and asserts the gate names it, plus a test that the
fourteen seeded agents clear the gate as shipped.

Every failure case is built by mutating a real seeded version inside a
transaction that is rolled back, rather than by assembling a fixture. A gate
that passes a hand-built object and fails on real data has proved nothing.
"""

from __future__ import annotations

import json

import pytest

from services.agents import publish_gate
from services.common.rubrics import load_current


@pytest.fixture()
def rubric(db):
    return load_current(db, "agent_evaluation")


@pytest.fixture()
def version_id(db) -> str:
    with db.cursor() as cursor:
        cursor.execute(
            "SELECT current_version_id FROM agent ORDER BY agent_id LIMIT 1"
        )
        row = cursor.fetchone()
    if row is None:
        pytest.skip("no seeded agents")
    return row["current_version_id"]


def _check(result: publish_gate.GateResult, code: str) -> publish_gate.Check:
    for check in result.checks:
        if check.code == code:
            return check
    raise AssertionError(f"the gate ran no check named {code}")


def test_every_seeded_agent_clears_the_gate(db, rubric) -> None:
    """The estate ships publishable. A seed that cannot publish is a broken seed."""
    with db.cursor() as cursor:
        cursor.execute("SELECT current_version_id FROM agent ORDER BY agent_id")
        versions = [row["current_version_id"] for row in cursor.fetchall()]

    blocked = {}
    for version in versions:
        result = publish_gate.evaluate(db, version, rubric)
        if not result.publishable:
            blocked[version] = result.shortfalls
    assert not blocked, f"seeded agents that cannot publish: {blocked}"


def test_the_gate_runs_every_check_section_15_3_lists(db, rubric, version_id) -> None:
    result = publish_gate.evaluate(db, version_id, rubric)
    assert {check.code for check in result.checks} == set(publish_gate.ORDER)
    assert [check.code for check in result.checks] == list(publish_gate.ORDER), (
        "checks are rendered on the agent page in this order"
    )


def test_an_agent_with_four_exchanges_is_rejected_naming_the_shortfall(
    db, rubric, version_id
) -> None:
    """The M6 acceptance criterion, verbatim.

    Five exchanges are required. Deleting one must not merely fail: the message
    has to say how many there are, how many are needed, and how many to author.
    """
    with db.cursor() as cursor:
        cursor.execute(
            "DELETE FROM demo_exchange WHERE exchange_id = ("
            "  SELECT exchange_id FROM demo_exchange WHERE agent_version_id = %s "
            "  ORDER BY ordinal DESC LIMIT 1)",
            (version_id,),
        )
        cursor.execute(
            "SELECT count(*) AS n FROM demo_exchange WHERE agent_version_id = %s",
            (version_id,),
        )
        remaining = cursor.fetchone()["n"]
    assert remaining == 4

    result = publish_gate.evaluate(db, version_id, rubric)
    assert not result.publishable

    check = _check(result, publish_gate.CHECK_EXCHANGES)
    assert not check.passed
    assert "4 curated demo exchange" in check.detail
    assert "requires 5" in check.detail
    assert "Author 1 more" in check.detail
    assert "4 curated demo exchange" in result.message()


def test_a_stale_exchange_blocks_publication(db, rubric, version_id) -> None:
    max_age = int(rubric.number(publish_gate.MAX_AGE_DAYS_PATH))
    with db.cursor() as cursor:
        cursor.execute(
            "UPDATE demo_exchange SET last_validated = now() - %s::interval "
            "WHERE agent_version_id = %s AND ordinal = 1",
            (f"{max_age + 1} days", version_id),
        )
    check = _check(publish_gate.evaluate(db, version_id, rubric), publish_gate.CHECK_EXCHANGES)
    assert not check.passed
    assert f"not validated in the last {max_age} day" in check.detail


def test_a_failing_exchange_blocks_publication(db, rubric, version_id) -> None:
    with db.cursor() as cursor:
        cursor.execute(
            "UPDATE demo_exchange SET validation_state = 'failing' "
            "WHERE agent_version_id = %s AND ordinal = 1",
            (version_id,),
        )
    check = _check(publish_gate.evaluate(db, version_id, rubric), publish_gate.CHECK_EXCHANGES)
    assert not check.passed
    assert "not passing against its golden answer" in check.detail


@pytest.mark.parametrize("statement", ["Too short.", "x" * 400])
def test_the_capability_statement_band_is_a_database_constraint(
    db, version_id, statement
) -> None:
    """I3 is enforced in the schema, so a bad statement never reaches the gate.

    Worth pinning: the gate's own length check exists for paths that have not
    hit the database yet, and this test is what says the stored data cannot get
    there in the first place.
    """
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation), db.cursor() as cursor:
        cursor.execute(
            "UPDATE agent_version SET capability_statement = %s WHERE agent_version_id = %s",
            (statement, version_id),
        )


@pytest.mark.parametrize("statement", ["Too short.", "x" * 400])
def test_the_gate_names_the_band_a_statement_missed(db, rubric, statement) -> None:
    version = {
        "capability_statement": statement,
        "business_value_block": "present",
        "out_of_scope": ["something"],
    }
    check = publish_gate.check_statement(version, rubric)
    assert not check.passed
    assert "outside" in check.detail
    assert str(len(statement)) in check.detail, "the message says how long it actually is"
    minimum = int(rubric.number(publish_gate.STATEMENT_MIN_PATH))
    maximum = int(rubric.number(publish_gate.STATEMENT_MAX_PATH))
    assert f"{minimum}-{maximum}" in check.detail, "and what the band is"


def test_an_empty_boundary_blocks_publication(db, rubric, version_id) -> None:
    with db.cursor() as cursor:
        cursor.execute(
            "UPDATE agent_version SET out_of_scope = '{}' WHERE agent_version_id = %s",
            (version_id,),
        )
    check = _check(publish_gate.evaluate(db, version_id, rubric), publish_gate.CHECK_STATEMENT)
    assert not check.passed
    assert "out-of-scope" in check.detail


def test_coverage_cannot_cite_an_unregistered_kpi(db, version_id) -> None:
    """A foreign key, not a gate check, is what makes this impossible."""
    import psycopg

    with pytest.raises(psycopg.errors.ForeignKeyViolation), db.cursor() as cursor:
        cursor.execute(
            "UPDATE agent_kpi_coverage SET kpi_id = 'KPI-DOES-NOT-EXIST' "
            "WHERE coverage_id = (SELECT coverage_id FROM agent_kpi_coverage "
            "                     WHERE agent_version_id = %s ORDER BY kpi_id LIMIT 1)",
            (version_id,),
        )


def test_an_empty_coverage_map_blocks_publication(db, rubric, version_id) -> None:
    with db.cursor() as cursor:
        cursor.execute(
            "DELETE FROM agent_kpi_coverage WHERE agent_version_id = %s", (version_id,)
        )
    check = _check(publish_gate.evaluate(db, version_id, rubric), publish_gate.CHECK_COVERAGE)
    assert not check.passed
    assert "coverage map is empty" in check.detail


def test_coverage_reading_outside_the_binding_blocks_publication(
    db, rubric, version_id
) -> None:
    """A coverage row may not use a column the product binding does not grant."""
    with db.cursor() as cursor:
        cursor.execute(
            "SELECT coverage_id, columns_used FROM agent_kpi_coverage "
            "WHERE agent_version_id = %s ORDER BY kpi_id LIMIT 1",
            (version_id,),
        )
        coverage = cursor.fetchone()
        cursor.execute(
            "UPDATE agent_kpi_coverage SET columns_used = %s WHERE coverage_id = %s",
            ([*coverage["columns_used"], "a_column_nobody_granted"], coverage["coverage_id"]),
        )
    check = _check(publish_gate.evaluate(db, version_id, rubric), publish_gate.CHECK_COVERAGE)
    assert not check.passed
    assert "a_column_nobody_granted" in check.detail


def test_a_binding_beyond_the_approved_scope_blocks_publication(
    db, rubric, version_id
) -> None:
    """I12 at the gate: the agent may not be bound to more than it was granted."""
    with db.cursor() as cursor:
        cursor.execute(
            "SELECT a.machine_identity FROM agent a JOIN agent_version v "
            "ON v.agent_id = a.agent_id WHERE v.agent_version_id = %s",
            (version_id,),
        )
        machine = cursor.fetchone()["machine_identity"]
        cursor.execute(
            "UPDATE grant_scope SET expression = 'nothing_at_all' WHERE grant_id IN ("
            "  SELECT grant_id FROM entitlement_grant WHERE principal_id = %s)",
            (machine,),
        )
    check = _check(publish_gate.evaluate(db, version_id, rubric), publish_gate.CHECK_ENTITLEMENT)
    assert not check.passed
    assert "approved scope does not cover" in check.detail


def test_a_missing_evaluation_run_blocks_publication(db, rubric, version_id) -> None:
    with db.cursor() as cursor:
        cursor.execute("UPDATE agent_version SET eval_run_id = NULL")
        cursor.execute("DELETE FROM evaluation_run WHERE agent_version_ref = %s", (version_id,))
    result = publish_gate.evaluate(db, version_id, rubric)
    for code in (
        publish_gate.CHECK_EVALUATION,
        publish_gate.CHECK_GROUNDEDNESS,
        publish_gate.CHECK_COMPOSITIONAL,
    ):
        check = _check(result, code)
        assert not check.passed, f"{code} passed without an evaluation run"
        assert "no evaluation run" in check.detail


def test_one_uncited_numeric_claim_blocks_publication(db, rubric, version_id) -> None:
    """I11: groundedness is 100% or the version does not publish."""
    with db.cursor() as cursor:
        cursor.execute(
            "SELECT eval_run_id, suite_results FROM evaluation_run "
            "WHERE agent_version_ref = %s ORDER BY finished_at DESC LIMIT 1",
            (version_id,),
        )
        run = cursor.fetchone()
        if run is None:
            pytest.skip("no evaluation run recorded; run scripts/evaluate.py first")
        suites = run["suite_results"]
        for entry in suites:
            if entry["suite"] == "groundedness":
                entry["passed"] = False
                entry["failures"] = [
                    {"case_id": "GRD-1", "detail": "prose asserts 42 with no matching claim"}
                ]
        cursor.execute(
            "UPDATE evaluation_run SET suite_results = %s WHERE eval_run_id = %s",
            (json.dumps(suites), run["eval_run_id"]),
        )
    check = _check(publish_gate.evaluate(db, version_id, rubric), publish_gate.CHECK_GROUNDEDNESS)
    assert not check.passed
    assert "uncited numeric claim" in check.detail


def test_a_missing_on_call_rotation_blocks_publication(db, rubric, version_id) -> None:
    with db.cursor() as cursor:
        cursor.execute(
            "UPDATE agent SET on_call = '' WHERE agent_id = ("
            "  SELECT agent_id FROM agent_version WHERE agent_version_id = %s)",
            (version_id,),
        )
    check = _check(publish_gate.evaluate(db, version_id, rubric), publish_gate.CHECK_OWNERSHIP)
    assert not check.passed
    assert "on-call" in check.detail


def test_a_missing_value_case_blocks_publication(db, rubric, version_id) -> None:
    with db.cursor() as cursor:
        cursor.execute(
            "SELECT agent_id FROM agent_version WHERE agent_version_id = %s", (version_id,)
        )
        agent_id = cursor.fetchone()["agent_id"]
        # Assumptions and realised measurements both hang off the case. Since
        # M10 the value snapshot writes measurements, so a case that has ever
        # been measured cannot be removed without them.
        for child in ("value_assumption", "value_measurement"):
            cursor.execute(
                f"DELETE FROM {child} WHERE value_case_id IN ("  # noqa: S608 - fixed set
                "  SELECT value_case_id FROM value_case WHERE asset_type = 'agent' "
                "  AND asset_id = %s)",
                (agent_id,),
            )
        cursor.execute(
            "DELETE FROM value_case WHERE asset_type = 'agent' AND asset_id = %s", (agent_id,)
        )
    check = _check(publish_gate.evaluate(db, version_id, rubric), publish_gate.CHECK_OWNERSHIP)
    assert not check.passed
    assert "no value case" in check.detail


def test_the_gate_records_which_rubric_version_judged_the_version(
    db, rubric, version_id
) -> None:
    """A gate result that cannot say what it was judged against cannot be replayed."""
    result = publish_gate.evaluate(db, version_id, rubric)
    assert result.rubric_version_id == rubric.rubric_version_id
    assert result.document()["rubric_version_id"] == rubric.rubric_version_id


def test_an_unknown_version_is_an_error_not_a_pass(db, rubric) -> None:
    with pytest.raises(publish_gate.GateUnavailableError):
        publish_gate.evaluate(db, "AGV-DOES-NOT-EXIST", rubric)
