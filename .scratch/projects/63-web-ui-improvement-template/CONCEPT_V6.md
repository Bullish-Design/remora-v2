# Concept: Graph View Overhaul (v6)

## Table of Contents

1. [Executive Summary](#1-executive-summary) - What is still failing in the latest screenshot and why v6 is needed.
2. [Observed Issues in Latest Screenshot](#2-observed-issues-in-latest-screenshot) - Concrete UI failures visible in `ui-playwright-20260328-121351-721.png`.
3. [Gap vs Desired Demo Outcome](#3-gap-vs-desired-demo-outcome) - Where current behavior still misses the demo goal.
4. [Root Causes in Current V5 Behavior](#4-root-causes-in-current-v5-behavior) - Code-level causes driving the visual issues.
5. [V6 Goals](#5-v6-goals) - Non-negotiable outcomes for the next revision.
6. [V6 Layout Strategy](#6-v6-layout-strategy) - How to present connected and isolated nodes without fragmentation.
7. [V6 Label Strategy](#7-v6-label-strategy) - How to keep labels always visible but concise and readable.
8. [V6 Hierarchy and Edge Strategy](#8-v6-hierarchy-and-edge-strategy) - Make structure and relationships visible at first glance.
9. [V6 Implementation Plan](#9-v6-implementation-plan) - Step-by-step changes in `index.html` and tests.
10. [V6 Verification Plan](#10-v6-verification-plan) - Automated and visual checks to prove the UI meets the target.
11. [Rollout Plan](#11-rollout-plan) - Safe shipping sequence with fallback controls.
12. [Definition of Done](#12-definition-of-done) - Acceptance bar for v6 completion.

## 1. Executive Summary

The latest screenshot (`ui-playwright-20260328-121351-721.png`) confirms that v5 solved overlap and stability issues, but the graph still does not hit the demo goal of instant architectural comprehension with a strong “wow” first impression.

Main problem: the view is now readable at the node level, but still weak at the **story level**. The graph appears fragmented, path labels are too verbose, and structure cues (hierarchy + dependency emphasis) do not guide the eye toward a clear main narrative.

v6 should focus on **presentation quality and cognitive parsing**, not raw rendering correctness.

## 2. Observed Issues in Latest Screenshot

### 2.1 Label verbosity is too high

The graph includes full absolute path labels (for example long `.../src/models/order.py::...`) that dominate visual attention and reduce scannability.

Impact:
- technical viewers spend time parsing filesystem noise instead of relationships,
- central cluster appears cluttered despite limited node count,
- the UI looks “debug-like” rather than polished.

### 2.2 Composition is still fragmented into separated islands

There are multiple disconnected clusters in bottom-left and bottom-right with large unused space between them and the top dependency cluster.

Impact:
- graph looks disjointed and accidental,
- presenter cannot narrate a coherent left-to-right or top-to-bottom flow,
- first impression remains “scatter” instead of “architecture map.”

### 2.3 Weak primary/secondary visual hierarchy

Important flow nodes (order/service dependency chain) are not strongly separated from peripheral/virtual/observer groups.

Impact:
- eye does not lock onto the main pathway quickly,
- all clusters feel similarly weighted.

### 2.4 Filesystem grouping remains too subtle

`filesystem` is enabled, but box/group cues are not clearly organizing the scene.

Impact:
- viewers do not immediately see module ownership boundaries,
- grouping channel is present but underpowered.

### 2.5 Edge storytelling remains underpowered for disconnected graphs

Only some edges are visible in the central/top area; isolated groups have no relation context.

Impact:
- disconnected nodes feel like random leftovers,
- visual meaning of “why this node is here” is not obvious.

## 3. Gap vs Desired Demo Outcome

Desired demo behavior:
1. A viewer can identify core flow and supporting clusters within 2-3 seconds.
2. Labels are always visible but concise.
3. Visual hierarchy communicates: core logic first, support/virtual nodes second.
4. Layout feels intentional and high-signal, not sparse/scattered.

Current behavior:
1. Readable nodes, but still too much label and spacing noise.
2. Core flow exists, but is not dominant enough.
3. Isolated clusters dilute narrative focus.

## 4. Root Causes in Current V5 Behavior

### 4.1 Label qualification escalates to absolute file paths

The uniqueness pipeline currently allows path-heavy labels, and many file paths are absolute.

Consequence: readability regresses when uniqueness requires level 3 fallback.

### 4.2 Component packing treats disconnected components as peers

Disconnected components are packed in a deterministic way, but without strong “primary vs peripheral” weighting.

Consequence: peripheral groups receive too much canvas priority.

### 4.3 No dedicated treatment for isolated/peripheral nodes

Nodes with no strong relationship context are laid out similarly to core graph structures.

Consequence: low-information nodes consume high-attention positions.

### 4.4 Hierarchy overlays are conservative

Box rendering and header gating avoid clutter, but in sparse views this can make grouping too faint.

Consequence: hierarchy exists technically, but does not drive comprehension.

## 5. V6 Goals

1. Preserve always-visible labels while making labels concise and human-parsable.
2. Make core connected architecture visually dominant by default.
3. De-emphasize isolated/peripheral nodes without hiding them.
4. Make filesystem grouping clearly legible when enabled.
5. Maintain deterministic placement and camera reliability.

## 6. V6 Layout Strategy

### 6.1 Two-zone composition

Split graph into two visual zones:
- **Core zone**: components with meaningful connectivity (edge-rich, larger clusters).
- **Peripheral zone**: low-degree/isolated components.

Core zone gets central canvas priority; peripheral zone is docked in predictable rails (bottom or side lanes) with reduced visual weight.

### 6.2 Component priority scoring

Score components by:
- node count,
- internal edge count,
- count of cross-file edges,
- count of non-virtual symbol types.

Sort by score for placement; highest-score component anchors the scene.

### 6.3 Peripheral docking

Place low-score components into compact dock rows with tighter spacing and lower edge emphasis.

This keeps all labels visible while preventing peripheral components from competing with the core story.

### 6.4 Reserved narrative corridor

Maintain a central corridor for the main dependency flow to reduce arc crossing and improve readability during demos.

## 7. V6 Label Strategy

### 7.1 Workspace-relative labels only

Never render absolute paths in primary labels.

Process:
1. detect common workspace prefix,
2. convert to workspace-relative paths,
3. use shortest unique suffix path segments.

### 7.2 Two-line label model for long qualifiers

Keep node names prominent, push qualifier into a smaller secondary line when needed.

Example:
- line 1: `OrderSummary`
- line 2: `models/order.py`

### 7.3 Deterministic truncation

When still too long, truncate middle segments (`src/.../models/order.py`) with deterministic rules.

## 8. V6 Hierarchy and Edge Strategy

### 8.1 Strengthen top-level hierarchy boxes

Always render top-level module boxes with stronger stroke alpha and header visibility when `filesystem` is on.

Nested boxes remain gated by size/zoom thresholds.

### 8.2 Edge channel clarity by role

- Core-zone edges: highest visibility.
- Peripheral-zone edges: lower alpha unless selected.
- Cross-zone edges: curved and visually distinct to explain attachment points.

### 8.3 Context edges for isolated nodes

For nodes with no explicit edges, optionally render a light “context tether” to their file/module anchor (visual-only, not semantic graph edge) to prevent “floating orphan” perception.

## 9. V6 Implementation Plan

Scope:
- `src/remora/web/static/index.html`
- `tests/unit/test_views.py`
- `tests/acceptance/test_web_graph_ui.py`

### Step 1: Label pipeline refinement

- Add workspace-root stripping and relative-path normalization.
- Replace absolute-path label fallbacks.
- Add deterministic truncation helper.

### Step 2: Component scoring and zoning

- Add `componentScore` function.
- Partition into core/peripheral sets.
- Update packing to center core and dock peripheral components.

### Step 3: Peripheral visual treatment

- Lower default node/edge emphasis for peripheral zone.
- Restore full emphasis on hover/selection.

### Step 4: Hierarchy visibility upgrade

- Boost top-level box/header visibility.
- Keep nested declutter thresholds.

### Step 5: Optional context tether rendering

- Add lightweight visual tethers for edge-less nodes to module anchors (toggleable).

### Step 6: Tests and metrics updates

- Unit markers for new helpers.
- Acceptance checks for:
  - no absolute path labels,
  - minimum core-zone occupancy,
  - bounded peripheral-zone footprint.

## 10. V6 Verification Plan

### Automated

1. **No absolute labels**: assert no label starts with `/` or drive prefix.
2. **Core dominance metric**: top scored component occupies meaningful central area.
3. **Peripheral containment**: low-score components remain within dock band bounds.
4. **Label overlap bound**: keep overlap ratio under threshold.

### Visual

Capture required screenshots:
1. default load,
2. reset view,
3. filesystem on/off,
4. cross-file emphasis on.

## 11. Rollout Plan

1. Ship behind `LAYOUT_MODE = "v6_core_peripheral"` with v5 fallback.
2. Validate on demo repo and at least one additional medium-size Python repo.
3. Keep fallback for one patch cycle, then remove if stable.

## 12. Definition of Done

v6 is complete when:
1. Latest screenshot shows a clear dominant core flow with peripheral nodes docked.
2. Labels are always visible and do not contain absolute paths.
3. Filesystem grouping is visibly useful at first glance.
4. Acceptance metrics pass consistently.
5. Presenter can explain architecture from default view without manual cleanup actions.
