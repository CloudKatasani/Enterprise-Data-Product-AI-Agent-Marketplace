"""The pre-filing check, at the boundary the intake page actually calls.

Two things are worth pinning here rather than in a unit test. The first is that
``/demand/assess`` and ``/demand/check`` answer different questions from one
request — coverage and similarity — and the intake needs both in one round
trip. The second is that a demand naming an unrecognised kind is refused rather
than quietly assessed as a data product, because a recommendation about the
wrong sort of asset is worse than no recommendation.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from services.api.main import create_app
from services.common import http_status
from services.workflow import assessment

TENANT = os.environ.get("TENANT_ID", "TEN-DEMO")
PREFIX = "/api/v1"
CONSUMER = "PTY-0061"

RELIABILITY = ["KPI-MTBF-108", "KPI-MTTREPAIR-109", "KPI-PMADHERE-110"]


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app(), raise_server_exceptions=False) as started:
        yield started


def _as(subject: str) -> dict[str, str]:
    return {"X-Marketplace-Subject": subject}


def test_the_assessment_carries_the_evidence_it_was_made_from(client) -> None:
    response = client.post(
        f"{PREFIX}/demand/assess",
        headers=_as(CONSUMER),
        json={"kind": "agent", "kpis": RELIABILITY},
    )
    assert response.status_code == http_status.OK
    verdict = response.json()["assessment"]
    assert verdict["recommendation"] in {
        assessment.RECOMMEND_SERVED,
        assessment.RECOMMEND_ENHANCE_AGENT,
        assessment.RECOMMEND_ENHANCE_PRODUCT,
        assessment.RECOMMEND_BUILD,
        assessment.RECOMMEND_INSUFFICIENT,
    }
    assert verdict["headline"] and verdict["rationale"]
    assert len(verdict["coverage"]) == len(RELIABILITY)
    assert verdict["rubric_version_id"]


def test_coverage_and_similarity_come_back_from_one_request(client) -> None:
    """The intake asks both questions at once; a page that had to call twice
    could show a recommendation made from one estate and duplicates from
    another."""
    response = client.post(
        f"{PREFIX}/demand/assess",
        headers=_as(CONSUMER),
        json={
            "kind": "agent",
            "text": "An agent for equipment reliability across the plants.",
            "kpis": RELIABILITY,
        },
    )
    assert response.status_code == http_status.OK
    body = response.json()
    assert body["assessment"]["coverage"]
    assert body["duplicates"] is not None


def test_no_text_means_no_similarity_rather_than_an_error(client) -> None:
    """KPIs alone are enough to assess coverage, so the check that needs prose
    is skipped rather than blocking the one that does not."""
    response = client.post(
        f"{PREFIX}/demand/assess",
        headers=_as(CONSUMER),
        json={"kind": "agent", "kpis": RELIABILITY},
    )
    assert response.status_code == http_status.OK
    assert response.json()["duplicates"] is None


def test_an_unrecognised_kind_is_refused(client) -> None:
    response = client.post(
        f"{PREFIX}/demand/assess",
        headers=_as(CONSUMER),
        json={"kind": "banana", "kpis": RELIABILITY},
    )
    assert response.status_code == http_status.BAD_REQUEST


def test_an_empty_demand_is_told_what_it_is_missing(client) -> None:
    response = client.post(
        f"{PREFIX}/demand/assess", headers=_as(CONSUMER), json={"kind": "agent"}
    )
    assert response.status_code == http_status.OK
    verdict = response.json()["assessment"]
    assert verdict["recommendation"] == assessment.RECOMMEND_INSUFFICIENT
