# AI-Assisted One-to-One Music Lesson Scheduling

Research demonstration of one-to-one music-lesson scheduling. Jury and assessment are out of scope. Python is the sole scheduling/validation authority; an investigator may propose but cannot write the ledger.

## Testing

- NEVER write unit tests after you write code.
- Highly prefer E2E tests as the sole testing mechanism. Use them to verify complex features work. At the end of E2E tests, produce a verifiable and repeatable artifact.
- If you must test a system in isolation, FIRST write all the ways it could fail, THEN write the code.
- Do not run the full E2E suite during development. Run it only when the work is finished.

## Ground truth

- Inspect the current repository, configuration, tests, and Git state before acting. Use [README.md](README.md) for the product overview.
- Preserve pre-existing worktree changes and stay within the user's requested scope. Commit, push, merge, and release only when explicitly requested.
- Python is the sole authority for scheduling and validation rules; React collects intent and presents server results.
- For Resolve / reconciliation, the investigator may propose a whole-day package; Python validates candidates; the human authorizes; Finalize is the only write to committed occupancy.
- Keep cross-layer contracts synchronized: regenerate TypeScript types after API schema changes and test the API/frontend contract; scheduler mutations must preserve canonical identity, `assigned XOR unresolved`, workspace-version freshness, atomic persistence, and complete rollback. Current occupancy is L0 PI plus explicit locks (committed bookings / lectures), not a stale L1 snapshot. Stage copies L0 PI into L1 `validation_authority` and must not write `bookings.json` or set `round_committed`; Finalize remains the only L2 commit.
- Use Python 3.9+ at the repository root and npm inside `frontend/`. Prefer the standard library, platform, and installed dependencies; add a dependency only when they cannot meet the requirement.
- Keep tests and development writes isolated from real application data.

## First principles

For non-trivial design, diagnosis, implementation, or review:

1. State the observable failure or required outcome and the invariants that must remain true.
2. Trace the real path from input through persistence to output, including callers of the shared contract being changed.
3. Separate observed facts, derived conclusions, and unverified assumptions.
4. Fix the root cause at the narrowest shared authority, reusing an existing primitive before adding code or structure.

This phase is complete when repository evidence explains both the failure and why the proposed change resolves it.

## Adversarial review

Before declaring work complete, try to break the relevant paths with boundary, missing, duplicate, oversized, stale, concurrent, interrupted, and semantically invalid states. Check rollback, recovery, cross-layer authority drift, privacy, accessibility, performance, and time/date anomalies where applicable.

For broad or release-critical changes, use independent reviewers or subagents for separate risk surfaces when available. Validate every finding against repository evidence before accepting it.

Every material risk must be fixed, disproved with evidence, or reported explicitly as remaining scope.

## Verification

Run the smallest direct regression check while working. Before release, run `python3 scripts/verify_release.py`; report what actually ran and distinguish verified behaviour from inference.
