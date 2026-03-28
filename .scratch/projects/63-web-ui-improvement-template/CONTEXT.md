# Context — 63-web-ui-improvement-template

Current focus:
- Apply **v4 sigma-first** graph readability updates from:
  - `.scratch/projects/63-web-ui-improvement-template/CONCEPT_V4.md`
  - `.scratch/projects/63-web-ui-improvement-template/SIGMA_FIRST_IMPLEMENTATION_STRATEGY.md`

Current status:
- `src/remora/web/static/index.html` now includes:
  - Sigma-native fit flow (`setCustomBBox` + `animatedReset`) with cross-file edge metadata and style routing.
  - Wrapped deterministic lane layout:
    - file columns are row-packed into multiple lanes based on viewport-informed target width.
    - collision guard pass enforces minimum inter-column separation.
  - Edge emphasis control:
    - new chip `data-filter-edge-emphasis="cross-file"`.
    - `filterState.edgeEmphasisCrossFileOnly` hides non-cross-file edges when active.
  - Zoom-aware box declutter:
    - deep nested box strokes attenuate when zoomed out.
    - box headers only render when both size and zoom thresholds are met.
- `tests/unit/test_views.py` updated to assert current graph implementation markers, removing stale expectations from pre-v2 layout code.

Validation:
- `devenv shell -- pytest tests/acceptance/test_web_graph_ui.py tests/unit/test_views.py tests/unit/test_web_static_assets.py tests/unit/test_web_server.py tests/unit/test_web_decomposition.py tests/unit/test_sse_resume.py -q -rs`
  - `70 passed, 2 warnings`

Constraints and direction:
- Node labels remain always visible.
- Scope remains graph-view focused; sidebar/event/timeline behavior unchanged.

Next immediate step:
- Capture new Playwright screenshots and tune constants (row width/row gap/header thresholds/edge prominence) against real demo graph density.
