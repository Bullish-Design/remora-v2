# Remora v2 — Recommendations & Improvements

**Date:** 2026-03-16
**Context:** Follows from CODE_REVIEW.md. These recommendations prioritize the cleanest, most elegant architecture without backwards-compatibility constraints.

---

## Table of Contents

1. [Priority 1: Unify the Node Model](#1-unify-the-node-model)
2. [Priority 2: Decompose the Reconciler](#2-decompose-the-reconciler)
3. [Priority 3: Fix Event Type Dispatch](#3-fix-event-type-dispatch)
4. [Priority 4: Decompose the Web Server](#4-decompose-the-web-server)
5. [Priority 5: Simplify the Turn Executor](#5-simplify-the-turn-executor)
6. [Priority 6: Fix the Externals God-Object](#6-fix-the-externals-god-object)
7. [Priority 7: Batch Event Commits](#7-batch-event-commits)
8. [Priority 8: Clean Up Grail Caching](#8-clean-up-grail-caching)
9. [Priority 9: Remove Test-Driven Production Indirection](#9-remove-test-driven-production-indirection)
10. [Priority 10: Miscellaneous Cleanup](#10-miscellaneous-cleanup)

---

## 1. Unify the Node Model

**Problem:** `CSTNode` and `Node` represent the same entity with nearly identical fields. The projection layer manually copies fields between them, adding complexity and a bug surface.

**Recommendation:** Merge into a single `Node` model with a lifecycle:

```
Discovery produces Node(status="discovered", source_hash=computed)
    -> Reconciler enriches with status, role, parent_id
    -> NodeStore persists
```

**Concrete steps:**
1. Add `source_hash` computation to discovery (it's just `sha256(text)`)
2. Add `status` and `role` fields to what is currently `CSTNode`, defaulting to `"idle"` and `None`
3. Delete `projections.py` entirely — its logic folds into 10 lines in the reconciler
4. Rename `CSTNode` to `DiscoveredNode` or just use `Node` directly
5. The `text` vs `source_code` naming inconsistency goes away

**Impact:** Eliminates `projections.py` (82 LOC), simplifies reconciler by ~50 LOC, removes an entire conceptual layer.

---

## 2. Decompose the Reconciler

**Problem:** `reconciler.py` is 735 LOC doing 4 distinct jobs: file watching, node reconciliation, directory management, and virtual agent lifecycle.

**Recommendation:** Split into focused modules:

```
code/
  reconciler.py      -> Slim orchestrator (~100 LOC)
  watcher.py         -> File watching via watchfiles (~80 LOC)
  directories.py     -> Directory hierarchy projection (~150 LOC)
  virtual_agents.py  -> Virtual agent sync (~120 LOC)
```

**The reconciler becomes an orchestrator:**
```python
class Reconciler:
    def __init__(self, watcher, dir_manager, virtual_agent_manager, ...):
        ...
    
    async def full_scan(self):
        await self._virtual_agent_manager.sync()
        changed = self._watcher.collect_changes()
        await self._dir_manager.update(changed.file_paths)
        for path in changed.modified:
            await self._reconcile_file(path)
        for path in changed.deleted:
            await self._remove_file(path)
```

**Impact:** Each module becomes testable in isolation. The file lock generation GC goes away if the watcher owns its own concurrency.

---

## 3. Fix Event Type Dispatch

**Problem:** Subscriptions match events by string name (`"AgentCompleteEvent"`), but the EventBus dispatches by Python type. Renaming an event class silently breaks subscriptions.

**Recommendation:** Two options:

**Option A (preferred): Explicit event type registry**
```python
class EventType(StrEnum):
    AGENT_START = "agent_start"
    AGENT_COMPLETE = "agent_complete"
    NODE_CHANGED = "node_changed"
    ...

class Event(BaseModel):
    event_type: EventType  # Not str
```
Subscriptions and bus both use `EventType` enum values. Renaming the class doesn't matter — the stable string identity is the enum value.

**Option B: Type-based subscriptions**
Replace string-based subscription patterns with type-based ones. The `SubscriptionRegistry` stores Python type references instead of strings. This is cleaner but harder to serialize to SQLite.

**Impact:** Eliminates an entire class of silent breakage. Makes event types discoverable and refactorable.

---

## 4. Decompose the Web Server

**Problem:** `web/server.py` is 722 LOC with 17 route handlers, middleware, SSE streaming, rate limiting, and path resolution all in one file.

**Recommendation:** Split by concern:

```
web/
  server.py          -> App factory + middleware (~80 LOC)
  routes/
    nodes.py         -> Node CRUD endpoints
    events.py        -> Event listing + SSE stream
    proposals.py     -> Rewrite proposal workflow
    chat.py          -> Chat + respond endpoints
    search.py        -> Semantic search endpoint
    health.py        -> Health check
  middleware.py       -> CSRF, rate limiting
  sse.py             -> SSE streaming logic
  paths.py           -> Workspace path resolution
```

**Additional improvements:**
- `_INDEX_HTML` should be loaded lazily, not at import time
- SSE streaming should use `async for` on the bus stream directly instead of creating/cancelling tasks per event
- Rate limiters should be shared (web + externals use the same sliding-window pattern)
- Add a `project_root` property to `CairnWorkspaceService` so the web server doesn't access `_project_root`

**Impact:** Each route group becomes independently testable. The 910-line test file can split accordingly.

---

## 5. Simplify the Turn Executor

**Problem:** `AgentTurnExecutor.__init__` takes 13 parameters and the class orchestrates workspace, tools, kernel, prompt building, trigger policy, metrics, and event emission.

**Recommendation:** Extract focused collaborators:

```python
class AgentTurnExecutor:
    def __init__(self, *, context_factory, kernel_factory, prompt_builder):
        ...

class TurnContextFactory:
    """Creates TurnContext instances for each turn."""
    def __init__(self, node_store, event_store, workspace_service, config, search_service):
        ...
    
    def create(self, node_id, trigger, outbox) -> TurnContext:
        ...

class KernelFactory:
    """Creates and runs agent kernels."""
    def __init__(self, config):
        ...
    
    async def run(self, messages, tools, model_name, max_turns, observer) -> Any:
        ...
```

**Additional improvements:**
- `_build_companion_context` should be a method on `AgentWorkspace` or a standalone function in a `companion.py` module
- `_read_bundle_config` should be a method on `CairnWorkspaceService`
- The hardcoded logger namespace should be removed — use `__name__`
- `_resolve_maybe_awaitable` should not exist — fix the interface to always return coroutines

**Impact:** The turn executor shrinks to ~100 LOC of pure orchestration logic.

---

## 6. Fix the Externals God-Object

**Problem:** `TurnContext` exposes 27 capabilities as methods. It's also where the send_message rate limiter lives (but it's broken because TurnContext is recreated per-turn).

**Recommendation:** Group capabilities into focused protocols:

```python
class FileCapabilities(Protocol):
    async def read_file(self, path: str) -> str: ...
    async def write_file(self, path: str, content: str) -> bool: ...
    async def list_dir(self, path: str) -> list[str]: ...
    async def file_exists(self, path: str) -> bool: ...
    async def search_files(self, pattern: str) -> list[str]: ...
    async def search_content(self, pattern: str, path: str) -> list[dict]: ...

class GraphCapabilities(Protocol):
    async def get_node(self, target_id: str) -> dict: ...
    async def query_nodes(self, ...) -> list[dict]: ...
    async def get_edges(self, target_id: str) -> list[dict]: ...
    async def get_children(self, parent_id: str) -> list[dict]: ...
    async def set_status(self, target_id: str, status: str) -> bool: ...

class EventCapabilities(Protocol):
    async def emit(self, event_type: str, payload: dict, tags: list[str]) -> bool: ...
    async def subscribe(self, ...) -> int: ...
    async def unsubscribe(self, subscription_id: int) -> bool: ...
    async def get_history(self, target_id: str, limit: int) -> list[dict]: ...

class CommunicationCapabilities(Protocol):
    async def send_message(self, to_node_id: str, content: str) -> bool: ...
    async def broadcast(self, pattern: str, content: str) -> str: ...
    async def request_human_input(self, question: str, options: list[str]) -> str: ...
    async def propose_changes(self, reason: str) -> str: ...
```

**Fix the rate limiter bug:** Move rate limiting state to the `Actor` level (persists across turns), not `TurnContext` (recreated each turn).

**Impact:** Each capability group is independently testable. Tools only get the capabilities they need (principle of least privilege).

---

## 7. Batch Event Commits

**Problem:** Every `EventStore.append()` call does an individual `await self._db.commit()`. Under burst emission, this serializes on SQLite write throughput.

**Recommendation:** Add a batching mode to EventStore:

```python
class EventStore:
    @asynccontextmanager
    async def batch(self):
        """Buffer events and commit in a single transaction."""
        self._batching = True
        try:
            yield
        finally:
            self._batching = False
            await self._db.commit()
            # Fan-out buffered events to bus + dispatcher
            for event in self._batch_buffer:
                await self._event_bus.emit(event)
                await self._dispatcher.dispatch(event)
            self._batch_buffer.clear()
    
    async def append(self, event):
        # ... INSERT ...
        if self._batching:
            self._batch_buffer.append(event)
        else:
            await self._db.commit()
            await self._event_bus.emit(event)
            await self._dispatcher.dispatch(event)
```

**Impact:** Reconciler's `full_scan` with hundreds of events goes from hundreds of commits to one.

---

## 8. Clean Up Grail Caching

**Problem:** Two-tier cache (dict + lru_cache) with temp file I/O on every cache miss.

**Recommendation:** Replace with a single bounded LRU dict:

```python
from functools import lru_cache

@lru_cache(maxsize=256)
def _parse_script(content_hash: str, name: str, source: str) -> grail.GrailScript:
    with tempfile.TemporaryDirectory(prefix="remora-grail-") as temp_dir:
        script_path = Path(temp_dir) / f"{name}.pym"
        script_path.write_text(source, encoding="utf-8")
        return grail.load(script_path)
```

Wait — `lru_cache` can't cache by source content directly because strings aren't hashable in a size-bounded way. Better approach:

```python
_SCRIPT_CACHE: dict[str, grail.GrailScript] = {}  # content_hash -> parsed script

def _load_script(source: str, name: str) -> grail.GrailScript:
    content_hash = hashlib.sha256(source.encode()).hexdigest()[:16]
    cached = _SCRIPT_CACHE.get(content_hash)
    if cached is not None:
        return cached
    
    with tempfile.TemporaryDirectory(prefix="remora-grail-") as td:
        path = Path(td) / f"{name}.pym"
        path.write_text(source)
        script = grail.load(path)
    
    if len(_SCRIPT_CACHE) >= 256:
        # Evict oldest
        _SCRIPT_CACHE.pop(next(iter(_SCRIPT_CACHE)))
    _SCRIPT_CACHE[content_hash] = script
    return script
```

One dict, one eviction path, no `lru_cache` gymnastics, no separate source cache.

**Impact:** Simpler code, same performance, easier to reason about.

---

## 9. Remove Test-Driven Production Indirection

**Problem:** `Actor.__init__` wraps `create_kernel`, `discover_tools`, and `extract_response_text` in lambdas solely to preserve monkeypatch paths in tests.

**Recommendation:** Delete the lambda wrappers. Pass the real functions directly:

```python
# Before (bad):
create_kernel_fn=lambda **kwargs: create_kernel(**kwargs),

# After (good):
create_kernel_fn=create_kernel,
```

Then update tests to monkeypatch on the actual module where the function is defined (`remora.core.kernel.create_kernel`) instead of the re-export path (`remora.core.actor.create_kernel`).

**Also:**
- Delete `clear_caches()` from `discovery.py` — tests should use fresh `LanguageRegistry` instances instead of clearing module-level caches
- Remove the hardcoded logger namespace in `turn_executor.py` — use `__name__` and update tests
- Delete the `_ContextFilter` → rename to something honest like `_StructuredFieldInjector`

**Impact:** Cleaner production code, tests that test real behavior instead of import paths.

---

## 10. Miscellaneous Cleanup

### 10.1 Make `_expand_env_vars` Public
It's used across module boundaries. Rename to `expand_env_vars` and add to `config.py`'s `__all__`.

### 10.2 Fix Config Silent Drops
`BundleConfig.prompts` validator silently drops unknown keys. Change to either:
- Raise a `ValueError` for unknown keys (strict mode)
- Log a warning for unknown keys (lenient mode)
Never silently discard user data.

### 10.3 Remove Dead Config
`bundle_overlays` default has `"file"` key but `NodeType` has no `FILE` variant. Remove it.

### 10.4 Add `project_root` Property to Workspace Service
```python
class CairnWorkspaceService:
    @property
    def project_root(self) -> Path:
        return self._project_root
```
Eliminates private attribute access in `web/server.py`.

### 10.5 Fix NodeStore.batch() Transaction Management
Replace `await self._db.execute("ROLLBACK")` with proper aiosqlite transaction management:
```python
@asynccontextmanager
async def batch(self):
    async with self._db.execute("BEGIN"):
        try:
            yield
            await self._db.commit()
        except BaseException:
            await self._db.rollback()
            raise
```
Or better yet, use aiosqlite's built-in `db.execute("BEGIN")` / `db.commit()` / `db.rollback()`.

### 10.6 Use `asyncio.iscoroutinefunction` Instead of `asyncio.iscoroutine`
In `EventBus._dispatch_handlers`, check the function, not the result:
```python
# Before:
result = handler(event)
if asyncio.iscoroutine(result):
    tasks.append(asyncio.create_task(result))

# After:
if asyncio.iscoroutinefunction(handler):
    tasks.append(asyncio.create_task(handler(event)))
else:
    handler(event)
```
This avoids calling the handler to check if its result is a coroutine, and correctly handles awaitables.

### 10.7 Idle Actor Eviction Config
Move the hardcoded `max_idle_seconds=300.0` to `Config`:
```python
class Config(BaseSettings):
    actor_idle_timeout_s: float = 300.0
```

### 10.8 SearchConfig Mode Enum
```python
class SearchMode(StrEnum):
    REMOTE = "remote"
    LOCAL = "local"

class SearchConfig(BaseModel):
    mode: SearchMode = SearchMode.REMOTE
```

### 10.9 Lazy HTML Loading
```python
# Before (fails at import if file missing):
_INDEX_HTML = (_STATIC_DIR / "index.html").read_text(encoding="utf-8")

# After:
_INDEX_HTML: str | None = None

def _get_index_html() -> str:
    global _INDEX_HTML
    if _INDEX_HTML is None:
        _INDEX_HTML = (_STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return _INDEX_HTML
```

### 10.10 SHA256 Truncation Length
In `CairnWorkspaceService._safe_id`, increase hash truncation from 10 to 16 hex chars:
```python
digest = hashlib.sha256(node_id.encode("utf-8")).hexdigest()[:16]
```
64 bits vs 40 bits — significantly reduces collision probability.

---

## Summary: Recommended Execution Order

| Phase | Items | Effort | Impact |
|-------|-------|--------|--------|
| **Phase 1** | #1 (unify node model), #9 (remove test indirection), #10.1-10.4 | Small | Eliminates a whole model layer + cleans up debt |
| **Phase 2** | #3 (event type dispatch), #6.rate-limiter-fix | Medium | Fixes real bugs, prevents future breakage |
| **Phase 3** | #2 (decompose reconciler), #4 (decompose web server) | Large | Structural improvement, enables independent testing |
| **Phase 4** | #5 (simplify turn executor), #6 (externals decomposition) | Medium | Reduces complexity of the most critical path |
| **Phase 5** | #7 (batch commits), #8 (grail caching), #10.5-10.10 | Small | Performance + polish |

Total estimated effort: 2-3 focused weeks for a senior engineer.
