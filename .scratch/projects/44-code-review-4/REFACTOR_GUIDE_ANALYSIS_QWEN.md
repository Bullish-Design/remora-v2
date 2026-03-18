# Refactoring Guide Analysis — Phases 6, 8-10

**Date:** 2026-03-18  
**Analyst:** Qwen  
**Source:** `.scratch/projects/44-code-review-4/REVIEW_REFACTOR_GUIDE.md`  
**Status:** Analysis Complete

---

## Executive Summary

This analysis examines **Phases 6, 8, 9, and 10** of the refactoring guide, evaluating the technical merit, implementation strategy, and potential risks of each recommendation. 

**Key Findings:**
- ✅ **Phase 6 (RoutingEnvelope):** Sound design, but implementation complexity is understated
- ✅ **Phase 8 (Immutable Node):** Correct approach, well-scoped
- ✅ **Phase 9 (Atomic Writes):** Essential fix, minimal risk
- ⚠️ **Phase 10 (SSE Event IDs):** Good intent, but has a critical flaw in the proposed solution

---

## Phase 6: Type-Safe Subscription Matching (RoutingEnvelope)

### Current State Analysis

**Problem:** The `SubscriptionPattern.matches()` method uses unsafe `getattr()` probing:

```python
# Current implementation (subscriptions.py:26-58)
def matches(self, event: Event) -> bool:
    if self.from_agents:
        from_agent = getattr(event, "from_agent", None)  # ❌ Unsafe
        agent_id = getattr(event, "agent_id", None)      # ❌ Unsafe
        if from_agent not in self.from_agents and agent_id not in self.from_agents:
            return False
    
    if self.path_glob:
        path = getattr(event, "path", None) or getattr(event, "file_path", None)  # ❌ Unsafe
        if path is None or not PurePath(path).match(self.path_glob):
            return False
```

**Risks:**
1. **Silent breakage:** Renaming `file_path` → `source_path` breaks matching silently
2. **Type unsafety:** No guarantee probed attributes exist
3. **Inconsistent probing:** Different code paths might probe different attributes
4. **Maintenance burden:** Every new event field requires updating multiple probe sites

### Proposed Solution Review

The guide proposes a `RoutingEnvelope` dataclass that every event provides:

```python
@dataclass(frozen=True, slots=True)
class RoutingEnvelope:
    """Stable routing attributes that every event provides."""
    event_type: str
    agent_id: str | None = None
    from_agent: str | None = None
    to_agent: str | None = None
    path: str | None = None
    tags: tuple[str, ...] = ()
```

**Implementation approach:**
1. Base `Event` class provides default `routing_envelope()` method
2. Subclasses override to expose their specific fields
3. `SubscriptionPattern.matches()` uses the envelope instead of `getattr()`

### Technical Assessment

#### ✅ Strengths

1. **Type Safety:** Envelope is a typed dataclass — mypy can verify field access
2. **Stable Contract:** Field renames in events don't break matching if `routing_envelope()` mapping is updated
3. **Explicit Mapping:** Each event explicitly declares its routing-relevant fields
4. **No Runtime Overhead:** `getattr()` calls replaced with direct attribute access

#### ⚠️ Concerns

1. **Boilerplate Explosion:**
   - ~15 event types in `types.py`
   - Each needs `routing_envelope()` override
   - Risk of copy-paste errors

2. **Frozen Dataclass Limitation:**
   - Guide specifies `frozen=True` but includes mutable `tags: tuple[str, ...]`
   - Tuples are immutable, so this is actually fine
   - However, `slots=True` with frozen requires Python 3.10+

3. **Inheritance Not Exploited:**
   - Events like `NodeChangedEvent` have `file_path`, but envelope uses `path`
   - Each override must manually map `self.file_path → path`
   - Could use inheritance to reduce duplication

4. **Incomplete Coverage:**
   - Guide only shows 4 event examples
   - Remaining 11+ event types need manual review
   - Some events may not fit the envelope pattern cleanly

#### 🔍 Deeper Issue: Is `getattr()` Actually Bad Here?

The guide claims `getattr()` is unsafe, but consider:

```python
# Current approach
path = getattr(event, "path", None) or getattr(event, "file_path", None)

# Proposed approach
env = event.routing_envelope()
path = env.path
```

**Both approaches handle missing fields gracefully** — `getattr()` returns `None`, envelope has `path=None` by default.

**The real win is not safety, but *explicitness*:**
- Current: Implicit contract — "events might have these fields"
- Envelope: Explicit contract — "here are the exact fields this event exposes for routing"

### Recommendation

**✅ APPROVE with modifications:**

1. **Add base class helper to reduce boilerplate:**
```python
class Event(BaseModel):
    def routing_envelope(self) -> RoutingEnvelope:
        """Default: only event_type and tags."""
        return RoutingEnvelope(
            event_type=self.event_type,
            tags=self.tags,
        )
    
    def _envelope_with_kwargs(self, **overrides) -> RoutingEnvelope:
        """Helper for subclasses to build envelope with overrides."""
        base = self.routing_envelope()
        return RoutingEnvelope(**{**base.__dict__, **overrides})
```

