# Plan - 23-demo-analysis-review

**ABSOLUTE RULE: NO SUBAGENTS (Task tool). Do ALL work directly.**

## Goal
Produce a thorough demo-readiness analysis of the current `remora-v2` codebase, grounded in current code and tests, and provide a practical step-by-step demo script for the library as it exists now.

## Steps
1. Read `.scratch/CRITICAL_RULES.md` and `.scratch/projects/22-production-readiness-review/DEMO_PLAN.md`.
2. Inspect current runtime architecture and surfaces (`CLI`, discovery/reconciler, actor/kernel/tools, events/store, web UI, LSP, bundles, contrib docs).
3. Run validation commands (dependency sync and test suite) to confirm current status.
4. Write `DEMO_ANALYSIS.md` with findings, strengths, risks, and concrete actions to reach/ensure a demo-ready state.
5. Write `DEMO_SCRIPT.md` with a realistic walkthrough that fits current implementation.
6. Update project tracking docs.

## Acceptance
- New project directory exists with standard tracking files.
- `DEMO_ANALYSIS.md` exists with evidence-backed analysis and recommendations.
- `DEMO_SCRIPT.md` exists with actionable, step-by-step demo flow.
- Guidance reflects the current codebase state as verified in this session.

**REMINDER: NO SUBAGENTS. Do ALL work directly.**
