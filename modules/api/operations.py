from __future__ import annotations

import copy
import dataclasses
import threading
import uuid
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Operation:
    id: str
    kind: str
    status: str = "queued"
    phase: str = "queued"
    result: Optional[dict] = None
    error: Optional[str] = None


class OperationRegistry:
    def __init__(self) -> None:
        self._items: dict[str, Operation] = {}
        self._lock = threading.Lock()

    def create(self, kind: str) -> Operation:
        operation = Operation(id=uuid.uuid4().hex, kind=kind)
        with self._lock:
            self._items[operation.id] = operation
        return operation

    def start(self, operation_id: str, phase: str) -> None:
        self._update(operation_id, status="running", phase=phase)

    def complete(self, operation_id: str, result: dict) -> None:
        self._update(
            operation_id,
            status="completed",
            phase="completed",
            result=copy.deepcopy(result),
        )

    def fail(self, operation_id: str, error: str) -> None:
        self._update(operation_id, status="failed", phase="failed", error=error)

    def _update(self, operation_id: str, **changes: object) -> None:
        with self._lock:
            current = self._items.get(operation_id)
            if current is None:
                raise KeyError(operation_id)
            self._items[operation_id] = dataclasses.replace(current, **changes)

    def get(self, operation_id: str) -> Operation:
        with self._lock:
            current = self._items.get(operation_id)
            if current is None:
                raise KeyError(operation_id)
            return dataclasses.replace(current, result=copy.deepcopy(current.result))