2. **Document which events need overrides:**
   - Events with `agent_id`, `from_agent`, `to_agent`, `path`, `file_path` fields
   - Events without these can use base class default

3. **Add tests for envelope consistency:**
   - Verify all event types have `routing_envelope()` method
   - Verify envelope fields match actual event fields

---

## Phase 8: Make Node Immutable

### Current State Analysis

**Problem:** `Node` is mutable (`frozen=False`), allowing in-place mutations:

```python
# Current (node.py:15)
class Node(BaseModel):
    model_config = ConfigDict(frozen=False)  # ❌ Mutable
```

**Mutation sites** (from reconciler.py):
```python
# Before
node.status = existing.status if existing is not None else NodeStatus.IDLE
node.role = mapped_bundle if mapped_bundle is not None else (existing.role if existing is not None else None)
```

**Risks:**
1. **Untracked Changes:** Mutating a node doesn't trigger re-persistence
2. **Hash Invalidation:** If `Node` is ever hashed, mutations break hash invariants
3. **Concurrency Hazards:** Multiple actors holding same node reference see inconsistent state
4. **Pydantic Semantics:** Defeats Pydantic's value object model

### Proposed Solution Review

**Approach:** Set `frozen=True` and use `model_copy()` for mutations:

```python
# After
class Node(BaseModel):
    model_config = ConfigDict(frozen=True)  # ✅ Immutable

# Mutation sites become:
node = node.model_copy(update={
    "status": existing.status if existing is not None else NodeStatus.IDLE,
    "role": mapped_bundle if mapped_bundle is not None else (existing.role if existing is not None else None),
})
```

### Technical Assessment

#### ✅ Strengths

1. **Correct by Construction:** Frozen models prevent accidental mutation
2. **Clear Intent:** `model_copy(update={...})` makes state changes explicit
3. **Pydantic Best Practice:** Aligns with Pydantic's value object design
4. **Test-Friendly:** Tests can rely on node immutability

#### ⚠️ Concerns

1. **Performance Overhead:**
   - `model_copy()` creates a new object (shallow copy)
   - For large nodes with many fields, this could be noticeable
   - However, `Node` is relatively small (~10 fields), so impact is minimal

2. **Migration Path:**
   - Guide suggests "let tests fail" approach
   - Better to identify all mutation sites upfront with grep:
   ```bash
   rg "node\.(status|role|parent_id)\s*=" src/
   ```

3. **Potential Gotcha:**
   - `model_copy()` is shallow — nested mutable objects (if any) would still be mutable
   - `Node` has no nested mutable objects, so this is fine

### Recommendation

**✅ APPROVE as written:**

This is a straightforward, well-scoped change. The guide's approach of "freeze and let tests find breakage" is appropriate here because:
- Compile-time checks (mypy) will catch many issues
- Runtime errors (AttributeError) will catch the rest
- Tests provide final verification

**Additional suggestion:**
- Add a comment explaining *why* Node is frozen (link to this analysis)
- Consider adding a `__init_subclass__` hook to prevent unfrozen subclasses

---

## Phase 9: Atomic File Writes for Proposal Accept

### Current State Analysis

**Problem:** `api_proposal_accept` uses non-atomic writes:

```python
# Current (proposals.py)
disk_path.write_bytes(new_bytes)  # ❌ Not atomic
```

**Risks:**
1. **Data Corruption:** Power loss mid-write corrupts file
2. **Partial Writes:** Disk-full condition leaves file in inconsistent state
3. **No Rollback:** If write fails, original file is lost

### Proposed Solution Review

**Approach:** Write to temp file, fsync, then atomic rename:

```python
def atomic_write(path: Path, content: bytes) -> None:
    """Write content atomically using temp-file + rename."""
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        os.write(fd, content)
        os.fsync(fd)  # ✅ Ensure data hits disk
        os.close(fd)
        os.replace(tmp_path, path)  # ✅ Atomic on POSIX
    except BaseException:
        os.close(fd)
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)  # ✅ Cleanup on failure
        raise
```

### Technical Assessment

#### ✅ Strengths

1. **POSIX Guarantee:** `os.replace()` is atomic on POSIX systems
2. **fsync() Call:** Ensures data is actually on disk before rename
3. **Exception Safety:** Temp file cleaned up on failure
4. **Minimal Code:** ~20 lines, easy to review and test

#### ⚠️ Concerns

1. **Windows Compatibility:**
   - `os.replace()` is atomic on Windows since Python 3.3
   - However, Windows antivirus can interfere with temp files
   - **Mitigation:** Document that atomic writes require POSIX or Windows 10+

2. **File Permissions:**
   - Temp file created with default permissions (usually 0600)
   - `os.replace()` preserves permissions of target, not temp
   - If original file had special permissions, they're lost
   - **Mitigation:** Check if permissions matter for proposal files (likely not)

