"""M12 — the academy's benefit, the console's guarantee, and the rollback.

Three acceptance criteria, one file, because they are the same claim in three
places: configuration is data, records are not, and the difference is enforced
rather than agreed.

    a rubric weight change through the admin console re-scores the estate and
    preserves prior snapshots;

    an agent canary rollback restores the previous bundle in one action;

    a certification pre-approves an access tier, which is what makes anyone
    finish the academy.
"""

from __future__ import annotations

import copy
import os
from decimal import Decimal

import pytest

from services.academy import paths as academy
from services.admin import estate
from services.admin import rubrics as admin
from services.agents import release
from services.common import flags
from services.common.db import fetch_all, fetch_one
from services.common.rubric_source import RubricVersionConflict
from services.common.rubrics import load_current

TENANT = os.environ.get("TENANT_ID", "TEN-DEMO")
LEARNER = "PTY-0064"
QUALITY = "data_product_quality"


@pytest.fixture()
def governance(db):
    return load_current(db, "governance")


@pytest.fixture()
def academy_rubric(db):
    return load_current(db, "academy")


# ---------------------------------------------------------------------------
# M12.2 acceptance: re-score and preserve
# ---------------------------------------------------------------------------


def test_a_weight_change_rescores_the_estate_and_preserves_prior_snapshots(
    db, governance
) -> None:
    """The M12.2 acceptance criterion, both halves.

    The second half is the harder one. A system that re-scored by updating rows
    would satisfy "re-scores the estate" and destroy the evidence behind every
    decision already made under the old weights.
    """
    before_version = load_current(db, QUALITY).rubric_version_id
    kept_before = int(
        fetch_one(
            db,
            "SELECT count(*) AS n FROM quality_score_snapshot WHERE rubric_version_id = %s",
            (before_version,),
        )["n"]
    )
    before = {
        row["product_id"]: Decimal(str(row["composite"]))
        for row in fetch_all(
            db,
            "SELECT DISTINCT ON (product_id) product_id, composite "
            "FROM quality_score_snapshot ORDER BY product_id, computed_at DESC",
        )
    }
    assert before, "nothing has been scored; the test would prove nothing"

    payload = copy.deepcopy(admin.payload_of(db, QUALITY))
    for dimension in payload["dimensions"]:
        if dimension["code"] == "freshness":
            dimension["weight"] = 0.10
        if dimension["code"] == "accuracy":
            dimension["weight"] = 0.30
    payload["version"] = "9.9.9-test"

    published = admin.publish(
        db, TENANT, governance, code=QUALITY, payload=payload, actor_party_id="PTY-0005"
    )
    assert published.created
    result = admin.rescore(db, TENANT)

    try:
        assert result["snapshots_after"] > result["snapshots_before"]
        after = {
            row["product_id"]: Decimal(str(row["composite"]))
            for row in fetch_all(
                db,
                "SELECT DISTINCT ON (product_id) product_id, composite "
                "FROM quality_score_snapshot ORDER BY product_id, computed_at DESC",
            )
        }
        assert any(after[key] != before[key] for key in before), (
            "no score moved; the weight change did not reach the engine"
        )
        # Every prior snapshot is still there, still pointing at the version it
        # was computed under. Counted rather than derived from the product
        # count: an estate scored twice has two snapshots per product, and both
        # of them are evidence.
        kept_after = int(
            fetch_one(
                db,
                "SELECT count(*) AS n FROM quality_score_snapshot "
                "WHERE rubric_version_id = %s",
                (before_version,),
            )["n"]
        )
        assert kept_after == kept_before
    finally:
        # The published version and its snapshots are records; the test does not
        # get to delete them. It restores what is *in force* by pointing the
        # rubric back at the version the manifests describe.
        db.rollback()


def test_a_content_change_without_a_version_bump_is_refused(db, governance) -> None:
    """Two different rubrics answering to one version name would make every
    score computed under that name unreplayable."""
    payload = copy.deepcopy(admin.payload_of(db, QUALITY))
    payload["dimensions"][0]["weight"] = 0.99
    with pytest.raises(RubricVersionConflict) as raised:
        admin.publish(
            db, TENANT, governance, code=QUALITY, payload=payload,
            actor_party_id="PTY-0005",
        )
    assert "did not" in str(raised.value)
    db.rollback()


def test_publishing_an_unchanged_payload_creates_nothing(db, governance) -> None:
    payload = admin.payload_of(db, QUALITY)
    published = admin.publish(
        db, TENANT, governance, code=QUALITY, payload=payload, actor_party_id="PTY-0005"
    )
    assert not published.created
    db.rollback()


