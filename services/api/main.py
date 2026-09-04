"""API application factory.

Base path ``/api/v1``. OpenAPI 3.1. The portal is a client of this API with no
privileged path (BUILD.md section 10). Routers are registered milestone by
milestone; the application refuses to start with an invalid environment.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from services.common import http_status
from services.common.config import get_settings

API_PREFIX = "/api/v1"
OPENAPI_VERSION = "3.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Fail closed at boot rather than on the first request.
    app.state.settings = get_settings()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=f"{settings.product_name} API",
        version="0.1.0",
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        lifespan=lifespan,
    )
    app.openapi_version = OPENAPI_VERSION

    @app.get(f"{API_PREFIX}/health", status_code=http_status.OK, tags=["meta"])
    def health() -> dict[str, str]:
        """Liveness probe. Reports the tenant the process is bound to."""
        return {"status": "ok", "tenant_id": settings.tenant_id}

    return app


app = create_app()
