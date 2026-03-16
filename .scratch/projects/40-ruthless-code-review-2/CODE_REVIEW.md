# Remora v2 — Ruthless Code Review

**Date**: 2026-03-16
**Scope**: Full library review — `src/remora/` (35 files, ~6,600 LOC)
**Severity Scale**: CRITICAL > HIGH > MEDIUM > LOW > NIT

---

## Table of Contents

1. **Executive Summary** — Overall assessment and grade
2. **Architecture Review** — Layering, dependency flow, separation of concerns
3. **actor.py (952 LOC)** — The largest file; actor model, turn execution, prompt building
4. **reconciler.py (704 LOC)** — File reconciliation, directory materialization, virtual agents
5. **web/server.py (603 LOC)** — HTTP API, SSE, CSRF, rate limiting
6. **externals.py (382 LOC)** — Agent tool API surface (TurnContext)
7. **Event System** — types.py, store.py, bus.py, subscriptions.py, dispatcher.py
8. **Core Infrastructure** — config.py, graph.py, workspace.py, db.py, kernel.py, services.py, lifecycle.py, grail.py, metrics.py, search.py
9. **Code Discovery** — discovery.py, languages.py, projections.py, paths.py
10. **CLI & LSP** — __main__.py, lsp/server.py
11. **Test Suite Assessment** — Coverage gaps, quality, patterns
12. **Cross-Cutting Concerns** — Error handling, logging, security, typing, naming

---

## 1. Executive Summary

**Overall Grade: C+**

Remora v2 is a functioning reactive agent substrate with a coherent core concept — code elements become nodes, nodes become actors, actors respond to events via LLM turns. The architecture is sound at the macro level. However, the implementation suffers from several recurring patterns that suggest the code was written quickly without enough refactoring passes:

**What works well:**
- Clear separation between discovery (tree-sitter) → graph (SQLite) → actor (event-driven) layers
- Pydantic models for config and events provide good validation boundaries
- The event system (bus + subscriptions + dispatcher) is cleanly decomposed
- Test suite exists and covers most modules with reasonable depth (~9,300 LOC of tests)
- Sensible use of asyncio primitives (semaphores, queues, locks)

**What doesn't:**
- The largest file (`actor.py`, 952 LOC) contains a massive delegation anti-pattern where `Actor` re-exposes every method of `AgentTurnExecutor` via trivial wrappers
- Pervasive use of `object | None` and `Any` types defeats static analysis
- The web server is a 600-line closure soup — all endpoints defined as nested functions inside `create_app()`
- Multiple encapsulation violations (accessing `_private` attributes from outside classes)
- Inconsistent error handling philosophy — some places catch `Exception` broadly, others let things propagate
- Class-level mutable state on `TurnContext` (`_send_message_timestamps` is a class variable shared across all instances)

**Risk assessment:**
- No critical security vulnerabilities found, but the CSRF middleware only checks origin header (no token-based CSRF protection)
- The `_workspace_path_to_disk_path` path traversal protection in the web server is good but relies on a single `relative_to()` check
- SHA-1 used for workspace IDs in `workspace.py` — not a security issue per se but signals carelessness about hash choice

---

## 2. Architecture Review

### Dependency Flow

The layering is generally good:

```
CLI (__main__.py) / Web (server.py) / LSP (lsp/server.py)
        ↓                ↓                 ↓
    RemoraLifecycle → RuntimeServices (DI container)
        ↓
    ActorPool → Actor → AgentTurnExecutor → Kernel
        ↓
    EventStore → EventBus + TriggerDispatcher → SubscriptionRegistry
        ↓
    NodeStore (graph.py) → aiosqlite
        ↓
    FileReconciler → discovery.py → tree-sitter
```

**[MEDIUM] RuntimeServices is a bag, not a container.** `RuntimeServices` in `services.py` just assigns everything to `self.*` attributes. It's a flat namespace of 12+ services with no interface segregation. Any consumer gets access to everything. This is a "service locator" pattern rather than proper dependency injection. It works at this scale but makes testing harder and coupling invisible.

**[MEDIUM] Circular conceptual dependency between EventStore and TriggerDispatcher.** `EventStore.append()` calls `self._dispatcher.dispatch()`, which calls `self._subscriptions.get_matching_agents()`, which routes back to `ActorPool._route_to_actor()`. This means every event append triggers a full subscription scan and potential actor creation. The chain is: write to DB → fan out to bus → fan out to subscriptions → create actors → queue events. This is all synchronous within a single `await`, meaning a slow subscription match blocks event persistence for all other callers.

