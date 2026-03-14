# Context

## Status
Project 17 is a lightweight investigation into whether the Remora runtime should be rewritten to lean on `aiosqlite` instead of the current `AsyncDB` helper.

## Focus
- Map where `AsyncDB` is used (graph/event/agent/subscription services) and consider how `aiosqlite` would integrate.
- Evaluate architectural cleanliness, concurrency handling, and dependency implications when pursuing an `aiosqlite` refactor.

## Next step
Document the analysis (pros/cons/opportunities) in `AIOSQLITE_ANALYSIS.md`, then decide whether to proceed with a refactor.
