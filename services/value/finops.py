"""Cost attribution, unit economics, budgets and retirement (M10.5, section 15.7).

    cost_per_answer          = inference + retrieval + query
    cost_per_accepted_answer = cost_per_answer / acceptance_rate
    value_ratio              = realized_value / total_cost_of_ownership

Cost per *accepted* answer is the number that matters and the one nobody
reports. An agent answering cheaply and being rejected half the time is not a
cheap agent; it is an expensive one with a flattering denominator. Dividing by
the acceptance rate is what makes the two comparable.

Attribution for agents is computed from what their answers actually cost —
every interaction records its own trace — rather than apportioned from a total.
Apportionment is what you do when you cannot measure; here it can be measured,
and a measured number and an apportioned one should never appear in the same
table pretending to be the same kind of thing.

Retirement candidates are quantified. "Nobody uses this" is an observation;
"nobody has queried this in ninety days and it costs $2,400 a year" is a
decision somebody can take to a meeting.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

import psycopg

from services.common.db import fetch_all, fetch_one
from services.common.rubrics import Rubric, load_current

MONEY = Decimal("0.000001")
DISPLAY = Decimal("0.01")
RATIO = Decimal("0.001")
ZERO = Decimal(0)

RETIREMENT_DAYS = "retirement_candidate.no_queries_days"
RETIREMENT_COST = "retirement_candidate.min_annual_cost_usd"
BUDGET_SOFT = "budgets.soft_threshold_fraction"
BUDGET_HARD = "budgets.hard_threshold_fraction"
COST_RATIO_MAX = "targets.cost_per_accepted_answer_vs_manual_max_ratio"
DEMO_SHARE_MAX = "targets.demo_tier_share_of_inference_max"
STEWARDSHIP_RATE = "stewardship.usd_per_asset_day"

# A share is a ratio; the percentage is a presentation of it. The scale and
# the precision live in the runtime rubric with every other display rule, so
# the portal renders what it is given instead of multiplying by a hundred of
# its own.
RUNTIME_RUBRIC = "agent_runtime"
PERCENT_SCALE_PATH = "presentation.percent_scale"
PERCENT_DISPLAY = Decimal("0.1")

SYSTEM_SESSION_PREFIX = "SES-SYS-"
TEST_SESSION_PREFIX = "SES-CONTRACT"

# Named for what it is: inference measured, platform apportioned, stewardship a
# rate. A reader who sees one label on three kinds of number learns nothing.
SOURCE_MIXED = "measured inference; platform apportioned by answer share; stewardship at rate"

# A year, for annualising a daily rate. Derived from the calendar rather than
# written down: today's date this time next year is a year, whatever that year's
# length turns out to be.
def _days_in_year(at: date | None = None) -> Decimal:
    today = at or date.today()
    try:
        next_year = today.replace(year=today.year + 1)
    except ValueError:  # 29 February
        next_year = today.replace(year=today.year + 1, day=today.day - 1)
    return Decimal((next_year - today).days)


@dataclass(frozen=True)
class UnitEconomics:
    agent_id: str
    answered: int
    rated: int
    accepted: int
    acceptance_rate: Decimal
    total_cost_usd: Decimal
    marginal_cost_usd: Decimal
    cost_per_answer_usd: Decimal | None
    cost_per_accepted_answer_usd: Decimal | None
    marginal_per_answer_usd: Decimal | None
    budget_per_answer_usd: Decimal
    within_budget: bool

    def document(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "answered": self.answered,
            "rated": self.rated,
            "accepted": self.accepted,
            "acceptance_rate": float(self.acceptance_rate),
            "total_cost_usd": float(self.total_cost_usd),
            # Marginal and loaded are different questions and must not be one
            # column. The declared budget is a marginal figure — what one more
            # answer costs to produce — so it is compared against the marginal
            # cost. The loaded figure, which carries the agent's share of
            # platform and stewardship, is what the value ratio divides by.
            "marginal_cost_usd": float(self.marginal_cost_usd),
            "marginal_cost_per_answer_usd": (
                float(self.marginal_per_answer_usd)
                if self.marginal_per_answer_usd is not None else None
            ),
            "cost_per_answer_usd": (
                float(self.cost_per_answer_usd)
                if self.cost_per_answer_usd is not None else None
            ),
            # The number that matters. An agent answering cheaply and being
            # rejected half the time is expensive with a flattering denominator.
            "cost_per_accepted_answer_usd": (
                float(self.cost_per_accepted_answer_usd)
                if self.cost_per_accepted_answer_usd is not None else None
            ),
            "budget_per_answer_usd": float(self.budget_per_answer_usd),
            "within_budget": self.within_budget,
        }


def attribute_agent_costs(
    connection: psycopg.Connection[Any],
    tenant: str,
    rubric: Rubric,
    *,
    since: date | None = None,
) -> int:
    """Roll each agent's recorded answer costs into cost_allocation.

    Three components, and the difference between them is stated rather than
    blurred.

    **Inference** is measured: every interaction carries what it cost, so the
    daily total is a sum of facts.

    **Platform** is apportioned. The warehouse bills the query, not the caller,
    so an agent's share of the query cost of the products it reads is its share
    of the traffic against them. The basis is named in the rubric so the number
    can be argued with.

    **Stewardship** is a rate: what it costs to keep one asset governed for a
    day. Leaving it out is what produces a value ratio of forty thousand — an
    agent whose only cost is its own inference looks free, and free is never
    true.

    A measured number and an apportioned one should never sit in one column
    pretending to be the same kind of thing, which is why they sit in three.
    """
    stewardship = Decimal(str(rubric.number(STEWARDSHIP_RATE)))
    rows = fetch_all(
        connection,
        "WITH answers AS ("
        "  SELECT v.agent_id, i.occurred_at::date AS cost_date, count(*) AS answers, "
        "         sum(i.cost_usd) AS inference "
        "  FROM agent_interaction i "
        "  JOIN agent_version v ON v.agent_version_id = i.agent_version_id "
        "  WHERE i.session_id NOT LIKE %s AND i.session_id NOT LIKE %s "
        + ("    AND i.occurred_at >= %s " if since else "")
        + "  GROUP BY v.agent_id, i.occurred_at::date"
        "), reach AS ("
        "  SELECT a.agent_id, a.cost_date, a.answers, a.inference, "
        "         coalesce(sum("
        "           c.query_usd * a.answers "
        "           / NULLIF(u.query_count + a.answers, 0)"
        "         ), 0) AS platform "
        "  FROM answers a "
        "  JOIN agent ag ON ag.agent_id = a.agent_id "
        "  JOIN agent_version v ON v.agent_version_id = ag.current_version_id "
        "  LEFT JOIN agent_product_binding b "
        "    ON b.agent_version_id = v.agent_version_id "
        "  LEFT JOIN cost_allocation c ON c.asset_id = b.product_id "
        "    AND c.asset_type = 'data_product' AND c.cost_date = a.cost_date "
        "  LEFT JOIN usage_daily_agg u ON u.asset_id = b.product_id "
        "    AND u.asset_type = 'data_product' AND u.activity_date = a.cost_date "
        "  GROUP BY a.agent_id, a.cost_date, a.answers, a.inference"
        ") SELECT * FROM reach ORDER BY agent_id, cost_date",
        (f"{SYSTEM_SESSION_PREFIX}%", f"{TEST_SESSION_PREFIX}%", since)
        if since else (f"{SYSTEM_SESSION_PREFIX}%", f"{TEST_SESSION_PREFIX}%"),
    )
    for row in rows:
        connection.execute(
            "INSERT INTO cost_allocation (allocation_id, tenant_id, asset_type, asset_id, "
            "  cost_date, inference_usd, retrieval_usd, query_usd, platform_usd, "
            "  stewardship_usd, tier, source) "
            "VALUES (%s, %s, 'agent', %s, %s, %s, 0, 0, %s, %s, 'live', %s) "
            "ON CONFLICT (allocation_id) DO UPDATE SET "
            "  inference_usd = EXCLUDED.inference_usd, "
            "  platform_usd = EXCLUDED.platform_usd, "
            "  stewardship_usd = EXCLUDED.stewardship_usd",
            (
                f"CA-{row['agent_id']}-{row['cost_date']:%Y%m%d}", tenant, row["agent_id"],
                row["cost_date"], Decimal(str(row["inference"])).quantize(MONEY),
                Decimal(str(row["platform"])).quantize(MONEY),
                stewardship.quantize(MONEY), SOURCE_MIXED,
            ),
        )
    return len(rows)


def unit_economics(
    connection: psycopg.Connection[Any], rubric: Rubric, *, since: date | None = None
) -> list[UnitEconomics]:
    rows = fetch_all(
        connection,
        "SELECT v.agent_id, v.budget_cost_per_answer_usd AS budget, "
        "       count(*) FILTER (WHERE i.outcome = 'answered') AS answered, "
        "       count(f.feedback_id) AS rated, "
        "       count(*) FILTER (WHERE f.accepted) AS accepted, "
        # Cost comes from cost_allocation, the same place the value model reads
        # it. Summing interaction cost here would give a different total for the
        # same agent on two pages, and two numbers with one name is worse than
        # either being wrong.
        "       (SELECT coalesce(sum(c.inference_usd + c.retrieval_usd + c.query_usd "
        "                            + c.platform_usd + c.stewardship_usd), 0) "
        "        FROM cost_allocation c "
        "        WHERE c.asset_type = 'agent' AND c.asset_id = a.agent_id) AS cost, "
        "       (SELECT coalesce(sum(c.inference_usd + c.retrieval_usd), 0) "
        "        FROM cost_allocation c "
        "        WHERE c.asset_type = 'agent' AND c.asset_id = a.agent_id) AS marginal "
        "FROM agent_version v "
        "JOIN agent a ON a.current_version_id = v.agent_version_id "
        "LEFT JOIN agent_interaction i ON i.agent_version_id = v.agent_version_id "
        "  AND i.session_id NOT LIKE %s AND i.session_id NOT LIKE %s "
        + ("  AND i.occurred_at >= %s " if since else "")
        + "LEFT JOIN answer_feedback f ON f.interaction_id = i.interaction_id "
        "GROUP BY v.agent_id, a.agent_id, v.budget_cost_per_answer_usd "
        "ORDER BY v.agent_id",
        (f"{SYSTEM_SESSION_PREFIX}%", f"{TEST_SESSION_PREFIX}%", since)
        if since else (f"{SYSTEM_SESSION_PREFIX}%", f"{TEST_SESSION_PREFIX}%"),
    )

    results: list[UnitEconomics] = []
    for row in rows:
        answered = int(row["answered"])
        rated = int(row["rated"])
        accepted = int(row["accepted"])
        cost = Decimal(str(row["cost"]))
        marginal = Decimal(str(row["marginal"]))
        budget = Decimal(str(row["budget"]))
        acceptance = (Decimal(accepted) / Decimal(rated)).quantize(RATIO) if rated else ZERO
        per_answer = (cost / Decimal(answered)).quantize(MONEY) if answered else None
        marginal_per_answer = (
            (marginal / Decimal(answered)).quantize(MONEY) if answered else None
        )
        per_accepted = (
            (per_answer / acceptance).quantize(MONEY)
            if per_answer is not None and acceptance > ZERO
            else None
        )
        results.append(
            UnitEconomics(
                agent_id=row["agent_id"],
                answered=answered,
                rated=rated,
                accepted=accepted,
                acceptance_rate=acceptance,
                total_cost_usd=cost.quantize(DISPLAY, rounding=ROUND_HALF_EVEN),
                marginal_cost_usd=marginal.quantize(DISPLAY, rounding=ROUND_HALF_EVEN),
                cost_per_answer_usd=per_answer,
                cost_per_accepted_answer_usd=per_accepted,
                marginal_per_answer_usd=marginal_per_answer,
                budget_per_answer_usd=budget,
                within_budget=(
                    marginal_per_answer is None or marginal_per_answer <= budget
                ),
            )
        )
    return results


def budgets(connection: psycopg.Connection[Any], rubric: Rubric) -> list[dict[str, Any]]:
    """Spend against each version's declared per-answer budget.

    Two thresholds, from the finops rubric: soft is a warning, hard is where
    "budget exhaustion freezes feature work" (section 14 of the operating
    model). Both are reported as a share so a reader sees the trajectory rather
    than only the breach.
    """
    soft = Decimal(str(rubric.number(BUDGET_SOFT)))
    hard = Decimal(str(rubric.number(BUDGET_HARD)))

    results = []
    for item in unit_economics(connection, rubric):
        if item.marginal_per_answer_usd is None:
            continue
        # Against the marginal cost, because that is what the budget is for.
        consumed = (
            item.marginal_per_answer_usd / item.budget_per_answer_usd
        ).quantize(RATIO)
        results.append(
            {
                "agent_id": item.agent_id,
                "marginal_cost_per_answer_usd": float(item.marginal_per_answer_usd),
                "loaded_cost_per_answer_usd": float(item.cost_per_answer_usd or ZERO),
                "budget_per_answer_usd": float(item.budget_per_answer_usd),
                "consumed_fraction": float(consumed),
                "state": (
                    "over" if consumed > hard
                    else "warning" if consumed >= soft
                    else "within"
                ),
            }
        )
    return sorted(results, key=lambda row: -row["consumed_fraction"])


def retirement_candidates(
    connection: psycopg.Connection[Any], rubric: Rubric
) -> list[dict[str, Any]]:
    """Assets nobody queries that still cost money, with the saving quantified.

    Both conditions, from the rubric. Something unused and free is not worth a
    meeting; something expensive and used is not a candidate. The annual figure
    is projected from the observed daily rate, and it is what makes this
    actionable rather than merely true.
    """
    days = int(rubric.number(RETIREMENT_DAYS))
    minimum = Decimal(str(rubric.number(RETIREMENT_COST)))

    return [
        {
            **row,
            "annual_cost_usd": float(row["annual_cost_usd"]),
            "why": (
                f"no query in {days} days, and it costs about "
                f"${row['annual_cost_usd']:,.0f} a year to keep"
            ),
        }
        for row in fetch_all(
            connection,
            "WITH spend AS ("
            "  SELECT asset_type, asset_id, "
            "         sum(inference_usd + retrieval_usd + query_usd + platform_usd "
            "             + stewardship_usd) AS total, "
            "         count(DISTINCT cost_date) AS days_observed "
            "  FROM cost_allocation GROUP BY asset_type, asset_id"
            # Usage lives in a different table for each kind of asset: products
            # are queried and agents are asked. Reading only one of them marks
            # every agent unused, which is how a heavily used estate produces
            # fourteen retirement candidates.
            "), last_use AS ("
            "  SELECT asset_type, asset_id, max(activity_date) AS last_query "
            "  FROM usage_daily_agg WHERE query_count > 0 GROUP BY asset_type, asset_id"
            "  UNION ALL "
            "  SELECT 'agent', v.agent_id, max(i.occurred_at::date) "
            "  FROM agent_interaction i "
            "  JOIN agent_version v ON v.agent_version_id = i.agent_version_id "
            "  WHERE i.session_id NOT LIKE %s AND i.session_id NOT LIKE %s "
            "  GROUP BY v.agent_id"
            ") "
            "SELECT s.asset_type, s.asset_id, max(u.last_query) AS last_query, "
            "       s.days_observed, "
            "       round(s.total, 2) AS observed_cost_usd, "
            "       round(s.total / NULLIF(s.days_observed, 0) * %s, 2) AS annual_cost_usd "
            "FROM spend s LEFT JOIN last_use u "
            "  ON u.asset_type = s.asset_type AND u.asset_id = s.asset_id "
            "GROUP BY s.asset_type, s.asset_id, s.days_observed, s.total "
            "HAVING (max(u.last_query) IS NULL "
            "        OR max(u.last_query) < current_date - %s::int) "
            "   AND s.days_observed > 0 "
            "   AND s.total / s.days_observed * %s >= %s "
            "ORDER BY annual_cost_usd DESC",
            (
                f"{SYSTEM_SESSION_PREFIX}%", f"{TEST_SESSION_PREFIX}%",
                _days_in_year(), days, _days_in_year(), minimum,
            ),
        )
    ]


def demo_tier_share(
    connection: psycopg.Connection[Any], rubric: Rubric
) -> dict[str, Any]:
    """What proportion of inference spend goes on demos.

    The finops rubric caps it. A marketplace whose demo theatre costs more than
    its production traffic is selling a thing it does not run.
    """
    cap = Decimal(str(rubric.number(DEMO_SHARE_MAX)))
    row = fetch_one(
        connection,
        "SELECT coalesce(sum(cost_usd) FILTER (WHERE tier = 'demo'), 0) AS demo, "
        "       coalesce(sum(cost_usd), 0) AS total FROM agent_interaction",
    )
    demo = Decimal(str(row["demo"])) if row else ZERO
    total = Decimal(str(row["total"])) if row else ZERO
    share = (demo / total).quantize(RATIO) if total else ZERO
    scale = Decimal(str(load_current(connection, RUNTIME_RUBRIC).number(PERCENT_SCALE_PATH)))
    return {
        "demo_usd": float(demo.quantize(DISPLAY)),
        "total_usd": float(total.quantize(DISPLAY)),
        "share": float(share),
        "cap": float(cap),
        "share_pct": float((share * scale).quantize(PERCENT_DISPLAY)),
        "cap_pct": float((cap * scale).quantize(PERCENT_DISPLAY)),
        "within_cap": share <= cap,
    }


def snapshot_costs(
    connection: psycopg.Connection[Any], *, since: date | None = None
) -> list[dict[str, Any]]:
    """Cost by asset and category, for the dashboard's breakdown."""
    return fetch_all(
        connection,
        "SELECT asset_type, asset_id, source, "
        "       round(sum(inference_usd), 2) AS inference_usd, "
        "       round(sum(retrieval_usd), 2) AS retrieval_usd, "
        "       round(sum(query_usd), 2) AS query_usd, "
        "       round(sum(platform_usd), 2) AS platform_usd, "
        "       round(sum(stewardship_usd), 2) AS stewardship_usd, "
        "       round(sum(inference_usd + retrieval_usd + query_usd + platform_usd "
        "                 + stewardship_usd), 2) AS total_usd "
        "FROM cost_allocation "
        + ("WHERE cost_date >= %s " if since else "")
        + "GROUP BY asset_type, asset_id, source ORDER BY total_usd DESC",
        (since,) if since else (),
    )
