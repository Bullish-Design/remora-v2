# Plan

NO SUBAGENTS. Do all work directly.

## Objective
Stabilize proposal accept flow semantics so demos/tests can prove `rewrite_accepted` followed by `content_changed` deterministically, while preserving reject flow behavior.

## Ordered Steps
1. Document current failure mode and event ordering root cause.
2. Implement event-order fix in `api_proposal_accept`.
3. Add/adjust tests for strict ordering and correlation-scoped validation.
4. Validate accept and reject flows with real API interactions.
5. Record outcomes and any residual risks.

## Acceptance Criteria
- Accept flow emits `rewrite_accepted` before `content_changed` for accepted files.
- Disk mutation still happens before acceptance response is returned.
- Reject flow remains unchanged and passing.
- Realistic noisy-event validation remains stable.

NO SUBAGENTS. Do all work directly.
