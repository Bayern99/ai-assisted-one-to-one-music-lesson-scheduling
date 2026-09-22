"""Operational progress and termination accounting for the Pi reconciliation turn."""

from __future__ import annotations

import json

import pytest

from modules.api.operations import OperationRegistry
from modules.api.services.pi_optimizer_intervention import (
    PiRpcResult,
    PiRpcTimeout,
)
from modules.api.services.pi_reconciliation import (
    build_reconciliation_investigation,
    run_pi_reconciliation_operation,
)
from modules.api.services.workspace import compute_workspace_version
from modules.scheduler.logic.optimizer_learning_record import record_optimizer_run
from modules.shared.session_manager import SessionManager


UNRESOLVED = {
    "id": "private-issue",
    "source_request_id": "private-source",
    "student": "Student Secret",
    "instructor": "Instructor One",
    "instrument": "Piano",
    "day": 1,
    "start": "10:00",
    "end": "11:00",
}

TARGET = {"room": "R2", "day": 1, "start": "10:00", "end": "11:00"}


def _write_facts(client):
    base_dir = client.app.state.config.base_dir
    (base_dir / "bookings.json").write_text("[]", encoding="utf-8")
    (base_dir / "rooms.json").write_text(
        json.dumps([{"id": "R1", "type": "Piano"}, {"id": "R2", "type": "Piano"}]),
        encoding="utf-8",
    )
    (base_dir / "scheduling_rules.json").write_text(
        json.dumps({
            "room_types": {"R1": ["Piano"], "R2": ["Piano"]},
            "instructor_time_change_eligibility": {"Instructor One": "ask_allowed"},
        }),
        encoding="utf-8",
    )


@pytest.fixture
def auth_client(client, bootstrap_token):
    _write_facts(client)
    response = client.post(
        "/api/auth/exchange",
        headers={"X-PI-Bootstrap-Token": bootstrap_token},
    )
    assert response.status_code == 200
    return client


def _install_run(client):
    state = {
        "step4_edit_session": {
            "optimizer_run_id": "run-reconciliation",
            "assignments": [],
            "unassigned_lessons": [dict(UNRESOLVED)],
            "history": [],
            "redo_stack": [],
            "dirty": False,
        }
    }
    base_dir = client.app.state.config.base_dir
    SessionManager(base_dir=str(base_dir)).save_session(state)
    context = client.app.state.scheduler_context
    record_optimizer_run(
        context.loader,
        run_id="run-reconciliation",
        input_workspace_version=compute_workspace_version(base_dir, context=context),
        state=state,
        rules=context.load_rules(),
        duplicate_count=0,
        started_at="2026-08-02T00:00:00+00:00",
    )
    return state


def _rpc_result(latency_ms=5):
    return PiRpcResult(
        text="Investigation complete.",
        pi_version="stub",
        provider="stub-provider",
        model="cursor-grok-4.5",
        latency_ms=latency_ms,
        usage={
            "input": 1200,
            "output": 90,
            "cache_read": 300,
            "cache_write": 40,
            "total_tokens": 1630,
            "cost": 0.01,
        },
    )


def _run_operation(client, rpc, **task_inputs):
    _install_run(client)
    context = client.app.state.scheduler_context
    version = compute_workspace_version(context.loader.base_dir, context=context)
    investigation = build_reconciliation_investigation(
        context,
        expected_version=version,
        day=1,
        **task_inputs,
    )
    store = client.app.state.pi_reconciliation_capabilities
    registry = OperationRegistry()
    operation = registry.create("pi_reconciliation")
    run_pi_reconciliation_operation(
        context=context,
        registry=registry,
        operation_id=operation.id,
        investigation=investigation,
        model="cursor-grok-4.5",
        tool_url="http://127.0.0.1:1/unused",
        capability_store=store,
        rpc_runner=rpc,
    )
    return registry, operation, investigation


def _token(environment):
    return environment["PI_RECONCILIATION_CAPABILITY"]


def _submit_brief(store, token, simulation):
    store.submit(token, {
        "termination": "recommendation_ready",
        "primary_simulation_id": simulation["simulation_id"],
        "title": "Keep the original time",
        "focus_question": "这节未排课可以按原时间安排，是否执行？",
        "rationale": "A compatible room is available.",
        "trade_offs": [],
        "limitations": [],
    })


