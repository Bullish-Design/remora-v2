# Fix Implementation Guide

> Step-by-step implementation guide for all issues identified in CODE_REVIEW.md.
> Ordered by priority (P0 → P1 → P2 → Nice-to-Have).

---

## Table of Contents

1. **[P0: Rename Duplicate Test Module](#1-p0-rename-duplicate-test-module)**
2. **[P1: Fix SSE Event IDs for Reliable Resume](#2-p1-fix-sse-event-ids-for-reliable-resume)**
3. **[P1: Fix graph_get_node Return Contract](#3-p1-fix-graph_get_node-return-contract)**
4. **[P1: Bound the EventBus Stream Queue](#4-p1-bound-the-eventbus-stream-queue)**
5. **[P2: Fix Unbounded _file_locks Growth](#5-p2-fix-unbounded-_file_locks-growth)**
6. **[P2: Add Explicit aiosqlite Import to SubscriptionRegistry](#6-p2-add-explicit-aiosqlite-import-to-subscriptionregistry)**
7. **[P2: Make Kernel Retry Count Configurable](#7-p2-make-kernel-retry-count-configurable)**
8. **[P2: Use error_response Helper in Chat Routes](#8-p2-use-error_response-helper-in-chat-routes)**
9. **[P2: Filter Content Change Events to Discovery Paths](#9-p2-filter-content-change-events-to-discovery-paths)**
10. **[P2: Handle Task Exceptions in lifecycle.run()](#10-p2-handle-task-exceptions-in-lifecyclerun)**
11. **[Nice-to-Have: Mask API Key in Debug Logs](#11-nice-to-have-mask-api-key-in-debug-logs)**
12. **[Nice-to-Have: Optimize search_content Scanning](#12-nice-to-have-optimize-search_content-scanning)**
13. **[Nice-to-Have: Document CORS Behavior](#13-nice-to-have-document-cors-behavior)**

---

## 1. P0: Rename Duplicate Test Module

**Problem**: `tests/unit/test_virtual_reactive_flow.py` and `tests/integration/test_virtual_reactive_flow.py` share the same module basename. pytest's default import mode collides on `test_virtual_reactive_flow`, causing a collection error that blocks the full test suite.

**Root cause**: Both `tests/unit/` and `tests/integration/` lack the `__init__.py` files needed to disambiguate them as separate packages under pytest's default import mode.

### Steps

1. **Rename the unit test file**:
   ```
   mv tests/unit/test_virtual_reactive_flow.py \
      tests/unit/test_virtual_reactive_flow_unit.py
   ```

2. **Update any internal references** within the renamed file. Check for `class` names or module-level docstrings that reference the old filename:
   ```bash
   grep -n "test_virtual_reactive_flow" tests/unit/test_virtual_reactive_flow_unit.py
   ```

3. **Verify collection**:
   ```bash
   devenv shell -- pytest --collect-only 2>&1 | tail -5
   ```

4. **Run full suite**:
   ```bash
   devenv shell -- pytest
   ```
   Expect: 434+ passed, 0 collection errors.

### Files Changed
- `tests/unit/test_virtual_reactive_flow.py` → renamed to `tests/unit/test_virtual_reactive_flow_unit.py`

---

## 2. P1: Fix SSE Event IDs for Reliable Resume

**Problem**: Live SSE events use `event.timestamp` (a float like `1711234567.89`) as the `id:` field. On reconnect, the client sends `Last-Event-ID: 1711234567.89`. The `get_events_after` method calls `int(after_id)`, which raises `ValueError` on a float string, returning `[]` and silently dropping all events between disconnect and reconnect.

**Root cause**: The live stream path (`sse.py:95`) uses the event's timestamp, but the replay path uses the SQLite integer row ID. These must be the same ID space.

### Steps

1. **Modify `EventStore.append` to return the row ID** — it already does (`cursor.lastrowid`). No change needed here.

2. **Add `event_id` to the `Event` base class** so it can carry the DB row ID after persistence:

   Edit `src/remora/core/events/types.py`:
   ```python
   class Event(BaseModel):
       ...
       event_id: int | None = None  # Set after persistence by EventStore.append
   ```

3. **Set `event_id` on the event after INSERT in `EventStore.append`**:

   Edit `src/remora/core/events/store.py`, in `append()`, after `event_id = int(cursor.lastrowid)`:
   ```python
   event.event_id = event_id
   ```

4. **Use `event.event_id` as the SSE `id:` field in the live stream**:

   Edit `src/remora/web/sse.py:95`, change:
   ```python
   yield f"id: {event.timestamp}\nevent: {event.event_type}\ndata: {payload}\n\n"
   ```
   to:
   ```python
   sse_id = event.event_id if event.event_id is not None else event.timestamp
   yield f"id: {sse_id}\nevent: {event.event_type}\ndata: {payload}\n\n"
   ```

5. **Verify `get_events_after` handles integer IDs** — it already does: `int(after_id)` will work with `"42"`. Confirmed, no change needed.

6. **Add a regression test**:
   - Append an event to EventStore
   - Capture the returned event_id
   - Verify `event.event_id == returned_id`
   - Verify `get_events_after(str(returned_id - 1))` returns the event

### Files Changed
- `src/remora/core/events/types.py` — add `event_id` field to `Event`
- `src/remora/core/events/store.py` — set `event.event_id` after INSERT
- `src/remora/web/sse.py` — use `event.event_id` as SSE ID
- `tests/unit/test_sse_resume.py` (new) — regression test

---

## 3. P1: Fix graph_get_node Return Contract

**Problem**: `GraphCapabilities.graph_get_node()` returns `{}` (empty dict) when the node is not found. The tool scripts declare `-> dict | None` via `@external`. While `if not node:` works on `{}` (falsy), the contract mismatch is confusing and will break scripts that check `if node is None:`.

### Steps

1. **Change the return value** in `src/remora/core/tools/capabilities.py:124`:

   Change:
   ```python
   async def graph_get_node(self, target_id: str) -> dict[str, Any]:
       node = await self._node_store.get_node(target_id)
       return node.model_dump() if node is not None else {}
   ```
   To:
   ```python
   async def graph_get_node(self, target_id: str) -> dict[str, Any] | None:
       node = await self._node_store.get_node(target_id)
       return node.model_dump() if node is not None else None
   ```

2. **Audit all `.pym` scripts** that call `graph_get_node` and verify they handle `None`:
   ```bash
   grep -rn "graph_get_node" src/remora/defaults/bundles/
   ```
   Known usage: `review_diff.pym` uses `if not node:` which works for both `None` and `{}`. No change needed there, but document that `None` is the contract.

3. **Update existing tests** that assert `graph_get_node` returns `{}`:
   ```bash
   grep -rn "graph_get_node" tests/
   ```
   Change assertions from `== {}` to `is None`.

### Files Changed
- `src/remora/core/tools/capabilities.py` — return `None` instead of `{}`
- Tests referencing `graph_get_node` — update assertions

---

## 4. P1: Bound the EventBus Stream Queue

**Problem**: `EventBus.stream()` creates an unbounded `asyncio.Queue()`. A slow SSE consumer that doesn't drain fast enough will cause unbounded memory growth.

### Steps

1. **Add `maxsize` parameter to the queue** in `src/remora/core/events/bus.py`:

   Change:
   ```python
   @asynccontextmanager
   async def stream(self, *event_types: str) -> AsyncIterator[AsyncIterator[Event]]:
       """Yield an async iterator of events for optional filtered types."""
       queue: asyncio.Queue[Event] = asyncio.Queue()
   ```
   To:
   ```python
   @asynccontextmanager
   async def stream(
       self, *event_types: str, max_buffer: int = 1000
   ) -> AsyncIterator[AsyncIterator[Event]]:
       """Yield an async iterator of events for optional filtered types."""
       queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=max_buffer)
   ```

2. **Handle queue-full in the enqueue handler** with a drop-newest policy:

   Change:
   ```python
   def enqueue(event: Event) -> None:
       if filter_set is None or event.event_type in filter_set:
           queue.put_nowait(event)
   ```
   To:
   ```python
   def enqueue(event: Event) -> None:
       if filter_set is None or event.event_type in filter_set:
           try:
               queue.put_nowait(event)
           except asyncio.QueueFull:
               logger.warning("SSE stream buffer full, dropping event %s", event.event_type)
   ```

3. **Add a test** that verifies events are dropped when the queue is full rather than raising.

### Files Changed
- `src/remora/core/events/bus.py` — bound the queue, catch `QueueFull`
- `tests/unit/test_event_bus_stream_overflow.py` (new) — overflow test

---

## 5. P2: Fix Unbounded _file_locks Growth

**Problem**: `FileReconciler._file_locks` and `_file_lock_generations` grow unbounded. Locks for files only touched once persist until the next reconcile cycle advances the generation past them. Between cycles, no eviction occurs.

### Steps

1. **Add a max lock count with LRU eviction** in `src/remora/code/reconciler.py`:

   Add a constant near the top of the class:
   ```python
   _MAX_FILE_LOCKS = 500
   ```

2. **Extend `_evict_stale_file_locks`** to also evict oldest locks when the count exceeds the limit:

   After the existing stale eviction logic, add:
   ```python
   if len(self._file_locks) > self._MAX_FILE_LOCKS:
       sorted_paths = sorted(
           self._file_lock_generations.items(),
           key=lambda item: item[1],
       )
       evict_count = len(self._file_locks) - self._MAX_FILE_LOCKS
       for file_path, _ in sorted_paths[:evict_count]:
           if file_path in self._file_locks and not self._file_locks[file_path].locked():
               self._file_locks.pop(file_path, None)
               self._file_lock_generations.pop(file_path, None)
   ```

### Files Changed
- `src/remora/code/reconciler.py` — add max lock count and LRU eviction

---

## 6. P2: Add Explicit aiosqlite Import to SubscriptionRegistry

**Problem**: `SubscriptionRegistry` uses `aiosqlite.Connection` as a type hint but relies on it being imported transitively at runtime. This is fragile.

### Steps

1. **Add the import** in `src/remora/core/events/subscriptions.py`:

   The file currently has no `aiosqlite` import. Add at the top with other imports:
   ```python
   import aiosqlite
   ```

   Also add the missing `TransactionContext` import (it's used in `__init__` but not imported):
   ```python
   from remora.core.storage.transaction import TransactionContext
   ```

   Or, if these should only be type-time imports, use:
   ```python
   from __future__ import annotations
   ```
   (already present) and add under `TYPE_CHECKING`:
   ```python
   from typing import TYPE_CHECKING
   if TYPE_CHECKING:
       import aiosqlite
       from remora.core.storage.transaction import TransactionContext
   ```

2. **Verify** the module imports cleanly:
   ```bash
   devenv shell -- python -c "from remora.core.events.subscriptions import SubscriptionRegistry"
   ```

### Files Changed
- `src/remora/core/events/subscriptions.py` — add explicit imports

---

## 7. P2: Make Kernel Retry Count Configurable

**Problem**: `AgentTurnExecutor._run_kernel` has `max_retries = 1` hardcoded. This should be configurable for different deployment environments.

### Steps

1. **Add `max_model_retries` to `RuntimeConfig`** in `src/remora/core/model/config.py`:

   In the `RuntimeConfig` class, add:
   ```python
   max_model_retries: int = Field(default=1, ge=0, le=5)
   ```

2. **Pass it through to `AgentTurnExecutor`** in `src/remora/core/agents/turn.py`:

   Add to `__init__`:
   ```python
   max_model_retries: int = 1,
   ```
   Store as `self._max_model_retries`.

3. **Use it in `_run_kernel`**:

   Change:
   ```python
   max_retries = 1
   ```
   To:
   ```python
   max_retries = self._max_model_retries
   ```

4. **Pass the config value** from wherever `AgentTurnExecutor` is constructed (in `ActorPool` or `runner.py`):
   ```python
   max_model_retries=config.runtime.max_model_retries,
   ```

### Files Changed
- `src/remora/core/model/config.py` — add `max_model_retries` to `RuntimeConfig`
- `src/remora/core/agents/turn.py` — accept and use `max_model_retries`
- `src/remora/core/agents/runner.py` — pass config value through

---

## 8. P2: Use error_response Helper in Chat Routes

**Problem**: `api_chat` and `api_respond` in `chat.py` return raw `JSONResponse({"error": "..."})` instead of using the `error_response()` helper, producing inconsistent error shapes (missing `message` field).

### Steps

1. **Add the import** in `src/remora/web/routes/chat.py`:
   ```python
   from remora.web.routes._errors import error_response
   ```

2. **Replace each raw error response**. There are 6 error returns in the file:

   **`api_chat` — rate limit (line 17-19)**:
   ```python
   return error_response(
       error="rate_limit_exceeded",
       message="Rate limit exceeded. Try again later.",
       status_code=429,
   )
   ```

   **`api_chat` — missing fields (line 25)**:
   ```python
   return error_response(
       error="invalid_request",
       message="node_id and message are required",
       status_code=400,
   )
   ```

   **`api_chat` — message too long (lines 27-35)**:
   ```python
   return error_response(
       error="message_too_long",
       message="message exceeds max length",
       status_code=413,
       extras={"max_chars": max_chars, "received_chars": len(message)},
   )
   ```

   **`api_chat` — node not found (line 39)**:
   ```python
   return error_response(
       error="not_found",
       message="node not found",
       status_code=404,
   )
   ```

   **`api_respond` — missing fields (line 53)**:
   ```python
   return error_response(
       error="invalid_request",
       message="request_id and response required",
       status_code=400,
   )
   ```

   **`api_respond` — no pending request (line 58)**:
   ```python
   return error_response(
       error="not_found",
       message="no pending request",
       status_code=404,
   )
   ```

3. **Run chat route tests** to verify no regressions:
   ```bash
   devenv shell -- pytest tests/ -k "chat" -v
   ```

### Files Changed
- `src/remora/web/routes/chat.py` — use `error_response()` for all error returns

---

## 9. P2: Filter Content Change Events to Discovery Paths

**Problem**: `FileReconciler._on_content_changed` triggers reconciliation for any `ContentChangedEvent`, even if the file is outside configured `discovery_paths`. This wastes CPU on no-op reconciliations.

### Steps

1. **Add a path check** at the top of `_on_content_changed` in `src/remora/code/reconciler.py`:

   After `file_path = event.path`, add:
   ```python
   # Skip files outside configured discovery paths
   resolved = Path(file_path).resolve()
   discovery_roots = [Path(p).resolve() for p in self._config.project.discovery_paths]
   if not any(
       resolved == root or root in resolved.parents
       for root in discovery_roots
   ):
       return
   ```

   Note: The discovery paths are relative to `project_root`, so resolve them:
   ```python
   discovery_roots = [
       (self._project_root / p).resolve()
       for p in self._config.project.discovery_paths
   ]
   ```

2. **Add a test** that emits a `ContentChangedEvent` for a file outside discovery paths and verifies no reconciliation occurs.

### Files Changed
- `src/remora/code/reconciler.py` — add discovery path filter to `_on_content_changed`

---

## 10. P2: Handle Task Exceptions in lifecycle.run()

**Problem**: `RemoraLifecycle.run()` with `run_seconds=0` uses `asyncio.gather(*self._tasks)` which re-raises the first exception, leaving other tasks running without cleanup.

### Steps

1. **Use `return_exceptions=True`** in `src/remora/core/services/lifecycle.py`:

   Change:
   ```python
   if run_seconds > 0:
       await asyncio.sleep(run_seconds)
   else:
       await asyncio.gather(*self._tasks)
   ```
   To:
   ```python
   if run_seconds > 0:
       await asyncio.sleep(run_seconds)
   else:
       results = await asyncio.gather(*self._tasks, return_exceptions=True)
       for i, result in enumerate(results):
           if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
               logger.error(
                   "Runtime task %s exited with exception: %s",
                   self._tasks[i].get_name(),
                   result,
               )
   ```

### Files Changed
- `src/remora/core/services/lifecycle.py` — use `return_exceptions=True` and log failures

---

## 11. Nice-to-Have: Mask API Key in Debug Logs

**Problem**: `AgentTurnExecutor._run_kernel` logs the full model request including `base_url` at debug level. While the API key itself is not directly logged in this message, the `create_kernel` call uses `api_key or "EMPTY"`, and debug-level structured logging could expose it.

### Steps

1. **Add a masking helper** in `src/remora/core/utils.py`:
   ```python
   def mask_secret(value: str | None, visible_chars: int = 4) -> str:
       if not value:
           return "EMPTY"
       if len(value) <= visible_chars:
           return "****"
       return value[:visible_chars] + "****"
   ```

2. **Use it in kernel creation debug log** in `turn.py` — ensure no log line includes the raw key. The current code at line 292-304 doesn't log the key directly, so this is primarily a defensive measure for future changes.

### Files Changed
- `src/remora/core/utils.py` — add `mask_secret` utility
- `src/remora/core/agents/turn.py` — use `mask_secret` if API key logging is added

---

## 12. Nice-to-Have: Optimize search_content Scanning

**Problem**: `FileCapabilities.search_content` reads every file in the workspace sequentially. For large workspaces, this is slow even though `_search_content_max_matches` bounds the output.

### Steps

1. **Add early path filtering** before reading files in `src/remora/core/tools/capabilities.py`:

   The existing code already filters by `path` prefix. The main optimization is to skip binary-looking files and limit file size:

   ```python
   _TEXT_EXTENSIONS = {".py", ".md", ".toml", ".yaml", ".yml", ".json", ".txt", ".pym"}

   async def search_content(self, pattern: str, path: str = ".") -> list[dict[str, Any]]:
       matches: list[dict[str, Any]] = []
       paths = await self._workspace.list_all_paths()
       for file_path in paths:
           normalized = file_path.strip("/")
           if path not in {".", "/", ""} and not normalized.startswith(path.strip("/")):
               continue
           # Skip likely binary files
           ext = Path(normalized).suffix.lower()
           if ext and ext not in _TEXT_EXTENSIONS:
               continue
           ...
   ```

2. This is a minor optimization. The real fix would be a workspace-level content search index, which is a larger effort.

### Files Changed
- `src/remora/core/tools/capabilities.py` — add extension filter for text files

---

## 13. Nice-to-Have: Document CORS Behavior

**Problem**: No CORS headers are set in the middleware, meaning cross-origin browser JavaScript cannot POST to the API. This is intentional for local-first but undocumented.

### Steps

1. **Add a comment** in `src/remora/web/middleware.py` after the CSRF class:
   ```python
   # Note: No CORS headers are set. Cross-origin browser requests (POST/PUT/DELETE)
   # will fail due to CORS preflight. This is intentional — Remora is designed for
   # localhost access only. If cross-origin access is needed, add CORSMiddleware
   # from starlette.middleware.cors.
   ```

2. **Mention in architecture docs** (`docs/architecture.md`) under the web layer section.

### Files Changed
- `src/remora/web/middleware.py` — add explanatory comment

---

## Implementation Order

The recommended implementation order groups related changes and minimizes risk:

1. **Fix #1** (P0: rename test file) — unblocks full test suite, zero risk
2. **Fix #3** (P1: graph_get_node contract) — simple one-line change + test updates
3. **Fix #2** (P1: SSE event IDs) — requires touching 3 files but well-scoped
4. **Fix #4** (P1: bound stream queue) — isolated to bus.py
5. **Fix #8** (P2: chat error responses) — pure refactor, no behavior change
6. **Fix #6** (P2: add imports) — trivial
7. **Fix #5** (P2: file locks) — low risk, reconciler-scoped
8. **Fix #9** (P2: filter content events) — reconciler-scoped
9. **Fix #7** (P2: configurable retries) — touches config model
10. **Fix #10** (P2: lifecycle gather) — touches lifecycle
11. **Fixes #11-13** (Nice-to-have) — independent, do whenever

---

_End of fix implementation guide._
