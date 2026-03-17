# Context

## Current snapshot
- Branch: `main`
- `HEAD`: `af4c35e` (intern Step 1)
- Previous commit `HEAD~1`: guide doc edit only.
- Uncommitted intern carry-over exists in:
  - `src/remora/core/config.py`
  - `src/remora/defaults/__init__.py`

## What intern completed
- Moved bundles + query assets into `src/remora/defaults/`.
- Added initial defaults helpers and `defaults.yaml`.
- Added early language-registry and config changes.

## Completed since audit
- Finished Phase 2/4 consistency layer:
  - Added centralized path resolvers in `core/config.py`.
  - Switched reconciler to `bundle_search_paths` + `resolve_bundle_dirs`.
  - Switched runtime language query resolution to `query_search_paths`.
  - Removed old `bundle_root` and old config key usage from source/tests.
  - Converted language registry defaults to config-driven + defaults-backed registry.

## Remaining gaps
- Prompt builder still hardcoded (`build_prompt`), not template-driven (Phase 3).
- Behavior defaults are only partially migrated; direct `Config()` callers still need cleanup (Phase 5).
- Externals version contract not wired (Phase 6).
- Search implementation still has module-level embeddy import boundary (Phase 7).

## Next action
Implement Phase 3 template-driven prompts and update callsites/tests.
