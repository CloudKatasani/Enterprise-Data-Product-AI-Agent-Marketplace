"""Product and agent signals (M10.1).

Each detector answers one question about one asset and returns a finding with
the numbers behind it. Nothing here raises an incident — that is
:mod:`services.observability.incidents`, which decides severity from blast
radius. Keeping detection and severity apart matters: a detector that also
judged importance would need to know about consumers, and then every new signal
would have to learn the whole estate.

Two signals are worth naming for what they are rather than what they measure.

The **access** signal counts permission denials. A denial rate is usually read
as a security metric; here it is a demand one. People are trying to use
something they cannot reach, and that is a queue of access requests nobody has
filed yet.

The **refusal** signal counts out-of-scope answers. High refusal is not an agent
failing. It is consumers asking for something the estate does not cover, which
is the most specific demand signal the marketplace ever gets.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import psycopg

from services.common.db import fetch_all
from services.common.rubrics import Rubric

ASSET_PRODUCT = "data_product"
ASSET_AGENT = "agent"

SIGNAL_FRESHNESS = "freshness"
SIGNAL_VOLUME = "volume"
SIGNAL_QUALITY = "quality"
SIGNAL_ACCESS = "access"
SIGNAL_COST = "cost"

SIGNAL_GROUNDEDNESS = "groundedness"
SIGNAL_REFUSAL = "refusal"
SIGNAL_PERFORMANCE = "performance"
SIGNAL_ACCEPTANCE = "acceptance"
SIGNAL_SAFETY = "safety"

# What kind of number a signal produces. A reader shown "0.0666" and "79" in
# one column has been told the arithmetic and not the meaning; a unit is what
# makes the two comparable sentences. It belongs to the signal, not to the
# individual finding, so it is stated once here rather than at every detector.
UNIT_MINUTES = "minutes"
UNIT_FRACTION = "fraction"
UNIT_POINTS = "points"
UNIT_COUNT = "count"
UNIT_MULTIPLE = "multiple"

UNIT_BY_SIGNAL = {
    SIGNAL_FRESHNESS: UNIT_MINUTES,
    SIGNAL_VOLUME: UNIT_FRACTION,
    SIGNAL_QUALITY: UNIT_POINTS,
    SIGNAL_ACCESS: UNIT_FRACTION,
    SIGNAL_COST: UNIT_MULTIPLE,
    SIGNAL_GROUNDEDNESS: UNIT_COUNT,
    SIGNAL_REFUSAL: UNIT_FRACTION,
    SIGNAL_PERFORMANCE: UNIT_FRACTION,
    SIGNAL_ACCEPTANCE: UNIT_FRACTION,
    SIGNAL_SAFETY: UNIT_FRACTION,
}

PRODUCT_SIGNALS = (
    SIGNAL_FRESHNESS, SIGNAL_VOLUME, SIGNAL_QUALITY, SIGNAL_ACCESS, SIGNAL_COST,
)
AGENT_SIGNALS = (
    SIGNAL_GROUNDEDNESS, SIGNAL_REFUSAL, SIGNAL_PERFORMANCE, SIGNAL_ACCEPTANCE,
    SIGNAL_SAFETY,
)

ZERO = Decimal(0)


@dataclass(frozen=True)
class Finding:
    """One signal firing on one asset, with the arithmetic that fired it."""

    asset_type: str
    asset_id: str
    signal: str
    detail: str
    observed: Decimal
    threshold: Decimal
    guarantee_breached: str | None = None

    @property
    def unit(self) -> str:
        return UNIT_BY_SIGNAL[self.signal]

    def document(self) -> dict[str, Any]:
        return {
            "asset_type": self.asset_type,
            "asset_id": self.asset_id,
            "signal": self.signal,
            "detail": self.detail,
            "observed": float(self.observed),
            "threshold": float(self.threshold),
            "unit": self.unit,
            "guarantee_breached": self.guarantee_breached,
        }


def _number(rubric: Rubric, path: str) -> Decimal:
    return Decimal(str(rubric.number(path)))


# ---------------------------------------------------------------------------
# Product signals
# ---------------------------------------------------------------------------


def freshness(connection: psycopg.Connection[Any], rubric: Rubric) -> list[Finding]:
    """Load state against the contract's stated freshness guarantee.

    Freshness is measured by the product's own freshness rules, which record how
    many minutes late the load ran against the tolerance the contract states.
    Reading the rule rather than re-deriving lateness keeps one measurement: the
    number on the quality tab and the number that raised the incident are the
    same number.

    The rubric's grace is the allowance for a load that is late but not broken.
    Without it a product with a 06:00 target raises an incident at 06:01 every
    morning, and a signal that fires daily is a signal everybody mutes.
    """
    grace = _number(rubric, "product_signals.freshness.grace_minutes")
    return [
        Finding(
            asset_type=ASSET_PRODUCT,
            asset_id=row["product_id"],
            signal=SIGNAL_FRESHNESS,
            detail=(
                f"{row['product_id']} loaded {int(row['observed'])} minutes late against "
                f"a {int(row['tolerance'])} minute tolerance on {row['target_text']}"
            ),
            observed=Decimal(str(row["observed"])),
            threshold=Decimal(str(row["tolerance"])) + grace,
            guarantee_breached=f"freshness: {row['target_text']}",
        )
        for row in fetch_all(
            connection,
            "SELECT DISTINCT ON (q.product_id) q.product_id, q.target_text, "
            "       q.tolerance_minutes AS tolerance, r.observed_value AS observed "
            "FROM quality_result r "
            "JOIN quality_rule q ON q.rule_id = r.rule_id "
            "WHERE q.dimension = 'freshness' AND q.enabled "
            "  AND r.observed_value IS NOT NULL AND q.tolerance_minutes IS NOT NULL "
            "  AND r.observed_value > q.tolerance_minutes + %s "
            "ORDER BY q.product_id, r.evaluated_at DESC",
            (grace,),
        )
    ]


def volume(connection: psycopg.Connection[Any], rubric: Rubric) -> list[Finding]:
    """A day's rows well below the trailing median."""
    drop = _number(rubric, "product_signals.volume.drop_fraction")
    days = int(rubric.number("product_signals.volume.trailing_days"))
    return [
        Finding(
            asset_type=ASSET_PRODUCT,
            asset_id=row["asset_id"],
            signal=SIGNAL_VOLUME,
            detail=(
                f"{row['asset_id']} scanned {int(row['latest'])} rows against a "
                f"{days}-day median of {int(row['median'])}"
            ),
            observed=Decimal(str(row["shortfall"])),
            threshold=drop,
        )
        for row in fetch_all(
            connection,
            "WITH recent AS ("
            "  SELECT asset_id, activity_date, rows_scanned FROM usage_daily_agg "
            "  WHERE asset_type = 'data_product' "
            "    AND activity_date > current_date - %s::int"
            "), latest AS ("
            "  SELECT DISTINCT ON (asset_id) asset_id, rows_scanned FROM recent "
            "  ORDER BY asset_id, activity_date DESC"
            "), middle AS ("
            "  SELECT asset_id, percentile_cont(0.5) WITHIN GROUP (ORDER BY rows_scanned) "
            "         AS median FROM recent GROUP BY asset_id"
            ") "
            "SELECT l.asset_id, l.rows_scanned AS latest, m.median, "
            "       (m.median - l.rows_scanned) / NULLIF(m.median, 0) AS shortfall "
            "FROM latest l JOIN middle m ON m.asset_id = l.asset_id "
            "WHERE m.median > 0 "
            "  AND (m.median - l.rows_scanned) / m.median > %s",
            (days, drop),
        )
    ]


