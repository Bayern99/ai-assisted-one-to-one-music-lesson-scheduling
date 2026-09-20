from __future__ import annotations

import json

import pytest

from modules.api.services.pi_optimizer_intervention import (
    PiOptimizerInterventionError,
    PiRpcTimeout,
    THINKING_LEVELS,
    public_pi_runtime,
    resolve_pi_runtime,
    run_pi_rpc,
)


def _touch_extensions(tmp_path):
    provider = tmp_path / "cursor.js"
    tool = tmp_path / "intervention.js"
    provider.write_text("export default () => {}", encoding="utf-8")
    tool.write_text("export default () => {}", encoding="utf-8")
    return provider, tool


def _fake_pi(
    tmp_path,
    assertions: str = "",
    *,
    version: str = "0.82.1",
    interpreter: str = "python3",
):
    executable = tmp_path / "fake-pi"
    executable.write_text(
        f"""#!/usr/bin/env {interpreter}
import json
import os
import sys

def read_prompt():
    while True:
        line = sys.stdin.readline()
        if not line:
            raise SystemExit(1)
        request = json.loads(line)
        if request.get("type") == "prompt":
            return request
        print(json.dumps({{"id": request.get("id"), "type": "response", "command": request.get("type"), "success": True}}), flush=True)

if "--version" in sys.argv:
    print({version!r})
    raise SystemExit

{assertions}
request = read_prompt()
print(json.dumps({{"id": request["id"], "type": "response", "command": "prompt", "success": True}}), flush=True)
message = {{
    "role": "assistant",
    "content": [{{"type": "text", "text": "Proposal submitted."}}],
    "provider": sys.argv[sys.argv.index("--provider") + 1],
    "model": sys.argv[sys.argv.index("--model") + 1],
    "usage": {{
        "input": 10, "output": 2, "cacheRead": 1, "cacheWrite": 0,
        "cost": {{"total": 0.001}},
    }},
    "stopReason": "stop",
}}
print(json.dumps({{"type": "message_end", "message": message}}), flush=True)
print(json.dumps({{"type": "agent_settled"}}), flush=True)
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable


def test_pi_rpc_loads_only_cursor_first_party_model_and_controlled_tools(tmp_path):
    provider, tool = _touch_extensions(tmp_path)
    executable = _fake_pi(
        tmp_path,
        """
required = {
    "--mode", "rpc", "--no-session", "--no-builtin-tools", "--no-extensions",
    "--no-skills", "--no-prompt-templates", "--no-context-files",
    "--no-themes", "--no-approve",
}
assert required.issubset(set(sys.argv))
assert "--no-tools" not in sys.argv
assert sys.argv[sys.argv.index("--provider") + 1] == "cursor"
assert sys.argv[sys.argv.index("--model") + 1] == "cursor-grok-4.5"
assert sys.argv[sys.argv.index("--thinking") + 1] == "off"
assert sys.argv[sys.argv.index("--tools") + 1] == "inspect_optimizer_case,simulate_intervention,submit_intervention_proposal"
extension_args = [sys.argv[index + 1] for index, value in enumerate(sys.argv) if value == "--extension"]
assert len(extension_args) == 2
assert os.environ["PI_INTERVENTION_CAPABILITY"] == "scoped-token"
assert os.environ["PI_RECONCILIATION_TOOL_URL"] == "http://127.0.0.1:9999/tool"
assert os.environ["PI_RECONCILIATION_CAPABILITY"] == "reconciliation-token"
assert "PI_SHOULD_NOT_LEAK" not in os.environ
""",
    )

    result = run_pi_rpc(
        "investigate",
        executable=str(executable),
        model="cursor-grok-4.5",
        provider_extension=str(provider),
        tool_extension=str(tool),
        environment={
            "PI_INTERVENTION_CAPABILITY": "scoped-token",
            "PI_RECONCILIATION_TOOL_URL": "http://127.0.0.1:9999/tool",
            "PI_RECONCILIATION_CAPABILITY": "reconciliation-token",
            "PI_SHOULD_NOT_LEAK": "secret",
        },
        timeout_seconds=2,
    )

    assert result.provider == "cursor"
    assert result.model == "cursor-grok-4.5"
    assert result.usage["total_tokens"] == 13


def test_pi_rpc_accepts_updated_pi_and_finds_its_sibling_runtime(
    tmp_path,
    monkeypatch,
):
    provider, tool = _touch_extensions(tmp_path)
    runtime = tmp_path / "pi-test-runtime"
    runtime.write_text(
        "#!/bin/sh\nexec /usr/bin/python3 \"$@\"\n",
        encoding="utf-8",
    )
    runtime.chmod(0o755)
    executable = _fake_pi(
        tmp_path,
        version="0.83.0",
        interpreter="pi-test-runtime",
    )
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    result = run_pi_rpc(
        "investigate",
        executable=str(executable),
        model="cursor-grok-4.5",
        provider_extension=str(provider),
        tool_extension=str(tool),
        timeout_seconds=2,
    )

    assert result.pi_version == "0.83.0"


def test_pi_rpc_rejects_models_outside_cursor_first_party_pool(tmp_path):
    provider, tool = _touch_extensions(tmp_path)

    with pytest.raises(PiOptimizerInterventionError, match="not allowed"):
        run_pi_rpc(
            "investigate",
            executable=str(tmp_path / "never-run"),
            model="gpt-5.4-mini",
            provider_extension=str(provider),
            tool_extension=str(tool),
        )


def test_resolve_pi_runtime_inherits_outer_pi_settings(tmp_path, monkeypatch):
    agent = tmp_path / "agent"
    agent.mkdir()
    (agent / "settings.json").write_text(
        json.dumps({"defaultProvider": "openai-codex", "defaultModel": "gpt-5.6-luna"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(agent))
    monkeypatch.delenv("PI_PROVIDER", raising=False)
    monkeypatch.delenv("PI_ALLOWED_MODELS", raising=False)

    target = resolve_pi_runtime(model="cursor-grok-4.5")
    assert target.provider == "openai-codex"
    assert target.model == "gpt-5.6-luna"
    assert "gpt-5.6-luna" in target.allowed_models

    pinned = resolve_pi_runtime(model="cursor-grok-4.5", executable=str(tmp_path / "fake-pi"))
    assert pinned.provider == "cursor"
    assert pinned.model == "cursor-grok-4.5"

    assert public_pi_runtime() == {
        "provider": "openai-codex",
        "model": "gpt-5.6-luna",
        "thinking_level": "off",
        "thinking_levels": list(THINKING_LEVELS),
        "choices": [{"provider": "openai-codex", "model": "gpt-5.6-luna"}],
        "allowed_models": ["gpt-5.6-luna"],
    }


def test_public_pi_runtime_lists_catalog_models_not_retired_picker_ids(tmp_path, monkeypatch):
    agent = tmp_path / "agent"
    agent.mkdir()
    (agent / "settings.json").write_text(
        json.dumps({"defaultProvider": "openai-codex", "defaultModel": "gpt-5.6-luna"}),
        encoding="utf-8",
    )
    (agent / "models-store.json").write_text(
        json.dumps({
            "deepseek": {"models": [{"id": "deepseek-flash"}]},
            "kimi-coding": {"models": [{"id": "k3"}]},
            "llama.cpp": {"models": [{"id": "UD-Q5_K_XL"}]},
            "openai-codex": {
                "models": [
                    {"id": "gpt-5.6-luna"},
                    {"id": "gpt-5.3-codex-spark"},
                ]
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(agent))
    monkeypatch.delenv("PI_PROVIDER", raising=False)
    monkeypatch.delenv("PI_ALLOWED_MODELS", raising=False)

    view = public_pi_runtime()
    assert view["provider"] == "openai-codex"
    assert view["model"] == "gpt-5.6-luna"
    assert view["thinking_level"] == "off"
    assert view["thinking_levels"] == list(THINKING_LEVELS)
    assert view["choices"] == [
        {"provider": "deepseek", "model": "deepseek-flash"},
        {"provider": "kimi-coding", "model": "k3"},
        {"provider": "llama.cpp", "model": "UD-Q5_K_XL"},
        {"provider": "openai-codex", "model": "gpt-5.3-codex-spark"},
        {"provider": "openai-codex", "model": "gpt-5.6-luna"},
    ]
    assert view["allowed_models"] == [
        "UD-Q5_K_XL",
        "deepseek-flash",
        "gpt-5.3-codex-spark",
        "gpt-5.6-luna",
        "k3",
    ]
    assert "cursor-grok-4.5" not in view["allowed_models"]
    assert "composer-2.5" not in view["allowed_models"]


def test_resolve_pi_runtime_does_not_inherit_coding_agent_thinking(tmp_path, monkeypatch):
    agent = tmp_path / "agent"
    agent.mkdir()
    (agent / "settings.json").write_text(
        json.dumps({
            "defaultProvider": "openai-codex",
            "defaultModel": "gpt-5.6-luna",
            "defaultThinkingLevel": "max",
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(agent))
    monkeypatch.delenv("PI_PROVIDER", raising=False)
    monkeypatch.delenv("PI_ALLOWED_MODELS", raising=False)

    inherited = resolve_pi_runtime()
    assert inherited.provider == "openai-codex"
    assert inherited.model == "gpt-5.6-luna"
    assert inherited.thinking_level == "off"

    selected = resolve_pi_runtime(
        provider="openai-codex",
        model="gpt-5.6-luna",
        thinking="high",
    )
    assert selected.thinking_level == "high"


def test_pi_rpc_passes_selected_thinking_level(tmp_path):
    provider, tool = _touch_extensions(tmp_path)
    executable = _fake_pi(
        tmp_path,
        """
assert sys.argv[sys.argv.index("--provider") + 1] == "cursor"
assert sys.argv[sys.argv.index("--model") + 1] == "cursor-grok-4.5"
assert sys.argv[sys.argv.index("--thinking") + 1] == "high"
""",
    )
    result = run_pi_rpc(
        "investigate",
        executable=str(executable),
        model="cursor-grok-4.5",
        thinking="high",
        provider_extension=str(provider),
        tool_extension=str(tool),
        environment={
            "PI_INTERVENTION_TOOL_URL": "http://127.0.0.1:9/tool",
            "PI_INTERVENTION_CAPABILITY": "scoped-token",
            "PI_SHOULD_NOT_LEAK": "secret",
        },
        timeout_seconds=2,
    )
    assert result.provider == "cursor"
    assert result.model == "cursor-grok-4.5"


def test_pi_rpc_inherits_outer_pi_and_skips_missing_cursor_extension(tmp_path, monkeypatch):
    agent = tmp_path / "agent"
    agent.mkdir()
    (agent / "settings.json").write_text(
        json.dumps({"defaultProvider": "openai-codex", "defaultModel": "gpt-5.6-luna"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(agent))
    monkeypatch.delenv("PI_PROVIDER", raising=False)
    monkeypatch.delenv("PI_ALLOWED_MODELS", raising=False)
    tool = tmp_path / "intervention.js"
    tool.write_text("export default () => {}", encoding="utf-8")
    executable = _fake_pi(
        tmp_path,
        f"""
assert sys.argv[sys.argv.index("--provider") + 1] == "openai-codex"
assert sys.argv[sys.argv.index("--model") + 1] == "gpt-5.6-luna"
extension_args = [sys.argv[index + 1] for index, value in enumerate(sys.argv) if value == "--extension"]
assert extension_args == [{str(tool)!r}]
""",
    )
    monkeypatch.setenv("PI_EXECUTABLE", str(executable))

    result = run_pi_rpc(
        "investigate",
        model="cursor-grok-4.5",
        tool_extension=str(tool),
        timeout_seconds=2,
    )

    assert result.provider == "openai-codex"
    assert result.model == "gpt-5.6-luna"


def test_pi_rpc_still_requires_cursor_extension_when_forced(tmp_path, monkeypatch):
    agent = tmp_path / "agent"
    agent.mkdir()
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(agent))
    tool = tmp_path / "intervention.js"
    tool.write_text("export default () => {}", encoding="utf-8")

    with pytest.raises(PiOptimizerInterventionError, match="Cursor provider extension was not found"):
        run_pi_rpc(
            "investigate",
            executable=str(tmp_path / "never-run"),
            provider="cursor",
            model="cursor-grok-4.5",
            tool_extension=str(tool),
        )


def test_pi_rpc_does_not_inherit_dashboard_secrets(tmp_path, monkeypatch):
    provider, tool = _touch_extensions(tmp_path)
    executable = tmp_path / "fake-pi"
    executable.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys

def read_prompt():
    while True:
        line = sys.stdin.readline()
        if not line:
            raise SystemExit(1)
        request = json.loads(line)
        if request.get("type") == "prompt":
            return request
        print(json.dumps({"id": request.get("id"), "type": "response", "command": request.get("type"), "success": True}), flush=True)

assert "PI_BOOTSTRAP_TOKEN" not in os.environ
if "--version" in sys.argv:
    print("0.82.1")
    raise SystemExit
request = read_prompt()
print(json.dumps({"id": request["id"], "type": "response", "command": "prompt", "success": True}), flush=True)
message = {
    "role": "assistant",
    "content": [{"type": "text", "text": "done"}],
    "provider": "cursor",
    "model": "composer-2.5",
    "usage": {},
    "stopReason": "stop",
}
print(json.dumps({"type": "message_end", "message": message}), flush=True)
print(json.dumps({"type": "agent_settled"}), flush=True)
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    monkeypatch.setenv("PI_BOOTSTRAP_TOKEN", "must-not-reach-pi")

    assert run_pi_rpc(
        "investigate",
        executable=str(executable),
        model="composer-2.5",
        provider_extension=str(provider),
        tool_extension=str(tool),
    ).text == "done"


def test_pi_rpc_drains_batched_events_before_waiting(tmp_path):
    provider, tool = _touch_extensions(tmp_path)
    executable = tmp_path / "fake-pi"
    executable.write_text(
        """#!/usr/bin/env python3
import json
import sys
import time

def read_prompt():
    while True:
        line = sys.stdin.readline()
        if not line:
            raise SystemExit(1)
        request = json.loads(line)
        if request.get("type") == "prompt":
            return request
        print(json.dumps({"id": request.get("id"), "type": "response", "command": request.get("type"), "success": True}), flush=True)

if "--version" in sys.argv:
    print("0.82.1")
    raise SystemExit

request = read_prompt()
message = {
    "role": "assistant",
    "content": [{"type": "text", "text": "done"}],
    "provider": "cursor",
    "model": "composer-2.5",
    "usage": {"input": 1, "output": 1, "cost": {"total": 0}},
    "stopReason": "stop",
}
events = [
    {"id": request["id"], "type": "response", "command": "prompt", "success": True},
    {"type": "message_end", "message": message},
    {"type": "agent_settled"},
]
sys.stdout.write("".join(json.dumps(event) + "\\n" for event in events))
sys.stdout.flush()
time.sleep(2)
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)

    result = run_pi_rpc(
        "investigate",
        executable=str(executable),
        model="composer-2.5",
        provider_extension=str(provider),
        tool_extension=str(tool),
        timeout_seconds=0.25,
    )

    assert result.text == "done"


