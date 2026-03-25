# Context

- Active project: `52-test-suite-real-world-coverage`.
- Source guide: `.scratch/projects/52-test-suite-real-world-coverage/TEST_SUITE_IMPROVEMENT_GUIDE.md`.
- Current state: Step 10 complete (aggregate real-LLM suite passing).
- Key notes:
  - `review_diff` now reads node `text` for actual diffing.
  - `suggest_tests` now reads node `text` for real source context.
  - `query_agents` now supports filtered argument shapes while remaining no-arg compatible.
  - Grail tool execution now applies optional `Input(..., default=...)` values before running scripts.
  - Reactive acceptance fixture now includes deterministic directory-agent `emit_mode_token` wiring.
- Next action: finalize commit/push for Step 10.