def quality(connection: psycopg.Connection[Any], rubric: Rubric) -> list[Finding]:
    """A composite that fell between snapshots, even inside its band."""
    points = _number(rubric, "product_signals.quality.composite_drop_points")
    return [
        Finding(
            asset_type=ASSET_PRODUCT,
            asset_id=row["product_id"],
            signal=SIGNAL_QUALITY,
            detail=(
                f"{row['product_id']} fell {row['drop']} points, from {row['previous']} "
                f"to {row['composite']}"
            ),
            observed=Decimal(str(row["drop"])),
            threshold=points,
            guarantee_breached=(
                f"quality band: {row['band']}" if row["band"] in _POOR_BANDS else None
            ),
        )
        for row in fetch_all(
            connection,
            "WITH ordered AS ("
            "  SELECT product_id, composite, band, computed_at, "
            "         lag(composite) OVER (PARTITION BY product_id ORDER BY computed_at) "
            "           AS previous "
            "  FROM quality_score_snapshot"
            "), latest AS ("
            "  SELECT DISTINCT ON (product_id) * FROM ordered "
            "  ORDER BY product_id, computed_at DESC"
            ") "
            "SELECT product_id, composite, band, previous, previous - composite AS drop "
            "FROM latest WHERE previous IS NOT NULL AND previous - composite > %s",
            (points,),
        )
    ]


