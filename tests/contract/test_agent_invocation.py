"""M7 — the agent invocation contract, all four of its outcomes.

BUILD.md section 10.2 defines the ask endpoint by its responses, not just its
success case, and the M7 acceptance criterion is stated in terms of the
failures: an answer with a stripped citation is withheld and returns 424; an
out-of-scope question returns 422 with a suggested agent; every demo answer
shows its tier badge.

These run against the real app over the real database, through the real
runtime. The 424 case is the one that needs care: to prove the check fires, the
runtime is made to return an answer whose prose states a number no claim
accounts for — the exact failure a language model produces and the reason the
check exists at all.
"""

from __future__ import annotations

import os
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from services.agent_runtime.base import Answer, Citation, ToolCall
from services.api.main import create_app
from services.common import http_status

TENANT = os.environ.get("TENANT_ID", "TEN-DEMO")
CONSUMER = "PTY-0061"
NO_GRANT = "PTY-0064"
PREFIX = "/api/v1"


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


def _headers(subject: str = CONSUMER) -> dict[str, str]:
    return {"X-Marketplace-Subject": subject}


@pytest.fixture(scope="module")
def agent(client: TestClient) -> dict:
    response = client.get(f"{PREFIX}/agents", headers=_headers())
    assert response.status_code == http_status.OK
    items = response.json()["items"]
    assert items, "no agents in the catalog"
    return items[0]


@pytest.fixture(scope="module")
def exchange(client: TestClient, agent: dict) -> dict:
    response = client.get(f"{PREFIX}/agents/{agent['agent_id']}/demo", headers=_headers())
    assert response.status_code == http_status.OK
    exchanges = response.json()["exchanges"]
    assert exchanges, "no validated exchanges to ask"
    return exchanges[0]


def _ask(client: TestClient, agent_id: str, subject: str = CONSUMER, **body):
    payload = {
        "tier": "demo",
        "purpose": "analytics",
        "session_id": "SES-CONTRACT",
        **body,
    }
    return client.post(
        f"{PREFIX}/agents/{agent_id}/ask", json=payload, headers=_headers(subject)
    )


# ---------------------------------------------------------------------------
# 200
# ---------------------------------------------------------------------------


def test_an_answer_carries_the_shape_section_10_2_specifies(
    client: TestClient, agent: dict, exchange: dict
) -> None:
    response = _ask(
        client, agent["agent_id"], question=exchange["question"],
        exchange_id=exchange["exchange_id"],
    )
    assert response.status_code == http_status.OK, response.text
    body = response.json()

    assert set(body["answer"]) == {"headline", "narrative", "visual", "table"}
    assert body["citations"] and body["kpi_definitions"]
    assert set(body["trace"]) >= {"tool_calls", "rows_scanned", "latency_ms", "tokens",
                                  "cost_usd"}
    assert body["grounded"] is True
    assert Decimal(str(body["confidence"])) > 0
    assert body["scope"]["effective_scope"] in {"intersection", "direct"}


def test_every_demo_answer_shows_its_tier(
    client: TestClient, agent: dict, exchange: dict
) -> None:
    """The M7 acceptance criterion: the tier badge is on every demo answer."""
    response = _ask(
        client, agent["agent_id"], question=exchange["question"],
        exchange_id=exchange["exchange_id"],
    )
    assert response.json()["tier"] == "demo"


def test_a_citation_names_the_contract_version_it_read(
    client: TestClient, agent: dict, exchange: dict
) -> None:
    body = _ask(
        client, agent["agent_id"], question=exchange["question"],
        exchange_id=exchange["exchange_id"],
    ).json()
    for citation in body["citations"]:
        assert citation["product_id"]
        assert citation["contract_version"]
        assert citation["columns"]


# ---------------------------------------------------------------------------
# 422 — out of scope
# ---------------------------------------------------------------------------


