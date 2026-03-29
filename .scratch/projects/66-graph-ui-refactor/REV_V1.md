# REV_V1 — Web UI Remediation Plan (Latest Screenshot)

Date: 2026-03-29
Screenshot reference: `.scratch/projects/66-graph-ui-refactor/ui-playwright-20260329-130146-010.png`

## 1. Goal Alignment Baseline

Desired web UI outcome:
- Graph is legible at runtime density.
- Topology is understandable quickly without manual micromanagement.
- Updates remain incremental and stable.
- Interactions (focus/filter/pin/search/select) reduce complexity, not add it.
- Sidebar actively supports workflow, not only passive display.

Assumption for this revision:
- Previous REV work is not fully landed yet (as noted), so this plan is written as a direct execution target from current screenshot state.

## 2. Issues Against Desired Goal

### Issue A — Core cluster is still too dense
What is visible:
- Central region around `create_order`, `compute_total`, `apply_tax`, `OrderSummary`, `OrderRequest` still has heavy node/edge congestion.

Why this is a goal mismatch:
- Dense overlap prevents quick topology comprehension.
- Graph should prioritize immediate readability.

Impact:
- Hard to trace causal flow across imports/contains edges.
- Label-hit precision and visual scanning quality drop.

### Issue B — Labels collide and stack in the same area
What is visible:
- Long labels overlap in center-left and center; repeated model/class labels crowd the same horizontal band.

Why this is a goal mismatch:
- Labels are primary anchors for understanding node identity.
- Overlap destroys identity clarity.

Impact:
- Users cannot rapidly distinguish similarly named nodes.

### Issue C — Edge clutter remains high (especially low-signal edges)
What is visible:
- Many `contains` connections are shown with high frequency in dense regions.

Why this is a goal mismatch:
- Low-signal edge classes should be thinned by default under density.
- High-signal relations should visually dominate.

Impact:
- Important cross-file/import paths get buried in structural noise.

### Issue D — Space utilization is unbalanced
What is visible:
- Graph occupies a tight center-left mass while substantial right/lower graph area is under-used.

Why this is a goal mismatch:
- The layout should spread nodes to maximize legibility and use available canvas.

Impact:
- Congestion persists despite available viewport capacity.

### Issue E — Sidebar remains low-information at first load
What is visible:
- “Select a node” empty state with little immediate guidance.

Why this is a goal mismatch:
- Sidebar should help users take the next step and understand current graph state.

Impact:
- Poor onboarding at first paint; interaction path is not obvious.

## 3. REV_V1 Fix Plan

## Phase 1: Aggressive anti-overlap layout policy

Implementation:
- Increase minimum target node spacing based on:
  - label width estimate,
  - node type class (class/function/method/virtual),
  - local degree.
- Run iterative post-force collision resolution until overlap budget is met.
- Add viewport-space spread normalization:
  - scale and distribute clusters to use 70–85% of drawable graph area.

Expected result:
- Center cluster expands; node-label collisions drop significantly.

## Phase 2: Label decluttering and priority rendering

Implementation:
- Label priority tiers:
  - Tier 1: selected node, hovered node, pinned node.
  - Tier 2: 1-hop neighbors of selected node.
  - Tier 3: high-centrality nodes.
  - Tier 4: all others (subject to suppression).
- Suppress lower-priority labels when rectangle overlap exceeds threshold.
- Use compact labels in-canvas, full name in sidebar/details.

Expected result:
- Text remains readable without sacrificing selection usability.

## Phase 3: Edge signal hierarchy and default thinning

Implementation:
- Default visibility policy by density:
  - Keep `imports`, `inherits`, cross-file edges fully visible.
  - Downweight/hide `contains` when edge count exceeds threshold.
- Edge opacity/width hierarchy:
  - high-signal edges thicker and brighter,
  - low-signal edges thinner and muted.
- Edge labels only for selected/hovered/emphasized edges.

Expected result:
- Structural noise reduced; meaningful dependency paths stand out.

## Phase 4: Interaction-driven clarity defaults

Implementation:
- Keep `full` mode initially, but after first node selection:
  - automatically switch to `1-hop` focus (with clear chip state update).
- Keep explicit quick action to restore full graph.
- Pin toggle should visibly lock selected node and preserve nearby layout.

Expected result:
- One click transforms noisy global view into readable local context.

## Phase 5: Sidebar usability upgrade

Implementation:
- Add empty-state helper block:
  - “Search or click a node to focus graph.”
- Add live graph summary:
  - visible nodes, visible edges, hidden-by-thinning count, active focus mode.
- Add selected-node quick actions:
  - pin/unpin,
  - focus 1-hop,
  - focus 2-hop,
  - reset focus.

Expected result:
- Sidebar becomes an active control panel for graph exploration.

## 4. File-Level Change Map

Primary targets:
- `src/remora/web/static/layout-engine.js`
  - spacing heuristics, post-force collision solver, viewport spread normalization.
- `src/remora/web/static/renderer.js`
  - label-priority rendering and overlap suppression.
- `src/remora/web/static/interactions.js`
  - density-aware edge thinning defaults, first-selection focus transition.
- `src/remora/web/static/main.js`
  - runtime readability metrics, focus-mode transition orchestration.
- `src/remora/web/static/panels.js`
  - empty-state guidance + graph summary + quick actions.
- `src/remora/web/static/index.html`
  - sidebar sections for summary and quick actions.

## 5. Validation Criteria

A change set is acceptable only if all are true:

1. Overlap metrics
- Label overlap ratio in dense center region reduced by >= 50% from current baseline.
- Node minimum pixel separation floor maintained in steady state.

2. Readability metrics
- High-signal edge visibility remains high while low-signal edge count drops under density.
- Median label legibility score improves (no major clipping/collision in central cluster).

3. Interaction behavior
- Node click and label hitbox selection remain reliable.
- First selection transitions to `1-hop` focus correctly.
- Incremental SSE updates preserve camera stability and do not force routine full reload.

4. Workflow UX
- Sidebar shows actionable guidance before selection.
- Selected-node action row works and reflects current state.

## 6. Execution Checklist

- [ ] Implement aggressive spacing + collision resolution in layout engine.
- [ ] Add viewport spread normalization after settle.
- [ ] Add label priority and overlap suppression in renderer.
- [ ] Add density-aware default thinning for low-signal edges.
- [ ] Add first-selection auto-focus behavior.
- [ ] Add sidebar summary and quick actions.
- [ ] Update acceptance checks for overlap/readability targets.
- [ ] Capture new screenshot and compare against this baseline.
