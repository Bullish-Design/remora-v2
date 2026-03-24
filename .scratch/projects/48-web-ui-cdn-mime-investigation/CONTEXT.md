# CONTEXT

- Project investigated web UI console failures related to script loading and `Sigma` runtime error.
- Source of failing URLs: `src/remora/web/static/index.html` lines 7-9 (before fix).

## Root Cause Evidence (2026-03-24)
- Graphology URL returned valid JS (`200`, JS MIME).
- Sigma URL at `/build/sigma.min.js` returned `404 text/plain` with `nosniff`.
- ForceAtlas2 URL at `/build/graphology-layout-forceatlas2.min.js` returned `404 text/plain` with `nosniff`.
- Package metadata confirmed Sigma publishes `/dist/sigma.min.js` and ForceAtlas2 package does not publish that `build/*.min.js` browser artifact.

## Changes Implemented
- `src/remora/web/static/index.html`
  - Sigma include changed to: `https://unpkg.com/sigma@3.0.0-beta.31/dist/sigma.min.js`
  - Removed invalid ForceAtlas2 include at `/build/graphology-layout-forceatlas2.min.js`
- `tests/unit/test_views.py`
  - Added `test_graph_html_uses_valid_cdn_script_paths` asserting:
    - Sigma uses `/dist/sigma.min.js`
    - broken Sigma `/build/...` URL absent
    - broken ForceAtlas2 `/build/...` URL absent

## Validation
- Ran: `devenv shell -- pytest tests/unit/test_views.py -q`
- Result: `5 passed`