def test_an_out_of_scope_question_returns_422_with_a_route_onward(
    client: TestClient, agent: dict
) -> None:
    response = _ask(
        client, agent["agent_id"], question="What is the weather in Lisbon tomorrow?"
    )
    assert response.status_code == http_status.UNPROCESSABLE_ENTITY, response.text
    body = response.json()
    assert body["type"].endswith("out_of_scope")
    assert body["detail"]
    assert "file_demand_url" in body
    assert "suggested_agents" in body


def test_an_action_request_returns_422_naming_the_boundary(
    client: TestClient, agent: dict
) -> None:
    detail = _ask(
        client, agent["agent_id"],
        question="Approve the change and close the alert now.",
    ).json()["detail"]
    # The refusal has to point at a limit the agent actually declares, whether
    # it can name the nearest one or has to list them all. Checking for the
    # word "boundary" only tested which of those two sentences was written.
    declared = agent["out_of_scope"]
    assert declared, "the agent under test declares no boundary"
    assert any(limit in detail for limit in declared), detail


# ---------------------------------------------------------------------------
# 403 — entitlement
# ---------------------------------------------------------------------------


def test_a_caller_without_an_invoke_grant_gets_403_with_the_scope_and_a_link(
    client: TestClient, agent: dict, exchange: dict
) -> None:
    response = _ask(
        client, agent["agent_id"], subject=NO_GRANT, question=exchange["question"]
    )
    assert response.status_code == http_status.FORBIDDEN, response.text
    body = response.json()
    assert body["required_scope"] == f"agent:{agent['agent_id']}:invoke"
    assert agent["agent_id"] in body["request_access_url"]


# ---------------------------------------------------------------------------
# 424 — ungrounded
# ---------------------------------------------------------------------------


class _UngroundedRuntime:
    """A runtime that writes a number into prose that no claim accounts for.

    This is the model failure the whole check exists for: a fluent sentence
    carrying a figure the runtime did not compute.
    """

    name = "ungrounded-for-test"

    def ask(self, connection, request) -> Answer:
        return Answer(
            headline="Churn rose to 7.4% last quarter.",
            narrative="Driven by a 1,204 subscriber increase in the affluent segment.",
            visual={"type": "line", "spec": {}},
            table={"columns": [], "rows": []},
            citations=[
                Citation(
                    product_id="DP-TEL-001", contract_version="1.0.0",
                    columns=("segment",), as_of=None,
                )
            ],
            kpi_definitions=["KPI-CHURN-001"],
            tool_calls=[
                ToolCall(tool="query_dp_tel_001", arguments={}, rows_returned=1,
                         rows_scanned=1, duration_ms=1, cost_class="small")
            ],
            rows_scanned=1,
            latency_ms=1,
            tokens_in=0,
            tokens_out=0,
            cost_usd=Decimal("0"),
            confidence=Decimal("0.9"),
            runtime=self.name,
            claims={},
        )


def test_an_ungrounded_answer_is_withheld_with_424(
    client: TestClient, agent: dict, exchange: dict, monkeypatch
) -> None:
    """M7 acceptance: a stripped citation withholds the answer.

    The answer body must not appear in the response at all. Returning it with a
    warning flag would leave the number on the consumer's screen, which is the
    whole failure.
    """
    from services.agent_runtime import registry

    monkeypatch.setattr(registry, "build", lambda *_args, **_kwargs: _UngroundedRuntime())

    response = _ask(client, agent["agent_id"], question=exchange["question"])
    assert response.status_code == http_status.FAILED_DEPENDENCY, response.text
    body = response.json()
    assert body["type"].endswith("ungrounded_answer")
    assert "withheld" in body["detail"]
    assert body["uncited_claims"] >= 1
    assert "7.4" not in response.text
    assert "1,204" not in response.text


