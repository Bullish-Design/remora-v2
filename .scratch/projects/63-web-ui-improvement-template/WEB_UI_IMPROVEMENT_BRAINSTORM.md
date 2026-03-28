# Web UI Improvement Brainstorm

## Table of Contents
1. [Problems Visible in Current Screenshot](#1-problems-visible-in-current-screenshot)
2. [Graph Readability Overhaul](#2-graph-readability-overhaul)
3. [Layout Algorithm Improvements](#3-layout-algorithm-improvements)
4. [Visual Hierarchy & Node Design](#4-visual-hierarchy--node-design)
5. [Edge Rendering & Differentiation](#5-edge-rendering--differentiation)
6. [Interaction & Navigation](#6-interaction--navigation)
7. [Sidebar & Panel Redesign](#7-sidebar--panel-redesign)
8. [Filtering & Search](#8-filtering--search)
9. [Information Density & Labels](#9-information-density--labels)
10. [Performance & Scalability](#10-performance--scalability)
11. [Implementation Priority Matrix](#11-implementation-priority-matrix)

---

## 1. Problems Visible in Current Screenshot

The demo screenshot (`00_repo_baseline`) exposes several critical readability issues:

### 1.1 Spaghetti Edges
The graph is dominated by edge crossings. Nearly every edge from `src` to its children
crosses multiple other edges. The `contains` edges (parent→child) visually blend with
`imports`/`inherits` edges, creating an unreadable tangle. The user cannot trace any
single relationship by eye.

### 1.2 Label Truncation & Overlap
Several labels are cut off or overlap adjacent labels:
- `"discount_for_"` — truncated, missing suffix
- `"co|fulfillment"` — two labels colliding
- `"Evented s"` — truncated "Evented subscriptions" or similar
- `"Repository artifa"` — truncated "Repository artifacts"
- `"Validat|"` — truncated "Validation" colliding with next label

This happens because box-label rendering doesn't account for neighbor proximity, and the
layout places nodes too close together in the horizontal axis.

### 1.3 No Visual Distinction Between Node Types
All nodes render as identical cyan-bordered rectangles regardless of whether they are
directories, files, classes, functions, or methods. The only differentiation is the
`TYPE_TRACK_OFFSETS` x-position, which is invisible to the user without a legend.

### 1.4 Ambiguous Grouping
File band labels (`src`, `utils`, `services`, `models`, `docs`, `configs`, `api`) float
on the left edge with no visual connection to their groups. It's unclear which nodes
belong to which file. The bands use subtle y-offsets but have no background regions,
separator lines, or enclosing shapes.

### 1.5 Duplicate Names Without Context
`OrderRequest` appears twice, `OrderSummary` appears twice, `services` appears twice,
`models` appears twice, `utils` appears twice, `configs` appears twice. Without file-path
context visible on the node, there's no way to tell them apart.

### 1.6 Bundle Roles Row is Cryptic
The "Bundle roles" band contains `"Evented s"`, `"Repository artifa"`, `"Source graph
mapping"`, `"Validat"`, `"Virtual agents"` — all truncated. These are meta-concepts that
don't clearly relate to the code graph above them.

### 1.7 Events Panel is Noisy
The sidebar events show raw `event_type: agent_id` lines with full absolute paths like
`/home/andrew/Documents/Projects/remora-test/src/api/orders.py::create_order`. These are
unreadable at the font size shown. The information density is high but comprehension is
near zero.

---

## 2. Graph Readability Overhaul

### 2.1 Hierarchical Containment Layout (Primary Recommendation)

**Problem**: The current layout uses flat bands with `TYPE_TRACK_OFFSETS` for x-positioning
and `FILE_BAND_SPACING` for y-positioning. This ignores the natural tree structure
(directory → file → class → method/function).

**Solution**: Switch from the flat band layout to a **compound/nested graph** approach where
containment relationships are visualized as nested boxes (like a treemap or compound node
layout).

```
┌─ src/ ─────────────────────────────────────────────┐
│  ┌─ services/ ────────────────────────────────────┐ │
│  │  ┌─ orders.py ──────────────────────────────┐  │ │
│  │  │  ┌──────────────┐  ┌───────────────────┐ │  │ │
│  │  │  │ OrderRequest │  │   OrderSummary    │ │  │ │
│  │  │  └──────────────┘  └───────────────────┘ │  │ │
│  │  │  ┌──────────────┐  ┌───────────────────┐ │  │ │
│  │  │  │ create_order │  │ discount_for_qty  │ │  │ │
│  │  │  └──────────────┘  └───────────────────┘ │  │ │
│  │  └──────────────────────────────────────────┘  │ │
│  └────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────┘
```

**Implementation**:
- Separate edges into two categories: **structural** (`contains`/`parent`) and
  **semantic** (`imports`, `inherits`, `calls`).
- Use structural edges to define nesting rectangles (drawn as rounded-rect backgrounds).
- Only render semantic edges as visible lines/arrows.
- This eliminates ~60-80% of visible edges (all parent→child lines), dramatically
  reducing visual clutter.

**How to implement in current code**:
1. After `loadGraph()`, build a tree from `parent_id` relationships.
2. Use a bottom-up size calculation: leaf nodes get a minimum box size, parents
   accumulate children sizes + padding.
3. Render parent nodes as background rectangles in a custom `beforeDrawNodes` Sigma
   program or via canvas layering.
4. Remove `contains`-type edges from the visible edge set.

### 2.2 Force-Directed with Containment Constraints (Alternative)

If compound layout is too complex, use **Sigma's built-in force atlas** or
**graphology-layout-forceatlas2** with constraints:
- Pin parent nodes as gravity centers for their children.
- Set strong attractive forces for `contains` edges, weak for `imports`.
- This naturally clusters children near parents without explicit nesting boxes.

**Trade-off**: Less clean than compound layout but far easier to implement. The graphology
ecosystem already has `graphology-layout-forceatlas2` which could be added as a vendor
script.

---

## 3. Layout Algorithm Improvements

### 3.1 Replace Hash-Based Positioning with Deterministic Tree Layout

The current layout (`loadGraph()` lines 479-516) uses a complex mix of:
- `TYPE_TRACK_OFFSETS` (x by node type)
- `SIBLING_SPREAD`, `LEVEL_SPREAD` (sibling/level fan-out)
- `DEPTH_X_FANOUT`, `DEPTH_ZIGZAG_SPREAD`, `DEPTH_WAVE_AMPLITUDE` (depth effects)
- `deterministicOffset()` (hash-based jitter)
- `fileBandKeyFromPath()` + `buildFileBands()` (y-banding by file)

This produces unpredictable, overlapping results because:
- Hash jitter can place unrelated nodes adjacent.
- Wave amplitude increases with depth, causing deep nodes to spread far.
- Type track offsets fight with sibling spread.

**Recommendation**: Replace with a proper **layered/Sugiyama layout** for the tree
structure:
1. Assign layers by depth (directories=0, files=1, classes=2, functions/methods=3).
2. Within each layer, order nodes to minimize edge crossings (barycenter heuristic).
3. Position nodes with uniform spacing per layer.

**Library option**: `graphology-layout-dagre` (if available) or implement a simple
Sugiyama with the existing graphology graph.

### 3.2 Smarter Spacing Based on Label Width

Currently, `SIBLING_SPREAD = 1.8` is a fixed constant. But labels like
`"discount_for_quantity"` need much more space than `"src"`.

**Implementation**:
```javascript
function requiredSpacing(nodeId) {
  const label = graph.getNodeAttribute(nodeId, 'label') || '';
  // Measure actual text width at render font size
  labelMeasureContext.font = '500 12px "IBM Plex Mono", sans-serif';
  const textWidth = labelMeasureContext.measureText(label).width;
  // Convert pixel width to graph units (approximate)
  return (textWidth + 20) / PIXELS_PER_GRAPH_UNIT;
}
```

Apply this per-sibling-pair when computing x-positions.

### 3.3 Collision Detection Pass

After initial layout, run a sweep to detect label overlaps and nudge colliding nodes apart:

```javascript
function resolveCollisions(nodePositions, iterations = 3) {
  for (let i = 0; i < iterations; i++) {
    for (const [idA, boxA] of nodePositions) {
      for (const [idB, boxB] of nodePositions) {
        if (idA >= idB) continue;
        const overlap = computeOverlap(boxA, boxB);
        if (overlap > 0) {
          // Push apart along the axis of least resistance
          nudgeApart(boxA, boxB, overlap);
        }
      }
    }
  }
}
```

This is O(n²) per iteration but fine for <500 nodes. Could use a spatial hash for larger
graphs.

---

## 4. Visual Hierarchy & Node Design

### 4.1 Distinct Shapes Per Node Type

Instead of uniform rectangles, use shape + color to encode node type:

| Node Type   | Shape              | Border Color | Fill           | Icon |
|-------------|-------------------|--------------|----------------|------|
| directory   | Rounded rect, bold | `#9fb2c8`   | `#1a2535`      | 📁   |
| file        | Rounded rect      | `#64748b`    | `#111b2b`      | 📄   |
| class       | Double-bordered   | `#a78bfa`    | `#1a1530`      | ◆    |
| function    | Pill/capsule      | `#60a5fa`    | `#0f1a2d`      | ƒ    |
| method      | Pill, dashed      | `#22d3ee`    | `#0f1a2d`      | →    |
| section     | Tag/badge         | `#fbbf24`    | `#1a1810`      | §    |
| table       | Table icon rect   | `#34d399`    | `#0f1a20`      | ≡    |

**Implementation**: Extend `drawNodeBoxLabel()` to branch on `data.node_type` and draw
different shapes. The current function already handles `__label__` vs normal — extend this
pattern.

### 4.2 Status Indication Without Color Alone

Currently, node status changes the border color (running=orange, error=red, idle=type
color). This is lost on colorblind users and conflicts with type colors.

**Improvement**: Use **animated indicators** alongside color:
- **Running**: Pulsing glow or spinning ring around the node.
- **Error**: Red corner badge with `!` icon.
- **Awaiting input**: Blinking cursor icon or `?` badge.
- **Idle**: No animation (steady state).

```javascript
// In drawNodeBoxLabel, after drawing the box:
if (data.status === 'running') {
  const time = Date.now() / 1000;
  const alpha = 0.3 + 0.3 * Math.sin(time * 3);
  context.shadowColor = 'rgba(251, 146, 60, ' + alpha + ')';
  context.shadowBlur = 8;
  // Redraw border with glow
}
```

### 4.3 Size Encoding

Encode node "importance" (e.g., line count, number of children, or turn count) as node
size. Currently all nodes are `size: 2.4`. A class with 200 lines and 8 methods should
be visually larger than a 3-line utility function.

```javascript
const lineCount = (node.end_line || 0) - (node.start_line || 0);
const size = Math.max(2, Math.min(6, 2 + Math.log2(lineCount + 1) * 0.5));
```

---

## 5. Edge Rendering & Differentiation

### 5.1 Hide Structural Edges, Show Semantic Edges

The single most impactful change for graph readability.

**Current state**: All edges render identically as thin gray lines. The `contains` edges
(parent→child) form the majority and create the spaghetti effect.

**Solution**:
- **Default**: Hide `contains`/`parent` edges entirely. The containment is shown by the
  nested layout (§2.1) or proximity grouping.
- **Show**: `imports`, `inherits`, `calls`, `triggers` edges as colored, curved arrows.

```javascript
// In edge rendering or reducer:
edgeReducer: (edge, data) => {
  if (data.label === 'contains') return { ...data, hidden: true };
  const colorMap = {
    imports: '#60a5fa',
    inherits: '#a78bfa',
    calls: '#22d3ee',
    triggers: '#fb923c',
  };
  return {
    ...data,
    color: colorMap[data.label] || '#3a4f6a',
    size: 1.5,
    type: 'arrow',
  };
},
```

### 5.2 Curved Edges to Reduce Overlap

Straight edges cross each other frequently. Sigma supports curved edges via
`defaultEdgeType: 'curve'` or custom edge programs.

```javascript
const renderer = new Sigma(graph, container, {
  defaultEdgeType: 'curved',
  // ... other options
});
```

### 5.3 Edge Bundling (Advanced)

For dense import graphs, implement simple edge bundling: group edges that share
source/target neighborhoods and route them through shared control points. This
dramatically reduces visual clutter for hub nodes.

**Library**: `graphology-layout-edge-bundling` or a custom implementation using
hierarchical bundling.

### 5.4 Edge Labels on Hover

Don't label edges by default. On hover over a node, highlight its edges and show small
labels (`imports`, `inherits`) near the midpoint of each connected edge.

---

## 6. Interaction & Navigation

### 6.1 Node Search / Focus

**Problem**: With 50+ nodes, finding a specific function requires scanning the entire graph.

**Solution**: Add a search input above the graph:

```html
<input id="graph-search" type="text" placeholder="Search nodes... (Ctrl+K)"
       style="position:absolute; top:12px; left:12px; z-index:10; ..." />
```

Implementation:
- On input, filter `graph.nodes()` by fuzzy match against `label` and `file_path`.
- Highlight matches (set `forceLabel: true`, increase size) and dim non-matches.
- On Enter or click a result, animate camera to the selected node.

### 6.2 Minimap

For large graphs, add a minimap in the corner showing the full graph extent with a
viewport rectangle. Sigma's `@sigma/minimap` plugin provides this.

### 6.3 Zoom Controls

Add explicit +/- buttons and a "fit to view" button. While scroll-zoom works, explicit
controls are more discoverable:

```html
<div id="zoom-controls" style="position:absolute; bottom:16px; left:16px; z-index:10;">
  <button onclick="renderer.getCamera().animatedZoom()">+</button>
  <button onclick="renderer.getCamera().animatedUnzoom()">-</button>
  <button onclick="renderer.getCamera().animatedReset()">⊡</button>
</div>
```

### 6.4 Keyboard Navigation

- `Ctrl+K` / `/` — Focus search
- `Tab` / `Shift+Tab` — Cycle through nodes
- `Enter` — Select focused node
- `Escape` — Deselect / close panels
- `1-5` — Toggle edge type visibility

### 6.5 Neighbor Highlight on Hover

When hovering a node, highlight its direct neighbors and connecting edges. Dim everything
else to ~20% opacity. This lets users trace relationships interactively.

```javascript
renderer.on('enterNode', ({ node }) => {
  const neighbors = new Set(graph.neighbors(node));
  neighbors.add(node);
  graph.forEachNode((n) => {
    graph.setNodeAttribute(n, 'hidden', !neighbors.has(n));
  });
  renderer.refresh();
});

renderer.on('leaveNode', () => {
  graph.forEachNode((n) => graph.setNodeAttribute(n, 'hidden', false));
  renderer.refresh();
});
```

---

## 7. Sidebar & Panel Redesign

### 7.1 Collapsible / Tabbed Sidebar

The current sidebar stacks everything vertically: node details, agent panel, events,
timeline. At typical viewport heights, only the top section is visible without scrolling.

**Option A — Tabs**:
```
┌──────────────────────────┐
│ [Node] [Agent] [Events]  │  ← tab bar
├──────────────────────────┤
│                          │
│  (active tab content)    │
│                          │
└──────────────────────────┘
```

**Option B — Collapsible Accordion**:
Each section has a clickable header that toggles expand/collapse. Default: Node expanded,
others collapsed.

**Option C — Resizable Split**:
Top half = node details + agent panel. Bottom half = events/timeline with a horizontal
drag divider.

**Recommendation**: Option A (tabs) for simplicity. The sidebar is 440px wide, which is
enough for any single panel but not enough for all four stacked.

### 7.2 Detachable Panels

Allow the user to pop out the agent panel or timeline into a floating window:
```javascript
document.getElementById('detach-timeline').addEventListener('click', () => {
  const win = window.open('', 'timeline', 'width=600,height=400');
  // Mirror timeline content to the new window
});
```

### 7.3 Graph-Sidebar Split Ratio

Make the sidebar width adjustable via a drag handle. Some users want a wider graph, others
want a wider detail panel.

### 7.4 Breadcrumb Path Display

When a node is selected, show its full containment path as a clickable breadcrumb:

```
src/ → services/ → orders.py → OrderRequest → validate()
```

Each segment is clickable to navigate to that ancestor node. This solves the "which
OrderRequest?" ambiguity.

---

## 8. Filtering & Search

### 8.1 Node Type Filter Chips

Add toggleable chips above or beside the graph:

```
[📁 Directories] [📄 Files] [◆ Classes] [ƒ Functions] [→ Methods] [§ Sections]
```

Clicking a chip hides/shows all nodes of that type. This lets users focus on, say, only
classes and their relationships.

**Implementation**:
```javascript
const hiddenTypes = new Set();

function toggleType(nodeType) {
  if (hiddenTypes.has(nodeType)) hiddenTypes.delete(nodeType);
  else hiddenTypes.add(nodeType);

  graph.forEachNode((id, attrs) => {
    graph.setNodeAttribute(id, 'hidden', hiddenTypes.has(attrs.node_type));
  });
  renderer.refresh();
}
```

### 8.2 Edge Type Toggles

Similar chips for edge types:

```
[→ imports] [◆ inherits] [⊂ contains] [↺ calls]
```

Default: `contains` OFF, everything else ON.

### 8.3 Status Filter

Filter by agent status:
```
[● All] [🟠 Running] [🔴 Error] [🟡 Awaiting] [⚪ Idle]
```

### 8.4 File Path Filter

A text input that filters nodes by file path glob:
```
Filter: [src/services/**________]
```

Matches highlight, non-matches dim to 15% opacity.

---

## 9. Information Density & Labels

### 9.1 Smart Label Truncation with Tooltips

Currently, labels are rendered at full length, causing overlap. Instead:
- Truncate labels to fit available space (measure neighbor distance).
- Show full label + metadata on hover as a tooltip overlay.

```javascript
function smartLabel(fullName, maxWidth) {
  labelMeasureContext.font = '500 12px "IBM Plex Mono"';
  if (labelMeasureContext.measureText(fullName).width <= maxWidth) return fullName;
  // Try removing underscores: discount_for_quantity → discountForQty
  // Try abbreviation: OrderRequest → OrdReq
  // Last resort: truncate with ellipsis
  let truncated = fullName;
  while (labelMeasureContext.measureText(truncated + '…').width > maxWidth) {
    truncated = truncated.slice(0, -1);
  }
  return truncated + '…';
}
```

### 9.2 Semantic Zoom (Level of Detail)

At different zoom levels, show different amounts of information:

| Zoom Level | Visible       | Labels Show           |
|-----------|---------------|-----------------------|
| Far out   | Directories   | Directory names only  |
| Medium    | + Files       | + File names          |
| Close     | + Classes     | + Class names         |
| Very close| + Functions   | + Function names, edges |

**Implementation**: Use Sigma's `nodeReducer` with `renderer.getCamera().ratio`:

```javascript
nodeReducer: (node, data) => {
  const ratio = renderer.getCamera().ratio;
  const depthThresholds = { directory: 2, file: 1, class: 0.5, function: 0.25, method: 0.15 };
  const threshold = depthThresholds[data.node_type] || 0.5;
  if (ratio > threshold) {
    return { ...data, hidden: true };
  }
  return data;
},
```

### 9.3 Qualified Labels for Duplicates

When duplicate names exist, automatically qualify them:
- If two `OrderRequest` nodes exist, show `services/OrderRequest` and `models/OrderRequest`.
- Only qualify when there's actual ambiguity (collision detection on names).

```javascript
function qualifyDuplicateLabels(nodes) {
  const nameCount = {};
  for (const node of nodes) {
    nameCount[node.name] = (nameCount[node.name] || 0) + 1;
  }
  for (const node of nodes) {
    if (nameCount[node.name] > 1 && node.file_path) {
      const parts = node.file_path.split('/');
      const qualifier = parts[parts.length - 2] || parts[parts.length - 1];
      node.qualifiedLabel = `${qualifier}/${node.name}`;
    } else {
      node.qualifiedLabel = node.name;
    }
  }
}
```

---

## 10. Performance & Scalability

### 10.1 Lazy Edge Rendering

For graphs with 500+ edges, render only edges connected to visible or hovered nodes.
All other edges are hidden until the user interacts.

### 10.2 WebGL Edge Program

Sigma's default canvas edge rendering becomes slow past ~1000 edges. Switch to Sigma's
WebGL edge programs:

```javascript
import { EdgeArrowProgram } from '@sigma/edge-arrow';
// In renderer options:
edgeProgramClasses: { arrow: EdgeArrowProgram },
defaultEdgeType: 'arrow',
```

### 10.3 Viewport Culling

Only render nodes and edges within the current camera viewport. Sigma does some of this
automatically, but custom node programs can skip off-screen work entirely.

### 10.4 Incremental Layout Updates

Currently, `node_discovered` SSE events trigger a full `loadGraph()` re-fetch and
re-layout. For incremental discovery:
1. Fetch only the new node from `payload.node_id`.
2. Insert it near its parent (if `parent_id` is known).
3. Run a local collision resolution around the insertion point.
4. Avoid full graph reload.

---

## 11. Implementation Priority Matrix

Ranked by impact on "clean and easy to interpret" vs implementation effort:

### Tier 1 — High Impact, Moderate Effort (Do First)
| # | Improvement | Impact | Effort | Section |
|---|-------------|--------|--------|---------|
| 1 | **Hide `contains` edges by default** | ★★★★★ | Low | §5.1 |
| 2 | **Distinct node shapes/colors by type** | ★★★★★ | Medium | §4.1 |
| 3 | **Node type filter chips** | ★★★★ | Low | §8.1 |
| 4 | **Neighbor highlight on hover** | ★★★★ | Low | §6.5 |
| 5 | **Qualify duplicate labels** | ★★★★ | Low | §9.3 |
| 6 | **Collision detection + nudge** | ★★★★ | Medium | §3.3 |

### Tier 2 — High Impact, Higher Effort (Do Next)
| # | Improvement | Impact | Effort | Section |
|---|-------------|--------|--------|---------|
| 7 | **Compound/nested layout** | ★★★★★ | High | §2.1 |
| 8 | **Semantic zoom (level of detail)** | ★★★★ | Medium | §9.2 |
| 9 | **Tabbed sidebar** | ★★★ | Medium | §7.1 |
| 10 | **Node search with Ctrl+K** | ★★★ | Medium | §6.1 |
| 11 | **Curved edges** | ★★★ | Low | §5.2 |
| 12 | **Edge type toggles** | ★★★ | Low | §8.2 |

### Tier 3 — Polish (Do When Core is Solid)
| # | Improvement | Impact | Effort | Section |
|---|-------------|--------|--------|---------|
| 13 | **Breadcrumb navigation** | ★★★ | Medium | §7.4 |
| 14 | **Zoom controls** | ★★ | Low | §6.3 |
| 15 | **Minimap** | ★★ | Low (plugin) | §6.2 |
| 16 | **Animated status indicators** | ★★ | Medium | §4.2 |
| 17 | **Smart label truncation** | ★★ | Medium | §9.1 |
| 18 | **Keyboard navigation** | ★★ | Medium | §6.4 |

### Tier 4 — Advanced (Future)
| # | Improvement | Impact | Effort | Section |
|---|-------------|--------|--------|---------|
| 19 | **Edge bundling** | ★★★ | High | §5.3 |
| 20 | **Incremental layout** | ★★ | High | §10.4 |
| 21 | **Detachable panels** | ★ | Medium | §7.2 |
| 22 | **Force-directed alternative** | ★★★ | Medium | §2.2 |

---

## Quick Win Checklist

These changes can each be done in <30 minutes and together would transform readability:

- [ ] Add `edgeReducer` that hides edges where `label === 'contains'`
- [ ] Add `nodeReducer` that sets distinct colors per `node_type`
- [ ] Add hover handler that dims non-neighbor nodes to 15% opacity
- [ ] Deduplicate labels: if `name` appears 2+ times, prepend parent directory
- [ ] Add 3-4 filter chip buttons above the graph for toggling node types
- [ ] Set `defaultEdgeType: 'curved'` in Sigma options
- [ ] Add `Ctrl+K` search overlay that filters and focuses nodes
- [ ] Replace sidebar stacked sections with a 3-tab layout

---

## Visual Mockup: Target State

```
 ┌─ [📁 Dirs] [📄 Files] [◆ Classes] [ƒ Funcs] [→ Methods] ──── [🔍 Ctrl+K] ─┐
 │                                                                              │
 │   ┌─ src/ ──────────────────────────────────────┐                            │
 │   │  ┌─ services/ ───────────────────────────┐  │         ┌────────────────┐ │
 │   │  │  ┌───────────┐                        │  │         │ [Node][Agent]  │ │
 │   │  │  │orders.py  │                        │  │         │ [Events][Time] │ │
 │   │  │  │ ┌────────┐ ┌──────────────┐       │  │         ├────────────────┤ │
 │   │  │  │ │OrdReq  │ │ create_order │───────────╋── ─ ─ →│ OrderRequest   │ │
 │   │  │  │ └────────┘ └──────────────┘       │  │         │ Type: class    │ │
 │   │  │  │ ┌────────┐ ┌──────────────┐       │  │         │ Status: idle   │ │
 │   │  │  │ │OrdSum  │ │discount_qty  │       │  │         │ File: srv/o.py │ │
 │   │  │  │ └────────┘ └──────────────┘       │  │         │                │ │
 │   │  │  └────────────────────────────────────┘  │         │ class OrderReq │ │
 │   │  │  ┌───────────┐                           │         │   name: str    │ │
 │   │  │  │pricing.py │  ← only import edges      │         │   qty: int     │ │
 │   │  │  │  ...      │     shown as curved lines  │         │   ...          │ │
 │   │  │  └───────────┘                           │         └────────────────┘ │
 │   │  └──────────────────────────────────────────┘                            │
 │   └─────────────────────────────────────────────┘                            │
 │                                                                              │
 │  [+] [-] [⊡ Fit]                                                             │
 └──────────────────────────────────────────────────────────────────────────────┘
```

Key differences from current:
1. **Containment shown by nesting**, not edges — dramatically fewer lines.
2. **Edge type visible** — only semantic edges drawn, as curved arrows.
3. **Type encoding** — shapes and colors differentiate node types at a glance.
4. **No label overlap** — labels sized to fit, duplicates qualified.
5. **Filter bar** — user controls what's visible.
6. **Tabbed sidebar** — no vertical scroll to reach events/timeline.
7. **Search** — instant access to any node.