3. **Directory Permissions:**
   - Guide suggests `disk_path.parent.mkdir(parents=True, exist_ok=True)`
   - This could fail if parent directory is read-only
   - **Mitigation:** Accept `OSError` and let caller handle

### Recommendation

**✅ APPROVE with minor modifications:**

```python
def atomic_write(path: Path, content: bytes) -> None:
    """Write content atomically using temp-file + rename.
    
    Guarantees:
    - File is either fully written or untouched (atomic rename)
    - Data is flushed to disk before rename (fsync)
    - Temp file cleaned up on failure
    
    Note: Requires POSIX or Windows 10+ for atomic guarantee.
    """
    import contextlib
    import tempfile
    
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        os.write(fd, content)
        os.fsync(fd)
        os.close(fd)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass  # Ignore close errors during exception handling
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise
```

---

## Phase 10: Use Database Row IDs for SSE Event IDs

### Current State Analysis

**Problem:** SSE uses `event.timestamp` as event ID:

```python
# Current (sse.py)
yield f"id: {event.timestamp}\nevent: {event.event_type}\ndata: {payload}\n\n"
```

**Risks:**
1. **Non-Unique IDs:** Two events in same millisecond get same ID
2. **SSE Reconnection Issues:** `Last-Event-ID` header would skip duplicate-timestamp events
3. **Float Precision:** Timestamps are floats, not ideal for ID comparison

### Proposed Solution Review

**Approach:** Add `event_id: int | None` field to `Event` base class:

```python
# Proposed (types.py)
class Event(BaseModel):
    event_type: str = ""
    event_id: int | None = None  # ← Added
    timestamp: float = Field(default_factory=time.time)
    correlation_id: str | None = None
    tags: tuple[str, ...] = ()

# Proposed (store.py)
async def append(self, event: Event) -> int:
    # ... INSERT ...
    event_id = int(cursor.lastrowid)
    event.event_id = event_id  # ← Stamp it
    # ... emit to bus ...
```

### Technical Assessment

#### ✅ Strengths

1. **Unique IDs:** Database row IDs are guaranteed unique
2. **SSE Compliance:** Proper event ID format for reconnection
3. **Backward Compatible:** `event_id` is optional (`None` for in-memory events)

#### ❌ CRITICAL FLAW: Mutating Immutable Event Objects

**The guide contradicts itself:**

Phase 8 says: "Make `Node` immutable with `frozen=True`"
Phase 10 says: "Set `event.event_id = event_id` after DB insert"

**Problem:** If `Event` inherits from `Node` or any frozen model, this mutation will fail:

```python
class Event(BaseModel):
    # If this has frozen=True (from Phase 8 inheritance or explicit config):
    model_config = ConfigDict(frozen=True)  # ← From Phase 8
    
    event_id: int | None = None
    
# In store.py:
event.event_id = event_id  # ❌ AttributeError: "Event" is frozen
```

**Current state:** `Event` is NOT frozen (as of analysis date), so Phase 10 works today. But if Phase 8's philosophy extends to `Event`, this breaks.

#### ⚠️ Additional Concerns

1. **Ordering Assumption:**
   - Guide assumes DB row ID == event ordering
   - True for single-writer SQLite, but not guaranteed in all databases
   - **Mitigation:** Document assumption

2. **Replay vs. Live Events:**
   - Replay events from DB have `event_id` set
   - Live events get `event_id` stamped in `append()`
   - What about events that bypass `EventStore` (e.g., in-memory only)?
   - **Mitigation:** Keep `event_id` optional, use timestamp as fallback

3. **Threading Issue:**
   - Multiple concurrent appends could stamp events with wrong IDs
   - SQLite serializes writes, so this is fine in practice
   - **Mitigation:** Ensure `append()` is called within transaction context

### Recommendation

**⚠️ CONDITIONAL APPROVE — requires fixes:**

1. **Fix the mutation issue:**
   - Option A: Keep `Event` unfrozen (document why)
   - Option B: Use `model_copy()` like Phase 8:
   ```python
   event = event.model_copy(update={"event_id": event_id})
   ```
   - Option C: Make `event_id` settable via a separate mechanism (e.g., `with_event_id()`)

2. **Clarify the design:**
   - When is `event_id` None? (in-memory events, test fixtures)
   - What's the fallback for SSE? (use `timestamp` if `event_id` is None)

3. **Add tests for:**
   - Duplicate timestamp handling
   - SSE reconnection with `Last-Event-ID`
   - Concurrent event appends

**Recommended implementation:**

