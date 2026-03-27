# Context — 61-idea6-required-impl

Implemented required P0 repo/test updates for Idea #6 reliability.

Code changes:
- `src/remora/code/reconciler.py`
  - Added semantic refresh orchestration helpers:
    - `_refresh_semantic_relationships_for_paths(...)`
    - `_semantic_refresh_paths(...)`
    - `_python_plugin_for_path(...)`
  - `reconcile_cycle()` now triggers semantic refresh over impacted Python set when Python files change/delete.
  - `_handle_watch_changes(...)` now uses same semantic refresh orchestration, ensuring watch-path parity.
  - `_on_content_changed(...)` now reconciles with `refresh_relationships=False` then applies shared semantic refresh orchestration.

Tests added/updated:
- `tests/unit/test_reconciler_edges.py`
  - `test_reconcile_backfills_imports_when_target_file_added_later`
  - `test_reconcile_removes_semantic_edges_when_target_symbol_removed`
  - `test_reconcile_does_not_duplicate_semantic_edges_across_repeated_cycles`
- `tests/unit/test_reconciler.py`
  - `test_handle_watch_changes_refreshes_semantic_edges_order_independently`
  - `test_handle_watch_changes_backfills_when_only_target_file_changes`
  - `test_reconciler_content_changed_event_backfills_target_only_relationships`
- `tests/integration/test_lifecycle.py`
  - helper `_wait_for_health(...)`
  - helper `_wait_for_semantic_edges(...)`
  - `test_lifecycle_startup_exposes_semantic_edges_via_api`

Validation:
- Targeted/new suite passes.
- Required doc gate passes:
  - `pytest tests/unit/test_reconciler_edges.py tests/unit/test_reconciler.py tests/unit/test_relationships.py tests/unit/test_graph.py tests/integration/test_lifecycle.py -q --tb=short`
- Touched-file lint passes.

Residual note:
- Full `ruff check src/ tests/` still reports many pre-existing unrelated violations.
