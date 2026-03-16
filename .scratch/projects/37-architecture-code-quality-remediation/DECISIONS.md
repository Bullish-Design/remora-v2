# Decisions

- `2026-03-16`: Implemented item `4.1` using composition inside `core/actor.py` first (not cross-file extraction yet) to minimize test churn while reducing `Actor` responsibilities immediately.
- `2026-03-16`: Preserved legacy private method names and state attributes via wrappers/properties to maintain existing test and monkeypatch compatibility while shifting logic ownership to extracted components.
- `2026-03-16`: Implemented item `4.2` as a dedicated `RemoraLifecycle` class in `core/lifecycle.py` to isolate startup/run/shutdown ownership from CLI wiring while preserving existing runtime behavior and task naming.
- `2026-03-16`: Added `serialize_enum` at the shared type boundary and replaced ad-hoc `hasattr(..., "value")` checks across production modules to enforce a single enum serialization mechanism.
