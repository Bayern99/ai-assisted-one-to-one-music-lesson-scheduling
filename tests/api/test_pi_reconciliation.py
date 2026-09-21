from __future__ import annotations

import json

import pytest

from modules.api.operations import OperationRegistry
from modules.api.services.pi_optimizer_intervention import (
    PiOptimizerInterventionError,
    PiRpcResult,
    PiRpcTimeout,
)
from modules.api.services.pi_reconciliation import (
    PiReconciliationCapabilityStore,
    _decision_from_record,
    _prior_day_decisions,
    build_reconciliation_investigation,
    run_pi_reconciliation_operation,
)
from modules.api.services.workspace import compute_workspace_version
from modules.scheduler.logic.optimizer_learning_record import (
    get_optimizer_learning_view,
    record_optimizer_run,
)
from modules.shared.session_manager import SessionManager


UNRESOLVED = {
    "id": "private-issue",
    "source_request_id": "private-source",
    "student": "Student Secret",
    "instructor": "Instructor 0008",
    "instrument": "Piano",
    "day": 1,
    "start": "10:00",
    "end": "11:00",
}


def _write_facts(client, rooms, room_types, eligibility):
    base_dir = client.app.state.config.base_dir
    (base_dir / "bookings.json").write_text("[]", encoding="utf-8")
    (base_dir / "rooms.json").write_text(json.dumps(rooms), encoding="utf-8")
    (base_dir / "scheduling_rules.json").write_text(
        json.dumps({
            "room_types": room_types,
            "instructor_time_change_eligibility": eligibility,
        }),
        encoding="utf-8",
    )


@pytest.fixture
def auth_client(client, bootstrap_token):
    base_dir = client.app.state.config.base_dir
    _write_facts(
        client,
        [{"id": "R1", "type": "Piano"}, {"id": "R2", "type": "Piano"}],
        {"R1": ["Piano"], "R2": ["Piano"]},
        {"Instructor 0008": "ask_allowed", "Instructor 0009": "ask_allowed"},
    )
    response = client.post(
        "/api/auth/exchange",
        headers={"X-PI-Bootstrap-Token": bootstrap_token},
    )
    assert response.status_code == 200
    return client


def test_decision_memory_keeps_only_the_packages_the_operator_decided():
    record = {
        "day": 1,
        "created_at": "2026-01-01T00:00:00+00:00",
        "operation_status": "completed",
        "brief": {
            "status": "rejected",
            "decided_at": "2026-01-02T00:00:00+00:00",
            "primary_simulation_id": "sim-selected",
            "fallback_simulation_id": None,
        },
        "simulations": {
            "sim-selected": {
                "raw_changes": [
                    {
                        "subject_alias": "event-selected",
                        "target": {"room": "R2", "day": 1, "start": "10:00", "end": "11:00"},
                    }
                ]
            },
            "sim-experiment": {
                "raw_changes": [
                    {
                        "subject_alias": "event-experiment",
                        "target": {"room": "R1", "day": 1, "start": "12:00", "end": "13:00"},
                    }
                ]
            },
        },
    }

    decision = _decision_from_record(record)
    assert decision["subject_ids"] == ["event-selected"]
    assert [item["simulation_id"] for item in decision["packages"]] == ["sim-selected"]
    assert decision["packages"][0]["changes"][0]["subject_alias"] == "event-selected"

    prior = _prior_day_decisions({"reconciliation_plans": {"plan": record}}, 1)
    assert prior == [{key: value for key, value in decision.items() if key != "day"}]
    assert "event-experiment" not in repr(prior)


