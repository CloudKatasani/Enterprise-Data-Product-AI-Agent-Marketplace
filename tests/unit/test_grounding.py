"""M7.3 — grounding validation.

The check has two ways to be wrong and both are bad in different ways. Missing
an uncited number lets a fabricated figure reach a consumer. Flagging a number
that is part of a label makes the check noise, and a check that cries wolf gets
turned off. So both directions are pinned here.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from services.agent_runtime.base import Answer, Citation, ToolCall
from services.agents import grounding


def _answer(headline: str, narrative: str = "", claims: dict[str, str] | None = None,
            *, cited: bool = True) -> Answer:
    return Answer(
        headline=headline,
        narrative=narrative,
        visual={},
        table={},
        citations=[
            Citation(product_id="DP-TEL-001", contract_version="1.0.0",
                     columns=("segment",), as_of=None)
        ]
        if cited
        else [],
        kpi_definitions=["KPI-CHURN-001"],
        tool_calls=[
            ToolCall(tool="query", arguments={}, rows_returned=1, rows_scanned=1,
                     duration_ms=1, cost_class="small")
        ],
        rows_scanned=1,
        latency_ms=1,
        tokens_in=0,
        tokens_out=0,
        cost_usd=Decimal("0"),
        confidence=Decimal("0.9"),
        runtime="test",
        claims={key: Decimal(value) for key, value in (claims or {}).items()},
    )


# ---------------------------------------------------------------------------
# It catches what it must
# ---------------------------------------------------------------------------


def test_a_number_in_prose_with_no_claim_behind_it_is_ungrounded() -> None:
    verdict = grounding.check(_answer("Churn rose to 7.4% last quarter."))
    assert not verdict.grounded
    assert "7.4" in verdict.uncited_numbers
    assert "7.4" in verdict.reason()


def test_every_uncited_number_is_reported_not_just_the_first() -> None:
    verdict = grounding.check(
        _answer("Churn rose to 7.4%.", "Driven by 1,204 subscribers in 3 regions.")
    )
    assert set(verdict.uncited_numbers) == {"7.4", "1204", "3"}
    assert verdict.uncited_count == len(verdict.uncited_numbers)


def test_claims_with_no_citation_are_ungrounded_even_with_silent_prose() -> None:
    """The table and the visual carry the claims too, not only the sentence."""
    verdict = grounding.check(
        _answer("Churn is up.", claims={"current": "7.4"}, cited=False)
    )
    assert not verdict.grounded
    assert verdict.unsupported_claims == ("current",)


# ---------------------------------------------------------------------------
# It does not cry wolf
# ---------------------------------------------------------------------------


def test_a_claimed_number_is_grounded() -> None:
    verdict = grounding.check(
        _answer("Churn rose to 7.4% last quarter.", claims={"current": "7.4"})
    )
    assert verdict.grounded
    assert verdict.reason() == ""


@pytest.mark.parametrize(
    "text",
    [
        "Computed from DP-TEL-001 under KPI-CHURN-001.",
        "For the month ending 2026-08-01.",
        "Ranked across DP-RTL-002 and DP-MFG-001.",
    ],
)
def test_numbers_inside_labels_are_not_claims(text: str) -> None:
    """A product id and a date are names of things, not assertions about them."""
    assert grounding.numbers_in(text) == set()


def test_a_thousands_separator_does_not_break_matching() -> None:
    verdict = grounding.check(
        _answer("Across 25,200 rows.", claims={"rows_scanned": "25200"})
    )
    assert verdict.grounded


def test_a_negative_number_keeps_its_sign() -> None:
    verdict = grounding.check(
        _answer("Growth is -1.36% this week.", claims={"current": "-1.36"})
    )
    assert verdict.grounded


def test_trailing_zeros_are_matched_either_way() -> None:
    """A claim of 12.0000 grounds a sentence that says 12.0000."""
    verdict = grounding.check(
        _answer("Median is 12.0000 days.", claims={"median": "12.0000"})
    )
    assert verdict.grounded


def test_a_claim_rendered_differently_from_the_prose_is_caught() -> None:
    """The precise failure this found in the composer: a claim quantised in
    percentage points beside prose printed in the KPI's own unit."""
    verdict = grounding.check(
        _answer("A gap of 23.3650 minutes.", claims={"cohort_gap": "23.36"})
    )
    assert not verdict.grounded
    assert "23.3650" in verdict.uncited_numbers
