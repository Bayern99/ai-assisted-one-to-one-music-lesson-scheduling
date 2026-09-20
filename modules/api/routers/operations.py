from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from modules.api.operations import Operation
from modules.api.schemas.common import ApiEnvelope
from modules.api.security import require_session

router = APIRouter(tags=["operations"], dependencies=[Depends(require_session)])


@router.get("/operations/{operation_id}", response_model=ApiEnvelope[Operation])
def get_operation(request: Request, operation_id: str) -> ApiEnvelope[Operation]:
    try:
        operation = request.app.state.operation_registry.get(operation_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="OPERATION_NOT_FOUND")
    return ApiEnvelope(data=operation)
