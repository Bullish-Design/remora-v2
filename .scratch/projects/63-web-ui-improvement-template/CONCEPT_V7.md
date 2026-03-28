# Concept: Graph View Overhaul (v7)

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Observed Issues in Latest Screenshot](#2-observed-issues-in-latest-screenshot)
3. [Gap vs Desired Demo Outcome](#3-gap-vs-desired-demo-outcome)
4. [Root Causes in Current V6 Behavior](#4-root-causes-in-current-v6-behavior)
5. [Sigma Framework Opportunities](#5-sigma-framework-opportunities)
6. [V7 Goals](#6-v7-goals)
7. [V7 Layout Strategy](#7-v7-layout-strategy)
8. [V7 Label and Readability Strategy](#8-v7-label-and-readability-strategy)
9. [V7 Hierarchy and Edge Strategy](#9-v7-hierarchy-and-edge-strategy)
10. [V7 Visual Polish Strategy](#10-v7-visual-polish-strategy)
11. [V7 Implementation Plan](#11-v7-implementation-plan)
12. [V7 Verification Plan](#12-v7-verification-plan)
13. [Definition of Done](#13-definition-of-done)

## 1. Executive Summary

The V6 screenshot (`ui-playwright-20260328-130400-075.png`) confirms that core/peripheral zoning was implemented and label paths are now workspace-relative. However, the graph still fails the "instant architectural comprehension" bar for three reasons:

1. **The peripheral dock is illegible.** Labels in the bottom rows collide and overlap, making the peripheral zone look like noisy debris rather than organized supporting context.
2. **The core zone is visually insufficiently dominant.** It occupies roughly a third of the canvas and does not command primary attention.
3. **Hierarchy boxes are invisible.** Filesystem grouping provides no comprehension benefit at current alpha levels on the dark background.

V7 focuses on **peripheral readability, core dominance, and hierarchy visibility** — the three remaining blockers to a demo-ready first impression.

Additionally, an audit of the bundled Sigma.js v3 reveals that we use only 8 of 33+ available settings and miss several high-value built-in features. V7 should leverage these to replace custom code with framework-native capabilities, improving both UX quality and maintainability.

## 2. Observed Issues in Latest Screenshot

### 2.1 Peripheral label collision

The bottom dock rows pack labels so tightly that text overlaps horizontally. Examples:
- `Repository artifact poli…Runtime profi…Source graph mappi…Validation checks` reads as one run-on string.
- `Virtual agents  risk_score  choose_warehouse  format_usd  no-companion-observer` blends together.
- `demo-docs-filter-obs…demo-review-obs…demo-src-filter-observer` is similarly unreadable.

Impact: the peripheral zone actively hurts comprehension; a viewer would have been better off without it.

### 2.2 Core zone canvas allocation too small

The core dependency cluster (`create_order` → `models/OrderRequest` → `OrderRequest` → `discount_for_tier` → `compute_total`, plus `OrderSummary` branch) occupies approximately the top 35% of the graph canvas. The peripheral dock and whitespace between zones consume the remaining 65%.

Impact: the eye scans equal amounts of useful and noisy content; there is no clear "hero" area.

### 2.3 Hierarchy boxes invisible on dark background

Filesystem bounding boxes are technically rendered (the `filesystem` toggle is enabled), but their fill and stroke alphas are so low on the `#0f1729` background that they provide no grouping signal at a glance.

Impact: the grouping feature exists but has zero visual payoff; toggling filesystem on/off produces no perceivable difference.

### 2.4 `apply_tax` floats in no-man's-land

The `apply_tax` node sits between the core cluster and the peripheral dock with no clear zone membership and no obvious edge context. It looks orphaned.

Impact: breaks the two-zone mental model and makes the layout feel accidental.

### 2.5 No visual zone separator

Core zone blends directly into peripheral zone with no dividing element (rule, gap, or tonal shift). The viewer has no affordance for "above this line = main architecture, below = supporting."

Impact: the zoning concept is invisible to the user.

### 2.6 Edge homogeneity in core zone

All visible edges in the core zone use the same cyan color and weight. The primary dependency chain does not stand out from secondary edges.

Impact: the viewer cannot trace the main narrative flow without carefully reading labels.

### 2.7 Right panel dominates width

The right sidebar (Agent Panel, Events, Timeline) is fixed-width and consumes roughly 35% of the viewport, compressing the graph canvas.

Impact: the graph — the primary visual artifact — gets less space than it needs for readable label placement.

## 3. Gap vs Desired Demo Outcome

| Demo goal | Current state | Gap |
|---|---|---|
| Core flow identifiable in 2-3 seconds | Core cluster exists but doesn't dominate | Core needs more canvas, stronger edge emphasis |
| Labels always visible and readable | Core labels OK; peripheral labels collide | Peripheral needs spacing or overflow strategy |
| Hierarchy communicates structure | Boxes invisible | Need visible fills/strokes on dark bg |
| Layout feels intentional | Peripheral dock is noisy; zone boundary unclear | Need separator, better peripheral spacing |
| "Wow" first impression | Still reads as debug scatter | Needs polish: zone contrast, edge narrative, whitespace |

## 4. Root Causes in Current V6 Behavior

### 4.1 Peripheral packing uses same density as core

The peripheral docking algorithm places nodes with the same spacing constants as the core zone. With many small peripheral components, this results in labels colliding in tight rows.

Fix direction: peripheral nodes need wider horizontal spacing or a grid layout with explicit cell sizing based on label width.

### 4.2 Core zone does not receive proportional canvas allocation

The two-zone split gives peripheral components their "natural" packed height, which can equal or exceed core zone height when there are many peripheral components.

Fix direction: allocate a minimum percentage of canvas height (e.g. 60-70%) to the core zone regardless of peripheral count.

### 4.3 Hierarchy box alphas are calibrated for light backgrounds

Current fill alpha (`0.07 + depth*0.02`) and stroke alpha (`0.22 + depth*0.06`) are too subtle against the deep navy background.

Fix direction: increase base alphas significantly (fill `0.12+`, stroke `0.35+`) and use a lighter box fill tint to contrast with `#0f1729`.

### 4.4 No minimum spacing constraint in peripheral dock

Peripheral rows have no per-node minimum width allocation, so short labels from different nodes visually merge.

Fix direction: enforce minimum cell width in peripheral rows, or add visual separators (subtle vertical dividers, chip-style backgrounds).

### 4.5 Zone boundary is implicit

There is no explicit visual element marking the transition from core to peripheral zone.

Fix direction: render a faint horizontal rule, tonal background shift, or labeled divider between zones.

## 5. Sigma Framework Opportunities

An audit of the bundled Sigma.js v3 (`sigma.min.js`, 176KB) against current usage reveals significant untapped built-in functionality. We currently configure 8 settings; 25+ remain at defaults. The following built-in features can replace or enhance custom code.

### 5.1 Currently used settings (8 of 33+)

`labelRenderedSizeThreshold`, `defaultDrawNodeLabel`, `defaultEdgeType`, `edgeProgramClasses`, `stagePadding`, `minCameraRatio`, `maxCameraRatio`, `zIndex`.

### 5.2 High-value unused features

#### `renderEdgeLabels: true` + `defaultDrawEdgeLabel` — Edge text labels

**Status:** Available in bundle (`drawStraightEdgeLabel` exported in `Sigma.rendering`).

Sigma can render relationship type names ("imports", "inherits") directly on edges. Currently edge types are only distinguishable by color, requiring the legend. Enabling this single setting makes edge meaning self-documenting.

**Impact:** Directly solves issue 2.6 (edge homogeneity). Viewers read "imports" along the edge instead of decoding colors.

**Usage:** Set `renderEdgeLabels: true` in the Sigma constructor. Edges must have a `label` attribute (already present — we set `label` to the edge type). Optionally provide `defaultDrawEdgeLabel` for custom styling; the built-in `drawStraightEdgeLabel` works well with dark backgrounds if `edgeLabelColor` is configured.

**Settings to configure:**
- `renderEdgeLabels: true`
- `edgeLabelSize: 10`
- `edgeLabelColor: { color: "#9fb2c8" }` (use `--muted` for subtlety)
- `edgeLabelFont: '"IBM Plex Mono", sans-serif'`

#### `defaultDrawNodeHover` — Native hover highlight

**Status:** Available in bundle (`drawDiscNodeHover` exported in `Sigma.rendering`).

Sigma has a dedicated hover rendering pipeline that draws a glow ring + enlarged label around the hovered node. Currently hover is handled entirely through manual `dimmed` attribute toggling in `enterNode`/`leaveNode` handlers.

**Impact:** Replaces ~30 lines of custom hover dimming logic with a polished framework-native effect. The hovered node gets a highlight ring automatically; combined with the existing `nodeReducer` dimming, this gives a layered hover experience.

**Usage:** Set `defaultDrawNodeHover: drawDiscNodeHover` (or a custom function). The `nodeHoverProgramClasses` setting can optionally assign a WebGL program (e.g. `createNodeBorderProgram`) for the hover ring.

#### `enableEdgeEvents: true` — Edge interactivity

**Status:** Available. Emits `clickEdge`, `enterEdge`, `leaveEdge` events.

Currently only node events are wired. Enabling edge events allows: clicking an edge to show relationship details in the sidebar, hovering an edge to highlight the connected pair and show the edge label.

**Impact:** Adds a new interaction channel that directly supports edge comprehension. Low effort — just set the boolean and add event handlers similar to existing node handlers.

**Usage:** Set `enableEdgeEvents: true` in the Sigma constructor. Wire `renderer.on("clickEdge", ...)` and `renderer.on("enterEdge", ...)`.

#### `animateNodes` — Smooth layout transitions

**Status:** Available in `Sigma.utils.animateNodes`.

When the graph updates (new nodes discovered via SSE), nodes currently jump to new positions. `animateNodes` smoothly interpolates node positions over a configurable duration and easing curve.

**Impact:** Makes the live-updating graph feel alive rather than jarring. Especially valuable during demos when nodes appear in real time.

**Usage:** `Sigma.utils.animateNodes(graph, newPositions, { duration: 500, easing: "cubicInOut" })`.

#### `hideEdgesOnMove` + `hideLabelsOnMove` — Interaction performance

**Status:** Available. Single boolean each.

During pan/zoom, edges and custom label rendering are expensive. These settings hide them during interaction for fluid panning, then restore on stop.

**Impact:** Noticeably smoother interaction with dense graphs. Trivial to enable.

**Usage:** Set `hideEdgesOnMove: true` and/or `hideLabelsOnMove: true`.

#### `createNodeBorderProgram` — Bordered node rendering

**Status:** Available in bundle (`Sigma.rendering.createNodeBorderProgram`).

Renders nodes as concentric discs with a colored border ring instead of flat circles. Border color can indicate node type; fill can indicate zone.

**Impact:** More polished node appearance. Could replace the current flat-circle WebGL nodes with a border treatment that visually encodes type information at the WebGL level (faster than canvas-only encoding).

**Usage:** `nodeProgramClasses: { bordered: createNodeBorderProgram({ borders: [{ size: { value: 0.15 }, color: { attribute: "borderColor" } }] }) }`. Set `type: "bordered"` on nodes.

#### `labelDensity` + `labelGridCellSize` — Zoom-aware label declutter

**Status:** Available. Currently `labelRenderedSizeThreshold: 0` forces all labels visible at all zoom levels.

Sigma has a built-in label collision grid that hides lower-priority labels when zoomed out and progressively reveals them on zoom-in. Tuning `labelDensity` (default: 1, higher = more labels) and `labelGridCellSize` (default: 100px) could provide automatic peripheral label management.

**Impact:** At zoomed-out views, only core labels show; peripheral labels appear on zoom-in. This naturally solves the peripheral label collision problem at certain zoom levels without layout changes.

**Trade-off:** We currently guarantee "all labels always visible" as a design constraint. Using label density would relax this to "all labels visible at sufficient zoom." This is a design decision — potentially acceptable if core labels are always shown via `forceLabel: true`.

**Usage:** Set `labelRenderedSizeThreshold: 4` (show labels for nodes ≥ 4px rendered size), `labelDensity: 0.8`. Set `forceLabel: true` on core-zone nodes to exempt them from decluttering.

#### `cameraPanBoundaries` — Prevent lost-graph panning

**Status:** Available.

Restricts how far users can pan away from the graph, preventing the "lost graph" scenario where users accidentally pan into empty space.

**Impact:** Small UX improvement. Prevents confusion during demos.

**Usage:** Set `cameraPanBoundaries: true` for auto-calculated boundaries based on graph extent.

#### `setCustomBBox` — Core-zone camera framing

**Status:** Already used, but underutilized.

Currently `setCustomBBox` is called with the full graph extent. Setting it to cover only the core zone would make Sigma's auto-fit center on the core architecture, pushing peripheral nodes to canvas edges.

**Impact:** Directly supports V7 core-dominance goal. The initial view frames the core zone with peripheral visible but secondary.

### 5.3 Feature adoption tiers

**Tier 1 — Adopt in V7** (high impact, low risk):
- `renderEdgeLabels` + edge label styling (solves edge narrative)
- `enableEdgeEvents` (adds edge interactivity)
- `hideEdgesOnMove` / `hideLabelsOnMove` (smoother interaction)
- `cameraPanBoundaries` (prevent lost-graph)
- `setCustomBBox` core-zone framing (core dominance)

**Tier 2 — Adopt in V7 with care** (high impact, moderate complexity):
- `defaultDrawNodeHover` with `drawDiscNodeHover` (replace custom hover logic)
- `animateNodes` for SSE-driven graph updates (smooth transitions)

**Tier 3 — Evaluate for V8** (design trade-offs or higher complexity):
- `labelDensity` zoom-aware declutter (changes "always visible" guarantee)
- `createNodeBorderProgram` (requires node type → program mapping overhaul)
- `createNodePiechartProgram` (niche, multi-role nodes only)

## 6. V7 Goals

1. **Peripheral readability**: every peripheral label must be individually readable without hovering.
2. **Core dominance**: core zone occupies at least 55% of graph canvas area and commands primary visual attention.
3. **Visible hierarchy**: filesystem grouping boxes are clearly visible when enabled, providing immediate module-boundary comprehension.
4. **Zone clarity**: a viewer can instantly distinguish core architecture from supporting/peripheral nodes.
5. **Edge narrative**: the primary dependency chain in the core zone is visually emphasized; edge labels show relationship types.
6. **Edge interactivity**: edges are clickable/hoverable, revealing relationship details.
7. **Interaction fluidity**: pan/zoom feels smooth even with dense graphs; live graph updates animate smoothly.
8. **Determinism preserved**: all changes maintain deterministic layout and camera behavior.

## 7. V7 Layout Strategy

### 7.1 Canvas allocation ratio

Reserve a minimum of 60% of vertical canvas space for the core zone. Peripheral zone gets the remaining 40% maximum. If the peripheral zone has few nodes, the core zone expands to fill available space.

### 7.2 Peripheral grid layout

Replace the current tight row packing with a grid-cell approach:
- Measure the maximum label width in each peripheral component.
- Assign each component a cell with width = `max(label_width + padding, MIN_CELL_WIDTH)`.
- Arrange cells in rows with explicit inter-cell gaps.
- Cap rows at canvas width; wrap to additional rows if needed.

This guarantees no label-to-label collision in the peripheral zone.

### 7.3 Zone separator

Render a faint horizontal rule (1px, alpha 0.15) between core and peripheral zones. Optionally add a small label ("supporting nodes") at the left edge of the separator.

### 7.4 Ambiguous node resolution

Nodes that are not clearly core or peripheral (e.g. `apply_tax` with a single weak edge) should be pulled into whichever zone contains their strongest connected neighbor. If truly isolated, they belong in peripheral.

### 7.5 Core zone internal spacing

Slightly increase inter-node spacing within the core zone to give labels breathing room. Use the space freed by capping peripheral zone height.

### 7.6 Core-zone camera framing via `setCustomBBox`

After layout, call `renderer.setCustomBBox(coreZoneBBox)` with only the core zone bounds. This makes Sigma's auto-fit and zoom-reset naturally center on the core architecture, pushing peripheral nodes to canvas edges without extra camera math.

## 8. V7 Label and Readability Strategy

### 8.1 Peripheral label chip styling

Give peripheral node labels a subtle background chip (rounded rect, fill alpha 0.08) to visually separate them from neighbors even when spacing is tight. This creates visual cell boundaries.

### 8.2 Core label sizing

Core zone labels should use slightly larger font size than peripheral labels (e.g. `coreSize * 1.15`) to reinforce visual hierarchy.

### 8.3 Label truncation with tooltip

If any label still exceeds its allocated cell width after the qualification pipeline, truncate with `…` and show full text on hover. Never allow a label to visually invade an adjacent node's space.

## 9. V7 Hierarchy and Edge Strategy

### 9.1 Hierarchy box visibility overhaul

When `filesystem` is enabled:
- Top-level boxes: fill alpha `0.12`, stroke alpha `0.40`, stroke width `1.5px`.
- Nested boxes: fill alpha `0.08`, stroke alpha `0.28`, stroke width `1.0px`.
- Box header labels: alpha `0.70`, font weight semi-bold.
- Use a slightly warmer tint for box fills (e.g. `hsla(220, 30%, 45%, alpha)`) to differentiate from the cold navy background.

### 9.2 Primary edge emphasis

Identify the primary dependency chain (longest path in the core zone's DAG, or highest-degree path):
- Render primary chain edges with full opacity, slightly increased width (2.5px), and a subtle glow or brighter color.
- Render secondary core edges at 70% opacity, standard width.
- Peripheral edges remain at 40% opacity.

### 9.3 Edge labels via `renderEdgeLabels` (Sigma built-in)

Enable Sigma's native edge label rendering to display relationship type names ("imports", "inherits") directly on edges. This replaces color-only edge type encoding with self-documenting text.

Sigma constructor settings:
```js
renderEdgeLabels: true,
edgeLabelSize: 10,
edgeLabelColor: { color: "#9fb2c8" },
edgeLabelFont: '"IBM Plex Mono", "IBM Plex Sans", sans-serif',
edgeLabelWeight: "500",
```

Edge labels are drawn from the existing `label` attribute (already set to edge type). The built-in `drawStraightEdgeLabel` renders text along the edge midpoint. Optionally provide a custom `defaultDrawEdgeLabel` to style for dark backgrounds.

### 9.4 Edge color by relationship type

Differentiate edge types by color (retained from current approach):
- `imports` → cyan (current default, keep).
- `inherits` → warm amber/gold.
- `cross-file` → brighter/wider variant of the base color.

Edge labels (9.3) complement edge colors — color for at-a-glance scanning, text for precise identification.

### 9.5 Edge interactivity via `enableEdgeEvents` (Sigma built-in)

Enable Sigma's edge event system to make edges clickable and hoverable:

```js
enableEdgeEvents: true,
```

Wire event handlers:
- `renderer.on("enterEdge", ...)` — highlight the edge and connected nodes, show edge type/metadata tooltip.
- `renderer.on("leaveEdge", ...)` — restore default styling.
- `renderer.on("clickEdge", ...)` — show edge relationship details in the sidebar (source, target, type, cross-file status).

This adds a new interaction channel parallel to node click/hover, directly supporting edge comprehension.

## 10. V7 Visual Polish Strategy

### 10.1 Zone background tint

Apply a very subtle background tint difference between zones:
- Core zone: current `#0f1729` (or very slightly lighter).
- Peripheral zone: slightly darker or desaturated variant (e.g. `#0c1220`).

This creates an ambient zone distinction without explicit borders.

### 10.2 Peripheral node de-emphasis

Peripheral nodes should use:
- Slightly smaller node size (80% of core node size).
- Lower label opacity (0.7 vs 1.0 for core).
- Muted node border color.

This creates a natural visual recession that says "supporting context."

### 10.3 Native hover highlight via `defaultDrawNodeHover` (Sigma built-in)

Replace the current manual hover dimming logic (~30 lines in `enterNode`/`leaveNode`) with Sigma's built-in hover rendering pipeline:

```js
defaultDrawNodeHover: Sigma.rendering.drawDiscNodeHover,
```

`drawDiscNodeHover` draws a glow ring + enlarged label around the hovered node automatically. The existing `nodeReducer` dimming for non-neighbor nodes is retained — the two effects layer: neighbors dim while the hovered node gets a highlight ring.

This reduces custom code and provides a polished, framework-consistent hover effect.

### 10.4 Interaction performance via `hideEdgesOnMove` / `hideLabelsOnMove` (Sigma built-in)

Enable smooth panning/zooming with dense graphs:

```js
hideEdgesOnMove: true,
hideLabelsOnMove: true,
```

During drag/zoom, edges and expensive custom label rendering are hidden. They restore instantly on interaction stop. This is a single-boolean change that noticeably improves perceived performance.

### 10.5 Camera pan boundaries via `cameraPanBoundaries` (Sigma built-in)

Prevent users from accidentally panning away from the graph into empty space:

```js
cameraPanBoundaries: true,
```

Sigma auto-calculates boundaries from graph extent. During demos, this prevents the "lost graph" scenario.

### 10.6 Smooth graph updates via `animateNodes` (Sigma built-in)

When the graph updates live (new nodes discovered via SSE), use `Sigma.utils.animateNodes` to smoothly interpolate node positions instead of jumping:

```js
// After computing new positions for updated graph:
Sigma.utils.animateNodes(graph, newPositions, {
  duration: 500,
  easing: "cubicInOut",
});
```

This makes live graph updates feel organic rather than jarring, which is especially valuable during demos when nodes appear in real time.

### 10.7 Smooth graph entry

Add a very brief fade-in (200-300ms CSS transition on the graph container opacity) on initial load to avoid the jarring flash of nodes appearing.

## 11. V7 Implementation Plan

Scope: `src/remora/web/static/index.html`, `tests/acceptance/test_web_graph_ui.py`, `tests/unit/test_views.py`.

### Step 1: Sigma settings upgrade

- Add to Sigma constructor: `renderEdgeLabels`, `edgeLabelSize`, `edgeLabelColor`, `edgeLabelFont`, `edgeLabelWeight`, `enableEdgeEvents`, `hideEdgesOnMove`, `hideLabelsOnMove`, `cameraPanBoundaries`.
- Set `defaultDrawNodeHover` to `Sigma.rendering.drawDiscNodeHover` (or custom wrapper for dark-bg styling).
- Verify no regressions from new settings.

### Step 2: Edge event handlers

- Wire `renderer.on("enterEdge", ...)` — highlight edge + connected nodes.
- Wire `renderer.on("leaveEdge", ...)` — restore styling.
- Wire `renderer.on("clickEdge", ...)` — show edge details in sidebar.

### Step 3: Fix peripheral grid layout

- Replace peripheral row packing with grid-cell layout.
- Add `MIN_CELL_WIDTH` constant.
- Measure label widths and allocate cells.
- Add inter-cell gap enforcement.

### Step 4: Core zone canvas reservation + `setCustomBBox`

- After component scoring, allocate 60% minimum vertical canvas to core zone.
- Cap peripheral zone to remaining 40%.
- Adjust peripheral grid cell sizing to fit within cap.
- Call `renderer.setCustomBBox(coreZoneBounds)` for core-zone camera framing.

### Step 5: Zone separator rendering

- In `beforeRender`, draw a faint horizontal rule between core and peripheral zone Y boundaries.
- Optionally render "supporting" label at separator left edge.

### Step 6: Hierarchy box alpha overhaul

- Update box fill/stroke/label alpha constants for dark background.
- Add warmer tint to box fills.
- Verify visibility with filesystem toggle on/off.

### Step 7: Edge narrative emphasis

- Add primary-chain detection (longest/highest-degree path in core DAG).
- Render primary edges with increased opacity and width.
- Edge labels (from Step 1) provide text; color differentiation provides visual scanning.

### Step 8: Peripheral visual de-emphasis

- Scale peripheral node sizes to 80%.
- Lower peripheral label opacity.
- Apply chip-style background to peripheral labels.

### Step 9: Smooth graph updates with `animateNodes`

- In `loadGraph`, when graph already has nodes (SSE update), compute new positions and call `Sigma.utils.animateNodes` instead of directly setting attributes.
- Use `duration: 500, easing: "cubicInOut"`.

### Step 10: Tests and verification

- Update acceptance tests for:
  - No peripheral label overlap (bounding-box intersection check).
  - Core zone occupies ≥ 55% of used canvas height.
  - Hierarchy boxes visible (alpha assertions on box rendering constants).
  - Primary edge emphasis exists (at least one edge with elevated width).
  - Edge labels rendered (assert `renderEdgeLabels` setting is true).
  - Edge events enabled (assert `enableEdgeEvents` setting is true).

## 12. V7 Verification Plan

### Automated

1. **Peripheral label collision**: assert no two peripheral node labels have overlapping bounding boxes.
2. **Core zone dominance**: assert core zone vertical extent ≥ 55% of total graph vertical extent.
3. **Hierarchy box visibility**: assert box fill alpha ≥ 0.10 and stroke alpha ≥ 0.30 at top level.
4. **Primary edge emphasis**: assert at least one core edge renders with width > default.
5. **Edge labels enabled**: assert Sigma `renderEdgeLabels` setting is `true`.
6. **Edge events enabled**: assert Sigma `enableEdgeEvents` setting is `true`.
7. **Existing metrics preserved**: overlap ratio, occupancy, label uniqueness continue to pass.

### Visual

Capture screenshots for:
1. Default load (core zone should dominate center).
2. Filesystem on (boxes clearly visible).
3. Filesystem off (boxes hidden, layout unchanged).
4. Zoom-out to show full graph including peripheral dock.
5. Edge hover (edge highlighted with label visible).
6. Node hover (native glow ring visible on hovered node).

## 13. Definition of Done

V7 is complete when:
1. Every peripheral label is individually readable without hover in the screenshot.
2. The core zone visually dominates the canvas — a viewer identifies the main architecture in ≤ 2 seconds.
3. Filesystem grouping boxes are clearly visible at default zoom when enabled.
4. Core and peripheral zones are visually distinct (separator, tint, or size difference).
5. Primary dependency chain edges are visually emphasized over secondary edges.
6. Edge labels ("imports", "inherits") are visible on edges without hovering.
7. Edges are interactive — hovering highlights, clicking shows details in sidebar.
8. Node hover shows a native highlight ring (via Sigma's `drawDiscNodeHover`).
9. Pan/zoom interaction is fluid (edges/labels hidden during movement).
10. Live graph updates animate smoothly (nodes transition to new positions).
11. All automated acceptance metrics pass.
12. A presenter can demo the graph by saying "here's the core architecture [top], here are the supporting components [bottom]" without needing manual zoom/pan adjustments.
