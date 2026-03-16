# 34 Testing Improvements Plan

## ABSOLUTE RULE
NO SUBAGENTS. All work in this project is performed directly in this session.

## Scope
Implement all testing improvements from section 6 of `.scratch/projects/29-ruthless-code-review/RECOMMENDATIONS.md`.

## Ordered Steps
1. Stabilize baseline by fixing reconciler test monkeypatch signature mismatch.
2. Add actor pool concurrency test under concurrent load.
3. Add property-based tests for subscription matching.
4. Add startup/shutdown integration test for `_start(..., run_seconds=2.0)`.
5. Add reconciler load test for 1000 files × 10 nodes.
6. Ensure 5 skipped tests have explicit skip reasons on annotations.
7. Run targeted and suite-level validations.

## Acceptance Criteria
- New tests are deterministic and pass in current environment.
- Skip annotations for real-LLM tests clearly include reasons.
- Baseline regressions introduced by previous changes are fixed.

## ABSOLUTE RULE REMINDER
NO SUBAGENTS. Continue directly until all listed items are done.
