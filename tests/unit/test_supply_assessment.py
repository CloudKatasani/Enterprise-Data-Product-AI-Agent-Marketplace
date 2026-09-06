"""Whether the estate already answers a demand, before anyone builds for it.

Duplicate detection asks whether a request *reads like* something published.
This asks whether the estate can already *answer* it, which is a coverage fact
rather than a similarity, and the recommendation that follows is the one thing
in the demand flow that can stop a build. So the cases pinned here are the ones
where a wrong recommendation costs something real:

    an answered set is never told to build, however it is spread across agents;

    an enhancement never names a measure something else already answers, because
    that is the divergence the whole assessment exists to prevent;

    a measure that is not in the register is not called a coverage gap, because
    no agent can answer a definition that does not exist yet.
"""

from __future__ import annotations

import os

import pytest

from services.common.rubrics import load_current
from services.workflow import assessment

TENANT = os.environ.get("TENANT_ID", "TEN-DEMO")

# One agent answers all three of these: the reliability set on DP-MFG-003.
RELIABILITY = ["KPI-MTBF-108", "KPI-MTTREPAIR-109", "KPI-PMADHERE-110"]
# Answered, but by a different agent on a different product.
ELSEWHERE = "KPI-CHURN-001"
# Not in the KPI register at all.
UNREGISTERED = "KPI-NOT-A-REAL-MEASURE-999"


@pytest.fixture()
def rubric(db):
    return load_current(db, "demand_scoring")


def test_one_agent_covering_everything_is_not_new_supply(db, rubric) -> None:
    verdict = assessment.assess(
        db, rubric, kind=assessment.KIND_AGENT, kpis=RELIABILITY,
    )
    assert verdict.recommendation == assessment.RECOMMEND_SERVED
    assert verdict.answered_share == 1.0


def test_a_set_answered_across_agents_is_still_answered(db, rubric) -> None:
    """The failure this guards against is real: with the measures spread over
    two agents, the closest single agent is missing one — and recommending it
    absorb a measure another agent already answers creates exactly the second
    definition the mesh exists to flag."""
    verdict = assessment.assess(
        db, rubric, kind=assessment.KIND_AGENT, kpis=[*RELIABILITY, ELSEWHERE],
    )
    assert verdict.recommendation == assessment.RECOMMEND_SERVED
    assert ELSEWHERE not in verdict.rationale
    assert all(row.answered_by for row in verdict.coverage)


def test_an_enhancement_never_names_an_answered_measure(db, rubric) -> None:
    """Whatever the recommendation, no KPI something already answers may appear
    in it as work to do."""
    verdict = assessment.assess(
        db, rubric, kind=assessment.KIND_AGENT,
        kpis=[*RELIABILITY, ELSEWHERE, UNREGISTERED],
    )
    answered = [row.kpi_id for row in verdict.coverage if row.answered_by]
    assert answered
    for kpi_id in answered:
        assert kpi_id not in verdict.rationale


def test_an_undefined_measure_is_a_definition_gap_not_a_coverage_gap(
    db, rubric
) -> None:
    verdict = assessment.assess(
        db, rubric, kind=assessment.KIND_AGENT, kpis=[*RELIABILITY, UNREGISTERED],
    )
    assert verdict.recommendation == assessment.RECOMMEND_ENHANCE_AGENT
    assert "not a certified measure" in verdict.rationale
    assert any(UNREGISTERED in note for note in verdict.notes)


def test_nothing_recognised_is_new_supply(db, rubric) -> None:
    verdict = assessment.assess(
        db, rubric, kind=assessment.KIND_AGENT, kpis=[UNREGISTERED, "KPI-ALSO-FAKE-1"],
    )
    assert verdict.recommendation == assessment.RECOMMEND_BUILD
    assert verdict.candidates == ()


def test_no_kpi_named_gets_no_recommendation(db, rubric) -> None:
    """A recommendation the evidence cannot support is worse than none."""
    verdict = assessment.assess(
        db, rubric, kind=assessment.KIND_AGENT,
        questions=["How many widgets did we ship?"],
    )
    assert verdict.recommendation == assessment.RECOMMEND_INSUFFICIENT


def test_questions_are_placed_against_the_agents_that_could_answer_them(
    db, rubric
) -> None:
    """The point of asking for questions is that unplaceable ones are the
    strongest evidence that supply is genuinely missing."""
    verdict = assessment.assess(
        db, rubric, kind=assessment.KIND_AGENT, kpis=RELIABILITY,
        questions=[
            "What is mean time between failures by plant?",
            "Which flavour of ice cream does the CFO prefer?",
        ],
    )
    assert "Which flavour of ice cream does the CFO prefer?" in (
        verdict.unplaced_questions
    )


def test_the_candidate_list_is_cut_where_the_rubric_says(db, rubric) -> None:
    shown = int(rubric.number(assessment.CANDIDATES_PATH))
    verdict = assessment.assess(
        db, rubric, kind=assessment.KIND_AGENT, kpis=[*RELIABILITY, ELSEWHERE],
    )
    agents = [c for c in verdict.candidates if c.asset_type == assessment.KIND_AGENT]
    products = [
        c for c in verdict.candidates if c.asset_type == assessment.KIND_PRODUCT
    ]
    assert len(agents) <= shown
    assert len(products) <= shown


def test_an_unknown_kind_is_refused_rather_than_guessed(db, rubric) -> None:
    with pytest.raises(ValueError):
        assessment.assess(db, rubric, kind="banana", kpis=RELIABILITY)


def test_the_verdict_carries_the_rubric_version_it_was_made_under(db, rubric) -> None:
    verdict = assessment.assess(
        db, rubric, kind=assessment.KIND_AGENT, kpis=RELIABILITY,
    )
    assert verdict.document()["rubric_version_id"] == rubric.rubric_version_id
