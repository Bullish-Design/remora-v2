# GRAPH_IMPLEMENTATION_GUIDE.md

## Purpose
This document is a deep technical analysis and implementation guide for refactoring the current Remora web UI from an "organized" deterministic layout into a true graph view that remains usable at runtime scale.

The guide is written for engineers working in the `remora-v2` UI codepath while validating behavior from the `remora-test` demo repository.

## Scope
In scope:
- Move layout ownership from custom deterministic placement heuristics to graph-native layout behavior.
- Preserve current core UX contracts: select/inspect nodes, edge filtering, SSE updates, chat/proposal workflows, screenshot stability.
- Keep packaged vendor assets under `/static/vendor/*` (no unpkg CDN).
- Provide a low-risk, phased migration plan with explicit verification gates.

Out of scope:
- Rewriting the entire backend API.
- Introducing a mandatory frontend bundler if you do not want one.
- Redesigning non-graph panels (chat/timeline/proposals) beyond compatibility updates.

---

## 1. Current State Analysis (Evidence)

### 1.1 Asset serving model
The UI is served from the installed `remora` package, not this repo's local `src/` tree.

Evidence:
- Server static mount and index source:
  - `.devenv/state/venv/lib/python3.13/site-packages/remora/web/server.py:31`
  - `.devenv/state/venv/lib/python3.13/site-packages/remora/web/server.py:48`
  - `.devenv/state/venv/lib/python3.13/site-packages/remora/web/server.py:103`
- Demo runbook explicitly states UI source is from installed package:
  - `demo/00_repo_baseline/README.md` section "UI Source"

Implication:
- Editing only `.devenv/.../site-packages/remora/web/static/index.html` is ephemeral and non-portable.
- Durable implementation must land in `remora-v2` source and then be consumed by this demo repo via dependency source.

### 1.2 Current graph UI implementation style
The current UI is a very large single-file `index.html` script with custom layout engines and rendering logic mixed together.

Evidence in installed asset:
- Graph object creation:
  - `.../remora/web/static/index.html:414`
- Large layout constant map:
  - `.../remora/web/static/index.html:418`
- Mode lock:
  - `.../remora/web/static/index.html:485` (`v6_core_peripheral`)
- Custom layout pipelines:
  - `layoutNodesV4FileWrap`: `.../index.html:1417`
  - `layoutNodesV5Component`: `.../index.html:1562`
  - `layoutNodes` dispatcher: `.../index.html:1809`
- Full graph reload pathway:
  - `loadGraph`: `.../index.html:2378`
  - `graph.clear()`: `.../index.html:2431`
- SSE behavior reloading whole graph on node discovery:
  - `evtSource.addEventListener("node_discovered"...)`: `.../index.html:3253`

Implication:
- The view is currently "graph rendered" but layout is predominantly a handcrafted scene composer.
- Whole-graph reload on discovery introduces avoidable jitter, complexity, and fragility.

### 1.3 Existing UI validation contracts
Existing checks assert that the UI is present, dependencies are local/static, and screenshot renders succeed.

Evidence:
- UI dependency check:
  - `demo/00_repo_baseline/checks/check_ui_dependencies.py`
- UI screenshot check:
  - `demo/00_repo_baseline/checks/check_ui_playwright.py`
- Shared screenshot tooling:
  - `scripts/playwright_screenshot.py`
  - `scripts/_lib/playwright_ui.py`

Implication:
- Migration must preserve these checks or update them intentionally with equivalent stronger assertions.

---

## 2. Root Cause Analysis

### 2.1 Why "organized graph" regresses
Primary causes:
1. Layout policy is overloaded.
   - Filesystem boxing, core/peripheral zoning, bridge lane placement, and occupancy normalization are all in the critical rendering path.
2. Runtime updates are expensive.
   - Discovery events trigger full reload and full re-layout.
3. Behavioral coupling is high.
   - Layout, filters, hover state, camera fitting, and side-panel actions are tightly coupled in one script.
4. Debugging surface is large.
   - Many heuristics means many edge cases.

### 2.2 What "true graph view" means here
A true graph view for this system should satisfy:
1. Node position is primarily derived from graph topology and runtime dynamics.
2. Updates are incremental (patch graph state, short reheat), not full reload by default.
3. Usability comes from interaction controls (filters, focus, pinning, neighborhood scope), not from rigid global arrangement rules.
4. Camera and node identity should remain stable enough for user mental map.

---

## 3. Target Architecture

## 3.1 High-level architecture
Recommended modules in `remora/web/static/` (or equivalent in upstream source):
- `graph-state.js`
  - canonical in-memory node/edge model
  - diff/apply semantics
- `layout-engine.js`
  - force layout lifecycle (init/reheat/settle)
  - pinning constraints for selected node