**[LOW] Three surfaces, no shared middleware.** CLI, Web, and LSP all compose services differently. The web server builds its own app with closures; the LSP server lazily opens stores; the CLI just calls `asyncio.run()`. There's no shared request/response abstraction, which is fine at this size but means each surface independently re-implements patterns like "get node, check if None, return 404."

### Separation of Concerns

**[HIGH] `actor.py` conflates three responsibilities.** This 952-line file contains:
1. `Outbox` + `OutboxObserver` — event emission adapter
2. `TriggerPolicy` + `PromptBuilder` + `AgentTurnExecutor` — turn execution engine
3. `Actor` — inbox/outbox lifecycle management

These should be separate modules. The `Actor` class itself is 210 lines but ~100 of those are delegation wrappers that just forward to `AgentTurnExecutor` methods, which is pure dead weight.

**[MEDIUM] `web/server.py` is a single function.** All 20+ endpoints are closures inside `create_app()`. This means:
- No class-based views, no way to test endpoints in isolation without calling `create_app()`
- All state (event_store, node_store, etc.) captured via closure, not injected
- The function is 560+ lines long

---

## 3. actor.py (952 LOC)

This is the heart of the system and the most problematic file.

### [HIGH] Massive Delegation Anti-Pattern (lines 854-936)

The `Actor` class re-exposes nearly every method of `AgentTurnExecutor` as trivial wrappers:

```python
async def _start_agent_turn(self, ...):
    return await self._turn_executor._start_agent_turn(...)

async def _prepare_turn_context(self, ...):
    return await self._turn_executor._prepare_turn_context(...)

async def _run_kernel(self, ...):
    return await self._turn_executor._run_kernel(...)
```

This is ~80 lines of pure boilerplate. These wrappers:
- Call private (`_`-prefixed) methods on another object, violating encapsulation
- Add zero logic — they're 1:1 pass-throughs
- Exist only because tests or other code historically called `actor._start_agent_turn()` directly
- Make the Actor class look bigger and more complex than it actually is

**Verdict:** Delete all the delegation wrappers. If tests need to call executor methods, they should test the executor directly.

### [HIGH] Compatibility Property Shims (lines 760-791)

Similarly, the Actor exposes internal TriggerPolicy state via property shims:

```python
@property
def _depths(self) -> dict[str, int]:
    return self._trigger_policy.depths

@_depths.setter
def _depths(self, value: dict[str, int]) -> None:
    self._trigger_policy.depths = value
```

These exist for backward compatibility with tests that poke at `actor._depths` directly. This is test-driven design in the worst sense — the API shape is dictated by test implementation details rather than actual usage requirements.

### [MEDIUM] OutboxObserver Uses String-Based Type Dispatch (lines 119-159)

```python
event_name = type(event).__name__
if event_name == "ModelRequestEvent":
    ...
```

This dispatches on `type(event).__name__` instead of using `isinstance()`. If `structured_agents` ever changes a class name or if there's a naming collision, this silently breaks. It also means you can't use type checkers to verify exhaustiveness.

### [MEDIUM] `_build_companion_context` Defensive Coding Overkill (lines 601-658)

This method has 58 lines of defensive `isinstance()` checks on every field of every entry in every list:

```python
if isinstance(reflections, list) and reflections:
    for entry in reflections[-5:]:
        if not isinstance(entry, dict):
            continue
        insight = entry.get("insight", "")
        if isinstance(insight, str) and insight.strip():
```

This level of defensive coding suggests the KV store data has no schema guarantee. Either enforce a schema at write time (so reads can trust the shape) or centralize the validation in the workspace layer — don't scatter `isinstance` checks through business logic.

### [LOW] `_read_bundle_config` Manual Validation (lines 660-721)

62 lines of manual YAML field validation that could be a Pydantic model. The function manually checks types, strips strings, validates max_turns, etc. This is exactly what Pydantic is for, and the project already uses Pydantic heavily.

### [LOW] Retry Logic with max_retries=1 (lines 500-553)

```python
max_retries = 1
...
for attempt in range(max_retries + 1):
```

