# Progress

## Items
- [x] 4.1 Extract Actor responsibilities
- [x] 4.2 Extract `_start()` into lifecycle manager
- [x] 4.3 Eliminate `hasattr(x, "value")` pattern
- [x] 4.4 Move `RecordingOutbox` to tests
- [x] 4.5 Proper abstraction for LSP handlers
- [x] 5.1 Fix Ruff violations
- [x] 5.2 Starlette lifespan migration
- [ ] 5.3 Replace production `assert`
- [ ] 5.4 Add type checking config to CI/project config
- [ ] 5.5 Standardize enum handling
- [ ] 5.6 Health check imports `__version__`

## Commit Log
- [x] `2024f2d` 4.1 Extract Actor responsibilities into `TriggerPolicy`, `PromptBuilder`, and `AgentTurnExecutor`
- [x] `e7f8705` 4.2 Extract startup/shutdown orchestration into `RemoraLifecycle`
- [x] `9100da5` 4.3 Add `serialize_enum` boundary helper and remove `hasattr(..., "value")` usage
- [x] `8fee526` 4.4 Move `RecordingOutbox` from production module into `tests/doubles.py`
- [x] `d34fcc9` 4.5 Replace `_remora_handlers` monkey patch with `RemoraLSPHandlers` abstraction
- [x] `d151bcb` 5.1 Run Ruff autofix and clear remaining lint violations
- [pending push] 5.2 Enforce lifespan API via typed context + regression test
