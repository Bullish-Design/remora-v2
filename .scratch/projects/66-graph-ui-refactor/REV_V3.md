# REV_V3 — Graph View Maximum Expansion Plan

Date: 2026-03-29
Screenshot reference: `.scratch/projects/66-graph-ui-refactor/ui-playwright-20260329-135330-701.png`

## 1. Scope (Strict)

This revision is **graph-canvas only**.

In scope:
- node placement and spacing
- node label placement and suppression rules
- edge visibility/geometry for readability
- graph occupancy and spread across available canvas

Out of scope:
- sidebar/panel UX
- events/timeline/chat
- non-graph workflows

## 2. Goal Alignment Baseline

Desired graph goal:
- Maximum legibility with minimum overlap.
- Graph should be aggressively spread so dense semantic cores are no longer compact knots.
- Readability should be immediate at first paint with minimal manual zoom/pan.

## 3. Current Issues Against Goal

### Issue A — Core semantic cluster is still too tight
What is visible:
- The center group (`create_order`, `compute_total`, `OrderSummary`, `OrderRequest`, `services`, `src`) is still concentrated in a narrow area.

Why this fails goal:
- Main flow nodes still compete for space.
- Expansion is improved but not aggressive enough.

### Issue B — Label collisions still occur in central lanes
What is visible:
- Mid-band labels overlap or sit nearly touching (`OrderSummary`, `create_order`, `compute_total`, `OrderRequest`).

Why this fails goal:
- Node identity is still not cleanly separable in the most important area.

### Issue C — Crossing concentration remains high near hubs
What is visible:
- Many edges still intersect around one central corridor, especially between function/class core and section/topic nodes.

Why this fails goal:
- Path tracing remains visually ambiguous in the highest-density zone.

### Issue D — Canvas occupancy is under-maximized
What is visible:
- Significant free space remains in outer regions while the center remains dense.

Why this fails goal:
- We are not using available area aggressively enough.

### Issue E — Local node-to-node clearance is inconsistent
What is visible:
- Some nodes are widely separated while nearby central nodes are nearly stacked.

Why this fails goal:
- Readability needs stronger minimum spacing floors in dense neighborhoods.

## 4. REV_V3 Fix Plan (Aggressive Spread)

## Phase 1: Extreme global spread targets

Implementation:
- Raise post-layout spread target to occupy ~88–94% of drawable graph area.
- Increase force repulsion and max step during initial settle.
- Run additional settle/relax rounds until overlap budget is near-zero.

Expected result:
- Immediate global expansion with less center compression.

Primary files:
- `src/remora/web/static/layout-engine.js`

## Phase 2: Hard local spacing floors (dense-cluster breaker)

Implementation:
- Increase dense-cell expansion strength and passes (more push, more iterations).
- Apply degree-weighted spacing floors so hub neighborhoods get extra clearance.
- Enforce a strict minimum nearest-neighbor distance in crowded cells.

Expected result:
- Central cluster visibly opens; short-distance collisions are eliminated.

Primary files:
- `src/remora/web/static/layout-engine.js`

## Phase 3: Label-first geometry constraints

Implementation:
- Increase label footprint contribution in spacing (treat labels as primary collision boxes).
- Add stricter overlap suppression thresholds for medium/low priority labels.
- Expand vertical label offsets where dense horizontal bands are detected.

Expected result:
- Central label stacking is strongly reduced.

Primary files:
- `src/remora/web/static/layout-engine.js`
- `src/remora/web/static/renderer.js`

## Phase 4: Crossing minimization reinforcement

Implementation:
- Increase hub-neighbor angular spread arc and ring separation.
- Add one extra post-hub deconfliction pass to reduce corridor crossings.
- Keep high-signal edges visually dominant while dimming low-signal line clutter.

Expected result:
- Fewer center-lane crossings and cleaner topology reading.

Primary files:
- `src/remora/web/static/layout-engine.js`
- `src/remora/web/static/renderer.js`

## Phase 5: Overlay exclusion hardening + boundary shaping

Implementation:
- Expand exclusion zone padding around top-left controls to prevent label creep.
- Add soft boundary shaping so expanded graph uses all available safe areas, not just center.

Expected result:
- Better use of open canvas while preserving control-legibility separation.

Primary files:
- `src/remora/web/static/layout-engine.js`
- `src/remora/web/static/main.js`

## 5. Validation Criteria (Graph-Only, Aggressive)

A build is acceptable only if all are true:

1. Overlap/spacing
- Node-label overlap pair ratio in baseline dense cluster reduced by >= 60% from current screenshot.
- Central-cluster nearest-neighbor floor improved to a consistently readable threshold.

2. Spread utilization
- Visible graph occupies >= 88% of target drawable area envelope.
- No dominant center knot remains.

3. Crossing clarity
- Central crossing density decreases measurably from current screenshot baseline.
- High-signal paths are traceable without visual line pileups.

4. Stability
- Selection/hitbox behavior remains reliable after aggressive spread.
- Incremental updates preserve legibility without immediate re-collapse.

## 6. Execution Checklist

- [ ] Increase global spread normalization targets and force strength.
- [ ] Increase dense-cell expansion intensity/passes and enforce hard local spacing floors.
- [ ] Tighten label-first collision and suppression policies.
- [ ] Increase hub angular/ring distribution and add post-hub deconfliction.
- [ ] Harden exclusion zones and boundary shaping to use full safe canvas.
- [ ] Update acceptance checks for aggressive spread + overlap reduction targets.
- [ ] Capture post-REV_V3 screenshot and compare to this baseline.
