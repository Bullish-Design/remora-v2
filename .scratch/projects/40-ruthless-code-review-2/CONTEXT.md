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
- Step 4.3 completed:
  - changed `_read_bundle_config` to return `BundleConfig`
  - changed `_start_agent_turn` and `PromptBuilder.build_system_prompt` to use typed `BundleConfig`
  - replaced dict `.get(...)` prompt logic with direct typed attribute access
  - updated actor unit tests to validate typed bundle config behavior
  - verification:
    - `tests/unit/test_actor.py`
    - `tests/unit/test_bundle_configs.py`

Next action:
- Start Phase 5 decomposition of `core/actor.py` (Step 5.1 outbox module extraction).
- Step 5.1 completed:
  - created `core/outbox.py` with `Outbox` and `OutboxObserver`
  - removed in-file outbox class definitions from `core/actor.py`
  - imported outbox classes into `core/actor.py` to preserve existing imports/re-exports
  - verification:
    - `tests/unit/test_actor.py`
    - `tests/unit/test_externals.py`

Next action:
- Step 5.2: extract `Trigger` and `TriggerPolicy` into `core/trigger.py`.
- Step 5.2 completed:
  - created `core/trigger.py` with `Trigger`, `TriggerPolicy`, and depth constants
  - removed trigger primitives from `core/actor.py` and imported from new module
  - verification:
    - `tests/unit/test_actor.py`
    - `tests/unit/test_runner.py`

Next action:
- Step 5.3: extract `PromptBuilder` and related prompt helpers/constants into `core/prompt.py`.
- Step 5.3 completed:
  - created `core/prompt.py` containing `PromptBuilder`, `_event_content`, and reflection prompt constant
  - removed in-file prompt builder implementation from `core/actor.py`
  - imported `PromptBuilder` into `core/actor.py` to preserve existing public imports
  - verification:
    - `tests/unit/test_actor.py`
    - `tests/unit/test_runner.py`

Next action:
- Step 5.4: extract `AgentTurnExecutor` and `_turn_logger` into `core/turn_executor.py`.
- Step 5.4 completed:
  - created `core/turn_executor.py` with `_turn_logger` and `AgentTurnExecutor`
  - slimmed `core/actor.py` to Actor orchestration + re-exports while preserving monkeypatch compatibility
  - kept historical logger namespace (`remora.core.actor`) for turn logs
  - verification:
    - `tests/unit/test_actor.py`
    - `tests/unit/test_runner.py`

Next action:
- Step 5.5/5.6: finalize actor slim-down and verify re-exports/import paths across src/tests.
- Step 5.5 completed:
  - `core/actor.py` now contains only the `Actor` orchestration class + re-export surface
  - verified only one class remains in actor module
- Step 5.6 completed:
  - verified `from remora.core.actor import ...` usage sites across `src/` and `tests/`
  - re-export paths are intact for Actor/Outbox/Trigger/PromptBuilder/AgentTurnExecutor

Next action:
- Step 5.7: run full test verification command for Phase 5 and commit/push the phase completion checkpoint.
- Step 5.7 completed:
  - full verification command passed:
    - `devenv shell -- python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q`
    - result: `351 passed, 8 skipped, 3 warnings`
  - decomposition details:
    - actor module now orchestrates only
    - extracted modules: `outbox.py`, `trigger.py`, `prompt.py`, `turn_executor.py`
    - maintained actor-module monkeypatch and logger compatibility during extraction

Next action:
- Start Phase 6 (`web/server.py` refactor): extract handler dependency dataclass and module-level handler groups.
- Step 6.1 completed:
  - added `WebDeps` dataclass to `web/server.py` for shared handler dependencies
  - verification: `tests/unit/test_web_server.py` passed

Next action:
- Step 6.2 completed:
  - moved all API/SSE handlers in `web/server.py` from `create_app` closure scope to module-level functions
  - each handler now resolves dependencies via `request.app.state.deps` (`WebDeps`)
  - `create_app` now wires `app.state.deps = deps` so handlers share one dependency container
  - verification: `devenv shell -- python -m pytest tests/unit/test_web_server.py -v` passed (`45 passed`)

Next action:
- Step 6.3 completed:
  - extracted `_resolve_within_project_root`, `_workspace_path_to_disk_path`, and `_latest_rewrite_proposal` to module scope in `web/server.py`
  - proposal endpoints now call shared helpers instead of repeating path/proposal resolution logic inline
  - verification: `devenv shell -- python -m pytest tests/unit/test_web_server.py -q` passed (`45 passed`)

Next action:
- Step 6.4 completed:
  - extracted `_build_routes()` so route declarations are no longer embedded in `create_app`
  - extracted `_build_lifespan(shutdown_event)` so `create_app` only wires dependencies and app state
  - `create_app` now focuses on constructing `WebDeps`, app initialization, and middleware/static mounting
  - verification: `devenv shell -- python -m pytest tests/unit/test_web_server.py -q` passed (`45 passed`)

Next action:
- Step 6.5 completed:
  - ran phase checkpoint verification:
    - `devenv shell -- python -m pytest tests/unit/test_web_server.py -v`
    - result: `45 passed, 1 warning`
  - Phase 6 (`web/server.py` refactor) is now complete.

Next action:
- Start Phase 7 Step 7.1 in `core/events/types.py`: remove the redundant `tags` field from `TurnDigestedEvent` to resolve the field shadow warning.
- Step 7.1 completed:
  - removed redundant `tags` field declaration from `TurnDigestedEvent` in `core/events/types.py`
  - behavior unchanged (field already inherited from base `Event`)
  - verification: `devenv shell -- python -m pytest tests/unit/test_events.py -q` passed (`14 passed`)

Next action:
- Step 7.2: override `CustomEvent.to_envelope()` to flatten payload shape (`payload` should not be nested under `payload.payload`).
- Step 7.2 completed:
  - added `CustomEvent.to_envelope()` override to emit payload directly (no nested `payload.payload`)
  - added regression test coverage in `tests/unit/test_events.py` for flattened envelope shape
  - verification: `devenv shell -- python -m pytest tests/unit/test_events.py -q` passed (`15 passed`)

Next action:
- Step 7.3: fix `EventBus.unsubscribe` to remove handlers from all relevant registries and prevent stale registrations.
