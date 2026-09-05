"""One generator specification per seed product.

Each spec says how the product's demo tier is laid out and — the part that
matters — plants the pattern its curated questions are meant to discover. A
generator that produced uniform noise would make every golden answer "no
material difference", which proves nothing about the agent.

The planted patterns are declared in the product manifests under
``demo_tier.planted_patterns``; the expressions here are how they are realised.
"""

from __future__ import annotations

from seed.synthetic.framework import (
    ProductSpec,
    pick,
    rnd,
    seasonal,
    uniform,
    weighted,
)

E = "entity::text"
P = "period::text"


def k(name: str) -> str:
    """A SQL string literal, used as a hash key so each column draws independently."""
    return "'" + name + "'"


def _spec(product_id: str, **kwargs) -> ProductSpec:
    return ProductSpec(product_id=product_id, **kwargs)


# ---------------------------------------------------------------------------
# DP-TEL-001 — Subscriber Churn & Retention 360
#
# Planted: churn concentrates in the 13-24 month tenure band in the Midwest,
# and subscribers with three or more network incidents churn at roughly twice
# the base rate. Both are what makes questions 2 and 3 answerable.
# ---------------------------------------------------------------------------
TEL_001_REGIONS = [("Midwest", 3), ("Northeast", 2), ("South", 2), ("West", 2)]
TEL_001_SEGMENTS = [("consumer", 6), ("small_business", 2), ("enterprise", 1)]
TEL_001_TENURE = "(CASE WHEN tenure_days < 365 THEN '0-12m' WHEN tenure_days < 730 THEN '13-24m' WHEN tenure_days < 1460 THEN '25-48m' ELSE '49m+' END)"

DP_TEL_001 = _spec(
    "DP-TEL-001",
    entity_column="subscriber_id", entity_count=2100,
    time_column="activity_date", grain="day", periods=120,
    expressions={
        "account_id": "('ACCT-' || lpad((entity / 2)::text, 7, '0'))",
        "activity_date": "period_at::date",
        "segment": weighted(TEL_001_SEGMENTS, E),
        "region": weighted(TEL_001_REGIONS, E),
        "plan_type": weighted([("unlimited", 4), ("tiered", 3), ("legacy", 1)], E),
        "tenure_days": f"(30 + floor({rnd(E, k('ten'))} * 2100))::int",
        "tenure_band": TEL_001_TENURE,
        "channel": pick(["retail", "digital", "partner", "care"], E, k('ch')),
        "active_at_period_start": "true",
        # The concentration: 13-24 month tenure in the Midwest churns hardest,
        # and network incidents roughly double the base rate.
        #
        # The base is per subscriber-day and is set so the monthly rate lands
        # near KPI-CHURN-001's own target of 1.4%. It was ten times higher, which
        # made the planted patterns easy to see and made every headline the
        # telecom agent produced — 14% monthly churn — obviously wrong to anyone
        # who works in telecom. A demo whose numbers are implausible teaches the
        # reader to stop reading the numbers, which is the opposite of the point.
        "churn_flag": (
            f"({rnd(E, P, k('churn'))} < "
            "  0.00013"
            f"  * (CASE WHEN {TEL_001_TENURE} = '13-24m' THEN 3.4 ELSE 1.0 END)"
            f"  * (CASE WHEN {weighted(TEL_001_REGIONS, E)} = 'Midwest' THEN 2.1 ELSE 1.0 END)"
            "  * (CASE WHEN network_incidents_30d >= 3 THEN 2.0 ELSE 1.0 END)"
            f"  * (1 + {seasonal(0.4, 'period', 30)})"
            ")"
        ),
        "churn_reason_code": (
            f"(CASE WHEN {rnd(E, P, k('reason'))} < 0.4 THEN 'price' "
            f"      WHEN {rnd(E, P, k('reason'))} < 0.7 THEN 'network' "
            "       ELSE 'competitor' END)"
        ),
        "save_offer_made": f"({rnd(E, P, k('offer'))} < 0.02)",
        "save_offer_accepted": (
            f"(save_offer_made AND {rnd(E, P, k('accept'))} < "
            f" (0.30 + 0.25 * (CASE WHEN propensity_decile <= 3 THEN 1 ELSE 0 END)))"
        ),
        "churn_propensity_score": f"round(({rnd(E, P, k('prop'))} * 0.6)::numeric, 4)",
        "propensity_decile": (
            f"(1 + floor({rnd(E, P, k('prop'))} * 10))::int"
        ),
        "ltv": f"round({uniform(180, 2400, E)}::numeric, 2)",
        "contract_end_date": (
            f"(period_at + ((30 + floor({rnd(E, k('contract'))} * 700))::int || ' days')"
            "::interval)::date"
        ),
        "care_contacts_30d": f"floor({rnd(E, P, k('care'))} * 5)::int",
        "network_incidents_30d": (
            f"floor({rnd(E, P, k('inc'))} * "
            f" (CASE WHEN {weighted(TEL_001_REGIONS, E)} = 'Midwest' THEN 7 ELSE 4 END))::int"
        ),
    },
    notes="churn concentrated in 13-24m tenure in the Midwest; incidents double the rate",
)

# ---------------------------------------------------------------------------
# DP-TEL-002 — Network Experience & Fault Signal
# Planted: a sustained throughput drop in Denver on two site classes, and a
# small set of sites carrying repeat faults of the same class.
# ---------------------------------------------------------------------------
TEL_002_REGIONS = [("Denver", 2), ("Midwest", 3), ("Northeast", 3), ("West", 2)]

DP_TEL_002 = _spec(
    "DP-TEL-002",
    entity_column="site_id", entity_count=900,
    time_column="observed_hour", grain="hour", periods=168,
    expressions={
        "site_id": "('SITE-' || lpad(entity::text, 6, '0'))",
        "observed_hour": "period_at",
        "region": weighted(TEL_002_REGIONS, E),
        "site_class": weighted([("urban", 4), ("suburban", 3), ("rural", 2)], E),
        "technology": weighted([("5g", 5), ("4g", 4), ("fixed_wireless", 1)], E),
        "scheduled_minutes": "60",
        "available_minutes": (
            f"least(60, (60 * (0.985 + 0.015 * {rnd(E, P, k('avail'))})))::int"
        ),
        "established_calls": f"(50 + floor({rnd(E, P, k('calls'))} * 400))::int",
        "dropped_calls": (
            f"floor(established_calls * (0.004 + 0.010 * {rnd(E, P, k('drop'))}))::int"
        ),
        # The Denver drop: two site classes lose roughly a third of throughput
        # part-way through the window, which is only visible when segmented.
        "throughput_mbps": (
            f"round((85 * (0.7 + 0.6 * {rnd(E, P, k('tp'))})"
            f"  * (CASE WHEN {weighted(TEL_002_REGIONS, E)} = 'Denver'"
            "         AND period > 96"
            f"        AND {weighted([('urban', 4), ('suburban', 3), ('rural', 2)], E)}"
            "            IN ('urban','suburban')"
            "       THEN 0.62 ELSE 1.0 END))::numeric, 2)"
        ),
        # Repeat faults: a tenth of sites carry the same fault class repeatedly.
        "fault_class": (
            f"(CASE WHEN {rnd(E, k('repeat'))} < 0.10 "
            f"      THEN {pick(['power', 'backhaul'], E, k('rf'))} "
            f"      ELSE {pick(['power', 'backhaul', 'radio', 'transport', 'software'], E, P, k('fc'))} "
            " END)"
        ),
        "fault_closed": (
            f"({rnd(E, P, k('closed'))} < "
            f" (CASE WHEN {rnd(E, k('repeat'))} < 0.10 THEN 0.22 ELSE 0.06 END))"
        ),
        "restore_minutes": (
            f"(CASE WHEN fault_closed THEN (30 + floor({rnd(E, P, k('rest'))} * 600))::int END)"
        ),
        "impacted_subscribers": f"(120 + floor({rnd(E, k('subs'))} * 3200))::int",
        "outage_hours": f"round(({rnd(E, P, k('out'))} * 0.08)::numeric, 4)",
        "impacted_subscriber_hours": "round((impacted_subscribers * outage_hours)::numeric, 2)",
    },
    notes="Denver throughput drop on urban/suburban after period 96; repeat faults on 10% of sites",
)

# ---------------------------------------------------------------------------
# DP-TCH-001 — Product Usage & Feature Adoption
# Planted: two features carry the activation lift, and a set of features is used
# by accounts whose plan does not entitle them.
# ---------------------------------------------------------------------------
TCH_FEATURES = [
    "guided_onboarding", "shared_workspaces", "automations", "api_access",
    "advanced_reporting", "sso", "audit_log", "mobile_offline",
]
LIFT_FEATURES = "('guided_onboarding','shared_workspaces')"
UNENTITLED_FEATURES = "('advanced_reporting','sso')"

DP_TCH_001 = _spec(
    "DP-TCH-001",
    entity_column="account_id", entity_count=700,
    time_column="activity_date", grain="day", periods=90,
    fan_out=("feature", TCH_FEATURES),
    expressions={
        "account_id": "('ACC-' || lpad(entity::text, 6, '0'))",
        "feature": "fan_value",
        "activity_date": "period_at::date",
        "plan_tier": weighted([("starter", 4), ("growth", 4), ("enterprise", 2)], E),
        "segment": weighted([("smb", 5), ("mid_market", 3), ("enterprise", 2)], E),
        "region": pick(["NA", "EMEA", "APAC"], E, k('reg')),
        "acquisition_channel": weighted(
            [("self_serve", 5), ("sales_led", 3), ("partner", 2)], E, k('acq')
        ),
        "feature_entitled": (
            f"(CASE WHEN fan_value IN {UNENTITLED_FEATURES} "
            f"      THEN {weighted([('starter', 4), ('growth', 4), ('enterprise', 2)], E)}"
            "            = 'enterprise' "
            "      ELSE true END)"
        ),
        "feature_used": (
            f"({rnd(E, P, 'fan_value', k('use'))} < "
            "  (CASE WHEN fan_value IN " + UNENTITLED_FEATURES + " THEN 0.34 ELSE 0.22 END))"
        ),
        "daily_active_account": (
            f"(CASE WHEN {rnd(E, P, k('dau'))} < 0.42 "
            "      THEN ('ACC-' || lpad(entity::text, 6, '0')) END)"
        ),
        "monthly_active_account": "('ACC-' || lpad(entity::text, 6, '0'))",
        "onboarded": "true",
        # The activation lift: accounts that used either lift feature activate
        # far more often, and the March change lifts the later cohort.
        "activated": (
            f"({rnd(E, k('act'))} < "
            f"  (0.42 + 0.34 * (CASE WHEN fan_value IN {LIFT_FEATURES} THEN 1 ELSE 0 END)"
            "        + 0.12 * (CASE WHEN period > 45 THEN 1 ELSE 0 END)))"
        ),
        "days_to_first_value": (
            f"(4 + floor({rnd(E, k('ttv'))} * "
            f"  (CASE WHEN {weighted([('self_serve', 5), ('sales_led', 3), ('partner', 2)], E, k('acq'))}"
            "         = 'self_serve' THEN 12 ELSE 42 END)))::int"
        ),
        "starting_recurring_revenue": f"round({uniform(4000, 90000, E)}::numeric, 2)",
        "ending_recurring_revenue": (
            f"round((starting_recurring_revenue * (0.92 + 0.28 * {rnd(E, P, k('nrr'))}))::numeric, 2)"
        ),
        "renewal_date": (
            f"(period_at + ((10 + floor({rnd(E, k('ren'))} * 300))::int || ' days')::interval)::date"
        ),
    },
    notes="two features carry the activation lift; two are used beyond entitlement",
)


# ---------------------------------------------------------------------------
# DP-BNK-001 — Customer Financial 360
# Planted: relationship value concentrates in a few Southeast households, and
# deposit balances shift measurably after the April rate change.
# ---------------------------------------------------------------------------
BNK_REGIONS = [("Southeast", 3), ("Northeast", 3), ("Midwest", 2), ("West", 2)]
BNK_SEGMENTS = [("mass", 6), ("affluent", 3), ("private", 1)]
RATE_CHANGE_PERIOD = 18

