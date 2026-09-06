"""M8 — the workflow rails, and the two acceptance criteria they exist for.

    an approved request provisions a scoped platform role, binds purpose and
    expiry, and writes an immutable audit record;

    a new-supply request matching a seed product at >= 0.75 is blocked pending
    owner review with the candidate shown side by side.

Both are tested here against the real policy, the real estate and the real
embedder, because both are claims about what this deployment actually does.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from services.common.rubrics import load_current
from services.search import embedding
from services.workflow import access, demand, engine, enhancement, policy

TENANT = os.environ.get("TENANT_ID", "TEN-DEMO")
STEWARD = "PTY-0031"
CONSUMER = "PTY-0062"
OWNER = "PTY-0051"

# An internal product with no PII: the only shape that can auto-approve.
OPEN_PRODUCT = "DP-MFG-001"
# Confidential with classified columns: owner plus steward.
CLASSIFIED_PRODUCT = "DP-HLT-002"
# Carries PII: the strictest path, whoever asks.
PII_PRODUCT = "DP-TEL-001"


@pytest.fixture()
def governance(db):
    return load_current(db, "governance")


@pytest.fixture()
def demand_rubric(db):
    embedding.configure_from_rubric(load_current(db, embedding.RUBRIC_CODE))
    return load_current(db, "demand_scoring")


# ---------------------------------------------------------------------------
# Policy evaluation
# ---------------------------------------------------------------------------


def test_the_preview_and_the_engine_read_the_same_evaluation(db, governance) -> None:
    """A path shown in the form and a path taken at submission must not differ."""
    preview = policy.evaluate(
        db, asset_type="data_product", asset_id=OPEN_PRODUCT,
        requester_party_id=STEWARD, purpose_code="analytics",
    )
    created = access.create(
        db, TENANT, request_id="REQ-SAME", requester_party_id=STEWARD,
        asset_type="data_product", asset_id=OPEN_PRODUCT, columns=["work_order_id"],
        purpose_code="analytics", purpose_text="line review",
    )
    assert created["evaluation"]["path"] == preview.path
    assert created["evaluation"]["policy_version_id"] == preview.policy_version_id


@pytest.mark.parametrize(
    ("product", "requester", "expected"),
    [
        (OPEN_PRODUCT, STEWARD, "auto"),
        (OPEN_PRODUCT, CONSUMER, "owner"),
        (CLASSIFIED_PRODUCT, CONSUMER, "owner_steward"),
        (PII_PRODUCT, STEWARD, "owner_privacy_security"),
    ],
)
def test_the_path_follows_the_asset_and_the_asker(
    db, product: str, requester: str, expected: str
) -> None:
    evaluation = policy.evaluate(
        db, asset_type="data_product", asset_id=product,
        requester_party_id=requester, purpose_code="analytics",
    )
    assert evaluation.path == expected
    assert evaluation.reasons, "a path with no stated reason is not a preview"


def test_a_forbidden_purpose_is_blocked_and_says_so(db) -> None:
    """purposes_by_sensitivity is a statement about what this estate will not do."""
    evaluation = policy.evaluate(
        db, asset_type="data_product", asset_id=CLASSIFIED_PRODUCT,
        requester_party_id=STEWARD, purpose_code="model_training",
    )
    assert evaluation.blocked
    assert "not a permitted purpose" in " ".join(evaluation.reasons)


def test_an_sla_lands_on_a_business_day(db) -> None:
    """A due date on a Saturday is a date nobody can act on."""
    friday = datetime(2026, 9, 4, 16, 0, tzinfo=UTC)
    assert friday.weekday() == 4
    evaluation = policy.evaluate(
        db, asset_type="data_product", asset_id=OPEN_PRODUCT,
        requester_party_id=CONSUMER, purpose_code="analytics", at=friday,
    )
    assert evaluation.due_at is not None
    assert evaluation.due_at.weekday() not in policy.WEEKEND
    assert evaluation.due_at > friday + timedelta(days=1)


def test_an_unknown_predicate_refuses_rather_than_passing(db) -> None:
    facts = policy.gather(
        db, asset_type="data_product", asset_id=OPEN_PRODUCT,
        requester_party_id=STEWARD, purpose_code="analytics",
    )
    with pytest.raises(policy.PolicyUnavailableError):
        policy._predicate("a_condition_nobody_implemented", True, facts, {})


# ---------------------------------------------------------------------------
# M8.1 / M8.2 acceptance
# ---------------------------------------------------------------------------


def test_an_approved_request_provisions_binds_and_audits(db, governance) -> None:
    """The M8 acceptance criterion, in one test.

    A scoped platform role, a bound purpose, an expiry, and an audit record that
    cannot be edited afterwards.
    """
    access.create(
        db, TENANT, request_id="REQ-ACC", requester_party_id=CONSUMER,
        asset_type="data_product", asset_id="DP-RTL-002",
        columns=["sku", "on_hand_units"], purpose_code="operational_planning",
        purpose_text="Weekly availability review",
    )
    access.submit(db, TENANT, request_id="REQ-ACC", actor=CONSUMER, governance=governance)
    result = access.decide(
        db, TENANT, request_id="REQ-ACC", approver_party_id=OWNER,
        outcome=access.OUTCOME_APPROVED, reason="standard planning access",
        governance=governance,
    )
    provisioned = result["provisioned"]

    # 1. a scoped platform role, derived not typed
    assert provisioned["platform_role"] == "MKT_DP_RTL_002_READ_DATA"
    assert provisioned["oauth_scopes"] == ["dp:DP-RTL-002:read"]
    # 2. purpose bound to the grant
    assert provisioned["purpose_code"] == "operational_planning"
    # 3. an expiry, from the policy rather than from code
    rules = policy.load_rules(db)[1]
    expires = datetime.fromisoformat(provisioned["expires_at"])
    assert expires > datetime.now(UTC)
    assert expires <= datetime.now(UTC) + timedelta(
        days=int(rules["grant"]["duration_days"]) + 1
    )
    # 4. the columns approved, and only those
    assert set(provisioned["columns"]) == {"sku", "on_hand_units"}

    with db.cursor() as cursor:
        cursor.execute(
            "SELECT event_name, asset_id, purpose_code, detail FROM audit_event "
            "WHERE audit_id = %s",
            (provisioned["audit_id"],),
        )
        record = cursor.fetchone()
    assert record["event_name"] == access.EVENT_PROVISIONED
    assert record["asset_id"] == "DP-RTL-002"
    assert record["detail"]["platform_role"] == provisioned["platform_role"]


def test_the_audit_record_cannot_be_edited(db, governance) -> None:
    """Append-only is a database trigger, not a convention."""
    import psycopg

    access.create(
        db, TENANT, request_id="REQ-IMM", requester_party_id=STEWARD,
        asset_type="data_product", asset_id=OPEN_PRODUCT, columns=["work_order_id"],
        purpose_code="analytics", purpose_text="x",
    )
    result = access.submit(
        db, TENANT, request_id="REQ-IMM", actor=STEWARD, governance=governance
    )
    audit_id = result["provisioned"]["audit_id"]

    with pytest.raises(psycopg.errors.RestrictViolation), db.cursor() as cursor:
        cursor.execute(
            "UPDATE audit_event SET outcome = 'something else' WHERE audit_id = %s",
            (audit_id,),
        )


def test_an_auto_approved_request_records_the_policy_as_its_actor(db, governance) -> None:
    """"The policy approved it" is a better record than an approval with no approver."""
    access.create(
        db, TENANT, request_id="REQ-AUTO", requester_party_id=STEWARD,
        asset_type="data_product", asset_id=OPEN_PRODUCT, columns=["work_order_id"],
        purpose_code="analytics", purpose_text="x",
    )
    access.submit(db, TENANT, request_id="REQ-AUTO", actor=STEWARD, governance=governance)
    moves = engine.history(db, engine.TYPE_ACCESS, "REQ-AUTO")
    approval = next(move for move in moves if move["to_state"] == engine.ACCESS_APPROVED)
    assert approval["actor"].startswith("PV-"), approval["actor"]
    assert approval["detail"]["automatic"] is True


def test_a_blocked_request_is_not_submittable(db, governance) -> None:
    access.create(
        db, TENANT, request_id="REQ-BLK", requester_party_id=STEWARD,
        asset_type="data_product", asset_id=CLASSIFIED_PRODUCT, columns=["ndc_code"],
        purpose_code="model_training", purpose_text="train a model",
    )
    with pytest.raises(access.RequestRefusedError) as error:
        access.submit(db, TENANT, request_id="REQ-BLK", actor=STEWARD, governance=governance)
    assert "not a permitted purpose" in str(error.value)

    instance = engine.load(db, engine.TYPE_ACCESS, "REQ-BLK")
    assert instance.state == engine.ACCESS_BLOCKED
    assert instance.terminal


def test_a_partial_approval_must_say_what_was_withheld(db, governance) -> None:
    access.create(
        db, TENANT, request_id="REQ-PART", requester_party_id=CONSUMER,
        asset_type="data_product", asset_id="DP-RTL-001",
        columns=["net_sales", "category"], purpose_code="analytics", purpose_text="x",
    )
    access.submit(db, TENANT, request_id="REQ-PART", actor=CONSUMER, governance=governance)
    with pytest.raises(access.RequestRefusedError):
        access.decide(
            db, TENANT, request_id="REQ-PART", approver_party_id=OWNER,
            outcome=access.OUTCOME_PARTIAL, reason="   ", governance=governance,
        )


def test_a_decline_must_carry_a_reason(db, governance) -> None:
    access.create(
        db, TENANT, request_id="REQ-DEC", requester_party_id=CONSUMER,
        asset_type="data_product", asset_id="DP-RTL-001", columns=["net_sales"],
        purpose_code="analytics", purpose_text="x",
    )
    access.submit(db, TENANT, request_id="REQ-DEC", actor=CONSUMER, governance=governance)
    with pytest.raises(access.RequestRefusedError):
        access.decide(
            db, TENANT, request_id="REQ-DEC", approver_party_id=OWNER,
            outcome=access.OUTCOME_DECLINED, reason="", governance=governance,
        )


# ---------------------------------------------------------------------------
# The engine's own rules
# ---------------------------------------------------------------------------


def test_a_state_cannot_be_reached_except_through_a_declared_edge(db) -> None:
    """A request cannot become Provisioned without having been Approved."""
    engine.start(
        db, TENANT, workflow_type=engine.TYPE_ACCESS, subject_id="REQ-SKIP",
        actor=STEWARD,
    )
    with pytest.raises(engine.IllegalTransitionError) as error:
        engine.transition(
            db, TENANT, workflow_type=engine.TYPE_ACCESS, subject_id="REQ-SKIP",
            to_state=engine.ACCESS_PROVISIONED, actor=STEWARD,
        )
    assert "draft" in str(error.value)


def test_a_transition_must_name_its_actor(db) -> None:
    engine.start(
        db, TENANT, workflow_type=engine.TYPE_ACCESS, subject_id="REQ-ANON", actor=STEWARD
    )
    with pytest.raises(engine.IllegalTransitionError):
        engine.transition(
            db, TENANT, workflow_type=engine.TYPE_ACCESS, subject_id="REQ-ANON",
            to_state=engine.ACCESS_EVALUATED, actor="",
        )


def test_the_history_reads_in_the_order_it_happened(db, governance) -> None:
    """Transitions committed together must not sort by id."""
    access.create(
        db, TENANT, request_id="REQ-ORD", requester_party_id=STEWARD,
        asset_type="data_product", asset_id=OPEN_PRODUCT, columns=["work_order_id"],
        purpose_code="analytics", purpose_text="x",
    )
    access.submit(db, TENANT, request_id="REQ-ORD", actor=STEWARD, governance=governance)
    states = [move["to_state"] for move in engine.history(db, engine.TYPE_ACCESS, "REQ-ORD")]
    assert states == [
        engine.ACCESS_DRAFT, engine.ACCESS_EVALUATED, engine.ACCESS_APPROVED,
        engine.ACCESS_PROVISIONED, engine.ACCESS_ACTIVE,
    ]


# ---------------------------------------------------------------------------
# M8.4 acceptance — duplicate supply
# ---------------------------------------------------------------------------


def test_a_restatement_of_a_seed_product_is_blocked_with_the_candidate(
    db, demand_rubric
) -> None:
    """The M8 acceptance criterion for demand intake."""
    check = demand.check_duplicates(
        db, demand_rubric,
        request_text="A view of subscriber churn and retention performance by segment "
                     "and region",
        entities=["subscriber_id", "churn_flag", "segment", "region"],
        sources=["SRC-BILLING"],
        kpis=["KPI-CHURN-001"],
    )
    assert check.verdict == demand.VERDICT_BLOCKING
    assert check.blocking

    best = check.matches[0]
    assert best.candidate_id == "DP-TEL-001"
    assert best.similarity >= float(demand_rubric.number(demand.BLOCKING_PATH))
    # Shown side by side means the reviewer gets the candidate's identity, the
    # score, what drove it and how much evidence there was.
    assert best.candidate_name
    assert set(best.contributing_factors) == {
        "embedding_match", "entity_overlap", "source_overlap", "kpi_overlap"
    }
    assert best.rationale
    assert best.confidence > 0


def test_genuinely_new_demand_passes_through(db, demand_rubric) -> None:
    check = demand.check_duplicates(
        db, demand_rubric,
        request_text="Carbon emissions by supplier tier for our scope 3 disclosure",
        entities=["supplier_id", "emissions_tco2e"],
    )
    assert check.verdict == demand.VERDICT_CLEAR
    assert not check.matches


def test_a_thin_request_does_not_block_on_a_coincidence(db, demand_rubric) -> None:
    """Confidence is evidence, not similarity.

    A high score computed from four words is a coincidence, and the rubric sends
    it to architect review rather than showing it to the requester as blocking.
    """
    floor = float(demand_rubric.number(demand.CONFIDENCE_FLOOR_PATH))
    check = demand.check_duplicates(
        db, demand_rubric, request_text="subscriber churn retention segment region",
    )
    assert check.verdict != demand.VERDICT_BLOCKING
    if check.matches:
        assert check.matches[0].confidence < floor


def test_a_blocking_match_stops_the_item_for_review(db, demand_rubric) -> None:
    result = demand.submit(
        db, TENANT, demand_rubric, demand_id="DEM-DUP", request_id="REQ-DUP",
        requester_party_id=CONSUMER,
        title="Subscriber churn and retention view",
        body="We need churn and retention performance by segment and region.",
        entities=["subscriber_id", "churn_flag", "segment", "region"],
        sources=["SRC-BILLING"], kpis=["KPI-CHURN-001"],
    )
    assert result["duplicate_check"]["blocking"]
    assert engine.load(db, engine.TYPE_DEMAND, "DEM-DUP").state == engine.DEM_DUPLICATE_REVIEW


def test_a_vote_without_a_use_case_is_not_counted(db, demand_rubric) -> None:
    demand.submit(
        db, TENANT, demand_rubric, demand_id="DEM-VOTE", request_id="REQ-VOTE",
        requester_party_id=CONSUMER, title="Supplier emissions",
        body="Scope 3 emissions by supplier tier.",
    )
    with pytest.raises(demand.DemandRefusedError) as error:
        demand.vote(
            db, TENANT, demand_id="DEM-VOTE", voter_party_id=STEWARD, use_case="  "
        )
    assert "use case" in str(error.value)

    counted = demand.vote(
        db, TENANT, demand_id="DEM-VOTE", voter_party_id=STEWARD,
        use_case="We report scope 3 quarterly and assemble it by hand.",
    )
    assert counted["votes"] == 1


def test_scoring_records_the_breakdown_and_the_rubric_version(db, demand_rubric) -> None:
    demand.submit(
        db, TENANT, demand_rubric, demand_id="DEM-SCORE", request_id="REQ-SCORE",
        requester_party_id=CONSUMER, title="Supplier emissions",
        body="Scope 3 emissions by supplier tier.",
    )
    result = demand.score(
        db, TENANT, demand_rubric, demand_id="DEM-SCORE", actor=STEWARD,
        assessments=dict.fromkeys(demand.CRITERIA, 0.8),
    )
    assert set(result["breakdown"]) == set(demand.CRITERIA)
    for entry in result["breakdown"].values():
        assert {"weight", "assessment", "contribution"} == set(entry)

    with db.cursor() as cursor:
        cursor.execute(
            "SELECT rubric_version_id, score FROM demand_item WHERE demand_id = %s",
            ("DEM-SCORE",),
        )
        row = cursor.fetchone()
    assert row["rubric_version_id"] == demand_rubric.rubric_version_id


def test_every_criterion_must_be_assessed(db, demand_rubric) -> None:
    demand.submit(
        db, TENANT, demand_rubric, demand_id="DEM-PART", request_id="REQ-PART2",
        requester_party_id=CONSUMER, title="x", body="y",
    )
    with pytest.raises(demand.DemandRefusedError):
        demand.score(
            db, TENANT, demand_rubric, demand_id="DEM-PART", actor=STEWARD,
            assessments={"business_value": 0.9},
        )


# ---------------------------------------------------------------------------
# M8.3 — the public backlog
# ---------------------------------------------------------------------------


def test_a_decline_needs_a_controlled_reason_and_free_text(db, demand_rubric) -> None:
    enhancement.submit(
        db, TENANT, demand_rubric, request_id="REQ-ENH", requester_party_id=CONSUMER,
        asset_type="data_product", asset_id="DP-RTL-001",
        title="Add promotion attribution", body="We cannot see incremental margin.",
    )
    for state in (engine.ENH_TRIAGED, engine.ENH_ASSESSED):
        enhancement.advance(db, TENANT, request_id="REQ-ENH", to_state=state, actor=OWNER)

    with pytest.raises(enhancement.EnhancementRefusedError):
        enhancement.advance(
            db, TENANT, request_id="REQ-ENH", to_state=engine.ENH_DECLINED, actor=OWNER,
            reason_code="i_dont_want_to", reason_text="no",
        )
    with pytest.raises(enhancement.EnhancementRefusedError):
        enhancement.advance(
            db, TENANT, request_id="REQ-ENH", to_state=engine.ENH_DECLINED, actor=OWNER,
            reason_code="out_of_scope", reason_text="",
        )

    result = enhancement.advance(
        db, TENANT, request_id="REQ-ENH", to_state=engine.ENH_DECLINED, actor=OWNER,
        reason_code="source_unavailable",
        reason_text="Promotion attribution is not in any source we read.",
    )
    assert result["reason_code"] == "source_unavailable"


def test_a_declined_item_stays_on_the_public_backlog_with_its_reason(
    db, demand_rubric
) -> None:
    """Hiding declines makes the backlog look healthier and the estate less trusted."""
    enhancement.submit(
        db, TENANT, demand_rubric, request_id="REQ-PUB", requester_party_id=CONSUMER,
        asset_type="data_product", asset_id="DP-RTL-001", title="A thing", body="Because.",
    )
    for state in (engine.ENH_TRIAGED, engine.ENH_ASSESSED):
        enhancement.advance(db, TENANT, request_id="REQ-PUB", to_state=state, actor=OWNER)
    enhancement.advance(
        db, TENANT, request_id="REQ-PUB", to_state=engine.ENH_DECLINED, actor=OWNER,
        reason_code="cost_prohibitive", reason_text="The build outweighs the benefit.",
    )

    listed = {row["request_id"]: row for row in enhancement.backlog(db)}
    assert "REQ-PUB" in listed
    assert listed["REQ-PUB"]["state"] == engine.ENH_DECLINED
    assert listed["REQ-PUB"]["decline"]["reason_code"] == "cost_prohibitive"
    assert listed["REQ-PUB"]["decline"]["reason_text"]


def test_a_demand_for_an_agent_is_compared_against_agents(db, demand_rubric) -> None:
    """"We already have one of these" is a claim about the same sort of asset.

    Comparing a demand for an agent against the product catalogue answers a
    question nobody asked: a churn agent does not read like a churn product, so
    the check comes back clear and the requester is told to build something the
    estate already runs.
    """
    text = (
        "An agent that watches subscriber churn and tells retention which "
        "cohorts are leaving."
    )
    against_agents = demand.check_duplicates(
        db, demand_rubric, request_text=text, kpis=["KPI-CHURN-001"],
        entities=["subscriber", "churn"], sources=["DP-TEL-001"],
        kind=demand.KIND_AGENT,
    )
    assert against_agents.verdict != demand.VERDICT_CLEAR
    assert against_agents.matches[0].candidate_id.startswith("AG-")


def test_the_default_comparison_is_still_the_product_catalogue(db, demand_rubric) -> None:
    """The submission path has always meant products, and adding a kind must not
    quietly move it."""
    text = "Subscriber churn and retention across the base, by cohort and region."
    default = demand.check_duplicates(
        db, demand_rubric, request_text=text, kpis=["KPI-CHURN-001"],
        entities=["subscriber", "churn"], sources=["SRC-CRM-01"],
    )
    explicit = demand.check_duplicates(
        db, demand_rubric, request_text=text, kpis=["KPI-CHURN-001"],
        entities=["subscriber", "churn"], sources=["SRC-CRM-01"],
        kind=demand.KIND_PRODUCT,
    )
    assert default.document() == explicit.document()
    for match in default.matches:
        assert match.candidate_id.startswith("DP-")


def test_an_unknown_kind_of_demand_is_refused(db, demand_rubric) -> None:
    with pytest.raises(ValueError):
        demand.check_duplicates(
            db, demand_rubric, request_text="anything at all", kind="banana"
        )
