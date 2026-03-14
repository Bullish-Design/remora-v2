# Plan

1. Inventory `AsyncDB` usage and locking semantics across the core graph/event/service layers.
2. Compare the current pattern (sqlite3 + `asyncio.to_thread`) with `aiosqlite` APIs for clarity, concurrency, and extension points.
3. Capture the trade-offs, opportunities, and recommended next step in `AIOSQLITE_ANALYSIS.md`.