DP_BNK_001 = _spec(
    "DP-BNK-001",
    entity_column="customer_id", entity_count=5000,
    time_column="as_of_month", grain="month", periods=36,
    expressions={
        "customer_id": "('CUST-' || lpad(entity::text, 7, '0'))",
        "household_id": "('HH-' || lpad((entity / 2)::text, 7, '0'))",
        "as_of_month": "date_trunc('month', period_at)::date",
        "segment": weighted(BNK_SEGMENTS, E),
        "region": weighted(BNK_REGIONS, E),
        "tenure_band": pick(["0-2y", "3-5y", "6-10y", "10y+"], E, k("ten")),
        "value_band": (
            "(CASE WHEN relationship_value > 4000 THEN 'top' "
            "      WHEN relationship_value > 1200 THEN 'upper' ELSE 'core' END)"
        ),
        "product_family": weighted(
            [("deposits", 5), ("lending", 3), ("wealth", 2)], E, k("pf")
        ),
        "active_product_count": f"(1 + floor({rnd(E, k('prod'))} * 6))::int",
        "primary_relationship": f"({rnd(E, k('primary'))} < 0.61)",
        "starting_deposit_balance": f"round({uniform(500, 180000, E, k('bal'))}::numeric, 2)",
        # The rate change: balances step up from the change month onward, more
        # sharply in the affluent segment.
        "ending_deposit_balance": (
            "round((starting_deposit_balance * "
            f" (1 + 0.004 * {rnd(E, P, k('drift'))}"
            f"    + (CASE WHEN period > {RATE_CHANGE_PERIOD} THEN "
            f"         0.035 + 0.05 * (CASE WHEN {weighted(BNK_SEGMENTS, E)} = 'affluent' "
            "                            THEN 1 ELSE 0 END) "
            "       ELSE 0 END)))::numeric, 2)"
        ),
        # The concentration: a small share of Southeast households hold outsized value.
        "relationship_value": (
            f"round(({uniform(120, 2600, E, k('rv'))} * "
            f"  (CASE WHEN {weighted(BNK_REGIONS, E)} = 'Southeast' "
            f"        AND {rnd(E, k('whale'))} < 0.04 THEN 9.5 ELSE 1.0 END))::numeric, 2)"
        ),
        "discounted_contribution_margin": "round((relationship_value * 3.4)::numeric, 2)",
        "attrition_model_score": (
            f"round(({rnd(E, P, k('risk'))} * 100 * "
            "  (CASE WHEN active_product_count = 1 THEN 1.4 ELSE 0.8 END))::numeric, 2)"
        ),
        "last_contact_date": (
            f"(period_at - ((floor({rnd(E, P, k('contact'))} * 300))::int || ' days')"
            "::interval)::date"
        ),
    },
    notes="value concentrated in a few Southeast households; balances step up after month 18",
)

# ---------------------------------------------------------------------------
# DP-BNK-002 — Transaction Surveillance & Financial Crime Signal
# Planted: one structuring typology has a far higher false positive rate, and
# SAR conversion moves after the June rule tuning.
# ---------------------------------------------------------------------------
TYPOLOGIES = [("structuring", 4), ("rapid_movement", 3), ("sanctions_proximity", 1),
              ("trade_based", 1), ("mule_network", 2)]
TUNING_PERIOD = 60

DP_BNK_002 = _spec(
    "DP-BNK-002",
    entity_column="alert_id", entity_count=1600,
    time_column="event_timestamp", grain="day", periods=90,
    expressions={
        "alert_id": "('ALERT-' || lpad(entity::text, 7, '0') || '-' || period::text)",
        "event_timestamp": "period_at",
        "typology": weighted(TYPOLOGIES, E),
        "rule_id": (
            f"('RULE-' || (CASE WHEN period > {TUNING_PERIOD} THEN 'v2-' ELSE 'v1-' END) || "
            f" (1 + floor({rnd(E, k('rule'))} * 6))::int::text)"
        ),
        "business_line": weighted([("retail", 5), ("commercial", 3), ("wealth", 2)], E),
        "region": pick(["US-East", "US-West", "EU", "APAC"], E, k("reg")),
        "investigator_team": weighted(
            [("team_alpha", 4), ("team_bravo", 3), ("team_charlie", 3)], E, k("team")
        ),
        # The efficiency spread: structuring produces most of the no-action work.
        "disposition": (
            f"(CASE WHEN {rnd(E, P, k('open'))} < 0.18 THEN NULL "
            f"      WHEN {rnd(E, P, k('disp'))} < "
            f"        (CASE WHEN {weighted(TYPOLOGIES, E)} = 'structuring' THEN 0.97 "
            "              ELSE 0.88 END) THEN 'no_further_action' "
            "      ELSE 'escalated' END)"
        ),
        # The tuning effect: conversion is higher for alerts raised by v2 rules.
        "sar_filed": (
            "(disposition = 'escalated' AND "
            f" {rnd(E, P, k('sar'))} < "
            f" (CASE WHEN period > {TUNING_PERIOD} THEN 0.42 ELSE 0.19 END))"
        ),
        "investigation_days": (
            f"(CASE WHEN disposition IS NOT NULL "
            f"      THEN round((1 + {rnd(E, P, k('cyc'))} * 30)::numeric, 2) END)"
        ),
        "age_days": (
            f"(CASE WHEN disposition IS NULL "
            f"      THEN round((1 + {rnd(E, P, k('age'))} * 70)::numeric, 2) "
            "       ELSE round((1 + " + rnd(E, P, k("age")) + " * 20)::numeric, 2) END)"
        ),
        "alert_score": f"round(({rnd(E, P, k('score'))} * 100)::numeric, 2)",
        "customer_risk_rating": weighted(
            [("low", 5), ("medium", 3), ("high", 2)], E, k("crr")
        ),
        "transaction_count": f"(1 + floor({rnd(E, P, k('txn'))} * 40))::int",
        "transaction_value": f"round({uniform(500, 250000, E, P, k('val'))}::numeric, 2)",
    },
    notes="structuring carries the false-positive tail; SAR conversion rises after the tuning",
)

# ---------------------------------------------------------------------------
# DP-INS-001 — Claims Lifecycle & Loss Performance
# Planted: auto physical damage accumulates cycle time at vendor assignment, and
# a share of eligible claims never opens a subrogation file.
# ---------------------------------------------------------------------------
COVERAGE_LINES = [("auto_physical_damage", 4), ("auto_liability", 3), ("property", 3),
                  ("general_liability", 2)]
CLAIM_STATUSES = ["fnol", "assigned", "vendor_assigned", "estimated", "settled", "closed"]
TRIAGE_CHANGE_PERIOD = 45

DP_INS_001 = _spec(
    "DP-INS-001",
    entity_column="claim_id", entity_count=1400,
    time_column="transition_timestamp", grain="day", periods=90,
    expressions={
        "claim_id": "('CLM-' || lpad(entity::text, 7, '0'))",
        "policy_id": "('POL-' || lpad((entity * 3)::text, 7, '0'))",
        "transition_timestamp": "period_at",
        "coverage_line": weighted(COVERAGE_LINES, E),
        "region": pick(["Northeast", "Southeast", "Midwest", "West"], E, k("reg")),
        "channel": weighted([("agent", 4), ("direct", 3), ("broker", 3)], E, k("ch")),
        "complexity_band": weighted([("low", 5), ("medium", 3), ("high", 2)], E, k("cx")),
        "adjuster_team": pick(["team_north", "team_south", "team_central"], E, k("team")),
        "claim_status": pick(CLAIM_STATUSES, E, P, k("status")),
        "incurred_losses": f"round({uniform(400, 42000, E, k('loss'))}::numeric, 2)",
        # Premium is drawn wide enough to sit above losses. The range was
        # originally picked beside the loss range rather than against it, which
        # put the book's loss ratio at 157% — a number no insurer survives, and
        # one nothing read until an agent covered KPI-LOSSRATIO-026.
        "earned_premium": f"round({uniform(4000, 64000, E, k('prem'))}::numeric, 2)",
        # The decomposition: auto physical damage sits far longer at vendor
        # assignment, which is where the extra days come from.
        "cycle_days": (
            f"round((6 + {rnd(E, k('cyc'))} * 30 "
            f"  + (CASE WHEN {weighted(COVERAGE_LINES, E)} = 'auto_physical_damage' "
            f"           AND {pick(CLAIM_STATUSES, E, P, k('status'))} = 'vendor_assigned' "
            "          THEN 22 ELSE 0 END))::numeric, 2)"
        ),
        "assessed_leakage_amount": (
            f"round((incurred_losses * (0.0 + 0.09 * {rnd(E, k('leak'))} "
            f"  * (CASE WHEN {weighted(COVERAGE_LINES, E)} = 'auto_physical_damage' "
            "         THEN 1.9 ELSE 1.0 END)))::numeric, 2)"
        ),
        # The recovery gap: most eligible claims never open a subrogation file.
        "subrogation_recovered": (
            f"(CASE WHEN {rnd(E, k('subro'))} < 0.17 "
            "       THEN round((incurred_losses * 0.22)::numeric, 2) ELSE 0 END)"
        ),
        "salvage_recovered": (
            f"(CASE WHEN {rnd(E, k('salv'))} < 0.11 "
            "       THEN round((incurred_losses * 0.08)::numeric, 2) ELSE 0 END)"
        ),
        "settlement_amount": "round((incurred_losses * 0.88)::numeric, 2)",
        "triage_rule_version": (
            f"(CASE WHEN period > {TRIAGE_CHANGE_PERIOD} THEN 'triage-v3' ELSE 'triage-v2' END)"
        ),
    },
    notes="APD accumulates cycle time at vendor assignment; most eligible subrogation unopened",
)


# ---------------------------------------------------------------------------
# DP-INS-002 — Policy & Underwriting Portfolio
# Planted: one commercial property segment is priced below technical, and wind
# exposure piles up in a handful of coastal counties.
# ---------------------------------------------------------------------------
INS_SEGMENTS = [("commercial_property", 4), ("commercial_auto", 3), ("small_commercial", 3)]
PERILS = ["wind", "flood", "fire", "hail"]
COASTAL_COUNTIES = "('Beaufort','Galveston','Monmouth')"
INS_COUNTIES = ["Beaufort", "Galveston", "Monmouth", "Marion", "Delaware", "Sussex", "Douglas"]
RATE_CHANGE_MONTH = 20

DP_INS_002 = _spec(
    "DP-INS-002",
    entity_column="policy_id", entity_count=1200,
    time_column="as_of_month", grain="month", periods=36,
    fan_out=("peril", PERILS),
    expressions={
        "policy_id": "('POL-' || lpad(entity::text, 7, '0'))",
        "quote_id": "('QTE-' || lpad(entity::text, 7, '0'))",
        "as_of_month": "date_trunc('month', period_at)::date",
        "coverage_line": weighted([("property", 4), ("casualty", 3), ("auto", 3)], E),
        "segment": weighted(INS_SEGMENTS, E),
        "region": pick(["Northeast", "Southeast", "Gulf", "Midwest"], E, k("reg")),
        "county": pick(INS_COUNTIES, E, k("county")),
        "channel": weighted([("broker", 5), ("agent", 3), ("direct", 2)], E, k("ch")),
        "peril": "fan_value",
        "written_premium": f"round({uniform(1200, 90000, E, k('wp'))}::numeric, 2)",
        "technical_premium": f"round({uniform(1400, 88000, E, k('tp'))}::numeric, 2)",
        # The adequacy gap: commercial property is charged below technical.
        "charged_premium": (
            "round((technical_premium * "
            f" (0.98 + 0.14 * {rnd(E, k('adq'))} "
            f"  - (CASE WHEN {weighted(INS_SEGMENTS, E)} = 'commercial_property' "
            "          THEN 0.13 ELSE 0 END)))::numeric, 2)"
        ),
        # The accumulation: wind exposure concentrates on three coastal counties.
        "total_insured_value": (
            f"round(({uniform(80000, 4200000, E, k('tiv'))} * "
            "  (CASE WHEN fan_value = 'wind' AND "
            f"        {pick(INS_COUNTIES, E, k('county'))} IN {COASTAL_COUNTIES} "
            "        THEN 4.2 ELSE 1.0 END))::numeric, 2)"
        ),
        "in_top_accumulation_zone": (
            f"(fan_value = 'wind' AND {pick(INS_COUNTIES, E, k('county'))} "
            f"  IN {COASTAL_COUNTIES})"
        ),
        "up_for_renewal": f"({rnd(E, P, k('due'))} < 0.09)",
        "renewed": (
            f"(up_for_renewal AND {rnd(E, P, k('ren'))} < "
            f" (0.90 - 0.9 * greatest(rate_change_pct, 0) "
            f"  - (CASE WHEN {weighted(INS_SEGMENTS, E)} = 'small_commercial' "
            "          THEN 0.08 ELSE 0 END)))"
        ),
        "bound": f"({rnd(E, k('bind'))} < (CASE WHEN period > {RATE_CHANGE_MONTH} "
                 "  THEN 0.17 ELSE 0.24 END))",
        "rate_change_pct": (
            f"round(((CASE WHEN period > {RATE_CHANGE_MONTH} THEN 0.05 ELSE 0.0 END) "
            f"  + 0.04 * {rnd(E, P, k('rate'))})::numeric, 4)"
        ),
    },
    notes="commercial property priced below technical; wind exposure on three coastal counties",
)

