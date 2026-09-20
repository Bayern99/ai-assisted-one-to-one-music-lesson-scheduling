from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class WorkspaceData(BaseModel):
    workflow_state: Dict[str, Any] = Field(default_factory=dict)
    activity: Optional[Dict[str, Any]] = None
    health: Dict[str, Any] = Field(default_factory=dict)
