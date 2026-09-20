from __future__ import annotations

from fastapi import APIRouter

from modules.api.schemas.common import ApiEnvelope

router = APIRouter(tags=["health"])


@router.get("/health", response_model=ApiEnvelope[dict[str, str]])
def get_health() -> ApiEnvelope[dict[str, str]]:
    return ApiEnvelope(data={"status": "ok"})
