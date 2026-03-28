# Concept: Graph View Overhaul (v4)

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Screenshot Diff: What Changed and What Failed](#2-screenshot-diff-what-changed-and-what-failed)
3. [Current Problems (Observed in v0.7.3 Screenshot)](#3-current-problems-observed-in-v073-screenshot)
4. [Root Causes in Current Implementation](#4-root-causes-in-current-implementation)
5. [V4 Design Goals](#5-v4-design-goals)
6. [V4 Layout Model](#6-v4-layout-model)
7. [V4 Edge and Box Rendering](#7-v4-edge-and-box-rendering)
8. [V4 Camera and Fit Strategy](#8-v4-camera-and-fit-strategy)
9. [V4 Interaction and Controls](#9-v4-interaction-and-controls)
10. [V4 Implementation Plan (Single-File Scope)](#10-v4-implementation-plan-single-file-scope)
11. [Verification and Regression Plan](#11-verification-and-regression-plan)
12. [Rollout Strategy](#12-rollout-strategy)

## 1. Executive Summary

The latest screenshot (`ui-playwright-20260328-100359-520.png`) still fails the primary demo objective: the graph is technically rendered, but functionally unreadable.

The current system remains horizontally over-compressed, vertically under-distributed, and semantically ambiguous. Compared with the earlier screenshot (`ui-playwright-20260327-221431-034.png`), there are minor spacing adjustments, but not the structural improvements needed for technical-demo legibility.

v4 should move from "single horizontal strip of file columns" to a deterministic **multi-lane, wrapped layout** with explicit spacing guarantees, plus camera fitting that protects readability rather than only maximizing inclusion.

## 2. Screenshot Diff: What Changed and What Failed

Compared images:
- Baseline in this folder: `ui-playwright-20260327-221431-034.png`
- Latest: `ui-playwright-20260328-100359-520.png`

What improved:
- Slightly more horizontal separation in the middle/right nodes.
- Better camera stability (no blank graph regression in this specific shot).

What is still broken:
- Left cluster remains heavily overlapped (labels, boxes, node borders collide).
- Graph remains concentrated into a narrow central horizontal band.
- Vertical structure is still too weak to communicate containment or code order.
- Arrow semantics are not visually obvious; edges read mostly as thin horizontal lines.
- Filesystem grouping exists but is not useful in dense zones because headers and borders stack into noise.

Conclusion:
- v3.x tuning improved mechanics but not legibility. The failure is architectural (layout model), not just constant values.

## 3. Current Problems (Observed in v0.7.3 Screenshot)

1. **One-dimensional composition**
The graph still reads as a single left-to-right stripe.

2. **Severe overlap in dense subgraphs**
Nodes in the left cluster overlap in both x and y, making labels unreadable.

3. **Weak cross-file relationship readability**
Dependencies are present but directionality and path tracing are hard to follow.

4. **Filesystem visualization lacks hierarchy clarity under load**
Bounding boxes and labels pile up near dense regions and do not guide the eye.

5. **Fit-to-view optimizes occupancy, not readability**
Camera fit prioritizes showing everything, but at a scale/layout that compresses cognition.

6. **Desired demo behavior not fully achieved**
For a technical audience “wow factor,” the graph should instantly show:
- what lives where,
- what depends on what,
- where activity is happening,
without zoom/pan/manual filtering.

## 4. Root Causes in Current Implementation

### 4.1 Single-row file-column architecture is fundamentally width-bound
Current layout logic places each file in one x-column and does not wrap columns into rows.

Relevant code:
- `layoutNodes` file grouping and `colX` accumulation in [index.html](/home/andrew/Documents/Projects/remora-v2/src/remora/web/static/index.html:675)
- x cursor increment in [index.html](/home/andrew/Documents/Projects/remora-v2/src/remora/web/static/index.html:693)

Impact:
- As file count grows, width dominates.
- Camera must zoom out to include full x-span.
- Vertical differences become visually negligible.

### 4.2 Vertical placement is local and low-dynamic-range
Y-position is derived from per-file normalized lines + small depth/stagger offsets.

Relevant code:
- y formula in [index.html](/home/andrew/Documents/Projects/remora-v2/src/remora/web/static/index.html:729)

Impact:
- File-internal ordering exists, but global vertical structure remains weak.
- Different files collapse around similar y bands.

### 4.3 Camera fit uses inclusion-only objective
`fitCameraToGraph` computes a ratio to include bounds, then centers to baseline camera state.

Relevant code:
- `computeVisualBounds` in [index.html](/home/andrew/Documents/Projects/remora-v2/src/remora/web/static/index.html:804)
- `fitCameraToGraph` in [index.html](/home/andrew/Documents/Projects/remora-v2/src/remora/web/static/index.html:836)

Impact:
- Good for “everything on screen,” poor for readability.
- Dense regions remain compressed instead of receiving space.

### 4.4 Box rendering in dense areas adds clutter
Headers and outlines render on many nested boxes simultaneously.

Relevant code:
- box drawing in `beforeRender` around [index.html](/home/andrew/Documents/Projects/remora-v2/src/remora/web/static/index.html:1206)

Impact:
- Instead of hierarchy aid, boxes become visual interference in clusters.

### 4.5 Edge styling is technically configured but perceptually weak
Even with arrow program wiring, edge direction/importance is low at current zoom and overlap state.

Relevant code:
- `EDGE_STYLES` in [index.html](/home/andrew/Documents/Projects/remora-v2/src/remora/web/static/index.html:519)
- edge reducer in [index.html](/home/andrew/Documents/Projects/remora-v2/src/remora/web/static/index.html:573)

Impact:
- Viewers cannot quickly infer dependency flow.

## 5. V4 Design Goals

1. **First-glance legibility**: no overlapping labels in default view for typical demo graphs.
2. **Deterministic placement**: same inputs produce same layout.
3. **Hierarchy clarity**: filesystem groups readable before interaction.
4. **Dependency clarity**: imports/inherits visually traceable.
5. **Readability-first camera fit**: preserve context while avoiding over-compression.
6. **Single-file implementation scope**: continue using `src/remora/web/static/index.html`.

## 6. V4 Layout Model

### 6.1 Replace single-strip columns with wrapped lanes
Keep deterministic file ordering, but place columns into **rows of lanes** based on available width estimate.

Algorithm:
1. Build deterministic sorted file columns (as today).
2. Compute each column width from max label width.
3. Pack columns into rows using first-fit deterministic packing:
   - `maxRowWidthUnits` derived from viewport width and target ratio baseline.
   - when next column would exceed row width, start a new row.
4. Assign each row a y band (row gap large enough to avoid inter-row collision).
5. Place nodes inside each column relative to row baseline.

Result:
- Wide repos become multi-row layouts instead of one ultra-wide strip.
- Camera no longer forced to extreme zoom-out.

### 6.2 Enforce hard minimum spacing guarantees
Add explicit no-overlap guardrails:
- `MIN_NODE_GAP_X_UNITS`
- `MIN_NODE_GAP_Y_UNITS`
- `MIN_COLUMN_SEPARATION_UNITS`

Run a deterministic post-pass that shifts colliding columns right and colliding rows down.

### 6.3 Improve vertical semantics
Within each column:
- preserve order by `(depth, start_line, name)`
- use stronger vertical scaling for deep trees
- reserve extra vertical space for nodes with duplicate labels/qualifiers

### 6.4 Distinguish logical sections in layout
Treat virtual/section/table nodes as a separate local band inside their file lane to reduce collisions with code symbol nodes.

## 7. V4 Edge and Box Rendering

### 7.1 Edge readability upgrades
- Increase base edge width and opacity.
- Use slight curvature for cross-file edges to reduce stacked-line ambiguity.
- Scale arrowhead size with zoom ratio (minimum visible arrowhead floor).
- Add optional “highlight cross-file edges only” mode for demos.

### 7.2 Filesystem box clutter control
- Keep boxes, but render headers conditionally:
  - hide header when box pixel width/height below threshold,
  - hide deep nested headers unless hovered/selected.
- Reduce simultaneous stroke prominence for deeply nested siblings.

### 7.3 Separation of concerns in visual channels
- Boxes encode containment.
- Edges encode semantics.
- Node labels remain always on.

No channel should obscure another in default view.

## 8. V4 Camera and Fit Strategy

### 8.1 Two-step fit policy
1. **Safety reset** to known-good camera baseline.
2. **Readability fit** with clamped zoom-out ceiling.

If computed fit would make median label width < target pixel threshold, stop zooming out and allow horizontal overflow to be solved by wrapped layout, not camera shrink.

### 8.2 Fit objective should include legibility constraints
Current objective is “include all bounds.”
V4 objective should be:
- include high-priority content,
- preserve minimum label pixel width,
- avoid clipping near sidebar,
- avoid collapsing into a strip.

### 8.3 Fallback behavior
If fit computation is invalid:
- use `animatedReset` fallback,
- emit one diagnostic event line in UI log,
- continue rendering (never blank graph).

## 9. V4 Interaction and Controls

1. Keep existing filter chips and zoom controls.
2. Add one new toggle: `layout mode` (`wrapped` / `strip`) for live comparison.
3. Add one new toggle: `edge emphasis` (`all` / `cross-file only`).
4. Keep node names always visible by default.

## 10. V4 Implementation Plan (Single-File Scope)

All changes remain in:
- `src/remora/web/static/index.html`

### Step A: Layout rewrite
- Replace current x accumulation with deterministic row-wrapping column packer.
- Add hard spacing constants.
- Add collision-avoidance post-pass.

### Step B: Camera rewrite
- Replace current fit metric with readability-constrained fit.
- Add guard for minimum label pixel size.
- Keep robust fallback to baseline reset.

### Step C: Edge rendering tuning
- Increase visibility defaults.
- Add curved edge option for cross-file edges.
- Guarantee visible arrowheads at default zoom.

### Step D: Box rendering tuning
- Header suppression for tiny/deep boxes.
- Slightly lower stroke noise in dense nested zones.

### Step E: Demo toggles
- Add lightweight toggles for `layout mode` and `edge emphasis`.

## 11. Verification and Regression Plan

### 11.1 Visual acceptance checks
1. No overlapping labels in default screenshot for demo baseline graph.
2. At least two discernible y-bands (not a single strip).
3. Right-edge labels are not clipped by sidebar.
4. Arrow direction is visible without zoom.
5. Filesystem groups are legible in dense and sparse regions.

### 11.2 Automated checks
Keep existing tests and add:
1. **Viewport presence check** (already added): if graph has nodes, at least one visible in viewport.
2. **No severe overlap check**: estimate label boxes and assert overlap ratio below threshold.
3. **Edge visibility check**: ensure non-hidden edges produce non-zero viewport span.

### 11.3 Screenshot regression set
Capture three required screenshots per change:
- default load
- zoom reset click
- after toggling `filesystem` and `cross-file only`

Store in project artifact folder with timestamps.

## 12. Rollout Strategy

1. Implement v4 layout + camera together (they are coupled).
2. Validate with acceptance + targeted screenshot review.
3. Ship behind default `wrapped` mode; keep `strip` as temporary fallback.
4. Remove `strip` mode after one release cycle if no regressions.

---

## Bottom Line

The current issues are real and expected from a single-strip architecture under dense graphs. v4 should stop tuning constants and instead adopt deterministic wrapped lanes + readability-constrained camera fitting. That is the smallest change set that materially improves legibility while preserving existing behavior and single-file scope.
