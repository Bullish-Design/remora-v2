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
- Finished Phase 5 defaults cleanup:
  - Config now accepts defaults payload keys merged from `defaults.yaml`.
  - Runtime/integration fixtures that instantiate `Config()` now pass explicit behavior defaults.
  - Legacy bundle-path tests were migrated to `src/remora/defaults/...`.
- Finished Phase 6 externals versioning:
  - Added `EXTERNALS_VERSION = 1` in core externals contract.
  - Bundle config load now warns if bundle requires newer externals API version.
  - Added `externals_version: 1` to all shipped bundles.
  - Added `docs/externals-contract.md`.
- Finished Phase 7 optional search cleanup:
  - Search service no longer imports embeddy at module import time.
  - Remote client import is lazy and capability-scoped.
  - Search/unit service tests updated and passing.

## Remaining gaps
- Final Phase 8 verification checklist and freeze validation.

## Next action
Run final verification pass (Phase 8), then close project 42.
