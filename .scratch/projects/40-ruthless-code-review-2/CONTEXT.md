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

Next action:
- Implement Step 1.2 (`NodeStore.batch()` rollback semantics + test).