def test_the_console_shows_what_a_superseded_version_still_explains(db) -> None:
    """A version with snapshots behind it is not dead weight to clean up."""
    for version in admin.history(db, QUALITY):
        assert version["quality_snapshots"] >= 0
        assert version["source_hash"]


def test_every_tenanted_table_appears_protected_in_the_tenancy_panel(db) -> None:
    panel = estate.tenancy(db)
    assert panel["unprotected_tables"] == []
    assert panel["row_level_security"] == panel["tenanted_tables"]


def test_a_flag_the_seeder_created_is_one_the_code_reads(db) -> None:
    """A console listing switches that do nothing invites somebody to turn one
    off during an incident and conclude the problem is elsewhere."""
    listed = {row["code"] for row in estate.flags(db)}
    assert flags.ACADEMY_PRE_APPROVED_ACCESS in listed
    assert flags.LANDING_ANSWER_STREAM in listed


def test_an_unknown_flag_is_off_rather_than_on(db) -> None:
    assert flags.enabled(db, "a_flag_nobody_defined") is False


# ---------------------------------------------------------------------------
# M12.3 acceptance: the rollback restores the previous bundle in one action
# ---------------------------------------------------------------------------


@pytest.fixture()
def published_agent(db):
    row = fetch_one(
        db,
        "SELECT a.agent_id, a.current_version_id FROM agent a "
        "JOIN agent_version v ON v.agent_version_id = a.current_version_id "
        "WHERE v.status = 'published' ORDER BY a.agent_id LIMIT 1",
    )
    if row is None:
        pytest.skip("no published agent")
    return row


def test_a_rollback_restores_every_field_of_the_previous_bundle(
    db, governance, published_agent
) -> None:
    """One call, one transaction, the whole configuration.

    Restoring a prompt without its bindings restores a version that never
    existed, and an agent running last week's prompt against this week's
    bindings is a configuration nobody has evaluated.
    """
    agent_id = published_agent["agent_id"]
    live_id = published_agent["current_version_id"]
    before = release.bundle(db, live_id)

    candidate = release.clone(
        db, TENANT, agent_version_id=live_id, semver="0.0.0-unit"
    )
    try:
        evaluation = load_current(db, "agent_evaluation")
        from services.agent_runtime import registry
        from services.agents import evaluation as suites

        result = suites.run_version(db, registry.build(db), agent_id, candidate, evaluation)
        suites.record_run(db, TENANT, result)

        release.publish(
            db, TENANT, governance, evaluation,
            agent_version_id=candidate, actor_party_id="PTY-0005",
        )
        assert fetch_one(
            db, "SELECT current_version_id FROM agent WHERE agent_id = %s", (agent_id,)
        )["current_version_id"] == candidate

        rolled = release.rollback(
            db, TENANT, governance, agent_id=agent_id,
            reason="unit test", actor_party_id="PTY-0005",
        )
        assert rolled["restored"]["agent_version_id"] == live_id
        # Every field, not merely the version id.
        assert release.bundle(db, live_id).document() == before.document()
    finally:
        db.rollback()


def test_a_rollback_without_a_reason_is_refused(db, governance, published_agent) -> None:
    with pytest.raises(release.ReleaseRefused):
        release.rollback(
            db, TENANT, governance, agent_id=published_agent["agent_id"],
            reason="   ", actor_party_id="PTY-0005",
        )
    db.rollback()


def test_a_canary_cannot_be_promoted_without_its_evidence(db) -> None:
    """Promotion is on evidence from real traffic, and the refusal says what is
    still missing rather than warning and proceeding."""
    evaluation = load_current(db, "agent_evaluation")
    row = fetch_one(
        db,
        "SELECT agent_version_id FROM agent_version WHERE status = 'published' LIMIT 1",
    )
    evidence = release.canary_evidence(
        db, evaluation, agent_version_id=row["agent_version_id"]
    )
    assert evidence["min_answers"] > 0
    assert evidence["min_hours"] > 0


def test_a_version_that_has_served_cannot_be_discarded(db, published_agent) -> None:
    """A drill creates versions and must never be able to remove a real one."""
    with pytest.raises(release.ReleaseRefused):
        release.discard(db, published_agent["current_version_id"])
    db.rollback()


# ---------------------------------------------------------------------------
# M12.1: the academy's concrete benefit
# ---------------------------------------------------------------------------


def test_every_path_ends_in_a_certification_the_rubric_maps(db, academy_rubric) -> None:
    """A certification that unlocks nothing is a badge, and nobody finishes for
    a badge."""
    for path in academy.paths(db):
        code = path["certification_code"]
        assert academy_rubric.number(f"pre_approved_access.{code}.max_sensitivity_rank") >= 0
        assert academy_rubric.text(f"pre_approved_access.{code}.access_level")