def _write_fake_pi(tmp_path, body: str):
    executable = tmp_path / "fake-pi"
    helper = """
import json, sys
def read_prompt():
    while True:
        line = sys.stdin.readline()
        if not line:
            raise SystemExit(1)
        request = json.loads(line)
        if request.get("type") == "prompt":
            return request
        print(json.dumps({"id": request.get("id"), "type": "response", "command": request.get("type"), "success": True}), flush=True)
"""
    executable.write_text("#!/usr/bin/env python3\n" + helper + body, encoding="utf-8")
    executable.chmod(0o755)
    return executable


def test_pi_rpc_ignores_retried_error_stop_reasons(tmp_path):
    provider, tool = _touch_extensions(tmp_path)
    executable = _write_fake_pi(
        tmp_path,
        """
import json, sys
if "--version" in sys.argv:
    print("0.82.1")
    raise SystemExit
request = read_prompt()
provider = sys.argv[sys.argv.index("--provider") + 1]
model = sys.argv[sys.argv.index("--model") + 1]
print(json.dumps({"id": request["id"], "type": "response", "command": "prompt", "success": True}), flush=True)
for reason in ("error", "stop"):
    print(json.dumps({
        "type": "message_end",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": reason}],
            "provider": provider,
            "model": model,
            "usage": {"input": 1, "output": 1, "cost": {"total": 0}},
            "stopReason": reason,
        },
    }), flush=True)
print(json.dumps({"type": "agent_settled"}), flush=True)
""",
    )
    result = run_pi_rpc(
        "investigate",
        executable=str(executable),
        model="cursor-grok-4.5",
        provider_extension=str(provider),
        tool_extension=str(tool),
        timeout_seconds=2,
    )
    assert result.text == "error\nstop"