# ---------------------------------------------------------------------------
# DP-HLT-001 — Patient Care Journey & Readmission
# Planted: readmissions concentrate in two conditions on three units, follow-up
# compliance differs sharply by discharge disposition, and the transitional care
# programme measurably reduces readmission in the enrolled cohort.
# ---------------------------------------------------------------------------
CONDITIONS = [("heart_failure", 4), ("copd", 3), ("pneumonia", 3), ("sepsis", 2),
              ("hip_replacement", 2)]
HIGH_READMIT = "('heart_failure','copd')"
UNITS = ["cardiology", "pulmonary", "general_medicine", "surgical", "geriatrics"]
HIGH_UNITS = "('cardiology','pulmonary','geriatrics')"
DISPOSITIONS = ["home", "home_health", "skilled_nursing", "hospice"]

DP_HLT_001 = _spec(
    "DP-HLT-001",
    entity_column="encounter_id", entity_count=2600,
    time_column="discharge_date", grain="day", periods=120,
    expressions={
        "encounter_id": "('ENC-' || lpad(entity::text, 7, '0') || '-' || period::text)",
        "index_encounter_id": "('ENC-' || lpad(entity::text, 7, '0') || '-' || period::text)",
        "attributed_member_id": "('MBR-' || lpad(entity::text, 7, '0'))",
        "ed_encounter_id": (
            f"(CASE WHEN {rnd(E, P, k('ed'))} < 0.22 "
            "       THEN ('ED-' || lpad(entity::text, 7, '0') || '-' || period::text) END)"
        ),
        "discharge_date": "period_at::date",
        "condition": weighted(CONDITIONS, E, P),
        "unit": pick(UNITS, E, P, k("unit")),
        "payer": weighted([("medicare", 4), ("commercial", 3), ("medicaid", 2), ("self", 1)],
                          E, k("payer")),
        "region": pick(["North", "Central", "South"], E, k("reg")),
        "clinic": pick(["clinic_a", "clinic_b", "clinic_c", "clinic_d"], E, k("clinic")),
        "measure": pick(["hba1c", "bp_control", "med_reconciliation", "follow_up"],
                        E, P, k("measure")),
        "discharge_disposition": weighted(
            [("home", 5), ("home_health", 3), ("skilled_nursing", 2), ("hospice", 1)],
            E, P, k("disp")
        ),
        "eligible_index": f"({rnd(E, P, k('elig'))} < 0.86)",
        # The concentration, the association and the programme effect, together.
        "readmitted_within_30d": (
            "(eligible_index AND "
            f" {rnd(E, P, k('readmit'))} < "
            f"  (0.072 * (CASE WHEN {weighted(CONDITIONS, E, P)} IN {HIGH_READMIT} "
            "                 THEN 2.3 ELSE 1.0 END)"
            f"        * (CASE WHEN {pick(UNITS, E, P, k('unit'))} IN {HIGH_UNITS} "
            "                 THEN 1.5 ELSE 1.0 END)"
            "         * (CASE WHEN discharge_disposition = 'skilled_nursing' THEN 1.8 "
            "                 WHEN discharge_disposition = 'home' THEN 0.7 ELSE 1.0 END)"
            "         * (CASE WHEN programme_enrolled THEN 0.55 ELSE 1.0 END)))"
        ),
        "inpatient_days": f"round((1 + {rnd(E, P, k('los'))} * 11)::numeric, 2)",
        # Follow-up compliance differs by where the patient went.
        "days_to_followup": (
            f"round((2 + {rnd(E, P, k('fu'))} * "
            "  (CASE WHEN discharge_disposition = 'home' THEN 8 "
            "        WHEN discharge_disposition = 'home_health' THEN 12 ELSE 26 END))::numeric, 2)"
        ),
        "gap_open_at_period_start": f"({rnd(E, P, k('gap'))} < 0.34)",
        "gap_closed": (
            f"(gap_open_at_period_start AND {rnd(E, P, k('close'))} < 0.78)"
        ),
        "programme_enrolled": (
            f"({pick(UNITS, E, P, k('unit'))} IN ('cardiology','pulmonary') "
            f" AND {rnd(E, P, k('prog'))} < 0.45)"
        ),
    },
    notes="two conditions on three units drive readmission; the programme halves it when enrolled",
)

# ---------------------------------------------------------------------------
# DP-HLT-002 — Pharmacy & Clinical Supply Utilization
# Planted: waste concentrates in short-dated high-cost items at two facilities,
# and a stable set of items sits at or below reorder point with live demand.
# ---------------------------------------------------------------------------
FACILITIES = ["north_campus", "south_campus", "west_clinic", "east_clinic"]
WASTE_FACILITIES = "('north_campus','south_campus')"
THERAPEUTIC = [("oncology", 3), ("anti_infective", 4), ("cardiovascular", 3),
               ("analgesia", 3), ("immunology", 2)]

DP_HLT_002 = _spec(
    "DP-HLT-002",
    entity_column="item_id", entity_count=850,
    time_column="activity_date", grain="day", periods=90,
    fan_out=("facility", FACILITIES),
    expressions={
        "item_id": "('ITEM-' || lpad(entity::text, 6, '0'))",
        "facility": "fan_value",
        "activity_date": "period_at::date",
        "therapeutic_class": weighted(THERAPEUTIC, E),
        "item_class": weighted(
            [("standard", 5), ("high_cost", 2), ("short_dated", 2), ("cold_chain", 1)], E,
            k("ic")
        ),
        "service_line": pick(["medicine", "surgery", "critical_care", "ambulatory"], E, k("sl")),
        "on_formulary": (
            f"({rnd(E, P, k('form'))} < "
            "  (CASE WHEN fan_value IN ('west_clinic','east_clinic') THEN 0.86 ELSE 0.96 END))"
        ),
        "substitution_eligible": f"({rnd(E, k('subel'))} < 0.31)",
        "substituted": f"(substitution_eligible AND {rnd(E, P, k('sub'))} < 0.22)",
        # The at-risk list: a stable tenth of items sit at or below reorder point.
        "on_hand_units": (
            f"round((CASE WHEN {rnd(E, k('risky'))} < 0.10 "
            f"            THEN {rnd(E, P, k('low'))} * 6 "
            f"            ELSE 40 + {rnd(E, P, k('oh'))} * 600 END)::numeric, 2)"
        ),
        "demand_units": f"round((2 + {rnd(E, P, k('dem'))} * 45)::numeric, 2)",
        "dispensed_cost": (
            f"round(((10 + {rnd(E, P, k('cost'))} * 400) * "
            f"  (CASE WHEN {weighted(THERAPEUTIC, E)} = 'oncology' THEN 9.0 ELSE 1.0 END)"
            "  )::numeric, 2)"
        ),
        # The waste Pareto: short-dated high-cost stock at two facilities.
        "wasted_cost": (
            "round((dispensed_cost * "
            f" (0.004 + 0.05 * {rnd(E, P, k('waste'))} * "
            f"  (CASE WHEN {weighted([('standard', 5), ('high_cost', 2), ('short_dated', 2), ('cold_chain', 1)], E, k('ic'))}"
            "           IN ('short_dated','high_cost') "
            f"        AND fan_value IN {WASTE_FACILITIES} THEN 7.5 ELSE 1.0 END)))::numeric, 2)"
        ),
        "patient_days": f"round((30 + {rnd(E, P, k('pd'))} * 400)::numeric, 2)",
        "days_to_expiry": (
            f"(CASE WHEN {weighted([('standard', 5), ('high_cost', 2), ('short_dated', 2), ('cold_chain', 1)], E, k('ic'))}"
            f"        = 'short_dated' THEN (3 + floor({rnd(E, P, k('exp'))} * 25))::int "
            f"      ELSE (60 + floor({rnd(E, P, k('exp'))} * 500))::int END)"
        ),
        "reorder_point": f"round((20 + {rnd(E, k('rop'))} * 120)::numeric, 2)",
    },
    notes="waste concentrated in short-dated and high-cost stock at two facilities",
)


# ---------------------------------------------------------------------------
# DP-RTL-001 — Omnichannel Sales & Basket Analytics
# Planted: two categories miss plan for different reasons (traffic in one,
# basket in the other), the back-to-school promotion is margin-dilutive, and a
# complementary category leaves the basket.
# ---------------------------------------------------------------------------
RTL_CATEGORIES = [("apparel", 4), ("home", 3), ("electronics", 3), ("grocery", 4),
                  ("beauty", 2), ("toys", 2)]
MISSING_PLAN = "('electronics','home')"
DILUTIVE_PROMOTION = "back_to_school"
LEAVING_BASKET = "beauty"

DP_RTL_001 = _spec(
    "DP-RTL-001",
    entity_column="transaction_id", entity_count=2600,
    time_column="business_date", grain="day", periods=90,
    expressions={
        "transaction_id": "('TXN-' || lpad(entity::text, 8, '0') || '-' || period::text)",
        "visit_id": "('VIS-' || lpad(entity::text, 8, '0') || '-' || period::text)",
        "business_date": "period_at::date",
        "category": weighted(RTL_CATEGORIES, E, P),
        "sku": f"('SKU-' || lpad((1 + floor({rnd(E, P, k('sku'))} * 4000))::int::text, 6, '0'))",
        "region": pick(["North", "South", "East", "West"], E, k("reg")),
        "channel": weighted([("store", 6), ("digital", 3), ("marketplace", 1)], E, P, k("ch")),
        "store_format": weighted([("large", 3), ("compact", 4), ("express", 3)], E, k("fmt")),
        "promotion": (
            f"(CASE WHEN {rnd(E, P, k('promo'))} < 0.16 "
            f"      THEN {pick([DILUTIVE_PROMOTION, 'spring_event', 'clearance'], E, P, k('pname'))}"
            "       END)"
        ),
        "comparable_store": f"({rnd(E, k('comp'))} < 0.92)",
        "net_sales": (
            f"round(((6 + {rnd(E, P, k('sales'))} * 120) * "
            f"  (1 + {seasonal(0.25, 'period', 7)}))::numeric, 2)"
        ),
        # The plan miss: two categories are below their prior year.
        "prior_year_net_sales": (
            "round((net_sales * "
            f" (CASE WHEN {weighted(RTL_CATEGORIES, E, P)} IN {MISSING_PLAN} "
            f"       THEN 1.09 + 0.05 * {rnd(E, P, k('ly'))} "
            f"       ELSE 0.94 + 0.05 * {rnd(E, P, k('ly'))} END))::numeric, 2)"
        ),
        # The dilutive promotion: back-to-school sells at a much thinner margin.
        "cost_of_goods_sold": (
            "round((net_sales * "
            f" (0.60 + 0.06 * {rnd(E, P, k('cogs'))} "
            f"  + (CASE WHEN {pick([DILUTIVE_PROMOTION, 'spring_event', 'clearance'], E, P, k('pname'))}"
            f"           = '{DILUTIVE_PROMOTION}' AND {rnd(E, P, k('promo'))} < 0.16 "
            "          THEN 0.26 ELSE 0 END)))::numeric, 2)"
        ),
        "promoted_sales": "(CASE WHEN promotion IS NOT NULL THEN net_sales END)",
        "baseline_sales": (
            "(CASE WHEN promotion IS NOT NULL "
            f"      THEN round((net_sales * (0.80 + 0.15 * {rnd(E, P, k('base'))}))::numeric, 2) "
            " END)"
        ),
        "units": f"(1 + floor({rnd(E, P, k('units'))} * 6))::int",
        # The basket shift: beauty leaves the basket in the second half.
        "basket_item_count": (
            f"(1 + floor({rnd(E, P, k('basket'))} * 7 "
            f"  - (CASE WHEN {weighted(RTL_CATEGORIES, E, P)} = '{LEAVING_BASKET}' "
            "          AND period > 45 THEN 2 ELSE 0 END)))::int"
        ),
    },
    notes="electronics and home miss plan; back-to-school is margin dilutive; beauty leaves the basket",
)

