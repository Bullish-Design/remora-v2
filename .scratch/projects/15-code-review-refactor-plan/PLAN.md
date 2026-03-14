# Plan

NO SUBAGENTS: All work for this project is executed directly without Task/subagent delegation.

## Goal
Create and maintain an actionable remediation plan covering all fixes/improvements/recommendations from the prior code review, then use it to drive implementation.

## Ordered Steps
1. Extract all actionable recommendations from `.scratch/projects/14-code-review-and-demo/CODE_REVIEW.md`.
2. Normalize items into a unique backlog (`R1-R15`) with owner modules and acceptance tests.
3. Split work into dependency-aware phases (critical, high, medium, low).
4. Add demo-readiness track (`D1-D4`) with explicit dependency on LSP/core fixes.
5. Track execution state in `PROGRESS.md` and decision/risk changes in `DECISIONS.md` and `ISSUES.md`.

## Acceptance Criteria
- Every recommendation from section 8 of the code review is represented in `REFACTOR_PLAN.md`.
- Demo-focused recommendations from section 6 are represented in a separate track.
- Each backlog item has target files/components and a verification strategy.
- Phase ordering enables safe, incremental delivery.

NO SUBAGENTS: This plan starts and ends with direct execution only; no subagent usage is allowed.
