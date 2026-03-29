# REV_V2 — Graph View Legibility Remediation Plan

Date: 2026-03-29
Screenshot reference: `.scratch/projects/66-graph-ui-refactor/ui-playwright-20260329-133345-256.png`

## 1. Scope (Strict)

This revision is **graph-view only**.

In scope:
- node positions
- node label rendering
- edge rendering / edge labels
- graph-space utilization
- graph overlay collision with graph content

Out of scope:
- sidebar content
- timeline/events/chat UX
- non-graph workflow panels

## 2. Goal Alignment Baseline

Desired graph-view outcome:
- At first paint, the graph is readable without manual micromanagement.
- Node identity is quickly scannable (labels do not stack/overlap heavily).
- Edge structure is understandable (signal emphasized, noise suppressed).
- Density is distributed across available graph space (no tight unreadable knot).

## 3. Current Graph-View Issues (From Latest Screenshot)

### Issue A — Dense center-left knot still causes node/label overlap
What is visible:
- `OrderSummary`, multiple `OrderRequest` variants, `create_order`, `apply_tax`, `services`, and nearby nodes still occupy a tight overlapping band.

Why this fails the goal:
- The main task-critical cluster remains the least readable area.
- Users still need visual parsing effort to distinguish adjacent nodes.

### Issue B — Long labels compete in same horizontal corridors
What is visible:
- Long labels (especially yellow topic nodes and repeated model/class labels) overlap or nearly overlap around the center and upper-center lanes.

Why this fails the goal:
- Long labels dominate nearby space and compress local neighborhoods.
- Identity clarity drops where labels should be strongest.

### Issue C — Edge labels are still visually noisy in dense regions
What is visible:
- Frequent `contains`/`imports` labels stack along crossing lines in the cluster core.

Why this fails the goal:
- Relationship text competes with node names.
- Core topology gets harder to trace because text overlays text.

### Issue D — Crossings remain high through a few hub corridors
What is visible:
- Many links converge around the center, producing repeated line intersections and ambiguous path tracing.

Why this fails the goal:
- Crossing-heavy bundles reduce directional comprehension.
- Important dependencies are not visually separable from structural background links.

### Issue E — Graph usable area is still underutilized relative to density
What is visible:
- Some outer nodes are sparse while the primary semantic subgraph remains tightly packed.

Why this fails the goal:
- Global spread exists, but local spread where needed is insufficient.
- Layout is not density-balanced.

## 4. REV_V2 Fix Plan (Graph-Only)

## Phase 1: Local-density expansion (primary overlap fix)

Implementation:
- Add a post-layout **density expansion pass**:
  - detect high-density cells (node count + average neighbor distance threshold),
  - apply outward displacement vectors from local centroid,
  - re-run short constrained relaxation.
- Increase minimum separation floor in dense cells by label footprint, not node radius only.

Expected result:
- The center-left knot opens up significantly.
- Neighboring labels gain stable separation.

Primary files:
- `src/remora/web/static/layout-engine.js`

## Phase 2: Label-box-aware collision model

Implementation:
- Upgrade spacing model to use approximate label rectangle footprint:
  - width from text length + font tier,
  - height by label tier.
- During collision resolution, use anisotropic separation (x/y) based on label box intersection, not radial-only distance.

Expected result:
- Horizontal label band collisions drop sharply.
- Long labels stop crushing local node neighborhoods.

Primary files:
- `src/remora/web/static/layout-engine.js`
- `src/remora/web/static/renderer.js`

## Phase 3: Edge-label austerity policy

Implementation:
- Disable edge labels by default in full view.
- Show edge labels only when one of the following is true:
  - edge incident to selected/hovered node,
  - edge is part of active focus subgraph (1-hop/2-hop),
  - edge type is high-signal and currently emphasized.
- Keep `contains` labels hidden by default at medium/high density.

Expected result:
- Text clutter shifts from edges back to nodes.
- Relationship reading becomes intentional instead of always-on noise.

Primary files:
- `src/remora/web/static/renderer.js`
- `src/remora/web/static/interactions.js`

## Phase 4: Crossing reduction in hub regions

Implementation:
- Add lightweight hub-aware ordering:
  - for nodes attached to same hub, sort by angle and distribute on ring slices,
  - reduce edge overlap lanes by angular spacing.
- For multi-edge corridors, switch to subtle curvature offsets instead of identical straight lines.

Expected result:
- Fewer ambiguous crossings around central hubs.
- Better path traceability.

Primary files:
- `src/remora/web/static/layout-engine.js`
- `src/remora/web/static/main.js` (edge style attrs if needed)

## Phase 5: Graph-overlay exclusion zone

Implementation:
- Reserve a no-layout zone under the top-left graph controls overlay (filter/search panel).
- During final settle, repel nodes/labels from this zone.

Expected result:
- Top-left node/label collisions with control overlay are eliminated.
- Effective visible graph area improves.

Primary files:
- `src/remora/web/static/layout-engine.js`
- `src/remora/web/static/renderer.js`

## 5. Validation Criteria (Graph-Only)

A change set is acceptable only if all are true:

1. Overlap reduction
- Node-label overlap pair ratio reduced by >= 50% from this screenshot baseline.
- Dense-cluster minimum nearest-neighbor distance exceeds configured floor.

2. Label readability
- In the central dense cluster, no major stacked text bands remain.
- Long labels no longer collide with adjacent long labels in steady state.

3. Edge readability
- Edge label count in full mode is substantially reduced.
- High-signal edges remain visually identifiable without text overload.

4. Spatial utilization
- Local density variance decreases (no single dominant unreadable knot).
- Graph cluster expands to use available drawable area more evenly.

## 6. Execution Checklist

- [ ] Implement local-density expansion pass in layout engine.
- [ ] Implement label-box-aware anisotropic collision separation.
- [ ] Implement edge-label austerity defaults and conditional reveal.
- [ ] Implement hub crossing reduction strategy.
- [ ] Add top-left overlay exclusion zone for graph layout.
- [ ] Add/adjust acceptance checks for overlap and label clutter metrics.
- [ ] Capture post-REV_V2 screenshot and compare against this baseline.