_POOR_BANDS = frozenset({"at_risk", "unfit"})


def access(connection: psycopg.Connection[Any], rubric: Rubric) -> list[Finding]:
    """Permission denials as a share of queries — a demand signal, not a fault."""
    rate = _number(rubric, "product_signals.access.denied_rate")
    minimum = int(rubric.number("product_signals.access.min_queries"))
    return [
        Finding(
            asset_type=ASSET_PRODUCT,
            asset_id=row["asset_id"],
            signal=SIGNAL_ACCESS,
            detail=(
                f"{int(row['denied'])} of {int(row['queries'])} queries against "
                f"{row['asset_id']} were refused for permission. People are trying to use "
                "it and cannot; that is an access request nobody has filed."
            ),
            observed=Decimal(str(row["denied_rate"])),
            threshold=rate,
        )
        for row in fetch_all(
            connection,
            "SELECT asset_id, sum(query_count) AS queries, sum(denied_count) AS denied, "
            "       sum(denied_count)::numeric / NULLIF(sum(query_count), 0) AS denied_rate "
            "FROM usage_daily_agg WHERE asset_type = 'data_product' "
            "GROUP BY asset_id "
            "HAVING sum(query_count) >= %s "
            "   AND sum(denied_count)::numeric / NULLIF(sum(query_count), 0) > %s",
            (minimum, rate),
        )
    ]


def cost(connection: psycopg.Connection[Any], rubric: Rubric) -> list[Finding]:
    """A day's cost well above the trailing median."""
    multiple = _number(rubric, "product_signals.cost.spike_multiple")
    days = int(rubric.number("product_signals.cost.trailing_days"))
    return [
        Finding(
            asset_type=row["asset_type"],
            asset_id=row["asset_id"],
            signal=SIGNAL_COST,
            detail=(
                f"{row['asset_id']} cost ${row['latest']} on its last recorded day, "
                f"{row['ratio']}x its {days}-day median of ${row['median']}"
            ),
            observed=Decimal(str(row["ratio"])),
            threshold=multiple,
        )
        for row in fetch_all(
            connection,
            "WITH totals AS ("
            "  SELECT asset_type, asset_id, cost_date, "
            "         inference_usd + retrieval_usd + query_usd + platform_usd "
            "           + stewardship_usd AS total "
            "  FROM cost_allocation WHERE cost_date > current_date - %s::int"
            "), latest AS ("
            "  SELECT DISTINCT ON (asset_type, asset_id) asset_type, asset_id, total "
            "  FROM totals ORDER BY asset_type, asset_id, cost_date DESC"
            "), middle AS ("
            "  SELECT asset_type, asset_id, "
            "         percentile_cont(0.5) WITHIN GROUP (ORDER BY total) AS median "
            "  FROM totals GROUP BY asset_type, asset_id"
            ") "
            # median comes back as double precision from percentile_cont, and
            # round(double, int) does not exist. Cast, rather than rounding to
            # whole dollars and losing the difference the signal is about.
            "SELECT l.asset_type, l.asset_id, round(l.total::numeric, 2) AS latest, "
            "       round(m.median::numeric, 2) AS median, "
            "       round((l.total / NULLIF(m.median, 0))::numeric, 2) AS ratio "
            "FROM latest l JOIN middle m ON m.asset_id = l.asset_id "
            "  AND m.asset_type = l.asset_type "
            "WHERE m.median > 0 AND l.total / m.median > %s",
            (days, multiple),
        )
    ]


# ---------------------------------------------------------------------------
# Agent signals
# ---------------------------------------------------------------------------


def groundedness(connection: psycopg.Connection[Any], rubric: Rubric) -> list[Finding]:
    """Any answer that failed grounding. I11 admits no rate."""
    allowed = _number(rubric, "agent_signals.groundedness.max_ungrounded")
    return [
        Finding(
            asset_type=ASSET_AGENT,
            asset_id=row["agent_id"],
            signal=SIGNAL_GROUNDEDNESS,
            detail=(
                f"{int(row['ungrounded'])} answer(s) from {row['agent_id']} failed "
                "grounding and were withheld. The check held; the next one might not."
            ),
            observed=Decimal(str(row["ungrounded"])),
            threshold=allowed,
            guarantee_breached="groundedness: every numeric claim cited",
        )
        for row in fetch_all(
            connection,
            "SELECT v.agent_id, count(*) AS ungrounded FROM agent_interaction i "
            "JOIN agent_version v ON v.agent_version_id = i.agent_version_id "
            "WHERE i.outcome = 'ungrounded' AND i.session_id NOT LIKE %s "
            "  AND i.session_id NOT LIKE %s "
            "GROUP BY v.agent_id HAVING count(*) > %s",
            (f"{SYSTEM_SESSION_PREFIX}%", f"{TEST_SESSION_PREFIX}%", allowed),
        )
    ]


