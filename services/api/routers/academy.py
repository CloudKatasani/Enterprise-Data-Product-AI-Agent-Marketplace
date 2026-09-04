"""`/api/v1/academy` — paths, modules, enrolment and certification.

Reading the academy needs no identity: the point of it is that a visitor can
learn what this estate expects before asking for anything. Enrolling and being
assessed do need one, because both are records about a person.

The module body is served from the manifest it was seeded from. There is one
copy of every sentence the academy teaches, and a change to it is a diff.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Body, Depends, Query

from services.academy import paths as academy
from services.api.deps import request_connection, rubric_dependency, tenant
from services.common import http_status
from services.common.principal import Principal, current_principal
from services.common.problem import bad_request, not_found
from services.common.rubrics import Rubric

router = APIRouter(prefix="/academy", tags=["academy"])

Connection = Annotated[psycopg.Connection[Any], Depends(request_connection)]
Caller = Annotated[Principal, Depends(current_principal)]
Tenant = Annotated[str, Depends(tenant)]
AcademyRubric = Annotated[Rubric, Depends(rubric_dependency("academy"))]

ASSET_TYPES = ("data_product", "agent")


@router.get("/paths", status_code=http_status.OK, summary="Every learning path")
def list_paths(connection: Connection, rubric: AcademyRubric) -> dict[str, Any]:
    return {
        "paths": academy.paths(connection),
        "pass_score_pct": float(rubric.number("assessment.pass_score_pct")),
        "certification_valid_days": int(rubric.number("certification.valid_days")),
        "rubric_version_id": rubric.rubric_version_id,
    }


@router.get("/paths/{path_id}", status_code=http_status.OK, summary="One path")
def read_path(
    connection: Connection, rubric: AcademyRubric, path_id: str
) -> dict[str, Any]:
    try:
        found = academy.path(connection, path_id)
    except academy.PathNotFound:
        raise not_found("learning path", path_id) from None
    return {**found, "rubric_version_id": rubric.rubric_version_id}


@router.get("/modules/{module_id}", status_code=http_status.OK, summary="A module and its body")
def read_module(connection: Connection, module_id: str) -> dict[str, Any]:
    try:
        body = academy.body_of(connection, module_id)
    except academy.ModuleNotFound:
        raise not_found("academy module", module_id) from None
    for found in academy.paths(connection):
        for module in found["modules"]:
            if module["module_id"] == module_id:
                return {**module, "body": body, "path_id": found["path_id"]}
    raise not_found("academy module", module_id)


@router.get("/contextual", status_code=http_status.OK, summary="Modules for one asset")
def contextual(
    connection: Connection,
    asset_type: str = Query(...),
    asset_id: str = Query(...),
) -> dict[str, Any]:
    """The reading list a listing links to (section 20.2).

    Contextual means *this* asset class in *this* order, not the whole academy
    filtered. A link that opens eleven modules has not answered the question the
    reader had.
    """
    if asset_type not in ASSET_TYPES:
        raise bad_request(
            "asset_type must be one of " + ", ".join(ASSET_TYPES), asset_type=asset_type
        )
    return {
        "asset_type": asset_type,
        "asset_id": asset_id,
        "modules": academy.contextual(connection, asset_type, asset_id),
    }


@router.get("/me", status_code=http_status.OK, summary="My progress and certifications")
def my_progress(connection: Connection, principal: Caller) -> dict[str, Any]:
    return {
        "party_id": principal.party_id,
        "certifications": academy.held(connection, principal.party_id),
        "progress": [
            academy.progress(
                connection, party_id=principal.party_id, path_id=found["path_id"]
            )
            for found in academy.paths(connection)
        ],
    }


@router.post("/enrollments", status_code=http_status.CREATED, summary="Enrol on a path")
def enrol(
    connection: Connection,
    principal: Caller,
    tenant_id: Tenant,
    path_id: Annotated[str, Body(embed=True)],
) -> dict[str, Any]:
    try:
        return academy.enrol(
            connection, tenant_id, party_id=principal.party_id, path_id=path_id
        )
    except academy.PathNotFound:
        raise not_found("learning path", path_id) from None


@router.post("/assessments", status_code=http_status.CREATED, summary="Record an attempt")
def assess(
    connection: Connection,
    principal: Caller,
    tenant_id: Tenant,
    rubric: AcademyRubric,
    payload: Annotated[dict[str, Any], Body()],
) -> dict[str, Any]:
    """Record one attempt, and certify if that completes the path.

    Attempts are append-only. A pass on the fourth try and a pass on the first
    are the same certificate and different evidence, and only one of those
    survives if a failed attempt can be replaced.
    """
    for required in ("path_id", "module_id", "score_pct"):
        if required not in payload:
            raise bad_request(f"{required} is required", field=required)
    try:
        return academy.record_assessment(
            connection,
            tenant_id,
            rubric,
            party_id=principal.party_id,
            path_id=str(payload["path_id"]),
            module_id=str(payload["module_id"]),
            score_pct=Decimal(str(payload["score_pct"])),
        )
    except academy.PathNotFound:
        raise not_found("learning path", str(payload["path_id"])) from None
