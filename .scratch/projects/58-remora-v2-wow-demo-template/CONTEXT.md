# Context — 58-remora-v2-wow-demo-template

User request (latest): study `/home/andrew/Documents/Projects/remora-test` and rewrite Idea #6 implementation guidance for a two-repo structure, split into `remora-v2` changes vs `remora-test` changes.

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
- Added detailed intern implementation guide:
  - `IDEA_6_IMPLEMENTATION_GUIDE.md`
  - includes phase-based implementation steps, exact commands, script requirements, reliability validation, acceptance criteria, and troubleshooting.
- Re-studied `remora-test` repo structure and conventions:
  - existing `scripts/`, `tests/integration/test_demo_contract.py`, `tests/unit/test_scripts_contracts.py`, `README.md`, `pyproject.toml`, `remora.yaml`.
- Rewrote `IDEA_6_IMPLEMENTATION_GUIDE.md` as a two-repo execution plan:
  - explicit workstream A (`remora-v2` runtime checks/conditional fixes)
  - explicit workstream B (`remora-test` demo scripts/docs/tests)
  - dependency pinning strategy between repos
  - repo-specific acceptance gates and handoff template.
- Updated both runbooks to use setup scripts instead of long manual heredoc blocks.
- Validated scripts:
  - `devenv shell -- python -m py_compile ...` passed
  - both scripts executed successfully with `--force` and created `/tmp/remora-demo-*` fixtures.
  - both scripts also executed directly as binaries via `devenv shell -- ./.../setup_*.py --force`.

Current recommendation:
- Use the rewritten two-repo `IDEA_6_IMPLEMENTATION_GUIDE.md` as the implementation source of truth.
- Implement demo packaging only in `remora-test`; keep `remora-v2` work limited to runtime correctness/verification unless a gap is found.
- Pin `remora-test` to a known-good `remora-v2` revision before rehearsal.

If resumed later:
1. Implement Workstream A and Workstream B items from the rewritten guide.
2. Run repo-specific validation commands and capture outputs.
3. Rehearse full clone-to-hotspot flow and lock cue-sheet numbers.
