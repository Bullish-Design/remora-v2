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
- Step 2.2 completed:
  - removed Actor compatibility properties exposing TriggerPolicy internals
  - removed `_should_trigger` and `_cleanup_depth_state` wrappers
  - switched Actor loop trigger check to direct `TriggerPolicy.should_trigger(...)`
  - verified actor sanity tests:
    - `tests/unit/test_actor.py::test_actor_start_stop`
    - `tests/unit/test_actor.py::test_actor_processes_inbox_message`

Next action:
- Step 2.3: rewrite actor/runner tests that depended on removed compatibility APIs.
- Step 2.3 completed:
  - rewrote trigger/cooldown/depth tests to target `TriggerPolicy` directly
  - updated reset-state test to call `AgentTurnExecutor` directly
  - migrated prompt tests to `PromptBuilder.build_prompt(...)`
  - updated bundle config tests to call `AgentTurnExecutor._read_bundle_config(...)`
  - updated concurrent runner test to patch `TriggerPolicy.should_trigger`
  - verification: `tests/unit/test_actor.py tests/unit/test_runner.py` passed

Next action:
- Step 2.4: simplify `FileReconciler._normalize_dir_id`.
- Step 2.4 completed:
  - simplified `_normalize_dir_id` to a single `Path(path).as_posix()` path
  - verification: `tests/unit/test_reconciler.py` passed

Next action:
- Start Phase 3, Step 3.1 (add `SearchServiceProtocol` and begin typing migration).
- Step 3.1 completed:
  - added `SearchServiceProtocol` in `core/search.py`
  - exported protocol in module `__all__`
  - verification: `tests/unit/test_search.py` passed

Next action:
- Step 3.2: replace `search_service` `object|Any` types with `SearchServiceProtocol` across core/reconciler/web.
- Step 3.2 completed:
  - typed `search_service` as `SearchServiceProtocol | None` in:
    - `core/actor.py`
    - `core/externals.py`
    - `core/runner.py`
    - `core/services.py`
    - `code/reconciler.py`
    - `web/server.py`
  - verification subset passed:
    - `tests/unit/test_services.py`
    - `tests/unit/test_runner.py`
    - `tests/unit/test_reconciler.py`
    - `tests/unit/test_web_server.py`
    - `tests/unit/test_actor.py`
    - `tests/unit/test_externals.py`

Next action:
- Step 3.3: replace `getattr(..., \"available\", False)` checks with protocol-backed attribute access.
- Step 3.3 completed:
  - replaced duck-typed availability checks with direct protocol property access in:
    - `code/reconciler.py`
    - `web/server.py`
  - verification: `tests/unit/test_reconciler.py tests/unit/test_web_server.py` passed

Next action:
- Step 3.4: type remaining `Any` parameters (`TurnContext.outbox`, lifecycle callable, workspace typing note).
- Step 3.4 completed:
  - typed `TurnContext.outbox` using `TYPE_CHECKING` import of `Outbox`
  - typed `AgentWorkspace` raw workspace as `fsdantic.Workspace`
  - typed lifecycle logging callback as `Callable[[Path], None]`
  - verification:
    - `tests/unit/test_externals.py`
    - `tests/unit/test_workspace.py`
    - `tests/unit/test_cli.py`
    - `tests/integration/test_startup_shutdown.py`

Next action:
- Start Phase 4, Step 4.1 (`BundleConfig`/`SelfReflectConfig` model extraction in `core/config.py`).
- Step 4.1 completed:
  - added `SelfReflectConfig` and `BundleConfig` pydantic models to `core/config.py`
  - exported new models in config module `__all__`
  - verification: `tests/unit/test_config.py` passed

Next action:
- Step 4.2: replace `AgentTurnExecutor._read_bundle_config` manual parsing with `BundleConfig`.
- Step 4.2 completed:
  - replaced `_read_bundle_config` manual field validation with `BundleConfig.model_validate(...)`
  - preserved previous behavior for malformed YAML and disabled `self_reflect`
  - kept explicit defaults provided in YAML via `exclude_unset=True`
  - verification: `tests/unit/test_actor.py` passed

Next action:
- Step 4.3: update bundle config caller typing so prompt/build paths use typed config shape.
