from __future__ import annotations

from fastapi import Request

from modules.scheduler.context import SchedulerContext


def get_scheduler_context(request: Request) -> SchedulerContext:
    return request.app.state.scheduler_context
