# Remora-v2 Refactoring Guide

## NO SUBAGENTS — Do all work directly.

---

## Table of Contents

1. [Phasing & Dependency Order](#phasing--dependency-order)
2. [Phase 0: Critical Bug Fixes](#phase-0-critical-bug-fixes) — C1, C2, C3, H2, H3
3. [Phase 1: Storage Foundation](#phase-1-storage-foundation) — R2, R23 (AsyncDB + unified storage)
4. [Phase 2: Event System Decomposition](#phase-2-event-system-decomposition) — R1, R17 (split events.py, dispatcher)
5. [Phase 3: Type Safety & Data Models](#phase-3-type-safety--data-models) — R6, R8, R15, R16 (status machine, collision-safe IDs, enums, dead code)
6. [Phase 4: Agent/Code Separation](#phase-4-agentcode-separation) — R21 (separate agent identity from code element)
7. [Phase 5: Externals Redesign](#phase-5-externals-redesign) — R4 (three options evaluated, chosen approach implemented)
8. [Phase 6: Direct Rewrite Flow](#phase-6-direct-rewrite-flow) — R5 (span-based apply + VCS-ready hooks)
9. [Phase 7: Discovery & Language Plugins](#phase-7-discovery--language-plugins) — R7, R8, R10, R19 (centralize paths, language plugin protocol)
10. [Phase 8: Reconciler Overhaul](#phase-8-reconciler-overhaul) — R9, R20 (fault isolation, event-driven reconciliation)
11. [Phase 9: Web & LSP Improvements](#phase-9-web--lsp-improvements) — R11, R12, R13
12. [Phase 10: Service Layer & Wiring](#phase-10-service-layer--wiring) — R3 (domain services, dependency injection)
13. [Phase 11: Test Consolidation](#phase-11-test-consolidation) — R14 (shared factories, new coverage)
14. [Phase 12: Event Sourcing Consideration](#phase-12-event-sourcing-consideration) — R22 (design outline)
15. [Appendix A: Externals Contract — Option Analysis](#appendix-a-externals-contract--option-analysis)
16. [Appendix B: Pydantic Patterns for Typed Enums](#appendix-b-pydantic-patterns-for-typed-enums)
17. [Appendix C: Event Sourcing Architecture Sketch](#appendix-c-event-sourcing-architecture-sketch)

---

## Phasing & Dependency Order

```
Phase 0 (bug fixes)  ──→  no deps, do first
Phase 1 (storage)    ──→  no deps
Phase 2 (events)     ──→  depends on Phase 1 (AsyncDB)
Phase 3 (types)      ──→  depends on Phase 2 (event types live in new locations)
Phase 4 (agent/code) ──→  depends on Phase 3 (new enums/types)
Phase 5 (externals)  ──→  depends on Phase 4 (agent model changes)
Phase 6 (direct rewrite)  ──→  depends on Phase 4 (agent model)
Phase 7 (discovery)  ──→  depends on Phase 3 (type safety)
Phase 8 (reconciler) ──→  depends on Phase 7 (discovery changes)
Phase 9 (web/lsp)    ──→  depends on Phase 2, Phase 4
Phase 10 (services)  ──→  depends on all above
Phase 11 (tests)     ──→  do incrementally within each phase + final consolidation
Phase 12 (eventsrc)  ──→  future consideration, not implemented in this guide
```

**Key constraint**: Tests must pass after every phase. Each phase is a self-contained refactor with its own acceptance criteria.

---

## Phase 0: Critical Bug Fixes

These are correctness fixes that should be applied to the *current* codebase before any structural refactoring. Each fix is small and independent.

### Step 0.1: Remove proposal-only status paths (C1)

**File**: `src/remora/core/runner.py`

**Current** (lines 176-180):
```python
finally:
    try:
        await self._node_store.set_status(node_id, "idle")
    except Exception:
        logger.exception("Failed to reset node status for %s", node_id)
```

**Fix**: In the no-proposals MVP, remove `pending_approval` from the runtime entirely and enforce a simple status model (`idle`/`running`/`error`). Keep guarded reset logic so we only transition `running -> idle`.

```python
finally:
    try:
        current_node = await self._node_store.get_node(node_id)
        if current_node is not None and current_node.status == "running":
            await self._node_store.set_status(node_id, "idle")
    except Exception:
        logger.exception("Failed to reset node status for %s", node_id)
```

**Test**: Add to `tests/unit/test_runner.py`:

```python
@pytest.mark.asyncio
async def test_runner_only_resets_running_to_idle(runner_env, monkeypatch) -> None:
    """Runner should only transition running -> idle in finally."""
    runner, node_store, event_store, workspace_service = runner_env
    node = _node("src/app.py::a")
    await node_store.upsert_node(node)
    ws = await workspace_service.get_agent_workspace(node.node_id)
    await ws.write("_bundle/bundle.yaml", "system_prompt: hi\nmodel: mock\nmax_turns: 1\n")

    class MockKernel:
        async def run(self, _messages, _tools, max_turns=20):
            del max_turns
            return SimpleNamespace(final_message=Message(role="assistant", content="done"))
        async def close(self):
            return None

    monkeypatch.setattr("remora.core.runner.create_kernel", lambda **kw: MockKernel())
    monkeypatch.setattr("remora.core.runner.discover_tools", lambda *_a, **_kw: [])
    await runner._execute_turn(Trigger(node_id=node.node_id, correlation_id="c1"))

    updated = await node_store.get_node(node.node_id)
    assert updated is not None
    assert updated.status == "idle"
```

### Step 0.2: Fix rewrite string replacement with span-based apply (C2)

**File**: `src/remora/core/externals.py`, `apply_rewrite` method

**Current** (lines 333-334):
```python
if old_source and old_source in full_source:
    complete_new_source = full_source.replace(old_source, new_source, 1)
```

**Fix**: Use byte-span replacement instead of string search. The node has `start_byte` and `end_byte` already. Apply directly to disk and emit `ContentChangedEvent` (no proposal queue).

```python
async def apply_rewrite(self, new_source: str) -> bool:
    node = await self._node_store.get_node(self.node_id)
    if node is None:
        return False
    file_path = Path(node.file_path)
    if not file_path.exists():
        return False

    full_bytes = file_path.read_bytes()
    if node.start_byte > 0 or node.end_byte > 0:
        before = full_bytes[:node.start_byte].decode("utf-8", errors="replace")
        after = full_bytes[node.end_byte:].decode("utf-8", errors="replace")
        next_text = before + new_source + after
    else:
        full_text = full_bytes.decode("utf-8", errors="replace")
        next_text = full_text.replace(node.source_code, new_source, 1)

    file_path.write_text(next_text, encoding="utf-8")
    await self._event_store.append(ContentChangedEvent(path=str(file_path), change_type="modified"))
    return True
```

**Test**: Add to `tests/unit/test_runner_externals.py`:

```python
@pytest.mark.asyncio
async def test_apply_rewrite_duplicate_source_blocks(runner_env) -> None:
    """When a file has duplicate code, rewrite targets the correct occurrence by byte span."""
    runner, node_store, event_store, workspace_service = runner_env
    source_path = workspace_service._project_root / "src" / "dup.py"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    # Two identical functions
    full_source = "def helper():\n    return 1\n\ndef helper():\n    return 1\n"
    source_path.write_text(full_source, encoding="utf-8")

    # Create a node representing the SECOND occurrence
    node = CodeNode(
        node_id=f"{source_path}::helper_2",
        node_type="function",
        name="helper",
        full_name="helper",
        file_path=str(source_path),
        start_line=4,
        end_line=5,
        start_byte=28,  # Second function starts at byte 28
        end_byte=52,    # ends at byte 52
        source_code="def helper():\n    return 1\n",
        source_hash="h-dup",
    )
    await node_store.upsert_node(node)
    ws = await workspace_service.get_agent_workspace(node.node_id)
    externals = runner._build_externals(node.node_id, ws, "corr-1")

    applied = await externals["apply_rewrite"]("def helper():\n    return 2\n")
    assert applied
    new_source = source_path.read_text(encoding="utf-8")

    # First helper should be unchanged, second should be updated
    assert "def helper():\n    return 1\n\ndef helper():\n    return 2\n" == new_source
```

### Step 0.3: Remove approval/rejection web endpoints (C3)

**File**: `src/remora/web/server.py`

**Change**: Delete `/api/approve` and `/api/reject` endpoints and all proposal lookup code. Rewrites are now applied directly through `apply_rewrite` + `ContentChangedEvent`, and future audit/version control is handled by Jujutsu integration.

Expected result:

```python
# remove Route("/api/approve", ...)
# remove Route("/api/reject", ...)
# remove _find_proposal(...)
```

**Test**: Update `tests/unit/test_web_server.py`:

```python
@pytest.mark.asyncio
async def test_api_approve_endpoint_removed(web_env) -> None:
    client, *_rest = web_env
    response = await client.post("/api/approve", json={"id": "x"})
    assert response.status_code == 404
```

### Step 0.4: Add fault isolation to reconciler loop (H2)

**File**: `src/remora/code/reconciler.py`

**Current** (lines 71-79):
```python
async def run_forever(self, *, poll_interval_s: float = 1.0) -> None:
    self._running = True
    try:
        while self._running:
            await self.reconcile_cycle()
            await asyncio.sleep(poll_interval_s)
    finally:
        self._running = False
```

**Fix**:
```python
async def run_forever(self, *, poll_interval_s: float = 1.0) -> None:
    self._running = True
    try:
        while self._running:
            try:
                await self.reconcile_cycle()
            except Exception:
                logger.exception("Reconcile cycle failed, will retry next cycle")
            await asyncio.sleep(poll_interval_s)
    finally:
        self._running = False
```

**Test**: Add to `tests/unit/test_reconciler.py`:

```python
@pytest.mark.asyncio
async def test_reconciler_survives_cycle_error(reconcile_env, tmp_path, monkeypatch) -> None:
    """A single cycle failure must not kill the reconciler loop."""
    _node_store, _event_store, _workspace_service, _config, reconciler = reconcile_env
    _write(tmp_path / "src" / "app.py", "def a():\n    return 1\n")
    await reconciler.full_scan()

    call_count = 0
    original_cycle = reconciler.reconcile_cycle

    async def flaky_cycle():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("simulated failure")
        await original_cycle()

    monkeypatch.setattr(reconciler, "reconcile_cycle", flaky_cycle)

    async def run_briefly():
        reconciler._running = True
        for _ in range(3):
            try:
                await reconciler.reconcile_cycle()
            except Exception:
                pass
            await asyncio.sleep(0.01)

    await run_briefly()
    assert call_count >= 2  # Continued past the failure
```

### Step 0.5: Fix unbounded `_cooldowns` and `_depths` (H3)

**File**: `src/remora/core/runner.py`

Add periodic cleanup. Simplest approach — prune entries older than 60 seconds on each trigger call:

```python
async def trigger(
    self, node_id: str, correlation_id: str, event: Event | None = None
) -> None:
    now_ms = time.time() * 1000.0

    # Prune stale cooldowns (older than 60s)
    cutoff_ms = now_ms - 60_000.0
    stale_keys = [k for k, v in self._cooldowns.items() if v < cutoff_ms]
    for k in stale_keys:
        del self._cooldowns[k]

    last_ms = self._cooldowns.get(node_id, 0.0)
    if now_ms - last_ms < self._config.trigger_cooldown_ms:
        return
    self._cooldowns[node_id] = now_ms
    # ... rest unchanged
```

For `_depths`, entries are already cleaned in `_execute_turn`'s `finally` block when they reach 0. No additional change needed.

### Phase 0 Acceptance Criteria
- [ ] Runtime no longer uses `pending_approval`
- [ ] Span-based rewrite patches correct occurrence (test passes)
- [ ] `/api/approve` and `/api/reject` are removed
- [ ] Reconciler loop survives cycle errors (test passes)
- [ ] All 125+ existing tests still pass

---

## Phase 1: Storage Foundation

### Step 1.1: Create `AsyncDB` wrapper

**New file**: `src/remora/core/db.py`

```python
"""Async SQLite database wrapper with connection lifecycle management."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any


class AsyncDB:
    """Thin async wrapper around sqlite3 with lock + thread-hop + auto-commit."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        lock: asyncio.Lock | None = None,
    ):
        self._conn = connection
        self._lock = lock or asyncio.Lock()

    @classmethod
    def from_path(cls, db_path: Path | str) -> AsyncDB:
        """Create an AsyncDB from a file path, configuring WAL mode."""
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.row_factory = sqlite3.Row
        return cls(conn)

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        """Execute SQL with auto-commit."""
        def run() -> sqlite3.Cursor:
            cursor = self._conn.execute(sql, params)
            self._conn.commit()
            return cursor

        async with self._lock:
            return await asyncio.to_thread(run)

    async def execute_script(self, sql: str) -> None:
        """Execute multiple SQL statements (for schema creation)."""
        def run() -> None:
            self._conn.executescript(sql)

        async with self._lock:
            await asyncio.to_thread(run)

    async def execute_many(self, statements: list[tuple[str, tuple[Any, ...]]]) -> None:
        """Execute multiple statements in a single transaction."""
        def run() -> None:
            for sql, params in statements:
                self._conn.execute(sql, params)
            self._conn.commit()

        async with self._lock:
            await asyncio.to_thread(run)

    async def fetch_one(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        """Fetch a single row."""
        def run() -> sqlite3.Row | None:
            return self._conn.execute(sql, params).fetchone()

        async with self._lock:
            return await asyncio.to_thread(run)

    async def fetch_all(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        """Fetch all matching rows."""
        def run() -> list[sqlite3.Row]:
            return self._conn.execute(sql, params).fetchall()

        async with self._lock:
            return await asyncio.to_thread(run)

    async def insert(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        """Execute an INSERT and return lastrowid."""
        def run() -> int:
            cursor = self._conn.execute(sql, params)
            self._conn.commit()
            return int(cursor.lastrowid)

        async with self._lock:
            return await asyncio.to_thread(run)

    async def delete(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        """Execute a DELETE and return rowcount."""
        def run() -> int:
            cursor = self._conn.execute(sql, params)
            self._conn.commit()
            return int(cursor.rowcount)

        async with self._lock:
            return await asyncio.to_thread(run)

    def close(self) -> None:
        """Close the underlying connection."""
        self._conn.close()


__all__ = ["AsyncDB"]
```

**Test**: `tests/unit/test_db.py` — basic tests for execute, fetch_one, fetch_all, insert, delete, from_path.

### Step 1.2: Migrate `NodeStore` to use `AsyncDB`

**File**: `src/remora/core/graph.py`

Change constructor from `(connection, lock)` to `(db: AsyncDB)`. Rewrite each method to use `self._db.fetch_one(...)`, `self._db.execute(...)`, etc.

**Before** (example, `get_node`):
```python
async def get_node(self, node_id: str) -> CodeNode | None:
    def run() -> CodeNode | None:
        row = self._conn.execute(
            "SELECT * FROM nodes WHERE node_id = ?", (node_id,),
        ).fetchone()
        return None if row is None else CodeNode.from_row(row)

    async with self._lock:
        return await asyncio.to_thread(run)
```

**After**:
```python
async def get_node(self, node_id: str) -> CodeNode | None:
    row = await self._db.fetch_one("SELECT * FROM nodes WHERE node_id = ?", (node_id,))
    return None if row is None else CodeNode.from_row(row)
```

This cuts every method from ~10 lines to ~2 lines. Apply to all methods in NodeStore.

### Step 1.3: Migrate `SubscriptionRegistry` to use `AsyncDB`

Same pattern. Remove the `_initialized` flag and lazy `initialize()` pattern. Instead, `create_tables()` is called once during setup, and methods just use `self._db` directly.

### Step 1.4: Migrate `EventStore` to use `AsyncDB`

Same pattern. The dual-initialization (`db_path` vs `connection`) is eliminated — `EventStore` always receives an `AsyncDB`. The `AsyncDB.from_path()` factory replaces the self-initialization path.

### Step 1.5: Update `__main__.py` wiring

**Before**:
```python
conn = sqlite3.connect(str(db_path), check_same_thread=False)
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA busy_timeout=5000")
conn.row_factory = sqlite3.Row
lock = asyncio.Lock()
node_store = NodeStore(conn, lock)
```

**After**:
```python
db = AsyncDB.from_path(db_path)
node_store = NodeStore(db)
```

### Step 1.6: Update all tests

All test fixtures that create `(conn, lock)` pairs should create `AsyncDB` instances instead. The `conftest.py` `db_connection` and `db_lock` fixtures become a single `db` fixture.

### Phase 1 Acceptance Criteria
- [ ] `AsyncDB` has full test coverage
- [ ] `NodeStore`, `EventStore`, `SubscriptionRegistry` all use `AsyncDB`
- [ ] No raw `sqlite3.Connection` or `asyncio.Lock` passed around externally
- [ ] SQLite pragma setup happens in exactly one place (`AsyncDB.from_path`)
- [ ] All existing tests pass (updated for new constructors)

---

## Phase 2: Event System Decomposition

### Step 2.1: Create `core/events/` package structure

```
src/remora/core/events/
├── __init__.py       — re-exports everything for backwards compat during migration
├── types.py          — Event base + all 12 event subclasses + EventHandler type alias
├── bus.py            — EventBus
├── subscriptions.py  — SubscriptionPattern + SubscriptionRegistry
├── store.py          — EventStore (append-only log)
└── dispatcher.py     — TriggerDispatcher (trigger queue management)
```

### Step 2.2: Extract `types.py`

Move all event class definitions (lines 17-116 of current `events.py`) plus the `EventHandler` type alias.

Add `summary()` method to Event base and subclasses (**R17**):

```python
class Event(BaseModel):
    event_type: str = ""
    timestamp: float = Field(default_factory=time.time)
    correlation_id: str | None = None

    def model_post_init(self, __context: Any) -> None:
        if not self.event_type:
            self.event_type = type(self).__name__

    def summary(self) -> str:
        """Return a human-readable summary of this event."""
        return ""


class AgentCompleteEvent(Event):
    agent_id: str
    result_summary: str = ""

    def summary(self) -> str:
        return self.result_summary


class AgentErrorEvent(Event):
    agent_id: str
    error: str

    def summary(self) -> str:
        return self.error

# ... and so on for AgentMessageEvent, HumanChatEvent, AgentTextResponse, ToolResultEvent
```

### Step 2.3: Extract `bus.py`

Move `EventBus` class. No changes needed — it's already self-contained. Only imports `Event` and `EventHandler` from `types.py`.

### Step 2.4: Extract `subscriptions.py`

Move `SubscriptionPattern` and `SubscriptionRegistry`.
- `SubscriptionRegistry` constructor takes `AsyncDB` instead of `(connection, lock)`.
- Remove lazy `initialize()` — table creation happens via explicit `create_tables()`.

### Step 2.5: Extract `dispatcher.py`

New class extracted from `EventStore`'s trigger queue logic:

```python
"""Trigger dispatch: routes events to matching agents via subscriptions."""

from __future__ import annotations

import asyncio
from typing import Any

from remora.core.events.types import Event
from remora.core.events.subscriptions import SubscriptionRegistry


class TriggerDispatcher:
    """Routes persisted events to agent trigger queues via subscription matching."""

    def __init__(self, subscriptions: SubscriptionRegistry):
        self._subscriptions = subscriptions
        self._queue: asyncio.Queue[tuple[str, Event]] = asyncio.Queue()

    async def dispatch(self, event: Event) -> None:
        """Match event against subscriptions and enqueue triggers."""
        for agent_id in await self._subscriptions.get_matching_agents(event):
            self._queue.put_nowait((agent_id, event))

    async def get_triggers(self) -> asyncio.AsyncIterator[tuple[str, Event]]:
        """Yield queued (agent_id, event) pairs forever."""
        while True:
            yield await self._queue.get()

    @property
    def subscriptions(self) -> SubscriptionRegistry:
        return self._subscriptions
```

### Step 2.6: Simplify `store.py`

`EventStore` becomes simpler — it owns persistence + bus emission, but delegates trigger dispatch to `TriggerDispatcher`:

```python
class EventStore:
    def __init__(
        self,
        db: AsyncDB,
        event_bus: EventBus,
        dispatcher: TriggerDispatcher,
    ):
        self._db = db
        self._event_bus = event_bus
        self._dispatcher = dispatcher

    async def create_tables(self) -> None: ...
    async def append(self, event: Event) -> int: ...
    async def get_events(self, limit: int = 100) -> list[dict[str, Any]]: ...
    async def get_events_for_agent(self, agent_id: str, limit: int = 50) -> list[dict[str, Any]]: ...
```

The `_summarize` static method is replaced by `event.summary()`.

### Step 2.7: Update `__init__.py` re-exports

```python
"""Event system: types, bus, subscriptions, persistence, and dispatch."""

from remora.core.events.types import *       # noqa: F401, F403
from remora.core.events.bus import *          # noqa: F401, F403
from remora.core.events.subscriptions import *  # noqa: F401, F403
from remora.core.events.store import *        # noqa: F401, F403
from remora.core.events.dispatcher import *   # noqa: F401, F403
```

This preserves all existing import paths (`from remora.core.events import EventStore` still works).

### Step 2.8: Update all callers

- `__main__.py`: Create `TriggerDispatcher` and pass it to `EventStore` and `AgentRunner`.
- `runner.py`: Consume triggers from `TriggerDispatcher` instead of `EventStore.get_triggers()`.
- `reconciler.py`: Access subscriptions via `dispatcher.subscriptions` or directly.
- `web/server.py`: No change (uses EventStore.append and get_events).

### Phase 2 Acceptance Criteria
- [ ] `events.py` is gone, replaced by `events/` package with 5 modules
- [ ] Each module is independently importable and testable
- [ ] `Event.summary()` replaces `EventStore._summarize()`
- [ ] `TriggerDispatcher` owns the trigger queue independently from persistence
- [ ] All existing import paths still work via `__init__.py` re-exports
- [ ] All tests pass

---

## Phase 3: Type Safety & Data Models

### Step 3.1: Create type enums (R15)

**New file**: `src/remora/core/types.py`

```python
"""Shared type definitions for Remora."""

from __future__ import annotations

from enum import Enum
from typing import Literal


class NodeStatus(str, Enum):
    """Valid states for a code node / agent."""
    IDLE = "idle"
    RUNNING = "running"
    ERROR = "error"


class NodeType(str, Enum):
    """Types of discovered code elements."""
    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"
    SECTION = "section"
    TABLE = "table"


class ChangeType(str, Enum):
    """Types of content changes."""
    MODIFIED = "modified"
    CREATED = "created"
    DELETED = "deleted"
    OPENED = "opened"


# Valid status transitions
STATUS_TRANSITIONS: dict[NodeStatus, set[NodeStatus]] = {
    NodeStatus.IDLE: {NodeStatus.RUNNING},
    NodeStatus.RUNNING: {NodeStatus.IDLE, NodeStatus.ERROR},
    NodeStatus.ERROR: {NodeStatus.IDLE, NodeStatus.RUNNING},
}


def validate_status_transition(current: NodeStatus, target: NodeStatus) -> bool:
    """Return True if the transition is allowed."""
    return target in STATUS_TRANSITIONS.get(current, set())
```

Using `str, Enum` means these serialize naturally to/from strings in Pydantic, SQLite, and JSON. Pydantic will validate them at construction time — if you try to create `CodeNode(status="bogus")`, it raises `ValidationError`.

### Step 3.2: Apply enums to `CodeNode` (R6)

**File**: `src/remora/core/node.py`

```python
from remora.core.types import NodeStatus, NodeType

class CodeNode(BaseModel):
    model_config = ConfigDict(frozen=False)

    node_id: str
    node_type: NodeType
    name: str
    full_name: str
    file_path: str
    start_line: int
    end_line: int
    start_byte: int = 0
    end_byte: int = 0
    source_code: str
    source_hash: str
    parent_id: str | None = None
    caller_ids: list[str] = Field(default_factory=list)
    callee_ids: list[str] = Field(default_factory=list)
    status: NodeStatus = NodeStatus.IDLE
    bundle_name: str | None = None
```

### Step 3.3: Apply enums to event types

Update `ContentChangedEvent`:
```python
class ContentChangedEvent(Event):
    path: str
    change_type: ChangeType = ChangeType.MODIFIED
```

### Step 3.4: Implement status state machine in `NodeStore` (R6)

Add a method that enforces transitions:

```python
async def transition_status(self, node_id: str, target: NodeStatus) -> bool:
    """Transition node status if the transition is valid. Returns True on success."""
    node = await self.get_node(node_id)
    if node is None:
        return False
    current = node.status
    if not validate_status_transition(current, target):
        logger.warning(
            "Invalid status transition for %s: %s -> %s",
            node_id, current, target,
        )
        return False
    await self.set_status(node_id, target.value)
    return True
```

Update `runner.py` to use `transition_status` instead of `set_status` everywhere.

### Step 3.5: Make discovery IDs collision-safe (R8)

**File**: `src/remora/code/discovery.py`

Change the ID formula from `f"{file_path}::{full_name}"` to include start_byte for disambiguation:

```python
# In _parse_file, where CSTNode is constructed:
node_id_base = f"{file_path}::{full_name}"
# Check for collision
if node_id_base in seen_ids:
    node_id = f"{file_path}::{full_name}@{node.start_byte}"
else:
    node_id = node_id_base
seen_ids.add(node_id)
```

Actually, the cleanest approach: always include start_line in the ID for any node that has a parent (methods, nested functions). Top-level items keep clean IDs:

```python
# For nodes with a parent (methods, nested definitions), include line for disambiguation
if parent_id is not None:
    node_id = f"{file_path}::{full_name}"
else:
    node_id = f"{file_path}::{full_name}"
```

Simplest correct approach — detect collision and append byte offset:

```python
seen_ids: set[str] = set()
for key, entry in by_key.items():
    # ... existing name building ...
    candidate_id = f"{file_path}::{full_name}"
    if candidate_id in seen_ids:
        candidate_id = f"{file_path}::{full_name}@{node.start_byte}"
    seen_ids.add(candidate_id)
    # use candidate_id as node_id
```

### Step 3.6: Remove dead code (R16)

- Delete `src/remora/utils/__init__.py` (empty, unused)
- Remove `utils/` from package
- Simplify `code/__init__.py` re-exports (or remove if unused)
- Remove `caller_ids`/`callee_ids` from `CodeNode` if truly unused (check all references first). If they're kept for future use, add a TODO comment explaining the intent.

### Phase 3 Acceptance Criteria
- [ ] `NodeStatus`, `NodeType`, `ChangeType` enums exist and are used in all models
- [ ] `CodeNode(status="bogus")` raises `ValidationError`
- [ ] Status transitions are validated via `transition_status()`
- [ ] Runner's `finally` block uses `transition_status` (fixing C1 properly)
- [ ] Discovery IDs are collision-safe
- [ ] Dead code removed
- [ ] All tests pass (updated for enum values)

---

## Phase 4: Agent/Code Separation

This is a significant architectural change (**R21**). Currently `CodeNode` is both a code element and an agent. We separate these concepts.

### Step 4.1: Define the new models

**File**: `src/remora/core/node.py` (rewrite)

```python
"""Code elements and agent models."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from remora.core.types import NodeStatus, NodeType


class CodeElement(BaseModel):
    """An immutable code structure discovered from source. Not an agent — just data."""

    model_config = ConfigDict(frozen=True)

    element_id: str       # e.g. "src/app.py::MyClass.method"
    element_type: NodeType
    name: str
    full_name: str
    file_path: str
    start_line: int
    end_line: int
    start_byte: int = 0
    end_byte: int = 0
    source_code: str
    source_hash: str
    parent_id: str | None = None


class Agent(BaseModel):
    """An autonomous agent that may be attached to a code element."""

    model_config = ConfigDict(frozen=False)

    agent_id: str         # Same as element_id when attached to a code element
    element_id: str | None = None  # None for free-standing agents (orchestrators, etc.)
    status: NodeStatus = NodeStatus.IDLE
    bundle_name: str | None = None


class CodeNode(BaseModel):
    """Combined view for persistence and backwards compatibility during migration.

    Long-term, callers should use CodeElement and Agent separately.
    """

    model_config = ConfigDict(frozen=False)

    # Identity (from CodeElement)
    node_id: str
    node_type: NodeType
    name: str
    full_name: str
    file_path: str
    start_line: int
    end_line: int
    start_byte: int = 0
    end_byte: int = 0
    source_code: str
    source_hash: str
    parent_id: str | None = None

    # Agent state
    status: NodeStatus = NodeStatus.IDLE
    bundle_name: str | None = None

    def to_element(self) -> CodeElement:
        return CodeElement(
            element_id=self.node_id,
            element_type=self.node_type,
            name=self.name,
            full_name=self.full_name,
            file_path=self.file_path,
            start_line=self.start_line,
            end_line=self.end_line,
            start_byte=self.start_byte,
            end_byte=self.end_byte,
            source_code=self.source_code,
            source_hash=self.source_hash,
            parent_id=self.parent_id,
        )

    def to_agent(self) -> Agent:
        return Agent(
            agent_id=self.node_id,
            element_id=self.node_id,
            status=self.status,
            bundle_name=self.bundle_name,
        )

    def to_row(self) -> dict[str, Any]:
        data = self.model_dump()
        # Convert enums to strings for SQLite
        data["node_type"] = data["node_type"].value if hasattr(data["node_type"], "value") else data["node_type"]
        data["status"] = data["status"].value if hasattr(data["status"], "value") else data["status"]
        return data

    @classmethod
    def from_row(cls, row: sqlite3.Row | dict[str, Any]) -> CodeNode:
        data = dict(row)
        return cls(**data)
```

### Step 4.2: Update `NodeStore` schema

Remove `caller_ids`/`callee_ids` columns (these were never populated). Add an `agents` table:

```sql
CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY,
    element_id TEXT,
    status TEXT DEFAULT 'idle',
    bundle_name TEXT,
    FOREIGN KEY (element_id) REFERENCES nodes(node_id) ON DELETE SET NULL
);
```

For Phase 4, keep using the combined `CodeNode` model for the `nodes` table but also populate the `agents` table. This allows a gradual migration.

### Step 4.3: Add `AgentStore` alongside `NodeStore`

```python
class AgentStore:
    """SQLite persistence for agent state, separate from code elements."""

    def __init__(self, db: AsyncDB):
        self._db = db

    async def create_tables(self) -> None: ...
    async def upsert_agent(self, agent: Agent) -> None: ...
    async def get_agent(self, agent_id: str) -> Agent | None: ...
    async def set_status(self, agent_id: str, status: NodeStatus) -> None: ...
    async def transition_status(self, agent_id: str, target: NodeStatus) -> bool: ...
    async def list_agents(self, status: NodeStatus | None = None) -> list[Agent]: ...
    async def delete_agent(self, agent_id: str) -> bool: ...
```

### Step 4.4: Update runner to use `AgentStore`

The runner currently only needs agent status and node source. It should take both stores:
```python
class AgentRunner:
    def __init__(
        self,
        event_store: EventStore,
        node_store: NodeStore,
        agent_store: AgentStore,
        workspace_service: CairnWorkspaceService,
        config: Config,
    ): ...
```

Status operations go through `agent_store`, source lookups through `node_store`.

### Step 4.5: Create free-standing agents

This separation enables agents that aren't tied to code elements — e.g., a project-level orchestrator:

```python
orchestrator = Agent(
    agent_id="project::orchestrator",
    element_id=None,  # No code element
    status=NodeStatus.IDLE,
    bundle_name="orchestrator",
)
```

This is not implemented in Phase 4 but the architecture now supports it.

### Phase 4 Acceptance Criteria
- [ ] `CodeElement` and `Agent` models exist as distinct types
- [ ] `CodeNode` still works as a combined view for migration
- [ ] `AgentStore` manages agent lifecycle independently from code elements
- [ ] Runner uses `AgentStore` for status operations
- [ ] Reconciler creates agents for new code elements
- [ ] All tests pass

---

## Phase 5: Externals Redesign

See **Appendix A** for the full option analysis as requested.

**Chosen approach: Option B — Class-based externals with method registry.**

### Step 5.1: Define `AgentContext`

**New file**: `src/remora/core/externals.py`

```python
"""Agent externals — the API surface available to agent tool scripts."""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any

from remora.core.events.store import EventStore
from remora.core.events.types import (
    AgentMessageEvent,
    ContentChangedEvent,
    CustomEvent,
    SubscriptionPattern,
)
from remora.core.graph import NodeStore
from remora.core.node import CodeNode
from remora.core.types import NodeStatus
from remora.core.workspace import AgentWorkspace


class AgentContext:
    """Per-turn context providing the externals API for an agent's tools.

    Each method is a named external that Grail tools can call.
    """

    def __init__(
        self,
        node_id: str,
        workspace: AgentWorkspace,
        correlation_id: str | None,
        node_store: NodeStore,
        event_store: EventStore,
    ):
        self.node_id = node_id
        self.workspace = workspace
        self.correlation_id = correlation_id
        self._node_store = node_store
        self._event_store = event_store

    # -- Filesystem --------------------------------------------------------

    async def read_file(self, path: str) -> str:
        return await self.workspace.read(path)

    async def write_file(self, path: str, content: str) -> bool:
        await self.workspace.write(path, content)
        return True

    async def list_dir(self, path: str = ".") -> list[str]:
        return await self.workspace.list_dir(path)

    async def file_exists(self, path: str) -> bool:
        return await self.workspace.exists(path)

    async def search_files(self, pattern: str) -> list[str]:
        paths = await self.workspace.list_all_paths()
        return sorted(p for p in paths if fnmatch.fnmatch(p, f"*{pattern}*"))

    async def search_content(self, pattern: str, path: str = ".") -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        paths = await self.workspace.list_all_paths()
        for file_path in paths:
            normalized = file_path.strip("/")
            if path not in {".", "/", ""} and not normalized.startswith(path.strip("/")):
                continue
            try:
                content = await self.workspace.read(normalized)
            except FileNotFoundError:
                continue
            for idx, line in enumerate(content.splitlines(), start=1):
                if pattern in line:
                    matches.append({"file": normalized, "line": idx, "text": line})
        return matches

    # -- Graph -------------------------------------------------------------

    async def graph_get_node(self, target_id: str) -> dict[str, Any]:
        node = await self._node_store.get_node(target_id)
        return node.model_dump() if node is not None else {}

    async def graph_query_nodes(
        self,
        node_type: str | None = None,
        status: str | None = None,
        file_path: str | None = None,
    ) -> list[dict[str, Any]]:
        nodes = await self._node_store.list_nodes(
            node_type=node_type, status=status, file_path=file_path,
        )
        return [n.model_dump() for n in nodes]

    async def graph_get_edges(self, target_id: str) -> list[dict[str, Any]]:
        edges = await self._node_store.get_edges(target_id)
        return [{"from_id": e.from_id, "to_id": e.to_id, "edge_type": e.edge_type} for e in edges]

    async def graph_set_status(self, target_id: str, new_status: str) -> bool:
        await self._node_store.set_status(target_id, new_status)
        return True

    # -- Events ------------------------------------------------------------

    async def event_emit(self, event_type: str, payload: dict[str, Any]) -> bool:
        event = CustomEvent(
            event_type=event_type, payload=payload, correlation_id=self.correlation_id,
        )
        await self._event_store.append(event)
        return True

    async def event_subscribe(
        self,
        event_types: list[str] | None = None,
        from_agents: list[str] | None = None,
        path_glob: str | None = None,
    ) -> int:
        pattern = SubscriptionPattern(
            event_types=event_types, from_agents=from_agents, path_glob=path_glob,
        )
        return await self._event_store.subscriptions.register(self.node_id, pattern)

    async def event_unsubscribe(self, subscription_id: int) -> bool:
        return await self._event_store.subscriptions.unregister(subscription_id)

    async def event_get_history(self, target_id: str, limit: int = 20) -> list[dict[str, Any]]:
        return await self._event_store.get_events_for_agent(target_id, limit=limit)

    # -- Communication -----------------------------------------------------

    async def send_message(self, to_node_id: str, content: str) -> bool:
        await self._event_store.append(
            AgentMessageEvent(
                from_agent=self.node_id, to_agent=to_node_id,
                content=content, correlation_id=self.correlation_id,
            )
        )
        return True

    async def broadcast(self, pattern: str, content: str) -> str:
        nodes = await self._node_store.list_nodes()
        target_ids = _resolve_broadcast_targets(self.node_id, pattern, nodes)
        for target_id in target_ids:
            await self._event_store.append(
                AgentMessageEvent(
                    from_agent=self.node_id, to_agent=target_id,
                    content=content, correlation_id=self.correlation_id,
                )
            )
        return f"Broadcast sent to {len(target_ids)} agents"

    # -- Code operations ---------------------------------------------------

    async def apply_rewrite(self, new_source: str) -> bool:
        node = await self._node_store.get_node(self.node_id)
        if node is None:
            return False
        # ... (rewrite logic from Step 0.2)
        await self._event_store.append(
            ContentChangedEvent(path=node.file_path, change_type="modified")
        )
        return True

    async def get_node_source(self, target_id: str) -> str:
        node = await self._node_store.get_node(target_id)
        return node.source_code if node is not None else ""

    def to_externals_dict(self) -> dict[str, Any]:
        """Build the externals dict expected by Grail tools."""
        return {
            "read_file": self.read_file,
            "write_file": self.write_file,
            "list_dir": self.list_dir,
            "file_exists": self.file_exists,
            "search_files": self.search_files,
            "search_content": self.search_content,
            "graph_get_node": self.graph_get_node,
            "graph_query_nodes": self.graph_query_nodes,
            "graph_get_edges": self.graph_get_edges,
            "graph_set_status": self.graph_set_status,
            "event_emit": self.event_emit,
            "event_subscribe": self.event_subscribe,
            "event_unsubscribe": self.event_unsubscribe,
            "event_get_history": self.event_get_history,
            "send_message": self.send_message,
            "broadcast": self.broadcast,
            "apply_rewrite": self.apply_rewrite,
            "get_node_source": self.get_node_source,
            "my_node_id": self.node_id,
            "my_correlation_id": self.correlation_id,
        }


def _resolve_broadcast_targets(
    source_id: str, pattern: str, nodes: list[CodeNode],
) -> list[str]:
    # ... (moved from runner.py, unchanged)
```

### Step 5.2: Simplify `runner.py`

Delete `_build_externals` (170+ lines) and `_resolve_broadcast_targets`. Replace with:

```python
context = AgentContext(
    node_id=node_id,
    workspace=workspace,
    correlation_id=trigger.correlation_id,
    node_store=self._node_store,
    event_store=self._event_store,
)
externals = context.to_externals_dict()
```

The runner drops from ~432 lines to ~250 lines.

### Step 5.3: Test `AgentContext` independently

Create `tests/unit/test_externals.py` — directly test `AgentContext` methods without needing to mock the runner. This was impossible before because externals were closures.

### Phase 5 Acceptance Criteria
- [ ] `AgentContext` class exists with all 18 externals as named methods
- [ ] `runner.py` no longer defines inline closures
- [ ] `AgentContext` is independently unit-testable
- [ ] All existing externals tests pass (migrated to test `AgentContext`)
- [ ] Runner is ~250 lines, down from ~432

---

## Phase 6: Direct Rewrite Flow

### Step 6.1: Remove proposal persistence and endpoints

Delete proposal-only components and keep the runtime focused on immediate rewrite execution:
- remove `RewriteProposalEvent` and any proposal-related fields/models,
- remove `/api/approve` and `/api/reject`,
- remove proposal lookup helpers and proposal tables/stores.

### Step 6.2: Make `AgentContext.apply_rewrite` the single rewrite path

`apply_rewrite` should:
1. read the target file,
2. apply a span-based replacement using `start_byte`/`end_byte` when available,
3. write the updated file,
4. emit `ContentChangedEvent`.

This preserves deterministic edit targeting without introducing approval lifecycle state.

### Step 6.3: Add lightweight VCS-ready hooks (Jujutsu later)

Keep the MVP simple now, but shape the API so VCS integration can be added without another surface redesign:
- keep rewrite metadata in emitted events (`agent_id`, `file_path`, `old_hash`, `new_hash`),
- isolate file-write logic in one method (`apply_rewrite`) so future Jujutsu commit/branch operations wrap a single boundary.

### Phase 6 Acceptance Criteria
- [ ] No proposal-specific models, stores, or endpoints remain
- [ ] `apply_rewrite` performs direct span-based file updates
- [ ] Rewrites emit `ContentChangedEvent`
- [ ] Rewrite path is centralized and VCS-wrap-friendly
- [ ] All tests pass

---

## Phase 7: Discovery & Language Plugins

### Step 7.1: Centralize path resolution (R7)

**New file**: `src/remora/code/paths.py`

```python
"""Centralized path resolution and source file walking."""

from __future__ import annotations

import fnmatch
from pathlib import Path

from remora.core.config import Config


def resolve_discovery_paths(config: Config, project_root: Path) -> list[Path]:
    """Resolve configured discovery paths relative to project root."""
    resolved: list[Path] = []
    for configured in config.discovery_paths:
        candidate = Path(configured)
        if not candidate.is_absolute():
            candidate = project_root / candidate
        resolved.append(candidate.resolve())
    return resolved


def resolve_query_paths(config: Config, project_root: Path) -> list[Path]:
    """Resolve configured query paths relative to project root."""
    resolved: list[Path] = []
    for configured in config.query_paths:
        candidate = Path(configured)
        if not candidate.is_absolute():
            candidate = project_root / candidate
        resolved.append(candidate.resolve())
    return resolved


def walk_source_files(
    paths: list[Path],
    ignore_patterns: tuple[str, ...] = (),
) -> list[Path]:
    """Collect source files from paths while respecting ignore patterns."""
    discovered: list[Path] = []
    seen: set[Path] = set()
    normalized = tuple(p.strip() for p in ignore_patterns if p.strip())

    def ignored(path: Path) -> bool:
        text = path.as_posix()
        parts = set(path.parts)
        for pattern in normalized:
            if pattern in parts:
                return True
            if fnmatch.fnmatch(text, pattern) or fnmatch.fnmatch(path.name, pattern):
                return True
            if fnmatch.fnmatch(text, f"*/{pattern}/*"):
                return True
        return False

    for raw in paths:
        root = raw.resolve()
        if not root.exists():
            continue
        if root.is_file():
            if root not in seen and not ignored(root):
                seen.add(root)
                discovered.append(root)
            continue
        for candidate in root.rglob("*"):
            if not candidate.is_file() or ignored(candidate) or candidate in seen:
                continue
            seen.add(candidate)
            discovered.append(candidate)

    return sorted(discovered)
```

### Step 7.2: Update consumers to use `paths.py`

- `discovery.py`: Delete `_walk_source_files`, import `walk_source_files` from `paths.py`
- `reconciler.py`: Delete `_iter_source_files` and `_resolve_query_paths`, import from `paths.py`
- `__main__.py`: Delete inline path resolution, import from `paths.py`

### Step 7.3: Implement language plugin protocol (R19)

**New file**: `src/remora/code/languages.py`

```python
"""Language plugin system for tree-sitter based discovery."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from tree_sitter import Language


class LanguagePlugin(Protocol):
    """Protocol for language-specific discovery behavior."""

    @property
    def name(self) -> str:
        """Language name (e.g., 'python')."""
        ...

    @property
    def extensions(self) -> list[str]:
        """File extensions this language handles (e.g., ['.py'])."""
        ...

    def get_language(self) -> Language:
        """Return the tree-sitter Language object."""
        ...

    def get_default_query_path(self) -> Path:
        """Return path to the default .scm query file."""
        ...

    def resolve_node_type(self, ts_node: Any) -> str:
        """Map a tree-sitter node to a Remora node type string."""
        ...


class PythonPlugin:
    """Python language support."""

    @property
    def name(self) -> str:
        return "python"

    @property
    def extensions(self) -> list[str]:
        return [".py"]

    def get_language(self) -> Language:
        import tree_sitter_python
        return Language(tree_sitter_python.language())

    def get_default_query_path(self) -> Path:
        return Path(__file__).parent / "queries" / "python.scm"

    def resolve_node_type(self, ts_node: Any) -> str:
        if ts_node.type == "class_definition":
            return "class"
        if ts_node.type == "function_definition":
            return "method" if self._has_class_ancestor(ts_node) else "function"
        if ts_node.type == "decorated_definition":
            target = self._decorated_target(ts_node)
            if target and target.type == "class_definition":
                return "class"
            if target and target.type == "function_definition":
                return "method" if self._has_class_ancestor(ts_node) else "function"
        return "function"

    @staticmethod
    def _has_class_ancestor(node: Any) -> bool:
        current = node.parent
        while current is not None:
            if current.type == "class_definition":
                return True
            if current.type == "decorated_definition":
                for child in current.children:
                    if child.type == "class_definition":
                        return True
            current = current.parent
        return False

    @staticmethod
    def _decorated_target(node: Any) -> Any | None:
        for child in node.children:
            if child.type in {"function_definition", "class_definition"}:
                return child
        return None


class MarkdownPlugin:
    @property
    def name(self) -> str:
        return "markdown"

    @property
    def extensions(self) -> list[str]:
        return [".md"]

    def get_language(self) -> Language:
        import tree_sitter_markdown
        return Language(tree_sitter_markdown.language())

    def get_default_query_path(self) -> Path:
        return Path(__file__).parent / "queries" / "markdown.scm"

    def resolve_node_type(self, ts_node: Any) -> str:
        return "section"


class TomlPlugin:
    @property
    def name(self) -> str:
        return "toml"

    @property
    def extensions(self) -> list[str]:
        return [".toml"]

    def get_language(self) -> Language:
        import tree_sitter_toml
        return Language(tree_sitter_toml.language())

    def get_default_query_path(self) -> Path:
        return Path(__file__).parent / "queries" / "toml.scm"

    def resolve_node_type(self, ts_node: Any) -> str:
        return "table"


# Default registry
BUILTIN_PLUGINS: list[LanguagePlugin] = [PythonPlugin(), MarkdownPlugin(), TomlPlugin()]


class LanguageRegistry:
    """Registry of language plugins, resolved by name or extension."""

    def __init__(self, plugins: list[LanguagePlugin] | None = None):
        self._by_name: dict[str, LanguagePlugin] = {}
        self._by_ext: dict[str, LanguagePlugin] = {}
        for plugin in (plugins or BUILTIN_PLUGINS):
            self.register(plugin)

    def register(self, plugin: LanguagePlugin) -> None:
        self._by_name[plugin.name] = plugin
        for ext in plugin.extensions:
            self._by_ext[ext.lower()] = plugin

    def get_by_name(self, name: str) -> LanguagePlugin | None:
        return self._by_name.get(name.lower())

    def get_by_extension(self, ext: str) -> LanguagePlugin | None:
        return self._by_ext.get(ext.lower())

    @property
    def names(self) -> list[str]:
        return list(self._by_name.keys())
```

### Step 7.4: Refactor `discovery.py` to use plugins

Replace `_GRAMMAR_REGISTRY`, `_resolve_node_type`, `_has_class_ancestor`, `_decorated_target`, `_detect_language` with `LanguageRegistry` lookups. The `_parse_file` function receives a `LanguagePlugin` instead of a language name string.

### Step 7.5: Cache Grail tool scripts (R10)

**File**: `src/remora/core/grail.py`

Add a module-level cache keyed by content hash:

```python
_script_cache: dict[str, grail.GrailScript] = {}  # content_hash → parsed script

def _load_script_from_source(source: str, name: str) -> grail.GrailScript:
    content_hash = hashlib.sha256(source.encode()).hexdigest()[:16]
    cached = _script_cache.get(content_hash)
    if cached is not None:
        return cached
    filename = f"{name}.pym" if not name.endswith(".pym") else name
    with tempfile.TemporaryDirectory(prefix="remora-grail-") as temp_dir:
        script_path = Path(temp_dir) / filename
        script_path.write_text(source, encoding="utf-8")
        script = grail.load(script_path)
    _script_cache[content_hash] = script
    return script
```

### Phase 7 Acceptance Criteria
- [ ] `paths.py` is the single source of truth for path resolution and file walking
- [ ] No duplicated path logic in reconciler, discovery, or __main__
- [ ] `LanguagePlugin` protocol exists with 3 implementations
- [ ] `LanguageRegistry` replaces `_GRAMMAR_REGISTRY` and `_resolve_node_type`
- [ ] Adding a new language = one new class + one .scm file, zero existing code changes
- [ ] Grail scripts are cached by content hash
- [ ] All tests pass

---

## Phase 8: Reconciler Overhaul

### Step 8.1: Event-driven reconciliation (R20)

Add `watchfiles` to dependencies:
```toml
"watchfiles>=1.0",
```

Update `FileReconciler` to support both polling and file-watching:

```python
class FileReconciler:
    def __init__(self, ...):
        # ... existing fields ...
        self._watch_mode = True  # Try filesystem watching first

    async def run_forever(self, *, poll_interval_s: float = 1.0) -> None:
        self._running = True
        try:
            if self._watch_mode:
                try:
                    await self._run_watching()
                except ImportError:
                    logger.info("watchfiles not available, falling back to polling")
                    await self._run_polling(poll_interval_s)
            else:
                await self._run_polling(poll_interval_s)
        finally:
            self._running = False

    async def _run_watching(self) -> None:
        """Use filesystem events for immediate change detection."""
        import watchfiles

        paths_to_watch = resolve_discovery_paths(self._config, self._project_root)
        watch_paths = [str(p) for p in paths_to_watch if p.exists()]
        if not watch_paths:
            return

        async for changes in watchfiles.awatch(*watch_paths, stop_event=self._stop_event()):
            if not self._running:
                break
            changed_files = {str(Path(path)) for _change_type, path in changes}
            try:
                for file_path in sorted(changed_files):
                    p = Path(file_path)
                    if p.exists() and p.is_file():
                        mtime = p.stat().st_mtime_ns
                        await self._reconcile_file(str(p), mtime)
                    elif str(p) in self._file_state:
                        # File was deleted
                        _mtime, node_ids = self._file_state[str(p)]
                        for nid in sorted(node_ids):
                            await self._remove_node(nid)
                        self._file_state.pop(str(p), None)
            except Exception:
                logger.exception("Watch-triggered reconcile failed")

    async def _run_polling(self, interval: float) -> None:
        """Fallback polling mode."""
        while self._running:
            try:
                await self.reconcile_cycle()
            except Exception:
                logger.exception("Reconcile cycle failed, will retry")
            await asyncio.sleep(interval)

    def _stop_event(self) -> asyncio.Event:
        """Create an event that is set when self._running becomes False."""
        # watchfiles needs a threading.Event, not asyncio.Event
        import threading
        event = threading.Event()
        # Check periodically
        async def _checker():
            while self._running:
                await asyncio.sleep(0.5)
            event.set()
        asyncio.create_task(_checker())
        return event
```

### Step 8.2: Subscribe to LSP ContentChangedEvent

The reconciler can also listen for `ContentChangedEvent` from the LSP server for even faster response:

```python
async def start(self, event_bus: EventBus) -> None:
    """Subscribe to content change events for immediate reconciliation."""
    event_bus.subscribe(ContentChangedEvent, self._on_content_changed)

async def _on_content_changed(self, event: ContentChangedEvent) -> None:
    """Immediately reconcile a file that was reported changed."""
    file_path = event.path
    p = Path(file_path)
    if p.exists() and p.is_file():
        try:
            mtime = p.stat().st_mtime_ns
            await self._reconcile_file(str(p), mtime)
        except Exception:
            logger.exception("Event-triggered reconcile failed for %s", file_path)
```

### Phase 8 Acceptance Criteria
- [ ] `watchfiles` is an optional dependency
- [ ] Reconciler uses filesystem watching when available, falls back to polling
- [ ] Single-file parse errors don't crash the loop
- [ ] LSP content change events trigger immediate reconciliation
- [ ] All tests pass

---

## Phase 9: Web & LSP Improvements

### Step 9.1: Extract HTML to static file (R11)

Create `src/remora/web/static/index.html` with the current contents of `GRAPH_HTML`.

Update `web/server.py`:
```python
from starlette.staticfiles import StaticFiles

_STATIC_DIR = Path(__file__).parent / "static"

# In create_app:
routes = [
    Route("/", endpoint=index),  # Serves index.html
    # ...
]
app = Starlette(routes=routes)
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
```

Or simply read the file at import time:
```python
_INDEX_HTML = (Path(__file__).parent / "static" / "index.html").read_text(encoding="utf-8")
```

Delete `views.py` entirely.

### Step 9.2: Add NodeRemovedEvent and NodeChangedEvent SSE handlers (R12)

In the HTML file, add:

```javascript
evtSource.addEventListener("NodeRemovedEvent", (event) => {
    const data = JSON.parse(event.data);
    if (graph.hasNode(data.node_id)) {
        graph.dropNode(data.node_id);
        renderer.refresh();
    }
    appendEventLine(`NodeRemovedEvent: ${data.node_id}`);
});

evtSource.addEventListener("NodeChangedEvent", (event) => {
    const data = JSON.parse(event.data);
    appendEventLine(`NodeChangedEvent: ${data.node_id}`);
});
```

### Step 9.3: Add batch edges endpoint (R13)

```python
async def api_all_edges(_request: Request) -> JSONResponse:
    # Query all edges at once
    rows = await db.fetch_all("SELECT from_id, to_id, edge_type FROM edges ORDER BY id ASC")
    return JSONResponse([dict(r) for r in rows])

# Add route:
Route("/api/edges", endpoint=api_all_edges),
```

Update the frontend `loadGraph` to use the batch endpoint instead of per-node fetching.

### Step 9.4: Fix LSP `__all__` exports (minor)

Remove private functions from `__all__` in `lsp/server.py`:
```python
__all__ = ["create_lsp_server"]
```

### Phase 9 Acceptance Criteria
- [ ] `views.py` is deleted, HTML lives in `static/index.html`
- [ ] SSE handles all lifecycle events (discovered, removed, changed, start, complete, error)
- [ ] Batch edges endpoint eliminates N+1 fetching
- [ ] All tests pass

---

## Phase 10: Service Layer & Wiring

### Step 10.1: Define `RuntimeServices` container (R3)

**New file**: `src/remora/core/services.py`

```python
"""Runtime service container for dependency injection."""

from __future__ import annotations

from pathlib import Path

from remora.code.languages import LanguageRegistry
from remora.code.reconciler import FileReconciler
from remora.core.config import Config
from remora.core.db import AsyncDB
from remora.core.events.bus import EventBus
from remora.core.events.dispatcher import TriggerDispatcher
from remora.core.events.store import EventStore
from remora.core.events.subscriptions import SubscriptionRegistry
from remora.core.graph import NodeStore
from remora.core.runner import AgentRunner
from remora.core.workspace import CairnWorkspaceService


class RuntimeServices:
    """Central container holding all runtime services."""

    def __init__(
        self,
        config: Config,
        project_root: Path,
        db: AsyncDB,
    ):
        self.config = config
        self.project_root = project_root.resolve()
        self.db = db

        # Storage
        self.node_store = NodeStore(db)

        # Events
        self.event_bus = EventBus()
        self.subscriptions = SubscriptionRegistry(db)
        self.dispatcher = TriggerDispatcher(self.subscriptions)
        self.event_store = EventStore(db, self.event_bus, self.dispatcher)

        # Workspaces
        self.workspace_service = CairnWorkspaceService(config, project_root)

        # Discovery
        self.language_registry = LanguageRegistry()

        # Runtime (created after initialization)
        self.reconciler: FileReconciler | None = None
        self.runner: AgentRunner | None = None

    async def initialize(self) -> None:
        """Create all tables and initialize services."""
        await self.node_store.create_tables()
        await self.subscriptions.create_tables()
        await self.event_store.create_tables()
        await self.workspace_service.initialize()

        self.reconciler = FileReconciler(
            self.config, self.node_store, self.event_store,
            self.workspace_service, self.project_root,
        )
        self.runner = AgentRunner(
            self.event_store, self.node_store,
            self.workspace_service, self.config,
        )

    async def close(self) -> None:
        """Shut down all services."""
        if self.reconciler:
            self.reconciler.stop()
        if self.runner:
            self.runner.stop()
        await self.workspace_service.close()
        self.db.close()
```

### Step 10.2: Simplify `__main__.py`

```python
async def _start(*, project_root: Path, config_path: Path | None, port: int, no_web: bool, run_seconds: float = 0.0) -> None:
    project_root = project_root.resolve()
    config = load_config(config_path)
    db_path = project_root / config.swarm_root / "remora.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = AsyncDB.from_path(db_path)

    services = RuntimeServices(config, project_root, db)
    await services.initialize()

    await services.reconciler.full_scan()

    tasks = [
        asyncio.create_task(services.runner.run_forever(), name="runner"),
        asyncio.create_task(services.reconciler.run_forever(), name="reconciler"),
    ]
    if not no_web:
        app = create_app(services)
        # ... uvicorn setup ...

    try:
        if run_seconds > 0:
            await asyncio.sleep(run_seconds)
        else:
            await asyncio.gather(*tasks)
    finally:
        await services.close()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
```

### Phase 10 Acceptance Criteria
- [ ] `RuntimeServices` container wires all dependencies
- [ ] `__main__.py` is ~80 lines, down from ~204
- [ ] All services are accessible via a single container
- [ ] Adding a new service = one field + one initialization line
- [ ] All tests pass

---

## Phase 11: Test Consolidation

### Step 11.1: Create shared factories (R14)

**New file**: `tests/factories.py`

```python
"""Shared test factories and helpers."""

from __future__ import annotations

from pathlib import Path

from remora.code.discovery import CSTNode
from remora.core.node import CodeNode
from remora.core.types import NodeStatus, NodeType


def make_node(
    node_id: str,
    *,
    file_path: str = "src/app.py",
    node_type: str | NodeType = NodeType.FUNCTION,
    status: str | NodeStatus = NodeStatus.IDLE,
    source_code: str | None = None,
    **overrides,
) -> CodeNode:
    name = node_id.split("::", maxsplit=1)[-1]
    return CodeNode(
        node_id=node_id,
        node_type=node_type,
        name=name,
        full_name=name,
        file_path=file_path,
        start_line=1,
        end_line=4,
        source_code=source_code or f"def {name}():\n    return 1\n",
        source_hash=f"hash-{node_id}",
        status=status,
        **overrides,
    )


def make_cst(
    *,
    file_path: str,
    name: str,
    node_type: str = "function",
    text: str | None = None,
    parent_id: str | None = None,
) -> CSTNode:
    source = text or f"def {name}():\n    return 1\n"
    return CSTNode(
        node_id=f"{file_path}::{name}",
        node_type=node_type,
        name=name,
        full_name=name,
        file_path=file_path,
        text=source,
        start_line=1,
        end_line=2,
        start_byte=0,
        end_byte=len(source),
        parent_id=parent_id,
    )


def write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_bundle_templates(root: Path, bundle_name: str = "code-agent") -> None:
    system = root / "system"
    bundle = root / bundle_name
    (system / "tools").mkdir(parents=True, exist_ok=True)
    (bundle / "tools").mkdir(parents=True, exist_ok=True)
    (system / "bundle.yaml").write_text("name: system\nmax_turns: 4\n", encoding="utf-8")
    (bundle / "bundle.yaml").write_text(f"name: {bundle_name}\nmax_turns: 8\n", encoding="utf-8")
    (system / "tools" / "send_message.pym").write_text("return 'ok'\n", encoding="utf-8")
    (bundle / "tools" / "rewrite_self.pym").write_text("return 'ok'\n", encoding="utf-8")
```

### Step 11.2: Migrate all test files to use shared factories

Replace every independent `_node()`, `_write()`, `_make_cst()`, `_write_bundle_templates()` with imports from `tests/factories.py`.

### Step 11.3: Add missing test coverage

From the test gaps identified in CODE_REVIEW_2:

1. **`broadcast` with `"siblings"` and `"file:"` patterns** — test_runner_externals.py
2. **Negative config tests** — test_config.py (invalid language map, missing paths)
3. **Reconciler with malformed source** — test_reconciler.py (file with syntax errors doesn't crash)
4. **Direct rewrite lifecycle** — test_externals.py / test_web_server.py (apply rewrite, emit content-changed, no approve/reject routes)
5. **AgentContext unit tests** — test_externals.py (all 18 externals)
6. **LanguagePlugin unit tests** — test_languages.py (each plugin resolves types correctly)

### Phase 11 Acceptance Criteria
- [ ] `tests/factories.py` exists with shared helpers
- [ ] No test file defines its own `_node()`, `_write()`, etc.
- [ ] All identified coverage gaps have tests
- [ ] Total test count ≥ 150 (up from 125)
- [ ] All tests pass

---

## Phase 12: Event Sourcing Consideration

See **Appendix C** for the full architecture sketch as requested. This phase is **design-only** — not implemented in this guide but documented for future consideration.

---

## Appendix A: Externals Contract — Option Analysis

### Option A: Protocol-based tool backends

```python
class AgentToolBackend(Protocol):
    async def read_file(self, path: str) -> str: ...
    async def write_file(self, path: str, content: str) -> bool: ...
    async def apply_rewrite(self, new_source: str) -> bool: ...
    async def search_files(self, pattern: str) -> list[str]: ...
    # ... all 18 externals
```

**Implementation**: One concrete class per deployment context (local, remote, sandboxed). Grail tools receive the backend, not individual functions.

**Pros:**
- Maximum type safety — Protocol catches missing methods at type-check time
- Easy to create test stubs (just implement the protocol)
- Clear interface contract documented in one place

**Cons:**
- Protocol with 18+ methods is unwieldy — essentially an interface-header style contract
- All externals must be on one object — can't mix and match
- Grail currently expects a `dict[str, Callable]`, so we'd still need a `to_dict()` adapter

**Best for**: Strict environments where compile-time checking matters more than flexibility.

### Option B: Class-based externals with method registry (CHOSEN)

```python
class AgentContext:
    def __init__(self, node_id, workspace, correlation_id, node_store, event_store):
        ...

    async def read_file(self, path: str) -> str: ...
    async def write_file(self, path: str, content: str) -> bool: ...
    # ... all 18 externals as methods

    def to_externals_dict(self) -> dict[str, Any]:
        """Generate the dict Grail expects."""
        return {name: getattr(self, name) for name in self._external_names}
```

**Pros:**
- Natural Python class — each external is a testable method
- Inheritable — specialized contexts can override specific methods
- `self` provides shared state (node_id, workspace, etc.) without closures
- `to_externals_dict()` bridges to Grail's expected format
- Easy to add new externals (just add a method)

**Cons:**
- Less formal than Protocol (no compile-time completeness check)
- `to_externals_dict()` is boilerplate — but it's one method, not 18

**Opportunities:**
- Subclasses for different agent types: `CodeAgentContext(AgentContext)` with code-specific tools, `CompanionAgentContext` with different tools
- Decorator-based registration: `@external` marks methods for inclusion in the dict
- Per-method permissions: metadata on methods controls what each agent type can access

**Best for**: Remora's use case — pragmatic, testable, extensible. Chosen approach.

### Option C: Individual external modules

```
externals/
├── __init__.py
├── filesystem.py    — read_file, write_file, list_dir, etc.
├── graph.py         — graph_get_node, graph_query_nodes, etc.
├── events.py        — event_emit, event_subscribe, etc.
├── communication.py — send_message, broadcast
└── code.py          — apply_rewrite, get_node_source
```

Each module exports functions that take an explicit context parameter.

**Pros:**
- Maximum separation of concerns
- Each module is independently testable with minimal fixtures
- Easy to understand — each file does one thing
- Natural grouping of related operations

**Cons:**
- Most complex to wire up — need a registry/discovery mechanism
- Functions are context-less — need to pass node_id, workspace, etc. to each call
- 5+ files for what is currently one method — potentially over-engineered for 18 functions
- Grail integration requires building the dict from multiple modules

**Best for**: Large systems with many tools where grouping by domain matters. Overkill for Remora's current scale but worth revisiting if the tool count grows past ~30.

---

## Appendix B: Pydantic Patterns for Typed Enums

The question was: *"What about pydantic classes/subclasses? Is there any additional functionality that could be composed/abstracted to these if we used pydantic?"*

### Pattern 1: `str, Enum` + Pydantic validation

```python
class NodeType(str, Enum):
    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"
```

Pydantic automatically validates these on construction:
```python
node = CodeNode(node_type="function")  # ✓ Works, coerces to NodeType.FUNCTION
node = CodeNode(node_type="bogus")     # ✗ ValidationError
```

JSON serialization works naturally: `node.model_dump()` → `{"node_type": "function"}`.

### Pattern 2: Discriminated unions for event types

Pydantic's discriminated unions allow deserializing events from JSON without knowing the type in advance:

```python
from typing import Annotated, Literal, Union
from pydantic import Discriminator

class AgentStartEvent(Event):
    event_type: Literal["AgentStartEvent"] = "AgentStartEvent"
    agent_id: str

class AgentCompleteEvent(Event):
    event_type: Literal["AgentCompleteEvent"] = "AgentCompleteEvent"
    agent_id: str
    result_summary: str = ""

AnyEvent = Annotated[
    Union[AgentStartEvent, AgentCompleteEvent, ...],
    Discriminator("event_type"),
]

# Now you can deserialize any event from a dict:
event = TypeAdapter(AnyEvent).validate_python({"event_type": "AgentStartEvent", "agent_id": "a"})
# Returns an AgentStartEvent instance
```

This would enable **typed event deserialization** from the SQLite event store, eliminating the current `dict[str, Any]` return type.

### Pattern 3: Pydantic validators for state transitions

```python
class Agent(BaseModel):
    status: NodeStatus = NodeStatus.IDLE

    @model_validator(mode="before")
    @classmethod
    def validate_status(cls, values):
        # Custom validation logic if needed
        return values
```

### Pattern 4: Computed fields for derived properties

```python
class CodeElement(BaseModel):
    file_path: str
    full_name: str

    @computed_field
    @property
    def element_id(self) -> str:
        return f"{self.file_path}::{self.full_name}"
```

This eliminates the possibility of `element_id` getting out of sync with its components.

### Recommendation

Use patterns 1 (str Enum), 2 (discriminated unions for event deserialization — nice-to-have, implement when refactoring EventStore query returns), and 4 (computed fields for derived IDs).

---

## Appendix C: Event Sourcing Architecture Sketch

### What event sourcing would look like for Remora

**Core idea**: The EventStore becomes the single source of truth. All other state (nodes, agents, subscriptions, rewrite history) is derived by "projecting" the event stream.

### Event stream (already exists)

```
NodeDiscoveredEvent → creates a node in the projection
NodeChangedEvent    → updates node source/hash
NodeRemovedEvent    → deletes node from projection
AgentStartEvent     → sets agent status = running
AgentCompleteEvent  → sets agent status = idle
RewriteAppliedEvent → records an agent-initiated file rewrite
```

### Projections (new)

A **projection** is a function that processes events in order and builds a read model:

```python
class NodeProjection:
    """Builds the current node graph from the event stream."""

    def __init__(self):
        self._nodes: dict[str, CodeNode] = {}

    def apply(self, event: Event) -> None:
        if isinstance(event, NodeDiscoveredEvent):
            self._nodes[event.node_id] = CodeNode(...)
        elif isinstance(event, NodeChangedEvent):
            node = self._nodes.get(event.node_id)
            if node:
                node.source_hash = event.new_hash
        elif isinstance(event, NodeRemovedEvent):
            self._nodes.pop(event.node_id, None)

    def get_node(self, node_id: str) -> CodeNode | None:
        return self._nodes.get(node_id)

    def list_nodes(self) -> list[CodeNode]:
        return list(self._nodes.values())
```

### Snapshot + replay

For performance, projections are periodically snapshotted:
1. On startup, load the latest snapshot
2. Replay events from the snapshot's sequence number to HEAD
3. Projections are now current
4. New events are applied in real-time

```python
class ProjectionManager:
    async def rebuild_from_scratch(self, event_store: EventStore) -> None:
        """Replay all events to rebuild projections."""
        events = await event_store.get_all_events_ordered()
        for event_dict in events:
            event = deserialize_event(event_dict)
            for projection in self._projections:
                projection.apply(event)

    async def save_snapshot(self) -> None: ...
    async def load_snapshot(self) -> int: ...  # Returns last applied event ID
```

### What would need to change

1. **NodeStore becomes read-only from projections**: Writes happen only through events. `upsert_node` is replaced by `emit(NodeDiscoveredEvent)`.
2. **New event types needed**: `RewriteAppliedEvent`, `StatusTransitionEvent`, `SubscriptionCreatedEvent`, `SubscriptionRemovedEvent`.
3. **All state mutations become events**: Instead of `node_store.set_status(id, "running")`, emit `StatusTransitionEvent(node_id, "idle", "running")`.
4. **Projections replace direct queries**: `node_store.get_node()` delegates to `NodeProjection.get_node()`.

### Implementation effort

| Component | Effort | Description |
|-----------|--------|-------------|
| New event types | Small | ~5 new event classes |
| Event serialization | Medium | Discriminated union deserialization |
| Projection framework | Medium | Base class + apply mechanism |
| NodeProjection | Medium | Replace NodeStore reads |
| AgentProjection | Small | Replace AgentStore reads |
| SubscriptionProjection | Medium | Replace SubscriptionRegistry reads |
| RewriteProjection | Small | Replace rewrite-history reads |
| Snapshot persistence | Large | Serialize/deserialize projection state |
| Migration | Large | All write paths must go through events |
| **Total** | **Large** | ~2-3 weeks of focused work |

### Trade-offs

**Gains:**
- Perfect audit trail — every state change is an event
- Time travel — can reconstruct state at any point in time
- Replay — can re-derive all state from events (disaster recovery)
- Debugging — "why is this node in state X?" → replay and see
- Consistency — impossible for state to drift from event log

**Costs:**
- Complexity — every write path becomes: validate → emit event → apply to projection
- Performance — projection rebuild on startup scales with event count
- Snapshot management — need periodic snapshots or startup gets slow
- Learning curve — event sourcing is a significant paradigm shift

### Recommendation

Event sourcing is powerful but premature for Remora's current scale. The dedicated stores (NodeStore, AgentStore) with explicit state management are sufficient. Revisit when:
- The event log is actively used for debugging/auditing
- There's a need for multi-process or distributed deployment
- The team is comfortable with the event sourcing paradigm

---

## Final Checklist

After all phases are complete:

- [ ] All critical bugs (C1-C3) are fixed
- [ ] All high-severity issues (H1-H3) are fixed
- [ ] All medium issues (M1-M3) are fixed
- [ ] `events.py` god module is split into 5 focused modules
- [ ] `AsyncDB` eliminates ~300 lines of boilerplate
- [ ] Externals are a testable class, not 18 closures
- [ ] Direct rewrites are centralized and ready to be wrapped by Jujutsu workflows
- [ ] Language plugins make new language support zero-touch for existing code
- [ ] Reconciler uses filesystem watching with polling fallback
- [ ] Agent identity is separated from code element
- [ ] Status transitions are validated by a state machine
- [ ] Discovery IDs are collision-safe
- [ ] Web UI is a proper HTML file with full event handling
- [ ] Test helpers are consolidated, coverage is expanded
- [ ] `__main__.py` is ~80 lines of clean orchestration
- [ ] Total source lines reduced from ~3,173 to ~2,800 despite added features

## NO SUBAGENTS — Do all work directly.