def test_pi_rpc_last_error_stop_reason_is_an_interrupt(tmp_path):
    provider, tool = _touch_extensions(tmp_path)
    executable = _write_fake_pi(
        tmp_path,
        """
import json, sys
if "--version" in sys.argv:
    print("0.82.1")
    raise SystemExit
request = read_prompt()
print(json.dumps({"id": request["id"], "type": "response", "command": "prompt", "success": True}), flush=True)
print(json.dumps({
    "type": "message_end",
    "message": {
        "role": "assistant",
        "content": [{"type": "text", "text": "failed"}],
        "provider": sys.argv[sys.argv.index("--provider") + 1],
        "model": sys.argv[sys.argv.index("--model") + 1],
        "usage": {},
        "stopReason": "error",
    },
}), flush=True)
print(json.dumps({"type": "agent_settled"}), flush=True)
""",
    )
    with pytest.raises(PiRpcTimeout, match="complete agent turn"):
        run_pi_rpc(
            "investigate",
            executable=str(executable),
            model="cursor-grok-4.5",
            provider_extension=str(provider),
            tool_extension=str(tool),
            timeout_seconds=2,
        )


def test_pi_rpc_aborts_after_successful_submit_and_ignores_aborted_stop(tmp_path):
    provider, tool = _touch_extensions(tmp_path)
    seen = tmp_path / "abort-seen.json"
    executable = _write_fake_pi(
        tmp_path,
        f"""
import json, sys
if "--version" in sys.argv:
    print("0.82.1")
    raise SystemExit
request = read_prompt()
provider = sys.argv[sys.argv.index("--provider") + 1]
model = sys.argv[sys.argv.index("--model") + 1]
print(json.dumps({{"id": request["id"], "type": "response", "command": "prompt", "success": True}}), flush=True)
print(json.dumps({{
    "type": "message_end",
    "message": {{
        "role": "assistant",
        "content": [{{"type": "text", "text": "submitting"}}],
        "provider": provider,
        "model": model,
        "usage": {{"input": 1, "output": 1, "cost": {{"total": 0}}}},
        "stopReason": "toolUse",
    }},
}}), flush=True)
print(json.dumps({{
    "type": "tool_execution_end",
    "toolName": "submit_reconciliation_brief",
    "isError": False,
}}), flush=True)
abort = json.loads(sys.stdin.readline())
open({str(seen)!r}, "w").write(json.dumps(abort))
print(json.dumps({{
    "type": "message_end",
    "message": {{
        "role": "assistant",
        "content": [{{"type": "text", "text": "aborted"}}],
        "provider": provider,
        "model": model,
        "usage": {{}},
        "stopReason": "aborted",
    }},
}}), flush=True)
print(json.dumps({{"type": "agent_settled"}}), flush=True)
""",
    )
    result = run_pi_rpc(
        "investigate",
        executable=str(executable),
        model="cursor-grok-4.5",
        provider_extension=str(provider),
        tool_extension=str(tool),
        timeout_seconds=2,
    )
    assert result.text == "submitting\naborted"
    assert json.loads(seen.read_text())["type"] == "abort"


