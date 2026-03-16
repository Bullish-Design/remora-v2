# Remora v2 — Recommendations & Improvements

**Date**: 2026-03-16
**Companion to**: `CODE_REVIEW.md`
**Priority**: P0 (do now) > P1 (do soon) > P2 (do eventually) > P3 (nice to have)

---

## Table of Contents

1. **P0 — Fix Before Any New Features** — Critical cleanup, safety, correctness
2. **P1 — Structural Improvements** — Architecture, decomposition, testing
3. **P2 — Performance & Scalability** — Batching, caching, query optimization
4. **P3 — Polish & Developer Experience** — Naming, docs, tooling
5. **Implementation Roadmap** — Suggested order of work

---

## 1. P0 — Fix Before Any New Features

### 1.1 Fix Class-Level Mutable State on TurnContext

**File:** `src/remora/core/externals.py:30`
**Problem:** `_send_message_timestamps` is a class variable shared across all instances, causing rate limit state to leak between agents and tests.
**Fix:** Move to instance variable in `__init__`. Better yet, extract rate limiting into a standalone `RateLimiter` class owned by `ActorPool` or passed into `TurnContext`, so the lifecycle is explicitly managed.

```python
# Before (broken)
class TurnContext:
    _send_message_timestamps: dict[str, deque[float]] = {}

# After (correct)
class TurnContext:
    def __init__(self, ...):
        self._send_message_timestamps: dict[str, deque[float]] = {}
```

**Effort:** 30 minutes
**Risk:** Low — purely internal state management

### 1.2 Delete Actor Delegation Wrappers

**File:** `src/remora/core/actor.py:854-936`
**Problem:** ~80 lines of boilerplate that forward calls to `AgentTurnExecutor` private methods.
**Fix:** Delete lines 854-936 of `Actor`. Update any tests that call `actor._start_agent_turn()` etc. to test `AgentTurnExecutor` directly. Also delete the compatibility property shims (lines 760-791).

**Effort:** 1-2 hours (mostly updating tests)
**Risk:** Medium — tests will break, but that's the point

### 1.3 Fix `batch()` Context Manager Error Handling

**File:** `src/remora/core/graph.py:39-48`
**Problem:** `batch()` commits even when an inner operation raises, persisting partial mutations.
**Fix:**

```python
@asynccontextmanager
async def batch(self):
    self._batch_depth += 1
    try:
        yield
    except Exception:
        if self._batch_depth == 1:
            await self._db.rollback()
        raise
    finally:
        self._batch_depth -= 1
        if self._batch_depth == 0:
            await self._db.commit()
```

**Effort:** 30 minutes
**Risk:** Low — makes existing behavior safer

### 1.4 Remove `set_status` or Make It Private

**File:** `src/remora/core/graph.py:158-165`
**Problem:** `set_status()` bypasses the state machine enforced by `transition_status()`. Any caller can silently corrupt the state machine.
**Fix:** Either delete `set_status` (if nothing uses it) or rename to `_force_status` and add a docstring explaining when it's appropriate.

**Effort:** 15 minutes
**Risk:** Low

### 1.5 Type the Search Service Interface

**File:** Multiple (7 files)
**Problem:** `search_service` is typed as `object | None` or `Any` everywhere.
**Fix:** Create a Protocol:

```python
# src/remora/core/search.py
class SearchServiceProtocol(Protocol):
    @property
    def available(self) -> bool: ...
    async def search(self, query: str, collection: str | None, top_k: int, mode: str) -> list[dict[str, Any]]: ...
    async def find_similar(self, chunk_id: str, collection: str | None, top_k: int) -> list[dict[str, Any]]: ...
    async def index_file(self, path: str, collection: str | None = None) -> None: ...
    async def delete_source(self, path: str, collection: str | None = None) -> None: ...
```

Then replace all `object | None` and `Any` with `SearchServiceProtocol | None`.

**Effort:** 1 hour
**Risk:** None — purely additive type annotations

---

## 2. P1 — Structural Improvements

### 2.1 Decompose actor.py Into Separate Modules

**Current:** 952 LOC single file with 7 classes
**Target:** Split into:
- `core/outbox.py` — `Outbox`, `OutboxObserver` (~60 LOC)
- `core/trigger.py` — `Trigger`, `TriggerPolicy` (~70 LOC)
- `core/prompt.py` — `PromptBuilder` (~90 LOC)
- `core/turn_executor.py` — `AgentTurnExecutor` (~350 LOC)
- `core/actor.py` — `Actor` only (~100 LOC after removing delegation wrappers)

This makes each concern independently testable and navigable.

**Effort:** 2-3 hours
**Risk:** Medium — lots of import changes but no logic changes

### 2.2 Refactor web/server.py From Closures to Class-Based or Module-Level Handlers

**Current:** 600 LOC single function with 20+ nested closures
**Target:** Extract handlers into a class or module-level functions that receive dependencies explicitly:

```python
class NodeAPI:
    def __init__(self, node_store: NodeStore, event_store: EventStore):
        self._node_store = node_store
        self._event_store = event_store

    async def list_nodes(self, request: Request) -> JSONResponse:
        nodes = await self._node_store.list_nodes()
        return JSONResponse([n.model_dump() for n in nodes])
```

