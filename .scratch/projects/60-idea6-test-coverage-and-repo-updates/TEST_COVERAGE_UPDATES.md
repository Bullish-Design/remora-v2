# TEST_COVERAGE_UPDATES — Idea #6 Reliability Coverage Plan

## Table of Contents
1. Objective and Scope
Description: Define what this test update plan must prove for the Idea #6 demo.

2. Current Coverage Baseline
Description: Summarize what is already covered in `remora-v2` tests and what those tests do not currently assert.

3. Coverage Gaps (Prioritized)
Description: Enumerate underspecified scenarios that can still break demo trust.

4. Required Test Additions (P0)
Description: Concrete tests to add now, with target files, setup, execution path, and assertions.

5. Recommended Test Additions (P1)
Description: High-value tests that improve confidence but are not strict blockers.

6. Contract and API Coverage Updates
Description: API-level assertions needed to validate startup and semantic edge availability from external interfaces.

7. Test Data Design Guidance
Description: Stable fixture patterns that avoid flaky outcomes and accidental false positives.

8. Validation Commands and CI Gate
Description: Exact commands to run locally and in CI for this coverage expansion.

9. Definition of Done
Description: Objective completion criteria for accepting this test coverage update work.

## 1) Objective and Scope

### Objective
Strengthen `remora-v2` test coverage so the Idea #6 claim is defensible:
- semantic cross-file relationships (`imports`, `inherits`) appear quickly and reliably,
- behavior is consistent across startup scan, reconcile cycles, and watch-triggered updates,
- API-visible graph state reflects that reliability.

### In Scope
- Unit tests in:
  - `tests/unit/test_reconciler_edges.py`
  - `tests/unit/test_reconciler.py`
  - `tests/unit/test_relationships.py`
  - `tests/unit/test_graph.py`
- Integration/API tests in:
  - `tests/integration/test_lifecycle.py`
  - optionally `tests/acceptance/*` if API-level semantic checks are already organized there.

### Out of Scope
- New UI behavior tests.
- Non-graph LLM behavior expansion.
- Full benchmark/performance work (timing can be measured separately).

## 2) Current Coverage Baseline

### Existing Strengths
1. Order-independence in same cycle is tested:
- `tests/unit/test_reconciler_edges.py::test_reconcile_import_resolution_is_order_independent`

2. Stale semantic edge cleanup on re-reconcile is tested:
- `tests/unit/test_reconciler_edges.py::test_reconcile_clears_stale_edges_on_rereconcile`

3. NodeStore typed edge deletion behavior is tested:
- `tests/unit/test_graph.py::test_nodestore_delete_outgoing_edges_by_type_preserves_incoming`

4. API route behavior for relationships endpoint is tested:
- `tests/unit/test_web_server.py` relationship route assertions (`contains` filtered, type query supported)

### Baseline Weakness
Coverage is still biased toward single-cycle and happy-path scenarios. It does not fully prove reliability for incremental, real-time repository evolution (the exact scenario technical audiences probe during demos).

## 3) Coverage Gaps (Prioritized)

### P0 Gap A — Target-only change backfill is untested
Scenario:
- `a.py` imports/inherits from symbol in `b.py`.
- `a.py` already exists; later only `b.py` is introduced or changed.

Risk:
- semantic edges can remain missing until `a.py` changes again.

Current blind spot:
- No test explicitly covers this target-only update path.

### P0 Gap B — Watch-triggered batch path lacks semantic-edge assertions
Scenario:
- updates arrive via watcher (`_handle_watch_changes`) not manual reconcile cycle invocation.

Risk:
- watch path can diverge from reconcile-cycle behavior.

Current blind spot:
- tests check watch survivability/error handling, but not semantic edge correctness after watch batches.

### P0 Gap C — Startup API contract does not assert semantic edges
Scenario:
- lifecycle start finishes, `/api/health` returns `ok`, but semantic edges are absent.

Risk:
- demo appears healthy while core claim is false.

Current blind spot:
- integration startup test validates health and node presence, not semantic edge presence.

### P1 Gap D — Import source-node semantics are underspecified
Scenario:
- import edges currently originate from one chosen file node (based on file node ordering).

Risk:
- hotspots become unstable or conceptually misleading if source-node policy changes silently.

Current blind spot:
- tests assert edge existence but not explicit source-node policy.

### P1 Gap E — Extractor edge cases are under-covered
Missing cases:
- alias imports (`import x as y`, `from m import n as k`)
- relative imports (`from .m import X`)
- multiline import forms
- explicit unsupported-form behavior

## 4) Required Test Additions (P0)

### P0-1: Target-only backfill behavior
Target file:
- `tests/unit/test_reconciler_edges.py`

Add test:
- `test_reconcile_backfills_imports_when_target_file_added_later`

Setup:
1. Create `a.py` with `from b import B` and `class A(B): pass`.
2. Run `reconcile_cycle()` with no `b.py` yet.
3. Assert no resolved `imports`/`inherits` edge to `B`.
4. Add `b.py` with `class B: pass`.
5. Run `reconcile_cycle()` again without editing `a.py`.

Assertions:
- `a.py::A -> b.py::B` exists for `imports` and `inherits`.
- no duplicate semantic edges.

Purpose:
- proves ongoing edge detection/backfill when only target changes.

### P0-2: Target rename/removal backfill behavior
Target file:
- `tests/unit/test_reconciler_edges.py`