- `renderer.js`
  - Sigma setup, reducers, draw handlers
- `interactions.js`
  - selection, hover, filter, focus mode, camera controls
- `events.js`
  - SSE subscription and event-to-state mutation routing
- `panels.js`
  - side panel renderers (node details, timeline, agent stream)
- `main.js`
  - bootstrapping and wiring

If you want zero tooling, ship these as native ES modules with `<script type="module">`.

## 3.2 Layout strategy
Use graph-native force layout with deterministic seeds and controlled reheats.

Recommended behavior:
- Initial full load:
  - Apply 200-400 iterations (worker preferred).
- Incremental update:
  - Reheat 40-120 iterations.
- User interaction:
  - If node is selected and pinned, freeze selected node position during reheats.
- Camera:
  - Do not auto-fit on every mutation.
  - Fit only on first load, explicit reset button, or when graph cardinality jumps significantly.

## 3.3 Interaction strategy for usability
To replace "organized" scaffolding, invest in explicit controls:
- Focus mode:
  - show selected node + N-hop neighborhood
- Semantic filters:
  - by node type, edge type, cross-file edges
- Search/jump:
  - locate node by id/name and center camera
- Pinning:
  - user can pin/unpin selected node
- Edge thinning:
  - hide low-signal edge categories by default when graph is dense

---

## 4. Source-of-Truth and Repo Workflow

Because UI is served from installed `remora`, implement in upstream `remora-v2` and consume from this repo.

## 4.1 Recommended development wiring
In `remora-test/pyproject.toml`, `tool.uv.sources` currently pins remora from git tag `v0.7.9`.

Suggested local-dev workflow:
1. Clone `remora-v2` adjacent to this repo.
2. Temporarily switch source in `remora-test/pyproject.toml`:
   - from git tag to local path source
3. Sync environment.
4. Implement in upstream remora source.
5. Validate from `remora-test` checks.
6. Upstream commit/tag.
7. Re-pin this demo repo to new tag/rev.

Suggested temporary source override:
- `remora = { path = "../remora-v2", editable = true }`

When done:
- restore git source with new tag/rev
- refresh lockfile

---

## 5. Detailed Step-by-Step Implementation Plan

This section is intentionally granular. Execute phases in order.

## Phase 0 - Baseline capture and guardrails
Goal:
- Establish measurable "before" behavior and artifacts.

Steps:
1. Capture current screenshot and check summary.
2. Record node/edge counts from `/api/nodes` and `/api/edges`.
3. Save baseline artifacts path under `demo/00_repo_baseline/artifacts/ui_screenshots/`.

Commands (from `remora-test`):
```bash
devenv shell -- python scripts/democtl.py verify --demo 00_repo_baseline --filter check_runtime --filter check_relationships --filter check_ui_playwright
```

Exit criteria:
- All three checks pass.
- Baseline screenshot file exists and is non-empty.

## Phase 1 - Decompose monolithic UI script
Goal:
- Separate concerns before changing behavior.

Files (upstream `remora-v2`):
- `remora/web/static/index.html`
- add module files listed in Section 3.1

Steps:
1. Keep existing behavior, but move code blocks into modules without logic changes.
2. Keep globally equivalent initialization order.
3. Add a thin compatibility layer so existing CSS/DOM ids continue to work.

Important:
- This phase is pure refactor. Do not switch layout yet.

Exit criteria:
- Visual output and checks unchanged.
- No references to removed global symbols from inline script.

## Phase 2 - Introduce graph-state diff engine
Goal:
- Stop full graph teardown during normal updates.

Design:
- Maintain maps:
  - `nodesById`
  - `edgesByKey` (stable key: `${from}|${type}|${to}` or backend edge id if available)
- Provide operations:
  - `upsertNode(node)`
  - `upsertEdge(edge)`
  - `removeNode(nodeId)`
  - `removeEdge(edgeKey)`
  - `applySnapshot(nodes, edges)`

Steps:
1. Replace direct `graph.clear()` full replacement path with diff apply.
2. Keep a fallback full snapshot path for rare resync events.
3. Ensure reducers and selection state survive incremental changes.

Current code to replace behaviorally:
- `graph.clear()` in `loadGraph` around `index.html:2431`.
- `node_discovered` handler triggering `loadGraph()` around `index.html:3253-3258`.

Exit criteria:
- `node_discovered` no longer always triggers full snapshot reload.
- Selected node remains selected across incremental additions.

## Phase 3 - Add force layout runtime
Goal:
- Move from deterministic scene composition to graph-driven placement.

Dependency options:
1. Preferred: package `graphology-layout-forceatlas2` into `/static/vendor/*`.
2. Alternative: use another graphology-compatible force layout package with similar API.

