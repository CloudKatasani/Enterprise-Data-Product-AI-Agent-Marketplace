"""M10 — the health plane, the value plane, and the two claims they accept on.

    a simulated freshness breach raises an incident, notifies consumers and
    banners every affected listing within 5 minutes;

    the exported board pack and the dashboard read from the same snapshot and
    cannot disagree.

The second is tested the only way it can be meaningfully tested: by changing the
underlying data after the snapshot is taken and asserting that both surfaces
still report the old, agreed figure. A test that merely compared two calls made
a millisecond apart would pass on an implementation that recomputed.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from services.common.rubrics import load_current
from services.observability import incidents, signals
from services.value import finops, model

TENANT = os.environ.get("TENANT_ID", "TEN-DEMO")


@pytest.fixture()
def watch(db):
    return load_current(db, "observability")


@pytest.fixture()
def value_rubric(db):
    return load_current(db, "value_model")


@pytest.fixture()
def cost_rubric(db):
    return load_current(db, "finops")


# ---------------------------------------------------------------------------
# M10 acceptance: the five-minute notification
# ---------------------------------------------------------------------------


def test_a_freshness_breach_raises_notifies_and_banners_within_the_deadline(
    db, watch
) -> None:
    """The M10 acceptance criterion, end to end and on the clock."""
    breach = signals.Finding(
        asset_type=signals.ASSET_PRODUCT,
        asset_id="DP-TEL-001",
        signal=signals.SIGNAL_FRESHNESS,
        detail="simulated: DP-TEL-001 loaded 90 minutes past its target",
        observed=Decimal("90"),
        threshold=Decimal("45"),
        guarantee_breached="freshness: 06:00",
    )

    detected = datetime.now(UTC)
    result = incidents.raise_incident(db, TENANT, watch, breach, at=detected)

    # 1. an incident exists
    assert result["incident_id"]
    open_now = {row["incident_id"] for row in incidents.open_incidents(db)}
    assert result["incident_id"] in open_now

    # 2. consumers were notified, inside the deadline
    deadline = int(watch.number(incidents.DEADLINE_PATH))
    assert result["notified_at"] - detected <= timedelta(minutes=deadline)
    assert incidents.overdue_notifications(db, watch) == []

    # 3. every affected listing carries a banner — the product and every agent
    #    bound to it, because a consumer reading the agent page is relying on
    #    this product whether or not they know its name.
    product_banners = incidents.banners(db, signals.ASSET_PRODUCT, "DP-TEL-001")
    assert any(row["incident_id"] == result["incident_id"] for row in product_banners)

    with db.cursor() as cursor:
        cursor.execute(
            "SELECT DISTINCT a.agent_id FROM agent_product_binding b "
            "JOIN agent_version v ON v.agent_version_id = b.agent_version_id "
            "JOIN agent a ON a.current_version_id = v.agent_version_id "
            "WHERE b.product_id = 'DP-TEL-001'"
        )
        bound = [row["agent_id"] for row in cursor.fetchall()]
    assert bound, "DP-TEL-001 should have agents bound to it"
    for agent_id in bound:
        carried = incidents.banners(db, signals.ASSET_AGENT, agent_id)
        assert any(row["incident_id"] == result["incident_id"] for row in carried), (
            f"{agent_id} reads DP-TEL-001 and must carry its banner"
        )


def test_a_late_notification_is_reported_not_hidden(db, watch) -> None:
    """The deadline is only a deadline if missing it is visible."""
    deadline = int(watch.number(incidents.DEADLINE_PATH))
    with db.cursor() as cursor:
        cursor.execute(
            "INSERT INTO incident (incident_id, tenant_id, asset_type, asset_id, signal, "
            "  severity, severity_inputs, status, detected_at, notified_at) "
            "VALUES ('INC-LATE', %s, 'data_product', 'DP-TEL-001', 'freshness', 'sev2', "
            "        '{}'::jsonb, 'open', now() - %s::interval, now())",
            (TENANT, f"{deadline * 2} minutes"),
        )
    late = incidents.overdue_notifications(db, watch)
    assert any(row["incident_id"] == "INC-LATE" for row in late)


# ---------------------------------------------------------------------------
# Severity is computed, not chosen
# ---------------------------------------------------------------------------


def test_severity_comes_from_blast_radius_and_says_what_produced_it(db, watch) -> None:
    radius = incidents.blast_radius(db, signals.ASSET_PRODUCT, "DP-TEL-001")
    severity, inputs = incidents.compute_severity(
        watch, radius, guarantee_breached=None
    )
    assert severity in {"sev1", "sev2", "sev3", "sev4"}
    assert inputs["consumers"] == radius.consumers
    assert inputs["sensitivity_rank"] == radius.sensitivity_rank
    assert inputs["rubric_version_id"] == watch.rubric_version_id


def test_a_breached_guarantee_escalates_the_severity(db, watch) -> None:
    """A promise broken is worse than a number moving, and the contract said so."""
    radius = incidents.BlastRadius(
        consumers=8, sensitivity_rank=2, products=("DP-TEL-001",), agents=()
    )
    plain, _ = incidents.compute_severity(watch, radius, guarantee_breached=None)
    escalated, inputs = incidents.compute_severity(
        watch, radius, guarantee_breached="freshness: 06:00"
    )
    order = [band["code"] for band in watch.payload["severity"]["bands"]]
    assert order.index(escalated) <= order.index(plain)
    assert inputs["band_before_escalation"] == plain


def test_a_wider_blast_radius_is_never_less_severe(db, watch) -> None:
    order = [band["code"] for band in watch.payload["severity"]["bands"]]
    narrow, _ = incidents.compute_severity(
        watch,
        incidents.BlastRadius(consumers=1, sensitivity_rank=1, products=(), agents=()),
        guarantee_breached=None,
    )
    wide, _ = incidents.compute_severity(
        watch,
        incidents.BlastRadius(consumers=100, sensitivity_rank=3, products=(), agents=()),
        guarantee_breached=None,
    )
    assert order.index(wide) <= order.index(narrow)


# ---------------------------------------------------------------------------
# Owners cannot suppress
# ---------------------------------------------------------------------------


def test_an_owner_can_add_context_and_nothing_else(db, watch) -> None:
    """Section 15.6. Context sits alongside the notification, never instead of it."""
    finding = signals.Finding(
        asset_type=signals.ASSET_PRODUCT, asset_id="DP-TEL-001",
        signal=signals.SIGNAL_FRESHNESS, detail="simulated", observed=Decimal("90"),
        threshold=Decimal("45"), guarantee_breached="freshness: 06:00",
    )
    raised = incidents.raise_incident(db, TENANT, watch, finding)
    before = incidents.banners(db, signals.ASSET_PRODUCT, "DP-TEL-001")

    incidents.add_context(
        db, incident_id=raised["incident_id"],
        owner_context="Upstream vendor feed was late; backfill running.",
    )
    after = incidents.banners(db, signals.ASSET_PRODUCT, "DP-TEL-001")

    assert len(after) == len(before), "context must not remove a banner"
    carried = next(
        row for row in after if row["incident_id"] == raised["incident_id"]
    )
    assert carried["owner_context"].startswith("Upstream vendor feed")

    with db.cursor() as cursor:
        cursor.execute(
            "SELECT notified_at FROM incident WHERE incident_id = %s",
            (raised["incident_id"],),
        )
        assert cursor.fetchone()["notified_at"] is not None


def test_empty_context_is_refused(db, watch) -> None:
    with pytest.raises(incidents.IncidentRefusedError):
        incidents.add_context(db, incident_id="INC-ANY", owner_context="   ")


def test_resolving_without_a_root_cause_is_refused(db, watch) -> None:
    """An incident closed without one leaves the next reader none the wiser."""
    with pytest.raises(incidents.IncidentRefusedError) as error:
        incidents.resolve(db, incident_id="INC-ANY", root_cause="")
    assert "root cause" in str(error.value)


def test_resolving_clears_the_banners(db, watch) -> None:
    finding = signals.Finding(
        asset_type=signals.ASSET_PRODUCT, asset_id="DP-TEL-001",
        signal=signals.SIGNAL_FRESHNESS, detail="simulated", observed=Decimal("90"),
        threshold=Decimal("45"),
    )
    raised = incidents.raise_incident(db, TENANT, watch, finding)
    assert incidents.banners(db, signals.ASSET_PRODUCT, "DP-TEL-001")

    incidents.resolve(
        db, incident_id=raised["incident_id"],
        root_cause="The upstream vendor's 05:00 delivery slipped; SLA renegotiated.",
    )
    remaining = [
        row for row in incidents.banners(db, signals.ASSET_PRODUCT, "DP-TEL-001")
        if row["incident_id"] == raised["incident_id"]
    ]
    assert remaining == []


def test_the_same_signal_twice_in_a_day_is_one_incident(db, watch) -> None:
    """Otherwise the count of open incidents measures how often the scanner ran."""
    finding = signals.Finding(
        asset_type=signals.ASSET_PRODUCT, asset_id="DP-TEL-001",
        signal=signals.SIGNAL_FRESHNESS, detail="simulated", observed=Decimal("90"),
        threshold=Decimal("45"),
    )
    first = incidents.raise_incident(db, TENANT, watch, finding)
    second = incidents.raise_incident(db, TENANT, watch, finding)
    assert first["incident_id"] == second["incident_id"]


# ---------------------------------------------------------------------------
# M10 acceptance: the pack and the dashboard cannot disagree
# ---------------------------------------------------------------------------


def test_the_board_pack_and_the_dashboard_read_one_snapshot(
    db, value_rubric, cost_rubric
) -> None:
    """Tested by moving the data underneath and asserting neither surface moves.

    A test comparing two calls a millisecond apart would pass on an
    implementation that recomputed, which is exactly the implementation the
    criterion forbids.
    """
    since = (datetime.now(UTC) - timedelta(days=30)).date()
    finops.attribute_agent_costs(db, TENANT, cost_rubric, since=since)
    taken = model.snapshot(
        db, TENANT, value_rubric,
        period_start=since, period_end=datetime.now(UTC).date(),
    )
    reference = taken["snapshot_ref"]

    dashboard_before = model.read_snapshot(db, reference)
    pack_before = model.board_pack(db, value_rubric, reference)
    assert dashboard_before, "the snapshot recorded nothing"

    # Move the world: delete a month of answers.
    with db.cursor() as cursor:
        cursor.execute(
            "DELETE FROM answer_feedback WHERE interaction_id IN "
            "(SELECT interaction_id FROM agent_interaction WHERE occurred_at >= %s)",
            (since,),
        )
        cursor.execute("DELETE FROM agent_interaction WHERE occurred_at >= %s", (since,))

    dashboard_after = model.read_snapshot(db, reference)
    pack_after = model.board_pack(db, value_rubric, reference)

    assert dashboard_after == dashboard_before, "the dashboard recomputed"
    assert pack_after["totals"] == pack_before["totals"], "the pack recomputed"
    assert pack_after["rows"] == dashboard_after, "the pack and the dashboard disagree"


def test_the_board_pack_refuses_a_snapshot_that_does_not_exist(db, value_rubric) -> None:
    """It reads a snapshot or it fails. It never computes one to fill the gap."""
    with pytest.raises(LookupError):
        model.board_pack(db, value_rubric, "VSN-NOT-A-SNAPSHOT")


def test_the_rendered_pack_carries_the_snapshot_and_rubric_it_came_from(
    db, value_rubric, cost_rubric
) -> None:
    since = (datetime.now(UTC) - timedelta(days=30)).date()
    finops.attribute_agent_costs(db, TENANT, cost_rubric, since=since)
    taken = model.snapshot(
        db, TENANT, value_rubric, period_start=since,
        period_end=datetime.now(UTC).date(),
    )
    rendered = model.render_board_pack(
        model.board_pack(db, value_rubric, taken["snapshot_ref"])
    )
    assert taken["snapshot_ref"] in rendered
    assert value_rubric.rubric_version_id in rendered
    assert "cannot disagree" in rendered


# ---------------------------------------------------------------------------
# The sample size travels with the figure
# ---------------------------------------------------------------------------


def test_every_deflection_carries_the_sample_sizes_behind_it(db, value_rubric) -> None:
    """Section 15.7: the sample size is displayed next to any figure derived from it.

    So it is on the payload, not a second request away — a caller that has to
    ask for it separately will render the number alone.
    """
    with db.cursor() as cursor:
        cursor.execute("SELECT agent_id FROM agent ORDER BY agent_id LIMIT 1")
        agent_id = cursor.fetchone()["agent_id"]

    document = model.agent_deflection(db, value_rubric, agent_id).document()
    if document["answered"] == 0:
        pytest.skip("no answers to deflect")
    assert document["evidence"], "a deflection with no evidence is a bare number"
    for item in document["evidence"]:
        assert item["sample_size"] > 0
        assert item["dated"]
        assert item["avg_manual_minutes"] > 0


def test_an_unknown_question_class_falls_back_to_reference_data_not_a_constant(
    db, value_rubric
) -> None:
    minutes, sample, dated = model._minutes_for(value_rubric, "a_class_nobody_timed")
    default_minutes, default_sample, _ = model._minutes_for(value_rubric, "default")
    assert minutes == default_minutes
    assert sample == default_sample > 0, "the fallback carries its own sample size"
    assert dated


def test_nothing_rated_means_no_deflection_claimed(db, value_rubric) -> None:
    """Assuming a perfect acceptance rate would be the most flattering guess."""
    with db.cursor() as cursor:
        cursor.execute("DELETE FROM answer_feedback")
        cursor.execute("SELECT agent_id FROM agent ORDER BY agent_id LIMIT 1")
        agent_id = cursor.fetchone()["agent_id"]

    result = model.agent_deflection(db, value_rubric, agent_id)
    assert result.acceptance_rate == Decimal(0)
    assert result.deflected_hours == Decimal(0)


# ---------------------------------------------------------------------------
# Unit economics
# ---------------------------------------------------------------------------


def test_cost_per_accepted_answer_is_never_flattered_by_rejections(
    db, cost_rubric
) -> None:
    """Dividing by the acceptance rate is what makes two agents comparable."""
    for item in finops.unit_economics(db, cost_rubric):
        if item.cost_per_answer_usd is None or item.acceptance_rate == Decimal(0):
            continue
        assert item.cost_per_accepted_answer_usd is not None
        assert item.cost_per_accepted_answer_usd >= item.cost_per_answer_usd


def test_marginal_and_loaded_cost_are_reported_separately(db, cost_rubric) -> None:
    """The declared budget is marginal; comparing it to loaded cost is meaningless."""
    finops.attribute_agent_costs(db, TENANT, cost_rubric)
    reported = [
        item for item in finops.unit_economics(db, cost_rubric)
        if item.cost_per_answer_usd is not None
    ]
    assert reported
    for item in reported:
        assert item.marginal_cost_usd <= item.total_cost_usd
        document = item.document()
        assert document["marginal_cost_per_answer_usd"] is not None
        assert document["cost_per_answer_usd"] is not None


def test_a_used_asset_is_not_a_retirement_candidate(db, cost_rubric) -> None:
    """Reading only product usage marks every agent unused."""
    finops.attribute_agent_costs(db, TENANT, cost_rubric)
    candidates = {row["asset_id"] for row in finops.retirement_candidates(db, cost_rubric)}

    with db.cursor() as cursor:
        cursor.execute(
            "SELECT DISTINCT v.agent_id FROM agent_interaction i "
            "JOIN agent_version v ON v.agent_version_id = i.agent_version_id "
            "WHERE i.occurred_at > now() - interval '7 days'"
        )
        recently_used = {row["agent_id"] for row in cursor.fetchall()}

    assert not (candidates & recently_used), (
        f"agents asked in the last week are not retirement candidates: "
        f"{sorted(candidates & recently_used)}"
    )


def test_a_retirement_candidate_quantifies_the_saving(db, cost_rubric) -> None:
    """"Nobody uses this" is an observation. A number is a decision."""
    for candidate in finops.retirement_candidates(db, cost_rubric):
        assert candidate["annual_cost_usd"] > 0
        assert "a year" in candidate["why"]


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------


def test_every_finding_states_what_it_observed_and_against_what(db, watch) -> None:
    for finding in signals.scan(db, watch):
        document = finding.document()
        assert document["detail"].strip()
        assert document["threshold"] is not None
        assert finding.asset_id in document["detail"]


def test_the_marketplaces_own_runs_do_not_raise_agent_incidents(db, watch) -> None:
    """The contract suite drives the real API and leaves real interactions."""
    before = {
        (finding.asset_id, finding.signal)
        for finding in signals.scan(db, watch, only=[signals.SIGNAL_GROUNDEDNESS])
    }
    with db.cursor() as cursor:
        cursor.execute("SELECT current_version_id FROM agent ORDER BY agent_id LIMIT 1")
        version = cursor.fetchone()["current_version_id"]
        for index in range(3):
            cursor.execute(
                "INSERT INTO agent_interaction (interaction_id, tenant_id, "
                "  agent_version_id, principal_id, session_id, tier, question, "
                "  question_class, outcome, grounded, kpi_definitions, rows_scanned, "
                "  latency_ms, tokens_in, tokens_out, cost_usd) "
                "VALUES (%s, %s, %s, 'PTY-0061', %s, 'demo', 'q', 'ad_hoc', 'ungrounded', "
                "        false, '{}', 0, 1, 0, 0, 0)",
                (
                    f"INT-SYSGRD-{index}", TENANT, version,
                    f"{signals.SYSTEM_SESSION_PREFIX}TEST",
                ),
            )
    after = {
        (finding.asset_id, finding.signal)
        for finding in signals.scan(db, watch, only=[signals.SIGNAL_GROUNDEDNESS])
    }
    assert after == before


def test_every_signal_declares_a_unit():
    """A finding's number is meaningless without the unit it is measured in.

    The unit belongs to the signal, so the mapping is exhaustive over the
    signals the scan runs — a new detector without a unit is a column of bare
    decimals on the health plane, and this is where that is caught.
    """
    for signal in signals.PRODUCT_SIGNALS + signals.AGENT_SIGNALS:
        assert signal in signals.UNIT_BY_SIGNAL


def test_a_finding_carries_its_unit_into_the_payload():
    finding = signals.Finding(
        asset_type=signals.ASSET_PRODUCT,
        asset_id="DP-TEST-001",
        signal=signals.SIGNAL_ACCESS,
        detail="a denial rate",
        observed=Decimal("0.07"),
        threshold=Decimal("0.05"),
    )
    assert finding.document()["unit"] == signals.UNIT_FRACTION
