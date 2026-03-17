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

## Next Action
- Commit and push section 1.3 checkpoint.
- Begin section 1.4 implementation (strict prompt key validation in bundle config).
