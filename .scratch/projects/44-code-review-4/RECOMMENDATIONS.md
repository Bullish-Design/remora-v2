# Remora v2 — Recommendations & Improvements

**Date:** 2026-03-17
**Context:** Post-code-review recommendations. No backwards compatibility concerns.
**Priority:** P0 (do now) > P1 (do soon) > P2 (do when convenient) > P3 (nice to have)

---

## Table of Contents

1. [P0 — Architectural Fixes](#p0--architectural-fixes)
2. [P1 — Design Improvements](#p1--design-improvements)
3. [P2 — Code Quality](#p2--code-quality)
4. [P3 — Polish & Ergonomics](#p3--polish--ergonomics)

---

## P0 — Architectural Fixes

These are fundamental structural issues that will compound in cost the longer they're deferred.

### 1. Unify Event Dispatch to a Single Mechanism

**Problem:** Events are routed two completely different ways — by Python type in `EventBus` and by string `event_type` in `SubscriptionRegistry`. These systems must agree but have no shared contract.

**Recommendation:** Eliminate the dual dispatch. Choose one:

- **Option A (recommended): String-based dispatch everywhere.** Remove the type-based `EventBus._handlers` dict. Use `event_type` strings as the universal dispatch key. The `subscribe(event_type: str, handler)` method replaces `subscribe(EventClass, handler)`. This is simpler, serializable, and consistent with the persistence layer.

- **Option B: Type-based dispatch everywhere.** Map stored string event types back to Python classes on load. This is more Pythonic but requires a global registry of event type string → class mappings.

The key insight is: subscriptions (the persistent, trigger-driven system) are the more important routing mechanism. The in-memory EventBus is secondary. Align the simpler system to the more important one.

**Files affected:** `events/bus.py`, `events/subscriptions.py`, `events/dispatcher.py`, `events/store.py`, all subscriber code.

---

### 2. Inject Dependencies Properly — Kill the `_tx` Monkey-Patch

**Problem:** `RuntimeServices.__init__` patches `self.subscriptions._tx = self.tx` after construction, violating encapsulation and creating a hidden circular dependency.

**Recommendation:** Restructure initialization so all dependencies flow downward:

```python
# TransactionContext is created first
tx = TransactionContext(db, event_bus, dispatcher)

# All stores receive tx at construction
subscriptions = SubscriptionRegistry(db, tx=tx)
dispatcher = TriggerDispatcher(subscriptions)
node_store = NodeStore(db, tx=tx)
event_store = EventStore(db, event_bus, dispatcher, metrics, tx=tx)
```

The `SubscriptionRegistry` already accepts `tx` as a constructor parameter — the monkey-patch just happens because `dispatcher` needs `subscriptions` but `tx` needs `dispatcher`. Break this cycle by making `TriggerDispatcher` accept subscriptions lazily (it already supports `router` being None initially — do the same for subscriptions).

**Files affected:** `services.py`, `events/subscriptions.py`, `events/dispatcher.py`, `transaction.py`.

---

### 3. Define Error Hierarchies — Stop Catching `Exception`

**Problem:** 15+ instances of `except Exception: # noqa: BLE001` swallow programming errors. This makes production debugging nearly impossible.

**Recommendation:** Define a hierarchy of expected exceptions:

```python
# core/errors.py
class RemoraError(Exception): pass
class ModelError(RemoraError): pass        # LLM backend failures
class ToolError(RemoraError): pass         # Grail tool execution failures  
class WorkspaceError(RemoraError): pass    # Cairn/filesystem failures
class SubscriptionError(RemoraError): pass # Event routing failures
class IncompatibleBundleError(RemoraError): pass  # (already exists)
```

Then replace each `except Exception` with the specific error type(s) expected at that boundary. For example:
- `turn_executor.py` outer catch → `except (ModelError, ToolError, WorkspaceError)`
- `grail.py` tool execution → `except ToolError`
- `reconciler.py` watch handler → `except (WorkspaceError, OSError)`

**Files affected:** `core/errors.py`, every file with `# noqa: BLE001`.

---

### 4. Adopt Structured Concurrency (TaskGroups)

**Problem:** Manual `asyncio.Task` management throughout — tasks in lists, `gather` calls, manual cancellation in finally blocks. This leads to task leaks, orphaned tasks, and complex shutdown code.

**Recommendation:** Since the project targets Python 3.13+, use `asyncio.TaskGroup` everywhere:

- `lifecycle.py` — replace the `self._tasks` list with a TaskGroup
- `bus.py` — replace `asyncio.gather(*tasks)` with a TaskGroup in `_dispatch_handlers`
- `sse.py` — use a TaskGroup for the disconnect/shutdown/stream tasks
- `runner.py` — consider a TaskGroup for actor lifecycle

This eliminates the 65-line `shutdown()` method and makes error propagation automatic.

**Files affected:** `lifecycle.py`, `bus.py`, `sse.py`, `runner.py`.

---

### 5. Extract Human-Input Futures from EventStore

**Problem:** EventStore manages `_pending_responses` (human-input futures) alongside event persistence and bus emission. This violates SRP.

**Recommendation:** Create a `HumanInputBroker` service:

```python
class HumanInputBroker:
    def create_request(self, request_id: str) -> asyncio.Future[str]: ...
    def resolve(self, request_id: str, response: str) -> bool: ...
    def discard(self, request_id: str) -> bool: ...
```

Inject it into `CommunicationCapabilities` and the web `api_respond` handler. Remove all future-related methods from EventStore.

**Files affected:** `events/store.py`, `externals.py`, `web/routes/chat.py`, `services.py`.

---

## P1 — Design Improvements

### 6. Make Event Subscription Matching Type-Safe

**Problem:** `SubscriptionPattern.matches` uses `getattr(event, "from_agent", None)` — accessing fields that may not exist on the event subclass. Renamed fields silently break matching.

**Recommendation:** Define a `RoutingEnvelope` that every event provides:

```python
class RoutingEnvelope:
    event_type: str
    agent_id: str | None
    from_agent: str | None
    to_agent: str | None
    path: str | None
    tags: tuple[str, ...]

class Event(BaseModel):
    def routing_envelope(self) -> RoutingEnvelope: ...
```

Each event subclass overrides `routing_envelope()` to map its fields to the standard routing attributes. `SubscriptionPattern.matches` operates on the envelope, never on raw event attributes. This creates a stable, documented, testable contract between events and subscriptions.

**Files affected:** `events/types.py`, `events/subscriptions.py`.

---

### 7. Split SearchService into Strategy Implementations

**Problem:** `SearchService` has `if self._client ... elif self._pipeline ...` branching in every method.

**Recommendation:** Two implementations of `SearchServiceProtocol`:

```python
class RemoteSearchService:  # wraps embeddy client
    ...

class LocalSearchService:   # wraps in-process embeddy
    ...

def create_search_service(config: SearchConfig, project_root: Path) -> SearchServiceProtocol:
    if config.mode == "remote":
        return RemoteSearchService(config)
    return LocalSearchService(config, project_root)
```

**Files affected:** `search.py`.

---

### 8. Decompose FileReconciler

**Problem:** FileReconciler is a God class with 400+ lines and 15+ methods covering file watching, node CRUD, bundle provisioning, search indexing, subscription management, directory management, and virtual agent management.

**Recommendation:** Extract focused collaborators that the reconciler orchestrates:

- `NodeReconciler` — handles add/update/remove of discovered nodes
- `BundleProvisioner` — handles bundle template resolution and workspace provisioning
- `SearchIndexer` — handles search indexing/deindexing
- Keep `DirectoryManager` and `VirtualAgentManager` as-is (already extracted)
- `FileReconciler` becomes a thin orchestrator calling these in sequence

**Files affected:** `code/reconciler.py`, new files for extracted classes.

---

### 9. Namespace Capability Functions

**Problem:** `TurnContext.to_capabilities_dict()` merges all capability groups into a flat dict. Name collisions are silent.

**Recommendation:** Either:

- **Option A:** Namespace by group: `{"files.read_file": fn, "graph.get_node": fn, ...}`
- **Option B:** Keep flat but use a `MergeConflictError` if two groups define the same key
- **Option C:** Use a `Capabilities` object instead of a dict, with attribute-style access per group

Option A is simplest and most robust. It requires updating Grail tool scripts to reference `files.read_file` instead of `read_file`, but since we don't care about backwards compatibility, this is fine.

**Files affected:** `externals.py`, `grail.py`, all `.pym` tool scripts.

---

### 10. Make Node Immutable — Use `model_copy` for Updates

**Problem:** `Node` is a mutable Pydantic model. Status and role are mutated in place during reconciliation, breaking Pydantic's value proposition.

**Recommendation:** Set `frozen=True` on Node. Replace mutation with `node.model_copy(update={"status": new_status})`. This makes change tracking possible and prevents accidental mutation.

**Files affected:** `node.py`, `reconciler.py`, `directories.py`, `virtual_agents.py`.

---

### 11. Atomic File Writes for Proposal Accept

**Problem:** `api_proposal_accept` writes files in place with no fsync or atomic rename. A crash or disk-full condition corrupts user source code.

**Recommendation:**

```python
import tempfile

def atomic_write(path: Path, content: bytes) -> None:
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        os.write(fd, content)
        os.fsync(fd)
        os.close(fd)
        os.replace(tmp_path, path)  # atomic on POSIX
    except:
        os.close(fd)
        os.unlink(tmp_path)
        raise
```

**Files affected:** `web/routes/proposals.py`.

---

### 12. Use Database Row IDs for SSE Event IDs

**Problem:** SSE uses `event.timestamp` as the event ID. Timestamps are not unique.

**Recommendation:** The `EventStore.append` method already returns the database row ID (`event_id`). Thread this through to the SSE generator. For live-streamed events, include the row ID in the event's envelope or use a monotonic counter.

**Files affected:** `sse.py`, `events/store.py`, `events/types.py`.

---

## P2 — Code Quality

### 13. Extract Shared JSON Deserialization in EventStore

All four query methods (`get_events`, `get_events_for_agent`, `get_latest_event_by_type`, `get_events_after`) have identical JSON parsing logic. Extract to `_deserialize_row(row) -> dict[str, Any]`.

### 14. DRY the Language Plugin Classes

`PythonPlugin` and `GenericLanguagePlugin` share 90% of their code. Extract a `BaseLanguagePlugin` with the shared `get_language()`, `get_query()`, `_resolve_query_file()` methods. Subclasses only override `resolve_node_type()`.

### 15. Replace FIFO Script Cache with `functools.lru_cache`

The `_PARSED_SCRIPT_CACHE` dict in `grail.py` is a manual FIFO cache labeled as LRU. Replace with `@functools.lru_cache(maxsize=256)` or use `cachetools.LRUCache` for an actual LRU.

### 16. Add Input Length Limits to Web Endpoints

Chat messages, search queries, and node IDs should have maximum length validation. A 1MB chat message should be rejected at the API boundary, not stored in SQLite and sent to an LLM.

### 17. Fix `RegisterSubscriptionsFn` to be a `Protocol`

```python
class RegisterSubscriptionsFn(Protocol):
    async def __call__(
        self,
        node: Node,
        *,
        virtual_subscriptions: tuple[SubscriptionPattern, ...] = (),
    ) -> None: ...
```

### 18. Remove Vestigial `db.py` Module

Inline `open_database` into the one place it's called (`lifecycle.py`). Remove the `Connection` type alias. If a proper database layer is needed later, build it then — don't leave a placeholder.

### 19. Make `_deps_from_request` and `_get_chat_limiter` Public

Remove the leading underscores. They're in `__all__` and imported by multiple route modules. The underscore prefix is actively misleading.

### 20. Add Pagination to `/api/nodes`

```python
async def api_nodes(request: Request) -> JSONResponse:
    limit = int(request.query_params.get("limit", "100"))
    offset = int(request.query_params.get("offset", "0"))
    # ... paginated query
```

### 21. Replace `snapshot()` manual field listing with reflection

```python
def snapshot(self) -> dict[str, Any]:
    data = dataclasses.asdict(self)
    data["uptime_seconds"] = round(self.uptime_seconds, 1)
    data["cache_hit_rate"] = round(self.cache_hit_rate, 3)
    return data
```

---

## P3 — Polish & Ergonomics

### 22. Use `asyncio.TaskGroup` for Deferred Event Fan-Out

In `TransactionContext.batch()`, replace the sequential `for event in self._deferred_events` loop with a TaskGroup for parallel emission.

### 23. Add IPv6 Loopback to CSRF Middleware

```python
return host in {"localhost", "127.0.0.1", "::1"}
```

### 24. Add `agent_id` as a Public Property on `AgentWorkspace`

Replace the `getattr(workspace, "_agent_id", "?")` pattern in `grail.py` with a proper public property.

### 25. Make Trigger Policy Constants Configurable

Move `_DEPTH_TTL_MS` and `_DEPTH_CLEANUP_INTERVAL` from module-level constants to `RuntimeConfig` fields.

### 26. Log Truncation Indicator in API Responses

When `api_conversation` truncates message content at 2000 chars, include a `"truncated": true` field in the response.

### 27. Cache Config File Discovery

`_find_config_file` walks the directory tree on every call. Cache the result after the first successful resolution, or accept `None` to skip the walk.

### 28. Consider `OutboxObserver` Dispatch Table

Replace the isinstance chain with a dict mapping:

```python
_TRANSLATION_MAP = {
    SAModelRequestEvent: _translate_model_request,
    SAModelResponseEvent: _translate_model_response,
    # ...
}
```

### 29. Add a `__repr__` to Key Domain Objects

`Node`, `Event`, `Actor`, and `Edge` would benefit from readable `__repr__` implementations for debugging.

### 30. Improve `_collect_changed_files` Naming

Rename to `_list_workspace_files` or `_list_non_bundle_files` to accurately describe behavior.

---

## Implementation Priority Matrix

| # | Recommendation | Effort | Impact | Priority |
|---|---------------|--------|--------|----------|
| 1 | Unify event dispatch | HIGH | HIGH | P0 |
| 2 | Fix DI / kill monkey-patch | LOW | HIGH | P0 |
| 3 | Error hierarchies | MEDIUM | HIGH | P0 |
| 4 | Structured concurrency | MEDIUM | HIGH | P0 |
| 5 | Extract HumanInputBroker | LOW | MEDIUM | P0 |
| 6 | Type-safe subscription matching | MEDIUM | HIGH | P1 |
| 7 | Split SearchService | LOW | MEDIUM | P1 |
| 8 | Decompose FileReconciler | HIGH | HIGH | P1 |
| 9 | Namespace capabilities | MEDIUM | HIGH | P1 |
| 10 | Immutable Node | LOW | MEDIUM | P1 |
| 11 | Atomic file writes | LOW | HIGH | P1 |
| 12 | SSE event IDs | LOW | MEDIUM | P1 |
| 13-21 | Code quality batch | LOW each | MEDIUM | P2 |
| 22-30 | Polish batch | LOW each | LOW | P3 |

---

*End of recommendations.*
