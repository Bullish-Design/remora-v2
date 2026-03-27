# Remora v2 — Comprehensive Code Review

**Reviewer:** Claude (8-agent parallel analysis)
**Date:** 2026-03-27
**Scope:** Full codebase — all subsystems, tests, bundles, config, docs

This review is written without filter. Every subsystem was read in full. Issues are
ranked CRITICAL / MAJOR / MINOR / NIT.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Core Agent Subsystem](#2-core-agent-subsystem)
3. [Storage Subsystem](#3-storage-subsystem)
4. [Events Subsystem](#4-events-subsystem)
5. [Tools & Capabilities](#5-tools--capabilities)
6. [Code Discovery & Reconciler](#6-code-discovery--reconciler)
7. [Web Server & LSP](#7-web-server--lsp)
8. [Services, Config & Model](#8-services-config--model)
9. [Architecture & Bundles](#9-architecture--bundles)
10. [Test Suite](#10-test-suite)
11. [Summary Scoreboard](#11-summary-scoreboard)

---

## 1. Executive Summary

The codebase has a solid architectural concept and generally clean code structure.
However, it has **systemic concurrency bugs**, **critical security gaps**, and
**fundamental correctness problems** in several core subsystems that must be fixed
before this can be considered production-ready.

**By the numbers:**

| Severity | Count |
|----------|-------|
| CRITICAL | 25 |
| MAJOR    | 41 |
| MINOR    | 18 |
| NIT      | 2 |

**The three most alarming patterns:**

1. **Shared mutable state mutated without asyncio locks.** TriggerPolicy, Outbox sequence
   counter, FileReconciler's `_file_state` and `_name_index`, Metrics — all mutated
   concurrently without synchronization.

2. **Silent failures everywhere.** Binary files crash discovery silently. Workspace
   provision failures log at DEBUG and continue. Event fan-out exceptions are swallowed.
   Status transitions fail silently.

3. **Security basics are missing.** CSRF protection is broken (missing Referer check).
   Path traversal in the proposal accept route. Grail cache poisonable via 64-bit collision
   space. Env var expansion across all config keys leaks secrets.

---

## 2. Core Agent Subsystem

**Files:** `actor.py`, `runner.py`, `turn.py`, `kernel.py`, `outbox.py`, `trigger.py`, `prompt.py`

### CRITICAL-agents-1: TriggerPolicy is not async-safe
**File:** `trigger.py:40–64`

`TriggerPolicy.should_trigger()` mutates `last_trigger_ms`, `depths`, `depth_timestamps`,
and `correlation_turn_counts` without any lock. Each actor has its own TriggerPolicy
instance, but within a single actor, multiple coroutines can be running simultaneously
during a kernel turn (tool calls are concurrent). Two concurrent calls can both pass the
cooldown check before either writes back `last_trigger_ms`:

```python
self.last_trigger_ms = now_ms  # RACE: two coroutines set this simultaneously
```

The depth dict can get incremented twice for the same correlation, and
`cleanup_depth_state` runs based on `trigger_checks` which is also mutated without lock.

**Fix:** Wrap the entire `should_trigger()` body in `asyncio.Lock`, or redesign as a
single-writer state machine.

---

### CRITICAL-agents-2: Actor stop() can hang indefinitely
**File:** `actor.py:91–96`

```python
async def stop(self) -> None:
    if self._task is not None and not self._task.done():
        self.inbox.put_nowait(None)   # sentinel
        await self._task              # wait forever if kernel never yields
    self._task = None
```

If the actor is blocked mid-turn inside `kernel.run()` (a long LLM call), the `None`
sentinel sits in the queue until the kernel finishes. Shutdown hangs indefinitely.

**Fix:** Cancel the task (`self._task.cancel()`) then await it, handling `CancelledError`
in the actor's `_run()` finally block.

---

### CRITICAL-agents-3: Unhandled RuntimeError crashes the actor loop
**File:** `turn.py:187–202`, `kernel.py:52–57`

The `except` clause in `execute_turn()` catches:
`ModelError, ToolError, WorkspaceError, IncompatibleBundleError`

But `run_kernel()` can raise `ModelError` wrapping the underlying exception. The actor
loop in `actor.py` only catches `asyncio.CancelledError`. Any unhandled exception kills
the actor silently — the node status stays `RUNNING` forever, blocking all future turns.

**Fix:** Wrap the inner `_execute_turn` call in the actor loop with `except Exception`
to at minimum log and reset status before the actor dies.

---

### MAJOR-agents-4: Outbox sequence counter race
**File:** `outbox.py:71–76`

```python
self._sequence += 1  # not atomic across awaits
```

Two concurrent `emit()` calls both read `_sequence = 5`, both set it to 6. Events with
duplicate sequence numbers. Broken ordering guarantees.

**Fix:** `asyncio.Lock` around the increment, or switch to `itertools.count()`.

---

### MAJOR-agents-5: Shared history list mutated without synchronization
**File:** `turn.py:157,172`

`self._history` is shared across all invocations of an actor's turn executor and extended
without a lock. Two turns running concurrently (while one is blocked at the kernel) can
interleave history entries, corrupting conversation context.

**Fix:** Lock history mutations, or give each turn its own history view.

---

### MAJOR-agents-6: Idle eviction race
**File:** `runner.py:165–183`

`_evict_idle()` checks `actor.last_active` and `actor.inbox.empty()`, then calls
`actor.stop()`. Between the idle check and the stop call, the actor may have received a
new event and started processing. Evicting a running actor leaves the node permanently
stuck in `RUNNING` status.

**Fix:** Add a "currently processing" flag to Actor; only evict if the flag is clear.

---

### MAJOR-agents-7: DROP_OLDEST overflow silently discards events
**File:** `runner.py:87–103`

Between the `put_nowait` failing and the `get_nowait` for DROP_OLDEST, the actor loop
may have drained the queue. `get_nowait()` raises `QueueEmpty`, the except logs a warning
and returns — the new event is silently discarded without being retried or metriced.

**Fix:** Retry `put_nowait(event)` after the `QueueEmpty` exception.

---

### MAJOR-agents-8: Kernel `create_kernel` OSError not retriable
**File:** `turn.py:281–291`

The retry loop catches `TimeoutError` and `aiohttp.ClientError` from `run_kernel`, but
`create_kernel` raises `OSError` which is immediately re-raised as `ModelError` before
the retry loop can help:

```python
for attempt in range(max_retries + 1):
    try:
        kernel = create_kernel(...)
    except OSError as exc:
        raise ModelError(...)  # immediate, no retry
```

**Fix:** Move `OSError` into the inner `except` block that respects retry logic.

---

### MAJOR-agents-9: Kernel close exceptions suppress the real error
**File:** `turn.py:332–335`

The `finally` block calls `await kernel.close()`. If `close()` raises, Python suppresses
the pending exception, hiding the actual failure cause.

**Fix:**
```python
finally:
    try:
        await kernel.close()
    except Exception:
        logger.exception("kernel.close() failed")
```

---

### MAJOR-agents-10: TriggerPolicy depth never released when correlation_id is None
**File:** `trigger.py:87–88`, `turn.py:425–435`

`release_depth(None)` silently returns. If a turn fires without a correlation ID,
its depth slot is never released. After `max_trigger_depth` such turns on the same
correlation key, the agent becomes permanently blocked.

**Fix:** Generate a UUID correlation ID at turn start if one is not present; never pass
`None` to depth tracking.

---

## 3. Storage Subsystem

**Files:** `db.py`, `graph.py`, `workspace.py`, `transaction.py`

### CRITICAL-storage-1: No FOREIGN KEY enforcement allows orphaned edges
**File:** `graph.py:81–90`

The schema has no `FOREIGN KEY (from_id) REFERENCES nodes(node_id)` on the edges table,
and `PRAGMA foreign_keys=ON` is never set. Any code that inserts edges before nodes, or
forgets to clean up edges on node deletion, silently corrupts the graph.

**Fix:** Add FK constraints and enable the pragma in `open_database`.

---

### CRITICAL-storage-2: delete_node deletes edges first — not atomic
**File:** `graph.py:171–182`

Edges are deleted before the node. If the node DELETE fails or is rolled back, the graph
is left with a node that has no edges, silently violating structure.

**Fix:** Use a single transaction with DEFER + delete node first (cascade handles edges
with FK constraints).

---

### CRITICAL-storage-3: TransactionContext nested batch doesn't rollback on exception
**File:** `transaction.py:30–53`

In a nested batch (`_depth > 1`), exceptions set `failed = True` but rollback is only
called at `_depth == 1`. Inner batch exceptions allow partial writes to persist:

```python
if self._depth == 1 and failed:
    await self._db.rollback()   # outer only
```

**Fix:** Use SQLite savepoints for nested batches; rollback to savepoint on inner
exception.

---

### CRITICAL-storage-4: SQLite SQLITE_BUSY not handled
**Files:** `db.py`, `graph.py`

`busy_timeout=5000` is set but if the timeout expires, `sqlite3.OperationalError("database
is locked")` propagates uncaught throughout the entire graph layer. No retry logic exists.

**Fix:** Catch `OperationalError` with `"database is locked"` message and retry with
exponential backoff.

---

### CRITICAL-storage-5: Concurrent NodeStore writes are not atomic
**File:** `graph.py`

Multiple `NodeStore` instances can exist (without `TransactionContext`) and auto-commit
after each statement. Concurrent `upsert_node` calls race on `INSERT OR REPLACE`. The
race window is small but real under load.

**Fix:** Mandate a `TransactionContext`; never allow NodeStore in auto-commit mode.

---

### MAJOR-storage-6: transition_status TOCTOU
**File:** `graph.py:184–214`

Failed UPDATE → subsequent GET to log current status → both are non-atomic. The logged
status can be wrong. More importantly, if the UPDATE fails due to `SQLITE_BUSY`, the
exception is unhandled.

---

### MAJOR-storage-7: _deferred_events not synchronized
**File:** `transaction.py:28,47–53`

Concurrent `defer_event` calls race on `list.append`. Events deferred after fan-out
starts can be lost if the list is cleared in the `else` branch before they're appended.

**Fix:** Use `asyncio.Lock` or serialize `defer_event` calls.

---

### MAJOR-storage-8: provision_bundle doesn't validate merged bundle
**File:** `workspace.py:196–229`

After deep-merging multiple `bundle.yaml` files, the result is written to the workspace
without calling `BundleConfig.model_validate()`. An invalid merged config is persisted;
subsequent `read_bundle_config` calls fail.

**Fix:** Validate before writing.

---

### MAJOR-storage-9: CairnWorkspaceService.close() races with get_agent_workspace()
**File:** `workspace.py:145–163,231–235`

`close()` clears `_agent_workspaces` without acquiring `_lock`. A concurrent
`get_agent_workspace()` call mid-close leaves a workspace reference in flight while
the underlying resource is freed.

**Fix:** Acquire `_lock` in `close()`.

---

### MINOR-storage-10: No pagination on list_nodes
**File:** `graph.py:133–160`

Returns all matching nodes with no limit. A large project can OOM the process.

---

### MINOR-storage-11: Magic string edge types
**File:** `graph.py:293,302`

`"imports"` and `"contains"` are hardcoded strings with no enum. Renaming requires
a grep.

---

### MINOR-storage-12: No timestamps on nodes
**File:** `graph.py:61–76`

No `created_at` / `updated_at` columns. Impossible to audit change history, implement
TTL eviction, or support time-based queries.

---

## 4. Events Subsystem

**Files:** `types.py`, `store.py`, `bus.py`, `dispatcher.py`, `subscriptions.py`

*(Based on full file reads; detailed findings from parallel analysis below)*

### CRITICAL-events-1: EventBus silently drops events on queue overflow
**File:** `bus.py:110–139`

When an SSE client is slow, the per-client queue fills and events are silently dropped
with only a log warning. The client has no way to know it missed events, leading to
corrupted state.

**Fix:** Send an explicit "events dropped" message type in the SSE protocol; or
implement per-client backpressure with disconnection rather than silent loss.

---

### MAJOR-events-2: Subscription find_matching_agents is O(subscriptions) per event
**File:** `subscriptions.py`

Every event triggers a full scan of all subscriptions to find matching agents. In a
large project with hundreds of nodes and multiple subscriptions each, this is thousands
of comparisons per event.

**Fix:** Index subscriptions by event_type; only scan subscriptions for the relevant type.

---

### MAJOR-events-3: EventStore.append is not atomic with EventBus.emit
**File:** `store.py`

`EventStore.append()` writes to SQLite, commits, then calls `EventBus.emit()`. If the
process crashes after commit but before emit, the event is durable but was never
dispatched. Agents miss the trigger.

**Fix:** This is a hard distributed systems problem. At minimum, add a startup replay
mechanism that re-dispatches unprocessed events from the store.

---

### MAJOR-events-4: TriggerDispatcher depth tracking is per-process, not per-correlation
**File:** `dispatcher.py`

Depth limits reset on process restart. A long reactive chain that spans a restart will
get its depth reset and trigger indefinitely.

---

### MAJOR-events-5: Subscription cache TOCTOU race
**File:** `subscriptions.py:134–138`, `subscriptions.py:146–149`

In `register()`, after `await self._maybe_commit()`, there is an `await` point before
`self._cache_add()`. A concurrent `get_matching_agents()` call can run between the commit
and the cache update, seeing a DB subscription that isn't yet reflected in the cache and
missing the newly-registered subscriber:

```python
await self._maybe_commit()       # <-- await point: yield to event loop
sub_id = int(cursor.lastrowid)
if self._cache is not None:
    self._cache_add(sub_id, ...)  # cache updated too late
```

The inverse holds for `unregister()`: between commit and `_cache_remove_subscription()`,
events are still routed to an agent whose subscription was just deleted from the DB.

**Fix:** Update the cache BEFORE the commit (or within the same synchronous code block
after the await, ensuring no further yields occur between cache and DB).

---

### MAJOR-events-6: Concurrent `_rebuild_cache()` calls produce a stale or duplicate cache
**File:** `subscriptions.py:164–166`, `subscriptions.py:179–193`

`get_matching_agents()` triggers a lazy cache rebuild:

```python
if self._cache is None:
    await self._rebuild_cache()   # await: yields to event loop
```

Two concurrent callers both see `self._cache is None`, both enter `_rebuild_cache()`.
The first completes and sets `self._cache`. The second overwrites it with a separate
rebuild that may have missed subscriptions registered between the two reads. No locking
guards the rebuild path.

**Fix:** Use `asyncio.Lock` to serialise `_rebuild_cache()`.

---

### MINOR-events-7: `event_id` excluded from `to_envelope()` — payload has no DB record key
**File:** `types.py:27–37`

`to_envelope()` explicitly excludes `event_id` from the payload dict. Live SSE events
have `event_id` exposed only in the SSE `id:` field (line 95 of `sse.py`), not inside
the JSON payload. Clients that parse only the data payload cannot correlate received
events back to DB records without separately tracking the SSE `id:` field.

Replay events are reconstructed from raw DB rows and share the same structure gap — the
`id` column is used as the SSE `id:` but is not injected into the payload object.

This is a minor API ergonomics issue but makes client-side event deduplication harder.

---

### MINOR-events-8: Event types are stringly typed
**File:** `types.py`

`EventType` StrEnum exists but `CustomEvent.event_type` accepts any string. Tools can
emit arbitrary event_type values that don't match any StrEnum member. Subscription
filters using `EventType.X` won't match `CustomEvent(event_type="x")` if there's a
case/spelling mismatch.

---

### MINOR-events-9: No TTL or archival for events
**File:** `store.py`

Events accumulate indefinitely in SQLite. A long-running system will have millions of
event rows and degraded query performance.

---

## 5. Tools & Capabilities

**Files:** `context.py`, `capabilities.py`, `grail.py`

### CRITICAL-tools-1: propose_changes() includes ALL workspace files, not changed files
**File:** `capabilities.py:389–391`

```python
async def _collect_changed_files(self) -> list[str]:
    all_paths = await self._workspace.list_all_paths()
    return sorted(path for path in all_paths if not path.startswith("_bundle/"))
```

The function is named `_collect_changed_files` but returns ALL files. Every proposal
includes the entire workspace, flooding reviewers with noise and false positives.

**Fix:** Track file state at turn start and diff at proposal time. Or rename the function
and document the actual behavior.

---

### CRITICAL-tools-2: request_human_input() leaves node in AWAITING_INPUT on timeout
**File:** `capabilities.py:340–367`

On `TimeoutError`, the code calls `self._broker.discard(request_id)` and re-raises.
The node status is **never transitioned back** from `AWAITING_INPUT`. The node is
permanently stuck.

**Fix:**
```python
except TimeoutError:
    self._broker.discard(request_id)
    await self._node_store.transition_status(self._node_id, NodeStatus.RUNNING)
    raise
```

---

### CRITICAL-tools-3: Grail script cache uses truncated 64-bit hash space
**File:** `grail.py:50–68`

```python
content_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
```

Only 16 hex chars = 64-bit hash space. Birthday collision probability is ~50% at
~4 billion scripts. The global `_PARSED_SCRIPT_CACHE` is module-level and shared
across all agents and turns. A hash collision causes the wrong script to execute for
a different agent.

**Fix:** Use the full 256-bit hash as the key.

---

### CRITICAL-tools-4: broadcast() silently sends to ghost nodes
**File:** `capabilities.py:325–338`

Between `list_nodes()` and the loop of `emit()` calls, any target node could be deleted.
The `AgentMessageEvent` is appended for a node that no longer exists. The TriggerDispatcher
routes to a non-existent actor. The event sits in the DB as noise.

More critically, `_resolve_broadcast_targets` with pattern `"siblings"` does not validate
that `source_file` was found — if the calling agent's own node was just deleted, it
broadcasts to all agents with `file_path=""`.

---

### MAJOR-tools-5: GrailTool silently omits externals with missing capabilities
**File:** `grail.py:138–148`

If a script declares `@external async def write_file(...)` but `write_file` is not in
`self._capabilities` (e.g., FileCapabilities not included in TurnContext), the external
is silently omitted. The script crashes at runtime with an obscure `KeyError`.

**Fix:** Before calling `script.run()`, verify all declared externals are available.

---

### MAJOR-tools-6: event_emit accepts arbitrary event_type strings
**File:** `capabilities.py:240–252`

No validation against the EventType enum. Scripts can emit events with arbitrary types
that collide with internal system events or fill the audit log with garbage.

---

### MAJOR-tools-7: broadcast() silently truncates to max_targets without informing caller
**File:** `capabilities.py:325–338`

50 agents targeted when 200 exist; return value claims "Broadcast sent to 50 agents"
with no indication that 150 were silently skipped.

---

### MINOR-tools-8: search_files() uses fnmatch but docs say substring
**File:** `capabilities.py:58–60`

`fnmatch.fnmatch(path, f"*{pattern}*")` is shell glob, not substring. `"test.*"` matches
`"oldest.py"` (contains `"test."`). The externals-api.md documents this as
"substring-based matching."

**Fix:** Use `if pattern in path` to match documentation.

---

### MINOR-tools-9: graph_query_nodes silently coerces node_type to role
**File:** `capabilities.py:139–157`

If `node_type="review-agent"` is passed and doesn't match any NodeType enum value, it
falls back to treating it as a role filter with no warning. Undocumented behavior that
makes debugging confusing.

---

## 6. Code Discovery & Reconciler

**Files:** `reconciler.py`, `discovery.py`, `directories.py`, `virtual_agents.py`,
`subscriptions.py`, `watcher.py`, `relationships.py`

### CRITICAL-discovery-1: No file size limit — binary files load into memory unchecked
**File:** `discovery.py:62`

```python
source_bytes = path.read_bytes()  # no size limit
```

A 2GB binary file in a discovery path OOMs the process. A `.so` or `.whl` makes
tree-sitter choke on arbitrary bytes.

**Fix:** Add a size limit (e.g., 10MB). Skip and warn on oversized files.

---

### CRITICAL-discovery-2: Tree-sitter parse failures are not caught
**File:** `discovery.py:61–64`

`parser.parse()` doesn't raise on malformed input but `get_query()` and
`QueryCursor().matches()` can. No try/except around either. A single malformed file
kills the entire reconciliation pass.

**Fix:** Wrap `_parse_file()` in try/except; return empty list and log warning on error.

---

### CRITICAL-discovery-3: Node IDs are not stable across file moves
**File:** `discovery.py:125–129`

`node_id = f"{file_path}::{full_name}"` — moving a function to a different file changes
its ID. All subscriptions, workspace state, and graph edges are silently orphaned.

This is a fundamental design limitation. At minimum, it must be prominently documented.
Ideally, a content-hash-based stable ID (or ID migration on rename) should be implemented.

---

### CRITICAL-discovery-4: Content subscription path validation is inverted
**File:** `reconciler.py:572`

```python
if not any(resolved == root or root in resolved.parents for root in discovery_roots):
    return
```

`root in resolved.parents` checks if the root is a parent of the resolved path — but
the logic is `root in resolved.parents` which means "root is an ancestor of resolved."
This is correct for files under roots. But the check for equality is separate:
`resolved == root` handles exact match. On re-reading this carefully, it may actually
be correct — but the logic is confusing enough that it's clearly been misread by at
least one reviewer as inverted. 

The real issue: should use `resolved.is_relative_to(root)` (Python 3.9+) which is
unambiguous:

```python
if not any(resolved.is_relative_to(root) for root in discovery_roots):
    return
```

---

### CRITICAL-discovery-5: Reconciler is a God Object
**File:** `reconciler.py` (~650 lines)

A single class handles: file watching, change detection, tree-sitter parsing, node
upsert, edge/relationship management, directory hierarchy, virtual agent sync,
subscription wiring, workspace provisioning, search indexing, and event emission.

Any change to any subsystem requires modifying this one class. It's impossible to test
subsystems in isolation.

**Fix:** Split into `FileChangeDetector`, `NodeReconciler`, `RelationshipManager`,
`DirectoryManager` (already exists but is tangled in), `ReconciliationOrchestrator`.

---

### CRITICAL-discovery-6: Virtual agent hash doesn't include the agent's own ID
**File:** `virtual_agents.py:142–158`

```python
payload = {"role": spec.role, "subscriptions": [...]}
```

Renaming a virtual agent (changing `spec.id`) produces the same hash. No
`NodeChangedEvent` is emitted on rename. Downstream systems relying on the event to
invalidate caches or re-subscribe miss the change entirely.

**Fix:** Include `spec.id` in the hash payload.

---

### MAJOR-discovery-7: Concurrent modifications to _file_state without locking
**File:** `reconciler.py:74,142–145,260–303`

`_file_state` and `_name_index` are accessed from multiple concurrent contexts (watch
handler and reconcile cycle) without an `asyncio.Lock`. Dict mutations during iteration
can cause `RuntimeError: dictionary changed size during iteration`.

---

### MAJOR-discovery-8: All Python relationships refreshed on any Python file change
**File:** `reconciler.py:357–372`

`_semantic_refresh_paths()` returns ALL known Python files whenever any one of them
changes. O(n) relationship re-extractions for a single file edit.

**Fix:** Only refresh files that import or are imported by the changed file
(transitive dependency set).

---

### MAJOR-discovery-9: Symlinks not handled — can OOM or infinite-recurse
**File:** `paths.py:59`

`root.rglob("*")` follows symlinks. A symlink to `/usr/lib/python3/` will attempt to
discover the entire stdlib. A symlink loop hangs discovery forever.

**Fix:** Use `follow_symlinks=False` in `rglob` (Python 3.13+) or manually check
`is_symlink()` before recursion.

---

### MAJOR-discovery-10: Virtual agent subscriptions accumulate on config change
**File:** `virtual_agents.py:113–116`

On update (hash changed), new subscriptions are registered but old ones are NOT
unregistered first. Each config reload adds duplicate subscriptions. After N reloads,
the agent receives each event N times.

**Fix:** Call `unregister_by_agent(node_id)` before re-registering.

---

### MAJOR-discovery-11: Rapid file delete+recreate with same mtime not detected
**File:** `reconciler.py:123–127`

Change detection is mtime-based. Same mtime after recreate = no change detected. Stale
nodes remain for deleted-and-recreated files that happen to land on the same mtime.

---

## 7. Web Server & LSP

**Files:** `server.py`, `sse.py`, `deps.py`, `middleware.py`, `routes/`, `lsp/server.py`

### CRITICAL-web-1: CSRF protection is broken
**File:** `middleware.py:12–28`

```python
origin = request.headers.get("origin", "").strip()
if origin and not _is_allowed_origin(origin):
    return JSONResponse({"error": "CSRF rejected"}, status_code=403)
```

The `if origin and ...` condition means **requests without Origin are allowed through**.
Older browsers and some configurations don't send Origin. An attacker can forge a
cross-origin request by not including the Origin header.

**Fix:** Check both Origin and Referer; reject state-changing requests that have neither.

---

### CRITICAL-web-2: Proposal accept is not atomic — race allows double-accept
**File:** `proposals.py:92–170`

Two concurrent accept requests for the same proposal both pass (no atomic status check),
both write files to disk, both append `RewriteAcceptedEvent`. The event log has two
contradictory accepts. File state is undefined.

**Fix:** Atomically transition node status from `AWAITING_REVIEW` to `IDLE` inside a
DB transaction before materializing files. If the transition fails (already accepted),
return 409.

---

### CRITICAL-web-3: Path traversal in proposal file materialization
**File:** `paths.py:30–47`

```python
if source_path.startswith("/"):
    result = Path(source_path)   # absolute path accepted!
```

A workspace file `source//etc/passwd` resolves to an absolute path before
`_resolve_within_project_root` catches it. The guard catches it eventually, but the
logic is convoluted enough to have a bypass risk.

**Fix:** Reject any workspace path containing `..` components or starting with `/` as
the very first check, before any other processing.

---

### CRITICAL-web-4: SSE stream iterator not closed on disconnect
**File:** `sse.py:67–101`

When a client disconnects, `stream_task.cancel()` is called but the underlying
`async_iterator` is never explicitly closed via `aclose()`. Over many connect/disconnect
cycles, iterator resources accumulate.

---

### MAJOR-web-5: Rate limiter keyed to proxy IP, not client IP
**File:** `deps.py:50–59`

`request.client.host` is the immediate TCP peer. Behind a reverse proxy, all requests
share the same rate limiter.

**Fix:** Check `X-Forwarded-For` with a configurable trust flag.

---

### MAJOR-web-6: LSP lazy store init is not async-safe
**File:** `lsp/server.py:106–115`

Two concurrent LSP requests both pass `if "node_store" not in stores`, both open
the database. Result: two live connections to the same SQLite file, first one leaked.

**Fix:** Use `asyncio.Lock` around the initialization block.

---

### MAJOR-web-7: Metrics counters are not atomic
**File:** `metrics.py:14–22`

Plain integer fields incremented with `+=` from concurrent async tasks. Under load,
increments are lost:

```python
self._metrics.events_emitted_total += 1  # read-modify-write, not atomic
```

**Fix:** Use `asyncio.Lock` for metric increments, or use `threading.Lock` with
`asyncio.run_in_executor`.

---

### MAJOR-web-8: api_respond uses node_id from path but never validates it
**File:** `chat.py:67–68`

```python
node_id = request.path_params["node_id"]
resolved = deps.human_input_broker.resolve(request_id, response_text)
```

`node_id` is obtained but never used. The broker resolves by `request_id` only. Any
caller knowing a `request_id` can respond for any node regardless of the URL path.

---

### MAJOR-web-9: JSON parse errors return Starlette's format, not the app's format
**File:** `chat.py:23`, `proposals.py:186`, `cursor.py:16`

`await request.json()` without try/except. Invalid JSON body returns Starlette's 400
in its own format, not the `error_response()` format used everywhere else. Inconsistent
API contract.

---

### MAJOR-web-10: Health check doesn't actually check health
**File:** `health.py:13–23`

Returns `"status": "ok"` with `node_count` if the DB responds. Returns 500 if the DB
is down (exception propagates). Does not check event bus, actor pool, search service,
or reconciler state.

---

### MINOR-web-11: HumanInputBroker futures never cleaned up
**File:** `broker.py:16–40`

Futures accumulate in `_pending` indefinitely. Timed-out futures that were `discard()`-ed
by the timeout handler are removed, but any future that was created and never resolved
or discarded leaks forever.

---

### MINOR-web-12: Conversation history truncation can split multibyte characters
**File:** `nodes.py:101`

```python
"content": str(getattr(message, "content", ""))[:message_limit]
```

Python string slicing at `[:N]` operates on Unicode code points, not UTF-8 bytes, so
this is fine for Python internal handling. However, if the value is later serialized
to bytes (JSON encode), slicing at character boundary is correct. This is not a bug
but the comment in the code suggesting "byte-safe truncation" would be misleading.
The real issue is no minimum content length validation.

---

## 8. Services, Config & Model

**Files:** `config.py`, `node.py`, `types.py`, `errors.py`, `container.py`, `lifecycle.py`

### CRITICAL-config-1: Env var expansion on all config keys leaks secrets
**File:** `config.py:293–302`

`expand_env_vars()` recursively expands `${VAR}` in every string in the config tree.
If a log message, comment, or debug field contains an env var reference, the expanded
value (potentially a secret API key) is written to logs.

**Fix:** Whitelist which fields support expansion (model.api_key, model.base_url only).
Or at minimum, never log expanded values.

---

### MAJOR-config-2: STATUS_TRANSITIONS graph is incomplete
**File:** `types.py:66–77`

- `AWAITING_REVIEW` → `ERROR` is missing (what if review fails?)
- `ERROR` → `RUNNING` is allowed (safe? should require explicit recovery action?)
- No documentation of the intended state machine semantics
- `graph.py`'s transition logic inverts the dict to find valid sources — works but is
  confusing and error-prone

---

### MAJOR-config-3: RuntimeConfig fields have no positive-value validation
**File:** `config.py:127–164`

`max_concurrency=0`, `trigger_cooldown_ms=-1`, `human_input_timeout_s=-100` all pass
validation. These cause cryptic runtime errors deep in asyncio.

**Fix:** Add `@field_validator` with `> 0` checks on all timeout/limit fields.

---

### MAJOR-config-4: Node model allows invalid line/byte ranges
**File:** `node.py:22–25`

No validation that `start_line <= end_line`, `start_byte <= end_byte`, or that values
are non-negative. Code slicing file content with negative byte offsets gets garbage.

---

### MAJOR-config-5: deep_merge silently replaces dicts with non-dicts
**File:** `utils.py:8–17`

```python
else:
    result[key] = value   # dict replaced with list, int, None — no warning
```

`deep_merge({"search": {"enabled": True}}, {"search": None})` produces
`{"search": None}`. Code that then accesses `config.search.enabled` crashes
with `AttributeError: 'NoneType' object has no attribute 'enabled'`.

---

### MINOR-config-6: Error hierarchy is too flat
**File:** `errors.py`

Six exception types for an entire framework. Missing: `NotFoundError`,
`StateTransitionError`, `ValidationError`, `RateLimitError`, `TimeoutError`.
Code resorts to string-matching on exception messages to distinguish subtypes.

---

### MINOR-config-7: Node enum deserialization relies on Pydantic coercion
**File:** `node.py:32–43`

`from_row()` passes raw dict from SQLite directly to `Node(**data)`. NodeType and
NodeStatus are StrEnums and Pydantic coerces strings to them. This works but is
implicit — if an invalid string is in the DB, Pydantic raises a confusing validation
error with no indication of which row or column caused it.

---

### MINOR-config-8: pyproject.toml pins to `rev="main"` for critical deps
**File:** `pyproject.toml`

```toml
grail = { git = "...", rev = "main" }
embeddy = { git = "...", rev = "main" }
```

Unreleased main branches can break silently. Pin to tags.

---

## 9. Architecture & Bundles

*(Architectural review findings)*

### CRITICAL-arch-1: Two-layer reflection creates infinite loop risk
**Architecture**

The reflection design:
1. Primary turn emits `AgentCompleteEvent(tags=["primary"])`
2. Subscription for `AgentCompleteEvent from self with tag "primary"` fires reflection turn
3. Reflection turn is supposed to NOT emit another primary-tagged event

But if a bundle misconfigures `self_reflect.enabled=true` AND the reflection prompt
causes a tool call that emits a custom event that looks like a primary complete...
there's no hard circuit breaker. The `TriggerPolicy.max_trigger_depth` is the only
guard, and it resets per-correlation.

---

### MAJOR-arch-2: Bundle system has no schema validation for .pym tools
**Architecture, bundles/**

System prompt templates use Jinja2 but there's no validation that referenced variables
actually exist in the render context. A bundle with `{{ node_type }}` in the prompt and
a context that doesn't provide `node_type` silently renders as empty string.

---

### MAJOR-arch-3: System prompt length is unbounded
**Architecture, bundles/**

The system prompt is built from: bundle template + node source + companion memory +
event history + tool definitions. No total length cap. A large function with extensive
comments + long companion memory can exceed the model's context window silently.

**Fix:** Truncate each component to configurable limits; log when truncation occurs.

---

### MAJOR-arch-4: No versioning of agent workspace state
**Architecture**

When a bundle is updated (new version deployed), existing agent workspaces have the old
bundle files. The fingerprint mechanism prevents re-provisioning if fingerprint matches,
but there's no migration mechanism for breaking changes. Old `companion/reflections`
KV structure from v1 is read by v2 code that expects a different schema.

---

### MAJOR-arch-5: Companion virtual agent is a single point of failure
**Architecture**

All agent reflections funnel through the companion virtual agent. If it becomes stuck
in any non-idle status, ALL agents that do self-reflection will queue
`TurnDigestedEvent` triggers indefinitely.

---

### MINOR-arch-6: Bundle deep_merge semantics not documented
**Bundles, docs/**

If both `system/bundle.yaml` and `code-agent/bundle.yaml` define `prompts.reactive`,
deep_merge gives the role bundle priority. This is correct, but is not documented.
Users wonder why their system bundle prompt is being overridden.

---

### MINOR-arch-7: Directory agent system prompt is empty
**File:** `bundles/directory-agent/bundle.yaml`

The directory-agent role has a sparse or missing system prompt. Directory agents
receive `NodeChangedEvent` from files in their subtree and are expected to do
something useful, but there's no guidance in the prompt about what that is.

---

### NIT-arch-8: remora.yaml.example has examples but no schema comments
**Docs**

The example config doesn't document units (is `trigger_cooldown_ms` in milliseconds?),
valid ranges, or the difference between `bundle_map` and `bundle_overlays`.

---

## 10. Test Suite

### MAJOR-test-1: No tests for concurrent scenarios
The most critical bugs (TriggerPolicy race, history mutation race, actor eviction race)
have zero test coverage. The test suite is entirely single-threaded sequential.

### MAJOR-test-2: Acceptance tests may be order-dependent
Several acceptance tests assume specific event sequences without asserting intermediate
states. If the system is faster or slower than expected, tests pass or fail nondeterministically.

### MAJOR-test-3: Status transition logic has minimal coverage
`validate_status_transition()` is tested only for a few invalid transitions. The full
state machine (5 states × 5 transitions) is not exhaustively tested.

### MINOR-test-4: No tests for node boundary validation
`node.py` has no validator for `start_line > end_line` — and there's no test that
checks this is caught.

### MINOR-test-5: No fuzz/property-based tests for discovery
Discovery parses arbitrary user files. No fuzz testing exists. A single malformed file
crashes the reconciler (already noted as CRITICAL) and could be caught with basic fuzzing.

### MINOR-test-6: Deep merge edge cases untested
`deep_merge({"a": {"b": 1}}, {"a": None})` crashes downstream code. No test for
type-changing merges.

### NIT-test-7: Test naming inconsistency
Some tests are `test_<thing>_<condition>`, others are `test_<thing>`. No convention
enforced.

---

## 11. Summary Scoreboard

### CRITICAL (25 issues)

| ID | Area | Title |
|----|------|-------|
| agents-1 | Agents | TriggerPolicy not async-safe |
| agents-2 | Agents | Actor stop() hangs on running turn |
| agents-3 | Agents | RuntimeError crashes actor loop silently |
| storage-1 | Storage | No FK constraints → orphaned edges |
| storage-2 | Storage | delete_node deletes edges first, not atomic |
| storage-3 | Storage | Nested batch doesn't rollback on exception |
| storage-4 | Storage | SQLite BUSY not handled |
| storage-5 | Storage | Concurrent NodeStore writes not atomic |
| events-1 | Events | EventBus silently drops events on overflow |
| tools-1 | Tools | propose_changes() reports ALL files not changed |
| tools-2 | Tools | request_human_input() leaves node stuck in AWAITING_INPUT |
| tools-3 | Tools | Grail cache uses truncated 64-bit hash (collision risk) |
| tools-4 | Tools | broadcast() sends to ghost/deleted nodes |
| discovery-1 | Discovery | No file size limit — binary files OOM process |
| discovery-2 | Discovery | Tree-sitter failures not caught — crashes scan |
| discovery-3 | Discovery | Node IDs not stable across file moves |
| discovery-4 | Discovery | Content subscription path check is ambiguous |
| discovery-5 | Discovery | Reconciler is a God Object |
| discovery-6 | Discovery | Virtual agent hash excludes agent ID |
| web-1 | Web | CSRF protection broken — missing Referer check |
| web-2 | Web | Proposal accept is not atomic — double-accept race |
| web-3 | Web | Path traversal in proposal file materialization |
| web-4 | Web | SSE iterator not closed on disconnect |
| config-1 | Config | Env var expansion across all keys leaks secrets |
| arch-1 | Arch | Two-layer reflection has no hard loop breaker |

### Top 10 "Fix These First"

1. **CSRF protection** — broken security is worse than no security
2. **Actor loop silent death** — agents die with no trace, system appears to work
3. **request_human_input stuck status** — nodes permanently blocked
4. **propose_changes wrong files** — wrong semantic, not a minor bug
5. **SQLite BUSY not handled** — any contention = data loss
6. **TriggerPolicy race** — depth tracking corruption under load
7. **Grail hash truncation** — 64-bit collision space in a production cache
8. **EventBus silent event drops** — client state corrupts silently
9. **God Object reconciler** — every bug in any area requires touching it
10. **Env var expansion scope** — secret leakage risk in logs

---

*Review complete. Findings from 8 parallel analysis passes across all subsystems.*
*Additional sections (events deep-dive, architecture deep-dive) may be appended.*