```python
# types.py
class Event(BaseModel):
    event_type: str = ""
    event_id: int | None = None
    timestamp: float = Field(default_factory=time.time)
    correlation_id: str | None = None
    tags: tuple[str, ...] = ()
    
    def with_event_id(self, event_id: int) -> "Event":
        """Return a copy of this event with the given event_id."""
        return self.model_copy(update={"event_id": event_id})

# store.py
async def append(self, event: Event) -> int:
    # ... INSERT ...
    event_id = int(cursor.lastrowid)
    event = event.with_event_id(event_id)  # ✅ Immutable update
    # ... emit ...
    return event_id

# sse.py
sse_id = event.event_id if event.event_id is not None else event.timestamp
```

---

## Cross-Phase Analysis

### Dependencies Between Phases

```\nPhase 6 (RoutingEnvelope)\n    ↓ (uses Event fields)\nPhase 8 (Immutable Node) ← Independent\n    ↓ (Event mutability affects)\nPhase 10 (SSE Event IDs) ← CONFLICT: Phase 10 assumes mutable Event\n```\n\n**Conflict Resolution:**
- Phase 8's immutability should apply to `Event` as well
- Phase 10 must be updated to use `model_copy()` or `with_event_id()` helper

### Shared Patterns

All four phases follow a consistent pattern:

1. **Identify implicit contract** (getattr probing, mutable state, non-atomic writes, timestamp IDs)
2. **Make contract explicit** (RoutingEnvelope, frozen=True, atomic_write, event_id field)
3. **Enforce at type level** (type hints, frozen models, atomic primitives, int IDs)

This is excellent architectural thinking — moving from implicit/fragile to explicit/robust.

---

## Summary Table

| Phase | Status | Complexity | Risk | Priority |\n|-------|--------|------------|------|----------|\n| 6. RoutingEnvelope | ✅ Approve (with helpers) | Medium | Low | High |\n| 8. Immutable Node | ✅ Approve | Low | Low | Medium |\n| 9. Atomic Writes | ✅ Approve | Low | Low | High |\n| 10. SSE Event IDs | ⚠️ Conditional | Medium | Medium | Medium |\n\n**Recommended Order:**
1. Phase 9 (Atomic Writes) — Independent, quick win
2. Phase 8 (Immutable Node) — Foundation for Event immutability
3. Phase 10 (SSE Event IDs) — Depends on Event mutability decision
4. Phase 6 (RoutingEnvelope) — Most complex, depends on Event structure

---

**Analysis completed:** 2026-03-18  
**Next Steps:** Implement in order above, starting with Phase 9

---

# Additional Phases Analysis (7, 11-15)

**Date Added:** 2026-03-18  
**Analyst:** Qwen

---

## Phase 7: Namespace Capability Functions

### Current State Analysis

**Problem:** `TurnContext.to_capabilities_dict()` merges capability groups into a flat dict:

```python
# Current (simplified)
def to_capabilities_dict(self) -> dict[str, Any]:
    return {
        **self.files.to_dict(),      # read_file, write_file, ...
        **self.graph.to_dict(),      # get_node, set_status, ...
        **self.kv.to_dict(),         # kv_get, kv_set, ...
        ...
    }
```

**Claimed Risk:** "If two groups define a function with the same name, the last one wins silently."

### Technical Assessment

#### ❌ CRITICAL FLAW: Solution Breaks Grail Integration

The guide proposes:
```python
# In .pym script:
result = await files.read_file(path)

# In grail.py exec context:
exec_globals = {
    "files": context.files,
    "graph": context.graph,
    ...
}
```

**This fundamentally breaks Grail's `@external` model:**

1. **Grail expects externals as functions, not objects:**
   ```python
   # Grail's model (from SPEC.md):
   @external
   async def read_file(path: str) -> str: ...
   
   # Host provides:
   externals = {"read_file": file_caps.read_file}
   ```

2. **Cannot inject namespace objects:**
   - Grail's `run()` accepts `externals: dict[str, Callable]`
   - There's no mechanism to inject `files`, `graph` as objects
   - The `.pym` scripts see externals as a flat dict of callables

3. **Dotted function names are invalid Python:**
   ```python
   @external
   async def files.read_file(path: str) -> str: ...  # ❌ SyntaxError!
   ```

#### ✅ What Actually Works

The current flat structure is **correct for Grail**:
```python
# Current (works):
externals = {
    "read_file": file_caps.read_file,
    "write_file": file_caps.write_file,
    "graph_get_node": graph_caps.get_node,  # ← Prefix, don't namespace
}

# In .pym script:
content = await read_file(path)
node = await graph_get_node(node_id)
```

### Recommendation

**❌ REJECT as written — fundamental incompatibility with Grail.**

**Alternative approach (if naming conflicts exist):**
- Use prefix naming: `graph_get_node`, `kv_get`, `files_read_file`
- This maintains Grail compatibility while avoiding collisions

**However:** The claimed problem (naming conflicts) should be verified empirically before solving. Current codebase shows no conflicts.

---

## Phase 11: Split SearchService into Strategy Implementations

### Current State Analysis

**Problem:** `SearchService` has conditional branching:
```python
class SearchService:
    async def search(self, query, ...):
        if self._client:  # Remote mode
            result = await self._client.search(...)
        elif self._pipeline:  # Local mode
            result = await self._pipeline.search(...)
        else:
            return []
```

