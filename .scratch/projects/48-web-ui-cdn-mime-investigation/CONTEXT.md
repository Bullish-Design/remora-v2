# CONTEXT

Project 48 now includes seven completed phases.

## Through phase 6
- Multiple layout tuning passes were applied for sidebar usage and x fanout.
- User screenshots still showed a narrow center-spine shape.

## Phase 7 completed
- Reworked file banding so y-bands are no longer keyed by full file paths (which caused excessive y stacking).
  - New band key extraction uses top-level segment under `src/` when available.
- Added per-depth level spread (`LEVEL_SPREAD`) to widen nodes that share depth.
- Kept and combined existing x fanout terms:
  - type track offset
  - sibling spread
  - level spread
  - depth fanout
  - depth zigzag
  - depth wave
  - deterministic hash offset
- File label nodes now represent coarse band keys.

## Current validation state
- Ran: `devenv shell -- pytest tests/unit/test_views.py -q`
- Result: `6 passed`

## Phase 8 completed
- Added box-hitbox click alignment:
  - `nodeLabelHitboxes` map populated in `drawNodeBoxLabel`
  - `clickStage` now hit-tests label boxes and selects matching node
  - `clickNode` ignores `__label__` nodes
- Fixed stale SSE discovery path that still referenced removed layout helpers (`getFileCluster`/`deterministicPosition`).
  - `node_discovered` now calls `loadGraph()` to stay consistent with current layout pipeline.
- Validation:
  - Ran `devenv shell -- pytest tests/unit/test_views.py -q`
  - Result `6 passed`
