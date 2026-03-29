# Progress — 64-graph-ui-refactor

## Project Setup
- [x] Read `GRAPH_IMPLEMENTATION_GUIDE.md` end-to-end.
- [x] Initialize standard project files (`PLAN`, `ASSUMPTIONS`, `CONTEXT`, `DECISIONS`, `ISSUES`, `PROGRESS`).
- [x] Scaffold template module directory for graph UI refactor.
- [x] Remove demo-repo check scaffolds and scope this project to `remora-v2` web UI code only.

## Phase Tracking
- [ ] Phase 0: Baseline capture and guardrails.
- [ ] Phase 1: Decompose monolithic script without behavior change.
- [ ] Phase 2: Introduce graph-state diff engine.
- [ ] Phase 3: Add force layout runtime.
- [ ] Phase 4: Interaction-first readability controls.
- [ ] Phase 5: SSE event reconciliation batching.
- [ ] Phase 6: Camera and mental-map stabilization.
- [ ] Phase 7: Remove obsolete deterministic layout code.
- [ ] Phase 8: Validation hardening + `remora-v2` web UI checks.
- [ ] Phase 9: Rollout flag, default flip, legacy cleanup.

## Immediate Next Actions
- [ ] Promote template modules into `src/remora/web/static/` and wire a no-op bootstrap path.
- [ ] Preserve all existing check pass behavior while decomposition lands.
