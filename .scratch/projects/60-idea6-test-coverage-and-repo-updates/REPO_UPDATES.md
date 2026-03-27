# REPO_UPDATES — `remora-v2` Library Changes for Idea #6 Demo

## Table of Contents
1. Purpose
Description: Define which `remora-v2` changes are needed specifically to support a credible Idea #6 demo.

2. Current State Summary
Description: Snapshot what already works and where reliability still has gaps.

3. Required Changes (P0)
Description: Must-implement runtime/library changes to make semantic edge behavior reliable under real incremental workflows.

4. Recommended Changes (P1)
Description: High-value improvements that enhance observability and demo UX but are not strict blockers.

5. Optional Enhancements (P2)
Description: Nice-to-have capabilities for scale, polish, and future demos.

6. Implementation Sequence
Description: Ordered execution plan to reduce risk and keep behavior verifiable.

7. Validation and Acceptance
Description: Exact checks that confirm the library updates are complete and stable.

## 1) Purpose

Idea #6 promises:
1. clone unknown repo,
2. immediately boot a meaningful knowledge graph,
3. extract trustworthy semantic hotspots.

For that promise to hold under technical scrutiny, `remora-v2` must guarantee not only startup correctness but also ongoing semantic edge correctness as files change incrementally.

This document describes what should be implemented in `remora-v2` to satisfy that bar.

## 2) Current State Summary

### What Already Works
1. Startup full scan happens before web server exposure.
2. Reconcile cycle uses a two-pass per-batch approach (`upsert` then relationship refresh on changed files).
3. Typed semantic edge cleanup (`delete_outgoing_edges_by_type`) prevents stale duplicates for refreshed source files.
4. Existing tests cover several core scenarios (order independence within one batch, stale edge cleanup on source rereconcile).

### Remaining Reliability Gap
The major remaining behavioral gap for this demo is **ongoing edge detection/backfill when only target files change**.

Example failure mode:
1. `a.py` references `B` from `b.py` (but `b.py` not yet present or lacks `B`).
2. Later `b.py` adds `B`.
3. Current refresh strategy updates changed files only.
4. `a.py` is not re-refreshed, so `a.py -> b.py::B` semantic edges may stay missing.

Impact:
- hotspot outputs can under-report true dependency structure,
- technical audience trust can drop quickly when probing incremental edits.

## 3) Required Changes (P0)

### P0-1: Ongoing Semantic Edge Backfill on Target Changes

#### Requirement
When symbols become newly resolvable due to changes in target files, importer files must be reprocessed (or otherwise backfilled) without requiring importer edits.

#### Recommended Implementation Pattern
Implement one of these strategies (A preferred for scale):

A) Dependency-aware targeted refresh (preferred)
1. During `_refresh_relationships(file_path)`, persist unresolved relationship intents by source file:
- unresolved import target names
- unresolved inheritance base names
2. Maintain an index:
- `target_symbol_or_module -> set[source_file_paths]`
3. When a file changes, after its own refresh, identify newly available symbols and refresh affected source files.

B) Conservative Python-wide refresh fallback (acceptable first increment)
1. On any changed Python file, refresh relationships for all discovered Python files in the project.
2. Keep behind config/flag if needed to manage runtime cost.

#### Minimal Data-Model Addition (if using A)
Introduce a lightweight store for unresolved intents, e.g. table:
- `pending_relationships(source_file, edge_type, target_name, target_module)`

Then derive reverse lookup for impacted source files.

#### Success Condition
Target-only changes (adding/changing target symbols) produce correct semantic edges without touching importer files.

### P0-2: Trigger Backfill from Watch and Content-Changed Paths

#### Requirement
Backfill logic must run consistently for:
1. `reconcile_cycle()`
2. `_handle_watch_changes(...)`
3. content-changed event handling paths that call reconcile.

#### Why
A fix only in startup/full-scan path is insufficient for real demo interaction.

### P0-3: Add Regression Tests for Ongoing Edge Detection

Add the P0 tests from `TEST_COVERAGE_UPDATES.md` and make them mandatory gates for merge.

### P0-4: Keep Existing Structural Edge Semantics Intact

Guarantee that any ongoing-backfill implementation:
- does not remove/duplicate `contains` edges,
- does not create duplicate semantic edges,
- does not regress reconcile latency catastrophically on small-to-medium repos.

## 4) Recommended Changes (P1)

### P1-1: Expose Graph Stats/Hotspots API
Add compact endpoints for demo narration and reduced shell complexity:
1. `GET /api/graph/stats`
- node counts by `node_type`
- edge counts by `edge_type`

2. `GET /api/graph/hotspots`
Query options:
- `edge_types=imports,inherits`
- `group_by=file|node`
- `limit=20`

Benefit:
- stable, presenter-friendly output without large jq pipelines.

### P1-2: Health/Startup Observability Fields
Enhance `/api/health` with fields such as:
- `startup_phase`
- `last_scan_duration_ms`
- `last_scan_nodes`
- `semantic_edge_counts` (optional)

Benefit:
- objective demo pacing and easier troubleshooting.

### P1-3: Optional Relative Path Surface in APIs
Include project-relative path in node payloads (alongside current path) for cleaner stage output:
- e.g. `file_path_rel`.

## 5) Optional Enhancements (P2)

### P2-1: Relationship Provenance Metadata
Store provenance for semantic edges:
- source file hash/generation
- extraction mode (`startup`, `watch`, `backfill`)

Benefit:
- easier debugging and explainability.

### P2-2: Debounced/Coalesced Backfill Scheduler
If using dependency-aware backfill, add batching/debounce to avoid thrash during rapid file saves.

### P2-3: Bounded Backfill Policies
Add runtime config knobs:
- max dependent files refreshed per cycle
- backfill cooldown ms
- fallback strategy when cap exceeded

## 6) Implementation Sequence

### Phase 1 — Test-first (required)
1. Add failing P0 coverage tests.
2. Confirm failures reproduce target-only backfill gap.

### Phase 2 — Core runtime update
1. Implement ongoing-backfill logic (A preferred, B acceptable first).
2. Ensure parity across reconcile and watch paths.
3. Keep edge deletion + add semantics idempotent.

### Phase 3 — Hardening
1. Run targeted unit/integration suites.
2. Measure reconciliation overhead on representative fixture repo.
3. Add guardrails if runtime cost is too high.

### Phase 4 — Optional API enhancements
Implement P1 endpoints/health fields only after P0 behavior is stable.

## 7) Validation and Acceptance

### Required validation commands
```bash
cd /home/andrew/Documents/Projects/remora-v2

devenv shell -- uv sync --extra dev

devenv shell -- pytest \
  tests/unit/test_reconciler_edges.py \
  tests/unit/test_reconciler.py \
  tests/unit/test_relationships.py \
  tests/unit/test_graph.py \
  tests/integration/test_lifecycle.py \
  -q --tb=short

devenv shell -- ruff check src/ tests/
```

### Acceptance Criteria
1. Target-only symbol additions update importer semantic edges automatically.
2. Watch-driven and cycle-driven paths produce equivalent semantic outcomes.
3. No duplicate semantic edges across repeated cycles.
4. Existing behavior remains stable (contains edges, status transitions, core API health).
5. Demo flow in `remora-test` can rely on semantic hotspots without caveats.

### Non-Goals for this pass
- Major architecture rewrite of relationship extraction.
- Broad multi-language semantic linking expansion beyond current Python-focused logic.
