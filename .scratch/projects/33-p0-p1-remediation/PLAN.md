# 33 P0/P1 Remediation Plan

## ABSOLUTE RULE
NO SUBAGENTS. All work in this project is performed directly in this session.

## Scope
Implement every P0 and P1 item from `.scratch/projects/29-ruthless-code-review/RECOMMENDATIONS.md`, one item at a time, with commit+push after each completed item.

## Ordered Steps
1. Path traversal fix in `web/server.py` (P0)
2. CSRF origin validation middleware (P0)
3. Actor `_depths` TTL cleanup (P0)
4. FileReconciler `_file_locks` eviction (P0)
5. Event bus dispatch fix (P0)
6. Atomic `transition_status` update (P0)
7. `graph_set_status` via transition validation (P1 in section 2, included in requested scope)
8. Batch SQLite commits (P1)
9. Subscription cache incremental update (P1)
10. Agent action limits (P1)
11. Ruff violations (P1)
12. Starlette deprecation fix (P1)
13. Replace production asserts (P1)

## Acceptance Criteria
- Each item has code + tests where applicable.
- Each item is committed separately with clear commit message.
- Each item is pushed before proceeding to next item.
- Project tracking files are kept current throughout.

## ABSOLUTE RULE REMINDER
NO SUBAGENTS. Continue directly until all listed items are done.
