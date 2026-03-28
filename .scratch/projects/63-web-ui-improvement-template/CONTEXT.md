# Context — 63-web-ui-improvement-template

Current focus:
- Execute the full `CONCEPT_V5.md` implementation sequence and validate outcomes.

Current status:
- `CONCEPT_V5.md` implementation is complete in `src/remora/web/static/index.html`:
  - v5 component-first layout path with mode dispatch.
  - occupancy normalization to stabilize graph density.
  - readability-constrained Sigma fit margins and label-width guard.
  - iterative globally-unique display labels with deterministic hash fallback.
  - edge priority tuning (cross-file emphasis, same-file attenuation, long-edge fade).
  - filesystem fallback grouping via synthetic directory hierarchy when needed.
- Acceptance suite now includes stronger runtime metrics in
  `tests/acceptance/test_web_graph_ui.py`:
  - occupancy floor/ceiling,
  - label overlap ratio,
  - duplicate label rejection,
  - non-zero edge on-screen span when edges exist.
- Verified:
  - `devenv shell -- pytest tests/acceptance/test_web_graph_ui.py tests/unit/test_views.py tests/unit/test_web_static_assets.py tests/unit/test_web_server.py tests/unit/test_web_decomposition.py tests/unit/test_sse_resume.py -q -rs`
  - `70 passed, 2 warnings`

Constraints and direction:
- Node labels remain always visible.
- Scope remains graph-view focused; sidebar/event/timeline behavior unchanged.

Next immediate step:
- Patch release handoff:
  - patch version bump,
  - commit/push,
  - annotated tag push.
