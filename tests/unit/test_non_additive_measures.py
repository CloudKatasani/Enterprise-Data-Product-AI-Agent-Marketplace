"""A measure that counts recurring entities cannot be pooled across periods.

This is the bug that produced a 45% monthly churn rate on a product whose
certified target is 1.4%: ``count(distinct subscriber_id) filter (where
churn_flag)`` over thirty-six months counts everyone who ever churned against
everyone who was ever active, and calls the result a monthly rate.

The rule is decided from the data, not from the SQL, because the SQL cannot tell
the two cases apart. ``count(distinct transaction_id)`` pools perfectly well —
a transaction happens once. ``count(distinct subscriber_id)`` does not.
"""

from __future__ import annotations

import os

import pytest

from services.agent_runtime import analytic, registry
from services.agent_runtime.base import AskRequest

SCHEMA = os.environ.get("DEMO_TIER_SCHEMA", "marketplace_demo")
CONSUMER = "PTY-0061"

# February is the shortest month; a period with at least this many days of data
# behind it is complete for the purpose of this test.
DAYS_THAT_MAKE_A_MONTH = 27


@pytest.mark.parametrize(
    ("expressions", "expected"),
    [
        (
            {
                "numerator_expr": "count(distinct subscriber_id) filter (where churn_flag)",
                "denominator_expr": "count(distinct subscriber_id)",
                "expression": None,
            },
            ["subscriber_id"],
        ),
        (
            {"numerator_expr": "sum(net_sales)",
             "denominator_expr": "count(DISTINCT transaction_id)", "expression": None},
            ["transaction_id"],
        ),
        (
            {"numerator_expr": "sum(a)", "denominator_expr": "sum(b)", "expression": None},
            [],
        ),
    ],
)
def test_distinct_keys_are_read_out_of_the_certified_expressions(
    expressions: dict, expected: list[str]
) -> None:
    assert analytic._distinct_keys(expressions) == expected


def test_a_recurring_key_forces_a_single_period(db) -> None:
    """subscriber_id repeats across months, so pooling changes what the number means."""
    kpi = {
        "numerator_expr": "count(distinct subscriber_id) filter (where churn_flag)",
        "denominator_expr": "count(distinct subscriber_id)",
        "expression": None,
    }
    assert analytic._needs_single_period(db, kpi, f"{SCHEMA}.t_dp_tel_001") is True


def test_a_one_per_row_key_does_not(db) -> None:
    """Where the distinct key is unique per row, pooling is the same arithmetic."""
    kpi = {
        "numerator_expr": "count(distinct subscriber_id)",
        "denominator_expr": None,
        "expression": None,
    }
    with db.cursor() as cursor:
        cursor.execute(
            f"CREATE TEMP TABLE one_per_row AS "
            f"SELECT DISTINCT ON (subscriber_id) * FROM {SCHEMA}.t_dp_tel_001"
        )
    assert analytic._needs_single_period(db, kpi, "one_per_row") is False


def test_a_measure_with_no_distinct_is_never_restricted(db) -> None:
    kpi = {"numerator_expr": "sum(ltv)", "denominator_expr": "count(*)", "expression": None}
    assert analytic._needs_single_period(db, kpi, f"{SCHEMA}.t_dp_tel_001") is False


def test_the_restricted_answer_says_which_period_it_covers(db) -> None:
    """A restricted answer and a pooled one are different numbers.

    The reader cannot tell them apart from the figure, so the sentence says
    which it is — and the row count reports what was actually read, not what the
    table holds, because the thin-evidence check reads that number.
    """
    runtime = registry.build(db)
    answer = runtime.ask(
        db,
        AskRequest(
            agent_id="AG-TEL-001",
            agent_version_id="AGV-AG-TEL-001-1.0.0",
            question="Which segments are driving churn?",
            tier="demo",
            purpose="analytics",
            session_id="SES-TEST",
            principal_id=CONSUMER,
        ),
    )
    assert "cannot be pooled across periods" in answer.narrative

    with db.cursor() as cursor:
        cursor.execute(f"SELECT count(*) AS n FROM {SCHEMA}.t_dp_tel_001")
        whole_table = cursor.fetchone()["n"]
    assert answer.rows_scanned < whole_table


def test_the_period_chosen_is_complete(db) -> None:
    """A load that ended one day into a month must not make that month the answer."""
    runtime = registry.build(db)
    answer = runtime.ask(
        db,
        AskRequest(
            agent_id="AG-TEL-001",
            agent_version_id="AGV-AG-TEL-001-1.0.0",
            question="Which segments are driving churn?",
            tier="demo",
            purpose="analytics",
            session_id="SES-TEST",
            principal_id=CONSUMER,
        ),
    )
    with db.cursor() as cursor:
        # Days of data in the final month, computed in the database so the
        # comparison is between two dates of the same type.
        cursor.execute(
            f"SELECT date_trunc('month', max(activity_date))::date AS last_period, "
            f"       max(activity_date)::date - date_trunc('month', max(activity_date))::date "
            f"         AS days_into_period "
            f"FROM {SCHEMA}.t_dp_tel_001"
        )
        row = cursor.fetchone()

    if row["days_into_period"] >= DAYS_THAT_MAKE_A_MONTH:
        pytest.skip("the demo tier's last period is complete; nothing to distinguish")
    assert row["last_period"].isoformat() not in answer.narrative
