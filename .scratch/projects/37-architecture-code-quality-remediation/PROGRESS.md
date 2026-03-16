# Progress

## Items
- [x] 4.1 Extract Actor responsibilities
- [x] 4.2 Extract `_start()` into lifecycle manager
- [x] 4.3 Eliminate `hasattr(x, "value")` pattern
- [x] 4.4 Move `RecordingOutbox` to tests
- [x] 4.5 Proper abstraction for LSP handlers
- [x] 5.1 Fix Ruff violations
- [x] 5.2 Starlette lifespan migration
- [x] 5.3 Replace production `assert`
- [x] 5.4 Add type checking config to CI/project config
- [x] 5.5 Standardize enum handling
- [x] 5.6 Health check imports `__version__`

## Commit Log
- [x] `2024f2d` 4.1 Extract Actor responsibilities into `TriggerPolicy`, `PromptBuilder`, and `AgentTurnExecutor`
- [x] `e7f8705` 4.2 Extract startup/shutdown orchestration into `RemoraLifecycle`
- [x] `9100da5` 4.3 Add `serialize_enum` boundary helper and remove `hasattr(..., "value")` usage
- [x] `8fee526` 4.4 Move `RecordingOutbox` from production module into `tests/doubles.py`
- [x] `d34fcc9` 4.5 Replace `_remora_handlers` monkey patch with `RemoraLSPHandlers` abstraction
- [x] `d151bcb` 5.1 Run Ruff autofix and clear remaining lint violations
- [x] `667e15a` 5.2 Enforce lifespan API via typed context + regression test
- [x] `6ca539e` 5.3 Add regression guard preventing production `assert` statements
- [x] `98ed9d5` 5.4 Add Pyright config and dev dependency in project config
- [x] `6c255e2` 5.5 Standardize enum usage and boundary serialization paths
- [x] `089ee5d` 5.6 Use package `__version__` in web health endpoint response
