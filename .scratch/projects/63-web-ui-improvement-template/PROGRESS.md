# Progress — 63-web-ui-improvement-template

- [x] Phase 1 complete: baseline audit
- [x] Phase 2 complete: UX spec + visual direction
- [x] Phase 3 complete: implementation
- [x] Phase 4 complete: validation
- [x] Phase 5 complete: polish + docs

## Active execution: `WEB_UI_IMPROVEMENT_GUIDE.md`

- [x] Step 1: Add CSS variables
- [x] Step 2: Add filter bar + zoom control HTML wrapper
- [x] Step 3: Add filter bar + zoom control CSS
- [x] Step 4: Replace layout constants
- [x] Step 5: Add edge style constants
- [x] Step 6: Add `qualifyLabels`
- [x] Step 7: Add `layoutNodes`
- [x] Step 8: Rewrite `loadGraph`
- [x] Step 9: Rewrite `drawNodeBoxLabel`
- [x] Step 10: Update Sigma constructor
- [x] Step 11: Update `nodeColor` palette
- [x] Step 12: Add `filterState` + `applyFilters`
- [x] Step 13: Wire filter chip handlers
- [x] Step 14: Add hover highlight handlers
- [x] Step 15: Wire zoom controls
- [x] Step 16: Remove dead layout code
- [x] Step 17: Verification checklist

## Verification results (Step 17)

- `devenv shell -- pytest tests/unit/test_web_static_assets.py tests/unit/test_web_server.py tests/unit/test_web_decomposition.py tests/unit/test_sse_resume.py -q`
  - Result: `60 passed`
- `devenv shell -- pytest tests/acceptance/test_web_graph_ui.py -q -rs`
  - Result: `3 passed`
  - Notes: Added pointer-event passthrough on graph overlays so chips/buttons are clickable
    while still allowing graph click hit-testing under the overlay regions.

## Release handoff

- [x] Bump package version to `0.6.0` in runtime and packaging metadata.
- [x] Commit, push, and publish tag `v0.6.0`.
- [x] Patch release follow-up completed: version `0.6.1` tagged and pushed.

## Follow-up utility

- [x] Add local Playwright screenshot helper script in `scripts/playwright_screenshot.py`.

## Post-release polish

- [x] Replace graph canvas background gradient with flat deep-blue fill.

## v2 follow-up (latest)

- [x] Re-read updated `WEB_UI_IMPROVEMENT_GUIDE.md` + `CONCEPT.md` and align implementation.
- [x] Switch to v2 layout semantics:
  - Negated Y-axis (top-down hierarchy).
  - Directory nodes excluded from graph.
  - `contains` edges excluded from graph rendering.
  - Directory hierarchy rendered as nested filesystem bounding boxes.
- [x] Add v2 `qualifyLabels` fallback (avoid `Name/Name`, prefer directory path qualifier).
- [x] Add camera auto-fit after graph rebuild.
- [x] Add `filesystem` filter chip wiring (`data-filter-boxes`) to toggle bounding boxes.
- [x] Fix Sigma `beforeRender` regression by drawing boxes from `renderer.getCanvases().edges`.
- [x] Compact filter bar footprint to avoid intercepting graph label clicks in acceptance flow.

### v2 verification

- `devenv shell -- pytest tests/acceptance/test_web_graph_ui.py tests/unit/test_web_static_assets.py tests/unit/test_web_server.py tests/unit/test_web_decomposition.py tests/unit/test_sse_resume.py -q -rs`
  - Result: `63 passed, 2 warnings`

## v3 implementation (CONCEPT_V3)

- [x] Apply v3 layout constants:
  - `COL_PAD 6.0`, `MIN_COL_WIDTH 6.0`, `PX_PER_UNIT 10`, `LABEL_PAD_PX 24`,
    `BOX_PAD 2.5`, `BOX_HEADER 1.6`.
- [x] Update within-column y placement to slot-index spacing (`y = -(slotIndex * ROW_HEIGHT)`).
- [x] Add load-time data centering (shift nodes + bounding boxes by centroid) before rendering.
- [x] Increase bounding-box visibility alpha values for dark background:
  - fill `0.07 + depth*0.02`, stroke `0.22 + depth*0.06`, label `0.55 + depth*0.1`.
- [x] Add explicit Sigma edge program wiring with safe fallback:
  - use arrow program when available, otherwise default to line.
- [x] Fix v3 regression: avoid direct `sigma` global reference; use `globalThis.sigma`.

### v3 verification

