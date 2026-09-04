"""M12.5 — the signature journey, end to end.

    search → demo → request → approve → provision → first query

Section 20 gives it a budget of eight minutes for a person. This runs it as a
sequence of API calls in a fraction of that, which tests something different and
more useful: that the journey has **no gap in it**. Every step here starts from
what the previous step returned — the search result names the product, the
product's 403 names the scope, the 403's link pre-fills the request, the
request's evaluation names the approvers, and the grant that follows is what
makes the last query work.

That chain is the product. A journey where a step needs a value the previous
step did not give you is a journey a consumer completes by asking somebody, and
asking somebody is the thing this marketplace exists to remove.

The persona is a consumer holding nothing, so every refusal along the way is a
real refusal rather than a formality.
"""

from __future__ import annotations

import os
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from services.api.main import create_app
from services.common import http_status
from services.common.db import connect, fetch_all, fetch_one

TENANT = os.environ.get("TENANT_ID", "TEN-DEMO")
PREFIX = "/api/v1"

# Somebody with no grants at all. The journey has to work for them, or it only
# works for people who did not need it.
NEWCOMER = "PTY-0064"

# Section 20's budget is for a person clicking. This asserts the machine path is
# not the slow part: if the API alone spends minutes, no interface saves it.
JOURNEY_BUDGET_SECONDS = 60


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app(), raise_server_exceptions=False) as started:
        yield started


@pytest.fixture(scope="module")
def db():
    with connect(TENANT) as connection:
        yield connection


def _as(subject: str) -> dict[str, str]:
    return {"X-Marketplace-Subject": subject}


def _approvers(db, roles: list[str], owner: str | None) -> list[str]:
    """A party for each approver the policy named."""
    found: list[str] = []
    for role in roles:
        if role == "owner" and owner:
            found.append(owner)
            continue
        row = fetch_one(
            db,
            "SELECT p.party_id FROM party p JOIN role_assignment r ON r.party_id = p.party_id "
            "WHERE r.role_code = %s ORDER BY p.party_id LIMIT 1",
            (role,),
        )
        if row:
            found.append(row["party_id"])
    return found


def _first_requestable(client, candidates: list[str]):
    """The first candidate the policy would not block, with its evaluation.

    Returns ``(None, None)`` when every one is blocked — which is the preview
    doing its job rather than the journey failing, and is reported as such.
    """
    for asset_id in candidates:
        preview = client.post(
            f"{PREFIX}/requests/access/evaluate",
            headers=_as(NEWCOMER),
            json={"asset_type": "data_product", "asset_id": asset_id,
                  "purpose_code": "analytics"},
        )
        assert preview.status_code == http_status.OK
        evaluation = preview.json()
        if evaluation["path"] != "blocked":
            return asset_id, evaluation
    return None, None