**Claimed Issue:** "Two implementations of `SearchServiceProtocol` eliminates branching."

### Technical Assessment

#### ✅ Strengths of Proposed Approach

1. **Cleaner Separation:**
   - `RemoteSearchService`: Only knows about remote embeddy client
   - `LocalSearchService`: Only knows about local embeddy pipeline
   - No conditional logic in individual methods

2. **Better Testability:**
   - Can test remote and local implementations independently
   - No need to mock both code paths

3. **Follows Strategy Pattern:**
   - Protocol defines interface
   - Concrete implementations for each strategy
   - Factory function for creation

#### ⚠️ Concerns

1. **Code Duplication Risk:**
   - Both implementations need `search()`, `find_similar()`, `index_file()`, `delete_source()`
   - Some logic (e.g., `collection_for_file`) might duplicate

2. **Complexity vs. Benefit:**
   - Current branching is simple (`if self._client ... elif self._pipeline`)
   - Refactoring adds 2 classes + factory
   - Benefit is marginal unless logic is complex

3. **Configuration Coupling:**
   - Both implementations still need `SearchConfig`
   - Factory must know about config.mode
   - Not much simpler than original

### Recommendation

**⚠️ CONDITIONAL APPROVE — verify complexity first.**

**Approve if:**
- Search logic is genuinely complex (multiple conditionals per method)
- Remote and local have significantly different implementations
- Tests are hard to write due to branching

**Reject if:**
- Branching is simple (`if self._client` / `elif self._pipeline`)
- Most methods just delegate to underlying embeddy objects
- Refactoring adds more code than it removes

**Suggested approach:**
1. Measure current complexity (lines with conditionals)
2. If <5 conditionals total, keep as-is (YAGNI)
3. If >5, refactor with strategy pattern

---

## Phase 12: Decompose FileReconciler

### Current State Analysis

**Problem:** `FileReconciler` is 414 lines with multiple responsibilities:
- File watching
- Node CRUD operations
- Bundle provisioning
- Search indexing
- Subscription management
- Directory management
- Virtual agent management

**Current structure:**
```python
class FileReconciler:
    def __init__(self, ...):
        self._watcher = FileWatcher(...)
        self._directory_manager = DirectoryManager(...)
        self._virtual_agent_manager = VirtualAgentManager(...)
        # But owns all reconciliation logic
    
    async def reconcile_cycle(self):
        # 100+ lines mixing orchestration + node logic
```

### Technical Assessment

#### ✅ Strengths of Proposed Decomposition

1. **Clear SRP Boundaries:**
   - `BundleProvisioner`: Bundle template resolution and provisioning
   - `SearchIndexer`: Search index updates
   - `NodeReconciler`: Node discovery, upsert, event emission
   - `FileReconciler`: Orchestration only

2. **Easier Testing:**
   - Test `NodeReconciler` without file watching
   - Test `BundleProvisioner` without database
   - Mock fewer dependencies per class

3. **Reduced Cognitive Load:**
   - Each class is <150 lines
   - Dependencies are explicit in constructor
   - Easier to understand in isolation

#### ⚠️ Concerns

1. **Dependency Injection Complexity:**
   - `NodeReconciler` needs 9 dependencies
   - Constructor signature is unwieldy
   - Risk of "parameter soup"

2. **Circular Dependencies:**
   - `FileReconciler` creates `NodeReconciler`
   - `NodeReconciler` calls back to `FileReconciler` methods?
   - Need to verify no cycles

3. **Orchestration Logic Still Complex:**
   - `reconcile_cycle()` remains ~50 lines
   - Still need to understand full flow
   - Decomposition helps, but doesn't eliminate complexity

### Recommendation

**✅ APPROVE with modifications:**

1. **Use Builder Pattern for NodeReconciler:**
```python
class NodeReconcilerBuilder:
    def __init__(self, config, node_store, event_store):
        self._config = config
        self._node_store = node_store
        self._event_store = event_store
        # ... accumulate deps
    
    def with_subscription_manager(self, manager):
        self._subscription_manager = manager
        return self
    
    def build(self) -> NodeReconciler:
        return NodeReconciler(...)
```

2. **Keep orchestration logic minimal:**
   - `FileReconciler.reconcile_cycle()` should delegate, not orchestrate
   - Consider `ReconciliationCycle` class if logic grows

3. **Document dependencies clearly:**
   - Add type hints
   - Document why each dep is needed
   - Consider grouping related deps (e.g., stores)

---

## Phase 13: Code Quality Batch

### 13.1 Extract Shared JSON Deserialization in EventStore

**Assessment:** ✅ **APPROVE** - Straightforward DRY improvement.

