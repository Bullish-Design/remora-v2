# Concept: Graph View Overhaul (v8)

## Table of Contents

1. [Executive Summary](#1-executive-summary) - What still misses the target and what v8 must fix.
2. [Observed Issues in Latest Screenshot](#2-observed-issues-in-latest-screenshot) - Concrete spacing/layout defects seen in `ui-playwright-20260328-140333-244.png`.
3. [Gap vs Desired Web UI Goal](#3-gap-vs-desired-web-ui-goal) - Mapping current state to the demo/UX outcomes.
4. [Root Causes in Current v7 Implementation](#4-root-causes-in-current-v7-implementation) - Why the current constants/algorithms produce these issues.
5. [V8 Goals](#5-v8-goals) - Non-negotiable outcomes for this revision.
6. [V8 Layout and Spacing Strategy](#6-v8-layout-and-spacing-strategy) - Proposed corrective architecture.
7. [V8 Implementation Plan](#7-v8-implementation-plan) - Ordered steps in `src/remora/web/static/index.html` and tests.
8. [V8 Verification Plan](#8-v8-verification-plan) - Automated + visual checks to prove fixes.
9. [Definition of Done](#9-definition-of-done) - Exit criteria for shipping v8.

## 1. Executive Summary

The latest screenshot (`ui-playwright-20260328-140333-244.png`) shows clear progress from v7 (edge labels, zone separator, stronger hierarchy boxes), but spacing and layout still miss the target of **instant architectural comprehension**.

The primary misses are:

1. Core graph content is pushed into the top-left and partially occluded by the filter overlay.
2. There is excessive dead vertical space between the core cluster and peripheral dock.
3. Peripheral labels are improved but still visually crowded in bottom rows with crossing tethers.
4. A bridge node (`apply_tax`) still reads as spatially ambiguous between zones.
5. Sidebar width remains large enough to materially reduce graph breathing room.

v8 should focus on **spatial balance and composition control**, not new interaction features.

## 2. Observed Issues in Latest Screenshot

### 2.1 Core cluster is clipped/occluded at top-left

- `create_order` is near the top-left edge and partially under the filter panel footprint.
- Core edges also run beneath the top-left controls, reducing first-glance readability.

Impact: the most important content is not presented as a clear hero region.

### 2.2 Excessive dead space between core and peripheral zones

- The separator sits far below the core cluster while peripheral rows begin much lower.
- Result is a large central void with mostly long diagonal edges crossing it.

Impact: eye travel increases and narrative flow is diluted.

### 2.3 Core composition is too flat (wide, low-height ribbon)

- Core nodes are arranged primarily in a horizontal strip.
- Camera fitting appears width-constrained, so core vertical presence stays weak.

Impact: even with core-first fit, the architecture does not dominate the canvas.

### 2.4 Peripheral rows still feel dense and noisy

- Long labels in the dock have improved celling, but rows remain visually congested.
- Context tether lines pass through dense label areas.

Impact: supporting context still competes with core readability.

### 2.5 Ambiguous bridge node placement (`apply_tax`)

- `apply_tax` appears between core and peripheral regions.
- It does not read clearly as either part of the main chain or supporting dock.

Impact: weakens the two-zone mental model.

### 2.6 Sidebar still consumes too much horizontal budget

- At 1280px width, the fixed sidebar footprint leaves limited canvas width for graph layout.

Impact: graph spacing constraints get tighter than necessary, increasing collision pressure.

### 2.7 Zone separator is present but too subtle

- The dashed separator and label are visible only on close inspection.

Impact: zone intent exists technically, but not as a strong compositional cue.

## 3. Gap vs Desired Web UI Goal

| Desired outcome | Current state | Gap |
|---|---|---|
| Faster graph understanding after startup | Core appears off-balance and partially occluded | Need safe-area-aware fit and centered hero placement |
| Clear separation of graph state, event stream, action panel | Functional separation exists, but graph area is compositionally weak and compressed by sidebar width | Need graph-first width rebalance and stronger zone hierarchy |
| Reduced cognitive load switching between nodes/proposals | Large whitespace + long cross-zone edges create scanning overhead | Need tighter vertical rhythm and cleaner bridge handling |
| Labels readable without effort | Core mostly readable; peripheral still dense with tether interference | Need stronger peripheral spacing and tether de-emphasis/routing |
| Layout feels intentional and demo-ready | Reads improved but still "debug layout" in places | Need composition constraints, not just collision avoidance |

## 4. Root Causes in Current v7 Implementation

### 4.1 Camera fit does not reserve UI-overlay safe areas

`computeFitBBox()` uses static margins and `setCustomBBox(coreBounds)` but does not account for the top-left filter overlay footprint.

Consequence: important core nodes can land under overlays even when technically inside the fitted graph box.

### 4.2 Sidebar width is still too permissive

Current CSS uses:

```css
#sidebar { width: min(440px, 92vw); }
```

Consequence: on 1280px viewports, sidebar can take a large share of width, forcing tighter graph composition.

### 4.3 Core/peripheral vertical rhythm uses fixed docking gaps

The dock uses fixed constants (`PERIPHERAL_DOCK_GAP_Y`, `PERIPHERAL_GRID_GAP_Y`) plus occupancy normalization scaling.

Consequence: depending on component bounds, central dead space can grow significantly.

### 4.4 Core layout lacks aspect-ratio normalization

Core component placement is score/packing driven, but there is no explicit pass to avoid overly wide-and-flat core geometry.

Consequence: camera fit often becomes width-limited, shrinking perceived core dominance.

### 4.5 Ambiguous nodes are zoned by component score only

Bridge-like nodes connected to core can still end up in peripheral/mid-space if their component score is low.

Consequence: nodes like `apply_tax` break zone semantics.

### 4.6 Separator styling is low-contrast relative to scene complexity

The current separator uses low alpha (`~0.20`) and thin dashed styling.

Consequence: separator does not reliably anchor the two-zone narrative.

## 5. V8 Goals

1. **Core safe placement:** no core node or core edge label is occluded by the filter bar or clipped against top/left viewport margins.
2. **Core prominence:** core visual mass should occupy the dominant attention band (upper-middle), not the top-left corner.
3. **Rhythmic spacing:** reduce dead space between core and peripheral zones while preserving label readability.
4. **Peripheral legibility:** peripheral labels remain readable with lower visual competition from tethers.
5. **Zone integrity:** bridge nodes are deterministically assigned to a clear zone or dedicated bridge lane.
6. **Canvas budget:** sidebar width no longer throttles graph readability on 1280px desktop captures.
7. **Separation clarity:** core/peripheral separator is obvious at first glance.

## 6. V8 Layout and Spacing Strategy

### 6.1 Safe-area-aware camera fit

Add a safe-area pass before applying camera reset:

- Measure overlay footprints (`#filter-bar`, `#zoom-controls`) in viewport pixels.
- Convert those insets into graph-space margins for `computeFitBBox()`.
- Apply asymmetric top/left padding so core labels cannot render under controls.

Proposed additions:

- New constants:
  - `FIT_SAFE_LEFT_PX = 288`
  - `FIT_SAFE_TOP_PX = 124`
  - `FIT_SAFE_RIGHT_PX = 24`
  - `FIT_SAFE_BOTTOM_PX = 64`
- Derive unit offsets from renderer dimensions and current bbox span.

### 6.2 Sidebar width rebalance

Change sidebar sizing to prioritize graph canvas on desktop:

```css
#sidebar { width: clamp(320px, 30vw, 400px); }
```

Optional media behavior:

- At `max-width: 1180px`, use `clamp(300px, 36vw, 380px)`.

### 6.3 Core aspect normalization pass

After core placement and before fit:

- Compute core bounds aspect (`width / height`).
- If aspect exceeds threshold (e.g. `> 1.9`), apply bounded transform around core center:
  - compress X by `0.88`
  - expand Y by `1.12`
- Re-run overlap sanity checks for core labels.

This makes core less ribbon-like and improves perceived dominance.

### 6.4 Dynamic core-peripheral spacing (replace fixed dead gap behavior)

Replace fixed vertical gap behavior with bounded dynamic spacing:

- New constraints:
  - `ZONE_GAP_MIN_UNITS = 2.8`
  - `ZONE_GAP_TARGET_UNITS = 3.6`
  - `ZONE_GAP_MAX_UNITS = 5.0`
- Compute gap from actual core/peripheral extents; clamp to bounds.
- Lower current defaults as baseline:
  - `PERIPHERAL_DOCK_GAP_Y: 6.2 -> 3.8`
  - `PERIPHERAL_GRID_GAP_Y: 7.8 -> 5.2`

### 6.5 Peripheral grid readability and tether hygiene

Improve dock readability without inflating total height:

- Increase minimum cell width slightly:
  - `PERIPHERAL_GRID_MIN_CELL_WIDTH: 16.0 -> 19.5`
- Keep row wrap deterministic; cap row density by measured label width.
- De-emphasize tethers in dock region:
  - lower tether alpha in peripheral zone
  - keep tether rendering behind labels (existing edge canvas path can preserve order)

### 6.6 Deterministic bridge-node handling

Introduce explicit bridge classification before zone assignment:

- If node has direct non-tether edge to a core node and degree >= 1, promote to core.
- Else if node links both zones, place into a narrow bridge lane anchored near separator.
- Else keep peripheral.

This should absorb `apply_tax` into a predictable placement rule.

### 6.7 Stronger separator affordance

Upgrade separator to a readable but still subtle guide:

- Increase line alpha and remove dash pattern.
- Add a small filled label chip (`supporting nodes`) with contrast background.

Suggested style:

- line: `rgba(159,178,200,0.34)`, width `1.25`
- chip fill: `rgba(16,24,38,0.92)`
- chip border: `rgba(159,178,200,0.46)`

## 7. V8 Implementation Plan

Scope: `src/remora/web/static/index.html`, `tests/acceptance/test_web_graph_ui.py`, `tests/unit/test_views.py`.

### Step 1: CSS width/layout rebalance

- Update `#sidebar` width clamp.
- Confirm graph container gains corresponding width.

### Step 2: Fit safe-area support

- Add helper to derive dynamic safe insets from overlay DOMRects.
- Integrate with `computeFitBBox()` so fit includes safe margins.

### Step 3: Core aspect normalization

- Add `normalizeCoreAspect(positions, zoneByNode, nodeById)`.
- Execute before occupancy normalization and box computation.

### Step 4: Vertical rhythm retune

- Introduce zone-gap constants and bounded gap computation.
- Reduce `PERIPHERAL_DOCK_GAP_Y` and `PERIPHERAL_GRID_GAP_Y` defaults.

### Step 5: Peripheral grid + tether cleanup

- Increase peripheral min cell width.
- Adjust tether alpha/priority when both endpoints are peripheral.

### Step 6: Bridge node rule

- Add bridge classification pass before `zoneByNode` finalization.
- Ensure `apply_tax`-like nodes follow deterministic rule.

### Step 7: Separator visual pass

- Replace dashed low-alpha separator with solid medium-alpha line + chip label.

### Step 8: Tests and screenshot verification

- Extend acceptance assertions (see section 8).
- Capture new screenshot and compare against v8 goals.

## 8. V8 Verification Plan

### Automated checks

1. **Overlay occlusion check:** no core label hitbox intersects filter-bar viewport rect.
2. **Core placement check:** core centroid X is within center band (30%-62% graph width), Y within top-middle band (16%-42% graph height).
3. **Zone gap check:** vertical gap between core bottom and peripheral top is within bounded range.
4. **Peripheral overlap check:** no peripheral label box overlaps another peripheral label box.
5. **Sidebar ratio check:** sidebar width <= 31.5% at 1280px viewport.
6. **Bridge rule check:** bridge candidate nodes resolve to core or bridge lane deterministically.

### Visual checks

1. First load screenshot: core is unobstructed and visually central.
2. First load screenshot: no major empty middle void.
3. First load screenshot: `supporting nodes` separator is obvious without zooming.
4. First load screenshot: peripheral rows are readable with reduced tether noise.
5. Edge + node interactions still behave as in v7 (no regression).

## 9. Definition of Done

v8 is complete when:

1. Core architecture is immediately readable and not occluded by overlays.
2. Graph composition reads as intentional: core hero zone, clear separator, peripheral support zone.
3. Vertical spacing between zones feels compact and balanced, without a large empty center.
4. Peripheral labels are readable in the default screenshot with minimal visual collisions.
5. Ambiguous bridge nodes no longer float in undefined space.
6. Sidebar no longer crowds the graph at 1280px desktop.
7. Existing v7 interaction improvements (edge labels/events, hover behavior, smooth updates) remain intact.
8. Acceptance metrics pass and the new screenshot clearly improves startup comprehension.
