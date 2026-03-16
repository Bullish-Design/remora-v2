# Decisions

- `2026-03-16`: Implemented item `4.1` using composition inside `core/actor.py` first (not cross-file extraction yet) to minimize test churn while reducing `Actor` responsibilities immediately.
- `2026-03-16`: Preserved legacy private method names and state attributes via wrappers/properties to maintain existing test and monkeypatch compatibility while shifting logic ownership to extracted components.
- `2026-03-16`: Implemented item `4.2` as a dedicated `RemoraLifecycle` class in `core/lifecycle.py` to isolate startup/run/shutdown ownership from CLI wiring while preserving existing runtime behavior and task naming.
- `2026-03-16`: Added `serialize_enum` at the shared type boundary and replaced ad-hoc `hasattr(..., "value")` checks across production modules to enforce a single enum serialization mechanism.
- `2026-03-16`: Moved `RecordingOutbox` into `tests/doubles.py` to keep production actor module free of test-only doubles while retaining the same interface for test call sites.
- `2026-03-16`: Replaced dynamic `server._remora_handlers` monkey patch with typed `RemoraLSPHandlers` attached to a dedicated `RemoraLanguageServer` subclass to formalize testing abstraction and reduce hidden attributes.
- `2026-03-16`: Treated item `5.1` as mandatory hygiene even after architecture work by running Ruff autofix immediately, then re-running lint and a focused regression test before moving on.
- `2026-03-16`: Since Starlette lifespan migration was already present, item `5.2` was completed by strengthening correctness signals: explicit lifespan return typing and a dedicated test asserting shutdown-event behavior via lifespan context.