# ---------------------------------------------------------------------------
# DP-RTL-002 — Inventory Position & Replenishment Signal
# Planted: a tail of express-format stores carries materially worse in-stock,
# excess cover concentrates after a season transition, and a quadrant of SKUs
# sells through while unavailable.
# ---------------------------------------------------------------------------
RTL2_CATEGORIES = [("apparel", 4), ("home", 3), ("electronics", 3), ("grocery", 4),
                   ("seasonal", 2)]

DP_RTL_002 = _spec(
    "DP-RTL-002",
    entity_column="sku", entity_count=1500,
    time_column="activity_date", grain="day", periods=60,
    fan_out=("location_id", ["STORE-001", "STORE-002", "STORE-003", "STORE-004", "STORE-005"]),
    expressions={
        "sku": "('SKU-' || lpad(entity::text, 6, '0'))",
        "location_id": "fan_value",
        "activity_date": "period_at::date",
        "category": weighted(RTL2_CATEGORIES, E),
        "region": pick(["North", "South", "East", "West"], E, k("reg")),
        # The in-stock tail: the express format runs materially thinner.
        "store_format": (
            "(CASE WHEN fan_value IN ('STORE-004','STORE-005') THEN 'express' "
            "      WHEN fan_value = 'STORE-003' THEN 'compact' ELSE 'large' END)"
        ),
        "season": weighted([("core", 5), ("spring", 2), ("autumn", 2), ("holiday", 1)], E),
        "horizon": pick(["1w", "4w", "13w"], E, P, k("hor")),
        "on_hand_units": (
            f"round((CASE WHEN {rnd(E, P, 'fan_value', k('stock'))} < "
            "             (CASE WHEN fan_value IN ('STORE-004','STORE-005') THEN 0.14 "
            "                   ELSE 0.035 END) THEN 0 "
            f"            ELSE 5 + {rnd(E, P, 'fan_value', k('oh'))} * 260 END)::numeric, 2)"
        ),
        "units_received": f"round((20 + {rnd(E, 'fan_value', k('recv'))} * 400)::numeric, 2)",
        "units_sold": (
            f"round(({rnd(E, P, 'fan_value', k('sold'))} * 24 * "
            f"  (CASE WHEN {weighted(RTL2_CATEGORIES, E)} = 'seasonal' AND period < 30 "
            "         THEN 2.4 ELSE 1.0 END))::numeric, 2)"
        ),
        "average_weekly_demand_units": (
            f"round((3 + {rnd(E, 'fan_value', k('dem'))} * 60)::numeric, 2)"
        ),
        "forecast_units": f"round((2 + {rnd(E, P, 'fan_value', k('fc'))} * 30)::numeric, 2)",
        "actual_units": (
            "round((forecast_units * "
            f" (0.72 + 0.55 * {rnd(E, P, 'fan_value', k('act'))} * "
            f"  (CASE WHEN {weighted(RTL2_CATEGORIES, E)} IN ('seasonal','apparel') "
            "         THEN 1.6 ELSE 1.0 END)))::numeric, 2)"
        ),
        "unmet_demand_units": (
            "(CASE WHEN on_hand_units = 0 "
            "      THEN round((average_weekly_demand_units / 7)::numeric, 2) ELSE 0 END)"
        ),
        "average_selling_price": f"round((4 + {rnd(E, k('asp'))} * 90)::numeric, 2)",
        "in_transit_units": f"round(({rnd(E, P, 'fan_value', k('transit'))} * 120)::numeric, 2)",
    },
    notes="express-format stores carry the in-stock tail; seasonal cover piles up after week 4",
)

# ---------------------------------------------------------------------------
# DP-TRN-001 — Fleet Movement & Delivery Performance
# Planted: lateness on Northeast lanes traces to dwell at two origin facilities,
# and two carriers price differently on comparable lanes.
# ---------------------------------------------------------------------------
LANES = ["NE-01", "NE-02", "SE-01", "MW-01", "MW-02", "W-01"]
NORTHEAST_LANES = "('NE-01','NE-02')"
SLOW_FACILITIES = "('DC-NEWARK','DC-ALBANY')"
FACILITIES_TRN = ["DC-NEWARK", "DC-ALBANY", "DC-ATLANTA", "DC-CHICAGO", "DC-RENO"]
CARRIERS = [("carrier_alpha", 4), ("carrier_bravo", 3), ("carrier_charlie", 3)]

DP_TRN_001 = _spec(
    "DP-TRN-001",
    entity_column="shipment_leg_id", entity_count=2200,
    time_column="departure_timestamp", grain="day", periods=60,
    expressions={
        "shipment_leg_id": "('LEG-' || lpad(entity::text, 8, '0') || '-' || period::text)",
        "shipment_id": "('SHP-' || lpad(entity::text, 8, '0'))",
        "departure_timestamp": "period_at",
        "lane": pick(LANES, E, P, k("lane")),
        "carrier": weighted(CARRIERS, E, P, k("carrier")),
        "customer": f"('CUST-' || lpad((1 + floor({rnd(E, k('cust'))} * 60))::int::text, 4, '0'))",
        "service_level": weighted([("standard", 5), ("expedited", 3), ("economy", 2)],
                                  E, P, k("svc")),
        "facility": pick(FACILITIES_TRN, E, P, k("fac")),
        "equipment_type": weighted([("dry_van", 5), ("reefer", 3), ("flatbed", 2)], E, k("eq")),
        "region": pick(["Northeast", "Southeast", "Midwest", "West"], E, k("reg")),
        "exception_type": (
            f"(CASE WHEN exception_logged THEN {pick(['damage', 'refusal', 'misroute', 'missed_appointment'], E, P, k('exc'))} END)"
        ),
        "delivery_attempted": "true",
        # Northeast lateness is dwell at two facilities, not transit.
        "delivered_within_window": (
            f"({rnd(E, P, k('otd'))} < "
            "  (0.965 "
            f"   - (CASE WHEN {pick(FACILITIES_TRN, E, P, k('fac'))} IN {SLOW_FACILITIES} "
            f"           AND {pick(LANES, E, P, k('lane'))} IN {NORTHEAST_LANES} "
            "           THEN 0.22 ELSE 0 END)))"
        ),
        "exception_logged": f"({rnd(E, P, k('exl'))} < 0.031)",
        "loaded_miles": f"round((40 + {rnd(E, P, k('miles'))} * 1400)::numeric, 2)",
        # The carrier spread: one carrier is materially cheaper on the same lanes.
        "linehaul_cost": (
            "round((loaded_miles * "
            f" (1.75 + 0.30 * {rnd(E, P, k('lh'))} "
            f"  - (CASE WHEN {weighted(CARRIERS, E, P, k('carrier'))} = 'carrier_alpha' "
            "           THEN 0.38 ELSE 0 END)))::numeric, 2)"
        ),
        "accessorial_cost": f"round(({rnd(E, P, k('acc'))} * 180)::numeric, 2)",
        "dwell_hours": (
            f"round((0.4 + {rnd(E, P, k('dwell'))} * 2.2 "
            f"  + (CASE WHEN {pick(FACILITIES_TRN, E, P, k('fac'))} IN {SLOW_FACILITIES} "
            "          THEN 4.8 ELSE 0 END))::numeric, 2)"
        ),
        "available_hours": "24",
        "revenue_hours": (
            f"round(greatest(0, 24 - dwell_hours - {rnd(E, P, k('idle'))} * 6)::numeric, 2)"
        ),
        "sla_penalty_risk": (
            f"(NOT delivered_within_window AND {rnd(E, P, k('pen'))} < 0.35)"
        ),
    },
    notes="Northeast lateness comes from dwell at two facilities; carrier_alpha prices lower",
)


# ---------------------------------------------------------------------------
# DP-UTL-001 — Grid Asset Health & Outage
# Planted: a handful of feeders carry most interruption minutes, poor-health
# assets serve disproportionately many customers, and one week carries a storm.
# ---------------------------------------------------------------------------
FEEDERS = ["FDR-101", "FDR-102", "FDR-103", "FDR-104", "FDR-105", "FDR-106", "FDR-107"]
WORST_FEEDERS = "('FDR-101','FDR-102')"
STORM_PERIOD_LOW, STORM_PERIOD_HIGH = 40, 47
ASSET_CLASSES = [("transformer", 4), ("recloser", 3), ("pole", 3), ("switch", 2)]

DP_UTL_001 = _spec(
    "DP-UTL-001",
    entity_column="asset_id", entity_count=2400,
    time_column="observed_date", grain="day", periods=90,
    expressions={
        "asset_id": "('ASSET-' || lpad(entity::text, 7, '0'))",
        "outage_id": (
            f"(CASE WHEN {rnd(E, P, k('out'))} < 0.06 "
            "       THEN ('OUT-' || lpad(entity::text, 7, '0') || '-' || period::text) END)"
        ),
        "observed_date": "period_at::date",
        "feeder": pick(FEEDERS, E, k("feeder")),
        "region": pick(["North", "Central", "Coastal"], E, k("reg")),
        "asset_class": weighted(ASSET_CLASSES, E),
        "vintage_band": weighted([("pre_1990", 3), ("1990_2005", 4), ("post_2005", 3)], E,
                                 k("vint")),
        "cause_class": (
            "(CASE WHEN outage_id IS NULL THEN NULL "
            f"      WHEN period BETWEEN {STORM_PERIOD_LOW} AND {STORM_PERIOD_HIGH} "
            "            THEN 'weather' "
            f"      ELSE {pick(['equipment', 'vegetation', 'animal', 'third_party'], E, P, k('cause'))} END)"
        ),
        "crew": pick(["crew_north", "crew_central", "crew_coastal"], E, P, k("crew")),
        "served_customer_id": "('SVC-' || lpad(entity::text, 7, '0'))",
        # The Pareto: two feeders carry most of the interruptions.
        "customer_interruptions": (
            "(CASE WHEN outage_id IS NULL THEN 0 "
            f"      ELSE round(((20 + {rnd(E, P, k('ci'))} * 400) * "
            f"        (CASE WHEN {pick(FEEDERS, E, k('feeder'))} IN {WORST_FEEDERS} "
            "               THEN 3.6 ELSE 1.0 END))::numeric, 2) END)"
        ),
        "customer_interruption_minutes": (
            "(CASE WHEN outage_id IS NULL THEN 0 "
            f"      ELSE round((customer_interruptions * (25 + {rnd(E, P, k('cim'))} * 160) * "
            f"        (CASE WHEN period BETWEEN {STORM_PERIOD_LOW} AND {STORM_PERIOD_HIGH} "
            "               THEN 3.2 ELSE 1.0 END))::numeric, 2) END)"
        ),
        "restoration_minutes": (
            f"(CASE WHEN outage_id IS NOT NULL "
            f"      THEN round((30 + {rnd(E, P, k('rest'))} * 320)::numeric, 2) END)"
        ),
        # The prioritisation matrix: poor-health assets serve the most customers.
        "asset_health_score": (
            f"round((100 - {rnd(E, k('ahi'))} * 55 "
            f"  - (CASE WHEN {weighted([('pre_1990', 3), ('1990_2005', 4), ('post_2005', 3)], E, k('vint'))}"
            "           = 'pre_1990' THEN 22 ELSE 0 END))::numeric, 2)"
        ),
        "scheduled": f"({rnd(E, P, k('sched'))} < 0.08)",
        "completed_within_window": f"(scheduled AND {rnd(E, P, k('pm'))} < 0.965)",
        "deferral_count": (
            f"floor({rnd(E, k('defer'))} * "
            "  (CASE WHEN asset_health_score < 45 THEN 5 ELSE 2 END))::int"
        ),
        "major_event_day": (
            f"(period BETWEEN {STORM_PERIOD_LOW} AND {STORM_PERIOD_HIGH})"
        ),
        "load_impact_mw": (
            f"(CASE WHEN outage_id IS NOT NULL "
            f"      THEN round(({rnd(E, P, k('mw'))} * 12)::numeric, 3) END)"
        ),
    },
    notes="two feeders carry most interruption minutes; a storm sits in periods 40-47",
)

