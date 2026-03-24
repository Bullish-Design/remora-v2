# CONTEXT

Project 48 now includes three completed phases.

## Phase 1 completed
- Root cause for console MIME/script errors identified and fixed.
- Sigma script path updated to valid `/dist/sigma.min.js`.
- Broken ForceAtlas2 CDN include removed.
- Regression test added to prevent broken CDN paths reappearing.

## Phase 2 completed
- New plan file created: `PLAN_02_NODE_BOX_LAYOUT.md`.
- Implemented box-style node labels using Sigma `defaultDrawNodeLabel` custom drawing.
- Implemented deterministic layout organization with file/depth/sibling structure.
- Removed stale ForceAtlas2 body attribute/runtime hook.

## Phase 3 completed
- New plan file created: `PLAN_03_SIDEBAR_TALL_LAYOUT.md`.
- Layout updated for narrow/tall sidebar usage:
  - file bands are stacked vertically (`FILE_BAND_SPACING`)
  - depth still flows downward (`DEPTH_ROW_SPACING`)
  - x is constrained using `TYPE_TRACK_OFFSETS` + small `SIBLING_SPREAD`
- Added unfiled section label for nodes without `file_path`.
- Updated tests to assert vertical-band markers.

## Current validation state
- Ran: `devenv shell -- pytest tests/unit/test_views.py -q`
- Result: `6 passed`
