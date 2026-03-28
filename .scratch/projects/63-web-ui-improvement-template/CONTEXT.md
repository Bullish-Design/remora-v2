# Context — 63-web-ui-improvement-template

Current focus:
- Apply the **v2** graph-overhaul spec from:
  - `.scratch/projects/63-web-ui-improvement-template/WEB_UI_IMPROVEMENT_GUIDE.md`
  - `.scratch/projects/63-web-ui-improvement-template/CONCEPT.md`

Current status:
- `src/remora/web/static/index.html` now matches v2 semantics:
  - Top-down hierarchy via negated Y in deterministic file-column layout.
  - Directories removed from graph nodes and rendered as nested bounding boxes.
  - `contains` edges skipped entirely; only `imports` and `inherits` render.
  - `filesystem` chip toggles box visibility.
  - `qualifyLabels` fallback avoids self-qualifying duplicates.
  - Camera auto-fit runs after `loadGraph`.
- Fixed runtime regression: Sigma `beforeRender` did not pass an event context in this build.
  - Resolution: draw boxes using `renderer.getCanvases().edges.getContext("2d")`.
- Fixed acceptance click interception:
  - Compacted filter bar footprint (`max-width` + wrapped groups + vertical stack) so graph label click targets remain accessible.

Validation:
- `devenv shell -- pytest tests/acceptance/test_web_graph_ui.py tests/unit/test_web_static_assets.py tests/unit/test_web_server.py tests/unit/test_web_decomposition.py tests/unit/test_sse_resume.py -q -rs`
  - `63 passed, 2 warnings`

Constraints and direction:
- Node labels remain always visible by default.
- Scope remains graph-focused; sidebar/event/timeline behavior unchanged.

Next immediate step:
- Capture a fresh Playwright screenshot from the target demo flow to validate visual legibility with live data.