A retry loop that only retries once is hard to justify. Either the operation is idempotent and worth retrying (use proper retry with backoff), or it's not (don't retry at all). The current implementation adds complexity for minimal benefit.

---

## 4. reconciler.py (704 LOC)

The file reconciler is one of the more complex modules and is generally well-structured, but has some notable issues.

### [HIGH] `_materialize_directories` is 125 Lines of Dense Logic (lines 195-320)

This single method handles:
1. Computing directory hierarchy from file paths
2. Building children-by-directory maps
3. Deleting stale directories
4. Upserting new/changed directories
5. Registering subscriptions
6. Provisioning bundles
7. Emitting discovery/change events

This should be decomposed into at least 3-4 smaller methods. The method is difficult to reason about because it mixes graph mutation, event emission, and workspace provisioning in a single dense loop.

### [MEDIUM] File Lock Memory Leak Potential (lines 489-511)

`_file_locks` and `_file_lock_generations` grow unbounded. The `_evict_stale_file_locks` method only cleans up locks from previous generations that aren't currently held. If files are added and never modified again, their locks persist forever. For a long-running daemon watching thousands of files, this accumulates.

### [MEDIUM] Duplicate Event Registration on Virtual Agent Updates (lines 645-649)

For existing virtual agents, `_register_subscriptions` and `_provision_bundle` are called unconditionally even when nothing changed:

```python
await self._register_subscriptions(virtual_node, virtual_subscriptions=patterns)
await self._provision_bundle(virtual_node.node_id, virtual_node.role)
```

This means every reconcile cycle re-registers subscriptions for all virtual agents, which involves deleting and re-inserting DB rows. Wasteful for what should be a no-op.

### [LOW] `_normalize_dir_id` is a No-Op (line 351-353)

```python
@staticmethod
def _normalize_dir_id(path: Path | str) -> str:
    value = Path(path).as_posix() if isinstance(path, Path) else Path(path).as_posix()
    return "." if value in {"", "."} else value
```

The `isinstance` check is meaningless — both branches do `Path(path).as_posix()`. The conditional adds nothing.

### [LOW] `_stop_event` Polling Pattern (lines 156-175)

The stop mechanism creates a `threading.Event` checked by a coroutine polling every 0.5s. This is a bridge between asyncio and threading (`watchfiles` requires a threading event). It works but the polling loop wastes cycles. An `asyncio.Event` signaled from `stop()` that sets the threading event would be cleaner.

---

## 5. web/server.py (603 LOC)

### [HIGH] Entire Server is One Giant Closure

`create_app()` is a 560-line function containing 20+ nested endpoint functions. Problems:

- **Testability:** You can't unit-test an endpoint without constructing the full Starlette app
- **Readability:** Scrolling through 560 lines of nested functions to find one endpoint
- **Reuse:** No way to compose endpoints or share handler logic
- **IDE support:** Poor navigation since everything is local to one function

This should use Starlette's class-based endpoint pattern or at minimum a router/blueprint approach where handlers are module-level functions or methods.

### [MEDIUM] Health Endpoint Accesses Private DB Attribute (line 433)

```python
cursor = await node_store._db.execute("SELECT COUNT(*) FROM nodes")
```

The health endpoint reaches through `NodeStore` to access its private `_db` attribute and runs a raw SQL query. This should be a method on `NodeStore` like `count_nodes()`.

### [MEDIUM] `_latest_rewrite_proposal` is N+1 Prone (lines 128-133)

```python
async def _latest_rewrite_proposal(node_id: str) -> dict | None:
    rows = await event_store.get_events_for_agent(node_id, limit=200)
    for row in rows:
        if row.get("event_type") == "RewriteProposalEvent":
            return row
    return None
```

This fetches up to 200 events and scans for the first matching type. A single SQL query with `WHERE event_type = 'RewriteProposalEvent'` would be far more efficient. This is called from `api_proposals` which itself iterates over all AWAITING_REVIEW nodes, making the total cost O(nodes × 200).

### [MEDIUM] SSE Stream Polling (lines 540-548)

```python
try:
    event = await asyncio.wait_for(stream_iterator.__anext__(), timeout=0.25)
except TimeoutError:
    continue
```

The SSE stream uses a 0.25s polling loop with `wait_for` + timeout instead of selecting on both the stream and disconnection. This means 4 exception raises per second per connected client even when idle. Use `asyncio.create_task` for the disconnection check instead.

