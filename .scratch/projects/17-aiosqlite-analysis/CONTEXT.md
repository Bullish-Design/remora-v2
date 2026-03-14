# Context

## Status
Project 17 is complete. The `AIOSQLITE_REFACTORING_GUIDE.md` has been fully implemented across phases A-G, and the codebase now uses `aiosqlite` directly with no `AsyncDB` wrapper or compatibility shims.

## Focus
- Final implementation highlights:
  - LSP `didChange` now updates in-memory `DocumentStore` only (no disk writes).
  - Added `aiosqlite` dependency and replaced `core/db.py` with `open_database()`.
  - Migrated graph/events/subscriptions stores to native `aiosqlite.Connection` calls.
  - Runtime startup/shutdown now opens and closes DB asynchronously.
  - Entire test suite migrated to `open_database()` and async DB closure.
- Verification:
  - `devenv shell -- pytest --tb=short -q` => `208 passed, 4 skipped`
  - `rg -n "AsyncDB|from_path|\\.connection|\\.lock" src tests` => no hits
  - `src/remora/core/db.py` now 22 lines and contains only connection factory logic.

## Next step
No pending tasks in this project.