def _successful_rpc(client):
    def fake_rpc(_prompt, *, environment=None, on_event=None, **_kwargs):
        store = client.app.state.pi_reconciliation_capabilities
        token = _token(environment)
        if on_event is not None:
            on_event({"type": "process_spawn", "spawn_ms": 140})
            on_event({"type": "agent_start"})
            on_event({"type": "first_agent_activity", "elapsed_ms": 900})
        inspected = store.inspect(token)
        alias = inspected["case_index"][0]["subject_alias"]
        if on_event is not None:
            on_event({
                "type": "tool_execution_start",
                "toolName": "simulate_reconciliation_package",
                "toolCallId": "call-1",
            })
        simulation = store.simulate(token, [{"subject_alias": alias, "target": TARGET}])
        assert simulation["feasible"], simulation["failure_codes"]
        if on_event is not None:
            on_event({
                "type": "tool_execution_end",
                "toolName": "simulate_reconciliation_package",
                "isError": False,
            })
        _submit_brief(store, token, simulation)
        if on_event is not None:
            on_event({"type": "agent_settled"})
        return _rpc_result()

    return fake_rpc


def test_python_progress_events_cover_the_full_turn(auth_client):
    registry, operation, _investigation = _run_operation(auth_client, _successful_rpc(auth_client))
    snapshot = registry.get(operation.id)

    assert snapshot.status == "completed"
    events = snapshot.events
    types = [event.type for event in events]
    assert types[0] == "investigation_started"
    for expected in (
        "inspection_started",
        "inspection_completed",
        "simulation_started",
        "first_valid_candidate",
        "simulation_completed",
        "brief_submitted",
    ):
        assert expected in types
    python_events = {event.type: event for event in events if event.source == "python"}
    assert python_events["inspection_completed"].detail["subjects"] == 1
    assert python_events["brief_submitted"].detail["termination"] == "recommendation_ready"


def test_rpc_events_are_forwarded_with_pi_rpc_source(auth_client):
    registry, operation, _investigation = _run_operation(auth_client, _successful_rpc(auth_client))
    events = registry.get(operation.id).events

    rpc_events = {event.type: event for event in events if event.source == "pi_rpc"}
    assert rpc_events["process_spawned"].detail["spawn_ms"] == 140
    assert rpc_events["first_agent_activity"].detail["elapsed_ms"] == 900
    assert "agent_alive" in rpc_events
    assert rpc_events["model_tool_request"].detail["tool"] == "simulate_reconciliation_package"
    assert "model_tool_end" in rpc_events
    assert "agent_settled" in rpc_events


def test_provider_retry_events_are_forwarded(auth_client):
    def fake_rpc(_prompt, *, environment=None, on_event=None, **_kwargs):
        store = auth_client.app.state.pi_reconciliation_capabilities
        token = _token(environment)
        if on_event is not None:
            on_event({
                "type": "auto_retry_start",
                "attempt": 2,
                "maxAttempts": 3,
                "delayMs": 1500,
                "errorMessage": "rate limited",
            })
            on_event({"type": "auto_retry_end", "attempt": 2, "success": True})
        inspected = store.inspect(token)
        alias = inspected["case_index"][0]["subject_alias"]
        simulation = store.simulate(token, [{"subject_alias": alias, "target": TARGET}])
        _submit_brief(store, token, simulation)
        return _rpc_result()

    registry, operation, _investigation = _run_operation(auth_client, fake_rpc)
    events = registry.get(operation.id).events

    retry = [event for event in events if event.type == "provider_retry"]
    assert retry and retry[0].detail == {"attempt": 2, "max_attempts": 3, "delay_ms": 1500}
    retry_end = [event for event in events if event.type == "provider_retry_end"]
    assert retry_end and retry_end[0].detail["success"] is True


def test_simulation_rejection_carries_the_python_reason(auth_client):
    def fake_rpc(_prompt, *, environment=None, **_kwargs):
        store = auth_client.app.state.pi_reconciliation_capabilities
        token = _token(environment)
        inspected = store.inspect(token)
        rejected = store.simulate(token, [{"subject_alias": "issue-does-not-exist", "target": TARGET}])
        assert rejected["rejection"]
        alias = inspected["case_index"][0]["subject_alias"]
        simulation = store.simulate(token, [{"subject_alias": alias, "target": TARGET}])
        _submit_brief(store, token, simulation)
        return _rpc_result()

    registry, operation, _investigation = _run_operation(auth_client, fake_rpc)
    snapshot = registry.get(operation.id)

    rejected = [event for event in snapshot.events if event.type == "simulation_rejected"]
    assert len(rejected) == 1
    assert "issue-does-not-exist" in rejected[0].detail["reason"]
    assert rejected[0].detail["failure_codes"] == ["unknown_subject_alias"]
    assert snapshot.result["rejected_candidates"] == 1
    assert snapshot.result["valid_candidates"] == 1


def test_operation_result_reports_turn_metrics(auth_client):
    registry, operation, _investigation = _run_operation(auth_client, _successful_rpc(auth_client))
    result = registry.get(operation.id).result

    assert result["termination"] == "recommendation_ready"
    assert result["latency_ms"] == 5
    assert result["provider"] == "stub-provider"
    assert result["usage"]["cache_read"] == 300
    assert result["tool_calls"] == 2
    assert result["tool_call_budget"] == 20
    assert result["simulation_count"] == 1
    assert result["valid_candidates"] == 1
    assert result["rejected_candidates"] == 0
    assert result["first_valid_candidate_ms"] is not None


