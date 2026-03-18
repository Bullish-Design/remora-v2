# Remora v2 — Complete Refactor Guide

**Date:** 2026-03-17
**Context:** Post-code-review refactor. Zero backwards compatibility concerns.
**Goal:** Cleanest, most elegant codebase and architecture possible.
**Test command:** `devenv shell -- pytest`
**Lint command:** `devenv shell -- ruff check src/ tests/`

---

## Principles

1. **No backwards compatibility.** Change any API, rename anything, delete anything. The only constraint is that the test suite passes after each step.
2. **Delete aggressively.** Remove shims, re-export aliases, dead code, vestigial modules, and commented-out code. If something is unused, it's gone.
3. **One mechanism for each concern.** Where the codebase has two ways of doing something, pick the better one and remove the other entirely.
4. **Use `EventType` enum members, not raw strings.** Wherever event types are referenced — subscriptions, bus handlers, pattern matching — use `EventType.CONTENT_CHANGED`, never `"content_changed"`.
5. **Structured concurrency everywhere.** Use `asyncio.TaskGroup` instead of manual task lists + `gather` + cancellation loops. The project targets Python 3.13+.
6. **Catch specific exceptions.** Replace `except Exception` with the narrowest exception type that covers the expected failure modes. Let programming errors (`TypeError`, `KeyError`, `AttributeError`) propagate.

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
16. [Appendix A: Complete File Inventory](#appendix-a-complete-file-inventory)
17. [Appendix B: Verification Checklist](#appendix-b-verification-checklist)

---

## Phase 1: Error Hierarchy

**Why first:** Every later phase touches error handling. Defining the hierarchy now means subsequent phases can use the correct exception types from the start instead of leaving `except Exception` placeholders.

### 1.1 Expand `core/model/errors.py`

The file currently contains only `IncompatibleBundleError`. Add a full hierarchy:

```python
# core/model/errors.py

class RemoraError(Exception):
    """Base for all expected Remora failures."""

class ModelError(RemoraError):
    """LLM backend failures — timeouts, rate limits, API errors."""

class ToolError(RemoraError):
    """Grail tool script execution failures."""

class WorkspaceError(RemoraError):
    """Cairn workspace / filesystem failures."""

class SubscriptionError(RemoraError):
    """Event routing or subscription matching failures."""

class IncompatibleBundleError(RemoraError):
    """Bundle's externals version exceeds runtime's."""
    def __init__(self, bundle_version: int, runtime_version: int) -> None:
        self.bundle_version = bundle_version
        self.runtime_version = runtime_version
        super().__init__(
            f"Bundle requires externals version {bundle_version}, "
            f"but runtime supports version {runtime_version}"
        )
```

Update `__all__` to export all new classes.

### 1.2 Replace Every `except Exception` with Specific Types

There are ~12-14 instances across the codebase. Here is the exact mapping for each:

| File | Location | Current Catch | Replace With |
|------|----------|---------------|--------------|
| `core/agents/turn.py:169` | Outer turn boundary | `except Exception as exc` | `except (ModelError, ToolError, WorkspaceError, IncompatibleBundleError) as exc` |
| `core/agents/turn.py:291` | Kernel retry loop | `except Exception as exc` | `except (ModelError, OSError, TimeoutError) as exc` |
| `core/agents/turn.py:346` | Status reset in finally | `except Exception` | `except (OSError, aiosqlite.Error)` |
| `core/tools/grail.py:155` | Tool execution boundary | `except Exception as exc` | `except ToolError as exc` — also wrap the `exec()` call so that any exception raised by tool code is caught and re-raised as `ToolError` (see 1.3) |
| `core/tools/grail.py:203` | Tool discovery | `except Exception` | `except (OSError, SyntaxError, ToolError)` |
| `core/events/bus.py:52` | Sync handler isolation | `except Exception as exc` | `except (RemoraError, OSError) as exc` |
| `core/services/search.py:78` | Remote health check | `except Exception` | `except (OSError, TimeoutError)` |
| `core/services/lifecycle.py:195` | LSP shutdown | `except Exception as exc` | `except OSError as exc` |
| `core/services/lifecycle.py:200` | LSP exit | `except Exception` | `except OSError` |
| `code/reconciler.py:167` | Watch batch isolation | `except Exception` | `except (OSError, RemoraError, aiosqlite.Error)` |
| `code/reconciler.py:316` | Search index | `except Exception` | `except (OSError, RemoraError)` |
| `code/reconciler.py:326` | Search deindex | `except Exception` | `except (OSError, RemoraError)` |
| `code/reconciler.py:390` | Bundle metadata sync | `except Exception` | `except (OSError, WorkspaceError, yaml.YAMLError)` |
| `code/reconciler.py:406` | Event-triggered reconcile | `except Exception` | `except (OSError, RemoraError, aiosqlite.Error)` |

### 1.3 Wire `ToolError` into Grail

In `core/tools/grail.py`, the tool execution function should wrap unexpected errors from tool scripts:

```python
# In the tool execution path, around the exec() call:
try:
    # ... existing tool execution logic ...
except ToolError:
    raise  # already wrapped, pass through
except Exception as exc:
    raise ToolError(f"Tool '{tool_name}' failed: {exc}") from exc
```

This is the ONE place where `except Exception` is acceptable — it's the boundary between untrusted tool script code and the runtime. The immediate re-raise as `ToolError` ensures callers can catch specifically.

### 1.4 Wire `ModelError` into Kernel

In `core/agents/kernel.py`, wrap model API calls at the boundary with `structured_agents`:

```python
try:
    result = await agent.run(...)
except Exception as exc:
    raise ModelError(f"Model call failed: {exc}") from exc
```

Same rationale: this is the boundary with an external library. Wrap once at the boundary, catch specifically everywhere above.

### 1.5 Remove All `# noqa: BLE001` Comments

After replacing every `except Exception`, search for and delete every `# noqa: BLE001` comment. There should be zero remaining.

```bash
rg "noqa: BLE001" src/
# Expected: no results
```

### 1.6 Verify

```bash
devenv shell -- pytest
devenv shell -- ruff check src/ tests/
```

Run `rg "except Exception" src/remora/` — the only hits should be the two boundary wraps in `grail.py` and `kernel.py`.

---

## Phase 2: Unify Event Dispatch to String-Based

**Why:** The codebase currently has two event routing mechanisms — `EventBus` dispatches by Python class type, `SubscriptionRegistry` dispatches by `event_type` string. These must agree but share no contract. A renamed class or a missing string silently breaks routing. We choose string-based dispatch because the persistence layer (SQLite), the wire format (SSE), the subscription patterns, and the Grail tool API are all already string-based. The `EventType` enum provides compile-time safety for the string keys.

### 2.1 Change `EventBus` to Key on `EventType` Strings

**File:** `core/events/bus.py`

Change the handler registry from `dict[type[Event], list[EventHandler]]` to `dict[str, list[EventHandler]]`:

```python
class EventBus:
    def __init__(self, max_concurrent_handlers: int = 100) -> None:
        self._handlers: dict[str, list[EventHandler]] = {}  # keyed by event_type string
        self._all_handlers: list[EventHandler] = []
        self._semaphore = asyncio.Semaphore(max_concurrent_handlers)

    async def emit(self, event: Event) -> None:
        """Emit an event to matching string-keyed and global handlers."""
        event_type_key = event.event_type
        await self._dispatch_handlers(self._handlers.get(event_type_key, []), event, self._semaphore)
        await self._dispatch_handlers(self._all_handlers, event, self._semaphore)

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Register a handler for a specific event type string.

        Use EventType enum members: bus.subscribe(EventType.CONTENT_CHANGED, handler)
        """
        self._handlers.setdefault(event_type, []).append(handler)
```

**Key changes:**
- `subscribe()` now takes `event_type: str` instead of `event_type: type[Event]`
- `emit()` dispatches on `event.event_type` (the string) instead of `type(event)` (the class)
- Remove the `if event_type is not Event` special case that dispatched base `Event` subscribers — with string-based dispatch, subscribe to the specific types you want
- `_dispatch_handlers`, `_run_bounded`, `subscribe_all`, `unsubscribe` stay unchanged

### 2.2 Update `stream()` to Filter on Strings

```python
@asynccontextmanager
async def stream(self, *event_types: str) -> AsyncIterator[AsyncIterator[Event]]:
    """Yield an async iterator of events, optionally filtered by event_type strings."""
    queue: asyncio.Queue[Event] = asyncio.Queue()
    filter_set = set(event_types) if event_types else None

    def enqueue(event: Event) -> None:
        if filter_set is None or event.event_type in filter_set:
            queue.put_nowait(event)

    self.subscribe_all(enqueue)
    # ... rest unchanged
```

This removes the `isinstance` check the code review flagged. Filtering is now `event.event_type in filter_set` — simple string membership, no inheritance ambiguity.

### 2.3 Update All Subscribe Call Sites

There are exactly 2 call sites (excluding `subscribe_all` and `stream`, which don't change):

**`code/reconciler.py:148`:**
```python
# Before:
event_bus.subscribe(ContentChangedEvent, self._on_content_changed)
# After:
event_bus.subscribe(EventType.CONTENT_CHANGED, self._on_content_changed)
```

Add `from remora.core.model.types import EventType` if not already imported.

**`web/routes/cursor.py:36`:**
This calls `event_bus.emit()` which doesn't change — emit takes an `Event` object and reads its `.event_type` string internally.

### 2.4 Clean Up the `_on_content_changed` Handler

In `code/reconciler.py:393-407`, the handler currently has a redundant `isinstance` check:

```python
async def _on_content_changed(self, event: Event) -> None:
    if not isinstance(event, ContentChangedEvent):
        return
    file_path = event.path
    ...
```

With string-based dispatch, only `content_changed` events reach this handler. The `isinstance` check is now truly redundant. However, keep it as a type narrowing hint for the type checker, or change the handler signature:

```python
async def _on_content_changed(self, event: Event) -> None:
    """Immediately reconcile a file reported changed by upstream systems."""
    assert isinstance(event, ContentChangedEvent)  # guaranteed by EventBus dispatch
    file_path = event.path
    ...
```

### 2.5 Update the `unsubscribe()` Method

The `unsubscribe()` method iterates `self._handlers.items()` — the iteration logic stays the same, only the key type changes from `type[Event]` to `str`. Update the type annotation:

```python
def unsubscribe(self, handler: EventHandler) -> None:
    empty_keys: list[str] = []
    for key, handlers in self._handlers.items():
        ...
```

### 2.6 Update Tests

Search tests for `EventBus` usage:
```bash
rg "\.subscribe\(" tests/ | grep -v subscribe_all
rg "EventBus" tests/
```

Update any test that calls `bus.subscribe(SomeEventClass, handler)` to `bus.subscribe(EventType.SOME_TYPE, handler)`.

### 2.7 Verify

```bash
devenv shell -- pytest
rg "subscribe\(.*Event[^T]" src/remora/  # should find no class-based subscribe calls
```

---

## Phase 3: Fix Dependency Injection — Kill the `set_tx` Cycle

**Why:** `RuntimeServices.__init__` creates `SubscriptionRegistry`, then `TriggerDispatcher`, then `TransactionContext`, then calls `subscriptions.set_tx(self.tx)` to wire the cycle. This is a hidden circular dependency. The fix: make `TriggerDispatcher` accept subscriptions lazily (it already supports `router` being `None` initially — do the same pattern for subscriptions in the registry).

### 3.1 Make `SubscriptionRegistry` Accept `tx` at Construction

**File:** `core/events/subscriptions.py`

```python
class SubscriptionRegistry:
    def __init__(self, db: aiosqlite.Connection, tx: TransactionContext | None = None):
        self._db = db
        self._tx = tx
        self._cache: dict[str, list[tuple[int, str, SubscriptionPattern]]] | None = None
```

Delete the `set_tx()` method entirely.

### 3.2 Restructure `RuntimeServices.__init__`

**File:** `core/services/container.py`

The circular dependency is: `TransactionContext` needs `TriggerDispatcher`, `TriggerDispatcher` needs `SubscriptionRegistry`, `SubscriptionRegistry` needs `TransactionContext`.

Break the cycle by constructing `TransactionContext` with a dispatcher that accepts subscriptions lazily:

```python
class RuntimeServices:
    def __init__(self, config: Config, project_root: Path, db: aiosqlite.Connection):
        from remora.code.languages import LanguageRegistry
        from remora.code.subscriptions import SubscriptionManager

        self.config = config
        self.project_root = project_root.resolve()
        self.db = db

        self.metrics = Metrics()
        self.event_bus = EventBus()

        # Phase 1: Create dispatcher with no subscriptions yet
        self.dispatcher = TriggerDispatcher()

        # Phase 2: Create tx with the dispatcher
        self.tx = TransactionContext(db, self.event_bus, self.dispatcher)

        # Phase 3: Create subscriptions with tx
        self.subscriptions = SubscriptionRegistry(db, tx=self.tx)

        # Phase 4: Wire subscriptions into dispatcher
        self.dispatcher.subscriptions = self.subscriptions

        # Everything else flows naturally
        self.node_store = NodeStore(db, tx=self.tx)
        self.event_store = EventStore(
            db=db,
            event_bus=self.event_bus,
            dispatcher=self.dispatcher,
            metrics=self.metrics,
            tx=self.tx,
        )
        # ... rest unchanged
```

### 3.3 Update `TriggerDispatcher` to Accept Lazy Subscriptions

**File:** `core/events/dispatcher.py`

```python
class TriggerDispatcher:
    def __init__(
        self,
        subscriptions: SubscriptionRegistry | None = None,
        router: Callable[[str, Event], None] | None = None,
    ):
        self._subscriptions = subscriptions
        self._router = router

    @property
    def subscriptions(self) -> SubscriptionRegistry:
        if self._subscriptions is None:
            raise RuntimeError("TriggerDispatcher.subscriptions not yet wired")
        return self._subscriptions

    @subscriptions.setter
    def subscriptions(self, value: SubscriptionRegistry) -> None:
        self._subscriptions = value

    async def dispatch(self, event: Event) -> None:
        if self._router is None or self._subscriptions is None:
            return
        # ... rest unchanged
```

### 3.4 Delete `set_tx`

Remove `set_tx()` from `SubscriptionRegistry`. Remove the `self.subscriptions.set_tx(self.tx)` call from `RuntimeServices.__init__`. Search for any other callers:

```bash
rg "set_tx" src/ tests/
# Expected: no results
```

### 3.5 Update Tests

Any test that calls `set_tx()` or constructs a `SubscriptionRegistry` without `tx=` needs updating. Search:

```bash
rg "set_tx\|SubscriptionRegistry\(" tests/
```

### 3.6 Verify

```bash
devenv shell -- pytest
```

---

## Phase 4: Extract HumanInputBroker from EventStore

**Why:** `EventStore` currently manages `_pending_responses` (asyncio futures for human-input request/response) alongside event persistence and bus emission. This violates SRP and makes EventStore harder to test and reason about.

### 4.1 Create `core/services/broker.py`

```python
"""Human-input request/response future management."""

from __future__ import annotations

import asyncio


class HumanInputBroker:
    """Manages pending human-input response futures."""

    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Future[str]] = {}

    def create_request(self, request_id: str) -> asyncio.Future[str]:
        """Create and register a pending human-input response future."""
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        return future

    def resolve(self, request_id: str, response: str) -> bool:
        """Resolve and remove a pending human-input response future."""
        future = self._pending.pop(request_id, None)
        if future is None or future.done():
            return False
        future.set_result(response)
        return True

    def discard(self, request_id: str) -> bool:
        """Remove an unresolved pending future (e.g. timeout/cancel)."""
        future = self._pending.pop(request_id, None)
        if future is None:
            return False
        if not future.done():
            future.cancel()
        return True
```

Add to `core/services/__init__.py` re-exports.

### 4.2 Remove Future Methods from `EventStore`

**File:** `core/events/store.py`

Delete these methods entirely:
- `create_response_future()`
- `resolve_response()`
- `discard_response_future()`

Delete the `self._pending_responses` field from `__init__`.

### 4.3 Wire `HumanInputBroker` into `RuntimeServices`

**File:** `core/services/container.py`

```python
from remora.core.services.broker import HumanInputBroker

class RuntimeServices:
    def __init__(self, ...):
        ...
        self.human_input_broker = HumanInputBroker()
        ...
```

### 4.4 Update All Callers

There are exactly 3 call sites that use the future methods:

**`core/tools/capabilities.py` — `CommunicationCapabilities.request_human_input()`:**
```python
# Before:
future = self._event_store.create_response_future(request_id)
...
self._event_store.discard_response_future(request_id)

# After:
future = self._broker.create_request(request_id)
...
self._broker.discard(request_id)
```

Add `broker: HumanInputBroker` to `CommunicationCapabilities.__init__()`. Thread it through from `TurnContext` → `AgentTurnExecutor` → `RuntimeServices`.

**`web/routes/chat.py` — `api_respond()`:**
```python
# Before:
deps.event_store.resolve_response(request_id, response)

# After:
deps.human_input_broker.resolve(request_id, response)
```

Add `human_input_broker: HumanInputBroker` to `WebDeps`. Wire it in `create_app()`.

### 4.5 Verify

```bash
devenv shell -- pytest
rg "pending_response\|create_response_future\|resolve_response\|discard_response_future" src/
# Expected: no results
```

---

## Phase 5: Adopt Structured Concurrency (TaskGroups)

**Why:** The codebase manually manages `asyncio.Task` objects in lists, uses `gather`/`wait`, and has complex cancellation logic in finally blocks. Python 3.13+ `TaskGroup` provides automatic cleanup and structured error propagation. This eliminates the 65+ line `shutdown()` method and prevents task leaks.

### 5.1 `core/events/bus.py` — Replace `gather` with `TaskGroup`

```python
@staticmethod
async def _dispatch_handlers(
    handlers: list[EventHandler],
    event: Event,
    semaphore: asyncio.Semaphore | None = None,
) -> None:
    sync_handlers = []
    async_handlers = []
    for handler in handlers:
        if asyncio.iscoroutinefunction(handler):
            async_handlers.append(handler)
        else:
            sync_handlers.append(handler)

    # Run sync handlers directly
    for handler in sync_handlers:
        try:
            handler(event)
        except (RemoraError, OSError) as exc:
            logger.exception("Event handler failed for %s: %s", event.event_type, exc)

    # Run async handlers in a TaskGroup
    if async_handlers:
        try:
            async with asyncio.TaskGroup() as tg:
                for handler in async_handlers:
                    if semaphore is None:
                        tg.create_task(handler(event))
                    else:
                        tg.create_task(EventBus._run_bounded(handler, event, semaphore))
        except* (RemoraError, OSError) as exc_group:
            for exc in exc_group.exceptions:
                logger.exception("Event handler failed for %s: %s", event.event_type, exc)
```

Note the `except*` syntax — this is the ExceptionGroup handling for TaskGroups. If any handler raises, the TaskGroup collects exceptions. The `except*` block handles them without crashing the bus.

### 5.2 `core/services/lifecycle.py` — Simplify with TaskGroup

The `shutdown()` method is currently 65+ lines of manual task management. Replace the `self._tasks` list with a TaskGroup-based approach:

```python
class RemoraLifecycle:
    def __init__(self, ...):
        ...
        self._task_group: asyncio.TaskGroup | None = None
        # Remove: self._tasks: list[asyncio.Task] = []
```

In `start()`, create tasks via the group. In `run()`, use the group as the structured scope. In `shutdown()`, cancelling the group automatically cancels all child tasks:

```python
async def run(self, *, run_seconds: float = 0.0) -> None:
    if not self._started:
        raise RuntimeError("RemoraLifecycle.start() must be called before run()")

    try:
        async with asyncio.TaskGroup() as tg:
            self._task_group = tg
            tg.create_task(services.runner.run_forever())
            tg.create_task(services.reconciler.run_forever())
            if not self._no_web:
                tg.create_task(self._web_server.serve())
            if self._lsp:
                tg.create_task(asyncio.to_thread(self._lsp_server.start_io))
            if run_seconds > 0:
                tg.create_task(self._timeout_shutdown(run_seconds))
    except* Exception as exc_group:
        for exc in exc_group.exceptions:
            logger.warning("Runtime task ended with exception: %s", exc)
    finally:
        await self._cleanup()
```

The `shutdown()` method becomes `_cleanup()` and shrinks to ~15 lines — just close services and release handlers. No task tracking, no cancellation loops, no `asyncio.wait` with timeouts.

### 5.3 `web/sse.py` — Replace Manual Task Management

The SSE generator currently creates `disconnect_task` and `shutdown_task` manually. Replace with a TaskGroup:

```python
async with deps.event_bus.stream() as stream:
    stream_iterator = stream.__aiter__()
    try:
        async with asyncio.TaskGroup() as tg:
            disconnect_task = tg.create_task(_wait_for_disconnect(request))
            shutdown_task = tg.create_task(_wait_for_shutdown(deps.shutdown_event))

            while True:
                stream_task = tg.create_task(stream_iterator.__anext__())
                done, _pending = await asyncio.wait(
                    {stream_task, disconnect_task, shutdown_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                # ... rest of the event loop
    except* asyncio.CancelledError:
        pass  # clean shutdown
```

**Important caveat:** The SSE generator is an async generator used by Starlette's `StreamingResponse`. TaskGroups inside async generators can be tricky — the generator may be abandoned by the framework without a clean `aclose()`. Test this thoroughly. If TaskGroup doesn't work cleanly inside the generator, keep the manual approach but ensure the `finally` block is robust.

### 5.4 `core/storage/transaction.py` — Parallel Deferred Event Fan-Out

Currently, deferred events are emitted sequentially in the `finally` block:

```python
for event in self._deferred_events:
    await self._event_bus.emit(event)
    await self._dispatcher.dispatch(event)
```

Replace with parallel fan-out:

```python
if not failed and self._deferred_events:
    await self._db.commit()
    async with asyncio.TaskGroup() as tg:
        for event in self._deferred_events:
            tg.create_task(self._fan_out(event))
    self._deferred_events.clear()

async def _fan_out(self, event: Event) -> None:
    await self._event_bus.emit(event)
    await self._dispatcher.dispatch(event)
```

**Note:** This changes the semantics — events are now fanned out concurrently rather than sequentially. If event ordering matters for triggers (e.g., `NodeDiscoveredEvent` must be processed before `NodeChangedEvent` for the same node), keep sequential emission for events with ordering constraints. If unsure, keep sequential — the performance gain from parallelism is minor for typical batch sizes.

### 5.5 Verify

```bash
devenv shell -- pytest
rg "asyncio\.gather\|asyncio\.wait\b" src/remora/
# Expect minimal hits — only in places where TaskGroup doesn't fit
```

---

## Phase 6: Type-Safe Subscription Matching (RoutingEnvelope)

**Why:** `SubscriptionPattern.matches()` currently uses 6 `getattr()` calls to probe event attributes (`from_agent`, `agent_id`, `to_agent`, `path`, `file_path`, `tags`) that may or may not exist on any given Event subclass. A renamed field silently breaks matching. The fix: define a stable `RoutingEnvelope` that every event provides, and match against that.

### 6.1 Define `RoutingEnvelope`

**File:** `core/events/types.py`

```python
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class RoutingEnvelope:
    """Stable routing attributes that every event provides for subscription matching."""
    event_type: str
    agent_id: str | None = None
    from_agent: str | None = None
    to_agent: str | None = None
    path: str | None = None
    tags: tuple[str, ...] = ()
```

Using a dataclass (not Pydantic) because this is a lightweight value object — no validation needed.

### 6.2 Add `routing_envelope()` to `Event` Base Class

```python
class Event(BaseModel):
    event_type: str = ""
    timestamp: float = Field(default_factory=time.time)
    correlation_id: str | None = None
    tags: tuple[str, ...] = ()

    def routing_envelope(self) -> RoutingEnvelope:
        """Return the routing attributes for subscription matching."""
        return RoutingEnvelope(
            event_type=self.event_type,
            tags=self.tags,
        )
```

### 6.3 Override in Subclasses That Have Routing-Relevant Fields

Each event subclass overrides `routing_envelope()` to expose its specific fields:

```python
class AgentStartEvent(Event):
    event_type: str = EventType.AGENT_START
    agent_id: str
    node_name: str = ""

    def routing_envelope(self) -> RoutingEnvelope:
        return RoutingEnvelope(
            event_type=self.event_type,
            agent_id=self.agent_id,
            tags=self.tags,
        )

class AgentMessageEvent(Event):
    event_type: str = EventType.AGENT_MESSAGE
    from_agent: str
    to_agent: str
    content: str

    def routing_envelope(self) -> RoutingEnvelope:
        return RoutingEnvelope(
            event_type=self.event_type,
            from_agent=self.from_agent,
            to_agent=self.to_agent,
            tags=self.tags,
        )

class ContentChangedEvent(Event):
    event_type: str = EventType.CONTENT_CHANGED
    path: str
    ...

    def routing_envelope(self) -> RoutingEnvelope:
        return RoutingEnvelope(
            event_type=self.event_type,
            agent_id=self.agent_id,
            path=self.path,
            tags=self.tags,
        )

class NodeChangedEvent(Event):
    event_type: str = EventType.NODE_CHANGED
    node_id: str
    file_path: str | None = None
    ...

    def routing_envelope(self) -> RoutingEnvelope:
        return RoutingEnvelope(
            event_type=self.event_type,
            path=self.file_path,  # map file_path -> path
            tags=self.tags,
        )
```

Do this for every event subclass. Events without routing-relevant fields (e.g., `CustomEvent`) use the base class default.

### 6.4 Rewrite `SubscriptionPattern.matches()` to Use the Envelope

**File:** `core/events/subscriptions.py`

```python
def matches(self, event: Event) -> bool:
    """Return True when the event matches this pattern."""
    env = event.routing_envelope()

    if self.event_types and env.event_type not in self.event_types:
        return False

    if self.from_agents:
        if env.from_agent not in self.from_agents and env.agent_id not in self.from_agents:
            return False

    if self.not_from_agents:
        if env.agent_id in self.not_from_agents or env.from_agent in self.not_from_agents:
            return False

    if self.to_agent:
        if env.to_agent != self.to_agent:
            return False

    if self.path_glob:
        if env.path is None or not PurePath(env.path).match(self.path_glob):
            return False

    if self.tags:
        if not set(env.tags).intersection(self.tags):
            return False

    return True
```

**Zero `getattr` calls.** The envelope is a typed, stable contract. If an event renames `file_path` to `source_path`, the `routing_envelope()` override handles the mapping. Subscription matching never breaks.

### 6.5 Update Event Logger in Lifecycle

**File:** `core/services/lifecycle.py:84-93`

The event logger also uses `getattr` probing. Fix it:

```python
def log_event(event: Event) -> None:
    env = event.routing_envelope()
    event_logger.info(
        "event=%s corr=%s agent=%s from=%s to=%s path=%s",
        env.event_type,
        event.correlation_id or "-",
        env.agent_id or "-",
        env.from_agent or "-",
        env.to_agent or "-",
        env.path or "-",
    )
```

### 6.6 Verify

```bash
devenv shell -- pytest
rg "getattr\(event" src/remora/
# Expected: no results (all getattr probing removed)
```

---

## Phase 7: Namespace Capability Functions (TODO: Does this work with Grail??)

**Why:** `TurnContext.to_capabilities_dict()` merges all capability groups into one flat dict. If two groups define a function with the same name, the last one wins silently. The fix: prefix each function name with its group namespace.

### 7.1 Update Each Capability Class's `to_dict()`

**File:** `core/tools/capabilities.py`

Each class prefixes its keys:

```python
class FileCapabilities:
    def to_dict(self) -> dict[str, Any]:
        return {
            "files.read_file": self.read_file,
            "files.write_file": self.write_file,
            "files.list_dir": self.list_dir,
            "files.file_exists": self.file_exists,
            "files.search_files": self.search_files,
            "files.search_content": self.search_content,
        }

class KVCapabilities:
    def to_dict(self) -> dict[str, Any]:
        return {
            "kv.get": self.kv_get,
            "kv.set": self.kv_set,
            "kv.delete": self.kv_delete,
            "kv.list": self.kv_list,
        }

class GraphCapabilities:
    def to_dict(self) -> dict[str, Any]:
        return {
            "graph.get_node": self.graph_get_node,
            "graph.query_nodes": self.graph_query_nodes,
            "graph.get_edges": self.graph_get_edges,
            "graph.get_children": self.graph_get_children,
            "graph.set_status": self.graph_set_status,
        }

class EventCapabilities:
    def to_dict(self) -> dict[str, Any]:
        return {
            "events.emit": self.event_emit,
            "events.subscribe": self.event_subscribe,
            "events.unsubscribe": self.event_unsubscribe,
            "events.get_history": self.event_get_history,
        }

class CommunicationCapabilities:
    def to_dict(self) -> dict[str, Any]:
        return {
            "comms.send_message": self.send_message,
            "comms.broadcast": self.broadcast,
            "comms.request_human_input": self.request_human_input,
            "comms.propose_changes": self.propose_changes,
        }

class SearchCapabilities:
    def to_dict(self) -> dict[str, Any]:
        return {
            "search.semantic_search": self.semantic_search,
            "search.find_similar_code": self.find_similar_code,
        }

class IdentityCapabilities:
    def to_dict(self) -> dict[str, Any]:
        return {
            "identity.get_node_source": self.get_node_source,
            "identity.my_node_id": self.my_node_id,
            "identity.my_correlation_id": self.my_correlation_id,
        }
```

### 7.2 Update Grail Tool Resolution

**File:** `core/tools/grail.py`

The Grail tool system resolves capability function references in `.pym` tool scripts. Update the resolution logic to match the new namespaced keys. The tool scripts themselves need updating — search for all `.pym` files:

```bash
find bundles/ -name "*.pym" -exec grep -l "read_file\|write_file\|kv_get\|graph_get_node\|send_message" {} \;
```

Update each tool script's function references:
```python
# Before (in .pym script):
content = await read_file("path/to/file")
# After:
content = await files.read_file("path/to/file")
```

**How Grail works:** The `.pym` scripts receive capabilities as local variables via `exec()`. The namespacing means the Grail `exec()` call needs to either:
- **Option A:** Pass the flat namespaced dict as-is — tool scripts use `await capabilities["files.read_file"](...)`. Ugly.
- **Option B:** Pass capability group objects directly — tool scripts use `await files.read_file(...)`. Clean.

**Choose Option B.** Modify `discover_tools` / the exec context to inject capability groups as named objects rather than a flat dict of callables:

```python
# In grail.py, when building the exec context:
exec_globals = {
    "files": context.files,
    "kv": context.kv,
    "graph": context.graph,
    "events": context.events,
    "comms": context.comms,
    "search": context.search,
    "identity": context.identity,
}
```

This is cleaner than either a flat dict or dotted-string keys. The `to_dict()` methods on each capability class can then be removed entirely if nothing else uses them — or kept as a secondary API for programmatic access.

### 7.3 Update All `.pym` Tool Scripts

Update every tool script in `bundles/` to use the group-prefixed access pattern:

```bash
find bundles/ -name "*.pym" | sort
```

For each script, replace bare function calls with group-prefixed calls. Example:

```python
# Before:
source = await read_file(path)
await write_file(path, new_source)
node = await graph_get_node(node_id)

# After:
source = await files.read_file(path)
await files.write_file(path, new_source)
node = await graph.get_node(node_id)
```

### 7.4 Verify

```bash
devenv shell -- pytest
```

---

## Phase 8: Make Node Immutable

**Why:** `Node` is a mutable Pydantic model (`frozen=False`). Status and role are mutated in-place during reconciliation, which breaks Pydantic's value proposition and makes change tracking impossible.

### 8.1 Set `frozen=True`

**File:** `core/model/node.py`

```python
class Node(BaseModel):
    model_config = ConfigDict(frozen=True)
    ...
```

This will cause `AttributeError` at every mutation site. That's intentional — the compiler (ruff/mypy) and tests will find every site.

### 8.2 Replace Mutations with `model_copy()`

Search for all mutation sites:

```bash
rg "node\.(status|role|parent_id) =" src/remora/
```

Replace each with `model_copy(update=...)`:

**`code/reconciler.py` — `_do_reconcile_file()`:**
```python
# Before:
node.status = existing.status if existing is not None else NodeStatus.IDLE
node.role = mapped_bundle if mapped_bundle is not None else (existing.role if existing is not None else None)

# After:
node = node.model_copy(update={
    "status": existing.status if existing is not None else NodeStatus.IDLE,
    "role": mapped_bundle if mapped_bundle is not None else (existing.role if existing is not None else None),
})
```

**`code/reconciler.py` — `_reconcile_events()`:**
```python
# Before:
if node.parent_id is None:
    node.parent_id = dir_node_id
    await self._node_store.upsert_node(node)

# After:
if node.parent_id is None:
    node = node.model_copy(update={"parent_id": dir_node_id})
    await self._node_store.upsert_node(node)
```

Repeat for any other mutation sites found by the grep.

### 8.3 Update `code/directories.py` and `code/virtual_agents.py`

These modules may also mutate Node objects. Search and fix:

```bash
rg "\.status\s*=\|\.role\s*=\|\.parent_id\s*=" src/remora/code/
```

### 8.4 Verify

```bash
devenv shell -- pytest
```

---

## Phase 9: Atomic File Writes for Proposal Accept

**Why:** `api_proposal_accept` writes files in place with `disk_path.write_bytes(new_bytes)`. A crash or disk-full condition mid-write corrupts user source code. The fix: write to a temp file, fsync, then atomic rename.

### 9.1 Add `atomic_write` Utility

**File:** `core/utils.py` (currently only has `deep_merge` — this is the right place)

```python
import os
import tempfile
from pathlib import Path


def atomic_write(path: Path, content: bytes) -> None:
    """Write content to a file atomically using temp-file + rename.

    Guarantees that the target file is either fully written or untouched.
    """
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

### 9.2 Use `atomic_write` in Proposal Accept

**File:** `web/routes/proposals.py`

```python
from remora.core.utils import atomic_write

# Replace:
disk_path.write_bytes(new_bytes)

# With:
disk_path.parent.mkdir(parents=True, exist_ok=True)
atomic_write(disk_path, new_bytes)
```

### 9.3 Verify

```bash
devenv shell -- pytest
```

---

## Phase 10: Use Database Row IDs for SSE Event IDs

**Why:** SSE currently uses `event.timestamp` as the event ID. Timestamps are floats, not unique. Two events in the same millisecond get the same ID, and SSE reconnection with `Last-Event-ID` would miss the second event.

### 10.1 Thread Event ID Through the Live Streaming Path

The issue: for events replayed from the database, we already have `row["id"]` and use it correctly. But for live-streamed events (via `EventBus.stream()`), the event object doesn't carry the DB row ID.

**Option A (simplest):** Add an `event_id: int | None` field to the `Event` base class. `EventStore.append()` sets it after the INSERT:

**File:** `core/events/types.py`

```python
class Event(BaseModel):
    event_type: str = ""
    event_id: int | None = None  # set by EventStore.append() after DB insert
    timestamp: float = Field(default_factory=time.time)
    correlation_id: str | None = None
    tags: tuple[str, ...] = ()
```

**File:** `core/events/store.py`

```python
async def append(self, event: Event) -> int:
    ...
    event_id = int(cursor.lastrowid)
    event.event_id = event_id  # stamp it before bus emission
    ...
```

**Note:** This requires Node to be `frozen=False` for Event... but Event is NOT frozen (it has no `ConfigDict(frozen=True)`), so this mutation is fine. However, after Phase 8 makes Node frozen, verify that Event is still mutable. Event's `model_config` is not set, so the Pydantic default (`frozen=False`) applies.

### 10.2 Use `event_id` in SSE

**File:** `web/sse.py`

```python
# Before (line 92):
yield f"id: {event.timestamp}\nevent: {event.event_type}\ndata: {payload}\n\n"

# After:
sse_id = event.event_id if event.event_id is not None else event.timestamp
yield f"id: {sse_id}\nevent: {event.event_type}\ndata: {payload}\n\n"
```

### 10.3 Verify

```bash
devenv shell -- pytest
```

---

## Phase 11: Split SearchService into Strategy Implementations

**Why:** `SearchService` has `if self._client ... elif self._pipeline ...` branching in every method. Two implementations of `SearchServiceProtocol` eliminates this.

### 11.1 Create `RemoteSearchService` and `LocalSearchService`

**File:** `core/services/search.py`

Keep `SearchServiceProtocol` unchanged. Replace the single `SearchService` class with two:

```python
class RemoteSearchService:
    """Search backed by a remote embeddy server."""

    def __init__(self, config: SearchConfig) -> None:
        self._config = config
        self._client: Any = None
        self._available = False

    @property
    def available(self) -> bool:
        return self._available

    async def initialize(self) -> None:
        # ... remote client setup (lines 60-83 of current code)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()

    async def search(self, query, collection=None, top_k=10, mode="hybrid"):
        if not self._available:
            return []
        target = collection or self._config.default_collection
        result = await self._client.search(query, target, top_k=top_k, mode=mode)
        return result.get("results", [])

    # ... find_similar, index_file, delete_source — each is simple, no branching


class LocalSearchService:
    """Search backed by in-process embeddy."""

    def __init__(self, config: SearchConfig, project_root: Path) -> None:
        self._config = config
        self._project_root = project_root
        self._pipeline: Any = None
        self._search_svc: Any = None
        self._store: Any = None
        self._available = False

    @property
    def available(self) -> bool:
        return self._available

    async def initialize(self) -> None:
        # ... local setup (lines 96-132 of current code)

    async def close(self) -> None:
        if self._store is not None:
            await self._store.close()

    async def search(self, query, collection=None, top_k=10, mode="hybrid"):
        if not self._available:
            return []
        # ... local search logic, no branching

    # ... find_similar, index_file, delete_source
```

### 11.2 Add Factory Function

```python
async def create_search_service(
    config: SearchConfig,
    project_root: Path,
) -> SearchServiceProtocol | None:
    """Create and initialize the appropriate search service."""
    if not config.enabled:
        return None
    if config.mode == "remote":
        svc = RemoteSearchService(config)
    else:
        svc = LocalSearchService(config, project_root)
    await svc.initialize()
    return svc
```

### 11.3 Update `RuntimeServices`

**File:** `core/services/container.py`

```python
# Before:
if self.config.search.enabled:
    self.search_service = SearchService(self.config.search, self.project_root)
    await self.search_service.initialize()

# After:
from remora.core.services.search import create_search_service
self.search_service = await create_search_service(self.config.search, self.project_root)
```

### 11.4 Delete `SearchService` Class

Remove the old monolithic `SearchService` class entirely. Also add `collection_for_file` as a standalone function or put it on both implementations (or on the protocol if needed).

### 11.5 Verify

```bash
devenv shell -- pytest
```

---

## Phase 12: Decompose FileReconciler

**Why:** `FileReconciler` is a God class with 400+ lines and 15+ methods covering file watching, node CRUD, bundle provisioning, search indexing, subscription management, directory management, and virtual agent management.

### 12.1 Extract `BundleProvisioner`

**New file:** `code/provisioner.py`

Move `_resolve_bundle_template_dirs()` and `_provision_bundle()` from `FileReconciler`:

```python
class BundleProvisioner:
    """Resolves and provisions agent bundle templates."""

    def __init__(
        self,
        config: Config,
        workspace_service: CairnWorkspaceService,
        bundle_search_paths: list[Path],
    ) -> None:
        self._config = config
        self._workspace_service = workspace_service
        self._bundle_search_paths = bundle_search_paths

    def resolve_template_dirs(self, bundle_name: str) -> list[Path]:
        return resolve_bundle_dirs(bundle_name, self._bundle_search_paths)

    async def provision(self, node_id: str, role: str | None) -> None:
        template_dirs = self.resolve_template_dirs("system")
        if role:
            template_dirs.extend(self.resolve_template_dirs(role))
        await self._workspace_service.provision_bundle(node_id, template_dirs)

        workspace = await self._workspace_service.get_agent_workspace(node_id)
        try:
            text = await workspace.read("_bundle/bundle.yaml")
            loaded = yaml.safe_load(text) or {}
            self_reflect = loaded.get("self_reflect") if isinstance(loaded, dict) else None
            if isinstance(self_reflect, dict) and self_reflect.get("enabled"):
                await workspace.kv_set("_system/self_reflect", self_reflect)
            else:
                await workspace.kv_set("_system/self_reflect", None)
        except (OSError, WorkspaceError, yaml.YAMLError):
            logger.debug("Failed to sync self_reflect config for %s", node_id, exc_info=True)
```

### 12.2 Extract `SearchIndexer`

**New file:** `code/indexer.py`

Move `_index_file_for_search()` and `_deindex_file_for_search()`:

```python
class SearchIndexer:
    """Manages search index updates during reconciliation."""

    def __init__(self, search_service: SearchServiceProtocol | None) -> None:
        self._search_service = search_service

    async def index_file(self, file_path: str) -> None:
        if self._search_service is None or not self._search_service.available:
            return
        try:
            await self._search_service.index_file(file_path)
        except (OSError, RemoraError):
            logger.debug("Search indexing failed for %s", file_path, exc_info=True)

    async def deindex_file(self, file_path: str) -> None:
        if self._search_service is None or not self._search_service.available:
            return
        try:
            await self._search_service.delete_source(file_path)
        except (OSError, RemoraError):
            logger.debug("Search deindexing failed for %s", file_path, exc_info=True)
```

### 12.3 Extract `NodeReconciler`

**New file:** `code/node_reconciler.py`

Move `_do_reconcile_file()`, `_reconcile_events()`, and `_remove_node()`. This is the heart of the reconciliation logic — node discovery, upsert, event emission, subscription wiring.

```python
class NodeReconciler:
    """Reconciles discovered nodes with the persistent graph."""

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
    ) -> None:
        ...

    async def reconcile_file(self, file_path: str, mtime_ns: int, *, sync_existing_bundles: bool = False) -> set[str]:
        """Reconcile a single file. Returns the set of node IDs discovered."""
        ...

    async def remove_node(self, node_id: str) -> None:
        ...
```

### 12.4 Simplify `FileReconciler` to Thin Orchestrator

`FileReconciler` becomes ~100 lines. It owns:
- `FileWatcher` (already delegated)
- `DirectoryManager` (already delegated)
- `VirtualAgentManager` (already delegated)
- `NodeReconciler` (new)
- File state tracking (`_file_state`, `_file_locks`)
- The `full_scan()` / `reconcile_cycle()` / `run_forever()` orchestration

```python
class FileReconciler:
    def __init__(self, ...):
        self._provisioner = BundleProvisioner(config, workspace_service, bundle_search_paths)
        self._indexer = SearchIndexer(search_service)
        self._node_reconciler = NodeReconciler(
            config, node_store, event_store, subscription_manager,
            self._provisioner, self._indexer, directory_manager,
            language_registry, project_root, tx=tx,
        )
        self._watcher = FileWatcher(config, project_root)
        self._directory_manager = DirectoryManager(...)
        self._virtual_agent_manager = VirtualAgentManager(...)
        ...

    async def reconcile_cycle(self) -> None:
        generation = self._next_reconcile_generation()
        await self._virtual_agent_manager.sync()
        current_mtimes = self._watcher.collect_file_mtimes()
        await self._directory_manager.materialize(...)

        for file_path in sorted(changed_paths):
            async with self._file_lock(file_path, generation):
                new_ids = await self._node_reconciler.reconcile_file(file_path, mtime_ns)
                self._file_state[file_path] = (mtime_ns, new_ids)

        for file_path in deleted_paths:
            for node_id in self._file_state[file_path][1]:
                await self._node_reconciler.remove_node(node_id)
            await self._indexer.deindex_file(file_path)
            self._file_state.pop(file_path, None)

        self._evict_stale_file_locks(generation)
```

### 12.5 Verify

```bash
devenv shell -- pytest
```

---

## Phase 13: Code Quality Batch

These are smaller, self-contained improvements. Each can be done independently.

### 13.1 Extract Shared JSON Deserialization in EventStore

**File:** `core/events/store.py`

All four query methods have identical JSON parsing. Extract:

```python
def _deserialize_row(self, row: aiosqlite.Row) -> dict[str, Any]:
    result = dict(row)
    result["tags"] = json.loads(result.get("tags") or "[]")
    result["payload"] = json.loads(result["payload"])
    return result
```

Replace the inline logic in `get_events`, `get_events_for_agent`, `get_latest_event_by_type`, and `get_events_after`.

### 13.2 DRY the Language Plugin Classes

**File:** `code/languages.py`

`PythonPlugin` and `GenericLanguagePlugin` share 90% code. Extract `BaseLanguagePlugin`:

```python
class BaseLanguagePlugin:
    def __init__(self, language: str, query: str, query_paths: list[Path]) -> None:
        self._language = language
        self._query = query
        self._query_paths = query_paths

    def get_language(self) -> str: return self._language
    def get_query(self) -> str: return self._query
    def _resolve_query_file(self) -> Path | None: ...
    def resolve_node_type(self, capture_name: str) -> NodeType | None:
        raise NotImplementedError

class PythonPlugin(BaseLanguagePlugin):
    def resolve_node_type(self, capture_name: str) -> NodeType | None: ...

class GenericLanguagePlugin(BaseLanguagePlugin):
    def resolve_node_type(self, capture_name: str) -> NodeType | None: ...
```

### 13.3 Replace FIFO Script Cache with `functools.lru_cache`

**File:** `core/tools/grail.py`

Replace the manual `_PARSED_SCRIPT_CACHE` dict:

```python
# Delete:
_PARSED_SCRIPT_CACHE: dict[str, Any] = {}
# And the manual FIFO eviction logic

# Replace with:
@functools.lru_cache(maxsize=256)
def _parse_script(script_path: str, content_hash: str) -> ParsedScript:
    ...
```

Use the file content hash as a cache key parameter to invalidate on content change.

### 13.4 Add Input Length Limits to Web Endpoints

**File:** `web/routes/chat.py`

```python
MAX_MESSAGE_LENGTH = 100_000  # 100KB

async def api_chat(request: Request) -> JSONResponse:
    data = await request.json()
    message = str(data.get("message", "")).strip()
    if len(message) > MAX_MESSAGE_LENGTH:
        return JSONResponse({"error": "message too long"}, status_code=413)
    ...
```

Similarly for search queries and other text inputs.

### 13.5 Fix `RegisterSubscriptionsFn` to Be a `Protocol`

**File:** `code/virtual_agents.py`

```python
from typing import Protocol

class RegisterSubscriptionsFn(Protocol):
    async def __call__(
        self,
        node: Node,
        *,
        virtual_subscriptions: tuple[SubscriptionPattern, ...] = (),
    ) -> None: ...
```

### 13.6 Remove Vestigial `db.py` Module

**File:** `core/storage/db.py`

This module is 21 lines — a type alias and a function. Inline `open_database` into `core/services/lifecycle.py` (the one place it's called). Delete the `Connection` type alias — callers can import `aiosqlite.Connection` directly.

After inlining:
- Delete `core/storage/db.py`
- Remove from `core/storage/__init__.py` re-exports
- Update any imports

```bash
rg "from remora.core.storage.db import\|from remora.core.storage import.*open_database\|from remora.core.storage import.*Connection" src/ tests/
```

### 13.7 Make `_deps_from_request` and `_get_chat_limiter` Public

**File:** `web/deps.py`

Rename:
- `_deps_from_request` → `deps_from_request`
- `_get_chat_limiter` → `get_chat_limiter`

Update `__all__` and all import sites:

```bash
rg "_deps_from_request\|_get_chat_limiter" src/ tests/
```

### 13.8 Add Pagination to `/api/nodes`

**File:** `web/routes/nodes.py`

```python
async def api_nodes(request: Request) -> JSONResponse:
    deps = deps_from_request(request)
    limit = min(500, max(1, int(request.query_params.get("limit", "100"))))
    offset = max(0, int(request.query_params.get("offset", "0")))
    nodes = await deps.node_store.list_nodes(limit=limit, offset=offset)
    ...
```

This requires adding `limit` and `offset` parameters to `NodeStore.list_nodes()`.

### 13.9 Replace `snapshot()` Manual Field Listing with `dataclasses.asdict()`

**File:** `core/services/metrics.py`

```python
def snapshot(self) -> dict[str, Any]:
    data = dataclasses.asdict(self)
    data["uptime_seconds"] = round(self.uptime_seconds, 1)
    data["cache_hit_rate"] = round(self.cache_hit_rate, 3)
    return data
```

### 13.10 Fix `get_events_after` Parameter Type

**File:** `core/events/store.py`

Change `after_id: str` to `after_id: int`:

```python
async def get_events_after(self, after_id: int, limit: int = 500) -> list[dict[str, Any]]:
    cursor = await self._db.execute(
        "SELECT * FROM events WHERE id > ? ORDER BY id ASC LIMIT ?",
        (after_id, limit),
    )
    ...
```

Update callers (SSE `Last-Event-ID` parsing) to convert to `int` at the call site.

### 13.11 Verify

```bash
devenv shell -- pytest
devenv shell -- ruff check src/ tests/
```

---

## Phase 14: Polish Batch

Smaller quality-of-life improvements.

### 14.1 Add IPv6 Loopback to CSRF Middleware

**File:** `web/middleware.py`

```python
return host in {"localhost", "127.0.0.1", "::1"}
```

### 14.2 Add `agent_id` Public Property to `AgentWorkspace`

**File:** `core/storage/workspace.py`

```python
@property
def agent_id(self) -> str:
    return self._agent_id
```

Then in `core/tools/grail.py`, replace `str(getattr(workspace, "_agent_id", "?"))` with `workspace.agent_id`.

### 14.3 Make Trigger Policy Constants Configurable

**File:** `core/agents/trigger.py`

Move `_DEPTH_TTL_MS` and `_DEPTH_CLEANUP_INTERVAL` to `RuntimeConfig` fields.

### 14.4 Log Truncation Indicator in API Responses

**File:** `web/routes/nodes.py`

When `api_conversation` truncates message content at 2000 chars, include a `"truncated": true` field.

### 14.5 Cache Config File Discovery

**File:** `core/model/config.py`

Cache the result of `_find_config_file()` after first resolution, or accept `None` to skip the walk.

### 14.6 `OutboxObserver` Dispatch Table

**File:** `core/agents/outbox.py`

Replace the isinstance chain with a dispatch dict:

```python
class OutboxObserver:
    _TRANSLATORS: dict[type, Callable] = {
        SAModelRequestEvent: _translate_model_request,
        SAModelResponseEvent: _translate_model_response,
        SAToolCallEvent: _translate_tool_call,
        SAToolResultEvent: _translate_tool_result,
        SATurnCompleteEvent: _translate_turn_complete,
    }

    def _translate(self, event: Any) -> Event | None:
        translator = self._TRANSLATORS.get(type(event))
        if translator is None:
            return None
        return translator(self._agent_id, event)
```

Extract each translation into a standalone function:

```python
def _translate_model_request(agent_id: str, event: Any) -> ModelRequestEvent:
    return ModelRequestEvent(
        agent_id=agent_id,
        model=str(getattr(event, "model", "")),
        tool_count=int(getattr(event, "tools_count", 0) or 0),
        turn=int(getattr(event, "turn", 0) or 0),
    )
```

### 14.7 Rename `_collect_changed_files`

**File:** `core/tools/capabilities.py`

```python
# Before:
async def _collect_changed_files(self) -> list[str]:
# After:
async def _list_non_bundle_files(self) -> list[str]:
```

### 14.8 Remove `serialize_enum` If Unnecessary

**File:** `core/model/types.py`

`serialize_enum(value)` just does `value.value if isinstance(value, StrEnum) else str(value)`. With `StrEnum`, `str(value)` already returns the value. Check all call sites — if they can use `str()` or `.value` directly, delete `serialize_enum` entirely.

```bash
rg "serialize_enum" src/
```

### 14.9 Verify

```bash
devenv shell -- pytest
devenv shell -- ruff check src/ tests/
```

---

## Phase 15: Final Cleanup Sweep

This is the last pass. Go through the entire codebase looking for leftover artifacts.

### 15.1 Dead Code Scan

```bash
# Find unused imports
devenv shell -- ruff check src/ --select F401

# Find unused variables
devenv shell -- ruff check src/ --select F841

# Find unreachable code
devg shell -- ruff check src/ --select F811
```

### 15.2 Remove Stale `# noqa` Comments

```bash
rg "# noqa" src/remora/ | grep -v "# noqa:" # malformed
rg "# noqa: ANN201" src/remora/  # add return type annotations instead
```

For each `# noqa: ANN201`, add the actual return type annotation and remove the noqa comment.

### 15.3 Remove Empty or Single-Use Modules

- `core/utils.py` — if `deep_merge` is the only function and it's used in one place, inline it
- After inlining `db.py` (Phase 13.6), verify it's deleted

### 15.4 Verify Re-exports Are Clean

Check every `__init__.py` in `core/` sub-packages. Every re-export should correspond to a real symbol that external code imports. Remove any re-exports that nothing uses:

```bash
for init in $(find src/remora/core -name "__init__.py"); do
    echo "=== $init ==="
    grep "from.*import" "$init"
done
```

For each re-exported symbol, verify it has at least one consumer outside its own package.

### 15.5 Verify `__all__` Lists Are Correct

Every module's `__all__` should match its public API. No private names (leading underscore) in `__all__` unless they're genuinely part of the public API (after Phase 13.7, `_deps_from_request` should already be renamed).

```bash
rg '^\s+"_' src/remora/ --glob "*__init__.py"
rg '^\s+"_' src/remora/ --glob "*.py" | grep "__all__"
```

### 15.6 Final Full Verification

```bash
devenv shell -- pytest
devenv shell -- ruff check src/ tests/
devenv shell -- python -c "import remora"  # smoke test
```

---

## Appendix A: Complete File Inventory

Files that are **modified** during this refactor:

| File | Phases |
|------|--------|
| `core/model/errors.py` | 1 |
| `core/model/types.py` | 14 |
| `core/model/node.py` | 8 |
| `core/model/config.py` | 14 |
| `core/events/types.py` | 6, 10 |
| `core/events/bus.py` | 1, 2, 5 |
| `core/events/store.py` | 4, 10, 13 |
| `core/events/subscriptions.py` | 3, 6 |
| `core/events/dispatcher.py` | 3 |
| `core/agents/turn.py` | 1 |
| `core/agents/kernel.py` | 1 |
| `core/agents/outbox.py` | 14 |
| `core/tools/capabilities.py` | 4, 7, 14 |
| `core/tools/context.py` | 4, 7 |
| `core/tools/grail.py` | 1, 7, 13, 14 |
| `core/storage/transaction.py` | 5 |
| `core/storage/workspace.py` | 14 |
| `core/services/container.py` | 3, 4, 11 |
| `core/services/lifecycle.py` | 1, 5, 6, 13 |
| `core/services/search.py` | 1, 11 |
| `core/services/metrics.py` | 13 |
| `core/utils.py` | 9 |
| `code/reconciler.py` | 1, 2, 8, 12 |
| `code/languages.py` | 13 |
| `code/virtual_agents.py` | 8, 13 |
| `web/sse.py` | 5, 10 |
| `web/deps.py` | 4, 13 |
| `web/middleware.py` | 14 |
| `web/routes/proposals.py` | 9 |
| `web/routes/chat.py` | 4, 13 |
| `web/routes/nodes.py` | 13, 14 |
| `web/routes/cursor.py` | (no changes — emit API unchanged) |
| `bundles/**/*.pym` | 7 |

Files that are **created** during this refactor:

| File | Phase |
|------|-------|
| `core/services/broker.py` | 4 |
| `code/provisioner.py` | 12 |
| `code/indexer.py` | 12 |
| `code/node_reconciler.py` | 12 |

Files that are **deleted** during this refactor:

| File | Phase |
|------|-------|
| `core/storage/db.py` | 13 |

---

## Appendix B: Verification Checklist

Run after completing all phases:

- [ ] `devenv shell -- pytest` — all tests pass
- [ ] `devenv shell -- ruff check src/ tests/` — no lint errors
- [ ] `rg "except Exception" src/remora/` — only 2 hits (grail.py boundary, kernel.py boundary)
- [ ] `rg "# noqa: BLE001" src/` — no hits
- [ ] `rg "getattr\(event" src/remora/` — no hits
- [ ] `rg "set_tx" src/ tests/` — no hits
- [ ] `rg "pending_response\|create_response_future\|resolve_response\|discard_response_future" src/remora/core/events/` — no hits (moved to broker)
- [ ] `rg "asyncio\.gather" src/remora/` — minimal hits (only where TaskGroup doesn't fit)
- [ ] `rg "subscribe\(.*Event[^T]" src/remora/` — no class-based subscribe calls
- [ ] `rg "_deps_from_request\b" src/` — no hits (renamed to `deps_from_request`)
- [ ] `rg "serialize_enum" src/` — no hits (or justified uses only)
- [ ] No files remain in `core/storage/db.py`
- [ ] Every `__init__.py` has clean `__all__` with no underscore-prefixed names
- [ ] `devenv shell -- python -c "import remora"` — no import errors
