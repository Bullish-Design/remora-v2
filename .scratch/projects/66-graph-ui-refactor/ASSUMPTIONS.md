# Assumptions — 64-graph-ui-refactor

1. Source of truth for durable UI changes is `src/remora/web/static/*` in `remora-v2`.
2. Existing endpoints (`/api/nodes`, `/api/edges`, `/sse`, `/api/chat`, proposal APIs) remain contract-stable.
3. Existing screenshot and dependency checks remain required quality gates.
4. Refactor should be phased to minimize regressions in existing `remora-v2` web UI behavior and tests.
5. Force-layout nondeterminism must be bounded with seed + fixed iteration policy for screenshot stability.
6. Migration should keep local vendor assets under `/static/vendor/*` and avoid CDN dependencies.