### [LOW] Rate Limiter is Per-Process, Not Per-Client (lines 46-61)

`RateLimiter` is a single shared instance — all clients share the same 10 req/60s budget for `/api/chat`. One active user blocks all other users. Rate limiting should be per-IP or per-session.

### [LOW] No Request Body Size Limits

POST endpoints like `api_chat`, `api_respond`, `api_search`, etc. call `await request.json()` without any body size limits. A malicious client could send a multi-GB JSON body.

### [NIT] Inconsistent Error Response Format

Some endpoints return `{"error": "..."}` with status 400/404/503, while `api_health` returns `{"status": "ok"}`. There's no consistent error envelope.

---

## 6. externals.py (382 LOC)

### [HIGH] Class-Level Mutable State Shared Across All Instances (line 30)

```python
class TurnContext:
    _send_message_timestamps: dict[str, deque[float]] = {}
```

This is a **class variable**, not an instance variable. Every `TurnContext` instance shares the same timestamps dictionary. This means:
- Rate limiting state persists across agent turns even after the `TurnContext` is garbage collected
- Memory grows unbounded as new node_ids accumulate
- In tests, state leaks between test cases unless manually cleared

This should be an instance variable initialized in `__init__`, with the rate limiter state managed at the `Actor` or `ActorPool` level for proper lifecycle management.

### [MEDIUM] `search_content` is O(files × lines) Full Scan (lines 81-97)

```python
async def search_content(self, pattern: str, path: str = ".") -> list[dict[str, Any]]:
    paths = await self.workspace.list_all_paths()
    for file_path in paths:
        ...
        content = await self.workspace.read(normalized)
        for index, line in enumerate(content.splitlines(), start=1):
            if pattern in line:
```

This does a linear scan of every line of every file in the workspace. For large workspaces, this is extremely slow. It also holds the workspace lock for each file read individually (releasing and reacquiring N times). The `_search_content_max_matches` cap helps but doesn't fix the fundamental inefficiency.

### [MEDIUM] `search_service` Typed as `Any` (line 45)

```python
search_service: Any = None,
```

The search service is passed around as `object | None` or `Any` throughout the codebase (actor.py, runner.py, reconciler.py, services.py, web/server.py). This means:
- No IDE autocompletion
- No static type checking
- Any typo in method calls (`search_service.serch(...)`) won't be caught until runtime

It should use a Protocol or ABC defining the `SearchService` interface.

### [LOW] `broadcast` Loads Entire Node Graph (line 217)

```python
async def broadcast(self, pattern: str, content: str) -> str:
    nodes = await self._node_store.list_nodes()
```

Broadcasting loads ALL nodes to resolve targets. For a large codebase with thousands of nodes, this is a heavy operation just to send a message to a subset. The node_store should support filtered queries for broadcast resolution.

### [LOW] `_resolve_broadcast_targets` Pattern Matching is Fragile (lines 354-381)

The broadcast pattern matching supports `*`, `all`, `siblings`, `file:path`, and substring matching. This is ad-hoc — no documentation of the pattern language, no validation, and substring matching (`pattern in node_id`) could accidentally match unintended targets.

---

## 7. Event System

The event system (types.py, store.py, bus.py, subscriptions.py, dispatcher.py) is the cleanest part of the codebase. Well-decomposed with clear responsibilities.

### types.py (255 LOC)

**[LOW] `TurnDigestedEvent.tags` Shadows Base Class Field.**
The base `Event` class has `tags: tuple[str, ...]`. `TurnDigestedEvent` also declares `tags: tuple[str, ...] = ()` (line 198). This is a redeclaration of the same field with the same type and default — unnecessary and confusing. It shadows the parent field.

**[NIT] `CustomEvent` Stores Payload Redundantly.**
`CustomEvent` has a `payload` field, but `Event.to_envelope()` already puts all non-base fields into `payload`. So `CustomEvent`'s payload ends up nested: `{"payload": {"payload": {...}}}`. This is likely a design mistake.

### store.py (180 LOC)

**[MEDIUM] Every `append()` Does a Full Commit.**
`EventStore.append()` runs `INSERT` then `await self._db.commit()` on every single event. In a busy system emitting dozens of events per second, this means dozens of fsync calls per second. This is a serious performance bottleneck for SQLite with WAL mode. Batching commits (e.g., commit every 100ms or every N events) would dramatically improve throughput.

