"""M6.3 — the runtime adapters, the registry, and what they refuse.

The claim these tests defend is the one the milestone's acceptance criterion
makes: no mocked answers exist. So the analytic runtime is exercised against the
real demo tier and asserted to change its answer when the data changes, and the
registry is asserted to refuse rather than substitute.
"""

from __future__ import annotations

import os
from decimal import Decimal

import pytest

from services.agent_runtime import analytic, registry
from services.agent_runtime.base import (
    AskRequest,
    EntitlementShortfall,
    OutOfScope,
    RuntimeUnavailable,
)
from services.common.rubrics import load_current

TENANT = os.environ.get("TENANT_ID", "TEN-DEMO")
BROAD = "PTY-0061"
NARROW = "PTY-0063"


@pytest.fixture()
def runtime(db):
    return registry.build(db)


@pytest.fixture()
def exchange(db):
    with db.cursor() as cursor:
        cursor.execute(
            "SELECT e.*, v.agent_id FROM demo_exchange e "
            "JOIN agent_version v ON v.agent_version_id = e.agent_version_id "
            "ORDER BY e.exchange_id LIMIT 1"
        )
        row = cursor.fetchone()
    if row is None:
        pytest.skip("no curated exchanges seeded")
    return row


def _ask(runtime, db, exchange, principal=BROAD, question=None):
    return runtime.ask(
        db,
        AskRequest(
            agent_id=exchange["agent_id"],
            agent_version_id=exchange["agent_version_id"],
            question=question if question is not None else exchange["question"],
            tier="demo",
            purpose="analytics",
            session_id="SES-TEST",
            principal_id=principal,
            exchange_id=exchange["exchange_id"] if question is None else None,
        ),
    )


def test_the_configured_runtime_is_the_analytic_one(runtime) -> None:
    assert runtime.name == analytic.RUNTIME_NAME


def test_the_spec_name_mock_resolves_to_the_real_runtime(db) -> None:
    """BUILD.md M6.3 calls it "mock"; the same milestone forbids mocked answers."""
    assert registry.build(db, registry.MOCK_ALIAS).name == analytic.RUNTIME_NAME


def test_an_unknown_runtime_is_refused_not_defaulted(db) -> None:
    with pytest.raises(RuntimeUnavailable) as error:
        registry.build(db, "a-runtime-that-does-not-exist")
    assert "available: analytic, cortex" in str(error.value)


def test_cortex_refuses_rather_than_falling_back(db, monkeypatch) -> None:
    """A runtime that cannot start is never replaced by one that can."""
    monkeypatch.setenv("SNOWFLAKE_PRIVATE_KEY", "")
    with pytest.raises(RuntimeUnavailable):
        registry.build(db, registry.CORTEX)


def test_an_answer_reports_zero_tokens_because_no_model_is_called(
    runtime, db, exchange
) -> None:
    """A trace that invents a plausible token count is a trace that lies."""
    answer = _ask(runtime, db, exchange)
    assert answer.tokens_in == 0
    assert answer.tokens_out == 0
    assert answer.runtime == analytic.RUNTIME_NAME


def test_every_answer_carries_a_citation_and_a_certified_definition(
    runtime, db, exchange
) -> None:
    answer = _ask(runtime, db, exchange)
    assert answer.citations
    assert answer.kpi_definitions
    for citation in answer.citations:
        assert citation.product_id
        assert citation.contract_version
        assert citation.columns


def test_the_answer_is_computed_not_recorded(runtime, db, exchange) -> None:
    """Change the data, and the number changes. That is the whole difference.

    Half the demo-tier rows are deleted inside the rolled-back transaction; an
    answer that came from a fixture would not notice.
    """
    schema = os.environ["DEMO_TIER_SCHEMA"]
    before = _ask(runtime, db, exchange)

    with db.cursor() as cursor:
        table = analytic._demo_table(schema, before.citations[0].product_id)
        cursor.execute(f"DELETE FROM {table} WHERE random() < 0.5")

    after = _ask(runtime, db, exchange)
    assert after.rows_scanned < before.rows_scanned
    assert after.claims != before.claims or after.headline != before.headline


def test_a_narrower_principal_never_reads_more(runtime, db, exchange) -> None:
    """I12, at the runtime: the intersection, never the union."""
    broad = _ask(runtime, db, exchange)
    try:
        narrow = _ask(runtime, db, exchange, principal=NARROW)
    except EntitlementShortfall:
        return  # Refusing outright is "strictly less" in the strongest form.
    broad_columns = {name for c in broad.citations for name in c.columns}
    narrow_columns = {name for c in narrow.citations for name in c.columns}
    assert narrow_columns <= broad_columns


def test_a_refusal_never_names_the_column_the_caller_cannot_see(db, runtime) -> None:
    """Naming the missing column tells the caller the column exists."""
    with db.cursor() as cursor:
        cursor.execute("UPDATE grant_scope SET expression = 'nothing_at_all'")
        cursor.execute("SELECT name FROM data_product_column LIMIT 200")
        published = {row["name"] for row in cursor.fetchall()}
        cursor.execute(
            "SELECT e.*, v.agent_id FROM demo_exchange e "
            "JOIN agent_version v ON v.agent_version_id = e.agent_version_id LIMIT 1"
        )
        exchange = cursor.fetchone()

    with pytest.raises(EntitlementShortfall) as error:
        _ask(runtime, db, exchange)
    assert not (published & set(error.value.detail.split())), error.value.detail
    assert error.value.required_scope.startswith("dp:")


def test_an_action_request_is_refused_and_names_the_boundary(runtime, db, exchange) -> None:
    with db.cursor() as cursor:
        cursor.execute(
            "SELECT out_of_scope FROM agent_version WHERE agent_version_id = %s",
            (exchange["agent_version_id"],),
        )
        declared = cursor.fetchone()["out_of_scope"]

    with pytest.raises(OutOfScope) as error:
        _ask(runtime, db, exchange, question="Approve the offer and close the alert now.")
    assert any(name in error.value.detail for name in declared), error.value.detail


def test_a_request_for_identifiers_is_refused(runtime, db, exchange) -> None:
    with pytest.raises(OutOfScope) as error:
        _ask(runtime, db, exchange, question="Give me the record numbers of the worst cases.")
    assert "records themselves" in error.value.detail


def test_a_question_outside_the_coverage_map_names_a_route(runtime, db, exchange) -> None:
    with pytest.raises(OutOfScope) as error:
        _ask(runtime, db, exchange, question="How is the weather in Lisbon?")
    assert "does not cover" in error.value.detail
    assert error.value.detail.rstrip().endswith(".")


def test_cost_is_the_finops_relative_unit_priced_by_the_runtime_rubric(
    runtime, db, exchange
) -> None:
    answer = _ask(runtime, db, exchange)
    finops = load_current(db, "finops")
    agent_runtime = load_current(db, "agent_runtime")
    expected = (
        finops.number(f"cost_classes.{answer.tool_calls[0].cost_class}")
        * agent_runtime.number("cost_per_relative_unit_usd")
    ).quantize(Decimal("0.000001"))
    assert answer.cost_usd == expected