Required check update:
- Expand expected vendor list in `check_ui_dependencies.py` if new vendor file is added.

Suggested API for layout engine:
- `initializeLayout(graph, { seed })`
- `runInitialLayout({ iterations })`
- `reheatLayout({ iterations, reason })`
- `setPinnedNode(nodeId | null)`
- `disposeLayout()`

Algorithm policy:
- Initial load: more iterations
- Incremental updates: fewer iterations
- Dense graph: reduce per-tick budget and label rendering threshold for performance

Exit criteria:
- Layout functions `layoutNodesV4FileWrap/V5Component` are no longer used for primary positioning.
- Node placement visibly reflects edge topology.

## Phase 4 - Preserve usability via interaction, not hardcoded arrangement
Goal:
- Keep graph readable without deterministic filesystem boxes.

Steps:
1. Add focus mode toggle.
   - full graph
   - 1-hop neighborhood
   - 2-hop neighborhood
2. Add quick isolate controls:
   - node type subsets
   - edge type subsets
   - cross-file emphasis
3. Add pin/unpin selected node action.
4. Keep zoom controls and reset fit behavior.

Notes:
- You can keep current filters (`applyFilters`) but decouple from layout assumptions.

Exit criteria:
- Users can isolate signal quickly without depending on custom zoned layout.

## Phase 5 - Event reconciliation strategy
Goal:
- Turn SSE into incremental state mutations.

Event mapping strategy:
- `node_discovered`: upsert node and fetch or infer connected edges
- `node_removed`: drop node and incident edges
- `node_changed`: patch node attributes only
- `agent_start/complete/error`: status/color patch only

Fallback resync triggers:
- unknown event schema
- edge inconsistency detected
- periodic drift correction timer (optional)

Implementation detail:
- Add small event queue to batch bursts (for example, flush every 50-100ms).

Exit criteria:
- SSE traffic no longer causes repeated full snapshot/layout cycles.
- Interaction remains responsive during event bursts.

## Phase 6 - Camera and mental-map stabilization
Goal:
- Prevent "jumping" and preserve user orientation.

Rules:
1. Auto-fit only on first load.
2. Preserve camera on incremental updates.
3. If selected node exists, keep it on-screen after updates.
4. If selected node disappears, clear selection and show non-blocking notice.

Exit criteria:
- No surprise camera resets during routine events.

## Phase 7 - Remove obsolete deterministic layout code
Goal:
- Reduce complexity and future regression surface.

Remove or retire:
- `LAYOUT` mega-constant that exists only for old deterministic placement.
- V4/V5 custom placement pipelines.
- directory bounding-box draw logic if it no longer serves focus UX.
- zone separator logic tied to core/peripheral partitioning.

Keep if still useful:
- node/edge style reducers
- hover/selection reducers
- panel rendering helpers

Exit criteria:
- Primary layout codepath is force-based and materially simpler.

## Phase 8 - Validation hardening
Goal:
- Ensure behavior is testable and stable.

### 8.1 Existing checks to run
```bash
devenv shell -- python demo/00_repo_baseline/checks/runner.py \
  --base http://127.0.0.1:8080 \
  --project-root . \
  --config-path demo/00_repo_baseline/config/remora.yaml \
  --filter check_ui_dependencies \
  --filter check_ui_playwright
```

### 8.2 Full quick suite used in practice
```bash
devenv shell -- python scripts/democtl.py verify --demo 00_repo_baseline \
  --filter check_runtime \
  --filter check_relationships \
  --filter check_ui_playwright
```

### 8.3 New checks to add (recommended)
1. `check_ui_incremental_updates.py`
   - trigger event-producing action
   - assert UI does not rebuild full graph state each event (exposed metric or debug counter)
2. `check_ui_focus_mode.py`
   - verify focus toggle changes visible node count as expected
3. `check_ui_layout_stability.py`
   - after small update burst, verify selected node remains near viewport center (within tolerance)

Exit criteria:
- Baseline checks pass.
- New incremental/focus checks pass.

## Phase 9 - Rollout, fallback, and cleanup
Goal:
- Deploy safely with reversible switch.

Steps:
1. Add a temporary runtime flag:
   - `?layout_mode=legacy|graph`
   - default to `legacy` for one short cycle if needed
2. Dogfood `graph` mode in demo runs.
3. Flip default to `graph` after confidence.
4. Remove `legacy` mode after one or two release cycles.

Exit criteria:
- Graph mode is default and stable.
- Legacy mode removed with no regression.

---

## 6. Concrete File Change Map

## 6.1 Upstream `remora-v2` changes
Likely touched files:
- `remora/web/static/index.html` (bootstrap + DOM shell)
- `remora/web/static/vendor/*` (new force-layout vendor asset if used)
- New module files under `remora/web/static/` (if splitting script)

