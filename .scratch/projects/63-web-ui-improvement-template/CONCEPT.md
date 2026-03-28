# Concept: Graph View Overhaul

## Table of Contents
1. [Design Goals](#1-design-goals)
2. [Deterministic Layout System](#2-deterministic-layout-system)
3. [Edge Rendering by Type](#3-edge-rendering-by-type)
4. [Node Visual Identity](#4-node-visual-identity)
5. [Interaction Layer](#5-interaction-layer)
6. [Filter Controls](#6-filter-controls)
7. [File Scope](#7-file-scope)
8. [Determinism Guarantee](#8-determinism-guarantee)

---

## 1. Design Goals

**Primary**: The graph should be immediately legible. A user glancing at the screen should
be able to identify containment hierarchy, cross-file relationships, and node types within
seconds — not minutes of tracing spaghetti edges.

**Secondary**: The layout must be **deterministic**. Given the same set of discovered nodes,
the graph must produce the same visual arrangement every time. Tear down and restart → same
picture. This rules out force-directed layouts, randomized initial positions, and any
algorithm that depends on iteration order from async discovery timing.

**Constraints**:
- Single-file change (`index.html`) — no new vendor scripts, no build step.
- Must work with the existing Sigma + graphology bundle already vendored.
- Must handle 10–150 nodes (typical project range) without overlap or truncation.

---

## 2. Deterministic Layout System

### 2.1 Why the Current Layout Fails

The current layout computes each node's `(x, y)` from a cocktail of:

```
x = typeTrackOffset + siblingSpread + levelSpread + depthFanout
    + depthZigzag + depthWave + hashJitter
y = fileBandY + depth * DEPTH_ROW_SPACING + hashJitter
```

This produces **unstable, overlapping results** because:

1. `depthWave = sin(depth * 0.85 + hash % 7) * amplitude` — sinusoidal jitter that fights
   the other x-terms.
2. `hashJitter` via `deterministicOffset()` — pseudo-random per node, unaware of neighbors.
3. `SIBLING_SPREAD = 1.8` — fixed constant regardless of label width.
4. `TYPE_TRACK_OFFSETS` — assigns x by type, but siblings of different types scatter
   across the x-axis with no coherent grouping.

The result is that labels overlap, edges cross needlessly, and the spatial layout carries
no semantic meaning that a user can learn and remember.

### 2.2 New Layout: File-Column Grid

Replace the entire positioning system with a **file-column grid** where:

- **X-axis** = file identity (each file gets a column).
- **Y-axis** = depth in the containment tree (directories at top, functions/methods at
  bottom).

This makes the graph read like a project explorer turned sideways: files are columns,
and their contents stack vertically within each column.

```
         orders.py       pricing.py      utils.py
         ─────────       ──────────      ────────
depth 0: [services/]─────────────────────────────── (directory row, shared)
depth 1: [orders.py]     [pricing.py]    [utils.py]
depth 2: [OrderRequest]  [PricingRule]   [format_usd]
         [OrderSummary]  [apply_tax]     [choose_warehouse]
depth 3: [validate]      [_compute]
         [serialize]
```

#### Algorithm

```
Step 1 — Build the containment tree from parent_id.
Step 2 — Assign each file-rooted subtree a column index.
         Sort columns by file_path (alphabetical → deterministic).
Step 3 — Within each column, sort children by (start_line, name) — deterministic.
Step 4 — Assign y by tree depth. Within a depth level, assign y-slots top to bottom
         in child order.
Step 5 — Assign x by column index × column width.
Step 6 — Column width = max label width of any node in that column + padding.
Step 7 — Directory nodes that span multiple file columns get placed as a wide row
         above their file children (spanning the column range).
```

#### Handling Directories

Directories sit *above* their file children as **spanning headers**. A directory node's
x-position is the midpoint of its children's column range, and it sits at its natural
tree depth on the y-axis. This visually groups files under their directory without needing
`contains` edges drawn.

```
              ┌──── services/ ────┐         ← directory, x = midpoint of children
              ▼                   ▼
         [orders.py]         [pricing.py]   ← files, each a column
         [OrderRequest]      [PricingRule]  ← classes within each file
         [OrderSummary]      [apply_tax]
```

#### Determinism Proof

Every input to the layout is a pure function of the node set:

| Input | Source | Deterministic? |
|-------|--------|----------------|
| File columns | Sorted `file_path` values | Yes — alphabetical sort is stable |
| Column order | `file_path.localeCompare()` | Yes |
| Child order within column | `(start_line, name)` sort | Yes — same source → same lines |
| Tree depth | `parent_id` chain length | Yes — same parent_id → same depth |
| Column width | `max(measureText(label))` per column | Yes — same labels → same widths |
| Directory x | Midpoint of child column range | Yes — derived from above |

No hash jitter. No sin waves. No iteration-order dependence. Same nodes → same picture.

### 2.3 Layout Constants

```javascript
const LAYOUT = Object.freeze({
  COL_PAD:       3.0,   // graph-unit padding between columns
  ROW_HEIGHT:    2.0,   // graph-unit vertical spacing per depth level
  LABEL_PAD_X:   20,    // pixel padding inside label boxes
  DIR_HEADER_GAP: 1.0,  // extra y-gap above directory spanning rows
  MIN_COL_WIDTH: 4.0,   // minimum column width in graph units
  PX_PER_UNIT:   14,    // approximate pixel-to-graph-unit conversion at default zoom
});
```

These are tuning constants, not algorithmic randomness. Changing them shifts the whole
grid uniformly — it doesn't change relative positions.

### 2.4 Pseudocode

```javascript
function layoutNodes(nodes) {
  // 1. Build tree
  const tree = buildContainmentTree(nodes);        // parent_id → children
  const depthOf = computeDepths(tree);             // node_id → int

  // 2. Group by file, sort columns
  const fileGroups = groupByFile(nodes);           // file_path → [node, ...]
  const sortedFiles = Object.keys(fileGroups).sort();

  // 3. Measure column widths
  const colWidths = sortedFiles.map(file =>
    Math.max(LAYOUT.MIN_COL_WIDTH,
      ...fileGroups[file].map(n => measureLabel(n.name) / LAYOUT.PX_PER_UNIT)
    )
  );

  // 4. Compute column x-offsets (cumulative widths + padding)
  const colX = [];
  let xCursor = 0;
  for (let i = 0; i < sortedFiles.length; i++) {
    colX.push(xCursor + colWidths[i] / 2);        // center of column
    xCursor += colWidths[i] + LAYOUT.COL_PAD;
  }

  // 5. Position file-level and below nodes
  const positions = new Map();
  for (let ci = 0; ci < sortedFiles.length; ci++) {
    const fileNodes = fileGroups[sortedFiles[ci]];
    // Sort by (depth, start_line, name) for vertical slot assignment
    fileNodes.sort((a, b) =>
      (depthOf[a.node_id] - depthOf[b.node_id])
      || (a.start_line - b.start_line)
      || a.name.localeCompare(b.name)
    );
    for (const node of fileNodes) {
      const y = depthOf[node.node_id] * LAYOUT.ROW_HEIGHT;
      positions.set(node.node_id, { x: colX[ci], y });
    }
  }

  // 6. Position directory nodes as spanning headers
  for (const node of nodes) {
    if (node.node_type === 'directory') {
      const childXs = getChildColumnXs(node, positions);
      const x = (Math.min(...childXs) + Math.max(...childXs)) / 2;
      const y = depthOf[node.node_id] * LAYOUT.ROW_HEIGHT - LAYOUT.DIR_HEADER_GAP;
      positions.set(node.node_id, { x, y });
    }
  }

  // 7. Collision resolution within each depth row
  resolveRowCollisions(positions, depthOf);

  return positions;
}
```

### 2.5 Within-Row Collision Resolution

After initial grid placement, nodes at the same depth in the same column may overlap
(e.g., two classes in the same file). Resolution:

1. Group nodes by `(column, depth)`.
2. Sort group by `(start_line, name)`.
3. Assign incrementing y-sub-slots: `y = baseY + slotIndex * SUB_ROW_HEIGHT`.

This is O(n) and deterministic. No iterative physics.

---

## 3. Edge Rendering by Type

### 3.1 Edge Types in the System

| Edge Type  | Created By | Meaning | Prevalence |
|------------|-----------|---------|------------|
| `contains` | `reconciler.py`, `directories.py` | Parent→child structural containment | ~1 per node (most edges) |
| `imports`  | `relationships.py` (tree-sitter) | File-level import dependency | Moderate |
| `inherits` | `relationships.py` (tree-sitter) | Class inheritance | Sparse |

### 3.2 Rendering Rules

| Edge Type  | Default Visibility | Color | Style | Arrow | Size |
|------------|-------------------|-------|-------|-------|------|
| `contains` | **Hidden** | `#233247` (muted) | Straight | None | 0.5 |
| `imports`  | **Visible** | `#60a5fa` (blue) | Curved | → | 1.8 |
| `inherits` | **Visible** | `#a78bfa` (purple) | Curved | ◇ (open) | 1.8 |

**Rationale for hiding `contains`**: The file-column layout already communicates
containment through spatial proximity. Drawing `contains` edges would add a line from
every parent to every child — which is exactly the spaghetti we're eliminating. Users who
want to see structure can toggle `contains` on via the filter bar.

### 3.3 Implementation

Sigma's bundled `EdgeArrow` program supports arrow rendering. Edge type styling goes into
the `edgeReducer`:

```javascript
const EDGE_STYLES = Object.freeze({
  contains: { color: '#233247', size: 0.5, hidden: true,  type: 'line'  },
  imports:  { color: '#60a5fa', size: 1.8, hidden: false, type: 'arrow' },
  inherits: { color: '#a78bfa', size: 1.8, hidden: false, type: 'arrow' },
});

// In Sigma options:
edgeReducer: (edge, data) => {
  const style = EDGE_STYLES[data.label] || { color: '#3a4f6a', size: 1, type: 'line' };
  return { ...data, ...style };
},
```

### 3.4 Curved Routing

For `imports` and `inherits`, use `type: 'curved'` (if Sigma supports it in the vendored
build) or compute a manual curvature offset. Since these edges typically cross multiple
file columns horizontally, a gentle arc prevents them from overlapping the column contents.

If the vendored Sigma doesn't expose a `curved` edge type, we fall back to `arrow`
(straight with arrowhead). The color + arrow differentiation alone is a massive
improvement over the current uniform gray lines.

---

## 4. Node Visual Identity

### 4.1 Color by Node Type (Idle State)

| Node Type   | Border Color | Fill Color | CSS Variable |
|-------------|-------------|------------|--------------|
| `directory` | `#94a3b8` | `rgba(148, 163, 184, 0.08)` | `--directory` |
| `class`     | `#a78bfa` | `rgba(167, 139, 250, 0.08)` | `--class` |
| `function`  | `#60a5fa` | `rgba(96, 165, 250, 0.08)` | `--function` |
| `method`    | `#22d3ee` | `rgba(34, 211, 238, 0.08)` | `--method` |
| `section`   | `#fbbf24` | `rgba(251, 191, 36, 0.08)` | `--section` |
| `table`     | `#34d399` | `rgba(52, 211, 153, 0.08)` | `--table` |
| `virtual`   | `#f472b6` | `rgba(244, 114, 182, 0.08)` | `--virtual` |

### 4.2 Status Overrides

Status changes override the **border color only**, preserving the fill so the user can
still identify node type:

| Status | Border Override | Additional Effect |
|--------|----------------|-------------------|
| `idle` | (use type color) | None |
| `running` | `#fb923c` (orange) | 2px border width |
| `error` | `#f87171` (red) | 2px border width |
| `awaiting_input` | `#fbbf24` (yellow) | Dashed border |
| `awaiting_review` | `#fbbf24` (yellow) | Dashed border |

### 4.3 Shape Variation

Extend `drawNodeBoxLabel()` to draw different shapes by type:

| Node Type | Shape |
|-----------|-------|
| `directory` | Rounded rect, **bold 2px** border, slightly larger font |
| `class` | Rounded rect, **double border** (outer + inner stroke) |
| `function` | **Pill** (fully rounded ends, `borderRadius = height / 2`) |
| `method` | **Pill**, dashed border |
| `section`, `table`, `virtual` | Standard rounded rect (current style) |

This gives users two redundant channels (color + shape) to identify type at a glance,
which also helps with colorblindness.

### 4.4 Qualified Labels for Duplicates

When two or more nodes share the same `name`, qualify them with their parent's name:

```javascript
function qualifyLabels(nodes) {
  const nameCount = {};
  for (const n of nodes) nameCount[n.name] = (nameCount[n.name] || 0) + 1;
  for (const n of nodes) {
    if (nameCount[n.name] > 1 && n.parent_id) {
      const parentName = nodeById[n.parent_id]?.name;
      if (parentName) n._displayLabel = `${parentName}/${n.name}`;
    }
    n._displayLabel ??= n.name;
  }
}
```

This resolves the screenshot's duplicate `OrderRequest`, `OrderSummary`, `services`,
`models`, `utils`, `configs` ambiguity.

---

## 5. Interaction Layer

### 5.1 Hover → Highlight Neighbors

When the mouse enters a node, highlight it and its direct neighbors. Dim everything else
to ~15% opacity.

```javascript
renderer.on('enterNode', ({ node }) => {
  const neighbors = new Set(graph.neighbors(node));
  neighbors.add(node);
  graph.forEachNode((id, attrs) => {
    graph.setNodeAttribute(id, 'dimmed', !neighbors.has(id));
  });
  graph.forEachEdge((edge, attrs, src, tgt) => {
    graph.setEdgeAttribute(edge, 'hidden',
      !neighbors.has(src) || !neighbors.has(tgt));
  });
  renderer.refresh();
});

renderer.on('leaveNode', () => {
  graph.forEachNode((id) => graph.removeNodeAttribute(id, 'dimmed'));
  graph.forEachEdge((edge) => graph.setEdgeAttribute(edge, 'hidden',
    EDGE_STYLES[graph.getEdgeAttribute(edge, 'label')]?.hidden ?? false));
  renderer.refresh();
});
```

The `nodeReducer` then applies `opacity: 0.15` when `dimmed` is set.

### 5.2 Click → Select + Sidebar Detail

No change from current behavior — clicking a node populates the sidebar panel. But the
node gets a bright highlight ring to indicate selection:

```javascript
// In nodeReducer:
if (node === selectedNode) {
  return { ...data, size: data.size * 1.3, zIndex: 10 };
}
```

### 5.3 Zoom Controls

Three buttons overlaid at bottom-left of the graph canvas:

```html
<div id="zoom-controls">
  <button onclick="renderer.getCamera().animatedZoom({ duration: 200 })">+</button>
  <button onclick="renderer.getCamera().animatedUnzoom({ duration: 200 })">−</button>
  <button onclick="renderer.getCamera().animatedReset({ duration: 200 })">⊡</button>
</div>
```

---

## 6. Filter Controls

### 6.1 UI: Chip Bar

A horizontal bar of toggleable chips at the top of the graph canvas:

```
┌──────────────────────────────────────────────────────────────────┐
│ [◆ classes] [ƒ functions] [→ methods] [📁 dirs]  │  [→ imports] [◇ inherits] [⊂ contains]  │
└──────────────────────────────────────────────────────────────────┘
```

Left group: node type toggles. Right group: edge type toggles.

Each chip shows its type color as a small swatch so the chip bar doubles as a **legend**.

### 6.2 State

```javascript
const filterState = {
  hiddenNodeTypes: new Set(),                 // e.g., Set(['section', 'table'])
  hiddenEdgeTypes: new Set(['contains']),     // contains hidden by default
};
```

### 6.3 Applying Filters

```javascript
function applyFilters() {
  graph.forEachNode((id, attrs) => {
    const hidden = filterState.hiddenNodeTypes.has(attrs.node_type)
                   || attrs.node_type === '__label__' && false; // labels always visible
    graph.setNodeAttribute(id, 'hidden', hidden);
  });
  graph.forEachEdge((edge, attrs) => {
    const hidden = filterState.hiddenEdgeTypes.has(attrs.label);
    graph.setEdgeAttribute(edge, 'hidden', hidden);
  });
  renderer.refresh();
}
```

Chip click handler toggles the set and calls `applyFilters()`.

---

## 7. File Scope

All changes are in **one file**: `src/remora/web/static/index.html`.

### 7.1 What Gets Replaced

| Section | Current Lines | Change |
|---------|--------------|--------|
| CSS variables | 10–24 | Add `--directory`, `--virtual` vars |
| Layout constants | 257–276 | Replace all `FILE_BAND_*`, `DEPTH_*`, `TYPE_TRACK_*` with `LAYOUT` object |
| `loadGraph()` positioning | 479–516 | Rewrite with file-column grid algorithm |
| File band label nodes | 519–547 | Replace with directory spanning-header logic |
| `drawNodeBoxLabel()` | 293–329 | Extend with type-based shape + color |
| Sigma constructor | 331–347 | Add `edgeReducer`, update `nodeReducer` |
| Event handlers | 828–841 | Add `enterNode`/`leaveNode` for hover highlight |

### 7.2 What Gets Added

| Addition | Location |
|----------|----------|
| `EDGE_STYLES` constant | After `colorByType` (~line 358) |
| `layoutNodes()` function | Replace current positioning in `loadGraph()` |
| `qualifyLabels()` function | Called in `loadGraph()` before adding nodes |
| `resolveRowCollisions()` function | Called at end of layout |
| Filter chip HTML + CSS | Inserted before `<div id="graph">` |
| Zoom control HTML + CSS | Inserted after `<div id="graph">` |
| `filterState` + `applyFilters()` | After Sigma constructor |
| Hover highlight handlers | After click handlers |

### 7.3 What Stays the Same

- Sidebar structure, agent panel, events, timeline — unchanged.
- SSE event handling — unchanged.
- API endpoints — unchanged.
- Hit-testing logic — unchanged (still uses `nodeLabelHitboxes`).
- `drawRoundedRect()` — unchanged (reused for all shapes).

---

## 8. Determinism Guarantee

### 8.1 Definition

> For any set of nodes N and edges E, the layout function `layoutNodes(N)` produces
> identical `(x, y)` coordinates for every node, regardless of:
> - The order nodes arrived via SSE
> - The wall-clock time of discovery
> - The number of times the page has been refreshed
> - Whether the demo was torn down and restarted

### 8.2 How It's Achieved

1. **Sort-based column assignment**: Columns assigned by `file_path.sort()`, not insertion
   order.
2. **Sort-based row assignment**: Within-column slots assigned by
   `(depth, start_line, name)` sort.
3. **No randomness**: No `Math.random()`, no hash jitter, no `Date.now()` in positions.
4. **Full re-layout on discovery**: When a `node_discovered` SSE event arrives, the
   current `loadGraph()` already re-fetches all nodes from `/api/nodes` and rebuilds from
   scratch. The new layout function is a pure function of that complete node set, so
   incremental arrivals produce the same final layout.
5. **Label measurement is pure**: `measureText()` returns the same width for the same
   string and font on the same browser.

### 8.3 Edge Case: Incremental Discovery

During live discovery, the graph builds up over a few seconds as nodes stream in. Each
`node_discovered` event triggers a full `loadGraph()` which re-fetches the complete node
set from the API and re-runs the layout. This means early frames may show a partial graph
that shifts as more nodes arrive, but once discovery is complete, the layout is stable and
identical across restarts.

This is acceptable because:
- Discovery typically completes in <2 seconds for a project.
- The final resting state is always the same.
- There's no animation that depends on the *sequence* of arrivals.
