# Context

- Project scaffold created and checklist initialized.
- Completed item `4.1` by refactoring `src/remora/core/actor.py` into focused components:
  - `TriggerPolicy` for cooldown/depth enforcement and cleanup
  - `PromptBuilder` for system/user prompt assembly
  - `AgentTurnExecutor` for turn orchestration and kernel execution
  - `Actor` now centered on inbox/outbox/lifecycle orchestration with compatibility wrappers
- Completed item `4.2` by extracting runtime `_start()` orchestration into `src/remora/core/lifecycle.py` as `RemoraLifecycle` with explicit `start()`, `run()`, and `shutdown()` phases; `src/remora/__main__.py` now delegates to this lifecycle manager.
- Verification run for 4.1:
  - `devenv shell -- uv sync --extra dev`
  - `devenv shell -- pytest tests/unit/test_actor.py tests/unit/test_runner.py -q`
  - `devenv shell -- pytest tests/unit/test_externals.py::test_externals_emit_uses_outbox_when_provided -q`
- Verification run for 4.2:
  - `devenv shell -- pytest tests/unit/test_cli.py tests/integration/test_startup_shutdown.py -q`
- Next action: commit+push item 4.2, then implement item `4.3` enum serialization boundary cleanup.
