"""Synthetic agent usage, so the agent plane has something real to measure.

The harvest gives the data plane its usage from the platform's query history.
The agent plane has no equivalent — an agent's usage lives in this marketplace,
not in a warehouse — so without this, `agent_interaction` contains only the
marketplace's own test runs. Adoption counts, co-usage edges, cost attribution
and every observability figure would then be measuring the demo runner.

Consumers are drawn from the same pool and by the same industry-anchored window
as the platform sandbox uses, so a person who queries the telecom products is
the person who asks the telecom agents. That is what makes the two meshes tell a
consistent story rather than two unrelated ones.

Sessions are the unit that matters. A person asks two or three questions in a
sitting, sometimes of two different agents, and the gap between sittings is days
— which is what makes co-usage a signal rather than a restatement of who is
busy.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg

from services.common.db import fetch_all

DAYS = 30
MIN_CONSUMERS = 3
CONSUMER_WINDOW_DIVISOR = 3
MINUTES_IN_WORKING_DAY = 540
MAX_QUESTIONS_PER_SITTING = 3

# Sessions the marketplace runs against itself. Named with a shared prefix so
# every usage query can exclude them: the demo runner asking all fourteen agents
# in ten seconds is the marketplace testing itself, not fourteen people using it,
# and counting it as adoption would make every figure a lie in the same
# direction.
SYSTEM_SESSION_PREFIX = "SES-SYS-"

OUTCOME_ANSWERED = "answered"
OUTCOME_OUT_OF_SCOPE = "out_of_scope"
OUTCOME_DENIED = "denied"

# Out of a hundred sittings: how many end in a refusal of each kind. Refusals are
# seeded deliberately — an estate whose agents never refuse anything would make
# the refusal surfaces untestable and the out-of-scope rate look like zero.
OUT_OF_SCOPE_IN_HUNDRED = 9
DENIED_IN_HUNDRED = 3
HUNDRED = 100

# SQL's wildcard. Spelled out because psycopg reads a literal % in a statement
# as the start of a placeholder.
PERCENT = "%"


def _draw(seed: str, lower: int, upper: int) -> int:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return lower + (int.from_bytes(digest[:8], "big") % (upper - lower + 1))


def _pool(connection: psycopg.Connection[Any]) -> list[str]:
    return [
        row["party_id"]
        for row in fetch_all(
            connection,
            "SELECT party_id FROM party WHERE party_type = 'person' ORDER BY party_id",
        )
    ]


def _window(pool: list[str], industry: str, count: int) -> list[str]:
    if not pool:
        return []
    anchor = _draw(f"industry-{industry}", 0, len(pool) - 1)
    return [pool[(anchor + offset) % len(pool)] for offset in range(count)]


def seed(connection: psycopg.Connection[Any], tenant: str) -> int:
    pool = _pool(connection)
    agents = fetch_all(
        connection,
        "SELECT a.agent_id, a.industry_code, v.agent_version_id, "
        "       v.budget_cost_per_answer_usd, v.budget_p95_latency_ms "
        "FROM agent a JOIN agent_version v ON v.agent_version_id = a.current_version_id "
        "ORDER BY a.agent_id",
    )
    exchanges = {
        row["agent_version_id"]: row["questions"]
        for row in fetch_all(
            connection,
            "SELECT agent_version_id, array_agg(question ORDER BY ordinal) AS questions, "
            "       array_agg(kpi_class ORDER BY ordinal) AS classes "
            "FROM demo_exchange GROUP BY agent_version_id",
        )
    }
    classes = {
        row["agent_version_id"]: row["classes"]
        for row in fetch_all(
            connection,
            "SELECT agent_version_id, array_agg(kpi_class ORDER BY ordinal) AS classes "
            "FROM demo_exchange GROUP BY agent_version_id",
        )
    }

    now = datetime.now(UTC).replace(microsecond=0)
    written = 0

    with connection.cursor() as cursor:
        # Replace the window rather than adding to it, for the same reason the
        # harvest does: usage that stopped has to be able to show as stopped.
        # Only what this seeder owns. The marketplace's own runs — the demo
        # runner, the evaluation harness — are somebody else's telemetry, and a
        # seeder that deletes another component's records is a seeder that makes
        # its own output look like the whole truth.
        # Feedback goes first: it references the interactions being replaced.
        cursor.execute(
            "DELETE FROM answer_feedback WHERE interaction_id IN ("
            "  SELECT interaction_id FROM agent_interaction "
            "  WHERE occurred_at >= %s AND session_id LIKE 'SES-U-' || chr(37))",
            (now - timedelta(days=DAYS),),
        )
        cursor.execute(
            "DELETE FROM agent_interaction WHERE occurred_at >= %s "
            "AND session_id LIKE 'SES-U-' || chr(37)",
            (now - timedelta(days=DAYS),),
        )

        for agent in agents:
            questions = exchanges.get(agent["agent_version_id"]) or []
            kpi_classes = classes.get(agent["agent_version_id"]) or []
            if not questions:
                continue
            consumers = _window(
                pool, agent["industry_code"],
                _draw(f"{agent['agent_id']}-consumers", MIN_CONSUMERS,
                      max(MIN_CONSUMERS, len(pool) // CONSUMER_WINDOW_DIVISOR)),
            )

            for day in range(DAYS):
                for index, party in enumerate(consumers):
                    sitting = f"{agent['agent_id']}-{day}-{index}"
                    # Not every consumer asks every day; that would make usage a
                    # flat line and every trend undetectable.
                    if _draw(sitting + "-active", 1, HUNDRED) > _activity(agent, day):
                        continue
                    started = now - timedelta(days=day) + timedelta(
                        minutes=_draw(sitting + "-minute", 0, MINUTES_IN_WORKING_DAY)
                    )
                    asked = _draw(sitting + "-count", 1, MAX_QUESTIONS_PER_SITTING)
                    for turn in range(asked):
                        key = f"{sitting}-{turn}"
                        which = _draw(key + "-q", 0, len(questions) - 1)
                        roll = _draw(key + "-outcome", 1, HUNDRED)
                        outcome = (
                            OUTCOME_OUT_OF_SCOPE if roll <= OUT_OF_SCOPE_IN_HUNDRED
                            else OUTCOME_DENIED
                            if roll <= OUT_OF_SCOPE_IN_HUNDRED + DENIED_IN_HUNDRED
                            else OUTCOME_ANSWERED
                        )
                        answered = outcome == OUTCOME_ANSWERED
                        cursor.execute(
                            "INSERT INTO agent_interaction (interaction_id, tenant_id, "
                            "  agent_version_id, principal_id, session_id, tier, question, "
                            "  question_class, purpose_code, outcome, grounded, confidence, "
                            "  citations, kpi_definitions, tool_calls, rows_scanned, "
                            "  latency_ms, tokens_in, tokens_out, cost_usd, occurred_at) "
                            "VALUES (%s, %s, %s, %s, %s, 'live', %s, %s, 'analytics', %s, "
                            "        %s, %s, '[]'::jsonb, %s, '[]'::jsonb, %s, %s, 0, 0, "
                            "        %s, %s) "
                            "ON CONFLICT (interaction_id) DO NOTHING",
                            (
                                f"INT-U-{key}", tenant, agent["agent_version_id"], party,
                                f"SES-U-{sitting}", questions[which],
                                kpi_classes[which] if which < len(kpi_classes) else "ad_hoc",
                                outcome, answered,
                                Decimal("0.93") if answered else None,
                                [kpi_classes[which]] if answered and kpi_classes else [],
                                _draw(key + "-rows", 800, 90000) if answered else 0,
                                _draw(key + "-ms", 400,
                                      int(agent["budget_p95_latency_ms"])),
                                (
                                    Decimal(_draw(key + "-cost", 1, 40)) / Decimal(10000)
                                    if answered else Decimal(0)
                                ),
                                started + timedelta(minutes=turn),
                            ),
                        )
                        written += 1

        # Feedback on a share of the answered interactions, so the acceptance
        # rate on the agent page is computed from something.
        cursor.execute(
            "INSERT INTO answer_feedback (feedback_id, tenant_id, interaction_id, party_id, "
            "  accepted, reason_code) "
            "SELECT 'FBK-' || i.interaction_id, i.tenant_id, i.interaction_id, "
            "       i.principal_id, "
            # mod(), not the % operator: psycopg reads % as a placeholder marker
            # and this statement carries no parameters to bind.
            "       mod(('x' || substr(md5(i.interaction_id), 1, 8))::bit(32)::bigint, 10) "
            "         > 1, "
            "       CASE WHEN mod(('x' || substr(md5(i.interaction_id), 1, 8))::bit(32)"
            "                     ::bigint, 10) > 1 "
            "            THEN 'correct' ELSE 'wrong_number' END "
            "FROM agent_interaction i "
            "WHERE i.outcome = 'answered' AND i.session_id LIKE 'SES-U-' || chr(37) "
            "  AND mod(('x' || substr(md5(i.interaction_id), 1, 8))::bit(32)::bigint, 5) = 0 "
            "ON CONFLICT (interaction_id, party_id) DO NOTHING"
        )
    return written


def _activity(agent: dict[str, Any], day: int) -> int:
    """How likely a given consumer is to ask on a given day, out of a hundred.

    Weekdays only, and rising slightly over the window so the adoption charts
    have a direction rather than a flat line.
    """
    weekday = (datetime.now(UTC) - timedelta(days=day)).weekday()
    if weekday >= _SATURDAY:
        return 0
    base = _draw(f"{agent['agent_id']}-base", 20, 60)
    growth = (DAYS - day) * _GROWTH_PER_DAY
    return min(HUNDRED, base + growth)


_SATURDAY = 5
_GROWTH_PER_DAY = 1