**[LOW] `get_events_after` Uses String-Based ID Comparison.**
```python
numeric_id = int(after_id)
```
The `Last-Event-ID` from SSE is parsed from float timestamp (`event.timestamp`) but then used as an integer event ID. This works because the SSE stream uses `event.timestamp` as the ID string, and `get_events_after` falls back to `[]` on parse failure. But the semantic mismatch (timestamp as event ID vs. autoincrement ID) is confusing and fragile.

### bus.py (92 LOC)

**[LOW] `unsubscribe` Only Removes First Occurrence.**
```python
handlers.remove(handler)
```
`list.remove()` removes only the first occurrence. If a handler is registered twice (e.g., due to a bug), unsubscribing leaves a ghost registration. Should use `while handler in handlers: handlers.remove(handler)` or filter.

**[NIT]** Good use of `asynccontextmanager` for the stream pattern. Clean implementation.

### subscriptions.py (190 LOC)

**[MEDIUM] Cache Invalidation on Every Write.**
`register()`, `unregister()`, and `unregister_by_agent()` all modify the cache incrementally. This is correct but fragile — if any cache update has a bug, the cache silently diverges from the DB. There's no periodic cache refresh or consistency check.

**[LOW] `get_matching_agents` Deduplicates in O(n) but Returns Unordered.**
The deduplication via `seen` set is fine, but the ordering depends on iteration order of the cache lists, which isn't guaranteed to be stable across cache rebuilds.

### dispatcher.py (57 LOC)

Clean, no issues. Good use of a settable `router` property to break the circular dependency with `ActorPool`.

---

## 8. Core Infrastructure

### config.py (266 LOC)

**[LOW] `_expand_env_vars` Recursion Without Depth Limit.**
```python
def _expand_env_vars(data: Any) -> Any:
    if isinstance(data, dict):
        return {key: _expand_env_vars(value) for key, value in data.items()}
```
If someone provides a deeply nested YAML config (or a recursive reference via YAML anchors), this will hit Python's recursion limit. Not a realistic concern but worth noting.

**[LOW] `_find_config_file` Walks to Filesystem Root.**
The config file search walks up from CWD to `/`. This is standard for tools like `.gitconfig` but could be surprising if it finds a stale `remora.yaml` in a parent directory.

**[NIT]** Good use of `pydantic_settings` for env var integration. Clean validators.

### graph.py (261 LOC)

**[MEDIUM] `batch()` Context Manager Doesn't Handle Nested Failures.**
```python
self._batch_depth += 1
try:
    yield
finally:
    self._batch_depth -= 1
    if self._batch_depth == 0:
        await self._db.commit()
```
If an inner operation fails and raises, the `finally` block still commits. This means a partially-completed batch of mutations gets persisted. Should `ROLLBACK` on exception instead.

**[LOW] `set_status` Bypasses Transition Validation.**
`NodeStore` has both `set_status()` (no validation) and `transition_status()` (validates against `STATUS_TRANSITIONS`). Any caller can use `set_status()` to bypass the state machine. If the state machine matters, `set_status` should be removed or made private.

**[NIT]** SQL construction via f-strings in `list_nodes` is safe (all parameters are bound) but looks like SQL injection at first glance. Using a query builder would improve readability.

### workspace.py (224 LOC)

**[MEDIUM] Every Operation Acquires a Lock.**
`AgentWorkspace` wraps every single operation in `async with self._lock`. This serializes all workspace I/O for an agent. Reads that don't conflict with writes are unnecessarily serialized. A read-write lock would allow concurrent reads.

**[LOW] SHA-1 for Workspace IDs (line 185).**
```python
digest = hashlib.sha1(node_id.encode("utf-8")).hexdigest()[:10]
```
SHA-1 is cryptographically broken. While this isn't used for security (just filesystem-safe naming), using SHA-256 everywhere (as done elsewhere in the codebase) would be more consistent.

**[NIT] `_merge_dicts` and `_bundle_template_fingerprint` Are Module-Level Functions After `__all__`.**
These utility functions are defined after the `__all__` declaration. Conventionally, `__all__` goes at the end of a module. Minor style issue.

### db.py (21 LOC)

Clean. `PRAGMA busy_timeout=5000` is sensible. `Connection` type alias is fine.

