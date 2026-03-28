# Web UI Camera-Fit Regression (v0.7.2)

## Summary

The web graph appears blank after the `v0.7.2` UI update, even though runtime APIs are healthy and node/edge data exists.

Root cause is a coordinate-space mismatch introduced in the new camera fitting logic.

## Scope

- Repo: `remora-v2`
- Commit: `dc03de71897573226129770b53b39981c31a8b8e`
- Commit message: `release: v0.7.2 improve web graph legibility and framing`
- Touched web file: `src/remora/web/static/index.html`

## User-Visible Symptoms

- Sidebar, events, and timeline render.
- Graph region appears empty/blank.
- API confirms graph data is present (`/api/nodes`, `/api/edges`).

## What Changed

`v0.7.2` replaced the previous camera reset flow with custom fit logic:

- Added `fitCameraToGraph()` and `computeVisualBounds()`.
- Replaced `renderer.getCamera().animatedReset(...)` with `fitCameraToGraph(...)` on load and zoom reset.

## Root Cause

`fitCameraToGraph()` computes center/bounds in graph coordinates and then calls `camera.setState({ x, y, ratio })` directly.

With Sigma auto-rescaling enabled, camera state is in framed/normalized space, not raw graph space. Feeding graph-space values into `setState` shifts the viewport far from the node cluster, so nodes are off-screen.

## Evidence

Live inspection against the failing UI showed:

- `graph.order` was non-zero.
- `/api/nodes` and `/api/edges` returned expected counts.
- No page JS exception.
- Camera state had out-of-range values for framed space (example: `x ~ 18`).
- Sample node viewport projections were far off-screen (example: `x ~ -10k`).

This confirms render data exists but camera framing is wrong.

## Recommended Fix

### Option A (Safe, Immediate)

Restore prior behavior:

- Use `camera.animatedReset(...)` for initial load and zoom reset.
- Remove or gate `fitCameraToGraph()` until coordinate conversion is corrected.

Pros:

- Fastest path to restore visible graph.
- Low risk.

Cons:

- Loses custom tighter framing behavior from v0.7.2.

### Option B (Keep New Fit, Correctly)

Keep `fitCameraToGraph()` but convert graph-space center into framed camera coordinates before `setState`, or derive fit using Sigma utilities in framed space.

Minimum requirements:

1. Do not pass raw graph center directly into camera state.
2. Verify zoom ratio computation is based on the same coordinate space as camera state.
3. Keep reset fallback to a known-good default if fit math yields invalid values.

Pros:

- Preserves intended framing improvements.

Cons:

- Slightly higher implementation and validation risk.

## Verification Plan

Run after applying fix:

1. Start runtime and open `/`.
2. Confirm node labels are visible without manual pan.
3. Confirm zoom reset recenters visible graph.
4. Capture Playwright screenshot and verify graph region is populated.
5. Validate both default and constrained demo configs.
6. Validate no regression in node click/select and timeline updates.

## Recommended Rollout

1. Apply Option A first if rapid stability is needed.
2. Implement Option B in a follow-up change with explicit UI checks.
3. Add a regression check that fails if nodes exist in API but no visible graph nodes are in viewport after initial load.

## Risk If Unfixed

- Demo credibility impact: appears broken despite healthy backend.
- Misleading diagnostics: API checks pass while UI appears empty.
- Increased support/debug churn around "blank graph" reports.
