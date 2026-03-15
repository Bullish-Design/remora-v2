# remora-v2 Edge Materialization Change Overview

## Objective

Enable graph links in the remora web UI and APIs by materializing structural relationships into the `edges` table during reconciliation.

Primary target: **containment edges** (`parent -> child`, `edge_type = "contains"`).  
Optional future target: semantic edges (`calls`, `imports`, etc.).

---

## Current gap (confirmed)

1. `NodeStore` supports persisted edges and `add_edge()`, but reconciler never calls it.
   - `src/remora/core/graph.py`
   - `src/remora/code/reconciler.py`
2. Reconciler stores hierarchy in `nodes.parent_id`.
3. Web/API graph links are loaded from `/api/edges`, which reads only `edges`.
   - `src/remora/web/server.py`

Result: nodes render, links remain empty when `edges` is not explicitly populated.

---

## Required code changes

## 1) Graph storage API enhancements

### Files
- `src/remora/core/graph.py`
- (optional) `src/remora/core/types.py` for edge type constants/enum

### Changes
1. Add a batch-sync API for deterministic reconciliation writes, for example:
   - `list_edges_by_type(edge_type: str) -> list[Edge]`
   - `delete_edge(from_id: str, to_id: str, edge_type: str) -> None`
   - `sync_edges(edge_type: str, desired: set[tuple[str, str]]) -> None`
2. Ensure sync is transactional (single commit per reconcile pass) to avoid partial edge states.
3. Keep existing `UNIQUE(from_id, to_id, edge_type)` behavior for idempotency.

### Why
Reconciler needs set-based diffing (`desired` vs `existing`) to safely handle adds/removals/re-parents.

---

## 2) Reconciler edge materialization

### File
- `src/remora/code/reconciler.py`

### Changes
1. Add helper(s) that derive containment edges from current node graph:
   - Build desired set:
     - For each node with `parent_id != None`, add `(parent_id, node_id)`.
     - Exclude self loops and virtual nodes (unless explicitly desired).
2. Invoke edge sync in these places:
   - End of `_materialize_directories(...)` (directory hierarchy changes).
   - End of `_do_reconcile_file(...)` (function/class/method/file changes).
3. On node deletion, existing `delete_node()` already removes connected edges; keep this path.
4. Add integrity guards:
   - Only create edges where both endpoints exist in `nodes`.
   - Normalize IDs to match node IDs (`.` root and relative directory IDs).

### Recommended algorithm

```text
desired_contains = {(node.parent_id, node.node_id) for node in nodes if node.parent_id}
existing_contains = {(e.from_id, e.to_id) for e in list_edges_by_type("contains")}
to_add = desired_contains - existing_contains
to_remove = existing_contains - desired_contains
apply adds/removes in one transaction
```

---

## 3) API behavior and compatibility

### Files
- `src/remora/web/server.py`
- (optional) `src/remora/core/externals.py`

### Changes
1. No breaking API changes required if edges are correctly materialized.
2. Optional hardening:
   - Fallback in `/api/edges`: if `edges` table is empty, synthesize `contains` edges from `parent_id` temporarily.
   - Add optional edge filtering (`?type=contains`) for diagnostics.
3. Externals (`graph_get_edges`) benefit automatically once edges are present.

---

## 4) Test plan updates

### Files
- `tests/unit/test_reconciler.py`
- `tests/unit/test_graph.py`
- `tests/unit/test_web_server.py`
- `tests/integration/test_e2e.py` (or equivalent integration suite)

### Add/adjust tests
1. **Reconciler**
   - After `full_scan()`, assert expected `contains` edges exist for directory and code nodes.
   - After file deletion/re-parenting, assert stale containment edges are removed.
2. **Graph store**
   - Unit test `sync_edges(...)` diff behavior (add, remove, idempotent no-op).
3. **Web server**
   - Assert `/api/edges` returns non-empty containment edges after normal reconcile flow (without manual `add_edge`).
4. **Integration**
   - End-to-end startup should produce `edges > 0` for a non-trivial fixture tree.

---

## 5) Documentation updates

### Files
- `docs/architecture.md`
- `docs/user-guide.md`
- `docs/externals-api.md`

### Changes
1. Clarify that hierarchy is represented by `contains` edges in `edges`.
2. Document edge types currently produced (`contains` now; `calls` optional future).
3. Update API examples to show real `/api/edges` payload with containment entries.

---

## 6) Rollout sequence

1. Implement `NodeStore` edge-sync primitives.
2. Wire reconciler to materialize containment edges.
3. Add/update unit tests.
4. Add integration assertion for non-empty edges.
5. Update docs.
6. Validate in demo workspace:
   - `remora start --project-root . --run-seconds N`
   - `GET /api/edges` should return containment edges
   - UI graph should show visible links

---

## Acceptance criteria

1. Fresh startup on a sample Python project yields non-empty `/api/edges`.
2. Every node with `parent_id` has corresponding `contains` edge.
3. Removing/moving files updates containment edges without stale links.
4. Existing APIs remain backward-compatible.
5. Unit/integration tests cover edge creation, updates, and removals.
