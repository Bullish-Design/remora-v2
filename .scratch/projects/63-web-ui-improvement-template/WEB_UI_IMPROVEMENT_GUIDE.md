# Web UI Improvement Guide (v2)

Step-by-step implementation guide for the graph view overhaul described in `CONCEPT.md`.
Every change is in a single file: `src/remora/web/static/index.html`.

Work through these steps in order. Each step is self-contained and produces a testable
intermediate state.

**Changes from v1 guide:**
- Y-axis is negated so directories appear at top, leaf nodes at bottom.
- Directories are bounding boxes, not graph nodes.
- `contains` edges are never added to the graph — bounding boxes replace them.
- `qualifyLabels` has a fallback when parent name matches node name.
- Camera auto-fits after load.
- The `dirs` filter chip is replaced by a `filesystem` chip that toggles bounding boxes.

## Table of Contents

- [Step 0: Orientation](#step-0-orientation)
- [Step 1: Add CSS Variables](#step-1-add-css-variables)
- [Step 2: Add Filter Bar and Zoom Control HTML](#step-2-add-filter-bar-and-zoom-control-html)
- [Step 3: Add Filter Bar and Zoom Control CSS](#step-3-add-filter-bar-and-zoom-control-css)
- [Step 4: Replace Layout Constants](#step-4-replace-layout-constants)
- [Step 5: Add Edge Style Constants](#step-5-add-edge-style-constants)
- [Step 6: Add the `qualifyLabels` Function](#step-6-add-the-qualifylabels-function)
- [Step 7: Write the `measureLabelWidth` Helper](#step-7-write-the-measuelabelwidth-helper)
- [Step 8: Write the `layoutNodes` Function](#step-8-write-the-layoutnodes-function)
- [Step 9: Write the Bounding Box Functions](#step-9-write-the-bounding-box-functions)
- [Step 10: Rewrite `loadGraph`](#step-10-rewrite-loadgraph)
- [Step 11: Rewrite `drawNodeBoxLabel` for Type-Based Shapes](#step-11-rewrite-drawnodeboxlabel-for-type-based-shapes)
- [Step 12: Update the Sigma Constructor](#step-12-update-the-sigma-constructor)
- [Step 13: Update `nodeColor` for the New Type Palette](#step-13-update-nodecolor-for-the-new-type-palette)
- [Step 14: Add Filter State and `applyFilters`](#step-14-add-filter-state-and-applyfilters)
- [Step 15: Wire Up Filter Chip Click Handlers](#step-15-wire-up-filter-chip-click-handlers)
- [Step 16: Add Hover Highlight Handlers](#step-16-add-hover-highlight-handlers)
- [Step 17: Wire Up Zoom Controls](#step-17-wire-up-zoom-controls)
- [Step 18: Clean Up Dead Code](#step-18-clean-up-dead-code)
- [Step 19: Verification Checklist](#step-19-verification-checklist)
- [Appendix A: Node Data Shape Reference](#appendix-a-node-data-shape-reference)
- [Appendix B: Complete Layout Walkthrough](#appendix-b-complete-layout-walkthrough)

---

## Step 0: Orientation

`index.html` is a single-file app with three sections:

| Section | Lines | Contains |
|---------|-------|----------|
| `<style>` | 9–186 | All CSS |
| `<body>` HTML | 188–251 | Graph container, sidebar |
| `<script>` | 252–1106 | All JavaScript |

Key functions you'll modify or replace:

| Function | Current Line | Fate |
|----------|-------------|------|
| `drawRoundedRect()` | 278–291 | **Keep** — reused for node shapes and bounding boxes |
| `drawNodeBoxLabel()` | 293–329 | **Replace** — new type-based shapes + dimming |
| `nodeColor()` | 360–376 | **Replace** — expanded type palette |
| `hashNodeId()` | 378–384 | **Delete** — no more hash jitter |
| `deterministicOffset()` | 386–389 | **Delete** |
| `fileBandKeyFromPath()` | 391–409 | **Delete** |
| `buildFileBands()` | 411–415 | **Delete** |
| `bandYForNode()` | 417–421 | **Delete** |
| `loadGraph()` | 423–559 | **Replace** — new layout, no directory nodes, no contains edges |
| Sigma constructor | 331–347 | **Replace** — add `edgeReducer`, `beforeRender` for boxes |

SSE handlers (921–1097), sidebar functions (561–746), and hit-testing (748–826) are
**not modified** except where noted.

---

## Step 1: Add CSS Variables

**Location:** Inside `:root { ... }` (lines 10–24).

Add after line 23 (`--method: #22d3ee;`):

```css
      --section: #fbbf24;
      --table: #34d399;
      --virtual: #f472b6;
```

Note: No `--directory` variable needed — directories are bounding boxes, not nodes.

**Verify:** Reload. No visible change yet.

---

## Step 2: Add Filter Bar and Zoom Control HTML

**Location:** Inside `<body>`, around line 188–189.

Replace:

```html
<body>
  <div id="graph"></div>
  <aside id="sidebar">
```

With:

```html
<body>
  <div id="graph-container">
    <div id="filter-bar">
      <div class="filter-group">
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
        <button class="filter-chip active" data-filter-edge="imports">
          <span class="chip-swatch" style="background: var(--function);"></span>
          imports
        </button>
        <button class="filter-chip active" data-filter-edge="inherits">
          <span class="chip-swatch" style="background: var(--class);"></span>
          inherits
        </button>
      </div>
      <div class="filter-separator"></div>
      <div class="filter-group">
        <button class="filter-chip active" data-filter-boxes="filesystem">
          <span class="chip-swatch" style="background: var(--muted);"></span>
          filesystem
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

**Key differences from v1:**
- No `dirs` node chip — directories are bounding boxes.
- No `contains` edge chip — `contains` edges are never drawn.
- New `filesystem` chip with `data-filter-boxes="filesystem"` — toggles bounding boxes.
- All chips start `active` (including `filesystem`).

---

## Step 3: Add Filter Bar and Zoom Control CSS

**Location:** Inside `<style>`, before `</style>` (line 186).

Add these rules. Also **delete** the original `#graph` rule on line 34
(`#graph { flex: 1; min-height: 100vh; }`), which is replaced below.

```css
    #graph-container {
      position: relative;
      flex: 1;
      min-height: 100vh;
    }
    #graph {
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

**Verify:** Filter chips visible top-left, zoom buttons bottom-left.

---

## Step 4: Replace Layout Constants

**Location:** Lines 257–276 in `<script>`.

**Delete** all of these:

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
    const TYPE_TRACK_OFFSETS = Object.freeze({ ... });
```

**Replace** with:

```javascript
    const LAYOUT = Object.freeze({
      COL_PAD:        3.0,
      ROW_HEIGHT:     2.2,
      SUB_ROW_HEIGHT: 1.6,
      MIN_COL_WIDTH:  4.0,
      PX_PER_UNIT:    14,
      LABEL_PAD_PX:   20,
      BOX_PAD:        2.0,
      BOX_HEADER:     1.4,
    });
```

| Constant | Purpose |
|----------|---------|
| `COL_PAD` | Horizontal gap between file columns (graph units) |
| `ROW_HEIGHT` | Vertical spacing per tree depth level |
| `SUB_ROW_HEIGHT` | Vertical spacing between siblings at the same depth |
| `MIN_COL_WIDTH` | Floor for column width |
| `PX_PER_UNIT` | Approximate pixel-to-graph-unit conversion |
| `LABEL_PAD_PX` | Pixel padding added to text width for label measurement |
| `BOX_PAD` | Padding inside directory bounding boxes |
| `BOX_HEADER` | Space reserved for bounding box header label |

---

## Step 5: Add Edge Style Constants

**Location:** After the `colorByType` object (around line 354–358).

```javascript
    const EDGE_STYLES = Object.freeze({
      imports:  { color: "#60a5fa", size: 1.8, type: "arrow" },
      inherits: { color: "#a78bfa", size: 1.8, type: "arrow" },
    });
    const DEFAULT_EDGE_STYLE = Object.freeze({
      color: "#3a4f6a", size: 1, type: "line",
    });
```

Note: No `contains` entry — `contains` edges never enter the graph.

---

## Step 6: Add the `qualifyLabels` Function

**Location:** After `EDGE_STYLES`, before `nodeColor()`.

```javascript
    function qualifyLabels(nodes, nodeById) {
      const nameCount = {};
      for (const n of nodes) {
        nameCount[n.name] = (nameCount[n.name] || 0) + 1;
      }
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
        // Fallback: use directory from file_path
        const parts = (n.file_path || "").replace(/\\/g, "/").split("/").filter(Boolean);
        let qualifier = null;
        for (let i = parts.length - 2; i >= 0; i--) {
          if (parts[i] !== n.name) {
            qualifier = parts[i];
            break;
          }
        }
        n._displayLabel = qualifier ? qualifier + "/" + n.name : n.name;
      }
    }
```

**Why the fallback matters:** When a class like `OrderRequest` has a parent node also
named `OrderRequest` (common with Python module-level discovery), using `parent.name`
produces the useless `OrderRequest/OrderRequest`. The fallback walks the file path to
find a directory component that differs (e.g., `services` or `models`).

---

## Step 7: Write the `measureLabelWidth` Helper

**Location:** After `qualifyLabels`, before the layout function.

```javascript
    function measureLabelWidth(text) {
      labelMeasureContext.font = '500 12px "IBM Plex Mono", "IBM Plex Sans", sans-serif';
      return labelMeasureContext.measureText(String(text)).width + LAYOUT.LABEL_PAD_PX;
    }
```

This measures the pixel width of a label string using the same font as
`drawNodeBoxLabel`. Used by the layout to compute adaptive column widths.

---

## Step 8: Write the `layoutNodes` Function

**Location:** After `measureLabelWidth`, before `loadGraph()`.

This is the core layout function. It returns both node positions and bounding boxes.

```javascript
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

      // --- 2. Separate directories from content nodes ---
      const directories = [];
      const fileGroups = {};
      for (const n of nodes) {
        if (n.node_type === "directory") {
          directories.push(n);
          continue;
        }
        const fp = n.file_path || "__unfiled__";
        (fileGroups[fp] ||= []).push(n);
      }

      // --- 3. Sort file columns deterministically ---
      const sortedFiles = Object.keys(fileGroups).sort();

      // --- 4. Measure column widths ---
      const colWidths = sortedFiles.map(fp => {
        let maxPx = 0;
        for (const n of fileGroups[fp]) {
          const px = measureLabelWidth(n._displayLabel || n.name);
          if (px > maxPx) maxPx = px;
        }
        return Math.max(LAYOUT.MIN_COL_WIDTH, maxPx / LAYOUT.PX_PER_UNIT);
      });

      // --- 5. Compute column x-centers ---
      const colX = [];
      let xCursor = 0;
      for (let i = 0; i < sortedFiles.length; i++) {
        colX.push(xCursor + colWidths[i] / 2);
        xCursor += colWidths[i] + LAYOUT.COL_PAD;
      }

      // --- 6. Position content nodes ---
      // Y is NEGATED so depth 0 = top of screen (Sigma positive y = up).
      const positions = new Map();
      for (let ci = 0; ci < sortedFiles.length; ci++) {
        const group = fileGroups[sortedFiles[ci]];
        group.sort((a, b) =>
          (depthOf[a.node_id] - depthOf[b.node_id])
          || (a.start_line - b.start_line)
          || a.name.localeCompare(b.name)
        );

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
          const y = -(d * LAYOUT.ROW_HEIGHT + slotInDepth * LAYOUT.SUB_ROW_HEIGHT);
          positions.set(n.node_id, { x: colX[ci], y });
        }
      }

      // --- 7. Compute bounding boxes for directories ---
      const boxes = computeBoundingBoxes(directories, positions, nodeById, depthOf);

      return { positions, boxes, directories };
    }
```

**Key difference from v1:** All y values are negated (`y = -(...)`). This flips the
layout so depth 0 nodes appear at the top of the screen.

---

## Step 9: Write the Bounding Box Functions

**Location:** Immediately after `layoutNodes`.

```javascript
    function isDescendantOf(nodeId, ancestorId, nodeById) {
      let current = nodeById[nodeId];
      let steps = 0;
      while (current && steps < 50) {
        if (current.parent_id === ancestorId) return true;
        current = current.parent_id ? nodeById[current.parent_id] : null;
        steps++;
      }
      return false;
    }

    function computeBoundingBoxes(directories, positions, nodeById, depthOf) {
      // Sort deepest first so inner boxes are placed before outer boxes
      const sorted = [...directories].sort((a, b) =>
        (depthOf[b.node_id] - depthOf[a.node_id]) || a.name.localeCompare(b.name)
      );

      const boxes = new Map();

      for (const dir of sorted) {
        const xs = [];
        const ys = [];

        // Collect positions of descendant content nodes
        for (const [nid, pos] of positions) {
          if (isDescendantOf(nid, dir.node_id, nodeById)) {
            xs.push(pos.x);
            ys.push(pos.y);
          }
        }

        // Include extents of child directory boxes
        for (const [did, box] of boxes) {
          if (nodeById[did]?.parent_id === dir.node_id) {
            xs.push(box.x);
            xs.push(box.x + box.w);
            ys.push(box.y);
            ys.push(box.y - box.h);
          }
        }

        if (xs.length === 0) continue;

        const minX = Math.min(...xs);
        const maxX = Math.max(...xs);
        const maxY = Math.max(...ys);  // top of screen (least negative y)
        const minY = Math.min(...ys);  // bottom of screen (most negative y)

        boxes.set(dir.node_id, {
          // x, y is the top-left corner of the box (in graph coordinates)
          x: minX - LAYOUT.BOX_PAD,
          y: maxY + LAYOUT.BOX_PAD + LAYOUT.BOX_HEADER,
          w: (maxX - minX) + LAYOUT.BOX_PAD * 2,
          h: (maxY - minY) + LAYOUT.BOX_PAD * 2 + LAYOUT.BOX_HEADER,
          label: dir.name,
          depth: depthOf[dir.node_id],
        });
      }

      return boxes;
    }
```

**How it works:**

1. Directories are sorted deepest-first (e.g., `src/services/` before `src/`).
2. For each directory, collect the `(x, y)` of all descendant content nodes.
3. Also include the corners of any child directory boxes already computed.
4. Compute the bounding extent, add padding and a header gap.
5. Store the box. When the parent directory is processed later, it will include this
   box's extent in its own calculation → natural nesting.

The `isDescendantOf` helper walks the `parent_id` chain upward. The `steps < 50` guard
prevents infinite loops from malformed parent chains.

---

## Step 10: Rewrite `loadGraph`

**Location:** The `loadGraph()` function (lines 423–559).

**Replace entirely** with:

```javascript
    let boundingBoxes = new Map();

    async function loadGraph() {
      const nodesResp = await fetch("/api/nodes");
      const nodes = await nodesResp.json();
      const nodeById = Object.fromEntries(nodes.map(n => [n.node_id, n]));

      // Qualify duplicate names before layout measures labels
      qualifyLabels(nodes, nodeById);

      // Compute deterministic layout
      const layout = layoutNodes(nodes, nodeById);
      boundingBoxes = layout.boxes;

      // Rebuild graphology graph
      graph.clear();

      // Add ONLY non-directory nodes
      for (const node of nodes) {
        if (node.node_type === "directory") continue;
        const pos = layout.positions.get(node.node_id);
        if (!pos) continue;
        graph.addNode(node.node_id, {
          node_id: node.node_id,
          label: node._displayLabel || node.name,
          forceLabel: true,
          size: 2.4,
          x: pos.x,
          y: pos.y,
          color: nodeColor(node.node_type, node.status),
          node_type: node.node_type,
          file_path: node.file_path || "",
          status: node.status,
        });
      }

      // Add ONLY non-contains edges
      const edgeResp = await fetch("/api/edges");
      const edges = await edgeResp.json();
      for (const edge of edges) {
        if (edge.edge_type === "contains") continue;
        const key = edge.from_id + "->" + edge.to_id + ":" + edge.edge_type;
        if (!graph.hasNode(edge.from_id) || !graph.hasNode(edge.to_id)) continue;
        if (!graph.hasEdge(key)) {
          graph.addEdgeWithKey(key, edge.from_id, edge.to_id, {
            label: edge.edge_type,
            size: 1,
          });
        }
      }

      applyFilters();
      renderer.refresh();

      // Fit the entire graph into view
      renderer.getCamera().animatedReset({ duration: 300 });
    }
```

**Key differences from v1:**

1. **Directories excluded:** `if (node.node_type === "directory") continue;`
2. **Contains edges excluded:** `if (edge.edge_type === "contains") continue;`
3. **Bounding boxes stored:** `boundingBoxes = layout.boxes;` — accessible to the
   `beforeRender` handler.
4. **Camera auto-fit:** `animatedReset()` after layout ensures the full graph is visible,
   fixing right-edge clipping.

---

## Step 11: Rewrite `drawNodeBoxLabel` for Type-Based Shapes

**Location:** Lines 293–329.

**Replace** with:

```javascript
    function drawNodeBoxLabel(context, data) {
      if (!data.label || data.hidden) return;

      const nodeType = data.node_type || "";
      const text = String(data.label);
      const fontSize = 12;
      const fontWeight = "500";
      const padX = 10;
      const padY = 5;

      context.save();
      context.font = fontWeight + " " + fontSize + 'px "IBM Plex Mono", "IBM Plex Sans", sans-serif';
      const textWidth = context.measureText(text).width;
      const boxWidth = textWidth + padX * 2;
      const boxHeight = fontSize + padY * 2;
      const x = data.x - boxWidth / 2;
      const y = data.y - boxHeight / 2;

      // Shape: pill for functions/methods, rounded rect for others
      let borderRadius = 8;
      if (nodeType === "function" || nodeType === "method") {
        borderRadius = boxHeight / 2;
      }

      // Per-type fill color
      const fillColors = {
        class:    "rgba(167, 139, 250, 0.10)",
        function: "rgba(96, 165, 250, 0.10)",
        method:   "rgba(34, 211, 238, 0.10)",
        section:  "rgba(251, 191, 36, 0.10)",
        table:    "rgba(52, 211, 153, 0.10)",
        virtual:  "rgba(244, 114, 182, 0.10)",
      };

      // Draw box
      drawRoundedRect(context, x, y, boxWidth, boxHeight, borderRadius);
      context.fillStyle = fillColors[nodeType] || "rgba(10, 16, 24, 0.9)";
      context.fill();

      // Border
      context.strokeStyle = data.color || "#22d3ee";
      context.lineWidth = 1.4;

      // Dashed border for methods and awaiting statuses
      if (nodeType === "method" ||
          data.status === "awaiting_input" ||
          data.status === "awaiting_review") {
        context.setLineDash([4, 3]);
      }
      context.stroke();
      context.setLineDash([]);

      // Double border for classes
      if (nodeType === "class") {
        const inset = 3;
        drawRoundedRect(context, x + inset, y + inset,
          boxWidth - inset * 2, boxHeight - inset * 2,
          Math.max(2, borderRadius - inset));
        context.strokeStyle = data.color || "#a78bfa";
        context.lineWidth = 0.8;
        context.stroke();
      }

      // Text — dimmed when hovering a different node
      context.fillStyle = data.dimmed ? "rgba(229, 237, 247, 0.15)" : "#e5edf7";
      context.textAlign = "center";
      context.textBaseline = "middle";
      context.fillText(text, data.x, data.y);

      // Record hitbox for click detection
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

**Shapes by type:**

| Type | Shape | Border |
|------|-------|--------|
| `class` | Rounded rect + inner double border | Solid |
| `function` | Pill (fully rounded ends) | Solid |
| `method` | Pill | Dashed |
| `section`, `table`, `virtual` | Rounded rect | Solid |

---

## Step 12: Update the Sigma Constructor

**Location:** Lines 331–347.

**Replace** with:

```javascript
    const renderer = new Sigma(graph, document.getElementById("graph"), {
      labelRenderedSizeThreshold: 0,
      defaultDrawNodeLabel: drawNodeBoxLabel,
      defaultEdgeType: "arrow",
      zIndex: true,
      nodeReducer: (node, data) => {
        const result = { ...data };
        if (data.dimmed) {
          result.color = "rgba(100, 116, 139, 0.2)";
          result.label = data.label;
          result.forceLabel = true;
        }
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
        };
      },
    });
```

Then, **immediately after** the renderer creation, add the `beforeRender` handler that
draws bounding boxes:

```javascript
    renderer.on("beforeRender", (e) => {
      nodeLabelHitboxes.clear();

      if (!filterState.showBoundingBoxes) return;

      const context = e.context;
      for (const [dirId, box] of boundingBoxes) {
        // Convert graph coords → screen coords
        const tl = renderer.graphToViewport({ x: box.x, y: box.y });
        const br = renderer.graphToViewport({ x: box.x + box.w, y: box.y - box.h });
        const screenW = br.x - tl.x;
        const screenH = br.y - tl.y;

        if (screenW < 2 || screenH < 2) continue;  // too small to draw

        const depth = box.depth || 0;
        const fillAlpha = 0.03 + depth * 0.015;
        const strokeAlpha = 0.12 + depth * 0.04;

        context.fillStyle = "rgba(148, 163, 184, " + fillAlpha + ")";
        context.strokeStyle = "rgba(148, 163, 184, " + strokeAlpha + ")";
        context.lineWidth = 1;
        drawRoundedRect(context, tl.x, tl.y, screenW, screenH, 8);
        context.fill();
        context.stroke();

        // Header label
        context.fillStyle = "rgba(148, 163, 184, " + (0.45 + depth * 0.1) + ")";
        context.font = '600 11px "IBM Plex Mono", "IBM Plex Sans", sans-serif';
        context.textAlign = "left";
        context.textBaseline = "top";
        context.fillText(box.label + "/", tl.x + 8, tl.y + 5);
      }
    });
```

**What this does:**

Before every frame, the handler:
1. Clears the label hitbox cache (same as the original `beforeRender`).
2. Checks `filterState.showBoundingBoxes` — skips drawing if the filesystem chip is off.
3. For each directory bounding box, converts graph coordinates to screen pixels.
4. Draws a translucent rounded rect with depth-scaled opacity (deeper = slightly darker).
5. Draws the directory name as a small header label in the top-left corner.

Boxes render *behind* nodes and edges because `beforeRender` fires before Sigma's own
rendering passes.

---

## Step 13: Update `nodeColor` for the New Type Palette

**Location:** The `colorByType` object and `nodeColor()` function.

**Replace** `colorByType` with:

```javascript
    const colorByType = {
      function: getComputedStyle(document.documentElement).getPropertyValue("--function").trim(),
      class:    getComputedStyle(document.documentElement).getPropertyValue("--class").trim(),
      method:   getComputedStyle(document.documentElement).getPropertyValue("--method").trim(),
      section:  getComputedStyle(document.documentElement).getPropertyValue("--section").trim(),
      table:    getComputedStyle(document.documentElement).getPropertyValue("--table").trim(),
      virtual:  getComputedStyle(document.documentElement).getPropertyValue("--virtual").trim(),
    };
```

**Replace** `nodeColor()` with:

```javascript
    function nodeColor(nodeType, status) {
      if (status === "running") return "#fb923c";
      if (status === "awaiting_input" || status === "awaiting_review") return "#fbbf24";
      if (status === "error") return "#f87171";
      return colorByType[nodeType] || "#818cf8";
    }
```

No `directory` entry needed — directories aren't graph nodes.

---

## Step 14: Add Filter State and `applyFilters`

**Location:** After the Sigma constructor + `beforeRender` handler, before `selectedNode`.

```javascript
    const filterState = {
      hiddenNodeTypes: new Set(),
      hiddenEdgeTypes: new Set(),
      showBoundingBoxes: true,
    };

    function applyFilters() {
      graph.forEachNode((id, attrs) => {
        graph.setNodeAttribute(id, "hidden",
          filterState.hiddenNodeTypes.has(attrs.node_type));
      });
      graph.forEachEdge((edge, attrs) => {
        graph.setEdgeAttribute(edge, "hidden",
          filterState.hiddenEdgeTypes.has(attrs.label));
      });
      renderer.refresh();
    }
```

Note: `showBoundingBoxes` is checked in the `beforeRender` handler (Step 12).
`applyFilters` triggers `renderer.refresh()` which triggers `beforeRender`.

---

## Step 15: Wire Up Filter Chip Click Handlers

**Location:** After the existing click handlers (after the `agent-stream` handler).

```javascript
    document.getElementById("filter-bar").addEventListener("click", (event) => {
      const chip = event.target.closest(".filter-chip");
      if (!chip) return;

      const nodeType = chip.dataset.filterNode;
      const edgeType = chip.dataset.filterEdge;
      const boxToggle = chip.dataset.filterBoxes;

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

      if (boxToggle) {
        chip.classList.toggle("active");
        filterState.showBoundingBoxes = !filterState.showBoundingBoxes;
      }

      applyFilters();
    });
```

**Three chip types:**
- `data-filter-node` → toggles node type visibility.
- `data-filter-edge` → toggles edge type visibility.
- `data-filter-boxes` → toggles `filterState.showBoundingBoxes`.

---

## Step 16: Add Hover Highlight Handlers

**Location:** After the `clickStage` handler, before the `send-chat` handler.

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
      applyFilters();
    });
```

On hover: dims non-neighbors, hides unrelated edges.
On leave: clears dimming, restores filter-based edge visibility via `applyFilters()`.

---

## Step 17: Wire Up Zoom Controls

**Location:** After hover handlers.

```javascript
    document.getElementById("zoom-in").addEventListener("click", () => {
      renderer.getCamera().animatedZoom({ duration: 200 });
    });
    document.getElementById("zoom-out").addEventListener("click", () => {
      renderer.getCamera().animatedUnzoom({ duration: 200 });
    });
    document.getElementById("zoom-reset").addEventListener("click", () => {
      renderer.getCamera().animatedReset({ duration: 200 });
    });
```

---

## Step 18: Clean Up Dead Code

**Delete** these functions that are no longer called:

1. `hashNodeId()` — hash for deterministic jitter.
2. `deterministicOffset()` — jitter from hash.
3. `fileBandKeyFromPath()` — file band grouping.
4. `buildFileBands()` — band y-offset computation.
5. `bandYForNode()` — band y lookup.

Search the file for each name to confirm zero remaining references.

---

## Step 19: Verification Checklist

### Layout
- [ ] Non-directory nodes are arranged in vertical columns, one per file.
- [ ] Columns sorted alphabetically by file path (left to right).
- [ ] Within each column, nodes sorted by source order (top to bottom).
- [ ] Depth 0 nodes appear at the **top** of the screen, deeper nodes below.
- [ ] No labels overlap or are truncated.
- [ ] Duplicate names are qualified (e.g., `services/OrderRequest` vs `models/OrderRequest`).
- [ ] No self-qualifying labels like `OrderSummary/OrderSummary`.

### Bounding Boxes
- [ ] Directories appear as translucent nested rectangles behind the graph.
- [ ] Each box has a header label (directory name + `/`).
- [ ] Inner directories nest inside outer ones.
- [ ] Section and virtual agent nodes appear inside their parent directory's box.
- [ ] Deeper boxes are slightly darker than shallower ones.
- [ ] No directory nodes appear as clickable graph nodes.

### Determinism
- [ ] Refresh the page 3 times. Layout + boxes are identical each time.
- [ ] Tear down the demo, restart, reload. Same layout.

### Edges
- [ ] No `contains` edges are drawn (not even as hidden lines).
- [ ] `imports` edges appear as blue arrows.
- [ ] `inherits` edges appear as purple arrows.
- [ ] No spaghetti tangle.

### Node Shapes
- [ ] Classes: double border (outer + inner ring), purple.
- [ ] Functions: pill shape (fully rounded ends), blue.
- [ ] Methods: pill shape, dashed border, cyan.
- [ ] Sections: standard rounded rect, yellow.
- [ ] Virtual: standard rounded rect, pink.

### Filters
- [ ] Clicking a node-type chip toggles visibility of that type.
- [ ] Clicking an edge-type chip toggles visibility of that edge type.
- [ ] Clicking the `filesystem` chip toggles bounding box visibility.
- [ ] Chip visual state (bright vs dim) matches the filter state.
- [ ] All chips start active.

### Hover
- [ ] Hovering a node dims non-neighbors and hides unrelated edges.
- [ ] Moving away restores the full graph.
- [ ] Bounding boxes remain visible during hover.

### Camera
- [ ] After initial load, the full graph fits in the viewport.
- [ ] No nodes are clipped by the sidebar.
- [ ] `+`/`-` zoom works.
- [ ] Fit-to-view button resets camera.

### SSE Events
- [ ] `node_discovered` triggers a full graph rebuild with correct layout.
- [ ] `agent_start`/`agent_complete`/`agent_error` change node border colors.
- [ ] Events and timeline panels still update.

---

## Appendix A: Node Data Shape Reference

`GET /api/nodes` returns:

```javascript
{
  "node_id":     "path/to/file.py::ClassName",    // unique, deterministic
  "node_type":   "function"|"class"|"method"|"section"|"table"|"directory"|"virtual",
  "name":        "ClassName",
  "full_name":   "ModuleName.ClassName",
  "file_path":   "src/services/orders.py",
  "start_line":  42,
  "end_line":    87,
  "start_byte":  1200,
  "end_byte":    2400,
  "text":        "class ClassName:\n  ...",
  "source_hash": "abc123...",
  "parent_id":   "path/to/file.py::Module" | null,
  "status":      "idle"|"running"|"error"|"awaiting_input"|"awaiting_review",
  "role":        "code-agent" | null
}
```

`GET /api/edges` returns:

```javascript
{
  "from_id":    "path/to/file.py::ClassName",
  "to_id":      "path/to/other.py::OtherClass",
  "edge_type":  "contains"|"imports"|"inherits"
}
```

The graph view uses `node_type === "directory"` to separate directory nodes from content
nodes. Directory nodes are consumed by the bounding box system and never added to the
graphology graph. `contains` edges are skipped entirely.

---

## Appendix B: Complete Layout Walkthrough

Given this example project:

```
src/
  services/
    orders.py     → OrderRequest, OrderSummary, create_order
    pricing.py    → PricingRule, apply_tax
  utils/
    formatting.py → format_usd
bundles/
  system/
    runtime.md    → (Runtime profiles) [section]
    checks.md     → (Validation checks) [section]
```

### Step 1 — Depths

| Node | Type | Depth |
|------|------|-------|
| `src/` | directory | 0 |
| `bundles/` | directory | 0 |
| `src/services/` | directory | 1 |
| `src/utils/` | directory | 1 |
| `bundles/system/` | directory | 1 |
| `OrderRequest` | class | 2 (or 3, depending on parent chain) |
| `OrderSummary` | class | 2 |
| `create_order` | function | 2 |
| `PricingRule` | class | 2 |
| `apply_tax` | function | 2 |
| `format_usd` | function | 2 |
| `Runtime profiles` | section | 2 |
| `Validation checks` | section | 2 |

### Step 2 — Separate directories from content

Directories: `src/`, `bundles/`, `src/services/`, `src/utils/`, `bundles/system/`
Content groups by file_path:
```
"src/services/orders.py"      → [OrderRequest, OrderSummary, create_order]
"src/services/pricing.py"     → [PricingRule, apply_tax]
"src/utils/formatting.py"     → [format_usd]
"bundles/system/runtime.md"   → [Runtime profiles]
"bundles/system/checks.md"    → [Validation checks]
```

### Step 3 — Sorted file columns

```
Column 0: bundles/system/checks.md
Column 1: bundles/system/runtime.md
Column 2: src/services/orders.py
Column 3: src/services/pricing.py
Column 4: src/utils/formatting.py
```

### Step 4 — Positions (y negated)

Column 2, sorted by (depth, start_line, name):
```
OrderRequest:  x=col2_center,  y = -(2 * 2.2 + 0 * 1.6) = -4.4
OrderSummary:  x=col2_center,  y = -(2 * 2.2 + 1 * 1.6) = -6.0
create_order:  x=col2_center,  y = -(2 * 2.2 + 2 * 1.6) = -7.6
```

Column 0:
```
Validation checks: x=col0_center, y = -(2 * 2.2 + 0 * 1.6) = -4.4
```

### Step 5 — Bounding boxes (bottom-up)

`bundles/system/` (depth 1): encloses columns 0–1 → box around `Validation checks` +
`Runtime profiles`.

`src/services/` (depth 1): encloses columns 2–3 → box around all orders.py + pricing.py
nodes.

`src/utils/` (depth 1): encloses column 4 → box around `format_usd`.

`src/` (depth 0): encloses the `src/services/` box + `src/utils/` box.

`bundles/` (depth 0): encloses the `bundles/system/` box.

### Final visual (conceptual)

```
┌─ bundles/ ────────┐  ┌─ src/ ────────────────────────────────────────┐
│ ┌─ system/ ─────┐ │  │ ┌─ services/ ──────────────┐ ┌─ utils/ ───┐ │
│ │ (Validation…) │ │  │ │ (OrderRequest) ── import ───→(format_usd)│ │
│ │ (Runtime…)    │ │  │ │ (OrderSummary)            │ └────────────┘ │
│ └───────────────┘ │  │ │ (create_order)            │                │
└───────────────────┘  │ │ (PricingRule)  (apply_tax) │                │
                       │ └──────────────────────────-─┘                │
                       └───────────────────────────────────────────────┘
```

Every value is derived from sorts and measurements. No randomness. Same project → same
picture. The bounding boxes show the filesystem. The arrows show the dependencies.