def test_pi_rpc_cancels_extension_ui_requests(tmp_path):
    provider, tool = _touch_extensions(tmp_path)
    seen = tmp_path / "ui-reply.json"
    executable = _write_fake_pi(
        tmp_path,
        f"""
import json, sys
if "--version" in sys.argv:
    print("0.82.1")
    raise SystemExit
request = read_prompt()
print(json.dumps({{"id": request["id"], "type": "response", "command": "prompt", "success": True}}), flush=True)
print(json.dumps({{
    "type": "extension_ui_request",
    "id": "ui-1",
    "method": "confirm",
}}), flush=True)
reply = json.loads(sys.stdin.readline())
open({str(seen)!r}, "w").write(json.dumps(reply))
print(json.dumps({{
    "type": "message_end",
    "message": {{
        "role": "assistant",
        "content": [{{"type": "text", "text": "cancelled-ui"}}],
        "provider": sys.argv[sys.argv.index("--provider") + 1],
        "model": sys.argv[sys.argv.index("--model") + 1],
        "usage": {{}},
        "stopReason": "stop",
    }},
}}), flush=True)
print(json.dumps({{"type": "agent_settled"}}), flush=True)
""",
    )
    result = run_pi_rpc(
        "investigate",
        executable=str(executable),
        model="cursor-grok-4.5",
        provider_extension=str(provider),
        tool_extension=str(tool),
        timeout_seconds=2,
    )
    assert result.text == "cancelled-ui"
    reply = json.loads(seen.read_text())
    assert reply["type"] == "extension_ui_response"
    assert reply["id"] == "ui-1"
    assert reply["cancelled"] is True