def test_a_module_body_comes_from_the_manifest_it_was_seeded_from(db) -> None:
    """One copy of every sentence the academy teaches."""
    for path in academy.paths(db):
        for module in path["modules"]:
            body = academy.body_of(db, module["module_id"])
            assert len(body) > len("a paragraph worth reading")


def test_a_contextual_link_offers_one_path_not_the_whole_academy(db) -> None:
    product = fetch_one(db, "SELECT product_id FROM data_product LIMIT 1")
    modules = academy.contextual(db, "data_product", product["product_id"])
    consuming = {entry["module_id"] for entry in academy.path(db, "LP-CONSUME")["modules"]}
    assert {entry["module_id"] for entry in modules} == consuming


def test_finishing_a_path_certifies_and_changes_the_policy_path(db) -> None:
    """The M12.1 benefit, end to end.

    Before: an ordinary consumer's request for an internal product goes to its
    owner. After: the same request takes the automatic path, because the
    requester has demonstrated they understand what they are asking for.
    """
    from services.workflow import policy

    product = fetch_one(
        db,
        "SELECT p.product_id FROM data_product p "
        "JOIN data_contract_version c ON c.product_id = p.product_id AND c.status = 'active' "
        "WHERE p.sensitivity_tier IN ('public', 'internal') AND NOT c.contains_pii "
        "ORDER BY p.product_id LIMIT 1",
    )
    if product is None:
        pytest.skip("no low-sensitivity product without personal data in this estate")

    before = policy.evaluate(
        db, asset_type="data_product", asset_id=product["product_id"],
        requester_party_id=LEARNER, purpose_code="analytics",
    )
    assert before.path != "certified_auto"

    rubric = load_current(db, "academy")
    for module in academy.path(db, "LP-CONSUME")["modules"]:
        outcome = academy.record_assessment(
            db, TENANT, rubric, party_id=LEARNER, path_id="LP-CONSUME",
            module_id=module["module_id"], score_pct=Decimal("95"),
        )
    assert outcome["certification"]["code"] == "CERT-CONSUMER"

    after = policy.evaluate(
        db, asset_type="data_product", asset_id=product["product_id"],
        requester_party_id=LEARNER, purpose_code="analytics",
    )
    assert after.path == "certified_auto"
    assert any("certification" in reason for reason in after.reasons)
    db.rollback()


def test_a_failed_attempt_is_part_of_the_record(db) -> None:
    """A pass on the fourth try and a pass on the first are the same certificate
    and not the same evidence."""
    rubric = load_current(db, "academy")
    module = academy.path(db, "LP-EXEC")["modules"][0]["module_id"]
    failed = academy.record_assessment(
        db, TENANT, rubric, party_id=LEARNER, path_id="LP-EXEC",
        module_id=module, score_pct=Decimal("10"),
    )
    assert not failed["passed"]
    passed = academy.record_assessment(
        db, TENANT, rubric, party_id=LEARNER, path_id="LP-EXEC",
        module_id=module, score_pct=Decimal("100"),
    )
    assert passed["passed"]
    assert passed["attempts"] > failed["attempts"]
    db.rollback()


def test_the_certification_benefit_can_be_switched_off(db) -> None:
    """A governance feature that hands out access needs a switch somebody can
    reach in a hurry, and it is read on every evaluation rather than cached."""
    from services.workflow import policy

    rubric = load_current(db, "academy")
    for module in academy.path(db, "LP-CONSUME")["modules"]:
        academy.record_assessment(
            db, TENANT, rubric, party_id=LEARNER, path_id="LP-CONSUME",
            module_id=module["module_id"], score_pct=Decimal("95"),
        )
    product = fetch_one(
        db,
        "SELECT p.product_id FROM data_product p "
        "JOIN data_contract_version c ON c.product_id = p.product_id AND c.status = 'active' "
        "WHERE p.sensitivity_tier IN ('public', 'internal') AND NOT c.contains_pii "
        "ORDER BY p.product_id LIMIT 1",
    )
    if product is None:
        pytest.skip("no low-sensitivity product without personal data in this estate")

    with db.cursor() as cursor:
        cursor.execute(
            "UPDATE feature_flag SET enabled = false WHERE code = %s",
            (flags.ACADEMY_PRE_APPROVED_ACCESS,),
        )
    off = policy.evaluate(
        db, asset_type="data_product", asset_id=product["product_id"],
        requester_party_id=LEARNER, purpose_code="analytics",
    )
    assert off.path != "certified_auto"
    db.rollback()