Add test:
- `test_reconcile_removes_semantic_edges_when_target_symbol_removed`

Setup:
1. Create `a.py` importing/inheriting from `B`.
2. Create `b.py` with `class B`.
3. Reconcile and assert semantic edges exist.
4. Change `b.py` to remove/rename `B`.
5. Reconcile again.

Assertions:
- stale semantic edges to removed `B` are gone.
- structural `contains` edges remain intact.

Purpose:
- ensures semantic topology stays correct as targets evolve.

### P0-3: Watch batch semantic-edge parity test
Target file:
- `tests/unit/test_reconciler.py`

Add test:
- `test_handle_watch_changes_refreshes_semantic_edges_order_independently`

Setup:
1. Prepare `a.py` and `b.py` such that importer sorts earlier.
2. Invoke `_handle_watch_changes({a, b})` directly (or through watcher harness).

Assertions:
- both `imports` and `inherits` edges resolved.
- behavior matches `reconcile_cycle()` outcome for same files.

Purpose:
- validates watch-path parity with manual reconcile flow.

### P0-4: Startup API semantic-edge contract test
Target file:
- `tests/integration/test_lifecycle.py`

Add test:
- `test_lifecycle_startup_exposes_semantic_edges_via_api`

Setup:
1. Create forward-reference fixture (`a.py` -> `b.py`).
2. Start lifecycle with web enabled.
3. Call `/api/edges` after `/api/health` is `ok`.

Assertions:
- response includes at least one `imports` edge for fixture.
- includes `inherits` where fixture defines inheritance.

Purpose:
- ensures demo-visible API truth matches runtime claim.

### P0-5: No-duplicate semantic edges across repeated cycles
Target file:
- `tests/unit/test_reconciler_edges.py`

Add test:
- `test_reconcile_does_not_duplicate_semantic_edges_across_repeated_cycles`

Setup:
1. Create fixed two-file import/inheritance fixture.
2. Run `reconcile_cycle()` multiple times with no content changes.

Assertions:
- semantic edge count remains stable and exact.
- no duplicates for same `(from_id,to_id,edge_type)`.

Purpose:
- protects against hidden accumulation regressions.

## 5) Recommended Test Additions (P1)

### P1-1: Source-node policy test for imports
Target:
- `tests/unit/test_reconciler_edges.py`

Add explicit assertion for expected `from_id` type (file node vs class/function node). Current runtime should be intentionally documented and pinned by test.

### P1-2: Extractor edge-form matrix
Target:
- `tests/unit/test_relationships.py`

Add matrix cases:
1. `import pkg.mod as m`
2. `from pkg.mod import Name as Alias`
3. `from .local import Thing`
4. parenthesized multiline imports
5. unsupported form expected behavior (explicitly empty/ignored)

### P1-3: Relationship endpoint richer coverage
Target:
- `tests/unit/test_web_server.py`

Add endpoint checks for:
- empty relationships list when no semantic edges
- invalid `type` values (behavior contract: empty vs error)
- deterministic ordering if ordering is intended

### P1-4: Cold-start then incremental-update API contract
Target:
- new or existing integration API test module

Flow:
1. startup
2. verify semantic edges
3. mutate target file only
4. verify API edges updated without source-file edit

## 6) Contract and API Coverage Updates

### API contract additions for Idea #6 credibility
1. `/api/health` alone is insufficient; test suite must pair it with `/api/edges` semantic checks.
2. `/api/edges` checks must filter by `edge_type in {imports, inherits}`.
3. Tests should verify semantic edge presence under both:
- initial startup scan
- subsequent incremental updates.

### Suggested helper for tests
Create a small local helper in integration tests:
- `wait_for_semantic_edges(base_url, timeout_s=5)`

This reduces flaky polling duplication and centralizes diagnostics.

## 7) Test Data Design Guidance

1. Always use deterministic filenames to control sort order:
- importer: `a.py`
- target: `b.py`

2. Keep fixtures minimal:
- one importer class/function, one target class.

3. Prefer explicit node-id assertions when possible:
- assert exact `from_id` and `to_id` values.

4. Avoid timing-based sleeps when possible:
- use direct reconcile invocation or bounded polling helpers.

5. Separate semantic and structural assertions:
- semantic: `imports`, `inherits`
- structural: `contains`

## 8) Validation Commands and CI Gate

From repo root (`/home/andrew/Documents/Projects/remora-v2`):

```bash
devenv shell -- uv sync --extra dev

devenv shell -- pytest \
  tests/unit/test_reconciler_edges.py \
  tests/unit/test_reconciler.py \
  tests/unit/test_relationships.py \
  tests/unit/test_graph.py \
  tests/integration/test_lifecycle.py \
  -q --tb=short
```

Optional broader gate:
```bash
devenv shell -- pytest tests/ -q --tb=short
```

Lint gate for touched files:
```bash
devenv shell -- ruff check \
  tests/unit/test_reconciler_edges.py \
  tests/unit/test_reconciler.py \
  tests/unit/test_relationships.py \
  tests/integration/test_lifecycle.py
```

## 9) Definition of Done

Coverage update is complete when all are true:
1. All P0 tests are implemented and passing.
2. New tests fail against intentionally broken behavior (sanity check), then pass with current/fixed behavior.
3. Startup + incremental semantic edge behavior is API-validated, not only storage-internal.
4. No flaky retries/sleeps remain without justification.
5. CI command set above passes on clean checkout.
