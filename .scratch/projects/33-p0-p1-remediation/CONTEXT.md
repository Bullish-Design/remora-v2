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
- Item 8 complete: `NodeStore.batch()` added and integrated into reconciler write-heavy paths.
- Added test proving grouped node writes issue a single commit.
- Item 9 complete: subscription registry cache now updates incrementally on register/unregister operations.
- Added tests ensuring cache updates without forcing full rebuild.
- Item 10 complete: action limits added for search_content (max matches), broadcast (max targets), and send_message (per-agent rate limit).
- Added tests for each limit behavior.
- Item 11 complete: Ruff issues in `src/remora` resolved (auto-fix + manual long-line cleanups).
- Verified with `devenv shell -- ruff check src/remora` passing clean.
- Item 12 complete: web server startup/shutdown hooks migrated from `on_shutdown` to `lifespan`.
- Verified by running full `tests/unit/test_web_server.py` (all passing).
- Item 13 complete: production `assert` usage replaced with explicit runtime checks in startup path.
- Verified lint state remains clean with `devenv shell -- ruff check src/remora`.

Next:
- All P0 and P1 recommendation items are complete, including the extra P1 performance items from section 3.
