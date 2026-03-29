# REV_V4 — Graph View Ultra-Spread Legibility Plan

Date: 2026-03-29
Screenshot reference: `.scratch/projects/66-graph-ui-refactor/ui-playwright-20260329-155744-732.png`

## 1. Scope (Strict)

This revision is **graph canvas only**.

In scope:
- node layout and spacing
- label placement/suppression behavior on graph canvas
- edge readability and crossing management
- graph occupancy across safe drawable area
- default graph camera framing (zoom-out at first paint)

Out of scope:
- sidebar/chat/events/timeline
- non-graph workflow controls
- backend/runtime features unrelated to graph rendering

## 2. Desired Outcome

- Maximum legibility with minimum overlap at first paint.
- Core semantic clusters must not remain visually compressed.
- Canvas utilization should be near-maximal while preserving control-overlay safety.
- Label readability should improve, not regress, as spread increases.

## 3. Current Issues Against Goal

### Issue A — Core label stacking still exists in left-mid cluster
What is visible:
- `OrderSummary` and repeated `OrderRequest` labels still collide/stack around the same horizontal zone.

Why this fails goal:
- Central identity anchors remain ambiguous.
- Overlap is reduced from earlier revisions but not eliminated.

### Issue B — Cluster remains center-left compressed despite free surrounding space
What is visible:
- Critical nodes (`create_order`, `compute_total`, `services`, related model nodes) still form a compact knot while large outer regions stay sparse.

Why this fails goal:
- Spread is still not aggressive enough.
- Layout is not maximizing the available safe area.

### Issue C — Crossing corridor still concentrated through the core
What is visible:
- Multiple long edges converge through a few central lanes.

Why this fails goal:
- Topology tracing remains harder than necessary.
- Crossing density in the core still degrades readability.

### Issue D — Label starvation in peripheral nodes
What is visible:
- Several visible nodes render as unlabeled dots in expanded regions.

Why this fails goal:
- Legibility is not just overlap reduction; users still need identity visibility.
- Current suppression is too aggressive for some non-colliding outer nodes.

### Issue E — Expansion is uneven (local over-density + global under-fill)
What is visible:
- Some regions are very sparse while local dense pockets still violate comfortable spacing.

Why this fails goal:
- We need stricter spacing floors and more uniform occupancy pressure.

## 4. REV_V4 Fix Plan (Max Expansion)

## Phase 1: Ultra-spread normalization targets

Implementation:
- Increase spread normalization envelope to target **92–98%** safe drawable occupancy.
- Add secondary expansion pass after exclusion-zone resolution to prevent recoil toward center.
- Increase initial force runtime and cooling persistence so expansion fully converges.
- Apply a default camera zoom-out at first paint so more of the spread graph is visible without manual interaction.

Expected result:
- Graph uses nearly all safe canvas area.
- Center compression is dramatically reduced.

Primary files:
- `src/remora/web/static/layout-engine.js`
- `src/remora/web/static/main.js`
- `src/remora/web/static/renderer.js`

## Phase 2: Hard no-overlap local solver

Implementation:
- Add strict local collision phase that continues until overlap budget is near-zero or round cap reached.
- Raise dense-cell nearest-neighbor floor substantially (aggressive minimum spacing in crowded buckets).
- Apply degree-aware spacing multipliers with stronger hub penalties.

Expected result:
- Residual label/node pileups in core are eliminated.

Primary files:
- `src/remora/web/static/layout-engine.js`

## Phase 3: Label visibility rebalance (less overlap, more identity)

Implementation:
- Keep strict suppression in dense center, but relax suppression for low-collision peripheral bands.
- Guarantee a minimum visible label budget per quadrant so outer nodes are not anonymous dots.
- Increase vertical staggering for repeated long labels (`Order*` family) to avoid same-lane stacking.

Expected result:
- Fewer central collisions without losing peripheral identity.

Primary files:
- `src/remora/web/static/renderer.js`
- `src/remora/web/static/layout-engine.js`

## Phase 4: Crossing deflection reinforcement

Implementation:
- Expand hub ring radii further and increase angular gap floor.
- Add crossing-deflection pass that pushes near-collinear edge corridors apart in hub neighborhoods.
- Increase low-signal edge deemphasis under high crossing density.

Expected result:
- Cleaner core lanes and more traceable dependency paths.

Primary files:
- `src/remora/web/static/layout-engine.js`
- `src/remora/web/static/renderer.js`

## Phase 5: Safe-area occupancy shaping

Implementation:
- Strengthen top-left exclusion zone and add soft target zones for underused safe regions.
- Introduce occupancy balancing by angular sectors to reduce hot-spot clustering.
- Increase safe drawable area by tuning overlay exclusion margins/padding to be protective but not overly conservative.

Expected result:
- More uniform spread, less local crowding, better global balance.

Primary files:
- `src/remora/web/static/layout-engine.js`
- `src/remora/web/static/main.js`

## 5. Validation Criteria (Graph-Only)

A build is acceptable only if all are true:

1. Overlap and spacing
- Central label overlap pair ratio reduced by >= 70% from this screenshot baseline.
- Dense-cluster nearest-neighbor floor reaches the new aggressive threshold.

2. Spread utilization
- Graph safe-area occupancy reaches target envelope (92–98% in spread metrics).
- No dominant center-left knot remains.

3. Label legibility quality
- Critical center labels are non-overlapping.
- Peripheral unlabeled-dot rate decreases materially (identity visibility improved).

4. Crossing readability
- Central crossing density decreases relative to this baseline.
- High-signal paths remain easy to follow.

5. Stability
- Selection/hitbox and focus interactions remain reliable under ultra-spread layout.

## 6. Execution Checklist

- [ ] Raise normalization and force settings to ultra-spread targets.
- [ ] Add hard no-overlap local solver with aggressive spacing floors.
- [ ] Rebalance label suppression to preserve peripheral identity.
- [ ] Reinforce hub crossing deflection and low-signal deemphasis.
- [ ] Add occupancy-sector shaping for uniform safe-area fill.
- [ ] Apply default camera zoom-out so expanded layout is visible at first paint.
- [ ] Update acceptance checks for REV_V4 aggressive thresholds.
- [ ] Capture post-REV_V4 screenshot and compare to this baseline.