def test_pi_rpc_timeout_sends_abort_before_raising(tmp_path):
    provider, tool = _touch_extensions(tmp_path)
    seen = tmp_path / "timeout-abort.json"
    executable = _write_fake_pi(
        tmp_path,
        f"""
import json, sys, time
if "--version" in sys.argv:
    print("0.82.1")
    raise SystemExit
request = read_prompt()
print(json.dumps({{"id": request["id"], "type": "response", "command": "prompt", "success": True}}), flush=True)
print(json.dumps({{
    "type": "message_end",
    "message": {{
        "role": "assistant",
        "content": [{{"type": "text", "text": "working"}}],
        "provider": sys.argv[sys.argv.index("--provider") + 1],
        "model": sys.argv[sys.argv.index("--model") + 1],
        "usage": {{}},
        "stopReason": "toolUse",
    }},
}}), flush=True)
abort = json.loads(sys.stdin.readline())
open({str(seen)!r}, "w").write(json.dumps(abort))
time.sleep(5)
""",
    )
    with pytest.raises(PiRpcTimeout, match="timed out"):
        run_pi_rpc(
            "investigate",
            executable=str(executable),
            model="cursor-grok-4.5",
            provider_extension=str(provider),
            tool_extension=str(tool),
            timeout_seconds=0.2,
        )
    assert json.loads(seen.read_text())["type"] == "abort"

