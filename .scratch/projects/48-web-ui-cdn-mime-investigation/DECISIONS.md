# DECISIONS

## Phase 1 (CDN issue)
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

## Phase 2 (Node visuals/layout)
5. Use Sigma custom node label drawing for box visuals.
- Rationale: gives box-like nodes with names while staying inside current Sigma architecture, avoiding a large renderer migration.

6. Use deterministic lane/depth/sibling placement.
- Rationale: predictable organization improves readability and avoids random layout jitter.

7. Remove stale ForceAtlas2 controls from HTML.
- Rationale: ForceAtlas2 script was intentionally removed in phase 1; leaving runtime toggles/attributes would be dead config.

## Phase 3 (Sidebar tall layout)
8. Pivot file grouping from x-axis lanes to y-axis bands.
- Rationale: sidebar contexts are narrow; vertical stacking preserves readability better than wide spread.

9. Keep x-axis compact and semantic.
- Rationale: assign narrow x tracks by node type plus limited sibling spread so the graph remains usable in skinny panes.

10. Expose clear spacing constants for iterative tuning.
- Rationale: practical follow-up tuning is expected, so constants are centralized (`FILE_BAND_SPACING`, `DEPTH_ROW_SPACING`, `SIBLING_SPREAD`, `TYPE_TRACK_OFFSETS`).

## Phase 4 (Wider x distribution)
11. Keep tall flow but intentionally widen x spacing.
- Rationale: screenshot feedback showed near-single-column collapse.

12. Expand type tracks to include directory/file and increase separation.
- Rationale: most nodes in current graph were on fallback/center tracks.

13. Add deterministic depth-wave/hash x offsets.
- Rationale: long single-child chains need non-sibling-based spread to avoid a rigid spine.
