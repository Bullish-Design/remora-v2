# Concept: Graph View Overhaul (v5)

## Table of Contents

1. [Executive Summary](#1-executive-summary) - Why the latest screenshot still misses the demo objective.
2. [Observed Failures in Latest Screenshot](#2-observed-failures-in-latest-screenshot) - Concrete visual problems visible in `ui-playwright-20260328-110404-178.png`.
3. [Gap vs Desired Demo Outcome](#3-gap-vs-desired-demo-outcome) - Exact mismatch against the “technical wow + immediate legibility” target.
4. [Root Causes in Current V4 Implementation](#4-root-causes-in-current-v4-implementation) - Code-level explanation for each failure mode.
5. [V5 Design Goals](#5-v5-design-goals) - Non-negotiable UX/visual outcomes for the graph view.
6. [V5 Layout Model: Component-First + Lane-Within-Component](#6-v5-layout-model-component-first--lane-within-component) - Replace global file striping with graph-aware placement.
7. [V5 Camera and Fit Model](#7-v5-camera-and-fit-model) - Readability-first framing with occupancy targets and asymmetric margins.
8. [V5 Labels, Edges, and Filesystem Hierarchy](#8-v5-labels-edges-and-filesystem-hierarchy) - Disambiguation, edge legibility, and box reliability fixes.
9. [V5 Implementation Plan](#9-v5-implementation-plan) - Ordered, step-by-step changes scoped to `index.html` plus tests.
10. [V5 Verification Plan](#10-v5-verification-plan) - Automated + screenshot checks that prove the UI reached the goal.
11. [Rollout Strategy](#11-rollout-strategy) - Safe rollout, fallback switches, and tuning sequence.
12. [Definition of Done](#12-definition-of-done) - Acceptance bar for shipping the web UI.

## 1. Executive Summary

The latest screenshot (`ui-playwright-20260328-110404-178.png`) is an improvement over the prior collapsed-strip state, but it still falls short of the intended demo outcome.

The graph is now less overlapped, yet it has three critical failures for a technical-audience demo:

1. The composition is fragmented into islands with excessive dead space.
2. Relationship understanding is still slow (too many long, low-priority arcs and weak structural grouping cues).
3. The default view does not immediately communicate architecture at first glance.

v5 should shift from “file-lane packing only” to a **component-first graph layout** with stronger readability constraints, then run lane layout inside each component. This preserves determinism and always-visible labels while making the view understandable within 2-3 seconds.

## 2. Observed Failures in Latest Screenshot

### 2.1 Graph mass occupies too little of the available canvas

The left panel graph area contains large empty zones (especially lower-left and mid-left), while node clusters remain concentrated near the top-middle and lower-middle. This makes the scene look sparse and accidental rather than deliberate.

### 2.2 Semantically related nodes are visually far apart

Long curved edges connect distant groups (e.g., central `create_order` to low-row nodes). This increases edge crossing and forces the viewer to trace large arcs, which is cognitively expensive in a live demo.

### 2.3 Duplicate labels remain ambiguous

Clusters with repeated labels (e.g., variants of `OrderRequest`/`OrderSummary`) still read as visually repetitive and difficult to differentiate without clicking each node.

### 2.4 Hierarchy (filesystem) is not contributing enough

`filesystem` is enabled in the toolbar, but hierarchy is not clearly helping the viewer parse ownership boundaries. In this screenshot, grouping is not visually obvious enough to guide the eye.

### 2.5 Visual emphasis hierarchy is still weak

Node chips are readable, but edge semantics and layout grouping are not strong enough to make the “main story” pop. The eye lands on labels first, then quickly loses structure due to distributed arcs and cluster gaps.

## 3. Gap vs Desired Demo Outcome

Desired outcome for this demo:
- immediate understanding of where core logic lives,
- immediate understanding of main cross-file dependencies,
- stable, intentional visual composition that looks curated ("wow") rather than incidental.

Current outcome:
- labels are visible, but the architecture story is still not obvious,
- the graph feels under-packed and disconnected,
- grouping and relationship channels do not reinforce one another strongly enough.

Conclusion: v4 addressed severe overlap and camera regressions, but not **narrative legibility**.

## 4. Root Causes in Current V4 Implementation

### 4.1 Layout is file-first, not graph-topology-first

`layoutNodes` currently builds columns by file and wraps rows by width estimate. This is deterministic but not dependency-aware. Connected components can be split across distant regions, producing long arcs and weak local coherence.

### 4.2 Vertical spread is over-amplified for some columns

Per-node Y offset combines depth, line normalization, duplicate offsets, and slot index spacing. In sparse files, this can push nodes far from related clusters, causing the “floating lower row” effect.

### 4.3 Initial fit path does not optimize occupancy/readability

Initial load uses `applyCustomFit(0)`, which sets a baseline camera state after `setCustomBBox`. This is stable, but can leave graph occupancy lower than desired (graph too small relative to viewport) and does not enforce a minimum readable label scale target.

### 4.4 Label disambiguation is not globally uniqueness-guaranteed

`qualifyLabels` adds a single parent/path qualifier pass. In repeated naming patterns, collisions remain semantically hard to distinguish in a dense visual.

### 4.5 Filesystem boxes depend on directory-node availability + threshold gates

When directory coverage is sparse or thresholds suppress labels, filesystem grouping contributes little. The feature exists, but in dense/sparse mixed views it can become visually absent as an organizing aid.

## 5. V5 Design Goals

1. **Narrative-first default view**: a new viewer should understand the core flow in under 3 seconds.
2. **High occupancy without clutter**: graph should use canvas intentionally (not tiny center island, not overpacked strip).
3. **Topology-coherent clustering**: connected nodes should be near each other by default.
4. **Unambiguous labels**: repeated names must be distinguishable at a glance.
5. **Always-visible labels retained**: keep current constraint.
6. **Deterministic layout retained**: same input graph => same output positions.
7. **No camera blank/regression risk**: maintain v4 stability improvements.

## 6. V5 Layout Model: Component-First + Lane-Within-Component

### 6.1 Component-first partitioning

Before file-lane layout, build an undirected adjacency from visible graph edges and compute connected components.

- Each component becomes a layout unit.
- Sort components by descending node count, then lexicographic stable tiebreaker on node ids.

Why: this keeps strongly related nodes together and reduces long cross-canvas edge arcs.

### 6.2 Internal component layout (reuse lane logic locally)

Inside each component:
- keep file grouping and deterministic node ordering (`depth`, `start_line`, `name`),
- apply wrapped lanes with tighter spacing defaults,
- clamp per-column vertical spread so sparse files cannot create distant floating rows.

### 6.3 Global component packing

Pack component rectangles into a deterministic grid/shelf layout that targets viewport occupancy.

- Place largest component first near visual center-left.
- Place remaining components around it using shelf packing with fixed gutters.
- Apply post-pass translation so overall centroid is stable and not top-biased.

### 6.4 Attach singleton satellites near nearest connected component

For 1-node components that have at least one edge, place near the nearest endpoint cluster rather than in a detached lower strip.

### 6.5 Occupancy normalization pass

After layout:
- compute graph bounds,
- if occupancy is below target, scale up coordinates (within max overlap guard),
- if occupancy is above target, scale down slightly.

This creates a consistent visual density across repos.

## 7. V5 Camera and Fit Model

### 7.1 Remove baseline camera override on initial fit

Do not call `camera.setState({x:0.5, y:0.5, ratio:1})` in the load path.

Instead:
- always use a single fit path (`setCustomBBox` + `animatedReset`),
- allow `duration=0` or very short animation for initial load while still honoring bbox fit.

### 7.2 Readability-constrained fit

Extend fit with hard constraints:
- minimum median label width in pixels,
- minimum node-separation in pixels,
- asymmetric safe margins for top-left controls and right sidebar.

If full inclusion violates label-readability floor, prefer slight clipping of low-priority outskirts over global illegibility.

### 7.3 Stable re-fit policy

Re-fit only on:
- initial load,
- explicit reset button,
- major graph topology changes.

Do not aggressively re-fit on every minor state change; preserve spatial memory.

## 8. V5 Labels, Edges, and Filesystem Hierarchy

### 8.1 Global unique label qualification

Replace single-pass `qualifyLabels` with iterative qualification:

1. start with `name`,
2. then `parent/name`,
3. then `dir/parent/name`,
4. then relative file path + name,
5. fallback to short deterministic hash suffix.

Stop when all visible labels are unique.

### 8.2 Edge readability priorities

- Keep edge count complete, but modulate visual priority:
  - same-file edges: thinner/lower-alpha,
  - cross-file edges: thicker/higher-alpha/curve,
  - selected-node neighborhood: temporary emphasis boost.
- Add optional mild length-based alpha attenuation so very long edges do not dominate.

### 8.3 Filesystem hierarchy reliability

If directory nodes are sparse/missing, synthesize directory groups from `file_path` segments for box rendering.

- Always render top-level group boundaries at readable alpha.
- Render nested headers only when area/zoom thresholds are met.
- Keep boxes as context, not dominant foreground objects.

## 9. V5 Implementation Plan

Scope remains:
- `src/remora/web/static/index.html`
- targeted tests in `tests/unit/test_views.py` and `tests/acceptance/test_web_graph_ui.py`

### Step 1: Add v5 layout mode scaffolding

- Introduce `LAYOUT_MODE = "v5_component"` (with temporary fallback to current v4 mode).
- Keep deterministic seedless behavior.

### Step 2: Implement component extraction + component-aware layout

- Build component sets from current nodes/edges.
- Apply existing lane layout per component.
- Add global component packing pass.
- Add singleton satellite attach rule.

### Step 3: Add occupancy normalization

- Compute viewport occupancy metric.
- Apply bounded coordinate scaling to hit target range.

### Step 4: Replace initial fit camera baseline override

- Refactor `applyCustomFit` to one path for all durations.
- Include asymmetric fit padding and readable-label guard.

### Step 5: Upgrade label qualification

- Implement iterative qualifier depth until uniqueness.
- Keep labels concise where possible.

### Step 6: Edge priority tuning

- Introduce length-aware alpha and stronger cross-file defaults.
- Preserve existing filter chips and cross-file emphasis toggle.

### Step 7: Filesystem fallback grouping

- Build synthetic directory boxes when directory nodes are absent.
- Retain current behavior when true directory nodes exist.

### Step 8: Tests and docs

- Update view-marker unit test assertions for new functions/constants.
- Add acceptance metric checks (occupancy + overlap + visibility).
- Capture screenshot set for regression comparison.

## 10. V5 Verification Plan

### 10.1 Automated metrics (acceptance test additions)

1. **Viewport occupancy**
- assert visible node bbox occupies at least 35% and at most 85% of graph canvas area.

2. **Label overlap ratio**
- estimate overlap from `nodeLabelHitboxes` and assert below threshold (e.g. < 8%).

3. **Component coherence proxy**
- for each connected component, average pairwise distance should be lower than distance to other components by margin.

4. **Edge visibility floor**
- ensure non-hidden edges have non-zero on-screen span and arrow visibility is present.

5. **Label uniqueness**
- assert rendered labels are unique when node ids differ.

### 10.2 Required screenshot checks

Capture and review:
1. default load,
2. after reset,
3. cross-file emphasis on,
4. filesystem off/on comparison.

### 10.3 Human review checklist

- Architecture is understandable at a glance.
- Core flow nodes are visually central and connected.
- No obvious “orphan strips” unless genuinely disconnected in data.

## 11. Rollout Strategy

1. Implement v5 behind a local JS mode flag and keep current v4 path as fallback.
2. Run full web test subset + screenshot comparisons.
3. Default to v5 when metrics pass on demo baseline and one additional medium-density repo.
4. Remove v4 fallback after one patch cycle with no regressions.

## 12. Definition of Done

v5 is complete when all are true:

1. Latest screenshot no longer appears fragmented or under-packed.
2. Label overlap is below threshold while labels remain always visible.
3. Connected structures are spatially coherent by default.
4. Filesystem grouping is visibly useful when enabled.
5. Acceptance tests include occupancy/overlap checks and pass reliably.
6. Demo presenter can explain architecture from default view without zoom/pan/filter adjustments.
