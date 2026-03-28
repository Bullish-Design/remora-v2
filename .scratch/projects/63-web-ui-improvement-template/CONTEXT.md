# Context — 63-web-ui-improvement-template

Current focus:
- Apply the **v3** graph-overhaul deltas from:
  - `.scratch/projects/63-web-ui-improvement-template/CONCEPT_V3.md`

Current status:
- `src/remora/web/static/index.html` now includes v3 updates on top of v2:
  - Wider deterministic spacing constants (`COL_PAD`, `MIN_COL_WIDTH`, `PX_PER_UNIT`, padding constants) to reduce label overlap.
  - Vertical placement now uses slot index per file column (`y = -(slotIndex * ROW_HEIGHT)`) for consistent spread.
  - Load-time centroid centering shifts all node positions and bounding boxes before graph add.
  - Bounding boxes are materially more visible on dark background via higher fill/stroke/label alpha.
  - Sigma edge program configuration now safely attempts arrow registration and falls back to line when unavailable.
- Fixed v3 boot regression:
  - Root cause: direct `sigma` global reference caused `ReferenceError` in this bundle.
  - Resolution: use `globalThis.sigma` guarded lookup for optional program exports.

Validation:
- `devenv shell -- pytest tests/acceptance/test_web_graph_ui.py tests/unit/test_web_static_assets.py tests/unit/test_web_server.py tests/unit/test_web_decomposition.py tests/unit/test_sse_resume.py -q -rs`
  - `63 passed, 2 warnings`

Constraints and direction:
- Node labels remain always visible by default.
- Scope remains graph-focused; sidebar/event/timeline behavior unchanged.

Next immediate step:
- Capture a fresh Playwright screenshot from the demo flow and compare legibility/edge visibility against the prior v2 screenshot.
