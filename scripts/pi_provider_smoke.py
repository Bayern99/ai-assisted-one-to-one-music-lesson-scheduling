#!/usr/bin/env python3
"""Run an opt-in real Cursor/Pi RPC smoke against an existing tool capability.

The Dashboard must already expose the internal plan-tool callback and provide a
fresh capability token. This script never creates a schedule mutation; the
plan extension may only inspect/simulate/submit through the supplied token.
"""

from __future__ import annotations

import argparse
import json
import os

from modules.api.services.pi_optimizer_intervention import run_pi_rpc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool-url", required=True)
    parser.add_argument("--capability", required=True)
    parser.add_argument("--provider", default=None)
    parser.add_argument("--model", default="cursor-grok-4.5")
    parser.add_argument("--executable", default=None)
    args = parser.parse_args()
    if os.environ.get("PI_REAL_PROVIDER_SMOKE") != "1":
        parser.error("Set PI_REAL_PROVIDER_SMOKE=1 to enable a real provider call.")
    result = run_pi_rpc(
        "Inspect the supplied bounded scope once. Do not apply anything. Return only the tool-call audit summary.",
        executable=args.executable,
        model=args.model,
        provider=args.provider,
        tool_names=("inspect_intervention_scope",),
        environment={
            "PI_PLAN_INTERVENTION_TOOL_URL": args.tool_url,
            "PI_PLAN_INTERVENTION_CAPABILITY": args.capability,
        },
    )
    print(json.dumps({
        "provider": result.provider,
        "model": result.model,
        "pi_version": result.pi_version,
        "latency_ms": result.latency_ms,
        "usage": result.usage,
        "text": result.text,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