# ---------------------------------------------------------------------------
# DP-ENG-001 — Smart Meter Consumption & Load Profile
# Planted: demand response delivery differs markedly by rate class, and
# estimated reads cluster on one meter type in two regions.
# ---------------------------------------------------------------------------
RATE_CLASSES = [("residential", 6), ("small_commercial", 3), ("large_commercial", 1)]
ESTIMATING_REGIONS = "('North','Coastal')"

DP_ENG_001 = _spec(
    "DP-ENG-001",
    entity_column="meter_id", entity_count=1800,
    time_column="interval_start", grain="hour", periods=168,
    expressions={
        "meter_id": "('MTR-' || lpad(entity::text, 8, '0'))",
        "interval_start": "period_at",
        "rate_class": weighted(RATE_CLASSES, E),
        "region": pick(["North", "Central", "Coastal"], E, k("reg")),
        "feeder": pick(FEEDERS, E, k("feeder")),
        "dwelling_type": weighted([("detached", 4), ("apartment", 4), ("commercial", 2)],
                                  E, k("dwell")),
        "meter_type": weighted([("communicating", 8), ("non_communicating", 2)], E, k("mtype")),
        "programme": (
            f"(CASE WHEN {rnd(E, k('prog'))} < 0.35 "
            f"      THEN {pick(['peak_time_rebate', 'direct_load_control'], E, k('pname'))} END)"
        ),
        # The estimated-read cluster: non-communicating meters in two regions.
        "read_type": (
            f"(CASE WHEN {weighted([('communicating', 8), ('non_communicating', 2)], E, k('mtype'))}"
            "         = 'non_communicating' "
            f"        AND {pick(['North', 'Central', 'Coastal'], E, k('reg'))} "
            f"            IN {ESTIMATING_REGIONS} "
            f"        AND {rnd(E, P, k('est'))} < 0.55 THEN 'estimated' "
            "      ELSE 'actual' END)"
        ),
        "consumption_kwh": (
            "(CASE WHEN read_type = 'estimated' THEN NULL "
            f"      ELSE round(((0.4 + {rnd(E, P, k('kwh'))} * 3.2) * "
            f"        (1 + {seasonal(0.45, 'period', 24)}))::numeric, 4) END)"
        ),
        "interval_demand_kw": (
            "(CASE WHEN read_type = 'estimated' THEN NULL "
            "      ELSE round((consumption_kwh * 1.05)::numeric, 4) END)"
        ),
        "period_hours": "1",
        "enrolled_and_called": (
            "(programme IS NOT NULL AND period IN (52, 100, 148))"
        ),
        # The response spread: residential meters deliver far less curtailment.
        "curtailed_during_event": (
            f"(enrolled_and_called AND {rnd(E, P, k('curt'))} < "
            f" (CASE WHEN {weighted(RATE_CLASSES, E)} = 'residential' THEN 0.52 ELSE 0.88 END))"
        ),
        "temperature_c": (
            f"round((14 + {seasonal(9, 'period', 24)} + {rnd(E, P, k('temp'))} * 4)::numeric, 2)"
        ),
    },
    notes="residential meters under-deliver curtailment; estimated reads cluster on one meter type",
)

# ---------------------------------------------------------------------------
# DP-MFG-001 — Manufacturing Yield & Equipment Effectiveness
# Planted: Line 3 downtime concentrates in two reason codes, the night shift
# carries a lower first pass yield, and changeover time shifts after
# standardisation.
# ---------------------------------------------------------------------------
LINES = ["LINE-1", "LINE-2", "LINE-3", "LINE-4"]
REASON_CODES = ["changeover", "material_starvation", "mechanical_fault", "operator_break",
                "quality_hold", "tooling_change"]
LINE3_REASONS = "('mechanical_fault','material_starvation')"
STANDARDISATION_PERIOD = 45

DP_MFG_001 = _spec(
    "DP-MFG-001",
    entity_column="run_id", entity_count=1400,
    time_column="shift_date", grain="day", periods=90,
    expressions={
        "run_id": "('RUN-' || lpad(entity::text, 7, '0') || '-' || period::text)",
        "line": pick(LINES, E, k("line")),
        "plant": weighted([("plant_north", 4), ("plant_south", 3), ("plant_east", 3)], E,
                          k("plant")),
        "shift": pick(["day", "evening", "night"], E, P, k("shift")),
        "shift_date": "period_at::date",
        "product_family": weighted([("family_a", 4), ("family_b", 3), ("family_c", 3)], E,
                                   k("fam")),
        # Line 3 concentrates on two reason codes.
        "reason_code": (
            f"(CASE WHEN {pick(LINES, E, k('line'))} = 'LINE-3' "
            f"      THEN {pick(['mechanical_fault', 'material_starvation'], E, P, k('rc3'))} "
            f"      ELSE {pick(REASON_CODES, E, P, k('rc'))} END)"
        ),
        "downtime_type": weighted([("unplanned", 7), ("planned", 3)], E, P, k("dtype")),
        "root_cause": pick(["tooling_wear", "material_defect", "setup_error", "contamination"],
                           E, P, k("root")),
        "availability_rate": f"round((0.82 + {rnd(E, P, k('avail'))} * 0.16)::numeric, 4)",
        "performance_rate": f"round((0.86 + {rnd(E, P, k('perf'))} * 0.13)::numeric, 4)",
        # The shift gap: the night shift yields materially lower.
        "quality_rate": (
            f"round((0.955 + {rnd(E, P, k('qual'))} * 0.04 "
            f"  - (CASE WHEN {pick(['day', 'evening', 'night'], E, P, k('shift'))} = 'night' "
            "          THEN 0.045 ELSE 0 END))::numeric, 4)"
        ),
        "started_units": f"round((400 + {rnd(E, P, k('start'))} * 2600)::numeric, 2)",
        "scrapped_units": (
            "round((started_units * (1 - quality_rate) * "
            f" (1 + 0.8 * {rnd(E, P, k('scrap'))}))::numeric, 2)"
        ),
        "passed_without_rework": (
            f"({rnd(E, P, k('fpy'))} < quality_rate)"
        ),
        "downtime_hours": (
            f"round(({rnd(E, P, k('dt'))} * 3.5 * "
            f"  (CASE WHEN {pick(LINES, E, k('line'))} = 'LINE-3' THEN 1.8 ELSE 1.0 END))"
            "::numeric, 2)"
        ),
        # The distribution shift: standardisation tightens the tail, not just the mean.
        "changeover_minutes": (
            f"round((CASE WHEN period > {STANDARDISATION_PERIOD} "
            f"            THEN 24 + {rnd(E, P, k('co'))} * 18 "
            f"            ELSE 26 + {rnd(E, P, k('co'))} * 62 END)::numeric, 2)"
        ),
        "standardised_changeover": f"(period > {STANDARDISATION_PERIOD})",
    },
    notes="Line 3 downtime on two reason codes; night shift yields lower; changeover tightens",
)

# ---------------------------------------------------------------------------
# DP-RTL-003 — Visit & Conversion Funnel
# Planted: digital converts at roughly half the store rate and mobile worst of
# all, express-format locations carry the weakest conversion of the three, and
# one category holds visitors longest while converting worst — the finding a
# transaction-grain table cannot produce, because a visit that bought nothing
# has no transaction row to appear in.
# ---------------------------------------------------------------------------
RTL3_CATEGORIES = [("apparel", 4), ("home", 3), ("electronics", 3), ("grocery", 4),
                   ("beauty", 2), ("toys", 2)]
RTL3_CHANNELS = [("store", 6), ("digital", 3), ("marketplace", 1)]
RTL3_FORMATS = [("large", 3), ("compact", 4), ("express", 3)]
# The category that holds attention and does not sell.
BROWSING_CATEGORY = "electronics"

_RTL3_CHANNEL = weighted(RTL3_CHANNELS, E, P, k("ch"))
_RTL3_FORMAT = weighted(RTL3_FORMATS, E, k("fmt"))
_RTL3_CATEGORY = weighted(RTL3_CATEGORIES, E, P, k("cat"))
# Mobile only exists off the shop floor, so the device draw is keyed the same
# way the column is and reused in the conversion term rather than re-derived.
_RTL3_DEVICE = f"(CASE WHEN {rnd(E, P, k('dev'))} < 0.62 THEN 'mobile' ELSE 'desktop' END)"

DP_RTL_003 = _spec(
    "DP-RTL-003",
    entity_column="visit_id", entity_count=2600,
    time_column="visit_timestamp", grain="hour", periods=300,
    expressions={
        "visit_id": "('VIS-' || lpad(entity::text, 8, '0') || '-' || period::text)",
        "visit_timestamp": "period_at",
        "business_date": "period_at::date",
        "region": pick(["North", "South", "East", "West"], E, k("reg")),
        "channel": _RTL3_CHANNEL,
        "store_format": _RTL3_FORMAT,
        "entry_category": _RTL3_CATEGORY,
        "device_class": f"(CASE WHEN {_RTL3_CHANNEL} <> 'store' THEN {_RTL3_DEVICE} END)",
        "traffic_source": (
            f"(CASE WHEN {_RTL3_CHANNEL} <> 'store' "
            f"      THEN {pick(['organic', 'paid_search', 'email', 'social'], E, P, k('src'))} "
            " END)"
        ),
        "loyalty_identified": f"({rnd(E, P, k('loy'))} < 0.38)",
        # The three planted gaps, multiplied onto a store base near the KPI's
        # own 24% target. A visit converts or it does not; everything else about
        # the row follows from that, so this term is computed first and read by
        # the columns below it.
        "converted": (
            f"({rnd(E, P, k('conv'))} < "
            "  0.30"
            f"  * (CASE WHEN {_RTL3_CHANNEL} = 'store' THEN 1.0 ELSE 0.52 END)"
            f"  * (CASE WHEN {_RTL3_CHANNEL} <> 'store' AND {_RTL3_DEVICE} = 'mobile' "
            "          THEN 0.74 ELSE 1.0 END)"
            f"  * (CASE WHEN {_RTL3_FORMAT} = 'express' THEN 0.68 ELSE 1.0 END)"
            f"  * (CASE WHEN {_RTL3_CATEGORY} = '{BROWSING_CATEGORY}' THEN 0.55 ELSE 1.0 END)"
            f"  * (1 + {seasonal(0.18, 'period', 24)})"
            ")"
        ),
        # Referential integrity with DP-RTL-001: a converted visit carries a
        # transaction id in that product's shape, and an unconverted one carries
        # nothing at all. The null is the column that makes the measure possible.
        "transaction_id": (
            "(CASE WHEN converted "
            "      THEN ('TXN-' || lpad(entity::text, 8, '0') || '-' || period::text) END)"
        ),
        "basket_started": (
            f"(converted OR {rnd(E, P, k('basket'))} < 0.41)"
        ),
        "basket_abandoned": "(basket_started AND NOT converted)",
        "items_viewed": (
            f"(1 + floor({rnd(E, P, k('items'))} * 9 "
            f"  + (CASE WHEN {_RTL3_CATEGORY} = '{BROWSING_CATEGORY}' THEN 5 ELSE 0 END)))::int"
        ),
        # The browsing category holds attention roughly twice as long, which is
        # what makes "long dwell, weak conversion" a finding rather than noise.
        "dwell_seconds": (
            f"round((60 + {rnd(E, P, k('dwell'))} * 540 "
            f"  + (CASE WHEN {_RTL3_CATEGORY} = '{BROWSING_CATEGORY}' THEN 420 ELSE 0 END) "
            "   + (CASE WHEN converted THEN 180 ELSE 0 END))::numeric, 1)"
        ),
        "net_sales": (
            "(CASE WHEN converted "
            f"      THEN round(((9 + {rnd(E, P, k('sales'))} * 130) * "
            f"        (1 + {seasonal(0.25, 'period', 168)}))::numeric, 2) END)"
        ),
    },
    notes="digital and mobile convert worse; express format trails; electronics holds and does not sell",
)