```python
# Current: Repeated in 4 methods
result = dict(row)
result["tags"] = json.loads(result.get("tags") or "[]")
result["payload"] = json.loads(result["payload"])

# Proposed:
def _deserialize_row(self, row: aiosqlite.Row) -> dict[str, Any]:
    result = dict(row)
    result["tags"] = json.loads(result.get("tags") or "[]")
    result["payload"] = json.loads(result["payload"])
    return result
```

**Impact:** Low risk, high clarity.

---

### 13.2 DRY the Language Plugin Classes

**Assessment:** ✅ **APPROVE** - Standard inheritance pattern.

```python
# Current: PythonPlugin and GenericLanguagePlugin share 90% code
# Proposed: Extract BaseLanguagePlugin

class BaseLanguagePlugin:
    def __init__(self, language: str, query: str, query_paths: list[Path]):
        self._language = language
        self._query = query
        self._query_paths = query_paths
    
    # Shared implementation
```

**Impact:** Reduces duplication, makes differences clearer.

---

## Phase 14: Polish Batch

*(Details not shown in guide excerpt — likely UI/UX improvements, logging enhancements, etc.)*

**Assessment:** Cannot assess without details.

---

## Phase 15: Final Cleanup Sweep

*(Details not shown in guide excerpt — likely removing dead code, updating docs, etc.)*

**Assessment:** Cannot assess without details.

---

## Cross-Phase Dependency Graph

```
Phase 6 (RoutingEnvelope)
    ↓ (Event structure)
Phase 10 (SSE Event IDs) ← Must use frozen-safe update
    ↓
Phase 8 (Immutable Node) ← Independent
    ↓
Phase 9 (Atomic Writes) ← Independent, quick win

Phase 7 (Capability Namespacing) ← REJECTED - breaks Grail
    └─> Alternative: Prefix naming if needed

Phase 11 (Search Strategy) ← Conditional - verify complexity
    ↓
Phase 12 (Decompose Reconciler) ← Can proceed independently
    ↓
Phase 13 (Code Quality) ← Independent improvements
```

---

## Revised Priority Order

**Tier 1 (Immediate - Independent, Low Risk):**
1. Phase 9: Atomic File Writes
2. Phase 13.1: Extract JSON Deserialization
3. Phase 13.2: DRY Language Plugins

**Tier 2 (Medium - Requires Coordination):**
4. Phase 8: Immutable Node
5. Phase 10: SSE Event IDs (after Phase 8, with frozen-safe update)
6. Phase 6: RoutingEnvelope (depends on Event structure)

**Tier 3 (Conditional - Verify Before Proceeding):**
7. Phase 11: Search Strategy (verify complexity)
8. Phase 12: Decompose Reconciler (can proceed independently)

**Rejected:**
- ❌ Phase 7: Capability Namespacing (breaks Grail)

**Unknown:**
- Phase 14, 15 (details not provided)

---

## Summary Table (All Phases)

| Phase | Status | Complexity | Risk | Priority |
|-------|--------|------------|------|----------|
| 6. RoutingEnvelope | ✅ Approve (with helpers) | Medium | Low | Medium |
| 7. Capability Namespace | ❌ Reject | Low | **High** | N/A |
| 8. Immutable Node | ✅ Approve | Low | Low | Medium |
| 9. Atomic Writes | ✅ Approve | Low | Low | **High** |
| 10. SSE Event IDs | ⚠️ Conditional | Medium | Medium | Medium |
| 11. Search Strategy | ⚠️ Conditional | Medium | Low | Low |
| 12. Decompose Reconciler | ✅ Approve (with builder) | High | Medium | Low |
| 13.1 JSON Deserialization | ✅ Approve | Low | Low | **High** |
| 13.2 Language Plugin DRY | ✅ Approve | Low | Low | **High** |

---

**Analysis completed:** 2026-03-18  
**Full document:** `.scratch/projects/46-refactor-guide-analysis/REFACTOR_GUIDE_ANALYSIS_QWEN.md`

---

# Appendix: Phase 11 Deep Dive — Embeddy Integration Analysis

**Date Added:** 2026-03-18  
**Analyst:** Qwen

## Objective

Determine whether splitting `SearchService` into `RemoteSearchService` and `LocalSearchService` is worthwhile, given deep understanding of embeddy library architecture.

---

## Current Architecture Analysis

### Remora's SearchService Structure

The current `SearchService` in remora-v2 acts as a **facade** over two embeddy backends:

```python
class SearchService:
    def __init__(self, config, project_root):
        self._client: Any = None      # Remote: embeddy.client.EmbeddyClient
        self._pipeline: Any = None    # Local: embeddy.Pipeline
        self._search_svc: Any = None  # Local: embeddy.search.SearchService
        self._store: Any = None       # Local: embeddy.store.VectorStore
```

**Initialization flow:**
1. If `config.mode == "remote"`: Initialize `EmbeddyClient(base_url)`
2. Else: Initialize local embeddy components (`Embedder`, `VectorStore`, `Pipeline`, `SearchService`)

