# Context

Project initialized from `REVIEW_REFACTORING_GUIDE.md`.
Phase 0 complete and documented in `BASELINE_NOTES.md`.

Current baseline:
- Dependency sync completed via `devenv shell -- uv sync --extra dev`
- Tests baseline: `349 passed, 8 skipped`
- Ruff baseline: 3 pre-existing `E501` violations

Next action:
- Step 1.1 completed:
  - moved `TurnContext._send_message_timestamps` from class state to instance state
  - added regression test: `test_externals_send_message_rate_limit_isolated_per_context_instance`
  - verification: `tests/unit/test_externals.py` passed
- Step 1.2 completed:
  - updated `NodeStore.batch()` to rollback on exception at outer batch boundary
  - added regression test: `test_batch_rolls_back_on_exception`
  - verification: `tests/unit/test_graph.py` passed
- Step 1.3 completed:
  - removed `NodeStore.set_status` API
  - migrated all callers/tests to `transition_status`
  - verification:
    - `tests/unit/test_graph.py` passed
    - `tests/unit/test_externals.py` passed

Next action:
- Start Phase 2, Step 2.1 (delete Actor delegation wrappers).
- Step 2.1 completed:
  - removed Actor delegation wrappers forwarding into `AgentTurnExecutor`/`PromptBuilder`
  - verified basic actor loop behavior with:
    - `tests/unit/test_actor.py::test_actor_start_stop`
    - `tests/unit/test_actor.py::test_actor_processes_inbox_message`

Next action:
- Step 2.2: remove Actor compatibility property shims and compatibility trigger wrappers.
