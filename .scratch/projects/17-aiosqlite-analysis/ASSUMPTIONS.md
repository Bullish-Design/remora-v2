# Assumptions

- The current `AsyncDB` design aims for safe async access over `sqlite3` but may be refactored.
- Backwards compatibility is not required; we can break APIs if it yields a cleaner architecture.
- Adding `aiosqlite` as a dependency is acceptable if it materially improves clarity and maintainability.
