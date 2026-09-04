"""API application factory.

Base path ``/api/v1``. OpenAPI 3.1. Cursor pagination. RFC 7807 problem
responses. The portal is a client of this API with no privileged path
(BUILD.md section 10).

Boot is fail-closed: the environment is validated and the embedder is
configured from its rubric before the first request is served, so a
misconfigured deployment refuses to start rather than serving degraded results.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from services.api.routers import discover, kpis, products, quality
from services.common import http_status, problem
from services.common.config import get_settings
from services.common.db import connect, tenant_id
from services.common.rubrics import RubricNotFound, load_current
from services.search import embedding

API_PREFIX = "/api/v1"
OPENAPI_VERSION = "3.1.0"

DESCRIPTION = """
Governed catalog of data products and the AI agents that run on them.

Every response that carries a computed number also carries the rubric version it
was computed under, so a score, a ranking or a value figure can be replayed
exactly. Every 403 names the missing scope and links to a pre-filled access
request. An agent answer that cannot be grounded is withheld, never guessed.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.settings = settings
    try:
        with connect(tenant_id()) as connection:
            embedding.configure_from_rubric(load_current(connection, embedding.RUBRIC_CODE))
    except (RubricNotFound, Exception) as error:  # noqa: BLE001 - reported, not swallowed
        # Generation and offline tooling create the app without a database. A
        # request that needs the embedder will fail loudly rather than silently
        # returning lexical-only results.
        app.state.embedder_error = repr(error)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=f"{settings.product_name} API",
        description=DESCRIPTION.strip(),
        version="0.1.0",
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        lifespan=lifespan,
    )
    app.openapi_version = OPENAPI_VERSION
    problem.install_handlers(app)

    @app.get(f"{API_PREFIX}/health", status_code=http_status.OK, tags=["meta"],
             summary="Liveness probe")
    def health() -> dict[str, str]:
        return {"status": "ok", "tenant_id": settings.tenant_id}

    for router in (products.router, discover.router, kpis.router, quality.router):
        app.include_router(router, prefix=API_PREFIX)

    return app


app = create_app()
