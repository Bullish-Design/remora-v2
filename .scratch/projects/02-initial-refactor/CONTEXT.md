# Context

## Status: COMPLETE

All work in `.scratch/projects/02-initial-refactor/PLAN.md` has been implemented.

## What was completed
- Foundation updates:
  - Added `NodeRemovedEvent` and `SubscriptionRegistry.unregister_by_agent()`
  - Added config fields `language_map` and `query_paths`
  - Fixed runner externals:
    - `event_emit` now preserves payload via `CustomEvent`
    - `_read_bundle_config` handles `FsdFileNotFoundError`
    - workspace path discovery now uses `AgentWorkspace.list_all_paths()`
    - `propose_rewrite` now builds/stores full-file `new_source` replacement
  - Added `AgentWorkspace.list_all_paths()`
  - Removed unused `runner` params from web/LSP factory functions
  - Fixed source rendering in web view to avoid unsafe source interpolation

- Tree-sitter multi-language discovery:
  - Rewrote `src/remora/code/discovery.py`
  - Added grammar-backed parsing for Python, Markdown, TOML
  - Added query override lookup from `query_paths`
  - Added default query files:
    - `src/remora/code/queries/python.scm`
    - `src/remora/code/queries/markdown.scm`
    - `src/remora/code/queries/toml.scm`

- Reconciler rewrite:
  - Replaced old startup/poll functions with `FileReconciler`
  - Implemented:
    - `full_scan()`
    - `reconcile_cycle()` for new/modified/deleted files
    - `run_forever()` / `stop()`
  - Added stale node removal + `NodeRemovedEvent` emission
  - Added subscription idempotency handling

- Runtime wiring:
  - `__main__.py` now uses `FileReconciler` in startup runtime
  - CLI `discover` now passes `language_map` and resolved `query_paths`

- Docs/config:
  - Updated `remora.yaml.example` with `language_map` and `query_paths`
  - Updated README for multi-language discovery + reconciler model

## Validation
- Lint: `devenv shell -- ruff check src/ tests/` passed
- Tests: `devenv shell -- pytest -q` passed
- Result: `125 passed`

## Notes
- The plan suggested removing direct `tree-sitter` dependency. In practice, runtime parser/query APIs require importing `tree_sitter` directly, so `tree-sitter>=0.25` remains in dependencies.
