# Sigma-First V4 Implementation Strategy

## Table of Contents

1. Goals
2. Sigma Capabilities to Leverage
3. Architecture Changes (vs current v0.7.3)
4. Camera Strategy (Sigma-Native)
5. Edge Strategy (Arrow + Curve Programs)
6. Layout Strategy (Custom, Sigma-Compatible)
7. Box/Label Declutter Strategy
8. Implementation Steps (ordered)
9. Verification Plan
10. Rollout and Fallback

## 1. Goals

- Keep deterministic layout and always-visible node names.
- Eliminate overlap-driven illegibility in dense graphs.
- Use Sigma’s camera/program APIs instead of ad-hoc camera-coordinate math.
- Preserve filesystem boxes and filter UX.
- Keep implementation in `src/remora/web/static/index.html`.

## 2. Sigma Capabilities to Leverage

Use these built-ins directly:

1. Camera + fit primitives
- `renderer.setCustomBBox(bbox)`
- `renderer.getCamera().animatedReset(...)`
- `stagePadding` setting
- `minCameraRatio` / `maxCameraRatio`

2. Coordinate helpers
- `renderer.graphToViewport(...)`
- `renderer.viewportToFramedGraph(...)`
- `renderer.framedGraphToViewport(...)`

3. Edge programs
- default `arrow` and `line` programs
- `Sigma.rendering.EdgeCurveProgram` available in vendored build

4. Dynamic style hooks
- `nodeReducer`, `edgeReducer`
- render hooks (`beforeRender`)

5. Label controls
- `labelDensity`, `labelGridCellSize`, `labelRenderedSizeThreshold`

Note: Sigma still does not provide the specific deterministic wrapped-lane layout needed here; layout remains custom.

## 3. Architecture Changes (vs current v0.7.3)

1. Replace custom `fitCameraToGraph` math with Sigma-native framing:
- Build graph-space bounds (nodes + label extents + visible boxes).
- Feed bounds to `setCustomBBox`.
- Call `animatedReset`.

2. Keep custom layout, but shift from single strip to deterministic wrapped lanes.

3. Add cross-file edge program routing:
- local edges: `arrow`
- cross-file edges: `curve` (or `arrow` fallback)

4. Add zoom-aware declutter behavior in `beforeRender`:
- suppress tiny/deep box headers when zoomed out.

## 4. Camera Strategy (Sigma-Native)

### 4.1 Core rule
Never assign raw graph-center values directly to camera `x/y`.

### 4.2 Fit flow
1. Compute visible graph-space bounds:
- include every non-hidden node
- include estimated label footprint around node positions
- include visible bounding boxes when filesystem filter is active

2. Call:
```js
renderer.setCustomBBox({ x: [minX, maxX], y: [minY, maxY] });
renderer.getCamera().animatedReset({ duration: 200 });
```

3. Use `stagePadding` in Sigma settings to enforce margins near container/sidebar.

4. Keep hard fallback:
```js
renderer.setCustomBBox(null);
renderer.getCamera().animatedReset({ duration: 200 });
```
if bounds are invalid.

### 4.3 Reset behavior
`zoom-reset` should call the same `applyCustomFit()` function, not bespoke camera math.

### 4.4 Filter interaction
When node/edge/box filters change:
- recompute fit bounds from current visible state
- reapply custom bbox + reset (or only on explicit reset button if preferred)

## 5. Edge Strategy (Arrow + Curve Programs)

### 5.1 Program registration
In renderer settings, register:
- `arrow`
- `line`
- `curve` when available (`Sigma.rendering.EdgeCurveProgram`)

### 5.2 Edge typing
At edge ingestion time, attach attributes:
- `source_file_path`
- `target_file_path`
- `is_cross_file = source_file_path !== target_file_path`

### 5.3 Reducer policy
In `edgeReducer`:
- `inherits`: arrow, stronger purple
- `imports` + cross-file: curve (preferred) with stronger blue
- `imports` + same-file: arrow or line with lower prominence

### 5.4 Fallback
If curve program unavailable, keep `arrow` but increase thickness/opacity and add slight color contrast delta for cross-file edges.

## 6. Layout Strategy (Custom, Sigma-Compatible)

### 6.1 Wrapped deterministic lanes
Keep deterministic file ordering, but pack columns into rows by target row width.

Algorithm:
1. Compute deterministic `sortedFiles`.
2. Compute column width from measured max label width.
3. Deterministic row-packing (first-fit, no randomness).
4. Assign each row a `rowBaseY` with large inter-row gap.
5. Place nodes within each column at `rowBaseY - localOffset`.

### 6.2 Collision guarantees
Run deterministic collision pass:
- if two label boxes overlap in a row, shift the later column right
- if row overlap remains, push next row down

### 6.3 Semantics inside column
Local order remains `(depth, start_line, name)`.

## 7. Box/Label Declutter Strategy

### 7.1 Keep all node labels visible
No change to the “always-on names” policy.

### 7.2 Box headers conditional
In `beforeRender`, draw directory header text only when:
- box pixel width >= threshold
- box pixel height >= threshold
- zoom ratio indicates readable scale

### 7.3 Depth attenuation
Reduce stroke alpha for deep nested boxes when zoomed out; restore when zoomed in.

## 8. Implementation Steps (ordered)

1. Add Sigma-first fit helpers
- `computeFitBBox()` -> returns `{x:[...], y:[...]}`
- `applyCustomFit(duration)` -> `setCustomBBox + animatedReset`

2. Replace current camera flow
- remove direct camera center math
- load path: `applyCustomFit(0 or 200)`
- reset button: `applyCustomFit(200)`

3. Register edge programs
- include curve when available
- preserve arrow fallback

4. Add cross-file edge metadata
- derive source/target file path from node attrs during edge creation

5. Update edge reducer
- route to `curve` for cross-file imports
- increase edge visibility constants

6. Implement wrapped lane layout
- row packer
- row y bands
- deterministic collision pass

7. Update beforeRender declutter
- conditional headers
- zoom-aware alpha attenuation

8. Re-run acceptance and unit web tests
- existing suite + overlap/visibility assertions

## 9. Verification Plan

Required checks:

1. Graph visible on load when nodes exist.
2. No severe overlap in baseline screenshot.
3. Zoom reset keeps graph legible and centered.
4. Cross-file edges are visually distinguishable.
5. Filesystem boxes are readable without dominating dense regions.

Automated tests:
- keep existing acceptance tests
- keep viewport-visibility regression test
- add overlap-ratio assertion in acceptance test using `nodeLabelHitboxes`

Manual screenshot set:
- default load
- after reset
- cross-file emphasis enabled

## 10. Rollout and Fallback

1. Implement behind a local runtime toggle in JS (`LAYOUT_MODE = "wrapped" | "strip"`).
2. Default to wrapped after screenshot validation.
3. Keep strip mode for one patch cycle as emergency fallback.
4. If a regression appears, revert to:
- strip layout
- Sigma custom bbox reset fit only
- arrow-only edges

This preserves stability while enabling iterative visual tuning.