def test_runtime_timeout_settles_operation_with_timeout_termination(auth_client):
    """A settled operation is not necessarily a successful run.

    `completed` means the registry finished processing; the run outcome travels in
    `result["termination"]` and the public advice `status`, never in the status flag.
    """

    def fake_rpc(_prompt, *, environment=None, **_kwargs):
        store = auth_client.app.state.pi_reconciliation_capabilities
        token = _token(environment)
        store.inspect(token)
        raise PiRpcTimeout(
            "Pi intervention timed out before the agent settled.",
            reason="timeout",
            latency_ms=180000,
            provider="stub-provider",
            model="cursor-grok-4.5",
            usage={
                "input": 500,
                "output": 10,
                "cache_read": 0,
                "cache_write": 0,
                "total_tokens": 510,
                "cost": 0.02,
            },
        )

    registry, operation, _investigation = _run_operation(auth_client, fake_rpc)
    snapshot = registry.get(operation.id)

    assert snapshot.status == "completed"
    result = snapshot.result
    assert result["termination"] == "runtime_timeout"  # not success: see docstring
    assert result["latency_ms"] == 180000
    assert result["provider"] == "stub-provider"
    assert result["model"] == "cursor-grok-4.5"
    assert result["usage"]["input"] == 500
    assert result["tool_calls"] == 1
    interrupted = [event for event in snapshot.events if event.type == "investigation_interrupted"]
    assert interrupted and interrupted[0].detail["reason"] == "runtime_timeout"

    advice = auth_client.get("/api/scheduler/resolution/advice").json()
    public = advice["data"]["pi_reconciliation"]
    assert public["status"] == "timeout"
    assert public["brief"]["termination"] == "budget_exhausted"


def test_process_exit_is_distinct_from_timeout(auth_client):
    def fake_rpc(_prompt, *, environment=None, **_kwargs):
        store = auth_client.app.state.pi_reconciliation_capabilities
        token = _token(environment)
        store.inspect(token)
        raise PiRpcTimeout(
            "Pi RPC exited before completing the intervention: boom",
            reason="exited",
            latency_ms=4200,
            provider="stub-provider",
            model="cursor-grok-4.5",
        )

    registry, operation, _investigation = _run_operation(auth_client, fake_rpc)
    snapshot = registry.get(operation.id)

    assert snapshot.result["termination"] == "crash"
    assert snapshot.result["latency_ms"] == 4200
    advice = auth_client.get("/api/scheduler/resolution/advice").json()
    assert advice["data"]["pi_reconciliation"]["status"] == "crash"


def test_tool_budget_exhaustion_is_distinct_from_runtime_timeout(auth_client):
    def fake_rpc(_prompt, *, environment=None, **_kwargs):
        store = auth_client.app.state.pi_reconciliation_capabilities
        token = _token(environment)
        inspected = store.inspect(token)
        alias = inspected["case_index"][0]["subject_alias"]
        store.submit(token, {
            "termination": "budget_exhausted",
            "title": "Bounded search complete",
            "rationale": "The Python exploration limit was reached.",
            "remaining_issues": [{"subject_alias": alias, "reason": "No package selected."}],
        })
        return _rpc_result()

    registry, operation, _investigation = _run_operation(
        auth_client,
        fake_rpc,
        max_tool_calls=1,
    )
    snapshot = registry.get(operation.id)

    assert snapshot.status == "completed"
    assert snapshot.result["termination"] == "budget_exhausted"
    assert snapshot.result["tool_calls"] == snapshot.result["tool_call_budget"] == 1
    advice = auth_client.get("/api/scheduler/resolution/advice").json()
    assert advice["data"]["pi_reconciliation"]["status"] == "completed"


def test_apply_error_carries_the_operation_id(auth_client):
    registry, operation, _investigation = _run_operation(auth_client, _successful_rpc(auth_client))
    advice = auth_client.get("/api/scheduler/resolution/advice").json()
    investigation_id = advice["data"]["pi_reconciliation"]["investigation_id"]
    workspace_version = advice["workspace_version"]

    response = auth_client.post(
        "/api/scheduler/resolution/reconciliation/{0}/apply".format(investigation_id),
        json={
            "expected_version": workspace_version,
            "simulation_id": "sim-does-not-exist",
            "confirmed_teacher_aliases": [],
            "confirmed_confirmation_ids": [],
            "authorized_sacrifice_aliases": [],
            "note": "",
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error"]["code"] == "PI_RECONCILIATION_APPLY_REJECTED"
    assert payload["error"]["operation_id"] == operation.id
