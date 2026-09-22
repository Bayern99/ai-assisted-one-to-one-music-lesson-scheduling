import { Type } from "typebox";

const toolUrl = process.env.PI_RECONCILIATION_TOOL_URL;
const capability = process.env.PI_RECONCILIATION_CAPABILITY;

async function callTool(action, params, signal) {
  if (!toolUrl || !capability) throw new Error("Pi reconciliation capability is unavailable.");
  const response = await fetch(toolUrl, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-PI-Agent-Capability": capability,
    },
    body: JSON.stringify({ action, params }),
    signal,
  });
  const payload = await response.json();
  if (!response.ok || payload.error) {
    throw new Error(payload.error?.message || "Pi reconciliation tool request failed.");
  }
  return payload.data;
}

const targetSchema = Type.Object({
  room: Type.String({ minLength: 1 }),
  day: Type.Optional(Type.Integer({ minimum: 0, maximum: 6 })),
  start: Type.Optional(Type.String({ minLength: 1 })),
  end: Type.Optional(Type.String({ minLength: 1 })),
});

const changeSchema = Type.Object({
  subject_alias: Type.String({ minLength: 1 }),
  target: Type.Optional(targetSchema),
  withdraw: Type.Optional(Type.Boolean()),
});

export default function registerPiReconciliation(pi) {
  pi.registerTool({
    name: "inspect_reconciliation",
    label: "Inspect linked reconciliation scope",
    description: "Inspect the selected privacy-minimised linked schedule scope once.",
    parameters: Type.Object({
      focus_aliases: Type.Optional(Type.Array(Type.String({ minLength: 1 }), { maxItems: 16 })),
    }),
    async execute(_toolCallId, params, signal) {
      const data = await callTool("inspect", params || {}, signal);
      return { content: [{ type: "text", text: JSON.stringify(data) }], details: data };
    },
  });

  pi.registerTool({
    name: "simulate_reconciliation_package",
    label: "Simulate reconciliation package",
    description: "Sandbox-test a complete linked adjustment package through Python validation.",
    parameters: Type.Object({
      changes: Type.Array(changeSchema, { minItems: 1, maxItems: 16 }),
    }),
    async execute(_toolCallId, params, signal) {
      const data = await callTool("simulate", params, signal);
      return { content: [{ type: "text", text: JSON.stringify(data) }], details: data };
    },
  });

  pi.registerTool({
    name: "submit_reconciliation_brief",
    label: "Submit reconciliation brief",
    description: "Submit one evidence-backed brief for human pursue and apply decisions.",
    parameters: Type.Object({
      termination: Type.Union([
        Type.Literal("recommendation_ready"),
        Type.Literal("no_feasible_package_found"),
        Type.Literal("budget_exhausted"),
      ]),
      primary_simulation_id: Type.Optional(Type.String({ minLength: 1 })),
      fallback_simulation_id: Type.Optional(Type.String({ minLength: 1 })),
      title: Type.String({ minLength: 1, maxLength: 80 }),
      focus_question: Type.Optional(Type.String({ minLength: 1, maxLength: 120 })),
      rationale: Type.String({ minLength: 1, maxLength: 800 }),
      trade_offs: Type.Array(Type.String({ maxLength: 200 }), { maxItems: 6 }),
      limitations: Type.Array(Type.String({ maxLength: 200 }), { maxItems: 6 }),
      agent_note: Type.Optional(Type.String({ maxLength: 200 })),
      unknowns: Type.Optional(Type.Array(
        Type.Object({
          subject: Type.String({ minLength: 1, maxLength: 60 }),
          note: Type.String({ maxLength: 200 }),
        }),
        { maxItems: 5 },
      )),
      pending_decisions: Type.Optional(Type.Array(
        Type.Object({
          kind: Type.Union([
            Type.Literal("business_tradeoff"),
            Type.Literal("missing_fact"),
            Type.Literal("exception_authorization"),
            Type.Literal("other"),
          ]),
          detail: Type.String({ maxLength: 400 }),
          teacher_alias: Type.Optional(Type.String({ minLength: 1 })),
        }),
        { maxItems: 8 },
      )),
      remaining_issues: Type.Optional(Type.Array(
        Type.Object({
          subject_alias: Type.String({ minLength: 1 }),
          reason: Type.String({ maxLength: 300 }),
        }),
        { maxItems: 24 },
      )),
    }),
    async execute(_toolCallId, params, signal) {
      const data = await callTool("submit", params, signal);
      return {
        content: [{ type: "text", text: "Reconciliation brief submitted for human review." }],
        details: data,
        terminate: true,
      };
    },
  });
}