**[NIT]** Consider `PRAGMA synchronous=NORMAL` for better WAL performance (default is FULL).

### kernel.py (59 LOC)

**[LOW] `api_key or "EMPTY"` Fallback (line 33).**
If no API key is configured, the code sends `"EMPTY"` as the key. This will cause an authentication error at the LLM provider, which is fine, but a clearer error at config validation time would be better.

**[NIT]** `extract_response_text` falls back to `str(result)` which could produce unhelpful output like `<AgentResult object at 0x...>`.

### services.py (98 LOC)

**[LOW] `create_tables` Called Redundantly.**
Both `node_store.create_tables()` and `event_store.create_tables()` are called, but `event_store.create_tables()` internally calls `self._dispatcher.subscriptions.create_tables()`. Then `services.py` also calls `subscriptions.create_tables()` separately. The subscription tables are created twice.

**[NIT]** Clean DI container pattern. Good that it's explicit rather than using a framework.

### lifecycle.py (196 LOC)

**[MEDIUM] `configure_file_logging` Passed as `Any`.**
```python
configure_file_logging: Any,
```
The logging configuration callback is typed as `Any`. This should be `Callable[[Path], None]`.

**[LOW] Shutdown Order Dependencies Not Documented.**
The shutdown sequence (stop reconciler → stop runner → stop web → close services → cancel tasks) has implicit ordering requirements. If the order changes, actors might try to write to a closed DB. This should be documented or enforced.

### grail.py (208 LOC)

**[MEDIUM] Global Mutable Cache `_SCRIPT_SOURCE_CACHE` (line 28).**
```python
_SCRIPT_SOURCE_CACHE: dict[tuple[str, str], str] = {}
```
Module-level mutable state that grows unbounded. Combined with `@lru_cache(maxsize=256)` on `_cached_script`, this creates a two-level cache with no coordination. The source cache has no eviction, and the LRU cache evicts compiled scripts but not their source text.

**[LOW] Temp Directory Created Per Script Load (lines 52-56).**
```python
with tempfile.TemporaryDirectory(prefix="remora-grail-") as temp_dir:
    script_path = Path(temp_dir) / normalized_name
    script_path.write_text(source, encoding="utf-8")
    return grail.load(script_path)
```
Every script parse creates a temp directory, writes a file, parses it, then deletes the directory. If Grail supports loading from strings, that would eliminate the filesystem round-trip.

### metrics.py (50 LOC)

Clean. Simple dataclass with counters and gauges. `snapshot()` is well-implemented.

**[NIT]** `cache_hit_rate` formula counts provisions as misses, which is slightly misleading — provisions include first-time creates, not just cache misses.

### search.py (245 LOC)

**[LOW] Duplicate Result Serialization (lines 129-143, 163-177).**
The `search()` and `find_similar()` methods both have identical dict-comprehension blocks for local mode results. This should be a shared helper.

**[NIT]** Good graceful degradation when embeddy is not installed.

---

## 9. Code Discovery

### discovery.py (231 LOC)

