"""`/api/v1/quality` — estate-level quality.

Per-product quality is on the product's own route. This is the view that only
makes sense across the estate: the tier-weighted composite, its breakdown by
tier and band, and how many products carry no score at all — which is usually
the number that matters most, because an unscored product is not a good one.
"""

from __future__ import annotations

from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends

from services.api.deps import request_connection, rubric_dependency, tenant
from services.common import http_status
from services.common.rubrics import Rubric
from services.quality.engine import RUBRIC_CODE
from services.quality.estate import score_estate

router = APIRouter(prefix="/quality", tags=["quality"])

Connection = Annotated[psycopg.Connection[Any], Depends(request_connection)]
Tenant = Annotated[str, Depends(tenant)]
QualityRubric = Annotated[Rubric, Depends(rubric_dependency(RUBRIC_CODE))]


@router.get("/estate", status_code=http_status.OK,
            summary="Tier-weighted estate quality with its breakdown")
def estate(connection: Connection, tenant_id: Tenant, rubric: QualityRubric) -> dict[str, Any]:
    return score_estate(connection, tenant_id, rubric).document()
