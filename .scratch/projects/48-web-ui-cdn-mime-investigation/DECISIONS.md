# DECISIONS

1. Treat the MIME mismatch as symptom, not root cause.
- Rationale: the browser reports MIME mismatch because the requested script URLs return 404 plain text, not JavaScript.

2. Classify failures into primary vs cascading.
- Primary: incorrect CDN paths (and incompatible packaging expectations for ForceAtlas2).
- Cascading: `Sigma is not defined` because Sigma never loaded.

3. Add a regression test before code changes (TDD).
- Rationale: lock in known-good script references and prevent reintroducing broken CDN paths.
- Test added: `tests/unit/test_views.py::test_graph_html_uses_valid_cdn_script_paths`.

4. Fix strategy implemented.
- Update Sigma script include from `/build/sigma.min.js` to `/dist/sigma.min.js`.
- Remove ForceAtlas2 script include that points to a non-existent `/build/*.min.js` artifact.
- Keep runtime guard `if (window.graphologyLayoutForceatlas2)` so optional layout remains non-fatal if introduced later.