Potentially touched server file only if needed:
- `remora/web/server.py` (only if asset path strategy changes; avoid unless necessary)

## 6.2 `remora-test` changes
Likely touched files:
- `pyproject.toml` (temporary path source for local upstream development)
- `uv.lock` (if source changes)
- `demo/00_repo_baseline/checks/check_ui_dependencies.py` (if vendor list changes)
- New UI checks under `demo/00_repo_baseline/checks/` (recommended)

---

## 7. Implementation Notes and Gotchas

1. Do not treat `.devenv/.../site-packages` as canonical source.
2. Keep `/static/vendor/*` local; do not regress to CDN.
3. Keep screenshot selector contract stable:
   - screenshot tool waits for `#graph canvas` by default.
4. Preserve API compatibility:
   - `/api/nodes`, `/api/edges`, `/sse`, `/api/chat`, proposal endpoints.
5. If adding worker-based layout, ensure worker asset path resolves under static mount.
6. If labels are expensive at high node count, add dynamic label thresholds.

---

## 8. Suggested Engineering Standards for this Refactor

Use these non-negotiable standards:
1. Every phase ends with passing checks and a screenshot artifact.
2. No large behavioral jump without an explicit fallback mode.
3. No silent full-graph refresh in hot event paths.
4. No hidden camera reset on routine updates.
5. Keep graph interactions deterministic enough for demos:
   - seeded initialization
   - controlled reheats

---

## 9. Definition of Done

The migration is complete when all are true:
1. Layout is graph-native (force-driven), not the current deterministic arrangement pipeline.
2. SSE updates mutate graph incrementally in most cases.
3. Focus/filter/pinning controls provide practical readability for dense graphs.
4. UI checks pass, including Playwright screenshot.
5. Vendor dependency check passes with updated expected local assets.
6. Source-of-truth implementation exists in upstream `remora-v2`, and this repo is pinned to that revision/tag.

---

## 10. Execution Checklist

Use this as a working checklist.

- [ ] Capture baseline screenshot and check outputs.
- [ ] Switch `remora` dependency to local upstream source for development.
- [ ] Split monolithic script into modules with no behavior changes.
- [ ] Add graph-state diff engine.
- [ ] Replace full snapshot updates on `node_discovered` with incremental upsert path.
- [ ] Add force layout engine and tune initial/reheat iteration policy.
- [ ] Implement focus mode and pinning controls.
- [ ] Stabilize camera behavior.
- [ ] Remove obsolete deterministic layout code.
- [ ] Update `check_ui_dependencies.py` if vendor set changes.
- [ ] Add incremental/focus/layout stability checks.
- [ ] Run verify/check commands and capture post-change screenshot.
- [ ] Upstream commit/tag and repin `remora-test` dependency.

---

## 11. Practical Command Appendix

### Check installed remora static source location
```bash
devenv shell -- python -c "import remora, pathlib; print(pathlib.Path(remora.__file__).resolve().parent / 'web' / 'static' / 'index.html')"
```

### Quick UI screenshot
```bash
devenv shell -- python scripts/playwright_screenshot.py \
  --url http://127.0.0.1:8080/ \
  --project-root . \
  --config-path demo/00_repo_baseline/config/remora.yaml \
  --json
```

### UI-only demo checks
```bash
devenv shell -- python demo/00_repo_baseline/checks/runner.py \
  --base http://127.0.0.1:8080 \
  --project-root . \
  --config-path demo/00_repo_baseline/config/remora.yaml \
  --filter check_ui_dependencies \
  --filter check_ui_playwright
```

### Quick mixed checks used in current workflow
```bash
devenv shell -- python scripts/democtl.py verify --demo 00_repo_baseline \
  --filter check_runtime \
  --filter check_relationships \
  --filter check_ui_playwright
```

---

## 12. Migration Risk Register

Risk: force layout introduces nondeterministic screenshots.
- Mitigation: deterministic seed + fixed initial iterations for screenshot path.

Risk: event bursts overload layout updates.
- Mitigation: event batching queue and capped reheat budgets.

Risk: loss of readability after removing organized zones.
- Mitigation: focus mode, edge filters, pinning, and neighborhood-only rendering options.

Risk: dependency drift between `remora-v2` and `remora-test`.
- Mitigation: explicit tag/rev pin update as final rollout step.

---

## 13. Final Recommendation

Implement this migration in two merged milestones:
1. Architecture milestone:
   - script decomposition + incremental state + compatibility mode
2. Behavior milestone:
   - force layout default + interaction-driven readability + cleanup

This sequencing minimizes breakage while moving decisively away from the fragile deterministic layout model.