# ---------------------------------------------------------------------------
# DP-BNK-003 — Lending & Credit Portfolio
# Planted: delinquency concentrates in one origination vintage and, within it,
# in the broker channel; one product type earns a yield out of line with the
# risk grades behind it; and defaulted accounts in one region are held at
# provision coverage below the rest of the book.
# ---------------------------------------------------------------------------
BNK3_PRODUCTS = [("mortgage", 4), ("auto", 3), ("personal", 2), ("card", 3)]
BNK3_GRADES = [("A", 4), ("B", 4), ("C", 2), ("D", 1)]
BNK3_CHANNELS = [("branch", 4), ("digital", 3), ("broker", 3)]
BNK3_VINTAGES = [("0-1y", 3), ("1-3y", 4), ("3-5y", 2), ("5y+", 2)]
# The vintage and channel the arrears sit in.
ARREARS_VINTAGE = "1-3y"
ARREARS_CHANNEL = "broker"
# The product whose yield is out of line with its grade mix.
YIELD_OUTLIER = "card"
UNDERPROVISIONED_REGION = "Southeast"

_B3_PRODUCT = weighted(BNK3_PRODUCTS, E, k("prod"))
_B3_GRADE = weighted(BNK3_GRADES, E, k("grade"))
_B3_CHANNEL = weighted(BNK3_CHANNELS, E, k("chan"))
_B3_VINTAGE = weighted(BNK3_VINTAGES, E, k("vint"))
_B3_REGION = pick(["Northeast", "Southeast", "Midwest", "West"], E, k("reg"))

DP_BNK_003 = _spec(
    "DP-BNK-003",
    entity_column="loan_id", entity_count=8000,
    time_column="as_of_month", grain="month", periods=24,
    expressions={
        "loan_id": "('LN-' || lpad(entity::text, 8, '0'))",
        "customer_id": "('CUST-' || lpad((entity / 2)::text, 7, '0'))",
        "as_of_month": "date_trunc('month', period_at)::date",
        "product_type": _B3_PRODUCT,
        "region": _B3_REGION,
        "segment": weighted([("mass", 5), ("affluent", 3), ("business", 2)], E, k("seg")),
        "channel": _B3_CHANNEL,
        "risk_grade": _B3_GRADE,
        "vintage_band": _B3_VINTAGE,
        "origination_date": (
            f"(period_at - ((180 + floor({rnd(E, k('orig'))} * 1800))::int || ' days')"
            "::interval)::date"
        ),
        "original_balance": f"round({uniform(4000, 480000, E, k('orig_bal'))}::numeric, 2)",
        "outstanding_balance": (
            f"round((original_balance * (0.35 + 0.6 * {rnd(E, P, k('amort'))}))::numeric, 2)"
        ),
        # Card carries a much higher coupon than its grade mix would imply, which
        # is the yield question the agent is meant to find.
        "interest_income": (
            "round((outstanding_balance * "
            f" ((0.0028 + 0.0022 * {rnd(E, P, k('cpn'))}) "
            f"  * (CASE WHEN {_B3_PRODUCT} = '{YIELD_OUTLIER}' THEN 2.4 ELSE 1.0 END)))"
            "::numeric, 2)"
        ),
        # The arrears concentration: one vintage, and the broker channel within it.
        "days_past_due": (
            f"(CASE WHEN {rnd(E, P, k('dpd'))} < "
            # Set so the book lands near KPI-DELINQ-079's own 2.4% target once
            # the vintage, channel and grade multipliers below are applied.
            "       0.0085"
            f"       * (CASE WHEN {_B3_VINTAGE} = '{ARREARS_VINTAGE}' THEN 2.8 ELSE 1.0 END)"
            f"       * (CASE WHEN {_B3_CHANNEL} = '{ARREARS_CHANNEL}' THEN 2.2 ELSE 1.0 END)"
            f"       * (CASE WHEN {_B3_GRADE} IN ('C','D') THEN 2.4 ELSE 1.0 END)"
            f"      THEN (30 + floor({rnd(E, P, k('dpdlen'))} * 150))::int ELSE 0 END)"
        ),
        "delinquent_30d": "(days_past_due >= 30)",
        "defaulted": "(days_past_due >= 90)",
        "charged_off_amount": (
            f"(CASE WHEN days_past_due >= 150 AND {rnd(E, P, k('co'))} < 0.35 "
            "       THEN round((outstanding_balance * 0.62)::numeric, 2) ELSE 0 END)"
        ),
        # The provisioning gap: one region holds materially less against its
        # defaulted balance than the rest of the book.
        "provision_amount": (
            "(CASE WHEN defaulted "
            f"      THEN round((outstanding_balance * (0.88 + 0.20 * {rnd(E, P, k('prov'))}) "
            f"        * (CASE WHEN {_B3_REGION} = '{UNDERPROVISIONED_REGION}' "
            "                THEN 0.58 ELSE 1.0 END))::numeric, 2) "
            f"      ELSE round((outstanding_balance * 0.006 * {rnd(E, P, k('prov'))})"
            "::numeric, 2) END)"
        ),
        "collateral_value": (
            f"(CASE WHEN {_B3_PRODUCT} IN ('mortgage', 'auto') "
            f"      THEN round((original_balance * (1.25 + 0.35 * {rnd(E, k('coll'))}))"
            "::numeric, 2) END)"
        ),
        "bureau_score": (
            f"(CASE WHEN {rnd(E, P, k('bureau'))} < 0.93 "
            f"      THEN (520 + floor({rnd(E, P, k('score'))} * 320) "
            f"        - (CASE WHEN {_B3_GRADE} IN ('C','D') THEN 90 ELSE 0 END))::int END)"
        ),
    },
    notes="arrears in the 1-3y broker vintage; card yield out of line; Southeast under-provisioned",
)


# ---------------------------------------------------------------------------
# DP-TCH-002 — Service Reliability & Incident
# Planted: change failure concentrates in the canary ring, one service tier
# acknowledges materially slower than the others, and one region carries a
# sustained error-rate elevation across a contiguous run of hours.
# ---------------------------------------------------------------------------
TCH2_TIERS = [("tier1", 3), ("tier2", 4), ("tier3", 3)]
TCH2_RINGS = [("canary", 2), ("early", 3), ("broad", 5)]
TCH2_REGIONS = [("us-east", 4), ("us-west", 3), ("eu-west", 3)]
TCH2_TEAMS = ["platform", "payments", "identity", "search", "billing"]
FAILING_RING = "canary"
SLOW_ACK_TIER = "tier3"
DEGRADED_REGION = "eu-west"
# The contiguous run of hours the regional elevation sits in.
DEGRADED_FROM, DEGRADED_TO = 96, 168

_T2_TIER = weighted(TCH2_TIERS, E, k("tier"))
_T2_RING = weighted(TCH2_RINGS, E, P, k("ring"))
_T2_REGION = weighted(TCH2_REGIONS, E, k("rgn"))
_T2_INCIDENT = f"({rnd(E, P, k('inc'))} < 0.015)"
_T2_DEPLOY = f"({rnd(E, P, k('dep'))} < 0.06)"

DP_TCH_002 = _spec(
    "DP-TCH-002",
    entity_column="service_id", entity_count=900,
    time_column="observed_hour", grain="hour", periods=336,
    expressions={
        "service_id": "('SVC-' || lpad(entity::text, 5, '0'))",
        "observed_hour": "period_at",
        "service_tier": _T2_TIER,
        "region": _T2_REGION,
        "team": pick(TCH2_TEAMS, E, k("team")),
        "deployment_ring": _T2_RING,
        # An incident belongs to the hour it was raised, so counting incidents
        # counts incidents rather than the hours they ran for.
        "incident_id": (
            f"(CASE WHEN {_T2_INCIDENT} "
            "       THEN ('INC-' || lpad(entity::text, 5, '0') || '-' || period::text) END)"
        ),
        "severity": (
            f"(CASE WHEN {_T2_INCIDENT} "
            f"      THEN {weighted([('sev1', 1), ('sev2', 3), ('sev3', 6)], E, P, k('sev'))} END)"
        ),
        "request_count": (
            f"round((2000 + {rnd(E, P, k('req'))} * 18000) "
            f"  * (1 + {seasonal(0.35, 'period', 24)}))"
        ),
        # The regional elevation: a contiguous run of hours in one region.
        "error_count": (
            "round(request_count * "
            f" ((0.0015 + 0.004 * {rnd(E, P, k('err'))}) "
            f"  * (CASE WHEN {_T2_REGION} = '{DEGRADED_REGION}' "
            f"           AND period BETWEEN {DEGRADED_FROM} AND {DEGRADED_TO} "
            "          THEN 5.5 ELSE 1.0 END)))"
        ),
        "latency_p95_ms": (
            f"round((120 + {rnd(E, P, k('lat'))} * 380 "
            f"  + (CASE WHEN {_T2_REGION} = '{DEGRADED_REGION}' "
            f"           AND period BETWEEN {DEGRADED_FROM} AND {DEGRADED_TO} "
            "          THEN 260 ELSE 0 END))::numeric, 1)"
        ),
        "scheduled_minutes": f"(CASE WHEN {rnd(E, P, k('maint'))} < 0.01 THEN 45 ELSE 60 END)",
        "availability_minutes": (
            f"(CASE WHEN {_T2_INCIDENT} "
            f"      THEN round((scheduled_minutes * (0.55 + 0.4 * {rnd(E, P, k('av'))}))"
            "::numeric, 1) ELSE scheduled_minutes END)"
        ),
        # The slow tier: tier3 is paged like the others and answers later.
        "acknowledged_minutes": (
            f"(CASE WHEN {_T2_INCIDENT} "
            f"      THEN round(((1 + {rnd(E, P, k('ack'))} * 9) "
            f"        * (CASE WHEN {_T2_TIER} = '{SLOW_ACK_TIER}' THEN 3.8 ELSE 1.0 END))"
            "::numeric, 1) ELSE 0 END)"
        ),
        "resolved_minutes": (
            f"(CASE WHEN {_T2_INCIDENT} "
            f"      THEN round((acknowledged_minutes + 12 + {rnd(E, P, k('res'))} * 110)"
            "::numeric, 1) ELSE 0 END)"
        ),
        "change_deployed": _T2_DEPLOY,
        # The canary ring is where failures are meant to surface, and do.
        "change_failed": (
            f"({_T2_DEPLOY} AND {rnd(E, P, k('cf'))} < "
            f"  0.06 * (CASE WHEN {_T2_RING} = '{FAILING_RING}' THEN 4.2 ELSE 1.0 END))"
        ),
        "on_call_page_count": (
            f"(CASE WHEN {_T2_INCIDENT} THEN (1 + floor({rnd(E, P, k('pg'))} * 4))::int "
            "       ELSE 0 END)"
        ),
    },
    notes="canary ring fails more; tier3 acknowledges slower; eu-west errors elevated for a run",
)

# ---------------------------------------------------------------------------
# DP-TRN-002 — Freight Cost & Margin
# Planted: accessorial spend concentrates on a small set of lanes through
# detention, spot-tendered movements carry a materially thinner margin than
# contracted ones, and one carrier accounts for most of the disputed value.
# ---------------------------------------------------------------------------
TRN2_LANES = ["LANE-CHI-ATL", "LANE-LAX-PHX", "LANE-NYC-BOS", "LANE-DFW-DEN",
              "LANE-SEA-POR", "LANE-MIA-ORL"]
TRN2_CARRIERS = [("carrier_alpha", 4), ("carrier_bravo", 3), ("carrier_charlie", 3)]
TRN2_MODES = [("road", 6), ("rail", 2), ("air", 1), ("ocean", 1)]
# The two lanes detention sits on, and the carrier the disputes sit with.
DETENTION_LANES = "('LANE-CHI-ATL','LANE-DFW-DEN')"
DISPUTING_CARRIER = "carrier_charlie"

_R2_LANE = pick(TRN2_LANES, E, k("lane"))
_R2_CARRIER = weighted(TRN2_CARRIERS, E, P, k("carr"))
_R2_SPOT = f"({rnd(E, P, k('spot'))} < 0.14)"