**Method branching pattern:**
```python
async def search(self, query, ...):
    if not self._available:
        return []
    
    if self._client is not None:  # Remote path
        result = await self._client.search(...)
        return result.get("results", [])
    
    if self._search_svc is not None:  # Local path
        results = await self._search_svc.search(...)
        return [transform(item) for item in results.results]
    
    return []
```

### Embeddy Library Architecture

#### Remote Backend (`embeddy.client.EmbeddyClient`)

**Location:** `.context/embeddy/src/embeddy/client/client.py`

```python
class EmbeddyClient:
    """HTTP client for embeddy REST API."""
    
    async def search(self, query, collection, top_k=10, mode="hybrid") -> dict:
        # HTTP POST to /api/v1/search
        # Returns {"results": [...], "query": ..., "elapsed_ms": ...}
    
    async def find_similar(self, chunk_id, collection, top_k=10) -> dict:
        # HTTP GET to /api/v1/search/similar/{chunk_id}
    
    async def reindex(self, path, collection) -> None:
        # HTTP POST to /api/v1/ingest/reindex
    
    async def delete_source(self, path, collection) -> None:
        # HTTP DELETE to /api/v1/chunks/source/{source_path}
```

**Characteristics:**
- Thin HTTP wrapper around remote server
- Returns raw JSON dicts
- No business logic, just serialization

#### Local Backend (`embeddy.search.SearchService` + `embeddy.pipeline.Pipeline`)

**Search Service Location:** `.context/embeddy/src/embeddy/search/search_service.py`

```python
class SearchService:
    """Async-native search composing embedder + store."""
    
    def __init__(self, embedder: Embedder, store: VectorStore):
        self._embedder = embedder
        self._store = store
    
    async def search(self, query, collection, top_k=10, mode=SearchMode.HYBRID):
        # Complex logic: encodes query, performs KNN/FTS search, fuses results
        # 150+ lines of fusion logic, score normalization, deduplication
```

**Pipeline Location:** `.context/embeddy/src/embeddy/pipeline/pipeline.py`

```python
class Pipeline:
    """Orchestrates ingest -> chunk -> embed -> store."""
    
    def __init__(self, embedder, store, collection, chunk_config):
        self._embedder = embedder
        self._store = store
        self._ingestor = Ingestor()
    
    async def reindex_file(self, path) -> IngestStats:
        # Complex multi-step ingestion with chunking, embedding, storing
    
    async def delete_source(self, path) -> None:
        # Delete chunks by source path
```

**Characteristics:**
- Heavy business logic (embedding, chunking, fusion algorithms)
- Direct database access (SQLite via `VectorStore`)
- Complex initialization (requires `Embedder`, `VectorStore`, `Pipeline`, `SearchService`)

---

## Branching Complexity Assessment

### Current Branching Points in remora-v2 `SearchService`

| Method | Lines | Branching Logic |
|--------|-------|-----------------|
| `initialize()` | 77 | `if mode == "remote"` (40 lines) + local init (37 lines) |
| `search()` | 37 | `if _client` / `if _search_svc` (15 lines) |
| `find_similar()` | 32 | `if _client` / `if _search_svc` (15 lines) |
| `index_file()` | 11 | `if _client` / `if _pipeline` (7 lines) |
| `delete_source()` | 11 | `if _client` / `if _pipeline` (7 lines) |
| `index_directory()` | 26 | `if _client` / `if _pipeline` (15 lines) |

**Total conditional lines:** ~59 lines of branching logic

### Embeddy Internal Complexity

**Remote client methods:** Simple HTTP wrappers (5-10 lines each)
- No internal branching
- Just serialize/deserialize

**Local search service methods:** Complex business logic (50-150 lines each)
- `search()`: 150+ lines including fusion strategies
- `find_similar()`: 70+ lines
- Multiple helper methods for RRF, weighted fusion

**Key insight:** The branching in remora is **not** complex — it's just:
```python
if self._client:
    return await self._client.method(...)
if self._search_svc:
    result = await self._search_svc.method(...)
    return [transform(item) for item in result]
```

The **complexity is in embeddy**, not in remora's branching.

---

## Strategy Pattern Analysis

### Guide's Proposed Split

```python
class RemoteSearchService:
    def __init__(self, config):
        self._client = EmbeddyClient(...)
    
    async def search(self, ...):
        result = await self._client.search(...)
        return result.get("results", [])

class LocalSearchService:
    def __init__(self, config, project_root):
        self._pipeline = Pipeline(...)
        self._search_svc = SearchService(...)
    
    async def search(self, ...):
        results = await self._search_svc.search(...)
        return [transform(item) for item in results.results]
```

### Benefits of Splitting

1. **Eliminates 59 lines of branching** — replaced with two focused classes
2. **Clearer responsibilities** — remote knows HTTP, local knows SQLite
3. **Easier testing** — mock only one backend per test
4. **Better isolation** — changes to embeddy API only affect remote, local logic changes don't ripple

### Costs of Splitting

