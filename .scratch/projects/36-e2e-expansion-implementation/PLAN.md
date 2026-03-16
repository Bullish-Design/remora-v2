# 36 E2E Expansion Implementation Plan

## ABSOLUTE RULE
NO SUBAGENTS. All work in this project is performed directly in this session.

## Scope
Implement all items from `.scratch/projects/35-test-suite-e2e-real-world-analysis/E2E_REAL_WORLD_ANALYSIS_REPORT.md` recommended E2E expansion plan, committing and pushing after each item.

## Ordered Steps
1. Add acceptance test: live web + dispatcher + actor pool + real vLLM.
2. Add acceptance test: proposal flow with real model-generated rewrite and accept path.
3. Add acceptance test: reactive trigger flow with live runtime + real vLLM.
4. Add process-level LSP smoke acceptance test with event assertion.
5. Add operational suggestions (markers and deterministic test guidance), validate suite slices.
6. Finalize docs/tracking updates.

## Acceptance Criteria
- Each plan item is implemented and validated with targeted test commands.
- A commit and push is completed after each item.
- Markers `acceptance` and `real_llm` are registered and used.
- New acceptance tests use strict timeouts and deterministic identifiers.

## ABSOLUTE RULE REMINDER
NO SUBAGENTS. Continue directly until all listed items are done.
