# Concept: Graph View Overhaul (v2)

## Table of Contents
1. [Design Goals](#1-design-goals)
2. [Core Idea: Two Visual Channels](#2-core-idea-two-visual-channels)
3. [Deterministic Layout System](#3-deterministic-layout-system)
4. [Directory Bounding Boxes](#4-directory-bounding-boxes)
5. [Edge Rendering by Type](#5-edge-rendering-by-type)
6. [Node Visual Identity](#6-node-visual-identity)
7. [Interaction Layer](#7-interaction-layer)
8. [Filter Controls](#8-filter-controls)
9. [Bug Fixes from v1](#9-bug-fixes-from-v1)
10. [File Scope](#10-file-scope)
11. [Determinism Guarantee](#11-determinism-guarantee)

---

## 1. Design Goals

**Primary**: The graph should be immediately legible. A user glancing at the screen should
be able to identify the filesystem hierarchy, cross-file relationships, and node types
within seconds.

**Secondary**: The layout must be **deterministic**. Given the same set of discovered nodes,
the graph must produce the same visual arrangement every time. Tear down and restart → same
picture.

**Constraints**:
- Single-file change (`index.html`) — no new vendor scripts, no build step.
- Must work with the existing Sigma + graphology bundle already vendored.
- Must handle 10–150 nodes (typical project range) without overlap or truncation.

---

## 2. Core Idea: Two Visual Channels

The graph has three edge types: `contains`, `imports`, `inherits`. These serve
fundamentally different purposes:

| Edge Type | Purpose | Nature |
|-----------|---------|--------|
| `contains` | Filesystem structure (dir→file→class→method) | Tree — every node has exactly one parent |
| `imports` | Cross-file dependency | DAG — sparse, semantic |
| `inherits` | Class inheritance | DAG — sparse, semantic |

Drawing all three as lines creates spaghetti. The solution is to encode them on
**different visual channels**:

| Channel | Encodes | Visual Form |
|---------|---------|-------------|
| **Spatial containment** | `contains` edges | Nested bounding boxes — translucent rectangles around each directory's contents |
| **Drawn arrows** | `imports` + `inherits` | Colored directional arrows between nodes |

These channels don't compete. The boxes define *where things live*. The arrows define
*how things relate*. A user reads the filesystem by scanning the nested rectangles and
reads the dependency graph by following the arrows.

```
┌─ src/ ─────────────────────────────────────────────────┐
│  ┌─ services/ ──────────────────┐  ┌─ utils/ ───────┐ │
│  │  (OrderRequest) ── imports ──────→ (format_usd)   │ │
│  │  (OrderSummary)              │  │  (choose_wh...) │ │
│  │  (create_order)              │  └─────────────────┘ │
│  └──────────────────────────────┘                      │
│  ┌─ models/ ────────────────────┐                      │
│  │  (OrderRequest)              │                      │
│  │  (OrderSummary)              │                      │
│  └──────────────────────────────┘                      │
└────────────────────────────────────────────────────────┘
┌─ bundles/ ──────────────────────┐
│  (Runtime profiles)             │
│  (Validation checks)            │
│  (Virtual agents)               │
└─────────────────────────────────┘
```

This directly solves the "disconnected section/virtual nodes" problem: bundle sections
and virtual agents appear inside their parent directory's bounding box, visually grouped
even though they have no `imports`/`inherits` edges.

---

## 3. Deterministic Layout System

### 3.1 Why the Original Layout Failed

The original layout computed each node's `(x, y)` from a mix of type-track offsets,
sibling spread, level spread, depth fanout, depth zigzag, sine-wave jitter, and hash
jitter. This produced overlapping labels, spaghetti edge crossings, and a spatial layout
that carried no learnable meaning.

### 3.2 New Layout: File-Column Grid

Replace the entire positioning system with a **file-column grid** where:

- **X-axis** = file identity (each unique `file_path` gets a column).
- **Y-axis** = containment depth (root directories at top, leaf functions at bottom).

**Critical**: Sigma's coordinate system has **positive y = up on screen**. To render
directories at the top and leaf nodes below, the layout must **negate y**:

```javascript
y = -(depth * ROW_HEIGHT + slotOffset * SUB_ROW_HEIGHT)
```

This gives root nodes (depth 0) the largest y values (top of screen) and deep nodes the
smallest y values (bottom of screen).

### 3.3 Directory Nodes Are Not Graph Nodes

Directories are removed from the graphology graph entirely. They don't participate in
node rendering, edge connections, hover, or selection. Instead, they become **background
bounding boxes** drawn on the canvas layer beneath Sigma's rendering (see §4).

This means the layout algorithm only positions non-directory nodes (functions, classes,
methods, sections, tables, virtual agents). Directories are consumed by the bounding-box
computation.

### 3.4 Algorithm

```
Step 1 — Compute tree depth for every node from parent_id chains.
Step 2 — Separate directory nodes from non-directory nodes.
Step 3 — Group non-directory nodes by file_path. Each group is a column.
Step 4 — Sort columns alphabetically by file_path → deterministic column order.
Step 5 — Measure the widest label in each column → adaptive column widths.
Step 6 — Compute column x-centers from cumulative widths + padding.
Step 7 — Within each column, sort nodes by (depth, start_line, name).
         Assign y-slots: nodes at the same depth get incrementing sub-slots.
         Negate all y values so depth 0 = top of screen.
Step 8 — After layout, compute bounding boxes from directory→descendant positions.
```

### 3.5 Layout Constants

```javascript
const LAYOUT = Object.freeze({
  COL_PAD:        3.0,   // graph-unit gap between columns
  ROW_HEIGHT:     2.2,   // graph-unit vertical spacing per depth level
  SUB_ROW_HEIGHT: 1.6,   // graph-unit spacing between siblings at same depth
  MIN_COL_WIDTH:  4.0,   // floor for column width so narrow labels don't collapse
  PX_PER_UNIT:    14,    // pixel-to-graph-unit conversion at default zoom
  LABEL_PAD_PX:   20,    // pixel padding inside label boxes for measurement
  BOX_PAD:        2.0,   // graph-unit padding inside bounding boxes
  BOX_HEADER:     1.4,   // graph-unit reserved for bounding box header label
});
```

### 3.6 Pseudocode

```javascript
function layoutNodes(nodes, nodeById) {
  const depthOf = computeDepths(nodes, nodeById);

  // Separate directories from content nodes
  const directories = [];
  const fileGroups = {};  // file_path → [node, ...]
  for (const n of nodes) {
    if (n.node_type === "directory") { directories.push(n); continue; }
    (fileGroups[n.file_path || "__unfiled__"] ||= []).push(n);
  }

  const sortedFiles = Object.keys(fileGroups).sort();

  // Measure column widths
  const colWidths = sortedFiles.map(fp =>
    Math.max(LAYOUT.MIN_COL_WIDTH,
      ...fileGroups[fp].map(n => measureLabel(n._displayLabel) / LAYOUT.PX_PER_UNIT))
  );

  // Cumulative x-centers
  const colX = [];
  let xCursor = 0;
  for (let i = 0; i < sortedFiles.length; i++) {
    colX.push(xCursor + colWidths[i] / 2);
    xCursor += colWidths[i] + LAYOUT.COL_PAD;
  }

  // Position content nodes — y NEGATED so depth 0 = top
  const positions = new Map();
  for (let ci = 0; ci < sortedFiles.length; ci++) {
    const group = fileGroups[sortedFiles[ci]];
    group.sort((a, b) =>
      (depthOf[a.node_id] - depthOf[b.node_id])
      || (a.start_line - b.start_line)
      || a.name.localeCompare(b.name));

    let prevDepth = -1, slotInDepth = 0;
    for (const n of group) {
      const d = depthOf[n.node_id];
      if (d === prevDepth) slotInDepth++;
      else { slotInDepth = 0; prevDepth = d; }
      positions.set(n.node_id, {
        x: colX[ci],
        y: -(d * LAYOUT.ROW_HEIGHT + slotInDepth * LAYOUT.SUB_ROW_HEIGHT),
      });
    }
  }

  // Compute bounding boxes for directories (see §4)
  const boxes = computeBoundingBoxes(directories, positions, nodeById, depthOf);

  return { positions, boxes };
}
```

### 3.7 Within-Column Collision Resolution

The sub-slot mechanism handles same-depth siblings directly:

1. Nodes in each column are sorted by `(depth, start_line, name)`.
2. When consecutive nodes share a depth, `slotInDepth` increments.
3. Each slot adds `SUB_ROW_HEIGHT` to the y offset.

This is O(n) and deterministic. No iterative physics.

---

## 4. Directory Bounding Boxes

### 4.1 Concept

Each directory node becomes a translucent rounded rectangle drawn behind all graph nodes
and edges. The rectangle encloses all of the directory's descendant node positions (with
padding), and has a small header label showing the directory name.

Boxes nest naturally: `src/` contains `src/services/`, which contains the nodes from
`services/orders.py`. This creates a visual hierarchy:

```
┌─ src/ (outermost, lightest) ──────────────────┐
│  ┌─ services/ (inner, slightly darker) ─────┐ │
│  │  (OrderRequest)  (OrderSummary)           │ │
│  │  (create_order)  (discount_for_tier)      │ │
│  └───────────────────────────────────────────┘ │
│  ┌─ models/ ─────────────────────────────────┐ │
│  │  (OrderRequest)  (OrderSummary)           │ │
│  └───────────────────────────────────────────┘ │
└────────────────────────────────────────────────┘
```

### 4.2 Computation

Bounding boxes are computed **bottom-up**: deepest directories first, so inner boxes are
resolved before outer boxes can include them in their extent.

```javascript
function computeBoundingBoxes(directories, positions, nodeById, depthOf) {
  // Sort deepest first
  directories.sort((a, b) =>
    (depthOf[b.node_id] - depthOf[a.node_id]) || a.name.localeCompare(b.name));

  const boxes = new Map();  // dir node_id → { x, y, w, h, label, depth }

  for (const dir of directories) {
    // Collect bounds of direct + transitive descendants
    const points = [];  // array of { x, y } extremes

    // Content nodes that descend from this directory
    for (const [nid, pos] of positions) {
      if (isDescendantOf(nid, dir.node_id, nodeById)) {
        points.push(pos);
      }
    }

    // Inner directory boxes that are direct children
    for (const [did, box] of boxes) {
      if (nodeById[did]?.parent_id === dir.node_id) {
        points.push({ x: box.x, y: box.y });
        points.push({ x: box.x + box.w, y: box.y - box.h });
      }
    }

    if (points.length === 0) continue;

    const minX = Math.min(...points.map(p => p.x));
    const maxX = Math.max(...points.map(p => p.x));
    const maxY = Math.max(...points.map(p => p.y));  // highest on screen (least negative)
    const minY = Math.min(...points.map(p => p.y));  // lowest on screen (most negative)

    boxes.set(dir.node_id, {
      x: minX - LAYOUT.BOX_PAD,
      y: maxY + LAYOUT.BOX_PAD + LAYOUT.BOX_HEADER,  // top edge (above highest child)
      w: (maxX - minX) + LAYOUT.BOX_PAD * 2,
      h: (maxY - minY) + LAYOUT.BOX_PAD * 2 + LAYOUT.BOX_HEADER,  // total height
      label: dir.name,
      depth: depthOf[dir.node_id],
    });
  }
  return boxes;
}

function isDescendantOf(nodeId, ancestorId, nodeById) {
  let current = nodeById[nodeId];
  while (current) {
    if (current.parent_id === ancestorId) return true;
    current = current.parent_id ? nodeById[current.parent_id] : null;
  }
  return false;
}
```

### 4.3 Rendering

Boxes are drawn in Sigma's `beforeRender` callback, which fires before node/edge
rendering. This ensures boxes appear *behind* everything.

```javascript
renderer.on("beforeRender", ({ context }) => {
  nodeLabelHitboxes.clear();
  if (!filterState.showBoundingBoxes) return;

  for (const [dirId, box] of boundingBoxes) {
    const tl = renderer.graphToViewport({ x: box.x, y: box.y });
    const br = renderer.graphToViewport({ x: box.x + box.w, y: box.y - box.h });
    const screenW = br.x - tl.x;
    const screenH = br.y - tl.y;

    // Deeper directories get slightly more opaque
    const alpha = 0.03 + box.depth * 0.015;
    const borderAlpha = 0.12 + box.depth * 0.04;

    context.fillStyle = `rgba(148, 163, 184, ${alpha})`;
    context.strokeStyle = `rgba(148, 163, 184, ${borderAlpha})`;
    context.lineWidth = 1;
    drawRoundedRect(context, tl.x, tl.y, screenW, screenH, 8);
    context.fill();
    context.stroke();

    // Header label in top-left
    context.fillStyle = `rgba(148, 163, 184, ${0.45 + box.depth * 0.1})`;
    context.font = '600 11px "IBM Plex Mono", "IBM Plex Sans", sans-serif';
    context.textAlign = "left";
    context.textBaseline = "top";
    context.fillText(box.label + "/", tl.x + 8, tl.y + 5);
  }
});
```

### 4.4 Why Not Graph Nodes

Drawing directories as graph nodes creates problems:
- They participate in edge rendering → `contains` edges create spaghetti.
- They participate in hover/selection → clicking a directory isn't useful.
- They compete for visual space with actual code nodes.
- They need `contains` edge lines to show hierarchy, which is what we're avoiding.

As bounding boxes:
- They provide visual containment without drawn edges.
- They're a canvas-layer overlay — outside Sigma's node/edge system.
- They nest naturally, showing the full filesystem tree.
- Non-Python nodes (sections, virtual agents) appear inside their parent box.

---

## 5. Edge Rendering by Type

### 5.1 Edge Types in the System

| Edge Type  | Created By | Meaning | Prevalence |
|------------|-----------|---------|------------|
| `contains` | `reconciler.py`, `directories.py` | Parent→child structural containment | ~1 per node |
| `imports`  | `relationships.py` (tree-sitter) | File-level import dependency | Moderate |
| `inherits` | `relationships.py` (tree-sitter) | Class inheritance | Sparse |

### 5.2 Rendering Rules

`contains` edges are **never drawn as lines**. They are consumed by the bounding-box
system (§4). Only `imports` and `inherits` edges are added to the graphology graph.

| Edge Type  | In graphology? | Color | Style | Arrow | Size |
|------------|---------------|-------|-------|-------|------|
| `contains` | **No** — consumed by bounding boxes | — | — | — | — |
| `imports`  | **Yes** | `#60a5fa` (blue) | Arrow | → | 1.8 |
| `inherits` | **Yes** | `#a78bfa` (purple) | Arrow | → | 1.8 |

### 5.3 Implementation

In `loadGraph()`, filter edges before adding them to the graph:

```javascript
for (const edge of edges) {
  if (edge.edge_type === "contains") continue;  // consumed by bounding boxes
  const key = edge.from_id + "->" + edge.to_id + ":" + edge.edge_type;
  if (!graph.hasNode(edge.from_id) || !graph.hasNode(edge.to_id)) continue;
  if (!graph.hasEdge(key)) {
    graph.addEdgeWithKey(key, edge.from_id, edge.to_id, {
      label: edge.edge_type,
      size: 1,
    });
  }
}
```

Edge styling via `edgeReducer`:

```javascript
const EDGE_STYLES = Object.freeze({
  imports:  { color: "#60a5fa", size: 1.8, type: "arrow" },
  inherits: { color: "#a78bfa", size: 1.8, type: "arrow" },
});
const DEFAULT_EDGE_STYLE = Object.freeze({
  color: "#3a4f6a", size: 1, type: "line",
});

// In Sigma options:
edgeReducer: (edge, data) => {
  const style = EDGE_STYLES[data.label] || DEFAULT_EDGE_STYLE;
  return { ...data, color: style.color, size: style.size, type: style.type };
},
```

---

## 6. Node Visual Identity

### 6.1 Color by Node Type (Idle State)

| Node Type   | Border Color | Fill Color | CSS Variable |
|-------------|-------------|------------|--------------|
| `class`     | `#a78bfa` | `rgba(167, 139, 250, 0.10)` | `--class` |
| `function`  | `#60a5fa` | `rgba(96, 165, 250, 0.10)` | `--function` |
| `method`    | `#22d3ee` | `rgba(34, 211, 238, 0.10)` | `--method` |
| `section`   | `#fbbf24` | `rgba(251, 191, 36, 0.10)` | `--section` |
| `table`     | `#34d399` | `rgba(52, 211, 153, 0.10)` | `--table` |
| `virtual`   | `#f472b6` | `rgba(244, 114, 182, 0.10)` | `--virtual` |

Note: `directory` is absent — directories are bounding boxes, not graph nodes.

### 6.2 Status Overrides

Status changes override the **border color only**, preserving the fill:

| Status | Border Override | Additional Effect |
|--------|----------------|-------------------|
| `idle` | (use type color) | None |
| `running` | `#fb923c` (orange) | 2px border width |
| `error` | `#f87171` (red) | 2px border width |
| `awaiting_input` | `#fbbf24` (yellow) | Dashed border |
| `awaiting_review` | `#fbbf24` (yellow) | Dashed border |

### 6.3 Shape Variation

| Node Type | Shape |
|-----------|-------|
| `class` | Rounded rect, **double border** (outer + inner stroke) |
| `function` | **Pill** (fully rounded ends, `borderRadius = height / 2`) |
| `method` | **Pill**, dashed border |
| `section`, `table`, `virtual` | Standard rounded rect |

Two redundant channels (color + shape) for type identification. Helps with colorblindness.

### 6.4 Qualified Labels for Duplicates

When two or more nodes share the same `name`, qualify them with context. The v1
implementation used `parent.name` which produced useless results like
`OrderSummary/OrderSummary` when the parent had the same name.

**Fixed algorithm:**

```javascript
function qualifyLabels(nodes, nodeById) {
  const nameCount = {};
  for (const n of nodes) nameCount[n.name] = (nameCount[n.name] || 0) + 1;

  for (const n of nodes) {
    if (nameCount[n.name] <= 1) {
      n._displayLabel = n.name;
      continue;
    }
    // Try parent name first
    const parent = n.parent_id ? nodeById[n.parent_id] : null;
    if (parent && parent.name !== n.name) {
      n._displayLabel = parent.name + "/" + n.name;
      continue;
    }
    // Fallback: use directory name from file_path
    const parts = (n.file_path || "").replace(/\\/g, "/").split("/").filter(Boolean);
    // Walk backwards to find a meaningful directory name (skip the filename itself)
    let qualifier = null;
    for (let i = parts.length - 2; i >= 0; i--) {
      if (parts[i] !== n.name) { qualifier = parts[i]; break; }
    }
    n._displayLabel = qualifier ? qualifier + "/" + n.name : n.name;
  }
}
```

This produces `services/OrderRequest` vs `models/OrderRequest` instead of
`OrderRequest/OrderRequest`.

---

## 7. Interaction Layer

### 7.1 Hover → Highlight Neighbors

When the mouse enters a node, dim non-neighbors to ~15% opacity and hide unrelated edges.

```javascript
renderer.on("enterNode", ({ node }) => {
  const neighbors = new Set(graph.neighbors(node));
  neighbors.add(node);
  graph.forEachNode((id) => {
    graph.setNodeAttribute(id, "dimmed", !neighbors.has(id));
  });
  graph.forEachEdge((edge, attrs, src, tgt) => {
    if (!neighbors.has(src) || !neighbors.has(tgt)) {
      graph.setEdgeAttribute(edge, "hidden", true);
    }
  });
  renderer.refresh();
});

renderer.on("leaveNode", () => {
  graph.forEachNode((id) => graph.removeNodeAttribute(id, "dimmed"));
  applyFilters();  // restore edge visibility to filter state
});
```

The `nodeReducer` applies dimming: faded color + faded text for `dimmed` nodes.
The `drawNodeBoxLabel` function checks `data.dimmed` for text opacity.

### 7.2 Click → Select + Sidebar Detail

Clicking a node highlights it (slightly larger via `nodeReducer`) and populates the
sidebar. No change from current behavior.

### 7.3 Zoom Controls + Camera Fit

Three buttons overlaid at bottom-left: `+`, `-`, `fit-to-view`.

**Critical addition**: After `loadGraph()` completes, call:
```javascript
renderer.getCamera().animatedReset({ duration: 300 });
```
This auto-fits the graph extent into the viewport, solving right-edge clipping for nodes
with long labels.

---

## 8. Filter Controls

### 8.1 UI: Chip Bar

A horizontal bar of toggleable chips at the top of the graph canvas:

```
[ classes ] [ functions ] [ methods ] [ sections ] [ virtual ]  |  [ imports ] [ inherits ] [ filesystem ]
```

**Key change from v1**: The old `contains` edge chip is replaced with a `filesystem` chip
that toggles **bounding box visibility**, not edge lines. `contains` edges no longer exist
in the graph.

### 8.2 State

```javascript
const filterState = {
  hiddenNodeTypes: new Set(),
  hiddenEdgeTypes: new Set(),
  showBoundingBoxes: true,         // filesystem boxes visible by default
};
```

### 8.3 Applying Filters

```javascript
function applyFilters() {
  graph.forEachNode((id, attrs) => {
    graph.setNodeAttribute(id, "hidden", filterState.hiddenNodeTypes.has(attrs.node_type));
  });
  graph.forEachEdge((edge, attrs) => {
    graph.setEdgeAttribute(edge, "hidden", filterState.hiddenEdgeTypes.has(attrs.label));
  });
  renderer.refresh();  // triggers beforeRender which checks showBoundingBoxes
}
```

The `filesystem` chip toggles `filterState.showBoundingBoxes`. The `beforeRender`
callback checks this flag and skips box drawing when false.

### 8.4 No `dirs` Node Chip

Since directories are no longer graph nodes, the `dirs` node-type chip is removed from
the filter bar. Directories are controlled by the `filesystem` chip instead.

---

## 9. Bug Fixes from v1

These issues were identified from the v1 implementation screenshot and are addressed in
the design above:

### 9.1 Y-Axis Inversion (§3.2)

**Symptom**: Directories appeared at the bottom of the screen, leaf nodes at the top.
**Cause**: Sigma positive y = up. Layout assigned `y = depth * ROW_HEIGHT` (increasing).
**Fix**: Negate all y values. `y = -(depth * ROW_HEIGHT + slot * SUB_ROW_HEIGHT)`.

### 9.2 Self-Referencing Qualified Labels (§6.4)

**Symptom**: Labels like `OrderSummary/OrderSummary`.
**Cause**: `qualifyLabels` used `parent.name` even when parent name === node name.
**Fix**: When parent name matches node name, fall back to file path directory component.

### 9.3 Disconnected Section/Virtual Nodes (§4)

**Symptom**: Bundle sections and virtual agents floated in empty space with no connections.
**Cause**: These nodes have `contains` edges to parents but no `imports`/`inherits`.
  With `contains` hidden, they appeared orphaned.
**Fix**: Bounding boxes provide visual containment. These nodes now appear inside their
  parent directory's box.

### 9.4 Right-Edge Clipping (§7.3)

**Symptom**: Long node names like `demo-src-filter-observer` cut off by the sidebar.
**Cause**: No camera fit-to-view after initial layout.
**Fix**: `renderer.getCamera().animatedReset()` after `loadGraph()`.

---

## 10. File Scope

All changes are in **one file**: `src/remora/web/static/index.html`.

### 10.1 What Gets Replaced

| Section | Change |
|---------|--------|
| CSS variables | Add `--section`, `--table`, `--virtual` |
| Layout constants | Replace all `FILE_BAND_*`, `DEPTH_*`, `TYPE_TRACK_*` with `LAYOUT` object |
| `loadGraph()` | Rewrite: new layout, directories excluded from graph, `contains` edges skipped |
| `drawNodeBoxLabel()` | Type-based shapes, dimming support |
| Sigma constructor | Add `edgeReducer`, update `nodeReducer`, add `beforeRender` for boxes |

### 10.2 What Gets Added

| Addition | Purpose |
|----------|---------|
| `EDGE_STYLES` constant | Edge type → color/size/arrow mapping |
| `layoutNodes()` function | Deterministic file-column grid + bounding box computation |
| `computeBoundingBoxes()` function | Bottom-up box extent calculation |
| `isDescendantOf()` helper | Walks parent chain for box membership |
| `qualifyLabels()` function | Duplicate name disambiguation with fallback |
| `filterState` + `applyFilters()` | Filter state management |
| `beforeRender` handler | Draws bounding boxes on canvas layer |
| Filter chip HTML + CSS | Node type, edge type, and filesystem toggles |
| Zoom controls HTML + handlers | +/−/fit buttons |
| Hover highlight handlers | `enterNode`/`leaveNode` for neighbor focus |
| Camera reset call | Fit-to-view after `loadGraph()` |

### 10.3 What Gets Deleted

| Deletion | Reason |
|----------|--------|
| `hashNodeId()` | Hash jitter removed — layout is sort-based |
| `deterministicOffset()` | Hash jitter removed |
| `fileBandKeyFromPath()` | File bands replaced by file columns |
| `buildFileBands()` | File bands replaced |
| `bandYForNode()` | File bands replaced |
| `__label__` synthetic nodes | Directories are now bounding boxes, not label nodes |

### 10.4 What Stays the Same

- Sidebar structure, agent panel, events, timeline — unchanged.
- SSE event handling — unchanged.
- API endpoints — unchanged.
- Hit-testing logic — unchanged (still uses `nodeLabelHitboxes`).
- `drawRoundedRect()` — unchanged (reused for boxes and node shapes).

---

## 11. Determinism Guarantee

### 11.1 Definition

> For any set of nodes N and edges E, the layout function produces identical `(x, y)`
> coordinates and identical bounding boxes, regardless of discovery order, wall-clock
> time, page refresh count, or demo restart.

### 11.2 How It's Achieved

| Input | Source | Deterministic? |
|-------|--------|----------------|
| File columns | Sorted `file_path` values | Yes — alphabetical sort is stable |
| Child order within column | `(depth, start_line, name)` sort | Yes — same source → same lines |
| Tree depth | `parent_id` chain length | Yes |
| Column widths | `max(measureText(label))` per column | Yes — same labels + font → same widths |
| Bounding boxes | Derived from descendant positions | Yes — positions are deterministic |
| Qualified labels | Derived from name counts + parent/path | Yes |

No hash jitter. No sin waves. No iteration-order dependence. Same nodes → same picture.

### 11.3 Edge Case: Incremental Discovery

During live discovery, `node_discovered` SSE events trigger a full `loadGraph()` which
re-fetches all nodes from `/api/nodes` and re-runs the layout from scratch. Early frames
show partial graphs. Once discovery completes, the layout is stable and identical across
restarts.