Or use Starlette's dependency injection pattern with `request.app.state`.

**Effort:** 3-4 hours
**Risk:** Medium — functional behavior unchanged, just restructuring

### 2.3 Replace `_read_bundle_config` Manual Validation with Pydantic

**File:** `src/remora/core/actor.py:660-721`
**Problem:** 62 lines of manual type checking that duplicates what Pydantic does.
**Fix:** Define a `BundleConfig` Pydantic model:

```python
class BundleConfig(BaseModel):
    system_prompt: str = "You are an autonomous code agent."
    system_prompt_extension: str = ""
    model: str | None = None
    max_turns: int = 8
    prompts: dict[str, str] = {}
    self_reflect: SelfReflectConfig | None = None
```

Then `_read_bundle_config` becomes `BundleConfig.model_validate(loaded)`.

**Effort:** 1 hour
**Risk:** Low

### 2.4 Add Lifecycle Integration Tests

**Problem:** `lifecycle.py` has zero test coverage. It orchestrates the most critical path: startup → scan → run → shutdown.
**Fix:** Write integration tests that:
1. Start the lifecycle with a small project and `run_seconds=2.0`
2. Verify nodes are discovered
3. Verify the web server responds to health checks
4. Verify shutdown completes cleanly with no leaked tasks

**Effort:** 3-4 hours
**Risk:** None

### 2.5 Add Concurrency Tests

**Problem:** No tests exercise concurrent access patterns.
**Fix:** Write tests for:
1. Two events dispatched simultaneously to the same agent (should serialize via inbox)
2. Subscription modification while dispatch is in progress
3. Multiple `reconcile_cycle()` calls overlapping (should be idempotent)
4. Actor eviction while a turn is in progress

Use `asyncio.gather()` and `asyncio.Event` to create controlled race conditions.

**Effort:** 4-6 hours
**Risk:** None — may reveal bugs

### 2.6 Fix OutboxObserver to Use isinstance() Dispatch

**File:** `src/remora/core/actor.py:119-159`
**Problem:** String-based type dispatch on `type(event).__name__`
**Fix:** Import the actual event types from structured_agents and use isinstance:

```python
from structured_agents.events import ModelRequestEvent as SAModelRequestEvent

def _translate(self, event: Any) -> Event | None:
    if isinstance(event, SAModelRequestEvent):
        return ModelRequestEvent(...)
```

If the structured_agents types aren't importable, add a comment explaining why string dispatch is necessary.

**Effort:** 30 minutes
**Risk:** Low

---

## 3. P2 — Performance & Scalability

### 3.1 Batch Event Store Commits

**File:** `src/remora/core/events/store.py:66-102`
**Problem:** Every `append()` calls `await self._db.commit()`. With WAL mode, each commit triggers an fsync.
**Fix:** Implement a write-behind buffer:

```python
class EventStore:
    def __init__(self, ...):
        self._pending_count = 0
        self._last_commit = time.monotonic()

    async def append(self, event: Event) -> int:
        # ... INSERT ...
        self._pending_count += 1
        if self._pending_count >= 50 or (time.monotonic() - self._last_commit) > 0.1:
            await self._db.commit()
            self._pending_count = 0
            self._last_commit = time.monotonic()
```

Or use a periodic commit task that flushes every 100ms.

**Effort:** 2 hours
**Risk:** Medium — events are briefly non-durable; acceptable for this use case

### 3.2 Add `get_latest_event_by_type` to EventStore

**File:** `src/remora/core/events/store.py`
**Problem:** `_latest_rewrite_proposal` in web/server.py fetches 200 events and scans linearly.
**Fix:** Add a purpose-built query:

```python
async def get_latest_event_by_type(
    self, agent_id: str, event_type: str
) -> dict[str, Any] | None:
    cursor = await self._db.execute(
        "SELECT * FROM events WHERE agent_id = ? AND event_type = ? ORDER BY id DESC LIMIT 1",
        (agent_id, event_type),
    )
    row = await cursor.fetchone()
    ...
```

**Effort:** 30 minutes
**Risk:** None

### 3.3 Batch Node Existence Checks in Projections

**File:** `src/remora/code/projections.py:27-40`
**Problem:** N+1 query pattern — one SELECT per CST node.
**Fix:** Fetch all potentially-existing nodes in one query:

```python
node_ids = [cst.node_id for cst in cst_nodes]
existing_nodes = await node_store.get_nodes_by_ids(node_ids)  # new method
existing_by_id = {n.node_id: n for n in existing_nodes}
```

Add `get_nodes_by_ids(ids: list[str])` to `NodeStore` using `WHERE node_id IN (?)`.

**Effort:** 1 hour
**Risk:** Low

### 3.4 Replace SSE Polling with Task-Based Disconnect Detection

**File:** `src/remora/web/server.py:540-548`
**Problem:** `asyncio.wait_for(..., timeout=0.25)` raises TimeoutError 4x/sec per client.
**Fix:**

