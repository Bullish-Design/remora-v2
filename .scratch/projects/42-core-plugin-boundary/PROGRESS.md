# Progress

## Intern Audit Status
- [x] Reviewed `HEAD~1`: docs-only update to refactor guide.
- [x] Reviewed `HEAD`: partial implementation landed (mostly Phase 1 + partial 2/5).
- [x] Reviewed current uncommitted intern edits (`core/config.py`, `defaults/__init__.py`).

## Guide Status

### Phase 1: Defaults package
- [x] 1.1 defaults package helpers added (needs small typing fix).
- [x] 1.2 bundles moved into `src/remora/defaults/bundles`.
- [x] 1.3 queries moved into `src/remora/defaults/queries`.
- [x] 1.4 packaging assets included.
- [~] 1.6/1.7 bundle fallback usage partially implemented but still inconsistent with config model.

### Phase 2: Config-driven language registry
- [x] Generic plugin + `LanguageRegistry.from_config` completed.
- [x] Python kept as the only advanced plugin; markdown/toml use `GenericLanguagePlugin`.
- [x] Discovery default registry now loads from shipped defaults (`LanguageRegistry.from_defaults()`).
- [x] Query search-path resolution unified through config helper + runtime wiring.

### Phase 3: Template-driven prompts
- [x] Replaced hardcoded `build_prompt` with template-based `build_user_prompt`.
- [x] Added interpolation contract variables (`node_*`, `event_*`, `turn_mode`, `companion_context`).
- [x] User prompt template now supports per-bundle override (`bundle.yaml` `prompt_templates.user`).
- [x] Reflection prompt now resolves from self_reflect override, bundle template, then defaults template.
- [x] Updated turn executor + tests to use `build_user_prompt`.

### Phase 4: Bundle search path resolution
- [x] `bundle_search_paths` and `query_search_paths` now drive resolution.
- [x] Added `resolve_bundle_search_paths`, `resolve_bundle_dirs`, `resolve_query_search_paths`.
- [x] Reconciler provisioning now uses precomputed bundle search paths.
- [x] Removed old `bundle_root`/`query_paths` usage in source and updated tests/config fixtures.

### Phase 5: Defaults extraction
- [x] `defaults.yaml` + `load_config` merge is wired.
- [x] Added Config fields for defaults payload keys (`prompt_templates`, `externals_version`).
- [x] Updated direct `Config()` tests/fixtures to pass explicit behavior-layer values where needed.
- [x] Updated bundle/tool tests to assert against `src/remora/defaults/...` paths.

### Phase 6: Externals versioning
- [ ] Not implemented.

### Phase 7: Optional search boundary
- [~] Optional deps exist, but module-level embeddy import boundary cleanup incomplete.

### Phase 8: Verification
- [ ] Pending after implementation completion.
