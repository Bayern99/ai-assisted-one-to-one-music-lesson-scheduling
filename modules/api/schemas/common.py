from __future__ import annotations

from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiErrorPayload(BaseModel):
    code: str
    message: str
    details: Optional[dict[str, Any]] = None
    operation_id: Optional[str] = None


class ApiEnvelope(BaseModel, Generic[T]):
    data: Optional[T] = None
    workspace_version: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    error: Optional[ApiErrorPayload] = None