**[MEDIUM] Global LRU Caches Never Cleared (lines 77-101).**
Four module-level `@lru_cache` functions (`_get_language_registry`, `_get_registry_plugin`, `_get_parser`, `_load_query`) hold onto tree-sitter Language and Parser objects forever. While these are intended to be singletons, they make testing difficult (tests can't reset state) and can hold stale query files if queries are modified at runtime.

**[LOW] `_parse_file` Builds Complex In-Memory Index (lines 115-203).**
The function builds three dictionaries (`by_key`, `parent_by_key`, `name_by_key`) and then iterates over all entries to construct parent-child relationships. This is quadratic in the worst case (each node walks up to root via `parent.parent`). For typical source files this is fine, but for auto-generated files with deep nesting it could be slow.

**[NIT]** `_build_name_from_tree` accepts `name_node` but immediately `del`s it (line 212). Remove the parameter.

### languages.py (157 LOC)

**[LOW] Plugin Properties Could Be Class Attributes.**
Each plugin (PythonPlugin, MarkdownPlugin, TomlPlugin) uses `@property` for `name` and `extensions` that always return constants. These should be plain class attributes for simplicity.

**[NIT]** Good use of Protocol for `LanguagePlugin`. Clean registry pattern.

### projections.py (79 LOC)

**[MEDIUM] N+1 Query Pattern (lines 27-40).**
```python
for cst in cst_nodes:
    existing = await node_store.get_node(cst.node_id)
    ...
    await node_store.upsert_node(node)
    ...
    await workspace_service.provision_bundle(cst.node_id, template_dirs)
```
For each CST node (could be hundreds per file), this does:
1. One SELECT to check if node exists
2. One INSERT/REPLACE to upsert
3. Multiple workspace operations to provision bundles

This should batch the existence checks (one SELECT with `IN` clause) and batch the upserts.

### paths.py (74 LOC)

**[LOW] `walk_source_files` Ignore Pattern Matching is Quadratic.**
```python
def ignored(path: Path) -> bool:
    for pattern in normalized:
        if pattern in parts:
            ...
        if fnmatch.fnmatch(text, pattern) or fnmatch.fnmatch(path.name, pattern):
            ...
```
For each file, every ignore pattern is checked three ways (part membership, full path match, name match). For large projects with many ignore patterns, this becomes slow. Pre-compiling patterns or using a trie would help.

**[NIT]** `resolve_query_paths` doesn't filter for existence (unlike `resolve_discovery_paths`). Inconsistent behavior.

---

## 10. CLI & LSP

### __main__.py (329 LOC)

**[LOW] `_discover` is Unnecessarily Async.**
```python
async def _discover(...) -> list[CSTNode]:
    ...
    return discover_nodes(...)
```
The `_discover` function is async but calls only synchronous functions. It's called via `asyncio.run()` for no reason.

**[LOW] `_index` Conflates UI and Logic.**
The index command mixes `typer.echo` calls with service operations. The search indexing logic should be separate from the CLI output formatting.

**[NIT]** Clean Typer setup. Good use of `Annotated` types.

### lsp/server.py (342 LOC)

**[MEDIUM] Standalone Mode Leaks Database Connections.**
`_open_standalone_stores()` opens an aiosqlite connection and stores it in a closure dict, but there's no corresponding close. The connection lives until the LSP server process exits.

**[MEDIUM] Chat Command Hardcodes Port (line 183).**
```python
uri=f"http://localhost:8080/?node={node_id}",
```
The web UI URL is hardcoded to port 8080. If the user starts remora with `--port 9090`, the LSP chat command opens the wrong URL.

**[LOW] `DocumentStore.apply_changes` Doesn't Handle All Edge Cases.**
The incremental text update logic works for most LSP clients but doesn't handle overlapping ranges or ranges that extend past the document end. These cases are rare but specified in the LSP protocol.

**[NIT]** Good test hook pattern with `RemoraLSPHandlers`. Makes LSP testing much easier than spinning up a transport.

---

## 11. Test Suite Assessment

**Stats:** 44 test files, ~9,300 LOC of tests vs ~6,600 LOC of source (1.4:1 ratio — solid)

### Coverage Gaps

**[HIGH] No tests for `lifecycle.py`.** The entire startup/shutdown orchestration is untested. This is the most complex coordination code in the system.

**[MEDIUM] `web/server.py` tests don't cover SSE reconnection.** The SSE `Last-Event-ID` replay and `?once` parameter are tested but SSE disconnection handling and the shutdown event propagation are not.

**[MEDIUM] No concurrency tests.** The system is heavily concurrent (semaphores, queues, actor pools, event fan-out) but there are no tests that exercise concurrent access patterns — e.g., two agents triggering simultaneously, or events emitted while subscriptions are being modified.

**[LOW]** `test_actor.py` at 1,256 lines is the largest test file and tests many internal implementation details of the old Actor API (before the refactor into AgentTurnExecutor). Many of these tests are testing the delegation wrappers that should be deleted.

### Test Quality

**Generally good:**
- Good use of factories (`tests/factories.py`) for test data
- Good use of test doubles (`tests/doubles.py`) for faking workspace, kernel, etc.
- Proper async test patterns with `pytest-asyncio`
- Integration tests exercise real tree-sitter parsing

**Could improve:**
- Many tests are whitebox — they poke at `actor._depths`, `actor._trigger_policy`, etc.
- Test names are often generic (`test_basic_flow`, `test_edge_cases`)
- No property-based testing for the event matching/subscription logic, which would be a natural fit

---

## 12. Cross-Cutting Concerns

### Error Handling

**[HIGH] Inconsistent Exception Philosophy.**

The codebase has two competing patterns:

1. **Catch everything:** `except Exception: # noqa: BLE001` appears 12+ times. This is the "never crash the loop" philosophy. It's applied to:
   - Actor turn execution (correct — agents shouldn't crash the system)
   - Tool execution (correct — tools shouldn't crash the agent)
   - Reconciler watch batches (correct — one file shouldn't block others)
   - Bundle provisioning metadata sync (questionable — silently losing config)
   - Search indexing (acceptable — degraded but functional)

2. **Let it propagate:** Some paths let exceptions bubble up with no handling:
   - `workspace.read()` can raise `FileNotFoundError` through to callers
   - `graph_set_status()` can raise `ValueError` for invalid status names
   - Config loading lets YAML parse errors propagate

The philosophy should be documented: what are the error boundaries? Where should errors be caught vs. propagated?

### Logging

**[MEDIUM] Excessive Info-Level Logging in Hot Paths.**

Every tool execution logs at INFO level (grail.py lines 124-146):
```python
logger.info("Tool start agent=%s tool=%s ...")
logger.info("Tool complete agent=%s tool=%s ...")
```

Every agent turn logs at INFO level (actor.py lines 378-386). For a system running dozens of concurrent agents with multiple tool calls per turn, this generates enormous log volume. These should be DEBUG level, with INFO reserved for lifecycle events (start, stop, error).

### Security

**[MEDIUM] CSRF Protection is Origin-Only.**
The `CSRFMiddleware` only checks the `Origin` header. This is insufficient for:
- Requests that don't send Origin (e.g., form POSTs from some browsers)
- Browser extensions that can forge Origin headers

Token-based CSRF (e.g., double-submit cookie) would be more robust. However, since this is a localhost-only developer tool, the risk is low.

**[LOW] No Authentication on Any Endpoint.**
All API endpoints are unauthenticated. Anyone who can reach the port can:
- Read all source code (via proposal diffs)
- Send messages to agents
- Accept/reject code changes (which writes to disk!)

For a localhost dev tool this is acceptable, but the `--bind 0.0.0.0` option makes it accessible on the network with zero auth.

### Typing

**[HIGH] `search_service: object | None` Pattern.**
The search service is typed as `object | None` or `Any` in 7 different files. Every consumer uses `getattr(search_service, "available", False)` duck-typing instead of proper interface checks. This is the most widespread typing failure in the codebase.

**[MEDIUM] Heavy Use of `Any`.**
- `TurnContext.__init__` takes `outbox: Any`
- `AgentWorkspace.__init__` takes `workspace: Any`
- `RemoraLifecycle.__init__` takes `configure_file_logging: Any`
- `GrailTool.execute` returns `ToolResult` but takes `context: ToolCall | None`
- `lifecycle.py` stores `_lsp_server: Any`

Each of these could be a Protocol or concrete type.

### Naming

**[LOW] Inconsistent Naming Conventions.**
- `_send_message_timestamps` (snake_case with leading underscore)
- `_DEPTH_TTL_MS` (SCREAMING_SNAKE for module constants)
- `_build_companion_context` (verb phrase for a method) but `_event_content` (noun phrase for a function)
- `CairnWorkspaceService` vs `SearchService` vs `ActorPool` — some have "Service" suffix, some don't
- `node_store` vs `event_store` vs `workspace_service` — "store" vs "service" used interchangeably

**[NIT] File-Level `__all__` Placement.**
Most files put `__all__` at the end (good). But `workspace.py` puts it before helper functions `_merge_dicts` and `_bundle_template_fingerprint`, and `externals.py` puts it at the very end after the helper function. Minor inconsistency.

---

## Summary of Findings by Severity

| Severity | Count | Key Issues |
|----------|-------|------------|
| CRITICAL | 0 | — |
| HIGH | 7 | Actor delegation anti-pattern, class-level mutable state on TurnContext, web server closure soup, lifecycle untested, inconsistent exceptions, `search_service` typing, `_materialize_directories` complexity |
| MEDIUM | 16 | Various performance, encapsulation, and design issues |
| LOW | 22 | Style, minor inefficiencies, edge cases |
| NIT | 12 | Cosmetic and convention issues |

The codebase is functional and demonstrates understanding of the domain, but needs a cleanup pass to address the HIGH issues before it would meet production standards.

