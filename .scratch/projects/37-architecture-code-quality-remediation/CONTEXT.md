# Context

- Project scaffold created and checklist initialized.
- Completed item `4.1` by refactoring `src/remora/core/actor.py` into focused components:
  - `TriggerPolicy` for cooldown/depth enforcement and cleanup
  - `PromptBuilder` for system/user prompt assembly
  - `AgentTurnExecutor` for turn orchestration and kernel execution
  - `Actor` now centered on inbox/outbox/lifecycle orchestration with compatibility wrappers
- Verification run for 4.1:
  - `devenv shell -- uv sync --extra dev`
  - `devenv shell -- pytest tests/unit/test_actor.py tests/unit/test_runner.py -q`
  - `devenv shell -- pytest tests/unit/test_externals.py::test_externals_emit_uses_outbox_when_provided -q`
- Next action: commit+push item 4.1, then implement item `4.2` lifecycle manager extraction.
