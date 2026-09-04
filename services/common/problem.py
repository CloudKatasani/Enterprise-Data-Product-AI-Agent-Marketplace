"""RFC 7807 problem responses.

Every non-2xx response the API returns is a problem document. Two of them are
contracts rather than conveniences and are constructed here so no route can get
them wrong:

* **403** carries the exact missing scope and a deep link to a pre-filled access
  request (section 10.3). A 403 that only says "forbidden" leaves the consumer
  with nowhere to go, which is how governance rails get bypassed.
* **422 / 424** are the agent refusals: out of scope names a covering agent, and
  ungrounded says how many numeric claims lacked citations. Neither is ever a
  guess dressed up as an answer.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from services.common import http_status

MEDIA_TYPE = "application/problem+json"


class Problem(HTTPException):
    """An HTTPException that always serialises as a problem document."""

    def __init__(
        self,
        status_code: int,
        problem_type: str,
        detail: str,
        **extra: Any,
    ) -> None:
        self.problem_type = problem_type
        self.extra = extra
        super().__init__(status_code=status_code, detail=detail)

    def document(self) -> dict[str, Any]:
        return {"type": self.problem_type, "status": self.status_code,
                "detail": self.detail, **self.extra}

    def response(self) -> JSONResponse:
        return JSONResponse(
            status_code=self.status_code, content=self.document(), media_type=MEDIA_TYPE
        )


def not_found(resource: str, identifier: str) -> Problem:
    return Problem(
        http_status.NOT_FOUND,
        "not_found",
        f"no {resource} with id {identifier!r}",
        resource=resource,
        id=identifier,
    )


def bad_request(detail: str, **extra: Any) -> Problem:
    return Problem(http_status.BAD_REQUEST, "bad_request", detail, **extra)


def entitlement_missing(required_scope: str, asset_id: str, surface: str) -> Problem:
    """The 403 contract from section 10.3.

    The consumer is told exactly which scope is missing and given a link that
    pre-fills the access request for it, so the next step is one click rather
    than a search for the right form.
    """
    return Problem(
        http_status.FORBIDDEN,
        "entitlement_missing",
        f"the caller holds no grant carrying {required_scope}",
        required_scope=required_scope,
        request_access_url=f"/requests/new/access?asset={asset_id}&surface={surface}",
    )


def purpose_required(asset_id: str, sensitivity: str) -> Problem:
    """Fail closed on a missing purpose (rule 7, section 11)."""
    return Problem(
        http_status.FORBIDDEN,
        "purpose_required",
        f"{asset_id} is classified {sensitivity}; a bound purpose is mandatory",
        asset_id=asset_id,
        sensitivity=sensitivity,
        request_access_url=f"/requests/new/access?asset={asset_id}&purpose=required",
    )


def out_of_scope(detail: str, suggested_agents: list[str], file_demand_url: str) -> Problem:
    return Problem(
        http_status.UNPROCESSABLE_ENTITY,
        "out_of_scope",
        detail,
        suggested_agents=suggested_agents,
        file_demand_url=file_demand_url,
    )


def ungrounded_answer(uncited_claims: int) -> Problem:
    return Problem(
        http_status.FAILED_DEPENDENCY,
        "ungrounded_answer",
        f"Answer withheld: {uncited_claims} numeric claims lacked citations.",
        uncited_claims=uncited_claims,
    )


def install_handlers(app: Any) -> None:
    @app.exception_handler(Problem)
    async def _handle_problem(_request: Any, exc: Problem) -> JSONResponse:
        return exc.response()

    @app.exception_handler(HTTPException)
    async def _handle_http(_request: Any, exc: HTTPException) -> JSONResponse:
        if isinstance(exc, Problem):
            return exc.response()
        return JSONResponse(
            status_code=exc.status_code,
            content={"type": "about:blank", "status": exc.status_code, "detail": exc.detail},
            media_type=MEDIA_TYPE,
        )
