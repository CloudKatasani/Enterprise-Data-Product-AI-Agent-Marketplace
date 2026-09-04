"""Request-scoped dependencies.

One connection per request, bound to the tenant, always in a transaction. The
rubrics a route needs are resolved from that same connection so a request reads
one consistent set of coefficients rather than a moving target.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import psycopg
from fastapi import Depends, Request

from services.common.db import connect, tenant_id
from services.common.rubrics import Rubric, load_current


def request_connection(request: Request) -> Iterator[psycopg.Connection[Any]]:
    with connect(tenant_id()) as connection:
        request.state.connection = connection
        yield connection


def tenant() -> str:
    return tenant_id()


def rubric_dependency(code: str) -> Any:
    def _resolve(
        connection: psycopg.Connection[Any] = Depends(request_connection),
    ) -> Rubric:
        return load_current(connection, code)

    return _resolve
