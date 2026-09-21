from __future__ import annotations

import copy
import dataclasses
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic
from typing import Any, Optional

MAX_OPERATION_EVENTS = 64
MAX_OPERATION_RECORDS = 64
_EVENT_DETAIL_STRING_LIMIT = 300


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _bounded_detail(value: Any) -> Any:
    if isinstance(value, str):
        return value if len(value) <= _EVENT_DETAIL_STRING_LIMIT else value[:_EVENT_DETAIL_STRING_LIMIT]
    if isinstance(value, dict):
        return {str(key): _bounded_detail(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_bounded_detail(item) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)


@dataclass(frozen=True)
class OperationEvent:
    seq: int
    type: str
    source: str
    label: str
    detail: dict[str, Any]
    at: str
    elapsed_ms: int


@dataclass(frozen=True)
class Operation:
    id: str
    kind: str
    status: str = "queued"
    phase: str = "queued"
    result: Optional[dict] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    last_activity_at: Optional[str] = None
    events: tuple[OperationEvent, ...] = ()


class OperationRegistry:
    def __init__(
        self,
        *,
        max_events: int = MAX_OPERATION_EVENTS,
        max_records: int = MAX_OPERATION_RECORDS,
    ) -> None:
        self._items: dict[str, Operation] = {}
        self._started_clock: dict[str, float] = {}
        self._event_seq: dict[str, int] = {}
        self._lock = threading.Lock()
        self._max_events = max(1, int(max_events))
        self._max_records = max(1, int(max_records))

    def create(self, kind: str) -> Operation:
        now = _utc_now()
        operation = Operation(
            id=uuid.uuid4().hex,
            kind=kind,
            started_at=now,
            last_activity_at=now,
        )
        with self._lock:
            self._items[operation.id] = operation
            self._started_clock[operation.id] = monotonic()
            self._event_seq[operation.id] = 0
            self._evict_terminal_locked()
        return operation

    def start(self, operation_id: str, phase: str) -> None:
        self._update(operation_id, status="running", phase=phase, last_activity_at=_utc_now())

    def complete(self, operation_id: str, result: dict) -> None:
        self._update(
            operation_id,
            status="completed",
            phase="completed",
            result=copy.deepcopy(result),
            last_activity_at=_utc_now(),
        )

    def fail(self, operation_id: str, error: str, result: dict | None = None) -> None:
        changes: dict[str, Any] = {
            "status": "failed",
            "phase": "failed",
            "error": error,
            "last_activity_at": _utc_now(),
        }
        if result is not None:
            changes["result"] = copy.deepcopy(result)
        self._update(operation_id, **changes)

    def emit(
        self,
        operation_id: str,
        *,
        type: str,
        source: str,
        label: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            current = self._items.get(operation_id)
            if current is None:
                raise KeyError(operation_id)
            started_clock = self._started_clock.get(operation_id)
            self._event_seq[operation_id] = self._event_seq.get(operation_id, 0) + 1
            event = OperationEvent(
                seq=self._event_seq[operation_id],
                type=str(type),
                source=str(source),
                label=str(label),
                detail=_bounded_detail(copy.deepcopy(detail or {})),
                at=_utc_now(),
                elapsed_ms=(
                    round((monotonic() - started_clock) * 1000)
                    if started_clock is not None
                    else 0
                ),
            )
            events = (current.events + (event,))[-self._max_events :]
            self._items[operation_id] = dataclasses.replace(
                current,
                events=events,
                last_activity_at=event.at,
            )

    def _update(self, operation_id: str, **changes: object) -> None:
        with self._lock:
            current = self._items.get(operation_id)
            if current is None:
                raise KeyError(operation_id)
            self._items[operation_id] = dataclasses.replace(current, **changes)

    def _evict_terminal_locked(self) -> None:
        # Only terminal records may leave; a queued or running operation is
        # never evicted, and bounded per-operation events keep each record small.
        surplus = len(self._items) - self._max_records
        if surplus <= 0:
            return
        for operation_id, operation in list(self._items.items()):
            if surplus <= 0:
                break
            if operation.status in {"completed", "failed"}:
                del self._items[operation_id]
                self._started_clock.pop(operation_id, None)
                self._event_seq.pop(operation_id, None)
                surplus -= 1

    def get(self, operation_id: str) -> Operation:
        with self._lock:
            current = self._items.get(operation_id)
            if current is None:
                raise KeyError(operation_id)
            return dataclasses.replace(
                current,
                result=copy.deepcopy(current.result),
                events=tuple(
                    dataclasses.replace(event, detail=copy.deepcopy(event.detail))
                    for event in current.events
                ),
            )
