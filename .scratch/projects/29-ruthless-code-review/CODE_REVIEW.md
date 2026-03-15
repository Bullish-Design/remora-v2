# Remora v2 — Ruthless Code Review

**Reviewer**: Senior Staff Engineer
**Date**: 2026-03-15
**Codebase**: `src/remora/` — 5,462 lines across 32 Python files
**Test suite**: 257 passing, 5 skipped, 37 deprecation warnings
**Linter**: 9 ruff violations (5 auto-fixable import sorting issues)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Architecture Assessment](#2-architecture-assessment)
3. [Module-by-Module Review](#3-module-by-module-review)
4. [Cross-Cutting Concerns](#4-cross-cutting-concerns)
5. [Security Review](#5-security-review)
6. [Testing Assessment](#6-testing-assessment)
7. [Performance & Scalability](#7-performance--scalability)
8. [Code Quality & Style](#8-code-quality--style)
9. [Severity Summary](#9-severity-summary)

---

## 1. Executive Summary

The codebase is **competent but not yet production-grade**. The intern has produced a coherent architecture with clear separation of concerns, but there are meaningful gaps in error handling, concurrency safety, resource management, and API design that need to be addressed before this can be trusted in a real deployment. The test suite is respectable in coverage breadth but thin on edge cases and concurrency scenarios.

**Overall grade: B-** — solid skeleton, needs hardening.

---

## 2. Architecture Assessment

### What's Good
- Clean layered architecture: `code/` (discovery) → `core/` (runtime) → surfaces (`web/`, `lsp/`, CLI)
- Event-driven design with proper separation: `EventBus` (in-memory fanout), `EventStore` (persistence), `TriggerDispatcher` (subscription routing)
- Actor model with per-actor inbox, cooldown, and depth limits
- Pydantic models for configuration and data
- Plugin system for language support via `LanguagePlugin` protocol

### What's Concerning
- **God function in `__main__.py`**: `_start()` is 130+ lines of imperative setup, teardown, and lifecycle management. This is the most fragile part of the system — a single function managing 5+ concurrent subsystems with complex shutdown ordering.
- **No dependency injection framework**: `RuntimeServices` is a manual service container that works but creates tight coupling. Every test that needs services must replicate this wiring.
- **Mixed abstraction levels**: `Actor` does prompt construction, bundle reading, kernel invocation, event emission, and state management — it's a 650-line class doing at least 4 distinct jobs.
- **Circular awareness**: `reconciler.py` knows about `EventStore`, `NodeStore`, `CairnWorkspaceService`, `Config`, discovery, paths, projections — it's the system's central coupling point at 620 lines.

---

## 3. Module-by-Module Review

### 3.1 `core/types.py` — ✅ Clean
- Status transition table is explicit and testable. No issues.

### 3.2 `core/config.py` — ⚠️ Minor Issues

**ISSUE [C-1] (Medium): `resolve_bundle` uses duck-typing instead of proper enum handling**
```python
# Line 159
normalized_type = node_type.value if hasattr(node_type, "value") else str(node_type)
```
This `hasattr(x, "value")` pattern appears 8+ times across the codebase. It's a code smell indicating the type boundaries between StrEnum and str are not well-defined. Pick one representation and enforce it at the boundary.

**ISSUE [C-2] (Low): `_expand_env_vars` handles tuples but YAML never produces them**
Line 189-190 handles tuples, but `yaml.safe_load` never returns tuples. This is dead code or anticipatory code for a case that doesn't exist.

### 3.3 `core/db.py` — ⚠️ Thin

**ISSUE [D-1] (Medium): No connection pooling or reconnection logic**
A single `aiosqlite.Connection` is shared across all async operations. While SQLite WAL mode helps, there's no retry-on-lock, no connection health check, and the `busy_timeout=5000` is the only protection against contention.

**ISSUE [D-2] (Low): `PRAGMA` results not verified**
The pragmas are fire-and-forget. WAL mode activation should be verified (it can silently fail in some configurations).

### 3.4 `core/node.py` — ⚠️ Minor Issues

**ISSUE [N-1] (Medium): `to_row()` / `from_row()` duck-type enum values**
```python
data["node_type"] = (
    data["node_type"].value if hasattr(data["node_type"], "value") else data["node_type"]
)
```
Same `hasattr` pattern. This should be a clean serialization boundary — use `.value` unconditionally since `node_type` is typed as `NodeType` (a StrEnum).

**ISSUE [N-2] (Low): `from_row()` uses string annotation `"Node"` instead of `Self`**
```python
def from_row(cls, row: dict[str, Any]) -> "Node":
```
With `from __future__ import annotations`, this is fine functionally, but `Self` from `typing` is more idiomatic in Python 3.13.

### 3.5 `core/events/types.py` — ⚠️ Design Issues

**ISSUE [E-1] (Medium): `Event.model_post_init` mutates a "base model" field**
```python
def model_post_init(self, __context: Any) -> None:
    if not self.event_type:
        self.event_type = type(self).__name__
```
This is clever but fragile — `event_type` defaults to `""` and gets mutated after init. If the model is ever frozen or validated after construction, this breaks. Use `@model_validator` or a `default_factory` that inspects the class instead.

**ISSUE [E-2] (Medium): `ToolResultEvent` vs `RemoraToolResultEvent` — naming collision**
Two event types with nearly identical names and overlapping semantics:
- `ToolResultEvent` (line 196): `agent_id`, `tool_name`, `result_summary`
- `RemoraToolResultEvent` (line 172): `agent_id`, `tool_name`, `is_error`, `duration_ms`, `output_preview`

This is confusing. One appears to be the legacy version. Consolidate or clearly document the distinction.

**ISSUE [E-3] (Low): 20+ event classes with no discriminated union**
There's no registry or discriminator for deserializing events from the database back into typed Python objects. Events are stored as JSON blobs and only ever read back as dicts. This means the type system is only half-used — types exist on the write path but not the read path.

### 3.6 `core/events/store.py` — ⚠️ Concerning

**ISSUE [ES-1] (High): `append()` commits after every single event**
```python
await self._db.commit()  # Line 95
```
Every event write triggers a SQLite WAL flush. Under moderate load (e.g., 10 agents doing tool calls), this creates a commit storm. Should batch commits or use write-ahead buffering.

**ISSUE [ES-2] (Medium): `_pending_responses` dict is never cleaned up on timeout**
The `create_response_future` / `resolve_response` / `discard_response_future` pattern works correctly when callers use it properly, but if a future is created and the caller crashes before resolving or discarding, the dict entry and future leak forever. There's no TTL-based cleanup.

**ISSUE [ES-3] (Medium): No pagination support for `get_events`**
`get_events_after` and `get_events` return up to 500 rows at once. For a long-running system, this is a full table scan with LIMIT. There's no cursor-based pagination.

**ISSUE [ES-4] (Low): `get_events_after` accepts `str` but stores `int` IDs**
The parameter is `after_id: str` but the column is `INTEGER PRIMARY KEY`. The type mismatch (with `int()` conversion) suggests this was designed for the SSE endpoint where IDs come from query strings, but it's a leaky abstraction.

### 3.7 `core/events/bus.py` — ⚠️ Subtle Bug

**ISSUE [B-1] (High): MRO-based dispatch causes duplicate handler calls**
```python
async def emit(self, event: Event) -> None:
    for event_type in type(event).__mro__:
        await self._dispatch_handlers(self._handlers.get(event_type, []), event)
    await self._dispatch_handlers(self._all_handlers, event)
```
If a handler is registered for `Event` (the base class), it gets called once from the MRO walk AND once from the base class's own entry. But more critically: the MRO includes `object`, `BaseModel`, etc. — every class in the MRO is checked against `self._handlers`. This is wasteful and could cause surprising behavior if someone registers a handler for `BaseModel`.

**ISSUE [B-2] (Medium): `stream()` creates unbounded queue**
```python
queue: asyncio.Queue[Event] = asyncio.Queue()
```
If a consumer is slow and events arrive quickly, this queue grows without bound. Should use `asyncio.Queue(maxsize=N)` with backpressure or a drop policy.

**ISSUE [B-3] (Low): `unsubscribe` uses identity comparison, not equality**
```python
if handler in handlers:
    handlers.remove(handler)
```
This uses `__eq__` (list `in`), which for functions falls back to identity. Fine for most cases, but `remove` only removes the first occurrence — if the same handler is registered twice, only one is removed.

### 3.8 `core/events/subscriptions.py` — ⚠️ Performance

**ISSUE [S-1] (Medium): Cache invalidation on every write**
```python
async def register(self, agent_id: str, pattern: SubscriptionPattern) -> int:
    ...
    self._cache = None  # Line 86
```
Every `register()` or `unregister()` nukes the entire in-memory cache. During startup reconciliation (which registers subscriptions for every node), the cache is rebuilt from scratch after each registration. For N nodes, this is O(N²) database reads.

**ISSUE [S-2] (Low): `PurePath.match()` for glob matching**
```python
if path is None or not PurePath(path).match(self.path_glob):
```
`PurePath.match()` has different semantics than `fnmatch` — notably, it's case-insensitive on Windows and handles `**` differently across Python versions. The behavior is platform-dependent.

### 3.9 `core/actor.py` — ⚠️ Multiple Issues (Largest File)

**ISSUE [A-1] (High): `_depths` dict grows unboundedly**
```python
self._depths: dict[str, int] = {}  # Line 225
```
The comment on line 297 says "Clean stale depth entries (done here rather than on a timer to keep it simple)" — but the cleaning never happens! The `_should_trigger` method increments `_depths[correlation_id]` but never removes old entries. `_reset_agent_state` decrements but only for the current correlation_id. Over time, this dict accumulates one entry per unique correlation_id seen by this actor.

**ISSUE [A-2] (High): `OutboxObserver._translate()` uses class name string matching**
```python
event_name = type(event).__name__
if event_name == "ModelRequestEvent":
    ...
```
This is extremely fragile. If the upstream library renames or refactors its event types, this silently stops translating events with no error. Use `isinstance()` or import the actual types.

**ISSUE [A-3] (Medium): `RecordingOutbox` is production code in a production module**
A test double (`RecordingOutbox`) lives in `core/actor.py` rather than in `tests/`. This violates separation of concerns and ships test infrastructure to production.

**ISSUE [A-4] (Medium): `_read_bundle_config` catches both `FileNotFoundError` and `FsdFileNotFoundError`**
```python
except (FileNotFoundError, FsdFileNotFoundError):
```
The fact that the Cairn/fsdantic library raises its own `FileNotFoundError` that's not a subclass of the builtin is a dependency smell, but more importantly this pattern is repeated in `grail.py` too. Should be handled at the `AgentWorkspace` boundary.

**ISSUE [A-5] (Medium): Full response text logged at INFO level**
```python
turn_log.info(
    "Agent turn complete node=%s corr=%s response=%s",
    node_id,
    trigger.correlation_id,
    response_text,  # Line 518 — unbounded string at INFO level
)
```
LLM responses can be thousands of characters. This should be truncated or logged at DEBUG.

**ISSUE [A-6] (Low): `_build_prompt` embeds source code without length limits**
The entire `node.source_code` is injected into the prompt. For large classes or functions, this could exceed model context limits with no protection.

### 3.10 `core/runner.py` — ⚠️ Minor Issues

**ISSUE [R-1] (Medium): `run_forever()` polls with `asyncio.sleep(1.0)`**
```python
while self._running:
    await asyncio.sleep(1.0)
    await self._evict_idle()
```
The main loop's only purpose is idle eviction, but it wakes up every second even when no actors are idle. Should use `asyncio.Event` or a timer-based approach.

**ISSUE [R-2] (Low): `_evict_idle` hardcodes 300s timeout**
```python
async def _evict_idle(self, max_idle_seconds: float = 300.0) -> None:
```
This should come from `Config`, not be a hardcoded default argument.

### 3.11 `core/graph.py` — ⚠️ Performance

**ISSUE [G-1] (Medium): `transition_status` requires two round-trips**
```python
async def transition_status(self, node_id: str, target: NodeStatus) -> bool:
    node = await self.get_node(node_id)  # SELECT
    ...
    await self.set_status(node_id, target)  # UPDATE + COMMIT
```
This is a read-then-write pattern with no locking. Two concurrent callers could both read "idle", both validate the transition, and both set "running". Should use `UPDATE ... WHERE status = ?` atomically.

**ISSUE [G-2] (Medium): Every `upsert_node` and `set_status` commits immediately**
Same as ES-1 — excessive commits. High-throughput reconciliation creates many small transactions.

**ISSUE [G-3] (Low): `list_nodes` builds SQL with f-string**
```python
sql = f"SELECT * FROM nodes{where_clause} ORDER BY node_id ASC"
```
While `where_clause` is constructed from controlled strings (not user input), using f-strings for SQL is a bad habit. Prefer a query builder or at minimum add a comment noting the safety invariant.

### 3.12 `core/kernel.py` — ✅ Clean
Thin wrapper, appropriately minimal. No issues.

### 3.13 `core/services.py` — ⚠️ Minor

**ISSUE [SV-1] (Low): `create_tables()` called 3 times with overlapping schema**
```python
await self.node_store.create_tables()     # Creates nodes, edges
await self.subscriptions.create_tables()  # Creates subscriptions
await self.event_store.create_tables()    # Creates events, ALSO calls subscriptions.create_tables()
```
`event_store.create_tables()` internally calls `self._dispatcher.subscriptions.create_tables()` (store.py:64), so subscriptions table is created twice. Not harmful (IF NOT EXISTS), but sloppy.

### 3.14 `core/workspace.py` — ⚠️ Minor Issues

**ISSUE [W-1] (Medium): SHA-1 for filesystem-safe IDs**
```python
digest = hashlib.sha1(node_id.encode("utf-8")).hexdigest()[:10]
```
SHA-1 is cryptographically broken. For generating unique filenames this is fine functionally, but using SHA-1 anywhere in new code is a red flag in reviews. Use SHA-256 truncated.

**ISSUE [W-2] (Low): `_merge_dicts` and `_bundle_template_fingerprint` are module-level privates defined after `__all__`**
These functions are placed after the `__all__` declaration, which is unconventional and makes them easy to miss.

### 3.15 `core/externals.py` — ⚠️ Security Concern

**ISSUE [X-1] (High): `graph_set_status` has no authorization**
```python
async def graph_set_status(self, target_id: str, new_status: str) -> bool:
    await self._node_store.set_status(target_id, new_status)
    return True
```
Any agent can set any other agent's status to any string, bypassing `validate_status_transition()`. This calls `set_status` directly (not `transition_status`), meaning an agent can force another agent into an invalid state.

**ISSUE [X-2] (Medium): `search_content` is O(N*M) with no limits**
```python
async def search_content(self, pattern: str, path: str = ".") -> list[dict[str, Any]]:
    paths = await self.workspace.list_all_paths()
    for file_path in paths:
        content = await self.workspace.read(normalized)
        for index, line in enumerate(content.splitlines(), start=1):
            if pattern in line:
                matches.append(...)
```
Reads every file in the workspace and scans every line. No result limit, no timeout, no file size limit. A large workspace could OOM or hang.

**ISSUE [X-3] (Medium): `broadcast` with pattern `*` sends to ALL agents**
No rate limiting or confirmation. A misbehaving agent can spam every other agent in the system.

### 3.16 `core/grail.py` — ⚠️ Caching Concern

**ISSUE [GR-1] (Medium): `_cached_script` uses `lru_cache` with `source` as key**
```python
@lru_cache(maxsize=256)
def _cached_script(content_hash: str, normalized_name: str, source: str) -> grail.GrailScript:
```
The `source` parameter is a potentially large string being used as a cache key. `lru_cache` stores all arguments, so this cache holds up to 256 copies of full script source text in memory. The `content_hash` alone should be sufficient as the key.

**ISSUE [GR-2] (Low): Temp directory created for every cache miss**
Each uncached script creates a temporary directory, writes the file, loads it, then the directory is cleaned up. This is the correct pattern for `grail.load()` but highlights that `grail` doesn't support loading from a string, which is an upstream limitation being worked around.

### 3.17 `core/metrics.py` — ⚠️ Thread Safety

**ISSUE [M-1] (Medium): Mutable counter fields with no synchronization**
```python
self._metrics.events_emitted_total += 1  # From event_store
self._metrics.agent_turns_total += 1      # From actor
self._metrics.active_actors = len(...)    # From runner
```
These are plain int attributes modified from multiple async tasks. In CPython with the GIL, `+=` on ints is actually not atomic (it's LOAD_FAST + BINARY_ADD + STORE_FAST). In practice, asyncio's single-threaded event loop makes this safe *today*, but it's fragile — any use of `asyncio.to_thread()` or a future runtime change breaks it.

### 3.18 `code/discovery.py` — ✅ Mostly Clean

**ISSUE [CD-1] (Low): Module-level `lru_cache` for registry/parser/query**
These are module-level caches that persist for the process lifetime. Fine for a long-running server, but means tests can't easily reset state. (The test suite appears to work around this by not testing discovery caching directly.)

### 3.19 `code/reconciler.py` — ⚠️ Complex (Largest Module)

**ISSUE [RC-1] (High): `_file_locks` dict grows unboundedly**
```python
self._file_locks: dict[str, asyncio.Lock] = {}
```
A new lock is created for every unique file path ever reconciled. These are never cleaned up. For a project with thousands of files and churn, this leaks memory.

**ISSUE [RC-2] (Medium): Full re-discovery for every file change**
```python
discovered = discover([Path(file_path)], ...)  # Line 362
```
Every file reconciliation re-parses the entire file with tree-sitter, rebuilds the node list, and does N database lookups (one `get_node` per discovered node). For rapid-fire saves, this could be expensive.

**ISSUE [RC-3] (Medium): Subscription re-registration on every node change**
When a node's hash changes, `_register_subscriptions` is called, which:
1. Unregisters all existing subscriptions for the agent
2. Re-registers 2-3 new subscriptions
Each of these is a separate DB operation with commit + cache invalidation (see S-1).

**ISSUE [RC-4] (Low): `_subscriptions_bootstrapped` flag is set inside `_materialize_directories`**
Line 305 sets `self._subscriptions_bootstrapped = True` at the end of directory materialization, but this flag guards subscription refresh for ALL node types. The interleaving of startup-specific flags with runtime behavior is confusing.

### 3.20 `code/projections.py` — ✅ Clean
Short, focused module. No significant issues.

### 3.21 `code/paths.py` — ✅ Clean
Simple path resolution and walking. No issues.

### 3.22 `code/languages.py` — ✅ Clean
Well-structured plugin system. Protocol class is properly defined.

### 3.23 `web/server.py` — ⚠️ Multiple Issues

**ISSUE [WS-1] (High): No CSRF protection on state-mutating POST endpoints**
`api_chat`, `api_respond`, `api_proposal_accept`, `api_proposal_reject`, `api_cursor` — all accept POST requests with no CSRF token, no Origin header check. Any page the user visits could make requests to `localhost:8080`.

**ISSUE [WS-2] (High): `_workspace_path_to_disk_path` path traversal risk**
```python
if source_path.startswith("/"):
    return Path(source_path)  # Line 81
```
If workspace_path starts with `source//etc/passwd`, this returns an absolute path outside the project. The workspace path comes from agent-proposed files which could be manipulated.

**ISSUE [WS-3] (Medium): `api_proposal_accept` writes files to disk without validation**
```python
disk_path.parent.mkdir(parents=True, exist_ok=True)
disk_path.write_bytes(new_bytes)
```
Combined with WS-2, this could write arbitrary files to disk. Even without path traversal, there's no check that the target is within the project root.

**ISSUE [WS-4] (Medium): SSE stream uses `event.timestamp` as event ID**
```python
yield f"id: {event.timestamp}\n..."
```
`event.timestamp` is a float (from `time.time()`). SSE IDs should be monotonically increasing integers. Two events with the same timestamp would have the same ID, causing the `Last-Event-ID` reconnection logic to miss events.

**ISSUE [WS-5] (Medium): Hardcoded version string**
```python
"version": "0.5.0",  # Line 333
```
Duplicated from `__init__.py`. Should import `remora.__version__`.

**ISSUE [WS-6] (Low): `create_app` is a 430-line closure-based function**
All endpoint handlers are closures inside `create_app`. This makes the function extremely long and difficult to test individual endpoints in isolation. Class-based views or a proper dependency injection pattern would be better.

**ISSUE [WS-7] (Low): Starlette `on_shutdown` deprecation**
The test suite generates 37 warnings about `on_shutdown` being deprecated in favor of `lifespan`. This should be migrated.

### 3.24 `lsp/server.py` — ⚠️ Minor Issues

**ISSUE [L-1] (Medium): `_remora_handlers` monkey-patches the server for testing**
```python
server._remora_handlers = { ... }  # type: ignore[attr-defined]
```
This is a testing backdoor that ships in production code. The LSP handlers should be extractable without monkey-patching.

**ISSUE [L-2] (Low): Hardcoded `localhost:8080` for chat command**
```python
uri=f"http://localhost:8080/?node={node_id}",
```
The port is configurable in the CLI but hardcoded in the LSP server.

**ISSUE [L-3] (Low): Standalone mode creates stores but never closes them**
`_open_standalone_stores` opens a database connection stored in a `stores` dict closure. There's no cleanup when the LSP server shuts down.

### 3.25 `__main__.py` — ⚠️ Issues

**ISSUE [M-1] (Medium): Shutdown logic has redundant reconciler stop**
```python
# Line 243-244
if services.reconciler is not None:
    services.reconciler.stop()
...
# services.close() also calls reconciler.stop()
```
The reconciler is stopped twice — once directly and once via `services.close()`. While `stop()` is idempotent, this reveals unclear ownership of shutdown sequencing.

**ISSUE [M-2] (Low): `assert` statements in production code**
```python
assert services.reconciler is not None  # Line 167
assert services.runner is not None      # Line 168
```
Asserts are stripped with `-O`. Use explicit checks with proper error messages.

---

## 4. Cross-Cutting Concerns

### 4.1 The `hasattr(x, "value")` Anti-Pattern
This appears in: `node.py:36-38`, `config.py:159`, `actor.py:548-549`, `lsp/server.py:211,235-236`, `web/server.py:387-389`.

The root cause is that `NodeType` and `NodeStatus` are `StrEnum` types whose `.value` is the same as `str(x)`. The codebase is inconsistent about whether it passes around StrEnums or plain strings. **Pick one and enforce it at boundaries.**

### 4.2 Excessive Per-Operation Commits
At least 8 modules call `await self._db.commit()` after single-row operations. During reconciliation of 100 files with 5 nodes each, this could mean 500+ individual commits. SQLite handles this, but it's needlessly slow.

### 4.3 No Structured Logging
The logging uses `%s` formatting throughout. There's a custom `_ContextFilter` for structured fields, but the messages themselves are unstructured strings. For a system that processes hundreds of events, structured logging (JSON lines) would be far more useful for debugging.

### 4.4 Inconsistent Error Handling
- `# noqa: BLE001` appears 5 times — bare `except Exception` at system boundaries
- Some locations log and re-raise, others swallow
- No custom exception hierarchy — everything is `Exception` or `RuntimeError`

---

## 5. Security Review

| Issue | Severity | Location |
|-------|----------|----------|
| Path traversal in workspace-to-disk mapping | HIGH | `web/server.py:81` |
| No CSRF on POST endpoints | HIGH | `web/server.py` (multiple) |
| Unrestricted agent status mutation | HIGH | `externals.py:145-147` |
| Agent broadcast without rate limiting | MEDIUM | `externals.py:196-208` |
| Unbounded search_content execution | MEDIUM | `externals.py:67-81` |
| SHA-1 usage | LOW | `workspace.py:185` |
| No input sanitization on chat messages | LOW | `web/server.py:136-137` |

---

## 6. Testing Assessment

### Strengths
- 257 tests with good breadth across all modules
- Proper async test fixtures with `pytest_asyncio`
- Clean factory pattern in `tests/factories.py`
- Unit tests properly isolated with in-memory databases

### Weaknesses
- **No concurrency tests**: The actor pool, event bus, and subscription system are concurrent by design but tested sequentially
- **No integration tests for the full startup/shutdown lifecycle**: `_start()` in `__main__.py` is untested
- **No load/stress tests**: The reconciler, event store, and actor pool have no tests under volume
- **5 skipped tests** without visible skip reasons in output
- **Test doubles in production code**: `RecordingOutbox` should be in `tests/`
- **No property-based testing**: Event serialization/deserialization and subscription matching are perfect candidates for hypothesis

---

## 7. Performance & Scalability

### Known Bottlenecks
1. **Per-event SQLite commits** (ES-1, G-2): ~1ms per commit under WAL mode, but serializes all writes
2. **O(N²) subscription cache rebuilds during startup** (S-1): For 1000 nodes with 3 subscriptions each, this is 3000 cache rebuilds
3. **Unbounded `_depths` and `_file_locks` dicts** (A-1, RC-1): Memory leaks
4. **Full file re-parse on every change** (RC-2): Tree-sitter supports incremental parsing, but it's not used
5. **`list_nodes()` returns all nodes** for health check (line 329): Should be `SELECT COUNT(*)`

### Estimated Scale Limits
- With current per-commit pattern: ~100 events/second
- With batched commits: ~5,000 events/second
- Actor pool: Limited by `max_concurrency` (default 4), which is appropriate
- Node count: Should handle 10,000+ nodes (SQLite indexed queries)
- Event history: No compaction/archival — table grows without bound

---

## 8. Code Quality & Style

### Good Practices
- Consistent use of `__all__` exports
- `from __future__ import annotations` everywhere
- Pydantic for data validation
- Type hints on all public functions
- Descriptive variable names

### Issues
- 9 ruff violations (import sorting), trivially fixable
- 37 Starlette deprecation warnings
- No `py.typed` marker for downstream type checking
- No `mypy` or `pyright` in CI (based on pyproject.toml)
- Several 100+ line functions (`_start`, `create_app`, `_materialize_directories`)
- Inconsistent blank lines before `__all__` declarations

---

## 9. Severity Summary

### High (Must Fix)
| ID | Issue | Module |
|----|-------|--------|
| WS-1 | No CSRF protection | web/server.py |
| WS-2 | Path traversal risk | web/server.py |
| X-1 | Unrestricted status mutation | externals.py |
| ES-1 | Per-event commits (perf) | events/store.py |
| A-1 | Unbounded _depths dict (leak) | actor.py |
| B-1 | Duplicate handler calls via MRO | events/bus.py |
| RC-1 | Unbounded _file_locks dict (leak) | reconciler.py |

### Medium (Should Fix)
| ID | Issue | Module |
|----|-------|--------|
| S-1 | O(N²) cache invalidation | subscriptions.py |
| G-1 | Race condition in transition_status | graph.py |
| A-2 | String-based event type matching | actor.py |
| A-3 | Test double in production code | actor.py |
| A-5 | Unbounded response text logging | actor.py |
| B-2 | Unbounded SSE queue | events/bus.py |
| WS-3 | Unvalidated disk writes | web/server.py |
| WS-4 | Float as SSE event ID | web/server.py |
| X-2 | Unbounded search_content | externals.py |
| X-3 | Unbounded broadcast | externals.py |
| M-1 | Non-atomic metric updates | metrics.py |
| RC-2 | Full re-parse per change | reconciler.py |
| RC-3 | Subscription churn on changes | reconciler.py |
| GR-1 | Source text in lru_cache keys | grail.py |
| L-1 | Monkey-patched test backdoor | lsp/server.py |

### Low (Nice to Fix)
| ID | Issue | Module |
|----|-------|--------|
| C-2 | Dead tuple handling | config.py |
| D-2 | Unverified PRAGMA | db.py |
| E-3 | No event deserialization | events/types.py |
| ES-4 | Type mismatch on event IDs | events/store.py |
| W-1 | SHA-1 usage | workspace.py |
| WS-5 | Hardcoded version | web/server.py |
| WS-7 | Starlette deprecation | web/server.py |
| L-2 | Hardcoded port | lsp/server.py |
| L-3 | Unclosed standalone stores | lsp/server.py |
| R-2 | Hardcoded eviction timeout | runner.py |

**Total: 7 High, 15 Medium, 10 Low**
