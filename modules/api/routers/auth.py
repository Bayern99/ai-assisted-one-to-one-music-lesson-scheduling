from __future__ import annotations

import secrets
from typing import Optional

from fastapi import APIRouter, Depends, Header, Request, Response

from modules.api.errors import ApiProblem
from modules.api.schemas.common import ApiEnvelope
from modules.api.security import require_session

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/exchange", response_model=ApiEnvelope[dict[str, bool]])
def exchange_bootstrap_token(
    request: Request,
    response: Response,
    bootstrap_token: Optional[str] = Header(
        default=None,
        alias="X-PI-Bootstrap-Token",
    ),
) -> ApiEnvelope[dict[str, bool]]:
    expected = request.app.state.config.bootstrap_token
    if not bootstrap_token or not secrets.compare_digest(bootstrap_token, expected):
        raise ApiProblem(
            status_code=401,
            code="AUTH_REQUIRED",
            message="Authentication required",
        )

    response.set_cookie(
        key="pi_session",
        value=expected,
        httponly=True,
        samesite="strict",
        secure=False,
    )
    return ApiEnvelope(data={"authenticated": True})


@router.get(
    "/session",
    response_model=ApiEnvelope[dict[str, bool]],
    dependencies=[Depends(require_session)],
)
def get_session() -> ApiEnvelope[dict[str, bool]]:
    return ApiEnvelope(data={"authenticated": True})
