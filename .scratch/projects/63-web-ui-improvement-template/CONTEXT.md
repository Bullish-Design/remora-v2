# Context — 63-web-ui-improvement-template

Current focus:
- Complete graph-view overhaul from
  `.scratch/projects/63-web-ui-improvement-template/WEB_UI_IMPROVEMENT_GUIDE.md`.

Current status:
- Steps 1-17 implemented in `src/remora/web/static/index.html`.
- Added node/edge filter bar, zoom controls, deterministic column layout, type-shaped
  node rendering, hover neighborhood focus, edge style reducers, and filter application.
- Removed legacy jitter/band layout helpers.
- Validation executed with unit + acceptance tests.
- Release follow-up requested: bump project version to `0.6.0`, commit, push, tag.
- Added screenshot utility request: local Playwright capture script for this repo.

Validation:
- `devenv shell -- pytest tests/unit/test_web_static_assets.py tests/unit/test_web_server.py tests/unit/test_web_decomposition.py tests/unit/test_sse_resume.py -q` -> `60 passed`.
- `devenv shell -- pytest tests/acceptance/test_web_graph_ui.py -q -rs` -> `3 passed`.
- During validation, fixed overlay pointer interception by setting overlay containers
  to `pointer-events: none` and interactive controls to `pointer-events: auto`.

Constraints and direction:
- Node labels remain always visible by default.
- Scope remains graph-focused; sidebar behavior preserved.

Next immediate step:
- Use `scripts/playwright_screenshot.py` for local graph UI snapshot verification.