def test_pi_rpc_disables_auto_compaction_before_prompt(tmp_path):
    provider, tool = _touch_extensions(tmp_path)
    seen = tmp_path / "first-command.json"
    executable = _write_fake_pi(
        tmp_path,
        f"""
if "--version" in sys.argv:
    print("0.82.1")
    raise SystemExit
first = json.loads(sys.stdin.readline())
open({str(seen)!r}, "w").write(json.dumps(first))
print(json.dumps({{"id": first.get("id"), "type": "response", "command": first.get("type"), "success": True}}), flush=True)
request = read_prompt()
print(json.dumps({{"id": request["id"], "type": "response", "command": "prompt", "success": True}}), flush=True)
print(json.dumps({{
    "type": "message_end",
    "message": {{
        "role": "assistant",
        "content": [{{"type": "text", "text": "ok"}}],
        "provider": sys.argv[sys.argv.index("--provider") + 1],
        "model": sys.argv[sys.argv.index("--model") + 1],
        "usage": {{}},
        "stopReason": "stop",
    }},
}}), flush=True)
print(json.dumps({{"type": "agent_settled"}}), flush=True)
""",
    )
    run_pi_rpc(
        "investigate",
        executable=str(executable),
        model="cursor-grok-4.5",
        provider_extension=str(provider),
        tool_extension=str(tool),
        timeout_seconds=2,
    )
    first = json.loads(seen.read_text())
    assert first["type"] == "set_auto_compaction"
    assert first["enabled"] is False