def refusal(connection: psycopg.Connection[Any], rubric: Rubric) -> list[Finding]:
    """Out-of-scope answers as a share — demand, not failure."""
    rate = _number(rubric, "agent_signals.refusal.rate")
    minimum = int(rubric.number("agent_signals.refusal.min_answers"))
    return [
        Finding(
            asset_type=ASSET_AGENT,
            asset_id=row["agent_id"],
            signal=SIGNAL_REFUSAL,
            detail=(
                f"{row['agent_id']} refused {int(row['refused'])} of {int(row['asked'])} "
                "questions as out of scope. That is consumers pointing at something the "
                "estate does not cover."
            ),
            observed=Decimal(str(row["refusal_rate"])),
            threshold=rate,
        )
        for row in fetch_all(
            connection,
            "SELECT v.agent_id, count(*) AS asked, "
            "       count(*) FILTER (WHERE i.outcome = 'out_of_scope') AS refused, "
            "       count(*) FILTER (WHERE i.outcome = 'out_of_scope')::numeric "
            "         / NULLIF(count(*), 0) AS refusal_rate "
            "FROM agent_interaction i "
            "JOIN agent_version v ON v.agent_version_id = i.agent_version_id "
            "WHERE i.session_id NOT LIKE %s "
            "GROUP BY v.agent_id HAVING count(*) >= %s "
            "   AND count(*) FILTER (WHERE i.outcome = 'out_of_scope')::numeric "
            "       / NULLIF(count(*), 0) > %s",
            (f"{SYSTEM_SESSION_PREFIX}%", minimum, rate),
        )
    ]


SYSTEM_SESSION_PREFIX = "SES-SYS-"
# The contract suite also drives the real API and leaves real interactions.
# Excluded for the same reason: it is the marketplace exercising itself.
TEST_SESSION_PREFIX = "SES-CONTRACT"


def performance(connection: psycopg.Connection[Any], rubric: Rubric) -> list[Finding]:
    """Answers over the version's own declared latency budget."""
    rate = _number(rubric, "agent_signals.performance.over_budget_rate")
    return [
        Finding(
            asset_type=ASSET_AGENT,
            asset_id=row["agent_id"],
            signal=SIGNAL_PERFORMANCE,
            detail=(
                f"{int(row['slow'])} of {int(row['answered'])} answers from "
                f"{row['agent_id']} exceeded its own {int(row['budget'])}ms budget"
            ),
            observed=Decimal(str(row["over_rate"])),
            threshold=rate,
            guarantee_breached=f"p95 latency: {int(row['budget'])}ms",
        )
        for row in fetch_all(
            connection,
            "SELECT v.agent_id, v.budget_p95_latency_ms AS budget, count(*) AS answered, "
            "       count(*) FILTER (WHERE i.latency_ms > v.budget_p95_latency_ms) AS slow, "
            "       count(*) FILTER (WHERE i.latency_ms > v.budget_p95_latency_ms)::numeric "
            "         / NULLIF(count(*), 0) AS over_rate "
            "FROM agent_interaction i "
            "JOIN agent_version v ON v.agent_version_id = i.agent_version_id "
            "WHERE i.outcome = 'answered' AND i.session_id NOT LIKE %s "
            "GROUP BY v.agent_id, v.budget_p95_latency_ms "
            "HAVING count(*) FILTER (WHERE i.latency_ms > v.budget_p95_latency_ms)::numeric "
            "       / NULLIF(count(*), 0) > %s",
            (f"{SYSTEM_SESSION_PREFIX}%", rate),
        )
    ]