1. **Code duplication:**
   - Both need `collection_for_file()` method (or extract to utility)
   - Both need identical method signatures (protocol helps, but still duplicate declarations)
   
2. **Factory complexity:**
   ```python
   async def create_search_service(config, project_root):
       if not config.enabled:
           return None
       if config.mode == "remote":
           svc = RemoteSearchService(config)
       else:
           svc = LocalSearchService(config, project_root)
       await svc.initialize()
       return svc
   ```
   
3. **Loss of unified view:**
   - Currently, `SearchService` is the "single source of truth"
   - Splitting makes it harder to see both implementations at once

4. **Embeddy already does the separation:**
   - `EmbeddyClient` ≠ `SearchService` ≠ `Pipeline`
   - Remora's `SearchService` is just adapting embeddy's internal split
   - Splitting remora's layer doesn't add value — embeddy already encapsulates

---

## Critical Finding: Embeddy Already Provides Strategy Pattern

**Key insight:** Embeddy's architecture already separates concerns:

```
embeddy.client.EmbeddyClient     → Remote HTTP API
embeddy.search.SearchService     → Local search logic
embeddy.pipeline.Pipeline        → Local ingestion logic
```

Remora's `SearchService` is **already a thin facade** — it just delegates to embeddy's own separation.

**Question:** Does splitting remora's facade add value, or does it just mirror embeddy's structure without benefit?

---

## Empirical Evidence: Branching Complexity

Let's count actual conditional branches in current code:

```python
# initialize() - 2 branches (remote vs local)
if self._config.mode == "remote":
    ...
else:
    await self._initialize_local()

# search() - 2 branches
if self._client is not None:
    ...
if self._search_svc is not None:
    ...

# find_similar() - 2 branches
# index_file() - 2 branches  
# delete_source() - 2 branches
# index_directory() - 2 branches
```

**Total:** 12 conditional checks across 6 methods

**Guide's threshold:** "If <5 conditionals total, keep as-is (YAGNI)"

**Reality:** 12 conditionals > 5, but they're **simple delegations**, not complex logic.

---

## Recommendation: DO NOT SPLIT

### Rationale

1. **Branching is simple delegation:**
   - Current code is `if remote: call_remote() elif local: call_local()`
   - This is the simplest possible branching pattern
   - Splitting adds classes without reducing complexity

2. **Embeddy already separates concerns:**
   - Remote client and local search service are already separate in embeddy
   - Remora's `SearchService` just adapts embeddy's API
   - Splitting remora's layer mirrors embeddy without adding value

3. **YAGNI violation:**
   - No evidence of maintenance burden
   - No testability issues reported
   - No confusion from developers

4. **Factory adds indirection:**
   - Current: `SearchService(config, project_root)`
   - After split: `create_search_service(config, project_root)`
   - One more layer of abstraction for no clear benefit

5. **Better alternative: Improve current structure**
   - Extract `collection_for_file()` to standalone function
   - Document the delegation pattern clearly
   - Add type hints for `_client` and `_search_svc`

### When Splitting Would Be Justified

Split into strategies if:
- Remote and local have **different business logic** (they don't — both delegate to embeddy)
- Tests need to mock **only one backend** (current tests already do this fine)
- Performance profiling shows **branching overhead** (unlikely — it's 2 if-statements)
- **New backends** are planned (e.g., PostgreSQL full-text, external vector DB)

None of these conditions currently exist.

---

## Alternative: Minimal Refactoring

Instead of full strategy pattern, consider:

```python
class SearchService:
    """Async semantic search service backed by embeddy."""
    
    # ... __init__ unchanged ...
    
    async def search(self, query, ...):
        if not self._available:
            return []
        
        if self._client:
            return await self._remote_search(query, ...)
        if self._search_svc:
            return await self._local_search(query, ...)
        return []
    
    async def _remote_search(self, query, ...) -> list[dict]:
        """Delegate to remote embeddy client."""
        result = await self._client.search(query, ...)
        return result.get("results", [])
    
    async def _local_search(self, query, ...) -> list[dict]:
        """Delegate to local embeddy search service."""
        results = await self._search_svc.search(query, ...)
        return [transform(item) for item in results.results]
```

**Benefits:**
- Clearer method boundaries
- Easier to test (mock `_remote_search` or `_local_search`)
- No factory needed
- Maintains single class

---

## Final Verdict

**Phase 11: REJECT**

**Reasoning:**
1. Embeddy already provides the strategy pattern — remora just adapts it
2. Branching is simple delegation, not complex logic
3. Splitting adds indirection without reducing complexity
4. No empirical evidence of problems requiring this refactoring
5. Better alternatives exist (extract methods, improve documentation)

**Recommended action:**
- Keep current `SearchService` structure
- Extract helper methods for remote/local delegation
- Document the embeddy adaptation pattern
- Revisit if new backends are added or business logic diverges

---

**Analysis completed:** 2026-03-18  
**Embeddy version studied:** v3.0.0 (from `.context/embeddy/`)
