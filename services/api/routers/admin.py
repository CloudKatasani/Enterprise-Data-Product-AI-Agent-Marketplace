"""`/api/v1/admin` — rubrics, taxonomies, connectors, flags and tenancy.

Every route here is open to the administrator role and closed to everyone else,
and the refusal says so in its own words rather than borrowing the entitlement
contract: no grant will ever carry an administrator role, so a 403 offering to
pre-fill an access request would be a link that goes nowhere.

What the console can do is bounded on purpose. It publishes new rubric versions
and toggles flags. It cannot edit a version that exists, an audit event, a
snapshot or a grant — those tables are append-only at the database, and an
administrator having authority over what the rules are but none over what
happened is what makes the record worth keeping.
"""

from __future__ import annotations

from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Body, Depends

from services.admin import estate
from services.admin import rubrics as admin_rubrics
from services.api.deps import request_connection, rubric_dependency, tenant
from services.common import http_status
from services.common.principal import Principal, current_principal
from services.common.problem import bad_request, not_found, role_required
from services.common.rubric_source import RubricVersionConflict
from services.common.rubrics import Rubric

router = APIRouter(prefix="/admin", tags=["admin"])

Connection = Annotated[psycopg.Connection[Any], Depends(request_connection)]
Tenant = Annotated[str, Depends(tenant)]
Governance = Annotated[Rubric, Depends(rubric_dependency("governance"))]

ROLE_ADMINISTRATOR = "administrator"


def administrator(
    principal: Annotated[Principal, Depends(current_principal)],
) -> Principal:
    """Fail closed on the role, before the handler reads anything."""
    if not principal.has_role(ROLE_ADMINISTRATOR):
        raise role_required(ROLE_ADMINISTRATOR)
    return principal


Admin = Annotated[Principal, Depends(administrator)]


@router.get("/rubrics", status_code=http_status.OK, summary="Every rubric")
def list_rubrics(connection: Connection, caller: Admin) -> dict[str, Any]:
    return {"rubrics": admin_rubrics.catalog(connection)}


@router.get("/rubrics/{code}", status_code=http_status.OK, summary="One rubric and its history")
def read_rubric(connection: Connection, caller: Admin, code: str) -> dict[str, Any]:
    try:
        payload = admin_rubrics.payload_of(connection, code)
    except admin_rubrics.RubricUnknown:
        raise not_found("rubric", code) from None
    return {
        "code": code,
        "payload": payload,
        # Every version, with how many snapshots each is still explaining. A
        # superseded version with scores behind it is not dead weight; it is
        # what makes those scores replayable.
        "versions": admin_rubrics.history(connection, code),
    }


@router.post(
    "/rubrics/{code}/versions",
    status_code=http_status.CREATED,
    summary="Publish an edited rubric",
)
def publish_version(
    connection: Connection,
    caller: Admin,
    tenant_id: Tenant,
    governance: Governance,
    code: str,
    payload: Annotated[dict[str, Any], Body()],
) -> dict[str, Any]:
    """Publish a new version, then re-score under it.

    The acceptance criterion for M12.2 is that a weight change here re-scores
    the estate *and* preserves prior snapshots, so both happen in one call and
    the response reports both counts. A console that published without
    re-scoring would leave the estate describing itself under a rubric no longer
    in force.
    """
    document = payload.get("payload") if "payload" in payload else payload
    if not isinstance(document, dict):
        raise bad_request("the payload must be a rubric document", code=code)

    try:
        published = admin_rubrics.publish(
            connection, tenant_id, governance,
            code=code, payload=document, actor_party_id=caller.party_id,
        )
    except admin_rubrics.RubricUnknown:
        raise not_found("rubric", code) from None
    except RubricVersionConflict as error:
        raise bad_request(str(error), code=code) from None
    except ValueError as error:
        raise bad_request(str(error), code=code) from None

    rescored = (
        admin_rubrics.rescore(connection, tenant_id)
        if published.created and code == admin_rubrics.QUALITY_RUBRIC
        else None
    )
    return {**published.document(), "rescore": rescored}


@router.get("/taxonomies", status_code=http_status.OK, summary="Controlled vocabulary")
def taxonomies(connection: Connection, caller: Admin) -> dict[str, Any]:
    return {"taxonomies": estate.taxonomies(connection)}


@router.get("/connectors", status_code=http_status.OK, summary="Source systems")
def connectors(connection: Connection, caller: Admin) -> dict[str, Any]:
    return {"connectors": estate.connectors(connection)}


@router.get("/flags", status_code=http_status.OK, summary="Feature flags")
def flags(connection: Connection, caller: Admin) -> dict[str, Any]:
    return {"flags": estate.flags(connection)}


@router.post("/flags/{code}", status_code=http_status.OK, summary="Toggle a flag")
def set_flag(
    connection: Connection,
    caller: Admin,
    tenant_id: Tenant,
    governance: Governance,
    code: str,
    enabled: Annotated[bool, Body(embed=True)],
) -> dict[str, Any]:
    try:
        return estate.set_flag(
            connection, tenant_id, governance,
            code=code, enabled=enabled, actor_party_id=caller.party_id,
        )
    except LookupError:
        raise not_found("feature flag", code) from None


@router.get("/tenancy", status_code=http_status.OK, summary="Tenancy and isolation")
def tenancy(connection: Connection, caller: Admin) -> dict[str, Any]:
    return estate.tenancy(connection)
