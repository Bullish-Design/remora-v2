# Edge Materialization Analysis — Senior Review of Intern Proposal

## Executive Summary

The intern correctly identified the core gap: the `edges` table is never populated by the reconciler, so the web UI graph has no visible links. However, their proposed solution — a batch `sync_edges()` diff-and-reconcile system with new `list_edges_by_type()` and `delete_edge()` APIs — is significantly over-engineered for the actual problem. The fix is ~15 lines of code in the reconciler, not a new storage API layer.

---

## What the Intern Got Right

1. **The gap is real.** The reconciler stores hierarchy in `nodes.parent_id` but never calls `add_edge()`. The web UI fetches `/api/edges` (which reads the `edges` table), so links never render. This is confirmed:
   - `reconciler.py`: zero calls to `add_edge` or any edge API.
   - `tests/unit/test_reconciler.py`: zero edge assertions.
   - `index.html:381-389`: fetches `/api/edges` and renders them — works correctly IF edges exist.

2. **Containment edges are the right first target.** The parent/child hierarchy is already fully computed by the reconciler; it just needs to be written as edges.

3. **Both endpoints must exist.** Correct — dangling edges would break the UI.

---

## What the Intern Got Wrong

### 1. Over-engineered storage layer

The proposal calls for three new `NodeStore` methods:
- `list_edges_by_type(edge_type) -> list[Edge]`
- `delete_edge(from_id, to_id, edge_type) -> None`
- `sync_edges(edge_type, desired: set[tuple[str, str]]) -> None`

**Why this is wrong:** `NodeStore` already has everything needed:
- `add_edge(from_id, to_id, edge_type)` — idempotent via `INSERT OR IGNORE` + `UNIQUE` constraint.
- `delete_node(node_id)` — already cascades edge deletion (`DELETE FROM edges WHERE from_id = ? OR to_id = ?`).
- `delete_edges(node_id)` — explicit edge cleanup by node.

The reconciler already handles node additions and removals. If we add containment edges when nodes are upserted and rely on `delete_node()` to cascade-remove edges (which it already does), the diff algorithm is unnecessary. The `UNIQUE` constraint handles idempotent re-adds. There is no need for a set-based diff because the reconciler already does incremental add/remove of nodes — we just piggyback edge writes onto those same operations.

### 2. Misunderstands the reconciler's lifecycle

The proposal suggests running edge sync "at the end of `_materialize_directories()`" and "at the end of `_do_reconcile_file()`" as batch operations. This misunderstands the reconciler's incremental design:

- The reconciler processes files one at a time (`_do_reconcile_file`).
- Each file reconcile already identifies additions, updates, and removals.
- Nodes are upserted individually, not in batch.

A batch "desired vs existing" diff at the end of each function would re-scan the entire node table on every single file change. That's O(n) for every file edit, where n is total nodes. The reconciler's current incremental design is O(k) where k is nodes in the changed file.

The correct approach: add the containment edge at the same point each node is upserted (already happens per-node), and let `delete_node()` handle edge cleanup (already does).

### 3. Transactional sync is unnecessary

The proposal emphasizes "single commit per reconcile pass" for edge sync. But `add_edge()` is idempotent and `delete_node()` already cleans up edges atomically. There's no partial-state risk because:
- An edge to a node that doesn't exist yet is harmless (the UI skips edges where endpoints are missing: `index.html:385`).
- A missing edge for an existing node just means a link doesn't render until the next upsert.
- The UNIQUE constraint prevents duplicates.

### 4. Missing the simpler API fallback

The proposal mentions an "optional" API fallback — synthesizing edges from `parent_id` if the `edges` table is empty. This is actually the simplest possible fix for the web UI, requiring zero reconciler changes. It's worth noting as a zero-risk alternative, not dismissing as "optional."

### 5. Unnecessary documentation scope

Proposing documentation updates to three files for what amounts to a 15-line reconciler change is scope creep. The API surface doesn't change at all.

---

## Recommended Fix

### Option A: Reconciler edge writes (correct approach, ~15 lines)

Add containment edge creation at the two points where nodes with `parent_id` are upserted:

**In `_materialize_directories()`**, after `upsert_node(directory_node)`:
```python
if directory_node.parent_id is not None:
    await self._node_store.add_edge(
        directory_node.parent_id, directory_node.node_id, "contains"
    )
```

**In `_do_reconcile_file()`**, after the parent_id assignment loop:
```python
for node in projected:
    if node.parent_id is not None:
        await self._node_store.add_edge(
            node.parent_id, node.node_id, "contains"
        )
```

That's it. Edge cleanup on deletion is already handled by `delete_node()`. Idempotency is already handled by `INSERT OR IGNORE`. No new APIs needed.

### Option B: API-level synthesis (zero-risk alternative)

If we want edges in the UI without touching the reconciler at all, modify `api_all_edges` in `server.py` to synthesize containment edges from `parent_id` when the `edges` table is empty:

```python
async def api_all_edges(_request: Request) -> JSONResponse:
    edges = await node_store.list_all_edges()
    if not edges:
        # Synthesize from parent_id hierarchy
        nodes = await node_store.list_nodes()
        payload = [
            {"from_id": n.parent_id, "to_id": n.node_id, "edge_type": "contains"}
            for n in nodes
            if n.parent_id is not None
        ]
        return JSONResponse(payload)
    payload = [
        {"from_id": e.from_id, "to_id": e.to_id, "edge_type": e.edge_type}
        for e in edges
    ]
    return JSONResponse(payload)
```

This is useful as a fallback but shouldn't be the primary solution — edges should be first-class persisted data for agent consumption via `graph_get_edges`.

### Recommendation

**Do Option A.** It's the right fix: edges are persisted, agents can query them via `graph_get_edges`, the web UI works, and it's ~15 lines with no new APIs. Option B can optionally be added as a defensive fallback.

---

## Test Plan (actual scope)

The intern's test plan is reasonable in coverage but lists files that don't need changes:

1. **`tests/unit/test_reconciler.py`** — Add assertions that after `full_scan()`, containment edges exist for nodes with `parent_id`. This is the critical test.
2. **`tests/unit/test_graph.py`** — No changes needed. `add_edge` and edge queries are already well-tested (5 existing test cases covering add, directions, uniqueness, deletion cascade).
3. **`tests/unit/test_web_server.py`** — No changes needed unless Option B fallback is added.
4. **Integration tests** — Reasonable to add a smoke assertion that edges > 0 after startup, but not essential for correctness.

---

## Summary Verdict

| Aspect | Intern Assessment | Correct Assessment |
|--------|------------------|--------------------|
| Gap identified | Correct | Correct |
| Root cause | Correct | Correct |
| Fix scope | New storage APIs + batch sync + transactions | ~15 lines in reconciler, no new APIs |
| Complexity | 3 new NodeStore methods + reconciler algorithm + API changes | Piggyback on existing upsert points |
| Edge cleanup | Custom diff algorithm | Already handled by `delete_node()` |
| Idempotency | Custom sync logic | Already handled by `UNIQUE` constraint |
| Risk | Medium (new transactional code paths) | Low (additive, uses existing primitives) |

The intern correctly spotted the problem but proposed a solution 10x more complex than necessary. The existing `NodeStore` API is already sufficient — the only missing piece is the reconciler actually calling `add_edge()` when it upserts nodes with a `parent_id`.