def test_an_ungrounded_answer_is_still_counted(
    client: TestClient, agent: dict, exchange: dict, monkeypatch
) -> None:
    """Withheld is not unrecorded: the owner has to be able to count these."""
    from services.agent_runtime import registry
    from services.common.db import connect, fetch_one

    monkeypatch.setattr(registry, "build", lambda *_args, **_kwargs: _UngroundedRuntime())
    _ask(client, agent["agent_id"], question=exchange["question"])

    with connect() as connection:
        row = fetch_one(
            connection,
            "SELECT count(*) AS n FROM agent_interaction "
            "WHERE outcome = 'ungrounded' AND grounded = false",
        )
    assert row["n"] >= 1


# ---------------------------------------------------------------------------
# 400 — the request itself
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "expected"),
    [("question", "question is required"), ("purpose", "purpose is required"),
     ("session_id", "session_id is required")],
)
def test_a_request_missing_a_required_field_is_refused(
    client: TestClient, agent: dict, exchange: dict, field: str, expected: str
) -> None:
    payload = {
        "question": exchange["question"], "tier": "demo", "purpose": "analytics",
        "session_id": "SES-CONTRACT",
    }
    payload[field] = ""
    response = client.post(
        f"{PREFIX}/agents/{agent['agent_id']}/ask", json=payload, headers=_headers()
    )
    assert response.status_code == http_status.BAD_REQUEST
    assert expected in response.json()["detail"]


def test_an_unknown_tier_is_refused(client: TestClient, agent: dict, exchange: dict) -> None:
    response = _ask(
        client, agent["agent_id"], question=exchange["question"], tier="production"
    )
    assert response.status_code == http_status.BAD_REQUEST
    assert "demo" in response.json()["detail"]


def test_an_unknown_agent_is_a_404(client: TestClient) -> None:
    response = _ask(client, "AG-DOES-NOT-EXIST", question="anything")
    assert response.status_code == http_status.NOT_FOUND


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------


def test_a_rejected_answer_with_a_defect_reason_becomes_an_evaluation_case(
    client: TestClient, agent: dict, exchange: dict
) -> None:
    """M7.5 — the loop closes. A defect reason authors a case; a preference does not."""
    answered = _ask(
        client, agent["agent_id"], question=exchange["question"],
        exchange_id=exchange["exchange_id"],
    ).json()

    response = client.post(
        f"{PREFIX}/agents/{agent['agent_id']}/feedback",
        json={
            "interaction_id": answered["interaction_id"],
            "accepted": False,
            "reason_code": "wrong_number",
            "reason_text": "the margin figure does not match the finance pack",
        },
        headers=_headers(),
    )
    assert response.status_code == http_status.CREATED, response.text
    assert response.json()["promoted"] is True

    from services.common.db import connect, fetch_one

    with connect() as connection:
        case = fetch_one(
            connection,
            "SELECT suite, origin, blocking FROM evaluation_case WHERE case_id = %s",
            (response.json()["promoted_case_id"],),
        )
    assert case["origin"] == "feedback"
    assert case["blocking"] is True


def test_an_accepted_answer_does_not_author_a_case(
    client: TestClient, agent: dict, exchange: dict
) -> None:
    answered = _ask(
        client, agent["agent_id"], question=exchange["question"],
        exchange_id=exchange["exchange_id"],
    ).json()
    response = client.post(
        f"{PREFIX}/agents/{agent['agent_id']}/feedback",
        json={"interaction_id": answered["interaction_id"], "accepted": True,
              "reason_code": "correct"},
        headers=_headers(),
    )
    assert response.status_code == http_status.CREATED
    assert response.json()["promoted"] is False


def test_an_unusable_reason_code_is_refused(client: TestClient, agent: dict) -> None:
    response = client.post(
        f"{PREFIX}/agents/{agent['agent_id']}/feedback",
        json={"interaction_id": "INT-nope", "accepted": False, "reason_code": "vibes"},
        headers=_headers(),
    )
    assert response.status_code == http_status.BAD_REQUEST
    assert "is not a reason code" in response.json()["detail"]
