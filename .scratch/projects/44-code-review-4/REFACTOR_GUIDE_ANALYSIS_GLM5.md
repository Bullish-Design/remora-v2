# Refactor Guide Analysis — All Phases

**Date:** 2026-03-18
**Author:** Analysis by Claude (GLM5)
**Subject:** Critical review of REVIEW_REFACTOR_GUIDE.md phases 1-15

---

## Table of Contents

1. [Phase 1: Error Hierarchy](#phase-1-error-hierarchy)
2. [Phase 2: Unify Event Dispatch to String-Based](#phase-2-unify-event-dispatch-to-string-based)
3. [Phase 3: Fix Dependency Injection — Kill the `set_tx` Cycle](#phase-3-fix-dependency-injection--kill-the-set_tx-cycle)
4. [Phase 4: Extract HumanInputBroker from EventStore](#phase-4-extract-humaninputbroker-from-eventstore)
5. [Phase 5: Adopt Structured Concurrency (TaskGroups)](#phase-5-adopt-structured-concurrency-taskgroups)
6. [Phase 6: Type-Safe Subscription Matching (RoutingEnvelope)](#phase-6-type-safe-subscription-matching-routingenvelope)
7. [Phase 7: Namespace Capability Functions](#phase-7-namespace-capability-functions)
8. [Phase 8: Make Node Immutable](#phase-8-make-node-immutable)
9. [Phase 9: Atomic File Writes for Proposal Accept](#phase-9-atomic-file-writes-for-proposal-accept)
10. [Phase 10: Use Database Row IDs for SSE Event IDs](#phase-10-use-database-row-ids-for-sse-event-ids)
11. [Phase 11: Split SearchService into Strategy Implementations](#phase-11-split-searchservice-into-strategy-implementations)
12. [Phase 12: Decompose FileReconciler](#phase-12-decompose-filereconciler)
13. [Phase 13: Code Quality Batch](#phase-13-code-quality-batch)
14. [Phase 14: Polish Batch](#phase-14-polish-batch)
15. [Phase 15: Final Cleanup Sweep](#phase-15-final-cleanup-sweep)
16. [Cross-Phase Dependencies](#cross-phase-dependencies)
17. [Recommendations Summary](#recommendations-summary)

---

## Phase 6: Type-Safe Subscription Matching (RoutingEnvelope)

### 6.1 Problem Statement

The guide correctly identifies that `SubscriptionPattern.matches()` uses 6 `getattr()` calls to probe event attributes that may not exist on all event subclasses:

```python
# Current implementation (subscriptions.py:26-58)
def matches(self, event: Event) -> bool:
    if self.from_agents:
        from_agent = getattr(event, "from_agent", None)  # Probe 1
        agent_id = getattr(event, "agent_id", None)       # Probe 2
        ...
    if self.to_agent:
        to_agent = getattr(event, "to_agent", None)       # Probe 3
        ...
    if self.path_glob:
        path = getattr(event, "path", None) or getattr(event, "file_path", None)  # Probes 4&5
        ...
    if self.tags:
        event_tags = set(getattr(event, "tags", ()))      # Probe 6
```

**Issues with current approach:**
1. **Fragile:** If an event renames `file_path` to `source_path`, matching silently breaks
2. **No compile-time safety:** Type checkers cannot verify attribute existence
3. **Inconsistent naming:** `path` vs `file_path` requires fallback logic

### 6.2 Proposed Solution Review

The guide proposes a `RoutingEnvelope` dataclass:

```python
@dataclass(frozen=True, slots=True)
class RoutingEnvelope:
    event_type: str
    agent_id: str | None = None
    from_agent: str | None = None
    to_agent: str | None = None
    path: str | None = None
    tags: tuple[str, ...] = ()
```

Each event subclass would override `routing_envelope()` to expose its routing-relevant fields.

### 6.3 Analysis

#### Strengths

1. **Type safety:** The envelope is a typed contract. MyPy/pyright can verify that `routing_envelope()` returns correct types.

2. **Encapsulation:** Field name changes (e.g., `file_path` → `source_path`) only require updating one `routing_envelope()` override, not all matching logic.

3. **Documentation:** The envelope explicitly documents which fields are routing-relevant.

4. **Using dataclass vs Pydantic:** The guide correctly chooses `dataclass` for this lightweight value object. No validation is needed, and avoiding Pydantic overhead is appropriate.

#### Weaknesses / Concerns

1. **Verbosity:** Every event subclass (currently 22 classes in `types.py`) needs a `routing_envelope()` override. This adds ~100 lines of boilerplate.

2. **Maintenance burden:** When adding a new event type, developers must remember to implement `routing_envelope()`. If forgotten, the base class default is used, which may not be correct.

3. **Duplication:** The envelope fields duplicate attributes that already exist on events. For example, `AgentMessageEvent.from_agent` appears both as an attribute and as a field returned by `routing_envelope()`.

4. **No inheritance consideration:** The guide doesn't address whether `routing_envelope()` should call `super()` to include base class fields. This could lead to subtle bugs if events are refactored.

#### Specific Implementation Issues

**Issue 1: `path` vs `file_path` mapping**

The guide shows:
```python
class NodeChangedEvent(Event):
    def routing_envelope(self) -> RoutingEnvelope:
        return RoutingEnvelope(
            event_type=self.event_type,
            path=self.file_path,  # map file_path -> path
            tags=self.tags,
        )
```

This is good — it normalizes `file_path` to `path`. But the guide should explicitly document this normalization as a design decision.

**Issue 2: Missing events**

Looking at the current `types.py`, the following events have routing-relevant fields not addressed in the guide:

| Event | Has Fields | Guide Coverage |
|-------|------------|----------------|
| `CursorFocusEvent` | `file_path` | Not mentioned |
| `HumanInputRequestEvent` | `agent_id` | Not mentioned |
| `HumanInputResponseEvent` | `agent_id` | Not mentioned |
| `RewriteProposalEvent` | `agent_id` | Not mentioned |
| `ToolResultEvent` | `agent_id` | Not mentioned |

All of these should have `routing_envelope()` overrides.

**Issue 3: The `to_agent` matching logic**

Current code:
```python
if self.to_agent:
    to_agent = getattr(event, "to_agent", None)
    if to_agent != self.to_agent:
        return False
```

Proposed code:
```python
if self.to_agent:
    if env.to_agent != self.to_agent:
        return False
```

The logic is unchanged, which is correct. However, the guide should note that `AgentMessageEvent` is the only event with `to_agent`, so this check only matters for message events.

### 6.4 Verdict

**RECOMMEND ADOPTION with modifications:**

1. ✅ The `RoutingEnvelope` concept is sound and addresses a real fragility
2. ⚠️ Add a comprehensive audit of all 22 event types with explicit `routing_envelope()` implementations
3. ⚠️ Document the `path` normalization design decision
4. ⚠️ Consider adding a unit test that verifies every event has a proper `routing_envelope()` implementation

---

## Phase 8: Make Node Immutable

### 8.1 Problem Statement

The `Node` model currently has `frozen=False`:

```python
class Node(BaseModel):
    model_config = ConfigDict(frozen=False)
    ...
```

And is mutated in-place during reconciliation:

```python
# reconciler.py:232-237
node.status = existing.status if existing is not None else NodeStatus.IDLE
node.role = (
    mapped_bundle
    if mapped_bundle is not None
    else (existing.role if existing is not None else None)
)

# reconciler.py:268-270
if node.parent_id is None:
    node.parent_id = dir_node_id
    await self._node_store.upsert_node(node)
```

### 8.2 Proposed Solution Review

The guide proposes setting `frozen=True` and replacing mutations with `model_copy(update=...)`.

### 8.3 Analysis

#### Strengths

1. **Immutability benefits:** Immutable models are easier to reason about, thread-safe by design, and enable change tracking.

2. **Pydantic alignment:** Frozen models align with Pydantic v2's recommendation for value objects.

3. **Explicit updates:** `model_copy(update=...)` makes changes visible at the call site.

#### Weaknesses / Concerns

1. **Performance overhead:** `model_copy()` creates a new Pydantic model instance. This involves validation, which has non-trivial overhead. The reconciliation code path creates many nodes; the cumulative cost should be measured.

2. **Ergonomics:** The mutation pattern `node.status = new_status` is simple and readable. The replacement pattern:
   ```python
   node = node.model_copy(update={"status": new_status})
   ```
   is more verbose and creates visual noise.

3. **Variable reassignment:** The pattern requires reassigning `node` after each `model_copy()`. This is error-prone — forgetting the reassignment would silently use the old value:
   ```python
   # BUG: forgetting to reassign
   node.model_copy(update={"status": new_status})  # Returns new instance, discarded
   await self._node_store.upsert_node(node)  # Uses old, unmodified node
   ```

4. **Multiple updates in sequence:** The guide shows this pattern:
   ```python
   node = node.model_copy(update={
       "status": existing.status if existing is not None else NodeStatus.IDLE,
       "role": mapped_bundle if mapped_bundle is not None else (existing.role if existing is not None else None),
   })
   ```
   This bundles multiple updates, which is good. But if updates need to happen in different code paths, you end up with:
   ```python
   node = node.model_copy(update={"status": new_status})
   # ... other logic ...
   node = node.model_copy(update={"parent_id": dir_node_id})
   ```
   Each `model_copy()` triggers full validation.

#### Mutation Sites Analysis

From grep results, mutations occur in:

| File | Line | Mutation |
|------|------|----------|
| `reconciler.py` | 232 | `node.status = ...` |
| `reconciler.py` | 233 | `node.role = ...` |
| `reconciler.py` | 269 | `node.parent_id = ...` |

The guide correctly identifies all production mutation sites. Test files have additional assertions that would need updates, but these are straightforward.

#### Alternative Considered: `validate_on_frozen=False`

Pydantic allows disabling validation during construction:
```python
model_config = ConfigDict(frozen=True, validate_on_assignment=False)
```

But this doesn't help — the issue is that `model_copy()` triggers validation by default. The guide doesn't address this.

#### Alternative Considered: Data Class

If performance is critical, Python's `@dataclass(frozen=True)` would be faster than Pydantic frozen models. But this would lose Pydantic's serialization, validation, and schema generation features.

### 8.4 Verdict

**RECOMMEND ADOPTION with caveats:**

1. ✅ Immutability is the right architectural direction
2. ⚠️ Benchmark the reconciliation path before/after to measure performance impact
3. ⚠️ Add lint rules or code review checklist to catch `model_copy()` calls without reassignment
4. ⚠️ Consider using `model_copy(update=..., deep=False)` if nested models don't need copying

---

## Phase 9: Atomic File Writes for Proposal Accept

### 9.1 Problem Statement

In `api_proposal_accept` (proposals.py:136):
```python
disk_path.write_bytes(new_bytes)
```

A crash or disk-full condition mid-write corrupts user source code.

### 9.2 Proposed Solution Review

The guide proposes a standard atomic write pattern:
1. Write to a temp file
2. `fsync()` to ensure data is on disk
3. Atomic `os.replace()` (rename) to target path

### 9.3 Analysis

#### Strengths

1. **Correct implementation:** The proposed code follows the standard POSIX atomic write pattern:
   ```python
   fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
   try:
       os.write(fd, content)
       os.fsync(fd)
       os.close(fd)
       os.replace(tmp_path, path)  # atomic on POSIX
   except BaseException:
       os.close(fd)
       with contextlib.suppress(OSError):
           os.unlink(tmp_path)
       raise
   ```

2. **Defensive error handling:** The `except BaseException` catches all exceptions including `KeyboardInterrupt`, ensuring cleanup.

3. **Cross-platform consideration:** Using `os.replace()` instead of `os.rename()` is correct — `replace` is atomic on POSIX and works on Windows (though not atomic there).

#### Weaknesses / Concerns

1. **Missing `import contextlib`:** The guide shows `with contextlib.suppress(OSError)` but doesn't mention importing `contextlib`. This is a minor oversight.

2. **Directory creation:** The guide shows:
   ```python
   disk_path.parent.mkdir(parents=True, exist_ok=True)
   atomic_write(disk_path, new_bytes)
   ```
   This is correct, but the `atomic_write` function should arguably handle parent directory creation itself for encapsulation. Currently, callers must remember to create parent directories.

3. **fsync overhead:** `fsync()` can be slow (milliseconds to seconds depending on disk). For a web endpoint, this adds latency. This is acceptable for data safety, but should be documented.

4. **Temp file location:** The temp file is created in `path.parent`. If `path.parent` is on a different filesystem than `/tmp`, the `mkstemp` might fail or the `replace` might not be atomic. The current approach (same directory as target) is correct for atomicity but could fill up the user's filesystem if many temp files accumulate before cleanup.

5. **No file permissions handling:** The temp file will have default permissions. If the original file had specific permissions, they're lost. The guide doesn't address this.

#### Current Code Context

Looking at the actual `api_proposal_accept`:

```python
# proposals.py:130-146
old_bytes = disk_path.read_bytes() if disk_path.exists() else b""
new_bytes = new_source.encode("utf-8")
if old_bytes == new_bytes:
    continue

disk_path.parent.mkdir(parents=True, exist_ok=True)
disk_path.write_bytes(new_bytes)  # <-- THE PROBLEMATIC LINE
await deps.event_store.append(ContentChangedEvent(...))
```

The guide's fix correctly targets line 136. The surrounding context is preserved.

#### Security Consideration

Atomic writes prevent corruption but don't address:
- TOCTOU races between the `read_bytes()` and `write_bytes()`
- Symlink attacks (an attacker could create a symlink at `disk_path` between the check and write)

The guide doesn't mention these, but they're outside the scope of this particular fix.

### 9.4 Verdict

**STRONGLY RECOMMEND ADOPTION:**

1. ✅ Implementation is correct and follows best practices
2. ⚠️ Add `import contextlib` to the imports
3. ⚠️ Document the fsync latency implication
4. ✅ The proposed `atomic_write` utility belongs in `core/utils.py`

---

## Phase 10: Use Database Row IDs for SSE Event IDs

### 10.1 Problem Statement

SSE (Server-Sent Events) uses `event.timestamp` as the event ID:

```python
# sse.py:95
yield f"id: {event.timestamp}\nevent: {event.event_type}\ndata: {payload}\n\n"
```

Issues:
1. Timestamps are floats, not unique — two events in the same millisecond get the same ID
2. SSE reconnection with `Last-Event-ID` would miss events with duplicate timestamps

### 10.2 Proposed Solution Review

The guide proposes:
1. Add `event_id: int | None` field to `Event` base class
2. `EventStore.append()` sets `event.event_id` after INSERT
3. SSE uses `event_id` if available, falling back to `timestamp`

### 10.3 Analysis

#### Strengths

1. **Correct problem identification:** Float timestamps are indeed unsuitable as unique IDs.

2. **Minimal changes:** The proposed solution is surgically targeted.

3. **Graceful fallback:** The SSE code falls back to `timestamp` if `event_id` is not set:
   ```python
   sse_id = event.event_id if event.event_id is not None else event.timestamp
   ```

#### Weaknesses / Concerns

**Issue 1: Mutating Event after creation**

The guide proposes:
```python
async def append(self, event: Event) -> int:
    ...
    event_id = int(cursor.lastrowid)
    event.event_id = event_id  # stamp it before bus emission
```

This mutates `event` in place. If Phase 8 makes `Node` frozen, consistency would suggest `Event` should also be frozen. But the guide explicitly notes:

> This requires Node to be `frozen=False` for Event... but Event is NOT frozen (it has no `ConfigDict(frozen=True)`), so this mutation is fine.

This is technically correct but architecturally inconsistent. The codebase would have:
- `Node` — frozen (immutable)
- `Event` — mutable

This inconsistency could confuse future developers.

**Issue 2: Event identity vs Event content**

Adding `event_id` to `Event` conflates the event's content (what happened) with its storage metadata (which row it occupies). These are separate concerns:
- **Content:** `event_type`, `timestamp`, `agent_id`, `payload`, etc.
- **Metadata:** `event_id` (database row), potentially `created_at`, etc.

A cleaner design would keep these separate:
```python
@dataclass
class StoredEvent:
    event: Event
    row_id: int
    # Maybe: stored_at: float
```

However, this would require more invasive changes to the SSE streaming path.

**Issue 3: Live events vs replayed events**

The guide correctly notes:
> For events replayed from the database, we already have `row["id"]` and use it correctly. But for live-streamed events (via `EventBus.stream()`), the event object doesn't carry the DB row ID.

Looking at `sse.py:38-50`:
```python
if last_event_id:
    rows = await deps.event_store.get_events_after(last_event_id)
    for row in rows:
        event_id = row.get("id", "")  # <-- Uses DB row ID
        ...
        yield f"id: {event_id}\nevent: {event_name}\ndata: {payload_text}\n\n"
```

Replayed events already use `row["id"]`. Live events use `event.timestamp`. The proposed change unifies these.

**Issue 4: The `get_events_after` parameter type**

Currently:
```python
async def get_events_after(self, after_id: str, limit: int = 500) -> list[dict[str, Any]]:
```

The `after_id` is a `str`, but it's converted to `int` inside:
```python
try:
    numeric_id = int(after_id)
except (TypeError, ValueError):
    return []
```

The guide (Phase 13.10) proposes changing this to `after_id: int`. This should be coordinated.

**Issue 5: No migration path**

If existing clients have cached `Last-Event-ID` values as float timestamps, they will:
1. Send the float timestamp as `Last-Event-ID`
2. Server tries to `int(float_timestamp)` which works
3. Server queries `WHERE id > int_value`
4. Events with IDs less than or equal are missed

Wait, let me reconsider. If a client has `Last-Event-ID: 1712345678.123`, the server does:
```python
numeric_id = int(after_id)  # 1712345678
```

Then `WHERE id > 1712345678`. If the actual DB row IDs are much smaller (e.g., starting from 1), this would return no events. The client would miss all events until the ID exceeds the float value.

This is a **breaking change** for existing clients with cached timestamps.

### 10.4 Verdict

**RECOMMEND ADOPTION with modifications:**

1. ✅ The core idea (use DB row IDs) is correct
2. ⚠️ Document the breaking change for existing SSE clients
3. ⚠️ Consider: `after_id` could be detected as either `int` (new format) or `float` (old format) with appropriate handling
4. ⚠️ Coordinate with Phase 13.10 (`get_events_after` parameter type change)
5. ⚠️ Consider architectural consistency: if `Node` is frozen, should `Event` be frozen too? If yes, use a different approach (e.g., return `event_id` from `append()` and pass it separately through the streaming path)

---

## Cross-Phase Dependencies

### Complete Dependency Graph

```
Phase 1 (Error Hierarchy) ────────────────────────────────────────┐
   │ All phases depend on this for exception types                 │
   │ STATUS: Already implemented                                   │
   │                                                                │
Phase 2 (String-Based Dispatch) ───────────────────────────────────┤
   │ Independent                                                    │
   │ STATUS: Already implemented                                    │
   │                                                                │
Phase 3 (Dependency Injection) ────────────────────────────────────┤
   │ Independent                                                    │
   │ STATUS: Already implemented                                    │
   │                                                                │
Phase 4 (HumanInputBroker) ────────────────────────────────────────┤
   │ Independent                                                    │
   │ STATUS: Already implemented                                    │
   │                                                                │
Phase 5 (TaskGroups) ──────────────────────────────────────────────┤
   │ Depends on: Phase 1 (exception types for except*)              │
   │ STATUS: Partially implemented                                  │
   │                                                                │
Phase 6 (RoutingEnvelope) ─────────────────────────────────────────┤
   │ Independent                                                    │
   │ STATUS: Needs implementation                                   │
   │                                                                │
Phase 7 (Capability Namespacing) ──────────────────────────────────┤
   │ ❌ DO NOT IMPLEMENT — Incompatible with Grail                  │
   │                                                                │
Phase 8 (Frozen Node) ─────────────────────────────────────────────┤
   │ Depends on: Phase 6 (should come after)                        │
   │ STATUS: Needs implementation                                   │
   │                                                                │
Phase 9 (Atomic Writes) ───────────────────────────────────────────┤
   │ Independent                                                    │
   │ STATUS: Needs implementation                                   │
   │                                                                │
Phase 10 (SSE Event IDs) ──────────────────────────────────────────┤
   │ Depends on: Phase 8 (Event mutability decision)                │
   │ Coordinates: Phase 13.10 (get_events_after param)              │
   │ STATUS: Needs implementation                                   │
   │                                                                │
Phase 11 (SearchService Split) ────────────────────────────────────┤
   │ Independent                                                    │
   │ STATUS: Needs implementation                                   │
   │                                                                │
Phase 12 (FileReconciler Decompose) ───────────────────────────────┤
   │ Independent                                                    │
   │ STATUS: Needs implementation                                   │
   │                                                                │
Phase 13 (Code Quality Batch) ─────────────────────────────────────┤
   │ Independent, but 13.10 coordinates with Phase 10               │
   │ STATUS: Needs implementation                                   │
   │                                                                │
Phase 14 (Polish Batch) ───────────────────────────────────────────┤
   │ Independent                                                    │
   │ STATUS: Needs implementation                                   │
   │                                                                │
Phase 15 (Final Cleanup) ──────────────────────────────────────────┤
   │ Must come LAST after all other phases                          │
   │ STATUS: Needs implementation                                   │
   │                                                                │
└──────────────────────────────────────────────────────────────────┘
```

### Execution Order Recommendation

**Already Complete (verify):**
1. Phase 1: Error Hierarchy
2. Phase 2: String-Based Dispatch  
3. Phase 3: Dependency Injection
4. Phase 4: HumanInputBroker

**Round 1 (Foundational):**
5. Phase 5: Complete TaskGroups implementation
6. Phase 6: RoutingEnvelope
7. Phase 9: Atomic Writes (independent, high priority)

**Round 2 (Architecture):**
8. Phase 8: Frozen Node
9. Phase 10: SSE Event IDs
10. Phase 13.10: get_events_after parameter type

**Round 3 (Decomposition):**
11. Phase 11: SearchService Split
12. Phase 12: FileReconciler Decompose

**Round 4 (Polish):**
13. Phase 13 (remaining items): Code Quality Batch
14. Phase 14: Polish Batch

**Final:**
15. Phase 15: Final Cleanup Sweep

**SKIPPED:**
- Phase 7: Namespace Capability Functions (incompatible with Grail)

---

## Recommendations Summary

### Implementation Status Overview

| Phase | Name | Status | Recommendation |
|-------|------|--------|----------------|
| 1 | Error Hierarchy | ✅ Implemented | Verify completion |
| 2 | String-Based Dispatch | ✅ Implemented | Verify completion |
| 3 | Dependency Injection | ✅ Implemented | Verify completion |
| 4 | HumanInputBroker | ✅ Implemented | Verify completion |
| 5 | TaskGroups | ⚠️ Partial | Complete remaining items |
| 6 | RoutingEnvelope | ❌ Not Started | **RECOMMEND** |
| 7 | Capability Namespacing | ❌ Skipped | **DO NOT IMPLEMENT** |
| 8 | Frozen Node | ❌ Not Started | **RECOMMEND** (with caveats) |
| 9 | Atomic Writes | ❌ Not Started | **STRONGLY RECOMMEND** |
| 10 | SSE Event IDs | ❌ Not Started | **RECOMMEND** (with modifications) |
| 11 | SearchService Split | ❌ Not Started | **RECOMMEND** |
| 12 | FileReconciler Decompose | ❌ Not Started | **RECOMMEND** |
| 13 | Code Quality Batch | ❌ Not Started | **RECOMMEND** |
| 14 | Polish Batch | ❌ Not Started | **RECOMMEND** |
| 15 | Final Cleanup | ❌ Not Started | **REQUIRED** (last step) |

### Phase-by-Phase Summary

#### Phase 1-4: Already Implemented
- **Action:** Run verification commands to confirm
- **Risk:** Low — verify no regressions

#### Phase 5: TaskGroups (Partial)
- **Missing:** SSE streaming TaskGroups, lifecycle simplification
- **Priority:** Medium
- **Risk:** Medium — async generator edge cases
- **Action:** Complete SSE implementation, verify lifecycle shutdown

#### Phase 6: RoutingEnvelope
- **Adoption:** ✅ **YES**
- **Priority:** Medium
- **Effort:** Medium (~100 lines boilerplate)
- **Risk:** Low
- **Action:** Implement for all 22 event types, add tests

#### Phase 7: Capability Namespacing
- **Adoption:** ❌ **NO**
- **Reason:** Fundamentally incompatible with Grail
- **Action:** Skip; add collision validation in `to_capabilities_dict()` instead

#### Phase 8: Frozen Node
- **Adoption:** ✅ **YES** (with caveats)
- **Priority:** High (architectural improvement)
- **Effort:** Medium-High
- **Risk:** Medium (performance, reassignment bugs)
- **Action:** Benchmark before/after, add lint rules

#### Phase 9: Atomic Writes
- **Adoption:** ✅ **YES**
- **Priority:** High (data safety)
- **Effort:** Low
- **Risk:** Low
- **Action:** Implement immediately

#### Phase 10: SSE Event IDs
- **Adoption:** ✅ **YES** (with modifications)
- **Priority:** Medium
- **Effort:** Medium
- **Risk:** Medium (breaking change)
- **Action:** Document breaking change, handle legacy format

#### Phase 11: SearchService Split
- **Adoption:** ✅ **YES**
- **Priority:** Medium
- **Effort:** Medium
- **Risk:** Low
- **Action:** Extract strategies, maintain error handling

#### Phase 12: FileReconciler Decompose
- **Adoption:** ✅ **YES**
- **Priority:** Medium
- **Effort:** High (many dependencies)
- **Risk:** Medium (constructor complexity)
- **Action:** Extract classes, consider dependency grouping

#### Phase 13-15: Quality/Cleanup
- **Adoption:** ✅ **YES**
- **Priority:** Low ( polish)
- **Effort:** Low per item
- **Risk:** Low
- **Action:** Execute in order after architecture phases

### Critical Actions

1. **Immediately implement:** Phase 9 (Atomic Writes) — data safety
2. **Verify first:** Phases 1-4 — confirm already implemented
3. **Architecture decision:** Phase 8 vs Event mutability (Phase 10 dependency)
4. **Skip entirely:** Phase 7 — incompatible with Grail
5. **Last step:** Phase 15 — only after all others complete

---

*End of Comprehensive Analysis*

## Appendix A: Event Types Audit

All event classes in `core/events/types.py` and their routing-relevant fields:

| Event | Routing Fields | Notes |
|-------|----------------|-------|
| `Event` (base) | `event_type`, `tags` | Base implementation |
| `AgentStartEvent` | `agent_id` | ✅ Covered in guide |
| `AgentCompleteEvent` | `agent_id` | Needs override |
| `AgentErrorEvent` | `agent_id` | Needs override |
| `AgentMessageEvent` | `from_agent`, `to_agent` | ✅ Covered in guide |
| `NodeDiscoveredEvent` | `file_path` → `path` | Needs override |
| `NodeRemovedEvent` | `file_path` → `path` | Needs override |
| `NodeChangedEvent` | `file_path` → `path` | ✅ Covered in guide |
| `ContentChangedEvent` | `path`, `agent_id` | ✅ Covered in guide |
| `HumanInputRequestEvent` | `agent_id` | Needs override |
| `HumanInputResponseEvent` | `agent_id` | Needs override |
| `RewriteProposalEvent` | `agent_id` | Needs override |
| `RewriteAcceptedEvent` | `agent_id` | Needs override |
| `RewriteRejectedEvent` | `agent_id` | Needs override |
| `ModelRequestEvent` | `agent_id` | Needs override |
| `ModelResponseEvent` | `agent_id` | Needs override |
| `RemoraToolCallEvent` | `agent_id` | Needs override |
| `RemoraToolResultEvent` | `agent_id` | Needs override |
| `TurnCompleteEvent` | `agent_id` | Needs override |
| `TurnDigestedEvent` | `agent_id` | Needs override |
| `CustomEvent` | (none beyond base) | Uses base implementation |
| `ToolResultEvent` | `agent_id` | Needs override |
| `CursorFocusEvent` | `file_path` → `path` | Needs override |

**16 events need explicit `routing_envelope()` overrides.**

---

## Appendix B: Mutation Sites Detail

All `node.(status|role|parent_id) =` mutations found:

| File | Line | Code | Fix Complexity |
|------|------|------|----------------|
| `reconciler.py` | 232 | `node.status = existing.status if ...` | Medium |
| `reconciler.py` | 233-237 | `node.role = mapped_bundle if ...` | Medium |
| `reconciler.py` | 269 | `node.parent_id = dir_node_id` | Simple |

**Test files** (not requiring production fixes):
- `test_externals.py:461` — assertion
- `test_reconciler.py:116, 397, 865` — assertions
- `test_actor.py:1081` — assertion
- `test_node.py:33` — assertion
- `test_refactor_naming.py:27` — assertion

---

*End of Part 1: Phases 6, 8, 9, 10*

---

## Phase 1: Error Hierarchy

### 1.1 Problem Statement

The codebase has ~12-14 `except Exception` blocks that catch too broadly. The guide proposes creating a proper exception hierarchy and replacing broad catches with specific types.

### 1.2 Proposed Solution Review

**Current state:** `core/model/errors.py` already has the hierarchy defined:
```python
class RemoraError(Exception): ...
class ModelError(RemoraError): ...
class ToolError(RemoraError): ...
class WorkspaceError(RemoraError): ...
class SubscriptionError(RemoraError): ...
class IncompatibleBundleError(RemoraError): ...
```

**The hierarchy is already implemented.** The guide's Phase 1 appears to be already complete in the codebase.

### 1.3 Analysis

#### Strengths

1. **Well-designed hierarchy:** The exception classes follow Python conventions with clear separation of concerns:
   - `ModelError` for LLM backend failures
   - `ToolError` for Grail tool execution
   - `WorkspaceError` for filesystem operations
   - `SubscriptionError` for event routing

2. **Comprehensive mapping:** The guide provides an exact line-by-line mapping for each `except Exception` replacement.

3. **Boundary pattern documented:** The guide correctly identifies two acceptable `except Exception` locations:
   - `grail.py` — wrapping untrusted tool script code
   - `kernel.py` — wrapping external library calls

#### Weaknesses / Concerns

**Issue 1: Verification needed**

The guide lists specific line numbers, but these may have drifted since the guide was written. Each site needs manual verification.

**Issue 2: Exception group handling**

The guide mentions using `except*` syntax (Python 3.11+) for TaskGroups. This is correct but creates a Python version dependency. The project targets 3.13+, so this is acceptable.

**Issue 3: Some catch sites might be too narrow**

For example, `turn.py:346` is listed as:
```python
except (OSError, aiosqlite.Error)
```

But what if Pydantic raises a validation error during status reset? This would propagate unexpectedly. Consider whether the catch should be broader at this boundary.

### 1.4 Verdict

**ALREADY IMPLEMENTED / VERIFY COMPLETION:**

1. ✅ Error hierarchy exists in `core/model/errors.py`
2. ⚠️ Verify each `except Exception` site matches the guide's line numbers
3. ⚠️ Run `rg "except Exception" src/remora/` and verify only 2 hits remain
4. ⚠️ Check for any `# noqa: BLE001` comments that should be removed

---

## Phase 2: Unify Event Dispatch to String-Based

### 2.1 Problem Statement

The codebase had two event routing mechanisms:
- `EventBus` dispatched by Python class type
- `SubscriptionRegistry` dispatched by `event_type` string

### 2.2 Proposed Solution Review

The guide proposes changing `EventBus` to key on `event_type` strings instead of class types.

### 2.3 Analysis

#### Current State Verification

Looking at `core/events/bus.py`:
```python
def __init__(self, max_concurrent_handlers: int = 100) -> None:
    self._handlers: dict[str, list[EventHandler]] = {}  # <-- Already string-keyed!
```

**Phase 2 appears to be already implemented.** The `EventBus` already uses string-based dispatch.

#### Strengths

1. **Correct architectural decision:** String-based dispatch aligns with SQLite persistence, SSE wire format, and subscription patterns.

2. **Clean implementation:** The current `emit()` method correctly dispatches on `event.event_type`.

#### Weaknesses / Concerns

**Issue 1: Type safety trade-off**

String-based dispatch loses the compile-time safety of class-based dispatch. The `EventType` enum mitigates this, but it's still string comparison at runtime.

**Issue 2: `isinstance` checks become redundant**

The guide notes that the `isinstance` check in `_on_content_changed` is now redundant but recommends keeping it as a type narrowing hint. This is good advice.

### 2.4 Verdict

**ALREADY IMPLEMENTED:**

1. ✅ `EventBus` uses `dict[str, list[EventHandler]]` for handler storage
2. ✅ `subscribe()` takes `event_type: str`
3. ✅ `emit()` dispatches on `event.event_type`
4. ⚠️ Verify `stream()` filtering uses string membership

---

## Phase 3: Fix Dependency Injection — Kill the `set_tx` Cycle

### 3.1 Problem Statement

`RuntimeServices.__init__` created a hidden circular dependency: `TransactionContext` needs `TriggerDispatcher`, `TriggerDispatcher` needs `SubscriptionRegistry`, `SubscriptionRegistry` needs `TransactionContext`. The cycle was broken via `set_tx()` method.

### 3.2 Proposed Solution Review

The guide proposes:
1. `SubscriptionRegistry` accepts `tx` at construction (optional)
2. `TriggerDispatcher` accepts `subscriptions` lazily via property setter
3. Delete `set_tx()` entirely

### 3.3 Analysis

#### Current State Verification

Looking at `core/events/subscriptions.py:64`:
```python
def __init__(self, db: aiosqlite.Connection, tx: TransactionContext | None = None):
    self._db = db
    self._tx = tx
```

**Phase 3 appears to be already implemented.** The `SubscriptionRegistry` already accepts `tx` at construction.

#### Strengths

1. **Eliminates hidden mutation:** No more `set_tx()` call after construction.

2. **Clearer initialization order:** The phased construction in `RuntimeServices.__init__` is documented.

3. **Explicit optional dependencies:** Using `| None` makes the dependency relationship clear.

#### Weaknesses / Concerns

**Issue 1: Runtime error vs compile-time error**

If code accesses `TriggerDispatcher.subscriptions` before wiring, it gets a `RuntimeError`. This is a runtime check rather than a compile-time guarantee.

**Issue 2: Setter pattern is unconventional**

Using `@subscriptions.setter` for post-construction wiring is unusual in Python. Consider whether a `wire_subscriptions()` method would be clearer.

### 3.4 Verdict

**ALREADY IMPLEMENTED:**

1. ✅ `SubscriptionRegistry.__init__` accepts `tx: TransactionContext | None`
2. ⚠️ Verify `set_tx()` method is deleted
3. ⚠️ Verify `TriggerDispatcher` has lazy subscriptions property

---

## Phase 4: Extract HumanInputBroker from EventStore

### 4.1 Problem Statement

`EventStore` managed `_pending_responses` (asyncio futures for human-input request/response) alongside event persistence and bus emission. This violated SRP.

### 4.2 Proposed Solution Review

Extract a dedicated `HumanInputBroker` class:
```python
class HumanInputBroker:
    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Future[str]] = {}
    
    def create_request(self, request_id: str) -> asyncio.Future[str]: ...
    def resolve(self, request_id: str, response: str) -> bool: ...
    def discard(self, request_id: str) -> bool: ...
```

### 4.3 Analysis

#### Current State Verification

Looking at `core/services/broker.py` — the file exists and contains:
```python
class HumanInputBroker:
    """Manages pending human-input response futures."""
```

**Phase 4 appears to be already implemented.**

#### Strengths

1. **Clean SRP:** `EventStore` handles persistence; `HumanInputBroker` handles request/response futures.

2. **Testability:** `HumanInputBroker` can be unit tested independently.

3. **Clear ownership:** The broker is explicitly passed to components that need it.

#### Weaknesses / Concerns

**Issue 1: Threading through dependencies**

The broker must be threaded through: `RuntimeServices` → `TurnContext` → `CommunicationCapabilities`. This adds constructor parameters but is architecturally correct.

**Issue 2: Potential for inconsistent state**

If `resolve()` is called for a non-existent request_id, it returns `False` silently. Consider whether this should log a warning or raise.

### 4.4 Verdict

**ALREADY IMPLEMENTED:**

1. ✅ `HumanInputBroker` class exists in `core/services/broker.py`
2. ✅ Methods: `create_request`, `resolve`, `discard`
3. ⚠️ Verify `EventStore` no longer has future methods
4. ⚠️ Verify wiring in `RuntimeServices` and `TurnContext`

---

## Phase 5: Adopt Structured Concurrency (TaskGroups)

### 5.1 Problem Statement

The codebase manually managed `asyncio.Task` objects in lists, used `gather`/`wait`, and had complex cancellation logic in finally blocks.

### 5.2 Proposed Solution Review

Replace manual task management with `asyncio.TaskGroup` (Python 3.11+).

### 5.3 Analysis

#### Current State Verification

Looking at `core/events/bus.py:56-63`:
```python
async with asyncio.TaskGroup() as tg:
    for handler in async_handlers:
        if semaphore is None:
            tg.create_task(EventBus._run_guarded(handler, event))
        else:
            tg.create_task(EventBus._run_guarded(handler, event, semaphore=semaphore))
```

**Phase 5 appears to be partially implemented.** The `EventBus` already uses TaskGroups.

#### Strengths

1. **Automatic cleanup:** TaskGroup cancels child tasks on exit, eliminating manual cancellation loops.

2. **Structured error propagation:** `except*` handles ExceptionGroups properly.

3. **Simpler lifecycle:** The `shutdown()` method shrinks from 65+ lines to ~15 lines.

#### Weaknesses / Concerns

**Issue 1: ExceptionGroup handling complexity**

The `except*` syntax is new and may be unfamiliar to developers. Proper handling requires understanding how exceptions are grouped.

**Issue 2: SSE generator caveat**

The guide correctly notes that TaskGroups inside async generators can be tricky:
> The generator may be abandoned by the framework without a clean `aclose()`. Test this thoroughly.

Looking at `web/sse.py:69-100`, the current implementation uses manual task management:
```python
disconnect_task = asyncio.create_task(_wait_for_disconnect(request), name="sse-disconnect")
shutdown_task = asyncio.create_task(_wait_for_shutdown(deps.shutdown_event), name="sse-shutdown")
```

This suggests Phase 5 may not be fully implemented for SSE streaming.

**Issue 3: Parallel vs sequential event fan-out**

The guide proposes parallel event fan-out in `transaction.py`:
```python
async with asyncio.TaskGroup() as tg:
    for event in self._deferred_events:
        tg.create_task(self._fan_out(event))
```

But notes: "If event ordering matters for triggers, keep sequential emission." This requires careful analysis of event dependencies.

### 5.4 Verdict

**PARTIALLY IMPLEMENTED:**

1. ✅ `EventBus._dispatch_handlers` uses TaskGroup
2. ⚠️ SSE streaming still uses manual task management (verify if intentional)
3. ⚠️ `lifecycle.py` `shutdown()` may not be simplified yet
4. ⚠️ Verify `transaction.py` deferred event handling

---

## Phase 7: Namespace Capability Functions

### 7.1 Problem Statement

`TurnContext.to_capabilities_dict()` merges all capability groups into one flat dict. If two groups define a function with the same name, the last one wins silently.

### 7.2 Proposed Solution Review

The guide proposes namespacing capability functions (e.g., `read_file` → `files.read_file`).

### 7.3 Analysis

**CRITICAL: This phase is fundamentally incompatible with Grail.**

See the separate `GRAIL_ANALYSIS_REPORT.md` in project 46 for a detailed analysis of why Phase 7 cannot work with Grail's `@external` decorator system.

**Key issues:**
1. Grail's `@external` decorator expects bare function names
2. All 29 `.pym` scripts use bare names (`read_file`, `kv_get`, etc.)
3. No actual naming collisions exist in current capability classes
4. Implementing namespacing would require modifying Grail itself

### 7.4 Verdict

**DO NOT IMPLEMENT:**

1. ❌ Fundamentally incompatible with Grail architecture
2. ❌ Would require updating all 29 `.pym` scripts
3. ❌ Would require modifying Grail's parser, code generator, and stub system
4. ✅ Current capability naming already prevents collisions (`kv_*`, `graph_*`, `event_*` prefixes)
5. ✅ `GrailTool.execute()` already filters capabilities to declared externals

**Alternative:** Add validation in `to_capabilities_dict()` that raises on collision detection.

---

## Phase 11: Split SearchService into Strategy Implementations

### 11.1 Problem Statement

`SearchService` has `if self._client ... elif self._pipeline ...` branching in every method, making it harder to maintain.

### 11.2 Proposed Solution Review

Replace the single `SearchService` class with:
- `RemoteSearchService` — backed by remote embeddy server
- `LocalSearchService` — backed by in-process embeddy

Both implement `SearchServiceProtocol`.

### 11.3 Analysis

#### Current State Verification

Looking at `core/services/search.py`, the file contains:
1. `SearchServiceProtocol` — the Protocol definition
2. `SearchService` — a monolithic class with branching

**Phase 11 is NOT yet implemented.**

#### Strengths

1. **Strategy pattern:** Each implementation is self-contained and testable.

2. **No branching:** Each class has a single code path.

3. **Factory function:** `create_search_service()` encapsulates the choice logic.

#### Weaknesses / Concerns

**Issue 1: Code duplication**

`RemoteSearchService.search()` and `LocalSearchService.search()` will have similar structure:
```python
if not self._available:
    return []
target = collection or self._config.default_collection
# ... implementation-specific logic
```

The "check availability, get target, execute" pattern is duplicated.

**Issue 2: `collection_for_file` placement**

The guide mentions:
> Also add `collection_for_file` as a standalone function or put it on both implementations.

Looking at the current implementation, `collection_for_file` is a method on `SearchService`. Making it standalone is fine, but this is an extra change not detailed in the guide.

**Issue 3: Error handling divergence**

The current `SearchService.initialize()` handles both remote and local initialization with different error handling. The split would require duplicating or refactoring this logic.

### 11.4 Verdict

**RECOMMEND ADOPTION:**

1. ✅ Strategy pattern is cleaner than branching
2. ⚠️ Be careful about code duplication (extract shared helpers)
3. ⚠️ Ensure `collection_for_file` is properly handled
4. ⚠️ Maintain same error handling behavior for backward compatibility

---

## Phase 12: Decompose FileReconciler

### 12.1 Problem Statement

`FileReconciler` is a God class with 400+ lines and 15+ methods covering file watching, node CRUD, bundle provisioning, search indexing, subscription management, directory management, and virtual agent management.

### 12.2 Proposed Solution Review

Extract multiple focused classes:
- `BundleProvisioner` — resolves and provisions agent bundle templates
- `SearchIndexer` — manages search index updates during reconciliation
- `NodeReconciler` — reconciles discovered nodes with the persistent graph

`FileReconciler` becomes a thin orchestrator (~100 lines).

### 12.3 Analysis

#### Current State Verification

Looking at `code/reconciler.py`, the file is 414 lines. The `FileReconciler` class contains:
- `_resolve_bundle_template_dirs()` 
- `_provision_bundle()`
- `_index_file_for_search()`
- `_deindex_file_for_search()`
- `_do_reconcile_file()`
- `_reconcile_events()`
- `_remove_node()`

Plus orchestration methods: `full_scan()`, `reconcile_cycle()`, `run_forever()`.

**Phase 12 is NOT yet implemented.**

#### Strengths

1. **SRP adherence:** Each extracted class has a single responsibility.

2. **Testability:** Each class can be unit tested in isolation.

3. **Easier maintenance:** Changes to bundle provisioning don't affect search indexing.

#### Weaknesses / Concerns

**Issue 1: Circular dependencies**

The extracted classes need many dependencies:
```python
class NodeReconciler:
    def __init__(
        self,
        config: Config,
        node_store: NodeStore,
        event_store: EventStore,
        subscription_manager: SubscriptionManager,
        provisioner: BundleProvisioner,
        indexer: SearchIndexer,
        directory_manager: DirectoryManager,
        language_registry: LanguageRegistry,
        project_root: Path,
        tx: TransactionContext | None = None,
    ): ...
```

This is a 10-parameter constructor. Consider whether some dependencies can be grouped.

**Issue 2: State management**

`FileReconciler` owns state (`_file_state`, `_file_locks`, `_file_lock_generations`). The guide proposes keeping these in `FileReconciler`. This is correct, but the state must be passed to `NodeReconciler.reconcile_file()`.

**Issue 3: Method visibility**

Currently, `_do_reconcile_file()` is private. After extraction, `NodeReconciler.reconcile_file()` would be public. This is fine, but changes the API contract.

**Issue 4: `DirectoryManager` and `VirtualAgentManager` already exist**

Looking at the current code, these are already extracted:
```python
self._directory_manager = DirectoryManager(...)
self._virtual_agent_manager = VirtualAgentManager(...)
```

The guide's proposal focuses on extracting the remaining monolithic functionality.

### 12.4 Verdict

**RECOMMEND ADOPTION with modifications:**

1. ✅ The decomposition is architecturally sound
2. ⚠️ Consider grouping related dependencies (e.g., `ReconcilerDeps` dataclass)
3. ⚠️ Ensure state management is clear
4. ⚠️ Update tests to verify each extracted class independently

---

## Phase 13: Code Quality Batch

### 13.1 Overview

This phase contains 11 self-contained improvements. Each can be done independently.

### 13.2 Analysis of Each Item

#### 13.1: Extract Shared JSON Deserialization in EventStore

**Current:**
```python
# In get_events, get_events_for_agent, get_latest_event_by_type, get_events_after
result["tags"] = json.loads(result.get("tags") or "[]")
result["payload"] = json.loads(result["payload"])
```

**Proposed:** Extract to `_deserialize_row()`.

**Verdict:** ✅ **RECOMMEND** — Standard DRY improvement.

---

#### 13.2: DRY the Language Plugin Classes

**Current:** `PythonPlugin` and `GenericLanguagePlugin` share 90% code.

**Proposed:** Extract `BaseLanguagePlugin`.

**Verdict:** ✅ **RECOMMEND** — Standard inheritance refactor.

---

#### 13.3: Replace FIFO Script Cache with `functools.lru_cache`

**Current:**
```python
_PARSED_SCRIPT_CACHE: dict[str, Any] = {}
# Manual FIFO eviction logic
```

**Proposed:** Use `@functools.lru_cache(maxsize=256)`.

**Concern:** The current implementation uses content hash as key:
```python
content_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
cached = _PARSED_SCRIPT_CACHE.get(content_hash)
```

With `lru_cache`, the cache key would need to include both path and content hash. The proposed signature:
```python
@functools.lru_cache(maxsize=256)
def _parse_script(script_path: str, content_hash: str) -> ParsedScript:
```

This works, but callers must compute the hash before calling.

**Verdict:** ✅ **RECOMMEND** — But ensure hash computation is done correctly.

---

#### 13.4: Add Input Length Limits to Web Endpoints

**Proposed:**
```python
MAX_MESSAGE_LENGTH = 100_000  # 100KB

if len(message) > MAX_MESSAGE_LENGTH:
    return JSONResponse({"error": "message too long"}, status_code=413)
```

**Verdict:** ✅ **STRONGLY RECOMMEND** — Basic security measure.

---

#### 13.5: Fix `RegisterSubscriptionsFn` to Be a `Protocol`

**Current:** Type alias or unclear type.

**Proposed:**
```python
class RegisterSubscriptionsFn(Protocol):
    async def __call__(
        self,
        node: Node,
        *,
        virtual_subscriptions: tuple[SubscriptionPattern, ...] = (),
    ) -> None: ...
```

**Verdict:** ✅ **RECOMMEND** — Proper typing for callable.

---

#### 13.6: Remove Vestigial `db.py` Module

**Current:** `core/storage/db.py` is 21 lines — type alias and `open_database` function.

**Proposed:** Inline into `lifecycle.py`, delete the module.

**Verdict:** ⚠️ **CONDITIONAL** — Only if `db.py` is truly single-use. If other modules import from it, keep it.

---

#### 13.7: Make `_deps_from_request` and `_get_chat_limiter` Public

**Current:** Leading underscore indicates "private".

**Proposed:** Rename to `deps_from_request` and `get_chat_limiter`.

**Verdict:** ✅ **RECOMMEND** — These are clearly public APIs used across modules.

---

#### 13.8: Add Pagination to `/api/nodes`

**Proposed:**
```python
limit = min(500, max(1, int(request.query_params.get("limit", "100"))))
offset = max(0, int(request.query_params.get("offset", "0")))
nodes = await deps.node_store.list_nodes(limit=limit, offset=offset)
```

**Verdict:** ✅ **RECOMMEND** — Standard API feature.

---

#### 13.9: Replace `snapshot()` Manual Field Listing with `dataclasses.asdict()`

**Current:** Manual field listing.

**Proposed:** Use `dataclasses.asdict(self)` with post-processing.

**Verdict:** ✅ **RECOMMEND** — Simpler and less error-prone.

---

#### 13.10: Fix `get_events_after` Parameter Type

**Current:** `after_id: str` with internal `int()` conversion.

**Proposed:** Change to `after_id: int`.

**Coordinate with:** Phase 10 (SSE Event IDs).

**Verdict:** ✅ **RECOMMEND** — Type should match usage.

---

#### 13.11: Verify

Standard test/lint run.

---

## Phase 14: Polish Batch

### 14.1 Overview

9 smaller quality-of-life improvements.

### 14.2 Analysis of Each Item

#### 14.1: Add IPv6 Loopback to CSRF Middleware

**Proposed:** Add `"::1"` to allowed hosts.

**Verdict:** ✅ **RECOMMEND** — Correct for IPv6 support.

---

#### 14.2: Add `agent_id` Public Property to `AgentWorkspace`

**Proposed:**
```python
@property
def agent_id(self) -> str:
    return self._agent_id
```

**Verdict:** ✅ **RECOMMEND** — Encapsulates private attribute access.

---

#### 14.3: Make Trigger Policy Constants Configurable

**Proposed:** Move `_DEPTH_TTL_MS` and `_DEPTH_CLEANUP_INTERVAL` to `RuntimeConfig`.

**Verdict:** ⚠️ **EVALUATE** — Only if runtime tuning is needed. If these are truly constants, hardcoding is fine.

---

#### 14.4: Log Truncation Indicator in API Responses

**Proposed:** Add `"truncated": true` when content is truncated.

**Verdict:** ✅ **RECOMMEND** — Helpful for API consumers.

---

#### 14.5: Cache Config File Discovery

**Proposed:** Cache `_find_config_file()` result.

**Verdict:** ✅ **RECOMMEND** — Avoids repeated filesystem walks.

---

#### 14.6: `OutboxObserver` Dispatch Table

**Current:** `isinstance` chain for event translation.

**Proposed:** Dispatch dict mapping types to translator functions.

**Verdict:** ✅ **RECOMMEND** — More maintainable and extensible.

---

#### 14.7: Rename `_collect_changed_files`

**Proposed:** Rename to `_list_non_bundle_files`.

**Verdict:** ✅ **RECOMMEND** — Clearer name.

---

#### 14.8: Remove `serialize_enum` If Unnecessary

**Current:** `serialize_enum(value)` does `value.value if isinstance(value, StrEnum) else str(value)`.

**Analysis:** With `StrEnum`, `str(value)` already returns the value. The function may be unnecessary.

**Verdict:** ⚠️ **AUDIT FIRST** — Check all call sites before removing.

---

## Phase 15: Final Cleanup Sweep

### 15.1 Overview

Last pass to remove leftover artifacts.

### 15.2 Analysis

All items are standard cleanup procedures:

1. **15.1 Dead Code Scan:** Use ruff F401, F841, F811
2. **15.2 Remove Stale `# noqa` Comments:** Search and remove
3. **15.3 Remove Empty/Single-Use Modules:** Inline if appropriate
4. **15.4 Verify Re-exports Are Clean:** Audit `__init__.py` files
5. **15.5 Verify `__all__` Lists Are Correct:** No private names in exports
6. **15.6 Final Full Verification:** Run tests, lint, smoke test

**Verdict:** ✅ **STANDARD FINAL PHASE** — Execute after all other phases complete.