DP_TRN_002 = _spec(
    "DP-TRN-002",
    entity_column="invoice_line_id", entity_count=2400,
    time_column="invoice_date", grain="day", periods=120,
    expressions={
        "invoice_line_id": "('INV-' || lpad(entity::text, 8, '0') || '-' || period::text)",
        "shipment_id": "('SHP-' || lpad(entity::text, 8, '0'))",
        "invoice_date": "period_at::date",
        "lane": _R2_LANE,
        "carrier": _R2_CARRIER,
        "customer": pick(["cust_north", "cust_south", "cust_central", "cust_west"], E,
                         k("cust")),
        "service_level": weighted([("standard", 6), ("expedited", 3), ("economy", 1)], E, P,
                                  k("svc")),
        "mode": weighted(TRN2_MODES, E, k("mode")),
        "equipment_type": pick(["dry_van", "reefer", "flatbed"], E, k("eq")),
        "region": pick(["Northeast", "Southeast", "Midwest", "West"], E, k("reg")),
        "billable_km": f"round((80 + {rnd(E, P, k('km'))} * 2600)::numeric, 1)",
        "weight_kg": f"round((400 + {rnd(E, P, k('wt'))} * 18000)::numeric, 1)",
        "linehaul_cost": (
            f"round((billable_km * (1.05 + 0.35 * {rnd(E, P, k('rate'))}))::numeric, 2)"
        ),
        # Detention concentrates on two lanes, which is the accessorial finding.
        "accessorial_type": (
            f"(CASE WHEN {rnd(E, P, k('acc'))} < 0.34 "
            f"      THEN (CASE WHEN {_R2_LANE} IN {DETENTION_LANES} THEN 'detention' "
            f"                 ELSE {pick(['layover', 'redelivery', 'lumper'], E, P, k('at'))} "
            "            END) END)"
        ),
        "accessorial_cost": (
            "(CASE WHEN accessorial_type IS NULL THEN 0 "
            f"      ELSE round((linehaul_cost * (0.06 + 0.10 * {rnd(E, P, k('accv'))}) "
            f"        * (CASE WHEN {_R2_LANE} IN {DETENTION_LANES} THEN 2.6 ELSE 1.0 END))"
            "::numeric, 2) END)"
        ),
        "fuel_surcharge": (
            f"round((linehaul_cost * (0.11 + 0.04 * {seasonal(1.0, 'period', 30)}))::numeric, 2)"
        ),
        "tendered_to_spot": _R2_SPOT,
        "contracted_rate": (
            f"(CASE WHEN NOT {_R2_SPOT} "
            "       THEN round((linehaul_cost / NULLIF(billable_km, 0))::numeric, 4) END)"
        ),
        "spot_rate": (
            f"(CASE WHEN {_R2_SPOT} "
            f"      THEN round((linehaul_cost * (1.18 + 0.14 * {rnd(E, P, k('sr'))}) "
            "        / NULLIF(billable_km, 0))::numeric, 4) END)"
        ),
        # Spot moves are billed at the same market and cost more, so their
        # margin is thinner. That is the comparison the agent is asked for.
        "billed_revenue": (
            "round(((linehaul_cost + accessorial_cost + fuel_surcharge) "
            f" * (1.20 + 0.10 * {rnd(E, P, k('mkup'))}) "
            f" * (CASE WHEN {_R2_SPOT} THEN 0.87 ELSE 1.0 END))::numeric, 2)"
        ),
        "invoice_disputed": (
            f"({rnd(E, P, k('disp'))} < "
            f"  0.04 * (CASE WHEN {_R2_CARRIER} = '{DISPUTING_CARRIER}' THEN 4.5 ELSE 1.0 END))"
        ),
        "disputed_amount": (
            "(CASE WHEN invoice_disputed "
            f"      THEN round((billed_revenue * (0.08 + 0.22 * {rnd(E, P, k('dv'))}))"
            "::numeric, 2) ELSE 0 END)"
        ),
    },
    notes="detention on two lanes; spot margin thinner; carrier_charlie disputes concentrate",
)


# ---------------------------------------------------------------------------
# DP-MFG-002 — Supplier Quality & Inbound Materials
# Planted: a small number of suppliers carry most rejected units in one material
# class, one country of origin runs a materially longer lead time with a worse
# on-time rate for it, and price variance drifts upward in one commodity class.
# ---------------------------------------------------------------------------
MFG2_CLASSES = [("castings", 3), ("electronics", 4), ("fasteners", 3),
                ("polymers", 2), ("packaging", 2)]
MFG2_ORIGINS = [("US", 4), ("MX", 3), ("CN", 3), ("DE", 2)]
MFG2_TIERS = [("strategic", 2), ("preferred", 4), ("transactional", 4)]
DEFECT_CLASS = "electronics"
FAR_ORIGIN = "CN"
DRIFTING_CLASS = "polymers"

_M2_CLASS = weighted(MFG2_CLASSES, E, k("mcls"))
_M2_ORIGIN = weighted(MFG2_ORIGINS, E, k("orig"))
# Twenty-four suppliers: enough that ranking them says something, and inside
# the runtime's answer row limit so the share each carries is a share of the
# whole supply base rather than of whatever fitted in the answer.
_M2_SUPPLIER = "('SUP-' || lpad((1 + (entity % 24))::text, 4, '0'))"
# The defect tail sits with the first four suppliers, in one material class.
_M2_BAD_SUPPLIER = "((entity % 24) < 4)"

DP_MFG_002 = _spec(
    "DP-MFG-002",
    entity_column="receipt_line_id", entity_count=2200,
    time_column="receipt_date", grain="day", periods=120,
    expressions={
        "receipt_line_id": "('RCP-' || lpad(entity::text, 8, '0') || '-' || period::text)",
        "purchase_order_id": "('PO-' || lpad((entity / 3)::text, 8, '0'))",
        "supplier_id": _M2_SUPPLIER,
        "receipt_date": "period_at::date",
        "material_class": _M2_CLASS,
        "plant": weighted([("plant_north", 4), ("plant_south", 3), ("plant_east", 3)], E,
                          k("plant")),
        "region": pick(["Northeast", "Southeast", "Midwest", "West"], E, k("reg")),
        "supplier_tier": weighted(MFG2_TIERS, E, k("stier")),
        "country_of_origin": _M2_ORIGIN,
        "ordered_units": f"(50 + floor({rnd(E, P, k('ord'))} * 950))::int",
        "received_units": (
            f"round((ordered_units * (0.94 + 0.06 * {rnd(E, P, k('recv'))}))::numeric, 0)"
        ),
        # The defect tail: six suppliers, worse again in one material class.
        "rejected_units": (
            "round((received_units * "
            f" ((0.004 + 0.008 * {rnd(E, P, k('rej'))}) "
            f"  * (CASE WHEN {_M2_BAD_SUPPLIER} THEN 5.5 ELSE 1.0 END) "
            f"  * (CASE WHEN {_M2_CLASS} = '{DEFECT_CLASS}' THEN 2.2 ELSE 1.0 END)))"
            "::numeric, 0)"
        ),
        "accepted_units": "(received_units - rejected_units)",
        "rejection_reason": (
            "(CASE WHEN rejected_units > 0 "
            f"      THEN {pick(['dimensional', 'cosmetic', 'documentation', 'contamination'], E, P, k('rr'))} "
            " END)"
        ),
        # The far origin: longer to arrive, and later against its own promise.
        "lead_time_days": (
            f"round((9 + {rnd(E, P, k('lt'))} * 18 "
            f"  + (CASE WHEN {_M2_ORIGIN} = '{FAR_ORIGIN}' THEN 26 ELSE 0 END))::numeric, 1)"
        ),
        "promised_date": "period_at::date",
        "on_time": (
            f"({rnd(E, P, k('otd'))} < "
            f"  (CASE WHEN {_M2_ORIGIN} = '{FAR_ORIGIN}' THEN 0.79 ELSE 0.955 END))"
        ),
        "inspection_required": (
            f"({_M2_CLASS} IN ('electronics', 'castings') OR {rnd(E, k('insp'))} < 0.2)"
        ),
        "inspection_passed": (
            f"(NOT inspection_required OR {rnd(E, P, k('ip'))} < 0.96)"
        ),
        "standard_cost": f"round({uniform(2, 240, E, k('std'))}::numeric, 2)",
        # The drift: one commodity class walks away from standard over time.
        "unit_cost": (
            "round((standard_cost * "
            f" (0.99 + 0.02 * {rnd(E, P, k('uc'))} "
            f"  + (CASE WHEN {_M2_CLASS} = '{DRIFTING_CLASS}' "
            "          THEN 0.06 * (period::numeric / 120) ELSE 0 END)))::numeric, 2)"
        ),
    },
    notes="six suppliers carry the defects in electronics; CN lead time and OTD worse; polymers price drifts",
)

# ---------------------------------------------------------------------------
# DP-HLT-003 — Workforce & Care Capacity
# Planted: agency reliance concentrates on the night shift and, within it, on
# one unit type; boarding hours rise on the units closest to their staffed bed
# capacity; and a tail of units carries both the vacancies and the overtime
# that covers them.
# ---------------------------------------------------------------------------
HLT3_UNIT_TYPES = [("medical_surgical", 4), ("critical_care", 2), ("telemetry", 3),
                   ("emergency", 2)]
HLT3_FACILITIES = [("north_general", 4), ("river_memorial", 3), ("west_campus", 3)]
HLT3_SHIFTS = ["day", "evening", "night"]
AGENCY_SHIFT = "night"
AGENCY_UNIT_TYPE = "critical_care"
# The tail of units carrying the vacancies.
SHORT_STAFFED = "((entity % 40) < 7)"

_H3_UNIT_TYPE = weighted(HLT3_UNIT_TYPES, E, k("utype"))
# The shift is a fanned-out dimension rather than a draw, so a unit has exactly
# one row per shift per day and the label agrees with the timestamp.
_H3_SHIFT = "fan_value"
SHIFT_HOUR = "(CASE fan_value WHEN 'day' THEN 7 WHEN 'evening' THEN 15 ELSE 23 END)"

DP_HLT_003 = _spec(
    "DP-HLT-003",
    entity_column="unit_id", entity_count=900,
    time_column="shift_start", grain="day", periods=180,
    fan_out=("shift", HLT3_SHIFTS),
    expressions={
        "unit_id": "('UNIT-' || lpad(entity::text, 5, '0'))",
        "shift_start": f"(date_trunc('day', period_at) + ({SHIFT_HOUR} || ' hours')::interval)",
        "facility": weighted(HLT3_FACILITIES, E, k("fac")),
        "region": pick(["Northeast", "Southeast", "Midwest", "West"], E, k("reg")),
        "unit_type": _H3_UNIT_TYPE,
        "shift": _H3_SHIFT,
        "licensed_beds": f"(12 + floor({rnd(E, k('lic'))} * 28))::int",
        "staffed_beds": (
            f"round((licensed_beds * (0.82 + 0.16 * {rnd(E, P, k('staffed'))}) "
            f"  * (CASE WHEN {SHORT_STAFFED} THEN 0.82 ELSE 1.0 END))::numeric, 0)"
        ),
        # Occupancy is drawn against staffed beds, so a short-staffed unit runs
        # closer to its own ceiling rather than simply emptier.
        "census_patients": (
            "round((staffed_beds * "
            f" ((0.70 + 0.26 * {rnd(E, P, k('cen'))}) "
            f"  * (CASE {_H3_UNIT_TYPE} WHEN 'critical_care' THEN 1.14 "
            "          WHEN 'telemetry' THEN 1.04 WHEN 'emergency' THEN 0.94 "
            "          ELSE 0.88 END)) "
            f"  * (1 + {seasonal(0.08, 'period', 21)}))::numeric, 0)"
        ),
        "budgeted_hours": "round((census_patients * 8.2)::numeric, 1)",
        "worked_hours": (
            f"round((budgeted_hours * (0.94 + 0.14 * {rnd(E, P, k('wh'))}))::numeric, 1)"
        ),
        # The vacancy tail pays for itself in overtime.
        "overtime_hours": (
            "round((worked_hours * "
            f" ((0.025 + 0.03 * {rnd(E, P, k('ot'))}) "
            f"  * (CASE WHEN {SHORT_STAFFED} THEN 3.1 ELSE 1.0 END)))::numeric, 1)"
        ),
        # Agency covers the night shift, and critical care hardest of all.
        "agency_hours": (
            "round((worked_hours * "
            f" ((0.02 + 0.03 * {rnd(E, P, k('ag'))}) "
            f"  * (CASE WHEN {_H3_SHIFT} = '{AGENCY_SHIFT}' THEN 3.4 ELSE 1.0 END) "
            f"  * (CASE WHEN {_H3_UNIT_TYPE} = '{AGENCY_UNIT_TYPE}' THEN 2.1 ELSE 1.0 END)))"
            "::numeric, 1)"
        ),
        "admissions": f"floor({rnd(E, P, k('adm'))} * 9)::int",
        "discharges": f"floor({rnd(E, P, k('dis'))} * 9)::int",
        # Boarding rises where the unit is closest to its staffed capacity: the
        # link the question about occupancy and boarding is meant to surface.
        "boarding_hours": (
            f"round(((0.4 + {rnd(E, P, k('brd'))} * 2.2) "
            "  * (1 + 4.0 * greatest(0, "
            "       (census_patients::numeric / NULLIF(staffed_beds, 0)) - 0.88)))::numeric, 2)"
        ),
        "call_offs": f"floor({rnd(E, P, k('co'))} * 3)::int",
        "vacancy_count": (
            f"(CASE WHEN {SHORT_STAFFED} THEN (3 + floor({rnd(E, k('vac'))} * 6))::int "
            f"      ELSE floor({rnd(E, k('vac'))} * 3)::int END)"
        ),
        "filled_shift": "(worked_hours >= budgeted_hours * 0.97)",
        "float_pool_used": f"({rnd(E, P, k('float'))} < 0.22)",
    },
    notes="agency on nights in critical care; boarding rises with occupancy; a vacancy tail pays overtime",
)


