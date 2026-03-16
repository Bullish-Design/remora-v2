# Context

Project created to implement P0/P1 recommendations from project 29 doc.

Current status:
- Item 1 complete: path traversal prevention in proposal diff/accept disk path resolution.
- Added root-confinement validation and 400 responses for invalid proposal workspace paths.
- Added unit tests for traversal attempts in both diff and accept endpoints.
- Item 2 complete: CSRF Origin validation middleware for mutating web API methods.
- Added unit tests for rejected non-local origin and allowed localhost origin.
- Item 3 complete: Actor now tracks depth timestamps with periodic TTL cleanup.
- Added tests for stale depth eviction and timestamp cleanup on reset.
- Item 4 complete: FileReconciler now tracks file locks by reconcile generation and evicts stale unlocked entries.
- Added test coverage proving unused file locks are removed on subsequent cycles.
- Item 5 complete: EventBus emit now dispatches to exact type handlers plus base `Event` handlers only.
- Added regression test ensuring intermediate inheritance handlers are not invoked.
- Item 6 complete: `NodeStore.transition_status` now uses atomic conditional UPDATE based on allowed source states.
- Added concurrency-oriented test for competing transitions from `running`.
- Item 7 complete: `TurnContext.graph_set_status` now validates `NodeStatus` and routes through transition rules.
- Added tests for invalid status values and invalid transitions.

Next:
- Implement item 8: Batch SQLite commits.
- Keep one-item-per-commit and push after each item.
