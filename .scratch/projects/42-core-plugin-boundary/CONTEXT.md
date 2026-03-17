# Context

## Current snapshot
- Branch: `main`
- `HEAD`: `18a1e9e` (Phase 2/4 consistency step completed and pushed)

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
- Finished Phase 3 prompt templating:
  - `PromptBuilder.build_user_prompt` now uses template interpolation.
  - Turn executor now builds user prompts through templates.
  - Defaults now include `prompt_templates.user/system/reflection`.
  - Actor/runner prompt tests updated to the new template contract.

## Remaining gaps
- Behavior defaults are only partially migrated; direct `Config()` callers still need cleanup (Phase 5).
- Externals version contract not wired (Phase 6).
- Search implementation still has module-level embeddy import boundary (Phase 7).

## Next action
Implement Phase 5 defaults-driven config cleanup and align direct `Config()` callers.
