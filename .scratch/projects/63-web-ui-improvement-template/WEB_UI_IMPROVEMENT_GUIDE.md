# Web UI Improvement Guide

Step-by-step implementation guide for the graph view overhaul described in `CONCEPT.md`.
Every change is in a single file: `src/remora/web/static/index.html`.

Work through these steps in order. Each step is self-contained and produces a testable
intermediate state. After each step, reload the web UI and verify the described outcome
before proceeding.

## Table of Contents

- [Step 0: Orientation](#step-0-orientation)
- [Step 1: Add CSS Variables](#step-1-add-css-variables)
- [Step 2: Add Filter Bar and Zoom Control HTML](#step-2-add-filter-bar-and-zoom-control-html)
- [Step 3: Add Filter Bar and Zoom Control CSS](#step-3-add-filter-bar-and-zoom-control-css)
- [Step 4: Replace Layout Constants](#step-4-replace-layout-constants)
- [Step 5: Add Edge Style Constants](#step-5-add-edge-style-constants)
- [Step 6: Add the `qualifyLabels` Function](#step-6-add-the-qualifylabels-function)
- [Step 7: Write the `layoutNodes` Function](#step-7-write-the-layoutnodes-function)
- [Step 8: Rewrite `loadGraph` to Use the New Layout](#step-8-rewrite-loadgraph-to-use-the-new-layout)
- [Step 9: Rewrite `drawNodeBoxLabel` for Type-Based Shapes](#step-9-rewrite-drawnodeboxlabel-for-type-based-shapes)
- [Step 10: Update the Sigma Constructor](#step-10-update-the-sigma-constructor)
- [Step 11: Update `nodeColor` for the New Type Palette](#step-11-update-nodecolor-for-the-new-type-palette)
- [Step 12: Add Filter State and `applyFilters`](#step-12-add-filter-state-and-applyfilters)
- [Step 13: Wire Up Filter Chip Click Handlers](#step-13-wire-up-filter-chip-click-handlers)
- [Step 14: Add Hover Highlight Handlers](#step-14-add-hover-highlight-handlers)
- [Step 15: Wire Up Zoom Controls](#step-15-wire-up-zoom-controls)
- [Step 16: Clean Up Dead Code](#step-16-clean-up-dead-code)
- [Step 17: Verification Checklist](#step-17-verification-checklist)
- [Appendix A: Node Data Shape Reference](#appendix-a-node-data-shape-reference)
- [Appendix B: Complete Layout Algorithm Walkthrough](#appendix-b-complete-layout-algorithm-walkthrough)

---

## Step 0: Orientation

Before changing anything, understand the file structure. `index.html` is a single-file
app with three sections:

| Section | Lines | Contains |
|---------|-------|----------|
| `<style>` | 9–186 | All CSS (variables, layout, components) |
| `<body>` HTML | 188–251 | Graph container, sidebar with panels |
| `<script>` | 252–1106 | All JavaScript (graph, layout, SSE, UI) |

Key functions you'll be modifying or replacing:

| Function | Current Line | Role |
|----------|-------------|------|
| `drawNodeBoxLabel()` | 293–329 | Custom Sigma label renderer — draws the box around each node |
| `nodeColor()` | 360–376 | Returns border color for a node given its type and status |
| `hashNodeId()` | 378–384 | Hash function for deterministic jitter — **will be deleted** |
| `deterministicOffset()` | 386–389 | Jitter from hash — **will be deleted** |
| `fileBandKeyFromPath()` | 391–409 | Groups nodes into y-bands — **will be deleted** |
| `buildFileBands()` | 411–415 | Computes band y-offsets — **will be deleted** |
| `bandYForNode()` | 417–421 | Looks up band y — **will be deleted** |
| `loadGraph()` | 423–559 | Fetches nodes + edges, computes positions, adds to graphology |
| Sigma constructor | 331–347 | Creates the renderer — needs `edgeReducer` added |

The SSE event handlers (lines 921–1097), sidebar functions (lines 561–746), and
hit-testing (lines 748–826) are **not modified** except where noted.

---

## Step 1: Add CSS Variables

**File:** `index.html`
**Location:** Inside `:root { ... }` (lines 10–24)

Add new color variables for node types not currently covered, and a variable for the
virtual agent type. Insert these lines after line 23 (`--method: #22d3ee;`):

```css
      --directory: #94a3b8;
      --section: #fbbf24;
      --table: #34d399;
      --virtual: #f472b6;
```

The full `:root` block should now read:

```css
    :root {
      color-scheme: dark;
      --bg: #0a1018;
      --panel: #101826;
      --ink: #e5edf7;
      --muted: #9fb2c8;
      --line: #233247;
      --accent: #22d3ee;
      --running: #fb923c;
      --done: #34d399;
      --error: #f87171;
      --function: #60a5fa;
      --class: #a78bfa;
      --method: #22d3ee;
      --directory: #94a3b8;
      --section: #fbbf24;
      --table: #34d399;
      --virtual: #f472b6;
    }
```

**Verify:** Reload the page. Nothing should look different yet — these vars aren't
consumed until later steps.

---

## Step 2: Add Filter Bar and Zoom Control HTML

**Location:** Inside `<body>`, around line 188–189.

The current HTML is:

```html
<body>
  <div id="graph"></div>
  <aside id="sidebar">
```

Replace that opening `<body>` section with:

```html
<body>
  <div id="graph-container" style="position: relative; flex: 1; min-height: 100vh;">
    <div id="filter-bar">
      <div class="filter-group">
        <button class="filter-chip active" data-filter-node="directory">
          <span class="chip-swatch" style="background: var(--directory);"></span>
          dirs
        </button>
        <button class="filter-chip active" data-filter-node="class">
          <span class="chip-swatch" style="background: var(--class);"></span>
          classes
        </button>
        <button class="filter-chip active" data-filter-node="function">
          <span class="chip-swatch" style="background: var(--function);"></span>
          functions
        </button>
        <button class="filter-chip active" data-filter-node="method">
          <span class="chip-swatch" style="background: var(--method);"></span>
          methods
        </button>
        <button class="filter-chip active" data-filter-node="section">
          <span class="chip-swatch" style="background: var(--section);"></span>
          sections
        </button>
        <button class="filter-chip active" data-filter-node="virtual">
          <span class="chip-swatch" style="background: var(--virtual);"></span>
          virtual
        </button>
      </div>
      <div class="filter-separator"></div>
      <div class="filter-group">
        <button class="filter-chip" data-filter-edge="contains">
          <span class="chip-swatch" style="background: var(--muted);"></span>
          contains
        </button>
        <button class="filter-chip active" data-filter-edge="imports">
          <span class="chip-swatch" style="background: var(--function);"></span>
          imports
        </button>
        <button class="filter-chip active" data-filter-edge="inherits">
          <span class="chip-swatch" style="background: var(--class);"></span>
          inherits
        </button>
      </div>
    </div>
    <div id="graph"></div>
    <div id="zoom-controls">
      <button id="zoom-in" title="Zoom in">+</button>
      <button id="zoom-out" title="Zoom out">&minus;</button>
      <button id="zoom-reset" title="Fit to view">&#8862;</button>
    </div>
  </div>
  <aside id="sidebar">
```

**Important:** The `<div id="graph">` is now *inside* a `<div id="graph-container">`.
The sidebar `<aside>` follows immediately after `</div><!-- graph-container -->`.

Note: The `contains` chip starts **without** the `active` class (hidden by default).
All node-type chips and `imports`/`inherits` start with `active`.

**Verify:** The page should still render (the graph may look broken due to the extra
wrapper, but it won't crash). We'll fix the CSS next.

---

## Step 3: Add Filter Bar and Zoom Control CSS

**Location:** Inside `<style>`, before the closing `</style>` tag (line 186).

Add these rules at the end of the existing CSS block:

```css
    #graph-container {
      position: relative;
      flex: 1;
      min-height: 100vh;
    }
    #graph {
      flex: 1;
      width: 100%;
      height: 100%;
      position: absolute;
      top: 0;
      left: 0;
    }
    #filter-bar {
      position: absolute;
      top: 10px;
      left: 10px;
      z-index: 10;
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 6px 10px;
      background: rgba(16, 24, 38, 0.85);
      border: 1px solid var(--line);
      border-radius: 10px;
      backdrop-filter: blur(6px);
    }
    .filter-group {
      display: flex;
      gap: 4px;
    }
    .filter-separator {
      width: 1px;
      height: 20px;
      background: var(--line);
      margin: 0 4px;
    }
    .filter-chip {
      display: flex;
      align-items: center;
      gap: 4px;
      padding: 4px 8px;
      border-radius: 6px;
      font-size: 0.72rem;
      font-family: inherit;
      cursor: pointer;
      border: 1px solid var(--line);
      background: transparent;
      color: var(--muted);
      transition: opacity 0.15s, background 0.15s;
      opacity: 0.45;
    }
    .filter-chip.active {
      opacity: 1;
      background: rgba(255, 255, 255, 0.06);
      color: var(--ink);
    }
    .chip-swatch {
      display: inline-block;
      width: 8px;
      height: 8px;
      border-radius: 2px;
    }
    #zoom-controls {
      position: absolute;
      bottom: 16px;
      left: 16px;
      z-index: 10;
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
    #zoom-controls button {
      width: 32px;
      height: 32px;
      padding: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 1.1rem;
      border-radius: 8px;
      border: 1px solid var(--line);
      background: rgba(16, 24, 38, 0.85);
      color: var(--ink);
      cursor: pointer;
      backdrop-filter: blur(6px);
    }
    #zoom-controls button:hover {
      background: rgba(34, 211, 238, 0.15);
    }
```

Also **update** the existing `#graph` rule (line 34). The original rule is:

```css
    #graph { flex: 1; min-height: 100vh; }
```

**Delete** this original rule — it's superseded by the new `#graph` rule above.

**Verify:** Reload. You should see the filter chip bar in the top-left corner of the
graph area and three small zoom buttons in the bottom-left. They don't do anything yet.

---

## Step 4: Replace Layout Constants

**Location:** Inside `<script>`, lines 257–276.

**Delete** these lines entirely:

```javascript
    const FILE_BAND_SPACING = 4.4;
    const DEPTH_ROW_SPACING = 1.7;
    const LEVEL_SPREAD = 2.4;
    const SIBLING_SPREAD = 1.8;
    const HASH_X_SPREAD = 1.8;
    const DEPTH_WAVE_AMPLITUDE = 2.5;
    const DEPTH_X_FANOUT = 0.8;
    const DEPTH_ZIGZAG_SPREAD = 1.35;
    const FILE_HEADER_OFFSET_Y = -1.3;
    const FILE_HEADER_X = -9.0;
    const UNFILED_BAND_Y = 0;
    const TYPE_TRACK_OFFSETS = Object.freeze({
      directory: -6.5,
      file: -3.4,
      class: -1.2,
      function: 1.6,
      method: 4.2,
      section: 6.0,
      table: 6.0,
    });
```

**Replace** with the new layout constants object:

```javascript
    const LAYOUT = Object.freeze({
      COL_PAD: 3.0,
      ROW_HEIGHT: 2.2,
      SUB_ROW_HEIGHT: 1.6,
      DIR_HEADER_GAP: 1.2,
      MIN_COL_WIDTH: 4.0,
      PX_PER_UNIT: 14,
      LABEL_PAD_PX: 20,
    });
```

**What these mean:**

| Constant | Purpose |
|----------|---------|
| `COL_PAD` | Horizontal gap between file columns (graph units) |
| `ROW_HEIGHT` | Vertical spacing per tree depth level |
| `SUB_ROW_HEIGHT` | Vertical spacing between siblings at the same depth within a column |
| `DIR_HEADER_GAP` | Extra y-offset pulling directory headers above their children |
| `MIN_COL_WIDTH` | Floor for column width so narrow labels don't collapse |
| `PX_PER_UNIT` | Approximate conversion from pixel label widths to graph units |
| `LABEL_PAD_PX` | Pixel padding added to text width when measuring label boxes |

**Verify:** The page will break at this point (the old constants are referenced by code
we haven't replaced yet). That's expected — continue to the next step.

---

## Step 5: Add Edge Style Constants

**Location:** After the `colorByType` object (currently around line 354–358).

Insert this block immediately after the `colorByType` closing brace:

```javascript
    const EDGE_STYLES = Object.freeze({
      contains: { color: "#233247", size: 0.5, hidden: true,  type: "line"  },
      imports:  { color: "#60a5fa", size: 1.8, hidden: false, type: "arrow" },
      inherits: { color: "#a78bfa", size: 1.8, hidden: false, type: "arrow" },
    });
    const DEFAULT_EDGE_STYLE = Object.freeze({
      color: "#3a4f6a", size: 1, hidden: false, type: "line",
    });
```

**What this does:** Defines how each edge type renders. `contains` edges are hidden by
default (the layout communicates containment spatially). `imports` and `inherits` are
visible as colored arrows.

The `type: "arrow"` value tells Sigma to use its built-in `EdgeArrow` WebGL program,
which draws a small arrowhead at the target end.

---

## Step 6: Add the `qualifyLabels` Function

**Location:** After the `EDGE_STYLES` block you just added, before `nodeColor()`.

```javascript
    function qualifyLabels(nodes, nodeById) {
      const nameCount = {};
      for (const n of nodes) {
        nameCount[n.name] = (nameCount[n.name] || 0) + 1;
      }
      for (const n of nodes) {
        if (nameCount[n.name] > 1 && n.parent_id) {
          const parent = nodeById[n.parent_id];
          if (parent) {
            n._displayLabel = parent.name + "/" + n.name;
            continue;
          }
        }
        n._displayLabel = n.name;
      }
    }
```

**What this does:** When two or more nodes share the same `name` (e.g., `OrderRequest`
appears in both `services/orders.py` and `models/orders.py`), this prefixes each with
its parent's name → `services/OrderRequest` vs `models/OrderRequest`.

Nodes with unique names keep their bare name as the display label.

**Verify:** No visible change yet — this function isn't called until Step 8.

---

## Step 7: Write the `layoutNodes` Function

This is the core replacement for the old positioning logic. **Location:** After
`qualifyLabels()`, before `loadGraph()`.

```javascript
    function measureLabelWidth(text) {
      labelMeasureContext.font = '500 12px "IBM Plex Mono", "IBM Plex Sans", sans-serif';
      return labelMeasureContext.measureText(String(text)).width + LAYOUT.LABEL_PAD_PX;
    }

    function layoutNodes(nodes, nodeById) {
      // --- 1. Compute tree depth for every node ---
      const depthOf = {};
      const visiting = new Set();
      function computeDepth(nodeId) {
        if (depthOf[nodeId] !== undefined) return depthOf[nodeId];
        if (visiting.has(nodeId)) return 0;
        visiting.add(nodeId);
        const node = nodeById[nodeId];
        if (!node || !node.parent_id || !nodeById[node.parent_id]) {
          depthOf[nodeId] = 0;
        } else {
          depthOf[nodeId] = computeDepth(node.parent_id) + 1;
        }
        visiting.delete(nodeId);
        return depthOf[nodeId];
      }
      for (const n of nodes) computeDepth(n.node_id);

      // --- 2. Identify file-rooted subtrees ---
      // A "file node" is any non-directory node whose parent is a directory (or null).
      // We group all nodes by the file_path they belong to.
      // Directories are handled separately as spanning headers.
      const directories = [];
      const fileGroups = {};  // file_path → [node, ...]
      for (const n of nodes) {
        if (n.node_type === "directory") {
          directories.push(n);
          continue;
        }
        const fp = n.file_path || "__unfiled__";
        (fileGroups[fp] ||= []).push(n);
      }

      // --- 3. Sort file columns deterministically ---
      const sortedFilePaths = Object.keys(fileGroups).sort();

      // --- 4. Measure column widths ---
      const colWidths = sortedFilePaths.map(fp => {
        const groupNodes = fileGroups[fp];
        let maxPx = 0;
        for (const n of groupNodes) {
          const px = measureLabelWidth(n._displayLabel || n.name);
          if (px > maxPx) maxPx = px;
        }
        return Math.max(LAYOUT.MIN_COL_WIDTH, maxPx / LAYOUT.PX_PER_UNIT);
      });

      // --- 5. Compute column x-centers (cumulative widths + padding) ---
      const colX = [];
      const fileToCol = {};  // file_path → column index
      let xCursor = 0;
      for (let i = 0; i < sortedFilePaths.length; i++) {
        colX.push(xCursor + colWidths[i] / 2);
        fileToCol[sortedFilePaths[i]] = i;
        xCursor += colWidths[i] + LAYOUT.COL_PAD;
      }

      // --- 6. Position non-directory nodes within their file column ---
      // Sort each file group by (depth, start_line, name) for deterministic
      // vertical slot assignment.
      const positions = new Map();  // node_id → { x, y }
      for (let ci = 0; ci < sortedFilePaths.length; ci++) {
        const group = fileGroups[sortedFilePaths[ci]];
        group.sort((a, b) =>
          (depthOf[a.node_id] - depthOf[b.node_id])
          || (a.start_line - b.start_line)
          || a.name.localeCompare(b.name)
        );

        // Assign y-slots. Nodes at the same depth get incrementing sub-slots.
        let prevDepth = -1;
        let slotInDepth = 0;
        for (const n of group) {
          const d = depthOf[n.node_id];
          if (d === prevDepth) {
            slotInDepth++;
          } else {
            slotInDepth = 0;
            prevDepth = d;
          }
          const y = d * LAYOUT.ROW_HEIGHT + slotInDepth * LAYOUT.SUB_ROW_HEIGHT;
          positions.set(n.node_id, { x: colX[ci], y });
        }
      }

      // --- 7. Position directory nodes as spanning headers ---
      // A directory's x is the midpoint of the column range of its descendants.
      // Its y is based on its depth, pulled up by DIR_HEADER_GAP.
      // Sort directories deepest-first so inner dirs are placed before outer ones.
      directories.sort((a, b) => (depthOf[b.node_id] - depthOf[a.node_id])
        || a.name.localeCompare(b.name));

      for (const dir of directories) {
        const childXValues = [];
        // Collect x-positions of all direct and transitive descendants
        for (const [nid, pos] of positions.entries()) {
          const n = nodeById[nid];
          if (!n) continue;
          // Walk up parent chain to see if this node descends from dir
          let current = n;
          while (current) {
            if (current.parent_id === dir.node_id) {
              childXValues.push(pos.x);
              break;
            }
            current = current.parent_id ? nodeById[current.parent_id] : null;
          }
        }
        // Also include positions of child directories already placed
        for (const otherDir of directories) {
          if (otherDir.parent_id === dir.node_id && positions.has(otherDir.node_id)) {
            childXValues.push(positions.get(otherDir.node_id).x);
          }
        }

        if (childXValues.length > 0) {
          const minX = Math.min(...childXValues);
          const maxX = Math.max(...childXValues);
          const x = (minX + maxX) / 2;
          const y = depthOf[dir.node_id] * LAYOUT.ROW_HEIGHT - LAYOUT.DIR_HEADER_GAP;
          positions.set(dir.node_id, { x, y });
        } else {
          // Orphan directory with no discovered children — place at depth row
          positions.set(dir.node_id, {
            x: 0,
            y: depthOf[dir.node_id] * LAYOUT.ROW_HEIGHT,
          });
        }
      }

      return positions;
    }
```

**How this works, in plain English:**

1. Compute each node's depth in the containment tree (same recursive algorithm as before).
2. Separate directory nodes from everything else.
3. Group non-directory nodes by `file_path`. Each group becomes a vertical column.
4. Sort the columns alphabetically by file path → deterministic column order.
5. Measure the widest label in each column → adaptive column widths.
6. Lay out cumulative x-positions so columns don't overlap.
7. Within each column, sort nodes by `(depth, start_line, name)` and assign y-slots.
   Multiple nodes at the same depth in the same column get incrementing sub-slots.
8. Finally, position directory nodes as spanning headers centered above their descendants.

**Verify:** Not testable yet — `loadGraph()` still uses the old code. Continue to Step 8.

---

## Step 8: Rewrite `loadGraph` to Use the New Layout

**Location:** The `loadGraph()` function, currently lines 423–559.

**Replace the entire function** with:

```javascript
    async function loadGraph() {
      const nodesResp = await fetch("/api/nodes");
      const nodes = await nodesResp.json();
      const nodeById = Object.fromEntries(nodes.map(n => [n.node_id, n]));

      // Qualify duplicate names before layout measures labels
      qualifyLabels(nodes, nodeById);

      // Compute deterministic positions
      const positions = layoutNodes(nodes, nodeById);

      // Clear and rebuild the graphology graph
      graph.clear();

      // Add nodes
      for (const node of nodes) {
        const pos = positions.get(node.node_id);
        if (!pos) continue;
        const label = node._displayLabel || node.name;
        graph.addNode(node.node_id, {
          node_id: node.node_id,
          label: label,
          forceLabel: true,
          size: node.node_type === "directory" ? 3.0 : 2.4,
          x: pos.x,
          y: pos.y,
          color: nodeColor(node.node_type, node.status),
          node_type: node.node_type,
          file_path: node.file_path || "",
          status: node.status,
        });
      }

      // Add edges
      const edgeResp = await fetch("/api/edges");
      const edges = await edgeResp.json();
      for (const edge of edges) {
        const key = edge.from_id + "->" + edge.to_id + ":" + edge.edge_type;
        if (!graph.hasNode(edge.from_id) || !graph.hasNode(edge.to_id)) continue;
        if (!graph.hasEdge(key)) {
          graph.addEdgeWithKey(key, edge.from_id, edge.to_id, {
            label: edge.edge_type,
            size: 1,
          });
        }
      }

      // Apply current filter state
      applyFilters();
      renderer.refresh();
    }
```

**Key differences from the old `loadGraph`:**

1. Calls `qualifyLabels()` to disambiguate duplicate names.
2. Calls `layoutNodes()` for all positioning — no inline position math.
3. Uses `graph.clear()` on each call so incremental discovery rebuilds cleanly.
4. Stores `node.status` on the graphology node (needed by the new `nodeReducer`).
5. No more file-band label nodes (`__label__` synthetic nodes) — directories serve as
   their own headers now.
6. Calls `applyFilters()` at the end (defined in Step 12).

**Verify:** The page will error because `applyFilters` doesn't exist yet. That's fine —
we'll add it in Step 12. If you want to test now, temporarily replace `applyFilters();`
with nothing.

---

## Step 9: Rewrite `drawNodeBoxLabel` for Type-Based Shapes

**Location:** The `drawNodeBoxLabel` function, currently lines 293–329.

**Replace** with:

```javascript
    function drawNodeBoxLabel(context, data) {
      if (!data.label || data.hidden) return;

      const nodeType = data.node_type || "";
      const text = String(data.label);

      // --- Font sizing by type ---
      let fontSize = 12;
      let fontWeight = "500";
      if (nodeType === "directory") {
        fontSize = 13;
        fontWeight = "700";
      }

      const padX = 10;
      const padY = 5;

      context.save();
      context.font = fontWeight + " " + fontSize + 'px "IBM Plex Mono", "IBM Plex Sans", sans-serif';
      const textWidth = context.measureText(text).width;
      const boxWidth = textWidth + padX * 2;
      const boxHeight = fontSize + padY * 2;
      const x = data.x - boxWidth / 2;
      const y = data.y - boxHeight / 2;

      // --- Determine border radius by shape ---
      let borderRadius = 8;
      if (nodeType === "function" || nodeType === "method") {
        borderRadius = boxHeight / 2;  // pill shape
      } else if (nodeType === "directory") {
        borderRadius = 6;
      }

      // --- Determine fill color ---
      const fillColors = {
        directory: "rgba(148, 163, 184, 0.10)",
        class:     "rgba(167, 139, 250, 0.10)",
        function:  "rgba(96, 165, 250, 0.10)",
        method:    "rgba(34, 211, 238, 0.10)",
        section:   "rgba(251, 191, 36, 0.10)",
        table:     "rgba(52, 211, 153, 0.10)",
        virtual:   "rgba(244, 114, 182, 0.10)",
      };
      const fillColor = fillColors[nodeType] || "rgba(10, 16, 24, 0.9)";

      // --- Draw the box ---
      drawRoundedRect(context, x, y, boxWidth, boxHeight, borderRadius);
      context.fillStyle = fillColor;
      context.fill();

      // --- Border: use data.color (set by nodeColor/nodeReducer) ---
      context.strokeStyle = data.color || "#22d3ee";
      context.lineWidth = (nodeType === "directory") ? 2.0 : 1.4;

      // Dashed border for methods and awaiting statuses
      if (nodeType === "method" ||
          data.status === "awaiting_input" ||
          data.status === "awaiting_review") {
        context.setLineDash([4, 3]);
      }
      context.stroke();
      context.setLineDash([]);

      // --- Double border for classes ---
      if (nodeType === "class") {
        drawRoundedRect(context, x + 3, y + 3, boxWidth - 6, boxHeight - 6, borderRadius - 2);
        context.strokeStyle = data.color || "#a78bfa";
        context.lineWidth = 0.8;
        context.stroke();
      }

      // --- Draw text ---
      context.fillStyle = (data.dimmed) ? "rgba(229, 237, 247, 0.15)" : "#e5edf7";
      context.textAlign = "center";
      context.textBaseline = "middle";
      context.fillText(text, data.x, data.y);

      // --- Record hitbox for click detection ---
      if (data.node_id) {
        nodeLabelHitboxes.set(data.node_id, {
          x, y,
          width: boxWidth,
          height: boxHeight,
          area: boxWidth * boxHeight,
        });
      }

      context.restore();
    }
```

**What changed:**

| Aspect | Before | After |
|--------|--------|-------|
| Shape | Uniform rounded rect for all nodes | Pill for functions/methods, double-border for classes, bold rect for directories |
| Fill | `rgba(10, 16, 24, 0.9)` for all | Per-type tinted fill (subtle type-colored background) |
| Border width | 1 or 1.4 for all | 2.0 for directories, 1.4 for others |
| Dashed border | Never | Methods, `awaiting_input`, `awaiting_review` |
| Double border | Never | Classes get an inner border ring |
| Dim support | No | Checks `data.dimmed` flag for text opacity |
| Font size | 11–12 | 13 bold for directories, 12 for rest |

---

## Step 10: Update the Sigma Constructor

**Location:** The `new Sigma(...)` call, currently lines 331–347.

**Replace** with:

```javascript
    const renderer = new Sigma(graph, document.getElementById("graph"), {
      labelRenderedSizeThreshold: 0,
      defaultDrawNodeLabel: drawNodeBoxLabel,
      defaultEdgeType: "arrow",
      zIndex: true,
      nodeReducer: (node, data) => {
        const result = { ...data };
        // Dim non-neighbors when hovering (set by enterNode handler)
        if (data.dimmed) {
          result.color = "rgba(100, 116, 139, 0.2)";
          result.label = data.label;
          result.forceLabel = true;
        }
        // Highlight selected node
        if (node === selectedNode) {
          result.size = (data.size || 2.4) * 1.3;
          result.zIndex = 10;
        }
        return result;
      },
      edgeReducer: (edge, data) => {
        const style = EDGE_STYLES[data.label] || DEFAULT_EDGE_STYLE;
        return {
          ...data,
          color: style.color,
          size: style.size,
          type: style.type,
          hidden: data.hidden ?? style.hidden,
        };
      },
    });
```

**What changed:**

| Aspect | Before | After |
|--------|--------|-------|
| `defaultEdgeType` | Not set (defaults to "line") | `"arrow"` — edges get arrowheads |
| `edgeReducer` | Not set | Applies `EDGE_STYLES` per edge type — colors, sizes, visibility |
| `nodeReducer` | Only handled `__label__` type | Handles dimming (for hover) and selected node highlight |
| `__label__` handling | Explicit branch | Removed — we no longer use synthetic `__label__` nodes |

---

## Step 11: Update `nodeColor` for the New Type Palette

**Location:** The `colorByType` object and `nodeColor()` function (around lines 354–376).

**Replace** `colorByType` with:

```javascript
    const colorByType = {
      directory: getComputedStyle(document.documentElement).getPropertyValue("--directory").trim(),
      function: getComputedStyle(document.documentElement).getPropertyValue("--function").trim(),
      class: getComputedStyle(document.documentElement).getPropertyValue("--class").trim(),
      method: getComputedStyle(document.documentElement).getPropertyValue("--method").trim(),
      section: getComputedStyle(document.documentElement).getPropertyValue("--section").trim(),
      table: getComputedStyle(document.documentElement).getPropertyValue("--table").trim(),
      virtual: getComputedStyle(document.documentElement).getPropertyValue("--virtual").trim(),
    };
```

**Replace** `nodeColor()` with:

```javascript
    function nodeColor(nodeType, status) {
      if (status === "running") return colorByType.function || "#fb923c";
      if (status === "awaiting_input" || status === "awaiting_review") return "#fbbf24";
      if (status === "error") return colorByType.virtual || "#f87171";
      return colorByType[nodeType] || "#818cf8";
    }
```

**What changed:** The idle state now returns the type-specific color directly (including
`directory`, `section`, `table`, `virtual`). Running uses blue (function color) and
error uses pink (virtual color) as accents. The `--done` and `--running` CSS variable
reads were replaced with direct references for simplicity.

---

## Step 12: Add Filter State and `applyFilters`

**Location:** After the Sigma constructor and the `selectedNode` / cache declarations
(around line 348–352 in the original, after the code from Steps 10–11).

Insert:

```javascript
    const filterState = {
      hiddenNodeTypes: new Set(),
      hiddenEdgeTypes: new Set(["contains"]),
    };

    function applyFilters() {
      graph.forEachNode((id, attrs) => {
        const shouldHide = filterState.hiddenNodeTypes.has(attrs.node_type);
        graph.setNodeAttribute(id, "hidden", shouldHide);
      });
      graph.forEachEdge((edge, attrs) => {
        const edgeType = attrs.label;
        const baseHidden = EDGE_STYLES[edgeType]?.hidden ?? false;
        const filterHidden = filterState.hiddenEdgeTypes.has(edgeType);
        graph.setEdgeAttribute(edge, "hidden", baseHidden || filterHidden);
      });
      renderer.refresh();
    }
```

**What this does:**

- `filterState.hiddenNodeTypes` tracks which node types are toggled off. Starts empty
  (all types visible).
- `filterState.hiddenEdgeTypes` tracks which edge types are toggled off. Starts with
  `"contains"` (hidden by default, matching the `contains` chip starting without `active`).
- `applyFilters()` walks all nodes and edges, setting `hidden` based on the filter state.
  For edges, it also respects the base `EDGE_STYLES` hidden default.

**Verify:** Reload the page. The graph should now render with the new layout! `contains`
edges should be hidden. `imports` edges should appear as blue arrows. `inherits` edges
should appear as purple arrows. Nodes should be arranged in file columns.

---

## Step 13: Wire Up Filter Chip Click Handlers

**Location:** After the existing click handlers (after the `agent-stream` click handler
block, around line 908 in the original).

Add:

```javascript
    document.getElementById("filter-bar").addEventListener("click", (event) => {
      const chip = event.target.closest(".filter-chip");
      if (!chip) return;

      const nodeType = chip.dataset.filterNode;
      const edgeType = chip.dataset.filterEdge;

      if (nodeType) {
        chip.classList.toggle("active");
        if (filterState.hiddenNodeTypes.has(nodeType)) {
          filterState.hiddenNodeTypes.delete(nodeType);
        } else {
          filterState.hiddenNodeTypes.add(nodeType);
        }
      }

      if (edgeType) {
        chip.classList.toggle("active");
        if (filterState.hiddenEdgeTypes.has(edgeType)) {
          filterState.hiddenEdgeTypes.delete(edgeType);
        } else {
          filterState.hiddenEdgeTypes.add(edgeType);
        }
      }

      applyFilters();
    });
```

**How it works:** Uses event delegation on the filter bar. When a chip is clicked:
1. Toggles the `active` CSS class (visual on/off state).
2. Adds or removes the type from the appropriate hidden set.
3. Calls `applyFilters()` to update the graph.

**Verify:** Click the filter chips. Toggling "dirs" off should hide all directory nodes.
Toggling "contains" on should show the structural edges (gray, thin). Toggling "imports"
off should hide the blue arrows.

---

## Step 14: Add Hover Highlight Handlers

**Location:** After the `clickStage` handler (around line 841 in the original), before
the `send-chat` handler.

Add:

```javascript
    let hoveredNode = null;

    renderer.on("enterNode", ({ node }) => {
      hoveredNode = node;
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
      hoveredNode = null;
      graph.forEachNode((id) => {
        graph.removeNodeAttribute(id, "dimmed");
      });
      // Restore edge visibility to filter-based state
      applyFilters();
    });
```

**What this does:**

When the mouse enters a node:
1. All non-neighbor nodes get `dimmed: true` (handled by `nodeReducer` → faded color,
   and by `drawNodeBoxLabel` → faded text).
2. All edges not connecting to the hovered node or its neighbors are hidden.

When the mouse leaves:
1. `dimmed` is removed from all nodes.
2. `applyFilters()` restores edge visibility to the filter-bar state.

**Verify:** Hover over a node. Its neighbors should stay bright while everything else
fades to ~20% opacity. Only edges connecting to the hovered node and its neighbors
remain visible. Moving the mouse away restores the full graph.

---

## Step 15: Wire Up Zoom Controls

**Location:** After the hover handlers, before the `send-chat` handler.

Add:

```javascript
    document.getElementById("zoom-in").addEventListener("click", () => {
      const camera = renderer.getCamera();
      camera.animatedZoom({ duration: 200 });
    });
    document.getElementById("zoom-out").addEventListener("click", () => {
      const camera = renderer.getCamera();
      camera.animatedUnzoom({ duration: 200 });
    });
    document.getElementById("zoom-reset").addEventListener("click", () => {
      const camera = renderer.getCamera();
      camera.animatedReset({ duration: 200 });
    });
```

**Verify:** Click `+` to zoom in, `-` to zoom out, and the square icon to reset to the
default view.

---

## Step 16: Clean Up Dead Code

Now that the new layout is in place, **delete** these functions that are no longer called
anywhere:

1. `hashNodeId()` (was ~line 378–384) — hash for deterministic jitter. No longer used.
2. `deterministicOffset()` (was ~line 386–389) — jitter from hash. No longer used.
3. `fileBandKeyFromPath()` (was ~line 391–409) — grouped nodes into y-bands. No longer used.
4. `buildFileBands()` (was ~line 411–415) — computed band y-offsets. No longer used.
5. `bandYForNode()` (was ~line 417–421) — looked up band y. No longer used.

To confirm these are safe to delete, search the file for each function name. None of
them should appear outside their own definition after the Step 8 rewrite of `loadGraph`.

**Verify:** Reload. Everything should still work. No console errors.

---

## Step 17: Verification Checklist

Run through this checklist after all steps are complete:

### Layout
- [ ] Nodes are arranged in vertical columns, one column per file.
- [ ] Columns are sorted alphabetically by file path (left to right).
- [ ] Within each column, nodes are sorted by source order (top to bottom).
- [ ] Directory nodes appear above their child files/columns, centered.
- [ ] No labels overlap or are truncated.
- [ ] Duplicate names are qualified (e.g., `services/OrderRequest` vs `models/OrderRequest`).

### Determinism
- [ ] Refresh the page 3 times. The layout is identical each time.
- [ ] Tear down the demo, restart it, and reload. The layout matches.

### Edges
- [ ] `contains` edges are hidden by default.
- [ ] `imports` edges appear as blue arrows.
- [ ] `inherits` edges appear as purple arrows.
- [ ] No spaghetti tangle of edges.

### Node Shapes
- [ ] Directories: bold border, larger font, rounded rect.
- [ ] Classes: double border (outer + inner ring), purple.
- [ ] Functions: pill shape (fully rounded ends), blue.
- [ ] Methods: pill shape, dashed border, cyan.
- [ ] Other types (section, table, virtual): standard rounded rect, type-colored.

### Filters
- [ ] Clicking a node-type chip toggles visibility of that type.
- [ ] Clicking an edge-type chip toggles visibility of that edge type.
- [ ] Chip visual state (bright vs dim) matches the filter state.
- [ ] `contains` chip starts inactive; all others start active.

### Hover
- [ ] Hovering a node dims non-neighbors and hides unrelated edges.
- [ ] Moving away restores the full graph.
- [ ] Hover + filter interact correctly (e.g., hover restores filter state on leave).

### Selection
- [ ] Clicking a node highlights it (slightly larger).
- [ ] Sidebar populates with node details and agent panel.

### Zoom
- [ ] `+` button zooms in.
- [ ] `-` button zooms out.
- [ ] Square button resets to fit-all view.
- [ ] Scroll-wheel zoom still works.

### SSE Events
- [ ] `node_discovered` events trigger a graph rebuild with correct layout.
- [ ] `agent_start` / `agent_complete` / `agent_error` correctly change node border colors.
- [ ] Events and timeline panels still update.

---

## Appendix A: Node Data Shape Reference

These are the fields available on each node object returned by `GET /api/nodes`:

```javascript
{
  "node_id":     "path/to/file.py::ClassName",    // unique, deterministic
  "node_type":   "function"|"class"|"method"|"section"|"table"|"directory"|"virtual",
  "name":        "ClassName",                       // short name
  "full_name":   "ModuleName.ClassName",            // qualified name
  "file_path":   "src/services/orders.py",          // source file
  "start_line":  42,                                // 1-indexed
  "end_line":    87,
  "start_byte":  1200,
  "end_byte":    2400,
  "text":        "class ClassName:\n  ...",          // full source text
  "source_hash": "abc123...",                        // SHA-256 of text
  "parent_id":   "path/to/file.py::Module" | null,  // containment parent
  "status":      "idle"|"running"|"error"|"awaiting_input"|"awaiting_review",
  "role":        "code-agent" | null                 // bundle role
}
```

Edge objects from `GET /api/edges`:

```javascript
{
  "from_id":    "path/to/file.py::ClassName",
  "to_id":      "path/to/other.py::OtherClass",
  "edge_type":  "contains"|"imports"|"inherits"
}
```

---

## Appendix B: Complete Layout Algorithm Walkthrough

Given this example project:

```
src/
  services/
    orders.py     → OrderRequest, OrderSummary, create_order
    pricing.py    → PricingRule, apply_tax
  utils/
    formatting.py → format_usd
```

**Step 1 — Depths:**

| Node | Depth |
|------|-------|
| `src/` (directory) | 0 |
| `src/services/` (directory) | 1 |
| `src/utils/` (directory) | 1 |
| `orders.py` (file-level nodes) | 2 |
| `pricing.py` (file-level nodes) | 2 |
| `formatting.py` (file-level nodes) | 2 |
| `OrderRequest` (class) | 3 |
| `OrderSummary` (class) | 3 |
| `create_order` (function) | 3 |
| `PricingRule` (class) | 3 |
| `apply_tax` (function) | 3 |
| `format_usd` (function) | 3 |

**Step 2 — File groups (non-directories):**

```
"src/services/orders.py"     → [OrderRequest, OrderSummary, create_order]
"src/services/pricing.py"    → [PricingRule, apply_tax]
"src/utils/formatting.py"    → [format_usd]
```

**Step 3 — Sorted file columns:**

```
Column 0: src/services/orders.py
Column 1: src/services/pricing.py
Column 2: src/utils/formatting.py
```

**Step 4 — Column widths (measured):**

```
Column 0: max(OrderRequest, OrderSummary, create_order) + pad → ~8.5 units
Column 1: max(PricingRule, apply_tax) + pad → ~7.0 units
Column 2: max(format_usd) + pad → ~6.0 units
```

**Step 5 — Column x-centers:**

```
Column 0: x = 4.25
Column 1: x = 4.25 + 8.5 + 3.0 + 3.5 = 15.75
Column 2: x = 15.75 + 7.0 + 3.0 + 3.0 = 25.25
```

**Step 6 — Node positions (within columns):**

Column 0 sorted by (depth, start_line, name):
```
OrderRequest:  x=4.25,  y = 3 * 2.2 + 0 * 1.6 = 6.6
OrderSummary:  x=4.25,  y = 3 * 2.2 + 1 * 1.6 = 8.2
create_order:  x=4.25,  y = 3 * 2.2 + 2 * 1.6 = 9.8
```

Column 1:
```
PricingRule:   x=15.75, y = 3 * 2.2 + 0 * 1.6 = 6.6
apply_tax:     x=15.75, y = 3 * 2.2 + 1 * 1.6 = 8.2
```

Column 2:
```
format_usd:    x=25.25, y = 3 * 2.2 + 0 * 1.6 = 6.6
```

**Step 7 — Directory positions:**

```
src/services/: x = (4.25 + 15.75) / 2 = 10.0,  y = 1 * 2.2 - 1.2 = 1.0
src/utils/:    x = 25.25,                        y = 1 * 2.2 - 1.2 = 1.0
src/:          x = (10.0 + 25.25) / 2 = 17.625, y = 0 * 2.2 - 1.2 = -1.2
```

**Final visual:**

```
y=-1.2  ·                  [src/]
y= 1.0  ·         [services/]                 [utils/]
y= 6.6  · [OrderRequest]   [PricingRule]   [format_usd]
y= 8.2  · [OrderSummary]   [apply_tax]
y= 9.8  · [create_order]
          ───────────────────────────────────────────────
          x=4.25            x=15.75         x=25.25
```

Every value is derived from sorts and measurements. No randomness. Same project → same
picture.