- `devenv shell -- pytest tests/acceptance/test_web_graph_ui.py tests/unit/test_web_static_assets.py tests/unit/test_web_server.py tests/unit/test_web_decomposition.py tests/unit/test_sse_resume.py -q -rs`
  - Result: `63 passed, 2 warnings`

## v4 sigma-first follow-up

- [x] Add sigma-first implementation strategy docs:
  - `CONCEPT_V4.md`
  - `SIGMA_FIRST_IMPLEMENTATION_STRATEGY.md`
- [x] Implement Step 1 sigma-native fit + edge metadata/styling.
- [x] Implement Step 2 readability updates:
  - Wrapped lane layout in `layoutNodes` using deterministic row packing.
  - Cross-file edge emphasis filter chip (`data-filter-edge-emphasis="cross-file"`).
  - Zoom-aware filesystem box declutter in `beforeRender`.
- [x] Update static view coverage for new graph implementation markers.

### v4 verification (Step 2)

- `devenv shell -- pytest tests/acceptance/test_web_graph_ui.py tests/unit/test_views.py tests/unit/test_web_static_assets.py tests/unit/test_web_server.py tests/unit/test_web_decomposition.py tests/unit/test_sse_resume.py -q -rs`
  - Result: `70 passed, 2 warnings`

## v5 concept drafting

- [x] Analyze latest screenshot:
  - `.scratch/projects/63-web-ui-improvement-template/ui-playwright-20260328-110404-178.png`
- [x] Compare against v4 goals and identify remaining legibility gaps.
- [x] Draft v5 corrective architecture and implementation plan:
  - `.scratch/projects/63-web-ui-improvement-template/CONCEPT_V5.md`

## v5 implementation execution

- [x] Step 1: v5 layout mode scaffolding (`LAYOUT_MODE` switch + dispatch).
- [x] Step 2: component-aware layout pipeline (component extraction + packing).
- [x] Step 3: occupancy normalization pass for stable graph density.
- [x] Step 4: readability-constrained fit and initial-fit path cleanup.
- [x] Step 5: iterative unique label qualification with deterministic fallback.
- [x] Step 6: edge priority tuning (cross-file emphasis, same-file attenuation, long-edge fade).
- [x] Step 7: filesystem fallback grouping via synthetic directories.
- [x] Step 8: acceptance-test metric hardening (occupancy/overlap/uniqueness/edge-span).

### v5 verification

- `devenv shell -- pytest tests/acceptance/test_web_graph_ui.py tests/unit/test_views.py tests/unit/test_web_static_assets.py tests/unit/test_web_server.py tests/unit/test_web_decomposition.py tests/unit/test_sse_resume.py -q -rs`
  - Result: `70 passed, 2 warnings`

## v6 concept drafting

- [x] Analyze latest screenshot:
  - `.scratch/projects/63-web-ui-improvement-template/ui-playwright-20260328-121351-721.png`
- [x] Identify remaining gaps against desired demo UI goals.
- [x] Create v6 corrective design + implementation guide:
  - `.scratch/projects/63-web-ui-improvement-template/CONCEPT_V6.md`

## v6 implementation execution

- [x] Step 1: Refine label pipeline to enforce concise workspace-relative qualifiers.
- [x] Step 2: Add core/peripheral component zoning and peripheral docking.
- [x] Step 3: Add peripheral visual treatment (zone-aware node/edge emphasis).
- [x] Step 4: Increase hierarchy box/header legibility while keeping nested declutter.
- [x] Step 5: Add optional context tethers for edge-less nodes.
- [x] Step 6: Extend acceptance metrics and finalize verification.

### v6 verification (in progress)

- `devenv shell -- pytest tests/unit/test_views.py -q -rs`
  - Result: `6 passed`
- `devenv shell -- pytest tests/acceptance/test_web_graph_ui.py -q -rs`
  - Result: `4 passed, 2 warnings`

## v7 implementation execution (CONCEPT_V7)

- [x] Step 1: Sigma settings upgrade.
- [x] Step 2: Edge event handlers.
- [x] Step 3: Fix peripheral grid layout.
- [ ] Step 4: Core zone canvas reservation + `setCustomBBox`.
- [ ] Step 5: Zone separator rendering.
- [ ] Step 6: Hierarchy box alpha overhaul.
- [ ] Step 7: Edge narrative emphasis.
- [ ] Step 8: Peripheral visual de-emphasis.
- [ ] Step 9: Smooth graph updates with `animateNodes`.
- [ ] Step 10: Tests and verification.

### v7 verification (in progress)

- `devenv shell -- uv sync --extra dev`
  - Result: `synced`
- `devenv shell -- pytest tests/unit/test_views.py -q -rs`
  - Result: `6 passed`