def _install_run(client, unresolved=None, assignments=None, extra_unresolved=None):
    unresolved_items = list(unresolved if unresolved is not None else [UNRESOLVED])
    if extra_unresolved:
        unresolved_items.extend(extra_unresolved)
    state = {
        "step4_edit_session": {
            "optimizer_run_id": "run-reconciliation",
            "assignments": list(assignments or []),
            "unassigned_lessons": unresolved_items,
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


def _stub_rpc(client, target):
    """Drive the real capability store instead of a provider process."""

    def fake_rpc(_prompt, *, model, environment=None, **_kwargs):
        store = client.app.state.pi_reconciliation_capabilities
        token = environment["PI_RECONCILIATION_CAPABILITY"]
        inspected = store.inspect(token)
        alias = inspected["case_index"][0]["subject_alias"]
        simulation = store.simulate(token, [{"subject_alias": alias, "target": target}])
        assert simulation["feasible"], simulation["failure_codes"]
        store.submit(token, {
            "termination": "recommendation_ready",
            "primary_simulation_id": simulation["simulation_id"],
            "title": "Keep the original time",
            "rationale": "A compatible room is available.",
            "trade_offs": [],
            "limitations": ["Bounded single-day search."],
        })
        return PiRpcResult(
            text="Investigation complete.",
            pi_version="stub",
            provider="stub",
            model=model,
            latency_ms=5,
            usage={
                "input": 0,
                "output": 0,
                "cache_read": 0,
                "cache_write": 0,
                "total_tokens": 0,
                "cost": 0.0,
            },
        )

    return fake_rpc


def _investigate(client, *, target, day=1, rpc=None, **task_inputs):
    context = client.app.state.scheduler_context
    version = compute_workspace_version(context.loader.base_dir, context=context)
    investigation = build_reconciliation_investigation(
        context,
        expected_version=version,
        day=day,
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
        rpc_runner=rpc or _stub_rpc(client, target),
    )
    return investigation


def _public(client, expected_version=None):
    advice = client.get("/api/scheduler/resolution/advice").json()
    return advice, advice["data"]["pi_reconciliation"]


def test_capability_store_is_snapshot_bound_and_privacy_minimised(auth_client):
    _install_run(auth_client)
    context = auth_client.app.state.scheduler_context
    investigation = _investigate(
        auth_client,
        target={"room": "R1", "day": 1, "start": "10:00", "end": "11:00"},
    )

    record = investigation.persisted_record()
    # The local session record keeps the private snapshot; only server-issued
    # aliases may reach Pi, the ledger, or the API response.
    assert record["alias_to_subject"]["issue-1"][0] == "issue"

    _advice, public = _public(auth_client)
    assert public["scope_type"] == "day"
    assert public["day"] == 1
    assert public["status"] == "completed"
    assert public["stale"] is False
    assert public["brief"]["status"] == "proposed"
    assert public["brief"]["termination"] == "recommendation_ready"
    assert public["simulations"][0]["changes"]
    # This response only reaches the local authenticated operator, who needs real
    # instructor names to authorize a change, so it may carry display labels.
    assert public["teacher_display"]["Instructor 0008"] == "Instructor 0008"
    assert "private-source" not in json.dumps(public)

    # What the model sees stays alias-only, including failure evidence.
    context = auth_client.app.state.scheduler_context
    second = build_reconciliation_investigation(
        context,
        expected_version=compute_workspace_version(context.loader.base_dir, context=context),
        day=1,
    )
    store = auth_client.app.state.pi_reconciliation_capabilities
    token = store.create(second)
    inspected = store.inspect(token)
    refused = store.simulate(token, [
        {"subject_alias": inspected["case_index"][0]["subject_alias"], "target": {"room": "R9", "day": 1, "start": "10:00", "end": "11:00"}},
    ])
    for payload in (inspected, refused):
        text = json.dumps(payload)
        for secret in ("Student Secret", "private-source", "private-issue"):
            assert secret not in text, secret
        assert "Instructor 0008" in json.dumps(inspected)


def test_python_budget_allows_the_final_submit_audit_event(auth_client):
    _install_run(auth_client)
    context = auth_client.app.state.scheduler_context
    investigation = build_reconciliation_investigation(
        context,
        expected_version=compute_workspace_version(context.loader.base_dir, context=context),
        day=1,
        max_tool_calls=20,
    )
    store = PiReconciliationCapabilityStore()
    token = store.create(investigation)
    inspected = None
    for _ in range(20):
        inspected = store.inspect(token)
    issue_alias = inspected["case_index"][0]["subject_alias"]

    brief = store.submit(
        token,
        {
            "termination": "budget_exhausted",
            "title": "Bounded search complete",
            "rationale": "The Python exploration limit was reached.",
            "remaining_issues": [{"subject_alias": issue_alias, "reason": "No package selected."}],
        },
    )

    assert brief["termination"] == "budget_exhausted"
    events = store.snapshot(token)["tool_events"]
    assert len(events) == 21
    assert events[-1]["tool"] == "submit_reconciliation_brief"


def test_rpc_timeout_closes_as_interrupted_investigation(auth_client):
    _install_run(auth_client)

    def fake_rpc(_prompt, *, environment=None, **_kwargs):
        store = auth_client.app.state.pi_reconciliation_capabilities
        token = environment["PI_RECONCILIATION_CAPABILITY"]
        store.inspect(token)
        raise PiRpcTimeout("Pi intervention timed out before the agent settled.")

    _investigate(
        auth_client,
        target={"room": "R2", "day": 1, "start": "10:00", "end": "11:00"},
        rpc=fake_rpc,
    )
    _advice, public = _public(auth_client)
    assert public["brief"]["termination"] == "budget_exhausted"
    assert not public["brief"]["primary_simulation_id"]
    # A wall-clock timeout is not a completed investigation: the status names the
    # bound that stopped it, while the partial brief stays usable.
    assert public["status"] == "timeout"
    assert public["brief"]["remaining_issues"]


def test_rpc_error_after_brief_still_completes(auth_client):
    _install_run(auth_client)

    def fake_rpc(_prompt, *, environment=None, **_kwargs):
        store = auth_client.app.state.pi_reconciliation_capabilities
        token = environment["PI_RECONCILIATION_CAPABILITY"]
        inspected = store.inspect(token)
        alias = inspected["case_index"][0]["subject_alias"]
        simulation = store.simulate(
            token,
            [{"subject_alias": alias, "target": {"room": "R2", "day": 1, "start": "10:00", "end": "11:00"}}],
        )
        store.submit(token, {
            "termination": "recommendation_ready",
            "primary_simulation_id": simulation["simulation_id"],
            "title": "Keep the original time",
            "rationale": "A compatible room is available.",
        })
        raise PiOptimizerInterventionError("Pi could not complete the intervention.")

    _investigate(
        auth_client,
        target={"room": "R2", "day": 1, "start": "10:00", "end": "11:00"},
        rpc=fake_rpc,
    )
    _advice, public = _public(auth_client)
    assert public["status"] == "completed"
    assert public["brief"]["termination"] == "recommendation_ready"


def test_ledger_keeps_alias_evidence_and_drops_identities(auth_client):
    _install_run(auth_client)
    context = auth_client.app.state.scheduler_context
    _install_run(auth_client, assignments=[BLOCK_EVENT])
    _investigate(
        auth_client,
        target={"room": "R2", "day": 1, "start": "10:00", "end": "11:00"},
        goal="Please protect Student Secret",
        protect_instructors=["Instructor 0009"],
    )

    attempts = get_optimizer_learning_view(context.loader)["latest"]["reconciliation_attempts"]
    assert attempts
    text = json.dumps(attempts)
    for secret in (
        "Student Secret",
        "private-source",
        "private-issue",
        "teacher_display",
        "Please protect",
        "protect_teachers",
    ):
        assert secret not in text, secret
    assert attempts[0]["task"]["day"] == 1
    assert attempts[0]["task"]["protect_teacher_aliases"] == ["Instructor 0009"]
    assert attempts[0]["simulations"]
    assert "changes" not in attempts[0]["simulations"][0]


def test_apply_is_one_whole_package_approval_with_undo(auth_client):
    _install_run(auth_client)
    context = auth_client.app.state.scheduler_context
    _investigate(
        auth_client,
        target={"room": "R1", "day": 1, "start": "10:00", "end": "11:00"},
    )
    advice, public = _public(auth_client)
    version = advice["workspace_version"]
    simulation_id = public["simulations"][0]["simulation_id"]

    applied = auth_client.post(
        f"/api/scheduler/resolution/reconciliation/{public['investigation_id']}/apply",
        json={
            "expected_version": version,
            "simulation_id": simulation_id,
            "confirmed_teacher_aliases": [],
            "note": "Applied.",
        },
    )
    assert applied.status_code == 200, applied.json()
    payload = applied.json()
    session = auth_client.get("/api/scheduler/session").json()["data"]
    assert session["metrics"]["unresolved"] == 0
    assert session["metrics"]["assigned"] == 1
    assert session["assignments"][0]["resourceId"] == "R1"

    _advice_after, after = _public(auth_client)
    assert after["status"] == "applied"
    applied_change = after["apply_result"]["changes"][0]
    assert applied_change["action"] == "place"
    assert applied_change["teacher"] == "Instructor 0008"
    assert applied_change["from"]["room"] is None
    assert applied_change["to"]["room"] == "R1"
    assert after["apply_result"]["metrics"]["resolved_delta"] == 1

    undone = auth_client.post(
        "/api/scheduler/draft/undo",
        json={"expected_version": payload["workspace_version"]},
    )
    assert undone.status_code == 200, undone.json()
    restored = auth_client.get("/api/scheduler/session").json()["data"]
    assert restored["metrics"]["unresolved"] == 1
    assert restored["metrics"]["assigned"] == 0


def test_applied_record_failure_is_reported_as_a_warning(auth_client, monkeypatch):
    _install_run(auth_client)
    _investigate(
        auth_client,
        target={"room": "R1", "day": 1, "start": "10:00", "end": "11:00"},
    )
    advice, public = _public(auth_client)

    from modules.api.services import pi_reconciliation as service

    def fail_record(_context, _record):
        raise RuntimeError("task record store unavailable")

    monkeypatch.setattr(service, "_persist_private_investigation", fail_record)
    applied = auth_client.post(
        f"/api/scheduler/resolution/reconciliation/{public['investigation_id']}/apply",
        json={
            "expected_version": advice["workspace_version"],
            "simulation_id": public["simulations"][0]["simulation_id"],
            "confirmed_teacher_aliases": [],
            "note": "",
        },
    )

    assert applied.status_code == 200, applied.json()
    warnings = applied.json()["warnings"]
    assert any("applied and saved" in item for item in warnings)
    session = auth_client.get("/api/scheduler/session").json()["data"]
    assert session["metrics"]["unresolved"] == 0
    assert session["metrics"]["assigned"] == 1


def test_time_change_needs_an_explicit_exception_before_confirmation(auth_client):
    _install_run(auth_client)
    context = auth_client.app.state.scheduler_context
    version = compute_workspace_version(context.loader.base_dir, context=context)
    investigation = build_reconciliation_investigation(
        context, expected_version=version, day=1,
    )
    store = PiReconciliationCapabilityStore()
    token = store.create(investigation)
    alias = store.inspect(token)["case_index"][0]["subject_alias"]

    refused = store.simulate(token, [
        {"subject_alias": alias, "target": {"room": "R1", "day": 1, "start": "14:00", "end": "15:00"}},
    ])
    assert refused["status"] == "infeasible"
    assert refused["failure_codes"] == ["time_change_not_authorized"]

    cross_day = store.simulate(token, [
        {"subject_alias": alias, "target": {"room": "R1", "day": 2, "start": "10:00", "end": "11:00"}},
    ])
    assert cross_day["status"] == "infeasible"
    assert cross_day["failure_codes"] == ["cross_day_out_of_scope"]


def test_teacher_confirmation_gates_only_that_teacher(auth_client):
    _install_run(auth_client, assignments=[BLOCK_EVENT])
    investigation = _investigate(
        auth_client,
        target={"room": "R1", "day": 1, "start": "10:00", "end": "11:00"},
        allow_time_change_instructors=["Instructor 0008"],
        goal="Move the weekly lesson later the same day.",
        rpc=_time_change_rpc(auth_client, start="14:00", end="15:00"),
    )
    advice, public = _public(auth_client)
    simulation = public["simulations"][0]
    assert simulation["status"] == "conditional"
    assert simulation["same_day_time_change"] is True
    alias = simulation["required_teacher_confirmations"][0]["teacher_alias"]
    confirmation_id = simulation["required_teacher_confirmations"][0]["confirmation_id"]
    assert alias == "Instructor 0008"

    blocked = auth_client.post(
        f"/api/scheduler/resolution/reconciliation/{public['investigation_id']}/apply",
        json={
            "expected_version": advice["workspace_version"],
            "simulation_id": simulation["simulation_id"],
            "confirmed_teacher_aliases": [],
            "confirmed_confirmation_ids": [],
            "note": "",
        },
    )
    assert blocked.status_code == 400
    assert "confirm" in json.dumps(blocked.json()).lower()

    stolen = auth_client.post(
        f"/api/scheduler/resolution/reconciliation/{public['investigation_id']}/apply",
        json={
            "expected_version": advice["workspace_version"],
            "simulation_id": simulation["simulation_id"],
            "confirmed_teacher_aliases": [alias],
            "confirmed_confirmation_ids": ["not-this-package"],
            "note": "Teacher agreed.",
        },
    )
    assert stolen.status_code == 400

    applied = auth_client.post(
        f"/api/scheduler/resolution/reconciliation/{public['investigation_id']}/apply",
        json={
            "expected_version": advice["workspace_version"],
            "simulation_id": simulation["simulation_id"],
            "confirmed_teacher_aliases": [alias],
            "confirmed_confirmation_ids": [confirmation_id],
            "note": "Teacher agreed.",
        },
    )
    assert applied.status_code == 200, applied.json()
    assignments = auth_client.get("/api/scheduler/session").json()["data"]["assignments"]
    # Only the teacher who was asked carries a confirmation; the moved block
    # keeps its room without borrowing Instructor 0008's consent.
    confirmed = {
        item["extendedProps"]["Instructor"]: "teacher_time_change_confirmation" in item["extendedProps"]
        for item in assignments
    }
    assert confirmed["Instructor 0008"] is True
    assert confirmed["Instructor 0009"] is False
    assert investigation.persisted_record()


def _time_change_rpc(client, *, start, end):
    def fake_rpc(_prompt, *, model, environment=None, **_kwargs):
        store = client.app.state.pi_reconciliation_capabilities
        token = environment["PI_RECONCILIATION_CAPABILITY"]
        inspected = store.inspect(token)
        block = inspected["blocks"][0]
        simulation = store.simulate(token, [
            {"subject_alias": block["subject_alias"], "target": {"room": "R2"}},
            {
                "subject_alias": inspected["case_index"][0]["subject_alias"],
                "target": {"room": "R1", "day": 1, "start": start, "end": end},
            },
        ])
        store.submit(token, {
            "termination": "recommendation_ready",
            "primary_simulation_id": simulation["simulation_id"],
            "title": "Same-day time change",
            "rationale": "No fixed-time package was acceptable.",
            "trade_offs": ["The lesson moves later the same day."],
            "limitations": [],
            "pending_decisions": [
                {"kind": "exception_authorization", "detail": "Needs the teacher's agreement."},
            ],
        })
        return PiRpcResult(
            text="done", pi_version="stub", provider="stub", model=model, latency_ms=1,
            usage={"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "total_tokens": 0, "cost": 0.0},
        )

    return fake_rpc


def test_stale_schedule_rejects_apply(auth_client):
    _install_run(auth_client)
    _investigate(
        auth_client,
        target={"room": "R1", "day": 1, "start": "10:00", "end": "11:00"},
    )
    advice, public = _public(auth_client)
    simulation_id = public["simulations"][0]["simulation_id"]

    response = auth_client.post(
        "/api/scheduler/issues/private-issue/assign",
        json={
            "room": "R2",
            "day": 1,
            "start": "10:00",
            "end": "11:00",
            "expected_version": compute_workspace_version(
                auth_client.app.state.config.base_dir,
                context=auth_client.app.state.scheduler_context,
            ),
        },
    )
    assert response.status_code == 200, response.json()

    current = compute_workspace_version(
        auth_client.app.state.config.base_dir,
        context=auth_client.app.state.scheduler_context,
    )
    stale = auth_client.post(
        f"/api/scheduler/resolution/reconciliation/{public['investigation_id']}/apply",
        json={
            "expected_version": current,
            "simulation_id": simulation_id,
            "confirmed_teacher_aliases": [],
            "note": "",
        },
    )
    assert stale.status_code in {400, 409}
    body = json.dumps(stale.json()).lower()
    assert "changed" in body or "no longer present" in body


def test_reconciliation_package_rejections(auth_client):
    _install_run(auth_client)
    context = auth_client.app.state.scheduler_context
    version = compute_workspace_version(context.loader.base_dir, context=context)
    investigation = build_reconciliation_investigation(
        context,
        expected_version=version,
        day=1,
    )
    store = PiReconciliationCapabilityStore()
    token = store.create(investigation)
    alias = store.inspect(token)["case_index"][0]["subject_alias"]

    duplicate = store.simulate(token, [
        {"subject_alias": alias, "target": {"room": "R1", "day": 1, "start": "10:00", "end": "11:00"}},
        {"subject_alias": alias, "target": {"room": "R2", "day": 1, "start": "10:00", "end": "11:00"}},
    ])
    assert duplicate["status"] == "infeasible"
    assert duplicate["failure_codes"]

    unknown = store.simulate(token, [
        {"subject_alias": "issue-999", "target": {"room": "R1", "day": 1, "start": "10:00", "end": "11:00"}},
    ])
    assert unknown["status"] == "infeasible"

    occupied = store.simulate(token, [
        {"subject_alias": alias, "target": {"room": "R9", "day": 1, "start": "10:00", "end": "11:00"}},
    ])
    assert occupied["status"] == "infeasible"

    feasible = store.simulate(token, [
        {"subject_alias": alias, "target": {"room": "R1", "day": 1, "start": "10:00", "end": "11:00"}},
    ])
    assert feasible["status"] == "feasible"
    # The model-facing tool surface stays alias-only; the operator's local record
    # carries the display labels (asserted in the advice payload below).
    assert "changes" not in feasible
    assert feasible["normalized_changes"][0]["subject_alias"] == alias


BLOCK_EVENT = {
    "id": "block-event",
    "type": "weekly_lesson",
    "resourceId": "R1",
    "daysOfWeek": [1],
    "startTime": "10:00:00",
    "endTime": "11:00:00",
    "extendedProps": {"Instructor": "Instructor 0009", "Instrument": "Piano"},
}


def test_teacher_day_block_moves_as_a_unit_through_the_tool_surface(auth_client):
    _install_run(auth_client, assignments=[BLOCK_EVENT])
    context = auth_client.app.state.scheduler_context

    def block_rpc(_prompt, *, model, environment=None, **_kwargs):
        store = auth_client.app.state.pi_reconciliation_capabilities
        token = environment["PI_RECONCILIATION_CAPABILITY"]
        inspected = store.inspect(token)
        block = inspected["blocks"][0]
        assert block["candidate_rooms"] == ["R2"]
        simulation = store.simulate(token, [
            {"subject_alias": block["subject_alias"], "target": {"room": "R2"}},
            {
                "subject_alias": inspected["case_index"][0]["subject_alias"],
                "target": {"room": "R1", "day": 1, "start": "10:00", "end": "11:00"},
            },
        ])
        assert simulation["status"] == "feasible"
        assert simulation["metrics"]["moved_assignments"] == 1
        store.submit(token, {
            "termination": "recommendation_ready",
            "primary_simulation_id": simulation["simulation_id"],
            "title": "Swap rooms for the day block",
            "rationale": "The teacher-day block moves as a unit into the free room.",
            "trade_offs": [],
            "limitations": [],
            "remaining_issues": [],
        })
        return PiRpcResult(
            text="done", pi_version="stub", provider="stub", model=model, latency_ms=1,
            usage={"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "total_tokens": 0, "cost": 0.0},
        )

    version = compute_workspace_version(context.loader.base_dir, context=context)
    investigation = build_reconciliation_investigation(
        context, expected_version=version, day=1,
    )
    registry = OperationRegistry()
    operation = registry.create("pi_reconciliation")
    run_pi_reconciliation_operation(
        context=context,
        registry=registry,
        operation_id=operation.id,
        investigation=investigation,
        model="cursor-grok-4.5",
        tool_url="http://127.0.0.1:1/unused",
        capability_store=auth_client.app.state.pi_reconciliation_capabilities,
        rpc_runner=block_rpc,
    )
    assert registry.get(operation.id).status == "completed"

    advice, public = _public(auth_client)
    simulation_id = public["simulations"][0]["simulation_id"]
    applied = auth_client.post(
        f"/api/scheduler/resolution/reconciliation/{public['investigation_id']}/apply",
        json={
            "expected_version": advice["workspace_version"],
            "simulation_id": simulation_id,
            "confirmed_teacher_aliases": [],
            "note": "",
        },
    )
    assert applied.status_code == 200, applied.json()
    session = auth_client.get("/api/scheduler/session").json()["data"]
    assert session["metrics"]["unresolved"] == 0
    rooms = {item["id"]: item["resourceId"] for item in session["assignments"]}
    assert sorted(rooms.values()) == ["R1", "R2"]


SACRIFICE_BLOCK = {
    "id": "block-event",
    "type": "weekly_lesson",
    "resourceId": "R1",
    "daysOfWeek": [1],
    "startTime": "10:00:00",
    "endTime": "11:00:00",
    "extendedProps": {"Instructor": "Instructor 0009", "Instrument": "Piano"},
}
SACRIFICE_BLOCK_SECOND = {
    **SACRIFICE_BLOCK,
    "id": "block-event-2",
    "startTime": "12:00:00",
    "endTime": "13:00:00",
}


def test_sacrifice_needs_its_own_authorization_before_apply(auth_client):
    _write_facts(
        auth_client,
        [{"id": "R1", "type": "Piano"}, {"id": "R3", "type": "Voice"}],
        {"R1": ["Piano"], "R3": ["Voice"]},
        {"Instructor 0008": "ask_allowed", "Instructor 0009": "ask_allowed"},
    )
    _install_run(auth_client, assignments=[SACRIFICE_BLOCK, SACRIFICE_BLOCK_SECOND])
    context = auth_client.app.state.scheduler_context

    def sacrifice_rpc(_prompt, *, model, environment=None, **_kwargs):
        store = auth_client.app.state.pi_reconciliation_capabilities
        token = environment["PI_RECONCILIATION_CAPABILITY"]
        inspected = store.inspect(token)
        block = inspected["blocks"][0]
        assert block["candidate_rooms"] == []
        assert block["withdrawable"] is True
        simulation = store.simulate(token, [
            {"subject_alias": block["subject_alias"], "withdraw": True},
            {
                "subject_alias": inspected["case_index"][0]["subject_alias"],
                "target": {"room": "R1", "day": 1, "start": "10:00", "end": "11:00"},
            },
        ])
        assert simulation["status"] == "conditional"
        assert simulation["requires_sacrifice_authorization"] is True
        store.submit(token, {
            "termination": "recommendation_ready",
            "primary_simulation_id": simulation["simulation_id"],
            "title": "Trade the block for the missing lesson",
            "rationale": "No room can hold the block unchanged.",
            "trade_offs": ["One teacher-day block loses its place."],
            "limitations": ["Only a bounded room set was searched."],
            "pending_decisions": [
                {"kind": "business_tradeoff", "detail": "Accepting the sacrifice is the operator's call."},
            ],
        })
        return PiRpcResult(
            text="done", pi_version="stub", provider="stub", model=model, latency_ms=1,
            usage={"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "total_tokens": 0, "cost": 0.0},
        )

    version = compute_workspace_version(context.loader.base_dir, context=context)
    investigation = build_reconciliation_investigation(
        context, expected_version=version, day=1,
        goal="Place the missing lesson even at a real cost.",
    )
    registry = OperationRegistry()
    operation = registry.create("pi_reconciliation")
    run_pi_reconciliation_operation(
        context=context,
        registry=registry,
        operation_id=operation.id,
        investigation=investigation,
        model="cursor-grok-4.5",
        tool_url="http://127.0.0.1:1/unused",
        capability_store=auth_client.app.state.pi_reconciliation_capabilities,
        rpc_runner=sacrifice_rpc,
    )
    assert registry.get(operation.id).status == "completed"

    advice, public = _public(auth_client)
    simulation = public["simulations"][0]
    assert public["brief"]["requires_sacrifice_authorization"] is True
    assert public["brief"]["pending_decisions"][0]["kind"] == "business_tradeoff"
    assert public["task"]["goal"] == "Place the missing lesson even at a real cost."
    sacrifice_aliases = [item["subject_alias"] for item in simulation["sacrifices"]]
    # The complete teacher-day block is the sacrificed unit.
    assert sacrifice_aliases == ["assignment-1", "assignment-2"]
    assert simulation["metrics"]["sacrificed_assignments"] == 2

    blocked = auth_client.post(
        f"/api/scheduler/resolution/reconciliation/{public['investigation_id']}/apply",
        json={
            "expected_version": advice["workspace_version"],
            "simulation_id": simulation["simulation_id"],
            "confirmed_teacher_aliases": [],
            "authorized_sacrifice_aliases": [],
            "note": "",
        },
    )
    assert blocked.status_code == 400
    assert "sacrifice" in json.dumps(blocked.json()).lower()

    partial = auth_client.post(
        f"/api/scheduler/resolution/reconciliation/{public['investigation_id']}/apply",
        json={
            "expected_version": advice["workspace_version"],
            "simulation_id": simulation["simulation_id"],
            "confirmed_teacher_aliases": [],
            "authorized_sacrifice_aliases": sacrifice_aliases[:1],
            "note": "",
        },
    )
    assert partial.status_code == 400

    applied = auth_client.post(
        f"/api/scheduler/resolution/reconciliation/{public['investigation_id']}/apply",
        json={
            "expected_version": advice["workspace_version"],
            "simulation_id": simulation["simulation_id"],
            "confirmed_teacher_aliases": [],
            "authorized_sacrifice_aliases": sacrifice_aliases,
            "note": "Operator accepted the cost.",
        },
    )
    assert applied.status_code == 200, applied.json()
    session = auth_client.get("/api/scheduler/session").json()["data"]
    assert session["metrics"]["assigned"] == 1
    assert session["metrics"]["unresolved"] == 2
    unresolved_instructors = {
        item["instructor"] for group in session["issues"] for item in group["items"]
    }
    assert unresolved_instructors == {"Instructor 0009"}

    _advice_after, after = _public(auth_client)
    applied_rows = after["apply_result"]["changes"]
    assert sorted({row["action"] for row in applied_rows}) == ["place", "withdraw"]
    assert {row["teacher"] for row in applied_rows} == {"Instructor 0008", "Instructor 0009"}
    assert all(row["is_sacrifice"] for row in applied_rows if row["action"] == "withdraw")

    undone = auth_client.post(
        "/api/scheduler/draft/undo",
        json={"expected_version": applied.json()["workspace_version"]},
    )
    assert undone.status_code == 200, undone.json()
    restored = auth_client.get("/api/scheduler/session").json()["data"]
    assert restored["metrics"]["assigned"] == 2
    assert restored["metrics"]["unresolved"] == 1


def test_follow_up_investigation_carries_the_last_thread(auth_client):
    _install_run(auth_client)
    _investigate(
        auth_client,
        target={"room": "R1", "day": 1, "start": "10:00", "end": "11:00"},
        goal="Place the instrumental lesson first.",
    )
    context = auth_client.app.state.scheduler_context
    version = compute_workspace_version(context.loader.base_dir, context=context)
    follow_up = build_reconciliation_investigation(
        context,
        expected_version=version,
        day=1,
        goal="The remaining voice lesson may use a small room as an emergency.",
    )
    thread = follow_up.model_task()["prior_thread"]
    assert thread["goal"] == "Place the instrumental lesson first."
    assert thread["goals"] == ["Place the instrumental lesson first."]
    assert thread["termination"] == "recommendation_ready"


def test_rejected_brief_records_the_decision_and_blocks_apply(auth_client):
    _install_run(auth_client)
    _investigate(
        auth_client,
        target={"room": "R1", "day": 1, "start": "10:00", "end": "11:00"},
    )
    advice, public = _public(auth_client)

    decision = auth_client.post(
        f"/api/scheduler/resolution/reconciliation/{public['investigation_id']}/decision",
        json={
            "expected_version": advice["workspace_version"],
            "decision": "rejected",
            "note": "代价不能接受。",
        },
    )
    assert decision.status_code == 200, decision.json()
    _advice_after, after = _public(auth_client)
    assert after["brief"]["status"] == "rejected"
    assert after["brief"]["decision_note"] == "代价不能接受。"

    blocked = auth_client.post(
        f"/api/scheduler/resolution/reconciliation/{public['investigation_id']}/apply",
        json={
            "expected_version": decision.json()["workspace_version"],
            "simulation_id": public["simulations"][0]["simulation_id"],
            "confirmed_teacher_aliases": [],
            "note": "",
        },
    )
    assert blocked.status_code == 400
    assert "rejected" in json.dumps(blocked.json()).lower()

    # A new investigation carries the earlier rejection as task memory.
    _investigate(
        auth_client,
        target={"room": "R1", "day": 1, "start": "10:00", "end": "11:00"},
    )
    _advice_next, next_public = _public(auth_client)
    assert next_public["task"]["prior_decisions"][0]["status"] == "rejected"


def test_whole_day_scope_covers_every_unresolved_lesson_on_that_day(auth_client):
    _install_run(
        auth_client,
        extra_unresolved=[
            {
                "id": "second-issue",
                "source_request_id": "second-source",
                "instructor": "Instructor 0009",
                "instrument": "Piano",
                "day": 1,
                "start": "12:00",
                "end": "13:00",
            },
            {
                "id": "other-day-issue",
                "source_request_id": "other-day-source",
                "instructor": "Instructor 0009",
                "instrument": "Piano",
                "day": 3,
                "start": "12:00",
                "end": "13:00",
            },
        ],
    )
    context = auth_client.app.state.scheduler_context
    version = compute_workspace_version(context.loader.base_dir, context=context)
    investigation = build_reconciliation_investigation(
        context,
        expected_version=version,
        day=1,
    )
    store = PiReconciliationCapabilityStore()
    token = store.create(investigation)
    inspected = store.inspect(token)

    assert len(inspected["case_index"]) == 2
    assert {item["teacher_alias"] for item in inspected["case_index"]} == {"Instructor 0008", "Instructor 0009"}
    assert investigation.day == 1
    assert all(item["day"] == 1 for item in inspected["subjects"] if item["kind"] == "issue")


def test_reservation_internal_rows_are_not_reopened_as_work(auth_client):
    _install_run(
        auth_client,
        assignments=[BLOCK_EVENT],
        unresolved=[
            {
                "id": "studio-parked",
                "source_request_id": "studio-parked-source",
                "type": "studio_class",
                "instructor": "Instructor 0009",
                "instrument": "Piano",
                "day": 1,
                "start": "10:00",
                "end": "11:00",
            }
        ],
    )
    context = auth_client.app.state.scheduler_context
    version = compute_workspace_version(context.loader.base_dir, context=context)

    with pytest.raises(Exception) as error:
        build_reconciliation_investigation(
            context,
            expected_version=version,
            day=1,
        )
    assert "reservation-internal" in str(error.value)

    # A real queue row on the same day is still investigated.
    state = SessionManager(base_dir=str(auth_client.app.state.config.base_dir)).load_session()
    state["step4_edit_session"]["unassigned_lessons"].append({**UNRESOLVED, "day": 1})
    SessionManager(base_dir=str(auth_client.app.state.config.base_dir)).save_session(state)
    version = compute_workspace_version(context.loader.base_dir, context=context)
    investigation = build_reconciliation_investigation(
        context,
        expected_version=version,
        day=1,
    )
    assert investigation._scope_issue_ids == {"private-issue"}


def test_instructor_lists_reject_unknown_names(auth_client):
    _install_run(auth_client)
    context = auth_client.app.state.scheduler_context
    version = compute_workspace_version(context.loader.base_dir, context=context)
    with pytest.raises(Exception) as error:
        build_reconciliation_investigation(
            context,
            expected_version=version,
            day=1,
            protect_instructors=["Nobody Here"],
        )
    assert "Unknown instructor" in str(error.value)


def test_task_premises_map_instructor_names_to_aliases(auth_client):
    _install_run(auth_client, assignments=[SACRIFICE_BLOCK])
    context = auth_client.app.state.scheduler_context
    version = compute_workspace_version(context.loader.base_dir, context=context)
    investigation = build_reconciliation_investigation(
        context,
        expected_version=version,
        day=1,
        protect_instructors=["Instructor 0009"],
        allow_time_change_instructors=["Instructor 0008"],
    )
    task = investigation.public_task()
    assert task["protect_teacher_aliases"] == ["Instructor 0009"]
    assert task["time_change_exception_teacher_aliases"] == ["Instructor 0008"]
    assert task["time_is_fixed"] is True
    assert "Instructor 0009" in json.dumps(task)

    store = PiReconciliationCapabilityStore()
    token = store.create(investigation)
    inspected = store.inspect(token)
    block = inspected["blocks"][0]
    assert block["withdrawable"] is False
    blocked = store.simulate(token, [
        {"subject_alias": block["subject_alias"], "target": {"room": "R2"}},
    ])
    assert blocked["failure_codes"] == ["protected_subject"]
