# Context — 58-remora-v2-wow-demo-template

User request (latest): study Idea #6 doc + remora-v2 implementation and determine required changes/improvements for the Click knowledge-graph demo.

Completed in this pass:
- Created `.scratch/projects/58-remora-v2-wow-demo-template/`.
- Added required project-tracking files.
- Added `DEMO_IDEAS.md` with concept set, rankings, and recommended first demo candidate.
- Added primary runbook: `RUNBOOK_PRIMARY_EVENT_STORM_CONTROL_ROOM.md`.
- Added backup runbook: `RUNBOOK_BACKUP_GRAPH_BOOT_AND_TIME_TRAVEL.md`.
- Added executable setup scripts:
  - `setup_primary_event_storm_demo.py`
  - `setup_backup_graph_boot_demo.py`
- Added detailed Idea #6 brief:
  - `IDEA_6_INSTANT_LOCAL_KNOWLEDGE_GRAPH_BOOT_OVERVIEW.md`
- Revised Idea #6 brief to a Click-specific flow:
  - clone `pallets/click`
  - generate graph immediately
  - extract hotspots via concrete API queries
- Studied remora-v2 implementation paths used by Idea #6:
  - config parsing/flattening, lifecycle startup sequencing, reconciler, relationship extraction, web API routes.
- Ran local smoke validation for Idea #6-style config in `/tmp/remora-demo-analysis-smoke`:
  - `devenv shell -- remora discover ...` succeeded.
  - `devenv shell -- remora start ... --no-web --run-seconds 0.5` succeeded.
  - Confirmed startup graph materialization and surfaced an edge-completeness risk for forward cross-file references (`imports`/`inherits` absent in first scan for that fixture).
- Added analysis document:
  - `REPO_DEMO_ANALYSIS.md`
  - includes: required changes vs recommended improvements, prioritized implementation plan, and acceptance criteria.
- Updated both runbooks to use setup scripts instead of long manual heredoc blocks.
- Validated scripts:
  - `devenv shell -- python -m py_compile ...` passed
  - both scripts executed successfully with `--force` and created `/tmp/remora-demo-*` fixtures.
  - both scripts also executed directly as binaries via `devenv shell -- ./.../setup_*.py --force`.

Current recommendation:
- For Idea #6 specifically, baseline demo is viable now for graph boot/orientation.
- Before presenting hotspot claims to a technical audience, address cross-file relationship completeness (or scope demo claims to structural graph only).
- Update Idea #6 command/query examples to exclude `contains` edges when computing hotspots.

If resumed later:
1. Decide whether to implement the P0 relationship completeness fix in reconciler.
2. Revise Idea #6 doc queries to use semantic edges (`imports`, `inherits`) only.
3. Optionally add `/api/graph/stats` and `/api/graph/hotspots` for cleaner live narration.