```python
disconnect_task = asyncio.create_task(request.is_disconnected())
stream_task = asyncio.create_task(stream_iterator.__anext__())
done, pending = await asyncio.wait(
    {disconnect_task, stream_task},
    return_when=asyncio.FIRST_COMPLETED,
)
for task in pending:
    task.cancel()
```

**Effort:** 1 hour
**Risk:** Low

### 3.5 Decompose `_materialize_directories`

**File:** `src/remora/code/reconciler.py:195-320`
**Problem:** 125-line method doing 7 things.
**Fix:** Extract into:
- `_compute_directory_hierarchy(file_paths) -> dict[str, list[str]]`
- `_remove_stale_directories(existing, desired)`
- `_upsert_directory(dir_id, parent_id, children, existing, ...)`

**Effort:** 2 hours
**Risk:** Low — pure refactoring

---

## 4. P3 — Polish & Developer Experience

### 4.1 Establish Error Boundary Documentation

Create a `docs/error-boundaries.md` or inline comments documenting:
- Actor turn boundary: catches all exceptions, emits AgentErrorEvent
- Tool execution boundary: catches all exceptions, returns error ToolResult
- Reconciler batch boundary: catches all exceptions, logs and continues
- Event handler boundary: catches all exceptions in `_dispatch_handlers`

This prevents future developers from adding catch-all handlers in the wrong places.

### 4.2 Reduce Logging Verbosity

- Move tool start/complete logs from INFO to DEBUG
- Move agent turn detail logs from INFO to DEBUG
- Keep lifecycle events (actor created, actor evicted, reconcile complete) at INFO
- Add structured logging fields (JSON format option) for production use

### 4.3 Add `NodeStore.count_nodes()` Method

Eliminate the encapsulation violation in `api_health`:
```python
async def count_nodes(self) -> int:
    cursor = await self._db.execute("SELECT COUNT(*) FROM nodes")
    row = await cursor.fetchone()
    return int(row[0]) if row else 0
```

### 4.4 Clean Up Global Caches in discovery.py

Replace module-level `@lru_cache` with a `DiscoveryContext` class that holds parser/query caches. Pass it through `discover()` as an optional parameter. This makes testing easier and eliminates global state.

### 4.5 Make Web Rate Limiter Per-Client

Replace the single `RateLimiter` instance with a dict keyed by client IP:
```python
limiters: dict[str, RateLimiter] = {}
def get_limiter(request: Request) -> RateLimiter:
    ip = request.client.host if request.client else "unknown"
    if ip not in limiters:
        limiters[ip] = RateLimiter(max_requests=10, window_seconds=60.0)
    return limiters[ip]
```

### 4.6 Fix LSP Chat Command Hardcoded Port

Pass the web server port through to the LSP server or read it from config.

### 4.7 Consistent Naming

Adopt a convention and apply it:
- All data access layers: `*Store` (NodeStore, EventStore, SubscriptionStore)
- All service layers: `*Service` (WorkspaceService, SearchService, DiscoveryService)
- All runtime components: no suffix (Actor, ActorPool, Reconciler, Lifecycle)

### 4.8 Address Grail Script Filesystem Round-Trip

If Grail supports loading scripts from strings, eliminate the temp-file-per-parse pattern in `grail.py`. If not, file an upstream feature request.

---

## 5. Implementation Roadmap

### Phase 1: Safety & Correctness (P0) — 1 day

| # | Task | Effort |
|---|------|--------|
| 1 | Fix TurnContext class-level mutable state | 30 min |
| 2 | Fix batch() error handling | 30 min |
| 3 | Remove/privatize set_status | 15 min |
| 4 | Type search service interface | 1 hr |
| 5 | Delete Actor delegation wrappers + update tests | 2 hr |

### Phase 2: Structural Cleanup (P1) — 2-3 days

| # | Task | Effort |
|---|------|--------|
| 6 | Decompose actor.py into separate modules | 3 hr |
| 7 | Refactor web/server.py handlers | 4 hr |
| 8 | Replace _read_bundle_config with Pydantic model | 1 hr |
| 9 | Fix OutboxObserver dispatch | 30 min |
| 10 | Write lifecycle integration tests | 4 hr |
| 11 | Write concurrency tests | 5 hr |

### Phase 3: Performance (P2) — 1-2 days

| # | Task | Effort |
|---|------|--------|
| 12 | Batch EventStore commits | 2 hr |
| 13 | Add get_latest_event_by_type | 30 min |
| 14 | Batch projections node lookups | 1 hr |
| 15 | Fix SSE polling | 1 hr |
| 16 | Decompose _materialize_directories | 2 hr |

### Phase 4: Polish (P3) — 1 day

| # | Task | Effort |
|---|------|--------|
| 17-24 | Remaining P3 items | 4-6 hr |

**Total estimated effort: ~5-7 working days**

This is a manageable cleanup that would elevate the codebase from C+ to B+/A- territory. The P0 items are critical correctness fixes. The P1 items make the codebase maintainable. P2 and P3 are quality-of-life improvements that can be done incrementally.

