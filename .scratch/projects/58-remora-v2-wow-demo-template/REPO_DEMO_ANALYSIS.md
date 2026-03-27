# Remora-v2 Repo Demo Analysis — Idea #6 (Click Knowledge Graph Boot)

## Scope
This document evaluates whether the current `remora-v2` codebase can implement the Click-based Idea #6 demo as written, and what changes are required vs. recommended.

## Executive Summary
- Baseline demo viability: **Yes**. The repo already supports clone -> discover -> graph API -> UI flow.
- Required for a credible "knowledge graph hotspot" narrative: **one core runtime fix** for cross-file relationship completeness.
- High-value, low-risk improvements: demo query tightening, optional API aggregation endpoints, and startup-progress visibility.

## What Already Works (No Core Code Changes Needed)
1. CLI and runtime startup path are already in place:
   - `remora start --project-root ... --config ...` in `src/remora/__main__.py`.
2. Startup performs initial full graph materialization automatically:
   - `RemoraLifecycle.start()` runs `reconciler.full_scan()` before service loop (`src/remora/core/services/lifecycle.py`).
3. Web and API surfaces needed by the demo already exist:
   - `/api/health` (`src/remora/web/routes/health.py`)
   - `/api/nodes`, `/api/edges` (`src/remora/web/routes/nodes.py`)
   - `/api/events`, `/sse` (`src/remora/web/routes/events.py`, `src/remora/web/sse.py`)
4. Idea #6 config shape is valid:
   - Nested `runtime:` keys are accepted by config model (`src/remora/core/model/config.py`, `_nest_flat_config`).

## Required Changes

### 1) Relationship Completeness for Cross-File Edges (Required)
If the demo claims "hotspots" based on graph connectivity, cross-file `imports`/`inherits` edges must be complete after initial boot.

Current behavior risk:
- Reconciler resolves relationships during per-file processing using an incrementally built `_name_index` (`src/remora/code/reconciler.py`).
- Files processed earlier cannot resolve references to symbols discovered in later files.
- Result: forward references are often missing until a later file change triggers re-reconcile.

Observed in smoke validation:
- With `a.py` importing/inheriting from `b.py`, initial boot produced only `contains` edges and no `imports`/`inherits` edges.

Why this is demo-critical:
- Idea #6’s hotspot extraction relies on edge topology, not just node counts.
- Missing semantic edges weakens trust for technical audience.

Recommended fix approach:
1. Keep per-file parse for nodes.
2. Add a second relationship resolution pass after reconcile cycle has indexed all discovered nodes.
3. Rebuild `imports`/`inherits` edges from collected raw relationships against final name index.

### 2) Demo Narrative/Runbook Correction for Startup UX (Required)
Idea #6 currently implies the audience will watch the graph "fill in" live after opening the web UI.

Current runtime behavior:
- Full scan completes before web startup in lifecycle.
- In most runs, the first UI load sees an already-materialized graph.

Required action:
- Either adjust narrative to "instant loaded graph" (no code change), or
- Change lifecycle ordering to serve UI earlier and stream startup progress (code change, higher risk).

For near-term delivery, narrative adjustment is the safe path.

### 3) Hotspot Query Tightening (Required for trustworthy demo output)
Current Idea #6 query examples compute out-degree from all edges, which are dominated by `contains` edges.

Required adjustment:
- Exclude structural edges when computing architectural hotspots.
- Use only semantic edges (`imports`, `inherits`, optionally others).

Without this, top hotspots will mostly be directories/root containers.

## Recommended Improvements (Should, Not Must)

### A) Add Aggregated Graph Stats Endpoint
Problem:
- Demo currently downloads full `/api/nodes` and `/api/edges` and computes summaries via `jq`.

Improvement:
- Add endpoint(s) like:
  - `GET /api/graph/stats` (node counts by type, edge counts by type)
  - `GET /api/graph/hotspots?edge_types=imports,inherits&limit=20`

Benefit:
- Faster live commands, less brittle shell pipelines, easier presenter narration.

### B) Startup Progress Signal
Problem:
- No explicit startup-phase progress API.

Improvement:
- Emit lifecycle startup milestones and expose in `/api/health` (e.g., `startup_phase`, `scan_duration_ms`, `last_scan_nodes`).

Benefit:
- Cleaner demo pacing and better operational observability.

### C) Presenter-Friendly Path Formatting
Problem:
- Node `file_path` for code nodes is absolute in current discovery path.

Improvement:
- Return project-relative path in API payloads (or include both absolute/relative fields).

Benefit:
- Better readability on stage and less visual noise in hotspot tables.

### D) Remove/Ignore `bundle_overlays.file` from Idea #6 config
`NodeType` does not include `file` (`src/remora/core/model/types.py`), so this overlay has no effect.

Benefit:
- Avoid confusion during live explanation.

## Suggested Implementation Plan
1. **P0**: Update Idea #6 runbook/query examples (exclude `contains`; revise startup narrative).
2. **P0**: Implement two-pass relationship resolution for complete `imports`/`inherits` after initial scan.
3. **P1**: Add graph aggregation API endpoint(s) for demo-friendly stats/hotspots.
4. **P2**: Add startup progress fields in health payload.

## Acceptance Criteria for Demo Readiness
1. Fresh clone of Click produces non-empty `imports`/`inherits` edge sets on first startup scan.
2. Hotspot command output is stable and semantically meaningful (not dominated by `contains`).
3. Demo completes in target time window with deterministic command outputs.
4. Presenter can explain graph evidence from API responses without caveats.

## Bottom Line
- **Can we run the demo today?** Yes, for structural graph boot and node-level orientation.
- **Do we need changes for the full "knowledge graph hotspot" promise?** Yes: relationship completeness should be fixed before presenting to a technical audience.
