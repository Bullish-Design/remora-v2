# Concept: Graph View Overhaul (v3)

## Table of Contents

1. [What Changed from v2 to v3](#1-what-changed-from-v2-to-v3)
2. [Design Goals (Unchanged)](#2-design-goals-unchanged)
3. [Core Idea: Two Visual Channels (Unchanged)](#3-core-idea-two-visual-channels-unchanged)
4. [Deterministic Layout System (Updated)](#4-deterministic-layout-system-updated)
5. [Directory Bounding Boxes (Updated)](#5-directory-bounding-boxes-updated)
6. [Edge Rendering by Type (Updated)](#6-edge-rendering-by-type-updated)
7. [Node Visual Identity (Unchanged)](#7-node-visual-identity-unchanged)
8. [Camera Framing (New)](#8-camera-framing-new)
9. [Interaction Layer (Unchanged)](#9-interaction-layer-unchanged)
10. [Filter Controls (Unchanged)](#10-filter-controls-unchanged)
11. [Bug Fixes from v2 Implementation](#11-bug-fixes-from-v2-implementation)
12. [File Scope](#12-file-scope)
13. [Determinism Guarantee (Unchanged)](#13-determinism-guarantee-unchanged)

---

## 1. What Changed from v2 to v3

v2 was implemented and produced a screenshot with six visible problems. v3 addresses all
of them while preserving the v2 architecture (two visual channels, file-column grid,
bounding boxes, edge filtering). The changes are surgical — no new abstractions, no
restructuring.

| # | v2 Problem | v3 Fix | Section |
|---|-----------|--------|---------|
| P0 | Camera framing: all nodes crushed to bottom 20% of viewport | Replace `animatedReset()` with computed camera centering on actual data bounds | §8 |
| P0 | Horizontal overlap: labels collide due to insufficient column spacing | Increase `COL_PAD` 3.0→6.0, lower `PX_PER_UNIT` 14→10 | §4.5 |
| P1 | No visible edge arrows between nodes | Register Sigma arrow program explicitly; verify edge data exists | §6.3 |
| P1 | Bounding boxes invisible (alpha too low on dark background) | Increase fill alpha 0.03→0.07, stroke alpha 0.12→0.22 | §5.3 |
| P2 | Right-edge label clipping by sidebar | Solved by camera framing fix (§8) which includes margin | §8 |
| P2 | Flat y-axis: all nodes at same vertical position | Use `start_line` as continuous vertical offset within each file column | §4.6 |

---

## 2. Design Goals (Unchanged)

Same as v2. Primary: immediately legible graph. Secondary: deterministic layout. Single-file
change to `index.html`.

---

## 3. Core Idea: Two Visual Channels (Unchanged)

Same as v2:
- **Spatial containment** → `contains` edges → nested bounding boxes
- **Drawn arrows** → `imports` + `inherits` → colored directional arrows

---

## 4. Deterministic Layout System (Updated)

### 4.1–4.4: Unchanged from v2

The file-column grid concept, directory exclusion, and overall algorithm structure remain
the same.

### 4.5 Updated Layout Constants

The v2 constants produced columns too narrow and too close together, causing label overlap.
The root cause: `PX_PER_UNIT: 14` divided measured pixel widths too aggressively, producing
graph-unit column widths smaller than the rendered labels. Combined with `COL_PAD: 3.0`,
adjacent columns overlapped.

**v3 constants:**

```javascript
const LAYOUT = Object.freeze({
  COL_PAD:        6.0,   // was 3.0 — doubled to eliminate label overlap
  ROW_HEIGHT:     2.2,   // unchanged
  SUB_ROW_HEIGHT: 1.6,   // unchanged
  MIN_COL_WIDTH:  6.0,   // was 4.0 — raised so short labels don't produce tiny columns
  PX_PER_UNIT:    10,    // was 14 — lowered so label widths convert to wider columns
  LABEL_PAD_PX:   24,    // was 20 — slightly more internal padding
  BOX_PAD:        2.5,   // was 2.0 — slightly more breathing room inside boxes
  BOX_HEADER:     1.6,   // was 1.4 — more room for directory name header
});
```

**Why these values fix the overlap:**

The measured label width for a typical node like `create_order` is ~100px. Under v2:
`100px / 14 PX_PER_UNIT = 7.14 graph units`. Under v3: `100px / 10 = 10.0 graph units`.
With `COL_PAD: 6.0`, adjacent column centers are now `10.0 + 6.0 = 16.0` units apart
instead of `7.14 + 3.0 = 10.14`. This provides clear separation even at default zoom.

### 4.6 Vertical Spread Using start_line (New)

**Problem**: In v2, the y-position is `-(depth * ROW_HEIGHT + slot * SUB_ROW_HEIGHT)`.
Since most code nodes (functions, classes, methods) are direct children of a file-level
module node, they all land at depth 1 or 2 — producing a flat horizontal line with no
vertical differentiation.

**Fix**: Replace the depth-based y with a **start_line-based continuous offset**. Within
each file column, nodes are spread vertically by their source position in the file. This
uses information already in the node data (every node has `start_line`) and produces
meaningful vertical ordering — functions defined early in a file appear higher than those
defined later.

**Updated y-position formula:**

```javascript
// Within each file column, after sorting by (depth, start_line, name):
const y = -(slotIndex * LAYOUT.ROW_HEIGHT);
```

Where `slotIndex` is simply the node's sorted position within its column (0, 1, 2, ...).
This replaces the depth+subslot scheme which collapsed when all nodes shared a depth.

**Why this is deterministic**: `slotIndex` is derived from a stable sort on
`(depth, start_line, name)`. Same nodes → same sort → same slots → same picture.

**Updated layoutNodes pseudocode:**

```javascript
function layoutNodes(nodes, nodeById) {
  const depthOf = computeDepths(nodes, nodeById);

  const directories = [];
  const fileGroups = {};
  for (const n of nodes) {
    if (n.node_type === "directory") { directories.push(n); continue; }
    (fileGroups[n.file_path || "__unfiled__"] ||= []).push(n);
  }

  const sortedFiles = Object.keys(fileGroups).sort();

  // Measure column widths
  const colWidths = sortedFiles.map(fp => {
    let maxPx = 0;
    for (const n of fileGroups[fp]) {
      const px = measureLabelWidth(n._displayLabel || n.name);
      if (px > maxPx) maxPx = px;
    }
    return Math.max(LAYOUT.MIN_COL_WIDTH, maxPx / LAYOUT.PX_PER_UNIT);
  });

  // Cumulative x-centers
  const colX = [];
  let xCursor = 0;
  for (let i = 0; i < sortedFiles.length; i++) {
    colX.push(xCursor + colWidths[i] / 2);
    xCursor += colWidths[i] + LAYOUT.COL_PAD;
  }

  // Position nodes — use sorted slot index for y
  const positions = new Map();
  for (let ci = 0; ci < sortedFiles.length; ci++) {
    const group = fileGroups[sortedFiles[ci]];
    group.sort((a, b) =>
      (depthOf[a.node_id] - depthOf[b.node_id])
      || (a.start_line - b.start_line)
      || a.name.localeCompare(b.name)
    );

    for (let si = 0; si < group.length; si++) {
      positions.set(group[si].node_id, {
        x: colX[ci],
        y: -(si * LAYOUT.ROW_HEIGHT),
      });
    }
  }

  const boxes = computeBoundingBoxes(directories, positions, nodeById, depthOf);
  return { positions, boxes, directories };
}
```

**Key difference from v2**: The inner loop uses `si` (slot index from sorted position)
instead of `depth * ROW_HEIGHT + slotInDepth * SUB_ROW_HEIGHT`. This guarantees even
vertical spacing regardless of depth distribution.

---

## 5. Directory Bounding Boxes (Updated)

### 5.1–5.2: Unchanged from v2

Concept and computation algorithm are the same.

### 5.3 Updated Rendering (Increased Visibility)

The v2 alpha values (`0.03` fill, `0.12` stroke) were invisible on the `#0a1018` dark
background. v3 increases these substantially.

**Updated beforeRender handler:**

```javascript
renderer.on("beforeRender", () => {
  nodeLabelHitboxes.clear();
  if (!filterState.showBoundingBoxes) return;

  const context = renderer.getCanvases()?.edges?.getContext("2d");
  if (!context) return;
  context.save();

  for (const [dirId, box] of boundingBoxes) {
    const tl = renderer.graphToViewport({ x: box.x, y: box.y });
    const br = renderer.graphToViewport({ x: box.x + box.w, y: box.y - box.h });
    const screenW = br.x - tl.x;
    const screenH = br.y - tl.y;
    if (screenW < 2 || screenH < 2) continue;

    const depth = box.depth || 0;

    // v3: increased alpha values for dark background visibility
    const fillAlpha = 0.07 + depth * 0.02;      // was 0.03 + depth * 0.015
    const strokeAlpha = 0.22 + depth * 0.06;     // was 0.12 + depth * 0.04
    const labelAlpha = 0.55 + depth * 0.1;       // was 0.45 + depth * 0.1

    context.fillStyle = "rgba(148, 163, 184, " + fillAlpha + ")";
    context.strokeStyle = "rgba(148, 163, 184, " + strokeAlpha + ")";
    context.lineWidth = 1;
    drawRoundedRect(context, tl.x, tl.y, screenW, screenH, 8);
    context.fill();
    context.stroke();

    // Header label
    context.fillStyle = "rgba(148, 163, 184, " + labelAlpha + ")";
    context.font = '600 11px "IBM Plex Mono", "IBM Plex Sans", sans-serif';
    context.textAlign = "left";
    context.textBaseline = "top";
    context.fillText(box.label + "/", tl.x + 8, tl.y + 5);
  }
  context.restore();
});
```

**Visual effect of the change:**

| Depth | v2 Fill | v3 Fill | v2 Stroke | v3 Stroke |
|-------|---------|---------|-----------|-----------|
| 0 | 0.030 | 0.070 | 0.120 | 0.220 |
| 1 | 0.045 | 0.090 | 0.160 | 0.280 |
| 2 | 0.060 | 0.110 | 0.200 | 0.340 |

The fills are now 2–3x more visible and the strokes provide clear boundary lines, while
still being translucent enough to not obscure the node labels inside them.

---

## 6. Edge Rendering by Type (Updated)

### 6.1–6.2: Unchanged from v2

Edge types, filtering rules, and the `contains`-are-consumed-by-boxes principle remain.

### 6.3 Arrow Program Registration (New Fix)

**Problem**: v2 specified `defaultEdgeType: "arrow"` in the Sigma constructor and set
`type: "arrow"` in the `edgeReducer`, but arrows still didn't render. This is because
Sigma's vendored UMD build may not auto-register the `EdgeArrowProgram` — it must be
passed explicitly in the Sigma constructor options.

**Fix**: Pass `edgeProgramClasses` in the Sigma constructor:

```javascript
const renderer = new Sigma(graph, document.getElementById("graph"), {
  // ... other options ...
  defaultEdgeType: "arrow",
  edgeProgramClasses: {
    arrow: sigma.EdgeArrowProgram,
    line: sigma.EdgeLineProgram || sigma.EdgeRectangleProgram,
  },
  // ... rest of options ...
});
```

**Fallback check**: If `sigma.EdgeArrowProgram` is `undefined`, the vendored build doesn't
export it. In that case, check for:
- `sigma.programs?.EdgeArrowProgram`
- `sigma.EdgeArrowProgram`
- The default programs exported by the Sigma UMD bundle

**Diagnostic step** (for implementation): Add a temporary `console.log` to verify:
```javascript
console.log("Arrow program:", sigma.EdgeArrowProgram);
console.log("Sigma exports:", Object.keys(sigma));
```

If the arrow program truly isn't available in the vendored build, fall back to using
`defaultEdgeType: "line"` with distinct colors and sizes to differentiate edge types
visually (arrows are nice-to-have; color differentiation is essential).

### 6.4 Edge Visibility Verification

Beyond the arrow program, verify that edge data actually flows through:

1. **API response**: `/api/edges` must return `imports` and `inherits` edges for this demo
   dataset. Check the network tab.
2. **Node presence**: Both `from_id` and `to_id` must exist in the graph. Since directories
   are excluded, any edge where either endpoint is a directory node will be silently dropped
   by the `graph.hasNode()` guard. Verify that `imports`/`inherits` edges connect
   non-directory nodes.
3. **Edge key uniqueness**: The key format `from_id + "->" + to_id + ":" + edge_type`
   should be unique. If not, duplicates are silently skipped.

**Diagnostic**: After loading edges, log the count:
```javascript
console.log("Edges loaded:", graph.size, "from", edges.length, "API edges");
```

---

## 7. Node Visual Identity (Unchanged)

Same as v2 §6: color-by-type, status overrides, shape variation (pills for
functions/methods, double-border for classes), and qualified labels.

---

## 8. Camera Framing (New)

This is the most impactful fix in v3. The v2 camera approach (`animatedReset()`) was
fundamentally wrong.

### 8.1 The Problem

`Sigma.getCamera().animatedReset()` animates to `{x: 0.5, y: 0.5, ratio: 1}`. This is
the *default center of the abstract viewport*, not the center of the data. Since all node
y-values are negative (due to the y-negation for depth), the data lives in the lower-left
quadrant. The camera resets to the center, leaving the graph crushed at the bottom edge.

### 8.2 The Fix: Compute Data Bounds and Center Camera

After `loadGraph()` populates the graph, compute the actual extent of all node positions
and animate the camera to center on that extent with appropriate zoom.

```javascript
function fitCameraToGraph() {
  const camera = renderer.getCamera();
  const nodes = graph.nodes();
  if (nodes.length === 0) {
    camera.animatedReset({ duration: 300 });
    return;
  }

  // Compute data bounds in graph coordinates
  let minX = Infinity, maxX = -Infinity;
  let minY = Infinity, maxY = -Infinity;
  for (const nodeId of nodes) {
    const attrs = graph.getNodeAttributes(nodeId);
    if (attrs.hidden) continue;
    if (attrs.x < minX) minX = attrs.x;
    if (attrs.x > maxX) maxX = attrs.x;
    if (attrs.y < minY) minY = attrs.y;
    if (attrs.y > maxY) maxY = attrs.y;
  }

  // Also include bounding boxes in extent calculation
  for (const [, box] of boundingBoxes) {
    if (box.x < minX) minX = box.x;
    if (box.x + box.w > maxX) maxX = box.x + box.w;
    if (box.y - box.h < minY) minY = box.y - box.h;
    if (box.y > maxY) maxY = box.y;
  }

  // Sigma normalized coordinates: the graph extent maps to [0,1] range.
  // We need to compute camera {x, y, ratio} that frames this extent.
  //
  // Sigma's camera model:
  //   x, y = position in [0, 1] normalized space (0.5, 0.5 = center)
  //   ratio = zoom level (1 = default, <1 = zoomed in, >1 = zoomed out)
  //
  // After graph.addNode(), Sigma auto-normalizes coordinates internally.
  // animatedReset() goes to {x: 0.5, y: 0.5, ratio: 1} which shows the
  // full normalized extent — but only if the extent is centered around origin.
  //
  // The simplest correct approach: use Sigma's built-in graph extent.

  // Approach: shift all node positions so data is centered at origin,
  // OR use animatedReset with a brief delay to let Sigma normalize.

  // Safest approach that works with Sigma's internals:
  camera.animate(
    { x: 0.5, y: 0.5, ratio: 1.05 },
    { duration: 300 }
  );
}
```

### 8.3 The Real Fix: Center Data at Origin

The camera framing problem is fundamentally caused by the data living at negative y-values
far from origin. The cleanest fix is to **shift all positions so the data centroid is at
(0, 0)** before adding nodes to the graph. This way, `animatedReset()` works correctly
because Sigma normalizes around the data extent.

**Add a centering step after layout, before adding nodes to the graph:**

```javascript
async function loadGraph() {
  const nodesResp = await fetch("/api/nodes");
  const nodes = await nodesResp.json();
  const nodeById = Object.fromEntries(nodes.map(n => [n.node_id, n]));

  qualifyLabels(nodes, nodeById);
  const layout = layoutNodes(nodes, nodeById);

  // === v3 NEW: Center all positions around origin ===
  const allPositions = [...layout.positions.values()];
  if (allPositions.length > 0) {
    let sumX = 0, sumY = 0;
    for (const p of allPositions) { sumX += p.x; sumY += p.y; }
    const cx = sumX / allPositions.length;
    const cy = sumY / allPositions.length;

    // Shift node positions
    for (const [nid, pos] of layout.positions) {
      pos.x -= cx;
      pos.y -= cy;
    }

    // Shift bounding boxes
    for (const [did, box] of layout.boxes) {
      box.x -= cx;
      box.y -= cy;
    }
  }
  // === end centering ===

  boundingBoxes = layout.boxes;
  graph.clear();

  // ... rest of loadGraph unchanged (add nodes, add edges, applyFilters) ...

  renderer.refresh();
  renderer.getCamera().animatedReset({ duration: 300 });
}
```

After this centering, `animatedReset()` works correctly because:
1. Sigma normalizes the graph extent to `[0, 1]` internally.
2. The centroid is at origin, so the normalized center is `(0.5, 0.5)`.
3. `animatedReset()` goes to `{x: 0.5, y: 0.5, ratio: 1}` — exactly the center.

### 8.4 Sidebar Margin

The graph container already has `flex: 1` and the sidebar is a separate `<aside>`. Sigma
renders into the `#graph` div which only occupies the space left of the sidebar. So the
camera framing automatically accounts for the sidebar — no additional margin needed.

**However**, if labels still clip at the right edge after centering, add a small padding
factor to the camera ratio:

```javascript
// Slightly zoomed out to provide margin
renderer.getCamera().animatedReset({ duration: 300 });
setTimeout(() => {
  const camera = renderer.getCamera();
  camera.animate({ ratio: camera.ratio * 1.15 }, { duration: 200 });
}, 350);
```

This zooms out 15% after the initial reset, providing breathing room on all edges.

---

## 9. Interaction Layer (Unchanged)

Same as v2 §7: hover highlights neighbors, click selects node + populates sidebar, zoom
controls at bottom-left.

---

## 10. Filter Controls (Unchanged)

Same as v2 §8: chip bar with node types, edge types, and filesystem toggle.

---

## 11. Bug Fixes from v2 Implementation

These are the six issues identified from the v2 implementation screenshot
(`ui-playwright-20260327-221431-034.png`):

### 11.1 Camera Not Framing Content (P0)

**Symptom**: All nodes crushed into the bottom ~20% of the viewport, ~80% of the canvas
is empty dark space above them.

**Root Cause**: `renderer.getCamera().animatedReset({ duration: 300 })` goes to
`{x: 0.5, y: 0.5, ratio: 1}` which is the center of Sigma's abstract viewport. But all
node y-values are negative (from the y-negation), so the data lives far below this center
point.

**Fix**: Center all positions at origin before adding to graph (§8.3). This makes
`animatedReset()` correctly frame the data.

### 11.2 Horizontal Label Overlap (P0)

**Symptom**: Node labels ("services/demo architecture", "source graph mapping",
"create_order", "models/OrderRequest", etc.) overlap and collide horizontally.

**Root Cause**: `PX_PER_UNIT: 14` was too aggressive — it converted measured pixel widths
to graph units that were narrower than the actual rendered labels. Combined with
`COL_PAD: 3.0`, columns were packed too tightly.

**Fix**: Lower `PX_PER_UNIT` to 10 and increase `COL_PAD` to 6.0 (§4.5). This roughly
doubles the effective column spacing.

### 11.3 No Visible Edge Arrows (P1)

**Symptom**: Despite `imports` and `inherits` edges existing in the data, no arrows are
visible between nodes.

**Root Cause**: Two possible causes, both addressed:
1. Sigma's vendored UMD build may not auto-register `EdgeArrowProgram`. Without explicit
   registration, `type: "arrow"` in the edgeReducer has no effect.
2. Edge endpoints may reference directory nodes (which are excluded from the graph),
   causing the `graph.hasNode()` guard to silently drop them.

**Fix**: Explicitly register `edgeProgramClasses` in the Sigma constructor (§6.3). Add
diagnostic logging to verify edge count after load (§6.4).

### 11.4 Invisible Bounding Boxes (P1)

**Symptom**: No visible directory rectangles grouping nodes, despite the `filesystem`
filter chip being active.

**Root Cause**: Fill alpha `0.03` and stroke alpha `0.12` are effectively invisible on the
dark `#0a1018` background. The `rgba(148, 163, 184, 0.03)` fill produces a color of
approximately `#0f1620` — virtually indistinguishable from `#0a1018`.

**Fix**: Increase base fill alpha to `0.07` and stroke alpha to `0.22` (§5.3). At depth 1,
this produces a visible `rgba(148, 163, 184, 0.09)` fill — subtle but clearly
distinguishable.

### 11.5 Right-Edge Label Clipping (P2)

**Symptom**: Labels on the rightmost nodes are cut off by the sidebar edge ("demo-
companion-c...", "demo-docs-filter-ob...").

**Root Cause**: The camera centers on the abstract viewport center, not the data center.
Nodes on the right side of the data extend beyond the visible area.

**Fix**: Solved by the camera centering fix (§8.3). With data centered at origin, the
camera frames all nodes with equal margin on all sides. Optional 15% zoom-out (§8.4)
provides additional breathing room.

### 11.6 Flat Y-Axis (P2)

**Symptom**: Almost all nodes sit at the same y-coordinate, producing a single horizontal
row with no vertical spread.

**Root Cause**: The depth-based y-formula `-(depth * ROW_HEIGHT + slot * SUB_ROW_HEIGHT)`
collapses when most non-directory nodes share depth 1 or 2. In a typical Python project,
functions and classes are direct children of a file-level module — so `depth` is uniformly
1, and `slotInDepth` provides minimal spread because the sub-slot counter resets per depth
level.

**Fix**: Replace depth-based y with slot-index-based y (§4.6). Each node's y is simply
`-(slotIndex * ROW_HEIGHT)` where `slotIndex` is its position in the sorted column. This
guarantees even vertical distribution regardless of depth uniformity.

---

## 12. File Scope

Same as v2. All changes in `src/remora/web/static/index.html`.

### 12.1 What Changes from v2 → v3

| Section | v2 → v3 Change |
|---------|---------------|
| `LAYOUT` constants | `COL_PAD` 3→6, `MIN_COL_WIDTH` 4→6, `PX_PER_UNIT` 14→10, `LABEL_PAD_PX` 20→24, `BOX_PAD` 2→2.5, `BOX_HEADER` 1.4→1.6 |
| `layoutNodes()` inner loop | Replace `depth * ROW + slotInDepth * SUB_ROW` with `slotIndex * ROW` |
| `beforeRender` handler | Increase alpha values for fill, stroke, and label text |
| Sigma constructor | Add `edgeProgramClasses` with explicit arrow program registration |
| `loadGraph()` | Add data-centering step (shift positions to origin) before adding nodes |

### 12.2 What Does NOT Change from v2

Everything else from v2 remains:
- Two visual channels architecture
- Directory exclusion from graph
- Bounding box computation (`computeBoundingBoxes`, `isDescendantOf`)
- `qualifyLabels()` with parent-name fallback
- `EDGE_STYLES`, `edgeReducer`, `nodeReducer`
- `drawNodeBoxLabel()` (shapes, colors, hit-boxes)
- Filter chip HTML/CSS and `applyFilters()`
- Zoom controls
- Hover highlight (`enterNode`/`leaveNode`)
- Sidebar, SSE handlers, agent panel — all untouched

---

## 13. Determinism Guarantee (Unchanged)

Same as v2 §11. The v3 changes (wider spacing, slot-index y, data centering) are all
deterministic:

| v3 Change | Deterministic? |
|-----------|---------------|
| `COL_PAD`, `PX_PER_UNIT` constants | Yes — constants |
| Slot-index y | Yes — derived from sorted position in column |
| Data centering (subtract centroid) | Yes — centroid is mean of deterministic positions |
| Camera `animatedReset()` | Yes — always goes to {0.5, 0.5, 1} |

Same nodes → same picture. Guaranteed.
