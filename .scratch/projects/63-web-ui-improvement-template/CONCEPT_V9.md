# Concept: Graph View Overhaul (v9)

## Table of Contents

1. [Executive Summary](#1-executive-summary) - What failed in the latest attempt and what v9 must correct.
2. [Evidence the Latest Attempt Was a Visual No-Op](#2-evidence-the-latest-attempt-was-a-visual-no-op) - Objective comparison of v8 and latest screenshots.
3. [Observed Issues vs Desired Web UI Goal](#3-observed-issues-vs-desired-web-ui-goal) - Concrete defects in `ui-playwright-20260328-161343-347.png`.
4. [Why v8 Changes Did Not Produce the Intended Result](#4-why-v8-changes-did-not-produce-the-intended-result) - Root-cause analysis in current `index.html` behavior.
5. [V9 Goals](#5-v9-goals) - Non-negotiable outcomes for startup readability.
6. [V9 Corrective Strategy](#6-v9-corrective-strategy) - Layout + camera + rendering changes to achieve the goals.
7. [V9 Implementation Plan](#7-v9-implementation-plan) - Ordered steps and file scope.
8. [V9 Verification Plan](#8-v9-verification-plan) - Automated metrics and visual checks to prevent another no-op.
9. [Definition of Done](#9-definition-of-done) - Exit criteria for v9.

## 1. Executive Summary

The latest screenshot (`ui-playwright-20260328-161343-347.png`) does not move the graph UI toward the desired outcome of fast architectural comprehension. The startup composition is still dominated by the same problems: clipped core content at top-left, a large dead middle region, weak zone separation, and dense peripheral noise.

v9 should prioritize **composition correctness and measurable visual change**. The key direction is:

1. Replace the current core-only fit behavior with a composition-aware fit that respects label extents and overlay safe areas.
2. Make core placement deterministic in a target hero band (upper-middle, not top-left).
3. Enforce bounded vertical rhythm between core and peripheral content.
4. Add stronger acceptance checks that fail when screenshots remain effectively unchanged.

## 2. Evidence the Latest Attempt Was a Visual No-Op

Compared screenshots:

- Previous: `ui-playwright-20260328-140333-244.png`
- Latest: `ui-playwright-20260328-161343-347.png`

Objective diff check (`compare -metric AE`) reports:

- `628 (0.000535617)` different pixels across a `1280 x 916` image.

Interpretation:

- Only `0.0536%` of pixels changed.
- Differences are limited to dynamic timeline text (timestamps), not graph composition.
- Practically, the graph rendering is unchanged from the prior capture.

## 3. Observed Issues vs Desired Web UI Goal

Desired goal baseline (from project brief):

1. Faster graph understanding after startup.
2. Clear separation of graph state, event stream, and action panel.
3. Reduced cognitive load when switching between nodes and proposals.

### 3.1 Core is clipped and partially off-canvas

- The left-most core node label is cut off by the left viewport boundary.
- Core content sits under the top-left control region.

Why this violates the goal:

- Users cannot parse the primary flow in one glance.
- Immediate trust in the layout is reduced because important text is truncated.

### 3.2 Core is anchored in top-left instead of the hero band

- Core nodes are concentrated in the upper-left corner rather than upper-middle.
- The main chain does not dominate the center attention band.

Why this violates the goal:

- The layout reads like a debug scatter, not an intentional architecture view.

### 3.3 Large dead middle canvas remains

- There is still a large empty region between core and peripheral zones.
- Long edges cross the void and increase eye travel.

Why this violates the goal:

- Cognitive load increases because users must scan larger distances to follow relationships.

### 3.4 Peripheral zone remains visually noisy

- Peripheral rows are still dense with many thin crossing tethers.
- Supporting labels compete for attention with relationship lines.

Why this violates the goal:

- Supporting context competes with core understanding instead of receding behind it.

### 3.5 Zone separator cue is still too weak

- The separator/chip does not register strongly at first glance.

Why this violates the goal:

- The intended core-vs-supporting mental model is not reinforced strongly enough.

### 3.6 Bridge semantics are still unclear in first-load narrative

- Bridge-like functionality is not visually signaled as a deliberate transition element.

Why this violates the goal:

- Users still need extra effort to infer zone boundaries and node role.

## 4. Why v8 Changes Did Not Produce the Intended Result

### 4.1 Fit is driven by core bounds, not full visible label extents

Current fit path prioritizes `coreZoneBounds` and does not directly account for rendered label hitbox width/height in the core-first branch. This allows long labels at the boundary to clip even if node centers are in-range.

### 4.2 Safe-area insets are not strong enough for actual overlay footprint

Insets exist (`FIT_SAFE_LEFT_PX`, `FIT_SAFE_TOP_PX`), but they are not yielding a visible shift away from top-left controls in the resulting composition. Effective safe margins must be derived from actual overlay footprint plus label extents.

### 4.3 Composition is not solved as a constrained target placement problem

Current logic mainly scales and pads bounds. It does not enforce target centroid bands for the core (`x`, `y`) with hard constraints, so the result can still drift into top-left bias.

### 4.4 Test thresholds allow visually poor but technically passing layouts

Acceptance metrics catch basic validity but still permit this poor startup composition. That created a false pass where v8 looked successful by metrics while remaining visually unchanged.

### 4.5 No visual change gate exists

There is no regression check that compares the graph-pane image against prior output while masking dynamic panels (events/timeline). This enabled an almost identical screenshot to pass review.

## 5. V9 Goals

1. No core label clipping at startup (left/top/right/bottom).
2. Core centroid placed in a strict hero band (upper-middle).
3. Zone gap bounded to avoid the large dead middle area.
4. Peripheral labels readable with lower tether competition.
5. Separator immediately visible as a compositional divider.
6. Bridge nodes assigned to deterministic, visually explicit roles.
7. Acceptance suite fails if composition regresses or remains effectively unchanged.

## 6. V9 Corrective Strategy

### 6.1 Replace core-only fit with composition-aware fit

Build fit bounds from three envelopes:

1. `coreEnvelope` including core label extents (not just node centers).
2. `peripheralEnvelope` clamped by max contribution so supporting nodes stay visible but do not dominate scale.
3. `safeInsetsEnvelope` derived from live overlay rectangles.

Then solve for a camera box that satisfies:

- Core fully visible.
- Core centroid in target band.
- Peripheral top remains below separator target lane.

### 6.2 Enforce target core centroid bands explicitly

After fit bounds are derived, apply deterministic translation to place core centroid in:

- `x` ratio: `0.40 - 0.56`
- `y` ratio: `0.20 - 0.36`

Do not rely on emergent placement from padding alone.

### 6.3 Make zone gap adaptive with hard upper bound

Use measured zone extents and enforce:

- `zoneGapPx >= 16`
- `zoneGapRatio <= 0.22`

This eliminates the middle void while preserving separation.

### 6.4 Make separator readability first-class

Increase separator salience:

- Stronger line alpha and width.
- Slight glow/contrast bump on the separator chip.
- Render order that guarantees visibility over busy edge regions.

### 6.5 Peripheral de-noise pass

- Reduce peripheral tether alpha and stroke width further.
- Prefer routing/context tethers behind peripheral label chips.
- Keep peripheral node label contrast, but lower edge emphasis in peripheral rows.

### 6.6 Deterministic bridge lane

Introduce an explicit `bridge` layout zone for nodes that connect core and peripheral semantics. Render this lane near the separator with distinct styling so users read transition intent immediately.

### 6.7 Visual no-op guardrail

Add a graph-pane screenshot diff check:

- Mask dynamic sidebar regions (events/timeline timestamps).
- Require meaningful pixel delta in graph region when a layout revision is claimed.
- Fail CI if change is below a configured threshold for the revision.

## 7. V9 Implementation Plan

Scope:

- `src/remora/web/static/index.html`
- `tests/acceptance/test_web_graph_ui.py`
- `tests/unit/test_views.py` (if template/assertion updates are needed)
- `scripts/playwright_screenshot.py` (optional: add graph-pane masking utility)

### Step 1: Instrument composition metrics in runtime

- Expose debug metrics in `window.__remora_layout_metrics`:
  - core label clipping counts
  - centroid ratios
  - zone gap px/ratio
  - separator y position
- Use these metrics in acceptance assertions.

### Step 2: Implement label-aware envelope extraction

- Add helpers to compute bounds from `nodeLabelHitboxes` (fallback to estimated label bounds when unavailable).
- Use these bounds in `computeFitBBox()` for core-first layout path.

### Step 3: Implement constrained fit solver

- Replace padding-only fit with solver that satisfies core visibility + hero band placement + safe insets.
- Keep a fallback path for empty/degenerate graphs.

### Step 4: Add bridge zone and lane placement

- Classify bridge nodes pre-placement.
- Place bridge lane near separator and style distinctly from core/peripheral.

### Step 5: Tighten separator and peripheral visual hierarchy

- Update separator rendering style and z-order.
- Reduce peripheral tether visual weight and ensure label-first readability.

### Step 6: Tighten acceptance thresholds

- Raise strictness on centroid bands, clipping, and gap ratio.
- Add assertion that at least one separator/chip cue is visibly rendered in viewport.

### Step 7: Add screenshot change gate

- Add helper that compares previous and current graph-pane captures with masking.
- Fail when delta is below threshold during layout revision verification.

## 8. V9 Verification Plan

### Automated checks

1. `core_clipped_label_count == 0`
2. `core_centroid_x_ratio` in `[0.40, 0.56]`
3. `core_centroid_y_ratio` in `[0.20, 0.36]`
4. `zone_gap_ratio <= 0.22`
5. `zone_gap_px >= 16`
6. `peripheral_label_overlap_ratio < 0.015`
7. `separator_visible == true`
8. `apply_tax_zone in {core, bridge, peripheral}` and if `bridge`, lane constraints hold
9. Graph-pane screenshot delta vs prior revision exceeds configured minimum when expected

### Visual checks

1. Core nodes are fully readable and unobstructed at startup.
2. Core appears in upper-middle hero band, not top-left.
3. Middle dead space is materially reduced.
4. Separator is obvious without zooming.
5. Peripheral rows remain readable and quieter than core.

### Command checklist

1. `devenv shell -- uv sync --extra dev`
2. `devenv shell -- pytest tests/acceptance/test_web_graph_ui.py -q -rs`
3. `devenv shell -- pytest tests/unit/test_views.py tests/unit/test_web_static_assets.py tests/unit/test_web_server.py tests/unit/test_web_decomposition.py tests/unit/test_sse_resume.py -q -rs`
4. `devenv shell -- python scripts/playwright_screenshot.py`

## 9. Definition of Done

v9 is complete when all of the following are true:

1. The startup screenshot no longer clips core labels and no longer anchors core at top-left.
2. Core/peripheral composition reads immediately as intentional and hierarchical.
3. The middle dead zone is reduced to within bounded metric targets.
4. Separator visibility is obvious at first glance.
5. Automated acceptance checks enforce the above and fail on regression.
6. Screenshot comparison confirms meaningful graph-pane improvement over the previous revision.