def acceptance(connection: psycopg.Connection[Any], rubric: Rubric) -> list[Finding]:
    """Rejections among the answers people bothered to rate."""
    rate = _number(rubric, "agent_signals.acceptance.rejection_rate")
    minimum = int(rubric.number("agent_signals.acceptance.min_rated"))
    return [
        Finding(
            asset_type=ASSET_AGENT,
            asset_id=row["agent_id"],
            signal=SIGNAL_ACCEPTANCE,
            detail=(
                f"{int(row['rejected'])} of {int(row['rated'])} rated answers from "
                f"{row['agent_id']} were rejected"
            ),
            observed=Decimal(str(row["rejection_rate"])),
            threshold=rate,
        )
        for row in fetch_all(
            connection,
            "SELECT v.agent_id, count(*) AS rated, "
            "       count(*) FILTER (WHERE NOT f.accepted) AS rejected, "
            "       count(*) FILTER (WHERE NOT f.accepted)::numeric "
            "         / NULLIF(count(*), 0) AS rejection_rate "
            "FROM answer_feedback f "
            "JOIN agent_interaction i ON i.interaction_id = f.interaction_id "
            "JOIN agent_version v ON v.agent_version_id = i.agent_version_id "
            "GROUP BY v.agent_id HAVING count(*) >= %s "
            "   AND count(*) FILTER (WHERE NOT f.accepted)::numeric "
            "       / NULLIF(count(*), 0) > %s",
            (minimum, rate),
        )
    ]


def safety(connection: psycopg.Connection[Any], rubric: Rubric) -> list[Finding]:
    """Consumers reaching for data their grant does not cover.

    Worth being precise about what this is and is not. Section 15.6 calls a
    scope violation a security event, and it means an *agent* reaching past its
    own binding. That cannot happen here: the analytic runtime plans only
    within the binding intersected with the caller's grant, and the Cortex
    adapter refuses an answer whose trace names an unbound tool or product
    before it becomes an answer. So the count of true scope violations is
    structurally zero, which is a claim this estate can make and should.

    What this counts instead is the other side of the same wall: a consumer
    asking an agent something their own entitlement does not reach. That is not
    a security event, it is the partial-permission case — and above a rate it
    says the agent's audience and its bindings disagree, which is an access
    request queue nobody has filed.
    """
    rate = _number(rubric, "agent_signals.safety.entitlement_denial_rate")
    minimum = int(rubric.number("agent_signals.safety.min_answers"))
    return [
        Finding(
            asset_type=ASSET_AGENT,
            asset_id=row["agent_id"],
            signal=SIGNAL_SAFETY,
            detail=(
                f"{int(row['denied'])} of {int(row['asked'])} questions to "
                f"{row['agent_id']} were refused because the asker's own grant did not "
                "reach the data. No agent exceeded its binding."
            ),
            observed=Decimal(str(row["denied_rate"])),
            threshold=rate,
        )
        for row in fetch_all(
            connection,
            "SELECT v.agent_id, count(*) AS asked, "
            "       count(*) FILTER (WHERE i.outcome = 'denied') AS denied, "
            "       count(*) FILTER (WHERE i.outcome = 'denied')::numeric "
            "         / NULLIF(count(*), 0) AS denied_rate "
            "FROM agent_interaction i "
            "JOIN agent_version v ON v.agent_version_id = i.agent_version_id "
            "WHERE i.session_id NOT LIKE %s "
            "GROUP BY v.agent_id HAVING count(*) >= %s "
            "   AND count(*) FILTER (WHERE i.outcome = 'denied')::numeric "
            "       / NULLIF(count(*), 0) > %s",
            (f"{SYSTEM_SESSION_PREFIX}%", minimum, rate),
        )
    ]


DETECTORS = {
    SIGNAL_FRESHNESS: freshness,
    SIGNAL_VOLUME: volume,
    SIGNAL_QUALITY: quality,
    SIGNAL_ACCESS: access,
    SIGNAL_COST: cost,
    SIGNAL_GROUNDEDNESS: groundedness,
    SIGNAL_REFUSAL: refusal,
    SIGNAL_PERFORMANCE: performance,
    SIGNAL_ACCEPTANCE: acceptance,
    SIGNAL_SAFETY: safety,
}


def scan(
    connection: psycopg.Connection[Any], rubric: Rubric, *, only: list[str] | None = None
) -> list[Finding]:
    """Run every detector, or the named ones."""
    names = only or list(DETECTORS)
    findings: list[Finding] = []
    for name in names:
        detector = DETECTORS.get(name)
        if detector is None:
            raise KeyError(f"no detector named {name!r}")
        findings.extend(detector(connection, rubric))
    return findings