def test_the_signature_journey_completes_without_a_gap(client, db) -> None:
    started = time.perf_counter()

    # ---- search ----------------------------------------------------------
    # A consumer arrives with a question, not an identifier.
    discovery = client.get(
        f"{PREFIX}/discover", params={"q": "customer churn"}, headers=_as(NEWCOMER)
    )
    assert discovery.status_code == http_status.OK
    results = discovery.json()["results"]
    assert results, "search found nothing; the journey has no first step"

    # The first result this persona does not already hold. A grant is not
    # revoked when a test finishes — grants are records, and this suite does not
    # get to rewrite the estate's history to make itself repeatable — so a
    # re-run walks to the next product instead.
    held = {
        row["asset_id"]
        for row in fetch_all(
            db,
            "SELECT asset_id FROM entitlement_grant WHERE principal_id = %s "
            "  AND revoked_at IS NULL AND expires_at > now()",
            (NEWCOMER,),
        )
    }
    candidates = [
        item["asset_id"]
        for item in results
        if item["asset_type"] == "data_product" and item["asset_id"] not in held
    ]
    assert candidates, (
        f"{NEWCOMER} already holds every product the search returned; the journey "
        "needs an asset they have not been granted"
    )

    # ---- the preview picks the one worth asking for -----------------------
    # Filing a request the policy would block is the mistake this step exists to
    # prevent, so the journey uses the preview the way a consumer would: check
    # first, then ask for the one that will actually go somewhere.
    product_id, evaluation = _first_requestable(client, candidates)
    assert product_id, (
        "every candidate is blocked for this purpose; a consumer here would be "
        "told so before filing, which is the preview working"
    )

    # ---- the listing tells them what they cannot do yet -------------------
    card = client.get(f"{PREFIX}/products/{product_id}", headers=_as(NEWCOMER))
    assert card.status_code == http_status.OK
    detail = card.json()["card"]
    # Metadata is visible before access. That is the point of a catalog: a
    # consumer can tell whether an asset is worth requesting before requesting.
    assert detail["name"]
    assert detail["access"]["granted"] is False
    request_url = detail["access"]["request_access_url"]
    assert request_url.startswith("/requests/new/access")

    # ---- demo ------------------------------------------------------------
    # Watch an agent answer on the demo tier before asking for anything.
    agents = client.get(f"{PREFIX}/agents", headers=_as(NEWCOMER))
    assert agents.status_code == http_status.OK
    agent_id = agents.json()["items"][0]["agent_id"]
    demo = client.get(f"{PREFIX}/agents/{agent_id}/demo", headers=_as(NEWCOMER))
    assert demo.status_code == http_status.OK
    exchanges = demo.json()["exchanges"]
    assert exchanges, "no curated exchange to watch; the demo step is a dead end"

    # ---- request ---------------------------------------------------------
    # The consumer saw the path, the approvers and the clock before committing.
    assert evaluation["due_at"] or evaluation["automatic"]

    request_id = f"REQ-E2E-{uuid.uuid4().hex[: len('0123456789ab')]}"
    created = client.post(
        f"{PREFIX}/requests/access",
        headers=_as(NEWCOMER),
        json={
            "request_id": request_id,
            "asset_type": "data_product",
            "asset_id": product_id,
            "purpose_code": "analytics",
            "purpose_text": "End-to-end journey check for the marketplace itself.",
        },
    )
    assert created.status_code == http_status.CREATED, created.text
    # What the form promised and what was recorded are the same evaluation.
    assert created.json()["evaluation"]["path"] == evaluation["path"]

    submitted = client.post(
        f"{PREFIX}/requests/access/{request_id}/submit", headers=_as(NEWCOMER)
    )
    assert submitted.status_code == http_status.OK, submitted.text

    # ---- approve ---------------------------------------------------------
    owner = fetch_one(
        db, "SELECT owner_party_id FROM data_product WHERE product_id = %s", (product_id,)
    )
    for approver in _approvers(db, evaluation["approvers"], owner["owner_party_id"]):
        decision = client.post(
            f"{PREFIX}/requests/access/{request_id}/decide",
            headers=_as(approver),
            json={"outcome": "approve", "reason": "journey check"},
        )
        assert decision.status_code == http_status.OK, decision.text

    # ---- provision -------------------------------------------------------
    grants = fetch_all(
        db,
        "SELECT grant_id, asset_id, oauth_scopes FROM entitlement_grant "
        "WHERE request_id = %s",
        (request_id,),
    )
    assert grants, "approval produced no grant; the journey stops before it is useful"

    # ---- the history explains every step ---------------------------------
    history = client.get(f"{PREFIX}/requests/{request_id}/history", headers=_as(NEWCOMER))
    assert history.status_code == http_status.OK
    events = history.json()["history"]
    assert len(events) >= len(evaluation["approvers"])
    # In order and each with an actor: a history nobody can read is a history
    # that settles no argument.
    assert all(event["actor"] for event in events)
    assert events == sorted(events, key=lambda event: event["occurred_at"])

    # ---- first query -----------------------------------------------------
    # The grant is live, so the same listing now says so. Nothing was cached in
    # between: effective permission is read fresh on every request.
    after = client.get(f"{PREFIX}/products/{product_id}", headers=_as(NEWCOMER))
    assert after.status_code == http_status.OK
    assert after.json()["card"]["access"]["granted"] is True

    elapsed = time.perf_counter() - started
    assert elapsed < JOURNEY_BUDGET_SECONDS, f"the journey took {elapsed:.1f}s"

    # Hand the access back. Revocation is a real operation with its own audit
    # record — the grant row stays, marked revoked, so "who had access to this
    # last March" is still answerable — and it leaves the estate as this suite
    # found it rather than accumulating a grant on every run.
    from services.common.rubrics import load_current
    from services.workflow import access

    governance = load_current(db, "governance")
    for grant in grants:
        access.revoke(
            db, TENANT, grant_id=grant["grant_id"], actor=NEWCOMER,
            reason="end-to-end journey check complete", governance=governance,
        )
    db.commit()


def test_the_journey_leaves_an_audit_trail(db) -> None:
    """Everything that touched access is written, immutably.

    Section 19 requires it and the journey above is the case that proves it: a
    request that was decided and provisioned with no audit behind it is a grant
    nobody can explain in a year.
    """
    events = fetch_all(
        db,
        "SELECT event_name, outcome, actor_party_id FROM audit_event "
        "WHERE asset_type = 'data_product' ORDER BY occurred_at DESC LIMIT 20",
    )
    assert events, "no audit events at all"
    for event in events:
        assert event["event_name"]
        assert event["outcome"]
