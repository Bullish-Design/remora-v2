# Plan

NO SUBAGENTS. Do all work directly.

## Objective
Close all known real-world and partial test coverage gaps identified in the codebase/test-suite audit by adding deterministic unit/integration/acceptance tests and required fixture/runtime hooks, with mandatory real-vLLM execution coverage for every default bundle `.pym` script.

## Primary Inputs

- Coverage gap review findings from the latest codebase audit (real-LLM gaps, behavior-only parse checks, mocked-only backend paths, frontend automation gaps, LSP process gap).
- Existing Project 52 real-LLM suite and acceptance harnesses.

## Ordered Steps

1. Define implementation scope and acceptance matrix in `REAL_WORLD_COVERAGE_IMPLEMENTATION_GUIDE.md`.
2. Add production `code-agent` real-LLM coverage for `rewrite_self` and `scaffold`.
3. Add behavioral tests for currently parse-only system/companion tools.
4. Add real-LLM coverage for `ask_human` and embeddy-gated `semantic_search`/`categorize`.
5. Add real backend integration checks for search service wiring.
6. Add browser automation tests for web graph interactions.
7. Expand process-level LSP acceptance coverage beyond open/save.
8. Execute full verification matrix and stabilize flaky tests.

## Acceptance Criteria

- Every uncovered/high-risk gap has at least one behavioral test.
- Real-LLM coverage includes all default production bundle `.pym` tools.
- Frontend graph interactions have automated regression tests.
- LSP process-level tests cover hover/code actions/command-trigger flows.
- A reproducible command matrix exists for local and CI runs.

NO SUBAGENTS. Do all work directly.