# ---------------------------------------------------------------------------
# DP-INS-003 — Policyholder & Distribution 360
# Planted: one distribution channel carries materially lower multi-line
# penetration, digital enrolment falls away in the longest tenure band, and
# complaints concentrate in one region and one segment together rather than in
# either alone.
# ---------------------------------------------------------------------------
INS3_SEGMENTS = [("mass", 5), ("preferred", 3), ("commercial", 2)]
INS3_CHANNELS = [("agency", 5), ("direct", 3), ("affinity", 2)]
INS3_TENURE = [("0-2y", 3), ("3-5y", 3), ("6-10y", 2), ("10y+", 2)]
LOW_MULTILINE_CHANNEL = "affinity"
LOW_DIGITAL_TENURE = "10y+"
COMPLAINT_REGION = "Southeast"
COMPLAINT_SEGMENT = "commercial"

_I3_SEGMENT = weighted(INS3_SEGMENTS, E, k("seg"))
_I3_CHANNEL = weighted(INS3_CHANNELS, E, k("chan"))
_I3_TENURE = weighted(INS3_TENURE, E, k("ten"))
_I3_REGION = pick(["Northeast", "Southeast", "Midwest", "West"], E, k("reg"))

DP_INS_003 = _spec(
    "DP-INS-003",
    entity_column="customer_id", entity_count=24000,
    time_column="as_of_month", grain="month", periods=24,
    expressions={
        "customer_id": "('PCUST-' || lpad(entity::text, 8, '0'))",
        "household_id": (
            f"(CASE WHEN {rnd(E, k('hh'))} < 0.88 "
            "       THEN ('HH-' || lpad((entity / 2)::text, 8, '0')) END)"
        ),
        "as_of_month": "date_trunc('month', period_at)::date",
        "segment": _I3_SEGMENT,
        "region": _I3_REGION,
        "distribution_channel": _I3_CHANNEL,
        "agency_id": (
            f"(CASE WHEN {_I3_CHANNEL} = 'agency' "
            "       THEN ('AGY-' || lpad((1 + (entity % 30))::text, 4, '0')) END)"
        ),
        "tenure_band": _I3_TENURE,
        # The multi-line gap: affinity business is sold one line at a time.
        "coverage_lines_held": (
            # The affinity multiplier stays above the level at which the floor
            # can still reach one. Pushed lower it produces a channel with
            # literally no multi-line customers, which is a generator artefact
            # rather than the penetration gap the question is looking for.
            f"(1 + floor({rnd(E, P, k('lines'))} * 1.7 "
            f"  * (CASE WHEN {_I3_CHANNEL} = '{LOW_MULTILINE_CHANNEL}' THEN 0.75 ELSE 1.0 END)))"
            "::int"
        ),
        "multi_line": "(coverage_lines_held > 1)",
        "policies_held": (
            f"(coverage_lines_held + floor({rnd(E, P, k('pol'))} * 1.4))::int"
        ),
        "total_written_premium": (
            f"round((policies_held * (420 + {rnd(E, P, k('prem'))} * 2600))::numeric, 2)"
        ),
        # The digital cliff: the longest-tenured customers never registered.
        "digital_registered": (
            f"({rnd(E, P, k('dig'))} < "
            f"  (CASE WHEN {_I3_TENURE} = '{LOW_DIGITAL_TENURE}' THEN 0.24 ELSE 0.71 END))"
        ),
        "autopay_enrolled": f"({rnd(E, P, k('auto'))} < 0.58)",
        "service_contacts_90d": f"floor({rnd(E, P, k('svc'))} * 6)::int",
        # The interaction: neither the region nor the segment alone explains it.
        "complaints_90d": (
            f"(CASE WHEN {rnd(E, P, k('cmp'))} < "
            "       0.018"
            f"       * (CASE WHEN {_I3_REGION} = '{COMPLAINT_REGION}' "
            f"                 AND {_I3_SEGMENT} = '{COMPLAINT_SEGMENT}' THEN 6.0 ELSE 1.0 END)"
            f"      THEN (1 + floor({rnd(E, P, k('cmpn'))} * 3))::int ELSE 0 END)"
        ),
        "nps_response": (
            f"(CASE WHEN {rnd(E, P, k('nps'))} < 0.31 "
            f"      THEN (1 + floor({rnd(E, P, k('npsv'))} * 10))::int END)"
        ),
        "cross_sell_eligible": f"({rnd(E, P, k('xe'))} < 0.34)",
        "cross_sell_accepted": (
            f"(cross_sell_eligible AND {rnd(E, P, k('xa'))} < "
            "  (CASE WHEN multi_line THEN 0.19 ELSE 0.08 END))"
        ),
        "lapsed": f"({rnd(E, P, k('lapse'))} < 0.004)",
    },
    notes="affinity is single-line; 10y+ never registered digitally; complaints are Southeast x commercial",
)

# ---------------------------------------------------------------------------
# DP-MFG-003 — Equipment Reliability & Maintenance
# Planted: one asset class fails far more often than the rest and carries the
# oldest installed base; repairs waiting on a part take materially longer; and
# preventive adherence slips on one line, whose unplanned share rises with it.
# ---------------------------------------------------------------------------
MFG3_ASSET_CLASSES = [("conveyor", 3), ("press", 2), ("robot_cell", 3),
                      ("packaging_head", 2), ("compressor", 2)]
MFG3_CRITICALITY = [("line_stopper", 3), ("degrader", 4), ("nuisance", 3)]
MFG3_MODES = ["bearing_wear", "seal_failure", "control_fault", "lubrication", "alignment"]
MFG3_LINES = ["LINE-1", "LINE-2", "LINE-3", "LINE-4"]
# The class that fails, and the line whose plan slips.
FAILING_CLASS = "compressor"
SLIPPING_LINE = "LINE-2"

_M3_CLASS = weighted(MFG3_ASSET_CLASSES, E, k("acls"))
_M3_LINE = pick(MFG3_LINES, E, k("line"))
_M3_UNPLANNED = (
    f"({rnd(E, P, k('unp'))} < "
    "  0.17"
    f"  * (CASE WHEN {_M3_CLASS} = '{FAILING_CLASS}' THEN 1.9 ELSE 1.0 END)"
    f"  * (CASE WHEN {_M3_LINE} = '{SLIPPING_LINE}' THEN 1.5 ELSE 1.0 END))"
)

_M3_SPARES_AVAILABLE = f"({rnd(E, P, k('spav'))} < 0.88)"

DP_MFG_003 = _spec(
    "DP-MFG-003",
    entity_column="work_order_id", entity_count=2600,
    time_column="raised_at", grain="day", periods=120,
    expressions={
        "work_order_id": "('WO-' || lpad(entity::text, 8, '0') || '-' || period::text)",
        # Assets recur across orders, which is what makes hours between failures
        # a meaningful thing to divide by.
        "asset_id": "('AST-' || lpad((1 + (entity % 240))::text, 5, '0'))",
        "raised_at": "period_at",
        "plant": weighted([("plant_north", 4), ("plant_south", 3), ("plant_east", 3)], E,
                          k("plant")),
        "line": _M3_LINE,
        "region": pick(["Northeast", "Southeast", "Midwest", "West"], E, k("reg")),
        "asset_class": _M3_CLASS,
        "criticality": weighted(MFG3_CRITICALITY, E, k("crit")),
        "crew": pick(["crew_a", "crew_b", "crew_c"], E, P, k("crew")),
        "unplanned": _M3_UNPLANNED,
        "preventive_scheduled": f"(NOT {_M3_UNPLANNED})",
        # A failure belongs to the order that addressed it, so counting failures
        # does not count the orders that found nothing.
        "failure_id": (
            f"(CASE WHEN {_M3_UNPLANNED} "
            "       THEN ('FLR-' || lpad(entity::text, 8, '0') || '-' || period::text) END)"
        ),
        "failure_mode": (
            f"(CASE WHEN {_M3_UNPLANNED} THEN {pick(MFG3_MODES, E, P, k('mode'))} END)"
        ),
        # The ageing class runs fewer hours between failures than the rest.
        "operating_hours": (
            f"round(((160 + {rnd(E, P, k('oph'))} * 900) "
            f"  * (CASE WHEN {_M3_CLASS} = '{FAILING_CLASS}' THEN 0.42 ELSE 1.0 END))"
            "::numeric, 1)"
        ),
        "spares_needed": f"({_M3_UNPLANNED} OR {rnd(E, P, k('spn'))} < 0.36)",
        "spares_available": f"(spares_needed AND {_M3_SPARES_AVAILABLE})",
        # Where the repair time actually goes: waiting for a part.
        "repair_minutes": (
            f"(CASE WHEN {_M3_UNPLANNED} "
            f"      THEN round(((45 + {rnd(E, P, k('rep'))} * 190) "
            f"        * (CASE WHEN NOT {_M3_SPARES_AVAILABLE} THEN 2.8 ELSE 1.0 END))"
            "::numeric, 1) ELSE 0 END)"
        ),
        "maintenance_hours": (
            f"round(((1.2 + {rnd(E, P, k('mh'))} * 5.5) "
            f"  + (CASE WHEN {_M3_UNPLANNED} THEN 2.4 ELSE 0 END))::numeric, 2)"
        ),
        # The plan slips on one line, which is where its breakdowns come from.
        "completed_in_window": (
            f"(NOT {_M3_UNPLANNED} AND {rnd(E, P, k('ciw'))} < "
            f"  (CASE WHEN {_M3_LINE} = '{SLIPPING_LINE}' THEN 0.71 ELSE 0.945 END))"
        ),
        "condition_alert_open": (
            f"({rnd(E, P, k('cond'))} < "
            f"  (CASE WHEN {_M3_UNPLANNED} THEN 0.41 ELSE 0.12 END))"
        ),
        "asset_age_years": (
            f"round(((1.5 + {rnd(E, k('age'))} * 12) "
            f"  + (CASE WHEN {_M3_CLASS} = '{FAILING_CLASS}' THEN 9 ELSE 0 END))::numeric, 1)"
        ),
    },
    notes="compressors fail oldest and hardest; missing spares triple repair time; LINE-2 plan slips",
)

ALL_SPECS = [
    DP_TEL_001, DP_TEL_002, DP_TCH_001, DP_BNK_001, DP_BNK_002, DP_INS_001, DP_INS_002,
    DP_HLT_001, DP_HLT_002, DP_RTL_001, DP_RTL_002, DP_RTL_003, DP_TRN_001, DP_UTL_001,
    DP_ENG_001, DP_MFG_001,
    DP_BNK_003, DP_TCH_002, DP_TRN_002, DP_MFG_002, DP_HLT_003, DP_INS_003,
    DP_MFG_003,
]
