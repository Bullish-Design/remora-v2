# Remora v2 — Recommendations & Improvement Roadmap

**Based on**: Code Review dated 2026-03-15
**Priority framework**: P0 = blocking for production, P1 = should fix before demo, P2 = next sprint, P3 = backlog

---

## Table of Contents

1. [Critical Fixes (P0)](#1-critical-fixes-p0)
2. [Security Hardening (P0/P1)](#2-security-hardening-p0p1)
3. [Performance Improvements (P1)](#3-performance-improvements-p1)
4. [Architecture Refactors (P2)](#4-architecture-refactors-p2)
5. [Code Quality (P2)](#5-code-quality-p2)
6. [Testing Improvements (P2)](#6-testing-improvements-p2)
7. [Developer Experience (P3)](#7-developer-experience-p3)
8. [Future Architecture (P3)](#8-future-architecture-p3)

---

## 1. Critical Fixes (P0)

### 1.1 Fix Memory Leaks

**`_depths` dict in `Actor`** — Add TTL-based cleanup. Simple approach: periodically (every 100 triggers) remove correlation_ids older than 5 minutes.

```python
def _should_trigger(self, correlation_id: str) -> bool:
    now_ms = time.time() * 1000.0
    # Periodic cleanup
    if len(self._depths) > 100:
        cutoff = now_ms - 300_000  # 5 minutes
        self._depths = {k: v for k, v in self._depths.items()
                        if self._depth_timestamps.get(k, 0) > cutoff}
    ...
```

**`_file_locks` dict in `FileReconciler`** — Use a `weakref`-based cache or LRU dict. Since locks are only needed during reconciliation, a simple approach is to use `asyncio.Lock()` per-file but evict locks not used in the last reconciliation cycle.

### 1.2 Fix Event Bus MRO Dispatch

Replace the MRO walk with explicit type checking:

```python
async def emit(self, event: Event) -> None:
    # Dispatch to exact-type handlers only
    handlers = self._handlers.get(type(event), [])
    await self._dispatch_handlers(handlers, event)
    # Dispatch to base Event handlers
    if type(event) is not Event:
        base_handlers = self._handlers.get(Event, [])
        await self._dispatch_handlers(base_handlers, event)
    # Global handlers
    await self._dispatch_handlers(self._all_handlers, event)
```

### 1.3 Fix Race Condition in `transition_status`

Use an atomic UPDATE:

```python
async def transition_status(self, node_id: str, target: NodeStatus) -> bool:
    valid_sources = [s for s, targets in STATUS_TRANSITIONS.items() if target in targets]
    placeholders = ",".join("?" for _ in valid_sources)
    cursor = await self._db.execute(
        f"UPDATE nodes SET status = ? WHERE node_id = ? AND status IN ({placeholders})",
        (target.value, node_id, *[s.value for s in valid_sources]),
    )
    await self._db.commit()
    return cursor.rowcount > 0
```

---

## 2. Security Hardening (P0/P1)

### 2.1 Path Traversal Fix (P0)

In `web/server.py`, validate all resolved disk paths are within the project root:

```python
def _workspace_path_to_disk_path(node_id, node_file_path, workspace_path) -> Path:
    ...  # existing resolution
    resolved = result.resolve()
    if not resolved.is_relative_to(workspace_service._project_root):
        raise ValueError(f"Path traversal attempt: {workspace_path}")
    return resolved
```

### 2.2 CSRF Protection (P0)

Add Origin header validation middleware:

```python
from starlette.middleware.base import BaseHTTPMiddleware

class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.method in ("POST", "PUT", "DELETE"):
            origin = request.headers.get("origin", "")
            if origin and not origin.startswith(("http://localhost:", "http://127.0.0.1:")):
                return JSONResponse({"error": "CSRF rejected"}, status_code=403)
        return await call_next(request)
```

### 2.3 Fix `graph_set_status` (P1)

Route through `transition_status` instead of `set_status`:

```python
async def graph_set_status(self, target_id: str, new_status: str) -> bool:
    target_enum = NodeStatus(new_status)  # Validates the value
    return await self._node_store.transition_status(target_id, target_enum)
```

### 2.4 Add Agent Action Limits (P1)

- Cap `search_content` results to 1000 matches
- Cap `broadcast` to configurable max targets (default 50)
- Add per-agent rate limiting to `send_message` (e.g., 10/second)

---

## 3. Performance Improvements (P1)

### 3.1 Batch SQLite Commits

Instead of committing after every operation, use a write-ahead buffer:

**Quick win**: Add a context manager for batch operations:

```python
class NodeStore:
    @asynccontextmanager
    async def batch(self):
        """Group multiple operations into a single commit."""
        yield
        await self._db.commit()
```

Then in the reconciler:
```python
async with self._node_store.batch():
    for node in projected:
        await node_store.upsert_node(node)  # No individual commits
```

This alone could improve reconciliation throughput by 10-50x.

### 3.2 Fix Subscription Cache Rebuild

Instead of invalidating the entire cache on every write, use incremental updates:

```python
async def register(self, agent_id: str, pattern: SubscriptionPattern) -> int:
    ...  # DB insert
    # Incremental cache update instead of full invalidation
    if self._cache is not None:
        key_types = pattern.event_types or [_ANY_EVENT_KEY]
        for event_type in key_types:
            self._cache.setdefault(event_type, []).append((agent_id, pattern))
    return sub_id
```

### 3.3 Use `SELECT COUNT(*)` for Health Check

```python
async def api_health(_request: Request) -> JSONResponse:
    cursor = await node_store._db.execute("SELECT COUNT(*) FROM nodes")
    row = await cursor.fetchone()
    node_count = row[0]
```

### 3.4 Truncate `_cached_script` Key

Remove `source` from the cache key — `content_hash` is sufficient:

```python
@lru_cache(maxsize=256)
def _cached_script(content_hash: str, normalized_name: str) -> grail.GrailScript:
    ...
```

Store source externally or pass it through without caching.

---

## 4. Architecture Refactors (P2)

### 4.1 Extract Actor Responsibilities

Split `Actor` into focused components:

- **`Actor`**: Inbox/outbox/lifecycle only (~100 lines)
- **`AgentTurnExecutor`**: Kernel invocation, retry logic (~150 lines)
- **`PromptBuilder`**: System prompt, user prompt, bundle config (~100 lines)
- **`TriggerPolicy`**: Cooldown, depth limits (~50 lines)

### 4.2 Extract `_start()` into a Lifecycle Manager

```python
class RemoraLifecycle:
    async def start(self, config, project_root, ...):
        self.services = RuntimeServices(config, project_root, db)
        await self.services.initialize()
        self._tasks = self._create_tasks()

    async def run(self):
        await asyncio.gather(*self._tasks)

    async def shutdown(self):
        # Ordered shutdown with clear ownership
```

### 4.3 Eliminate the `hasattr(x, "value")` Pattern

Define a serialization boundary:

```python
# In types.py
def serialize_enum(value: StrEnum | str) -> str:
    return value.value if isinstance(value, StrEnum) else str(value)
```

Or better: enforce StrEnum everywhere internally, serialize to str only at DB/JSON boundaries.

### 4.4 Move `RecordingOutbox` to Tests

Move `RecordingOutbox` from `core/actor.py` to `tests/factories.py` or `tests/doubles.py`. Define an `OutboxProtocol` if needed for typing.

### 4.5 Move Monkey-Patched LSP Handlers to a Proper Abstraction

Instead of `server._remora_handlers`, create a `RemoraLSPHandlers` class that holds the handlers and is passed to both the server setup and tests.

---

## 5. Code Quality (P2)

### 5.1 Fix Ruff Violations

```bash
ruff check --fix src/remora/
```

5 of 9 are auto-fixable import sorting. The remaining 4 need manual attention.

### 5.2 Fix Starlette Deprecation

Migrate from `on_shutdown` to `lifespan`:

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    yield
    shutdown_event.set()

app = Starlette(routes=routes, lifespan=lifespan)
```

### 5.3 Replace `assert` in Production Code

```python
# Before
assert services.reconciler is not None

# After
if services.reconciler is None:
    raise RuntimeError("RuntimeServices.initialize() must be called before start")
```

### 5.4 Add Type Checking to CI

Add `pyright` or `mypy` configuration to `pyproject.toml`:

```toml
[tool.pyright]
include = ["src/remora"]
typeCheckingMode = "basic"
```

### 5.5 Standardize Enum Handling

Pick one approach and enforce it. Recommendation: use StrEnum everywhere internally, add `.value` only at the serialization boundary (DB writes, JSON responses).

### 5.6 Import `__version__` in Web Health Check

```python
from remora import __version__
# ...
"version": __version__,
```

---

## 6. Testing Improvements (P2)

### 6.1 Add Concurrency Tests

Test the actor pool under concurrent load:

```python
async def test_concurrent_triggers():
    """Multiple agents processing events simultaneously."""
    pool = ActorPool(...)
    # Send 20 events to 5 different agents
    # Assert all processed without deadlock or data corruption
```

### 6.2 Add Subscription Matching Property Tests

```python
from hypothesis import given, strategies as st

@given(st.text(), st.text())
def test_subscription_pattern_matching_is_consistent(event_type, path):
    pattern = SubscriptionPattern(event_types=[event_type])
    event = Event(event_type=event_type)
    assert pattern.matches(event)
```

### 6.3 Add Startup/Shutdown Integration Test

Test the full `_start()` path with `run_seconds=2.0` to verify clean startup and shutdown.

### 6.4 Add Load Tests for Reconciler

Test reconciling 1000 files with 10 nodes each to verify performance and memory under load.

### 6.5 Document Skip Reasons

The 5 skipped tests should have explicit `@pytest.mark.skip(reason="...")` annotations.

---

## 7. Developer Experience (P3)

### 7.1 Add `py.typed` Marker

Create `src/remora/py.typed` (empty file) so downstream consumers can use type information.

### 7.2 Add Structured Logging Option

Support JSON-lines output for production:

```python
if log_format == "json":
    handler.setFormatter(JSONFormatter())
```

### 7.3 Add a `node_count()` Method to NodeStore

Avoid loading all nodes just to count them:

```python
async def node_count(self, **filters) -> int:
    # SELECT COUNT(*) with optional WHERE
```

### 7.4 Add Event Compaction/Archival

The events table grows without bound. Add a configurable retention policy:

```python
async def compact_events(self, retain_days: int = 30) -> int:
    cutoff = time.time() - (retain_days * 86400)
    cursor = await self._db.execute(
        "DELETE FROM events WHERE timestamp < ?", (cutoff,)
    )
    await self._db.commit()
    return cursor.rowcount
```

### 7.5 Make SSE Event IDs Monotonic Integers

Use the database event `id` (already an auto-increment integer) as the SSE event ID instead of `event.timestamp`.

---

## 8. Future Architecture (P3)

### 8.1 Consider Connection Pooling

If the system scales beyond a single sqlite connection, consider `aiosqlite` connection pooling or migration to PostgreSQL.

### 8.2 Consider Incremental Parsing

Tree-sitter supports incremental parsing (passing the old tree + edits). For large files, this could reduce re-parse time from milliseconds to microseconds.

### 8.3 Consider Event Sourcing Properly

The current design stores events but doesn't use them as the source of truth — node state is mutable in the `nodes` table. Consider whether true event sourcing (deriving node state from the event log) would simplify the architecture.

### 8.4 Consider a Custom Exception Hierarchy

```python
class RemoraError(Exception): ...
class NodeNotFoundError(RemoraError): ...
class InvalidTransitionError(RemoraError): ...
class WorkspaceError(RemoraError): ...
class ToolExecutionError(RemoraError): ...
```

This would allow callers to catch specific errors instead of bare `Exception`.

---

## Summary: Recommended Sprint Plan

### Sprint 1 (P0 — Blocking)
- [ ] Fix path traversal in web server
- [ ] Add CSRF protection
- [ ] Fix `graph_set_status` to use transition validation
- [ ] Fix `_depths` memory leak in Actor
- [ ] Fix `_file_locks` memory leak in FileReconciler
- [ ] Fix event bus MRO dispatch bug
- [ ] Fix `transition_status` race condition

### Sprint 2 (P1 — Before Demo)
- [ ] Batch SQLite commits
- [ ] Fix subscription cache O(N²) rebuild
- [ ] Add agent action limits (search_content, broadcast)
- [ ] Fix ruff violations
- [ ] Fix Starlette deprecation warnings
- [ ] Replace production `assert` statements

### Sprint 3 (P2 — Quality)
- [ ] Extract Actor responsibilities
- [ ] Move test doubles out of production code
- [ ] Add concurrency test suite
- [ ] Add type checker to CI
- [ ] Standardize StrEnum handling
- [ ] Add startup/shutdown integration test

### Backlog (P3)
- [ ] Structured logging
- [ ] Event compaction
- [ ] Incremental tree-sitter parsing
- [ ] Custom exception hierarchy
- [ ] Connection pooling evaluation
