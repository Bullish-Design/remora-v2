# Project 41: Code Review 3 - Context

## Current Status
Implementation phase started from `.scratch/projects/41-code-review-3/REVIEW_REFACTOR_GUIDE.md`.

## Completed in This Session
- Read and loaded `.scratch/CRITICAL_RULES.md`.
- Read and loaded `.scratch/REPO_RULES.md`.
- Read the refactor guide and identified 17 implementation sections (1.1 -> 5.5).
- Initialized project tracking docs: `PLAN.md`, `ASSUMPTIONS.md`, `DECISIONS.md`, `ISSUES.md`.
- Rebased progress tracker from review-deliverable status to implementation step tracking.
- Completed section 1.1 (Node model unification):
  - `CSTNode` removed; discovery now returns `Node` directly and computes `source_hash`.
  - `source_code` renamed to `text` across runtime, storage schema, APIs, UI, and tests.
  - `projections.py` deleted and projection logic inlined into reconciler `_do_reconcile_file`.
  - `tests/unit/test_projections.py` deleted.
  - `src/remora/code/__init__.py` exports updated for removed symbols.
- Verification for section 1.1:
  - TDD red phase captured with failing discovery tests before implementation.
  - `devenv shell -- pytest tests/unit/test_discovery.py tests/unit/test_reconciler.py -q` passed.
  - `devenv shell -- pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q` passed (`357 passed, 8 skipped`).
- Completed section 1.2 (remove test-driven production indirection):
  - removed injected `create_kernel_fn`, `discover_tools_fn`, and `extract_response_text_fn` from `AgentTurnExecutor`.
  - removed actor-side lambda wrappers and now uses direct module imports in `turn_executor`.
  - removed `clear_caches()` from discovery and updated tests to use fresh `LanguageRegistry` injection.
  - switched turn executor logger namespace to `__name__` (`remora.core.turn_executor`) and updated log-capture tests.
  - updated actor/e2e monkeypatch paths to `remora.core.turn_executor.*`.
- Verification for section 1.2:
  - Red phase captured with 18 failing tests after monkeypatch path migration and before code cleanup.
  - `devenv shell -- pytest tests/unit/test_actor.py tests/unit/test_discovery.py tests/integration/test_e2e.py -q` passed.
  - `devenv shell -- pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q` passed (`357 passed, 8 skipped`).
- Completed section 1.3 (make env expansion API public):
  - renamed `_expand_string` -> `expand_string`.
  - renamed `_expand_env_vars` -> `expand_env_vars`.
  - updated `load_config` and `turn_executor` call sites/imports.
  - exported both public helpers in `core.config.__all__`.
  - updated config unit tests to import/use `expand_env_vars`.
- Verification for section 1.3:
  - Red phase captured by import error after switching tests/callers before renaming in `config.py`.
  - `devenv shell -- pytest tests/unit/test_config.py tests/unit/test_actor.py -q` passed.
  - `devenv shell -- pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q` passed (`357 passed, 8 skipped`).
- Completed section 1.4 (fix config silent drops):
  - added strict prompt-key validation in `BundleConfig._validate_prompts`.
  - unknown prompt keys now raise `ValueError` with valid-key details.
  - added `test_bundle_config_rejects_unknown_prompt_keys`.
- Verification for section 1.4:
  - Red phase captured with failing test (`DID NOT RAISE`) before validator change.
  - `devenv shell -- pytest tests/unit/test_config.py -q` passed.
  - `devenv shell -- pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q` passed (`358 passed, 8 skipped`).
- Completed section 1.5 (remove dead config):
  - removed `"file": "code-agent"` from default `Config.bundle_overlays`.
  - updated default-config test to assert `"file"` is not present.
- Verification for section 1.5:
  - Red phase captured with failing default-config assertion before config default change.
  - `devenv shell -- pytest tests/unit/test_config.py -q` passed.
  - `devenv shell -- pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q` passed (`358 passed, 8 skipped`).
- Completed section 1.6 (workspace `project_root` property):
  - added public `project_root` property to `CairnWorkspaceService`.
  - replaced web server private attribute access (`_project_root`) with `project_root`.
  - added `test_service_project_root_property`.
- Verification for section 1.6:
  - Red phase captured with `AttributeError` on missing `project_root` property.
  - `devenv shell -- pytest tests/unit/test_workspace.py tests/unit/test_web_server.py -q` passed.
  - `devenv shell -- pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q` passed (`359 passed, 8 skipped`).
- Completed section 2.1 (event type dispatch with stable identifiers):
  - added `EventType` `StrEnum` in `core/types.py`.
  - removed event class-name auto-assignment (`model_post_init`) from base `Event`.
  - set explicit `event_type` defaults on all concrete events using `EventType`.
  - migrated runtime event matching/subscription wiring to stable values.
  - migrated event-type literals in web/static UI, bundles, and tests to snake_case values.
  - restored `core.events`/`core.events.types` `__all__` symbol exports after literal migration.
- Verification for section 2.1:
  - targeted regression run passed:
    - `devenv shell -- pytest tests/unit/test_events.py tests/unit/test_subscription_registry.py tests/unit/test_event_store.py tests/unit/test_reconciler.py tests/unit/test_actor.py tests/unit/test_web_server.py tests/integration/test_e2e.py -q`
  - full suite passed after fixing residual bundle/config fixture references:
    - `devenv shell -- pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q` (`359 passed, 8 skipped`).

## Next Action
- Commit and push section 2.1 checkpoint.
- Begin section 2.2 implementation (actor-scoped send_message rate limiter).
