# AIOSQLITE ANALYSIS

## Current state
- `AsyncDB` ([src/remora/core/db.py](/home/andrew/Documents/Projects/remora-v2/src/remora/core/db.py)) wraps a `sqlite3.Connection`, uses an `asyncio.Lock`, and runs every SQL call via `asyncio.to_thread` so the synchronous driver never shares the thread. The helper also exposes helper methods like `execute_script`, `fetch_all`, and `insert`, all of which manually commit the connection.
- Consumers in the graph, event store, and services layers rely on this wrapper and expect a long-lived, single-connection instance for the entire runtime. The pattern is functional but involves repeated boilerplate, custom locking, and thread-hopping code paths.

## Pros of using `aiosqlite`
- **Native async API**: `aiosqlite` already exposes `await conn.execute(...)`, `await cursor.fetchall()`, and context-managed transactions, which eliminates the custom `asyncio.Lock` + `asyncio.to_thread` dance. It would keep the event loop in charge of scheduling without manual thread trampoline code.
- **Cleaner semantics**: A new `AsyncDB` variant built on `aiosqlite` can be closer to the surface API we already have (same method names) while delegating serialization and buffering to the library. That makes the wrapper leaner and easier to reason about.
- **Better opportunity for batching**: `aiosqlite` supports `connection.executemany` and `connection.executemany` in async contexts, so batching patterns like `execute_many` can be implemented without spinning yet another thread or reimplementing commit logic.
- **Community-tested behavior**: `aiosqlite` handles connection lifecycle details (including WAL, busy timeouts, row factories) in a way that is idiomatic for asynchronous applications, so we can reuse its best practices rather than invent them.

## Cons / risks
- **Additional dependency**: Ship a new dependency (`aiosqlite`) and ensure it stays in sync with the rest of the stack (though it is a very small, established package).
- **API shift**: The current `AsyncDB` constructor is synchronous (`from_path` returns immediately). Moving to `aiosqlite` would likely require an async factory (e.g., `await AsyncDB.create(path)`). This means consumers must await the DB creation, which is not a huge issue but does change startup sequencing.
- **Performance parity**: Under the hood, `aiosqlite` still runs work on a worker thread, so throughput/latency is similar to the existing `asyncio.to_thread` implementation. The improvement is mainly structural clarity rather than raw performance.

## Opportunities
1. **Centralize connection creation**: With `aiosqlite`, we can have an async factory that sets the PRAGMAs (`WAL`, `busy_timeout`) immediately, so every consumer gets an identical setup without duplicating the `connect` utility.
2. **Drop manual locking**: Because `aiosqlite` serializes access per connection, we can remove the explicit `lock` property and the `asyncio.Lock`, reducing the conceptual surface area of `AsyncDB`.
3. **Improve testing ergonomics**: An `aiosqlite`-backed DB can be created within an async fixture using temporary files and `await AsyncDB.create(tmp_path)` without requiring thread synchronization plumbing, which makes the test helper suite simpler.
4. **Expose transactions more naturally**: The current helper does not expose context-managed transactions; `aiosqlite` makes it easy to support `async with db.transaction()` or `async with db.connection()` for multi-statement operations, which can be a building block for future refactors (e.g., migrating to `sqlmodel` or similar).

## Recommendation
Refactor the database layer to lean on `aiosqlite`. Keep the `AsyncDB` API surface but reimplement it with an async factory that opens `aiosqlite.Connection`, sets the same pragmas, and exposes the same helper methods. With that refactor we remove the manual locking logic, reduce the number of `asyncio.to_thread` wrappers, and make the codebase feel more explicitly asynchronous—aligning with the goal of a clean, elegant architecture. Since backwards compatibility is not a concern, the only notable work is updating the startup path to `await AsyncDB.create(...)` and ensuring dependent components await the ready connection.
