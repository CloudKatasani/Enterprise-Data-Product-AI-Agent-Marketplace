"""M12 — the academy and admin surfaces, against the real application.

Two shapes are worth pinning here rather than in a unit test, because both are
about the *boundary* rather than the logic behind it:

    reading the academy needs no identity, and enrolling does;

    the admin console refuses a consumer in its own words rather than borrowing
    the entitlement contract — no grant will ever carry an administrator role,
    so a 403 offering to pre-fill an access request would be a link that goes
    nowhere.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from services.api.main import create_app
from services.common import http_status

TENANT = os.environ.get("TENANT_ID", "TEN-DEMO")
PREFIX = "/api/v1"

CONSUMER = "PTY-0061"
ADMINISTRATOR = "PTY-0005"


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app(), raise_server_exceptions=False) as started:
        yield started


def _as(subject: str) -> dict[str, str]:
    return {"X-Marketplace-Subject": subject}


def test_the_academy_reads_without_an_identity(client) -> None:
    """A visitor should be able to learn what this estate expects before asking
    it for anything."""
    response = client.get(f"{PREFIX}/academy/paths")
    assert response.status_code == http_status.OK
    body = response.json()
    assert body["paths"]
    assert body["pass_score_pct"] > 0
    assert body["rubric_version_id"]


def test_every_path_carries_its_modules_in_order(client) -> None:
    paths = client.get(f"{PREFIX}/academy/paths").json()["paths"]
    for path in paths:
        assert path["modules"]
        assert path["estimated_minutes"] == sum(
            module["estimated_minutes"] for module in path["modules"]
        )
        assert path["certification_code"].startswith("CERT-")


def test_a_module_serves_its_body_and_names_its_path(client) -> None:
    paths = client.get(f"{PREFIX}/academy/paths").json()["paths"]
    module_id = paths[0]["modules"][0]["module_id"]
    response = client.get(f"{PREFIX}/academy/modules/{module_id}")
    assert response.status_code == http_status.OK
    body = response.json()
    assert body["body"]
    assert body["path_id"] == paths[0]["path_id"]


def test_an_unknown_module_is_a_404_not_an_empty_page(client) -> None:
    response = client.get(f"{PREFIX}/academy/modules/MOD-NOT-A-MODULE")
    assert response.status_code == http_status.NOT_FOUND


def test_a_contextual_link_needs_a_known_asset_class(client) -> None:
    response = client.get(
        f"{PREFIX}/academy/contextual",
        params={"asset_type": "spreadsheet", "asset_id": "DP-BNK-001"},
    )
    assert response.status_code == http_status.BAD_REQUEST


def test_progress_needs_an_identity(client) -> None:
    """A record about a person needs to know which person."""
    assert client.get(f"{PREFIX}/academy/me").status_code == http_status.UNAUTHORIZED
    assert (
        client.get(f"{PREFIX}/academy/me", headers=_as(CONSUMER)).status_code
        == http_status.OK
    )


def test_enrolling_twice_keeps_the_progress_behind_the_first(client) -> None:
    paths = client.get(f"{PREFIX}/academy/paths").json()["paths"]
    path_id = paths[0]["path_id"]
    first = client.post(
        f"{PREFIX}/academy/enrollments", headers=_as(CONSUMER),
        json={"path_id": path_id},
    )
    assert first.status_code == http_status.CREATED
    second = client.post(
        f"{PREFIX}/academy/enrollments", headers=_as(CONSUMER),
        json={"path_id": path_id},
    )
    assert second.status_code == http_status.CREATED
    assert second.json()["completed"] >= first.json()["completed"]


def test_the_admin_console_refuses_a_consumer_in_its_own_words(client) -> None:
    for route in ("rubrics", "taxonomies", "connectors", "flags", "tenancy"):
        response = client.get(f"{PREFIX}/admin/{route}", headers=_as(CONSUMER))
        assert response.status_code == http_status.FORBIDDEN, route
        problem = response.json()
        assert problem["type"] == "role_required"
        # Not the entitlement contract: there is nothing here to request.
        assert "request_access_url" not in problem
        assert "administrator" in problem["required_roles"]


def test_the_admin_console_serves_an_administrator(client) -> None:
    rubrics = client.get(f"{PREFIX}/admin/rubrics", headers=_as(ADMINISTRATOR))
    assert rubrics.status_code == http_status.OK
    codes = {row["code"] for row in rubrics.json()["rubrics"]}
    assert {"data_product_quality", "academy", "landing"} <= codes

    detail = client.get(
        f"{PREFIX}/admin/rubrics/data_product_quality", headers=_as(ADMINISTRATOR)
    )
    assert detail.status_code == http_status.OK
    body = detail.json()
    assert body["payload"]["dimensions"]
    # Every version, with what each is still explaining.
    assert any(version["in_force"] for version in body["versions"])


def test_publishing_without_a_version_bump_is_a_400_with_the_reason(client) -> None:
    detail = client.get(
        f"{PREFIX}/admin/rubrics/data_product_quality", headers=_as(ADMINISTRATOR)
    ).json()
    payload = detail["payload"]
    payload["dimensions"][0]["weight"] = 0.99

    response = client.post(
        f"{PREFIX}/admin/rubrics/data_product_quality/versions",
        headers=_as(ADMINISTRATOR),
        json=payload,
    )
    assert response.status_code == http_status.BAD_REQUEST
    assert "version" in response.json()["detail"]


def test_the_tenancy_panel_names_anything_unprotected(client) -> None:
    response = client.get(f"{PREFIX}/admin/tenancy", headers=_as(ADMINISTRATOR))
    assert response.status_code == http_status.OK
    body = response.json()
    assert body["unprotected_tables"] == []
    assert body["row_level_security"] == body["tenanted_tables"]


def test_the_release_state_shows_what_a_rollback_would_restore(client) -> None:
    """"Roll back" is not a decision anyone should take without seeing the
    bundle on the other side of it."""
    agents = client.get(f"{PREFIX}/agents", headers=_as(CONSUMER)).json()["items"]
    agent_id = agents[0]["agent_id"]
    response = client.get(f"{PREFIX}/agents/{agent_id}/release", headers=_as(CONSUMER))
    assert response.status_code == http_status.OK
    body = response.json()
    assert body["live"]["agent_version_id"]
    assert body["live"]["products"]
    assert body["live"]["coverage"]
    # None on a first version, which is the honest answer.
    assert "rollback_target" in body


def test_a_rollback_is_closed_to_a_consumer(client) -> None:
    agents = client.get(f"{PREFIX}/agents", headers=_as(CONSUMER)).json()["items"]
    response = client.post(
        f"{PREFIX}/agents/{agents[0]['agent_id']}/rollback",
        headers=_as(CONSUMER),
        json={"reason": "because I can"},
    )
    assert response.status_code == http_status.FORBIDDEN
    assert response.json()["type"] == "role_required"
