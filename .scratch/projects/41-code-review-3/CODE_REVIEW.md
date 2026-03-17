# Remora v2 — Ruthless Code Review

**Reviewer:** Senior Staff Engineer
**Date:** 2026-03-16
**Scope:** Full codebase review of `src/remora/` (6,923 LOC across 38 files)
**Verdict:** Mixed. Solid bones, but significant architectural debt, inconsistencies, and intern-level mistakes throughout.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Architecture & Design](#2-architecture--design)
3. [Core Module Reviews](#3-core-module-reviews)
   - 3.1 types.py
   - 3.2 config.py
   - 3.3 db.py
   - 3.4 node.py
   - 3.5 events/ (types, bus, store, dispatcher, subscriptions)
   - 3.6 graph.py
   - 3.7 actor.py
   - 3.8 turn_executor.py
   - 3.9 outbox.py
   - 3.10 prompt.py
   - 3.11 trigger.py
   - 3.12 runner.py
   - 3.13 services.py
   - 3.14 lifecycle.py
   - 3.15 kernel.py
   - 3.16 metrics.py
   - 3.17 externals.py
   - 3.18 workspace.py
   - 3.19 grail.py
   - 3.20 search.py
4. [Code Module Reviews](#4-code-module-reviews)
   - 4.1 discovery.py
   - 4.2 reconciler.py
   - 4.3 projections.py
   - 4.4 languages.py
   - 4.5 paths.py
5. [Surface Reviews](#5-surface-reviews)
   - 5.1 web/server.py
   - 5.2 lsp/server.py
   - 5.3 __main__.py (CLI)
6. [Test Infrastructure](#6-test-infrastructure)
7. [Cross-Cutting Concerns](#7-cross-cutting-concerns)
8. [Severity Summary](#8-severity-summary)

---

## 1. Executive Summary

**The Good:**
- Clean separation of concerns between event system, node graph, workspace, and surfaces
- Event-driven architecture is well-conceived with SQLite append-only log + in-memory bus
- Pydantic models are used consistently for data validation
- The `__all__` exports are maintained everywhere (good discipline)
- Error boundaries are marked with comments explaining intent (BLE001 suppressions are documented)
- Test coverage appears comprehensive (9,809 LOC of tests for 6,923 LOC of source)

**The Bad:**
- Dual-model problem: `CSTNode` and `Node` are redundant representations of the same thing
- God-file syndrome: `web/server.py` (722 LOC), `reconciler.py` (735 LOC), `turn_executor.py` (432 LOC), `externals.py` (385 LOC) are all too large
- Subscription cache is hand-rolled when a simple dict lookup would suffice
- `_discover` in `__main__.py` is `async` for no reason
- Private member access across module boundaries (`workspace_service._project_root` in web server)
- Inconsistent use of `tuple` vs `list` for immutable sequences in config
- Event type dispatch relies on string comparisons instead of the actual type system

**The Ugly:**
- `Outbox` claims "not a buffer" but has a `_sequence` counter that serves no purpose beyond incrementing
- `AgentTurnExecutor.__init__` takes 13 parameters — a sign the class is doing too much
- The `Actor.__init__` wraps `create_kernel` and `discover_tools` in lambdas solely to preserve test monkeypatch paths — this is the tail wagging the dog
- Module-level `_SCRIPT_SOURCE_CACHE` dict + `lru_cache` in `grail.py` is a Rube Goldberg caching setup
- `_expand_env_vars` is exported with a leading underscore (used in `turn_executor.py`)
- The `NodeStore.batch()` context manager issues a raw `ROLLBACK` SQL command instead of using proper transaction management

---

## 2. Architecture & Design

### 2.1 The Two-Model Problem (CSTNode vs Node)

`CSTNode` (discovery) and `Node` (graph) represent the same conceptual entity with nearly identical fields. The projection step (`projections.py`) manually copies fields between them. This is fragile, error-prone, and adds an entire layer of complexity for no benefit.

`CSTNode` has: `node_id, node_type, name, full_name, file_path, text, start_line, end_line, start_byte, end_byte, parent_id`
`Node` has: `node_id, node_type, name, full_name, file_path, source_code, source_hash, start_line, end_line, start_byte, end_byte, parent_id, status, role`

The only differences are: `text` vs `source_code`, and `Node` adds `source_hash`, `status`, `role`. This does not justify two separate model classes and a projection layer.

**Severity: HIGH** — Unnecessary complexity, bug surface, maintenance burden.

### 2.2 Event Type Resolution via Strings

Events use `event_type` strings for dispatch (e.g., `event.event_type == "AgentCompleteEvent"`). The subscription system stores patterns as JSON with string-based event type names. Meanwhile, the `EventBus` dispatches by Python `type()`. This dual dispatch mechanism is confusing and fragile — rename a class and the string-based subscriptions silently break.

**Severity: HIGH** — Silent breakage risk, violates DRY.

### 2.3 Service Container Pattern

`RuntimeServices` is a manual service container that constructs everything imperatively. The initialization order is implicit and fragile. The `reconciler` and `runner` are `None` until `initialize()` is called, requiring None-checks everywhere downstream. This is a code smell — services should be fully constructed or not exist.

**Severity: MEDIUM** — Null-safety issues, implicit lifecycle ordering.

### 2.4 The Outbox Abstraction

`Outbox` is described as "Not a buffer — events reach EventStore immediately on emit()." If it's not a buffer, it's just a wrapper that tags events with correlation_id. The `_sequence` counter increments but is never used for anything meaningful. The entire class could be replaced with a 3-line helper function.

**Severity: LOW** — Over-abstraction, but not harmful.

### 2.5 Workspace Locking Strategy

`AgentWorkspace` wraps every single operation in `async with self._lock`. This means all file I/O for an agent is serialized behind a single lock. Meanwhile, `CairnWorkspaceService` has its own `_lock` for workspace creation. This double-locking is overly conservative — the underlying Cairn workspace likely already handles concurrent access. At minimum, read operations should not need the write lock.

**Severity: MEDIUM** — Performance bottleneck under load.

---

## 3. Core Module Reviews

### 3.1 types.py (70 LOC) — CLEAN

Well-structured. `StrEnum` usage is correct. `STATUS_TRANSITIONS` dict is a good pattern. `serialize_enum` helper is sensible.

**One nit:** `validate_status_transition` returns `bool` but callers mostly ignore invalid transitions silently. Consider raising or at least logging.

### 3.2 config.py (303 LOC) — MIXED

**Good:**
- Pydantic `BaseSettings` with `frozen=True` is correct for config
- `_expand_env_vars` recursion is clean
- `_find_config_file` walking up directories is a nice UX touch

**Problems:**
- `_expand_env_vars` is a private function (leading underscore) but is imported and used in `turn_executor.py:16`. This violates the module boundary. Either make it public or don't use it externally.
- `BundleConfig.prompts` validator silently drops keys that aren't `"chat"` or `"reactive"`. This is a data-loss bug — if someone adds a new prompt mode, their config silently drops it with no warning.
- `bundle_overlays` default dict has `"file"` key, but `NodeType` has no `FILE` variant. Dead config.
- `SearchConfig.mode` validation via string comparison should be an enum.
- `SelfReflectConfig.max_turns` validator silently clamps to 1 instead of raising. User sets `max_turns: 0` and gets `1` with no warning — surprising behavior.

**Severity: MEDIUM**

### 3.3 db.py (21 LOC) — CLEAN

Minimal, correct. The `Connection` type alias re-export is a nice touch for downstream imports. `PRAGMA busy_timeout=5000` is sensible for WAL mode.

**One concern:** No `PRAGMA foreign_keys=ON`. If edges reference node_ids that get deleted, orphans can accumulate. (Though the code manually handles cascading deletes, this is fragile.)

### 3.4 node.py (46 LOC) — CLEAN BUT QUESTIONABLE

The model itself is fine. `to_row()` / `from_row()` is a reasonable serialization pattern.

**Problem:** `model_config = ConfigDict(frozen=False)` — the Node is mutable. This means any code holding a reference can mutate it, leading to stale/inconsistent state between the in-memory object and the database. Combined with the fact that `reconciler.py:454` does `node.parent_id = dir_node_id` (direct mutation after construction), this is a design smell.

**Severity: LOW** — works today but will cause bugs as complexity grows.

### 3.5 events/ Package

#### types.py (263 LOC) — BLOATED

23 event classes, most of which are simple data bags with 2-4 fields. This is fine as a pattern, but:

- `CustomEvent` overrides `to_envelope()` to keep payload at the top level, breaking the envelope contract that other events follow. Consumers cannot uniformly deserialize events.
- `ToolResultEvent` and `RemoraToolResultEvent` are suspiciously similar names with different schemas. This is confusing.
- `EventHandler = Callable[[Event], Any]` allows sync or async handlers. The bus then does `asyncio.iscoroutine(result)` to detect async. This is fragile — if someone returns an awaitable that isn't a coroutine, it won't be awaited.

**Severity: MEDIUM**

#### bus.py (99 LOC) — DECENT

Clean implementation. The `stream()` context manager is a nice API.

**Problem:** `_dispatch_handlers` creates a new `asyncio.Task` for every async handler on every event. For a high-throughput event bus, this is a lot of task creation overhead. Consider batching or using `loop.call_soon`.

**Problem:** The `stream()` method's `enqueue` callback uses `isinstance` checks in the hot path. For each event, it checks against every type in the filter set. This is O(n) per event per filter type.

**Severity: LOW**

#### store.py (205 LOC) — DECENT BUT OVERLOADED

The EventStore is doing four things: persistence, bus emission, trigger dispatch, and human-input future management. The future management (`create_response_future`, `resolve_response`, `discard_response_future`) is orthogonal to event storage and should be a separate component.

**Problem:** Every `append()` call does `await self._db.commit()` — one commit per event. Under burst event emission, this will bottleneck on SQLite write throughput. Should batch commits.

**Problem:** `get_events`, `get_events_for_agent`, and `get_events_after` all have duplicated JSON deserialization logic (`json.loads` for tags and payload). Should be a shared helper.

**Severity: MEDIUM**

#### dispatcher.py (57 LOC) — CLEAN

Simple and correct. The `router` property setter pattern is a bit unusual but works.

#### subscriptions.py (190 LOC) — OVER-ENGINEERED

The cache is a hand-rolled event_type-indexed dict. The `_cache_add`, `_cache_remove_subscription`, `_cache_remove_agent` methods manually maintain cache consistency. This is a classic "hand-rolled cache invalidation" antipattern.

**Problem:** `SubscriptionPattern.matches()` uses `getattr(event, "from_agent", None)` — runtime attribute lookup instead of typed field access. This bypasses the type system entirely.

**Problem:** Cache rebuilds load ALL subscriptions into memory. For a system with many agents and many subscriptions, this won't scale.

**Severity: MEDIUM**

### 3.6 graph.py (276 LOC) — SOLID

Well-structured SQLite-backed store. The `batch()` context manager is a good pattern.

**Problem:** `batch()` uses a bare `await self._db.execute("ROLLBACK")` instead of using aiosqlite's transaction support. This is fragile — if the connection is in auto-commit mode or a previous ROLLBACK already happened, this will error.

**Problem:** `transition_status` does an UPDATE followed by a SELECT if rowcount is 0. This is a TOCTOU race in concurrent scenarios — another coroutine could change the status between the UPDATE and SELECT. Should use RETURNING or handle atomically.

**Problem:** `list_nodes` builds SQL with f-strings (`f"SELECT * FROM nodes{where_clause}"`). While the parameters are properly parameterized, the f-string pattern for SQL construction is a maintenance hazard.

**Severity: MEDIUM**

### 3.7 actor.py (134 LOC) — MIXED

**Problem:** The constructor wraps `create_kernel`, `discover_tools`, and `extract_response_text` in lambdas:
```python
create_kernel_fn=lambda **kwargs: create_kernel(**kwargs),
discover_tools_fn=lambda workspace, capabilities: discover_tools(workspace, capabilities),
extract_response_text_fn=lambda result: extract_response_text(result),
```
The comment says "Keep these injected from actor module so existing test monkeypatch paths on remora.core.actor continue to work." This is test infrastructure driving production design — a red flag. The correct fix is to update the test monkeypatch paths, not add indirection in production code.

**Problem:** The `__all__` re-exports `Outbox`, `OutboxObserver`, `Trigger`, `TriggerPolicy`, `PromptBuilder`, `AgentTurnExecutor` — things that are imported from other modules. `actor.py` is acting as a public API aggregation module, but it shouldn't be. Each module should be imported directly by consumers.

**Severity: MEDIUM**

### 3.8 turn_executor.py (432 LOC) — TOO LARGE, TOO COMPLEX

This is the most complex file in the codebase and it shows.

**Problem:** `__init__` takes 13 keyword arguments. This is a classic "too many collaborators" smell. The class is orchestrating workspace, tools, kernel, prompt building, trigger policy, metrics, and event emission all in one place.

**Problem:** `_build_companion_context` is a 55-line static method that manually walks nested dicts with defensive `isinstance` checks everywhere. This suggests the companion data has no schema — it's untyped `Any` flowing through the system. Fragile.

**Problem:** `_read_bundle_config` catches `ValidationError` and falls back to defaults silently. This means broken config is invisible — the agent runs with wrong settings and nobody knows why.

**Problem:** Logger uses a hardcoded namespace `logging.getLogger("remora.core.actor")` — the comment says "Preserve historical logger namespace expected by runtime logs/tests." Tests should not dictate logger namespaces.

**Problem:** The `_resolve_maybe_awaitable` static method exists because `discover_tools_fn` might return a coroutine or a plain value. This ambiguity in the interface is the problem — fix the interface, don't patch around it.

**Severity: HIGH**

### 3.9 outbox.py (122 LOC) — OVER-ABSTRACTED

`Outbox` is a write-through wrapper with a sequence counter that nothing reads. `OutboxObserver` translates structured-agents events into Remora events via a chain of `isinstance` checks with defensive `getattr` everywhere. The `getattr(event, "model", "")` pattern suggests the structured-agents event types don't have stable APIs.

**Severity: LOW**

### 3.10 prompt.py (114 LOC) — CLEAN

Good separation. `turn_mode` logic is simple and clear.

**One nit:** `_event_content` uses `hasattr(event, "content")` — should use the type system.

### 3.11 trigger.py (76 LOC) — CLEAN

`TriggerPolicy` is well-designed with cooldown and depth limits. The cleanup mechanism is bounded and predictable.

**One nit:** `_DEPTH_TTL_MS = 5 * 60 * 1000` — this is 5 minutes. A constant named with `_MS` suffix that's computed from minutes is fine, but a comment would help.

### 3.12 runner.py (143 LOC) — SOLID

`ActorPool` is clean and well-structured. Lazy actor creation on first trigger is a good pattern.

**Problem:** `run_forever` does `await asyncio.sleep(1.0)` in a loop to periodically evict idle actors. This is a polling pattern — should use an asyncio.Event or similar to wake on demand.

**Problem:** `_evict_idle` has a hardcoded `max_idle_seconds=300.0` default. Should come from config.

**Severity: LOW**

### 3.13 services.py (97 LOC) — DECENT

Clean container pattern. Does what it says.

**Problem:** `reconciler` and `runner` are `None` until `initialize()` is called. Callers must null-check. This is a design smell — use the builder pattern or make initialization mandatory.

**Severity: LOW**

### 3.14 lifecycle.py (251 LOC) — SOLID

Good shutdown ordering with timeout-based cancellation. The `_release_file_log_handlers` cleanup is thorough.

**Problem:** The `shutdown()` method has a complex flow with multiple try/except blocks and conditional task management. The interaction between `services.close()` (which calls `runner.stop_and_wait()`) and the explicit `runner.stop_and_wait()` earlier means the runner is potentially stopped twice. The second call is likely a no-op, but it's confusing.

**Problem:** `_configure_file_logging` is passed as a callable from `__main__.py` instead of being a method on the lifecycle class. This indirection makes the code harder to follow.

**Severity: LOW**

### 3.15 kernel.py (59 LOC) — CLEAN

Thin wrapper. Does what it says. `extract_response_text` gracefully handles missing attributes.

### 3.16 metrics.py (50 LOC) — CLEAN

Simple dataclass. `snapshot()` is a reasonable serialization approach.

**Problem:** `cache_hit_rate` calculation includes both `workspace_provisions_total` and `workspace_cache_hits` in the denominator. This means the rate is `hits / (provisions + hits)`, which is correct. Good.

**One nit:** All counters are bare `int` fields with no thread-safety. In an async context this is fine (single-threaded event loop), but it's worth a comment noting this assumption.

### 3.17 externals.py (385 LOC) — TOO LARGE

`TurnContext` is a god-object that exposes 27 capabilities to agent tools. This is the entire external API surface for agents, and it's all in one class.

**Problem:** `search_content` does a linear scan of ALL workspace files and ALL lines in each file. For large workspaces, this is O(files * lines). No indexing, no early termination beyond the max_matches cap.

**Problem:** `_resolve_broadcast_targets` uses `"siblings"` and `"file:"` prefix patterns — custom DSL for broadcast targeting with no documentation or formal grammar.

**Problem:** `_allow_send_message` uses a `deque` keyed by `self.node_id` in `self._send_message_timestamps`. But `TurnContext` is created fresh per-turn (in `_prepare_turn_context`), so the rate limiter state is always empty on each turn. The rate limiting only works within a single turn, not across turns. If the intent is cross-turn rate limiting, this is broken.

**Severity: HIGH** — The rate limiter bug is a real behavioral issue.

### 3.18 workspace.py (233 LOC) — DECENT

`AgentWorkspace` is a clean facade over Cairn's `Workspace`. `CairnWorkspaceService` manages lifecycle well.

**Problem:** `_safe_id` uses `hashlib.sha256` truncated to 10 hex chars (40 bits). Collision probability becomes non-trivial above ~1M nodes (birthday paradox). Should use at least 16 chars.

**Problem:** `_merge_dicts` and `_bundle_template_fingerprint` are module-level functions defined AFTER the `__all__` export. This is a style inconsistency — private helpers should be above or grouped with their callers.

**Severity: LOW**

### 3.19 grail.py (220 LOC) — OVER-ENGINEERED CACHING

The caching setup is a Rube Goldberg machine:
1. `_SCRIPT_SOURCE_CACHE` — module-level dict mapping `(hash, name)` to source text
2. `_cached_script` — `@lru_cache` that reads from `_SCRIPT_SOURCE_CACHE`, writes to temp file, loads via grail
3. `_load_script_from_source` — populates `_SCRIPT_SOURCE_CACHE` then calls `_cached_script`
4. `_evict_source_cache` — manual LRU eviction on the dict

This two-tier cache (dict + lru_cache) is needlessly complex. The `_cached_script` function reads from the dict cache, writes to a temp file, and parses it — every cache miss involves filesystem I/O to a temporary directory. A simpler approach: cache the parsed `GrailScript` directly in a single LRU dict.

**Problem:** `_evict_source_cache` evicts by iteration order (oldest first), but `_SCRIPT_SOURCE_CACHE` is a regular dict, not an `OrderedDict`. In Python 3.7+, dicts maintain insertion order, so this works, but it's relying on an implementation detail without documentation.

**Problem:** `discover_tools` accesses `workspace._agent_id` via `getattr` — private attribute access across module boundaries.

**Severity: MEDIUM**

### 3.20 search.py (271 LOC) — DECENT

Clean protocol + implementation separation. Graceful degradation when embeddy is unavailable.

**Problem:** `search()` and `find_similar()` have duplicated result-mapping logic (10 lines each) for the local mode. Should be a shared helper.

**Problem:** The local mode initialization imports `embeddy` modules inside `_initialize_local()`. This is fine for optional deps, but the remote mode also does a conditional import at module level (`from embeddy.client import EmbeddyClient`). Inconsistent import strategy.

**Severity: LOW**

---

## 4. Code Module Reviews

### 4.1 discovery.py (236 LOC) — SOLID

Good use of tree-sitter. The deduplication via `_node_key` tuples and parent resolution is well thought out.

**Problem:** Multiple `@lru_cache` decorators with no invalidation strategy. The `_get_language_registry` cache is `maxsize=1` — effectively a singleton. The `_load_query` cache is `maxsize=64` — fine for a bounded set of query files. But `_get_parser` is `maxsize=16`, which means if you have more than 16 languages, parsers get evicted and recreated. Not a real problem today (3 languages), but the caching strategy is implicit.

**Problem:** `clear_caches()` exists "for tests" — production code carrying test-only infrastructure.

**Severity: LOW**

### 4.2 reconciler.py (735 LOC) — TOO LARGE, HIGHEST COMPLEXITY

This is the largest source file and the most complex. It handles:
- Full scan reconciliation
- Incremental file change detection
- Directory hierarchy projection
- Virtual agent materialization
- Bundle provisioning
- Subscription registration
- File watching via watchfiles
- Search indexing
- Lock management with generations

**This file is doing at least 4 distinct responsibilities:**
1. File watching and change detection
2. Node graph reconciliation (upsert/delete)
3. Directory hierarchy management
4. Virtual agent lifecycle

**Problem:** `_reconcile_file` calls `discover()` for a single file, which creates a `walk_source_files` call, which creates a full path resolution. This is heavy for a single-file incremental update.

**Problem:** `_upsert_directory_node` takes 6 parameters plus `self` and has complex conditional logic for new vs existing vs changed directories. This method is doing too much.

**Problem:** The file lock management with "generations" and `_evict_stale_file_locks` is a custom GC mechanism. This complexity suggests the locking strategy is wrong — if you need a garbage-collected lock pool, reconsider the concurrency model.

**Problem:** `_stop_event()` creates a `threading.Event` bridged to asyncio via a checker task that polls `self._running` every 0.5s. This is a polling bridge — fragile and adds latency.

**Severity: HIGH** — This file needs to be decomposed.

### 4.3 projections.py (82 LOC) — FINE

Simple transformation from CSTNode to Node. Clean.

**Problem:** Duplicates the "system + role bundle" template resolution logic that also exists in `reconciler._provision_bundle`. The comment `# System tools/config are always included; role bundle overlays them.` appears 3 times across 2 files — copy-paste.

**Severity: LOW**

### 4.4 languages.py (157 LOC) — CLEAN

Plugin system is well-designed. The `LanguagePlugin` protocol is clean.

**One nit:** `PythonPlugin._has_class_ancestor` checks for `decorated_definition` containing a `class_definition` child, which handles `@decorator\nclass Foo:` correctly. Good attention to detail.

**One nit:** `del ts_node` in `MarkdownPlugin.resolve_node_type` is unnecessary — just use `_ts_node` parameter name.

### 4.5 paths.py (74 LOC) — CLEAN

Simple and correct. The `ignored()` function's pattern matching is reasonable.

**One concern:** `walk_source_files` does `root.rglob("*")` which can be slow on large directory trees. No parallelism or lazy iteration.

---

## 5. Surface Reviews

### 5.1 web/server.py (722 LOC) — TOO LARGE

**This is the largest file in the codebase** and it's a monolithic handler dump.

**Problem:** All 17 route handlers are top-level functions in a single file. Each handler reaches into `WebDeps` for its dependencies. This is a flat, unstructured design — no grouping by concern (node APIs, event APIs, proposal APIs, SSE).

**Problem:** `_resolve_within_project_root` and `_workspace_path_to_disk_path` access `workspace_service._project_root` — a private attribute. This violates encapsulation.

**Problem:** `_INDEX_HTML` is loaded at module import time (`_STATIC_DIR / "index.html").read_text(...)`). If the file doesn't exist (e.g., during testing or packaging), the import fails with an unhelpful FileNotFoundError.

**Problem:** The SSE `event_generator` creates and cancels asyncio Tasks in a tight loop (`stream_task = asyncio.create_task(stream_iterator.__anext__())`). Each event involves creating a task, waiting, and potentially cancelling it. This is expensive.

**Problem:** `RateLimiter` is defined in the web module but duplicates the concept in `externals.py:_allow_send_message`. Different implementations of the same pattern.

**Severity: HIGH**

### 5.2 lsp/server.py (343 LOC) — DECENT

Good use of pygls. The `RemoraLSPHandlers` dataclass for test access is a pragmatic pattern.

**Problem:** `create_lsp_server` uses nested function definitions for all handlers (`code_lens`, `hover`, etc.) inside the factory function. This means every call to `create_lsp_server` re-creates all handler functions. For a singleton server this is fine, but it's an unusual pattern.

**Problem:** The standalone mode (`create_lsp_server_standalone`) lazily opens stores on first handler call. If the DB doesn't exist or is corrupted, the error surfaces as a handler failure, not a startup failure. Poor error UX.

**Problem:** `_uri_to_path` doesn't handle Windows UNC paths or percent-encoded characters beyond `unquote`.

**Severity: LOW**

### 5.3 __main__.py (337 LOC) — MIXED

**Problem:** `_discover` is an `async def` that does no async work — `discover_nodes` is synchronous. The `asyncio.run()` wrapper is unnecessary overhead.

**Problem:** `_configure_logging` and `_configure_file_logging` are module-level functions that mutate global logger state. This makes testing difficult and means log configuration is implicit.

**Problem:** `_ContextFilter.filter` always returns `True` — it's not filtering, it's injecting defaults. The name is misleading. Should be `_ContextDefaultsInjector` or similar.

**Problem:** `total_stats["errors"]` in `_index` is typed as `list` but the type annotation for the dict uses string values. This is a type error that pyright likely misses because the dict is `dict[str, ...]` with mixed value types.

**Severity: LOW**

---

## 6. Test Infrastructure

**Good:**
- 9,809 LOC of tests for 6,923 LOC of source (1.4:1 ratio)
- `factories.py` provides clean `make_node`, `make_cst` helpers
- `doubles.py` with `RecordingOutbox` is a proper test double
- `conftest.py` is minimal and focused

**Problems:**
- `test_actor.py` is 1,266 lines — the largest test file. This suggests `Actor` and `AgentTurnExecutor` are undertested at the unit level and over-tested at the integration level.
- `test_web_server.py` is 910 lines — the web server has no route-level unit tests, just full-app integration tests.
- The `cleanup_closed_root_stream_handlers` autouse fixture in conftest suggests a global state leak from log handler management. This is a symptom of the global logging configuration problem.

**Severity: LOW** — Tests exist and appear to pass. The structure could be better.

---

## 7. Cross-Cutting Concerns

### 7.1 Error Handling Philosophy

The codebase uses a "catch everything at boundaries" approach with `except Exception` and `# noqa: BLE001` comments. This is documented and intentional, which is good. However:

- Some error boundaries are too broad. `grail.py:213` catches ALL exceptions when loading a tool script. A `SyntaxError` in a .pym file gets the same treatment as an `IOError` from a missing file.
- Error boundaries consistently log but never surface errors to the user via events. An agent whose tools all fail to load gets no indication of why.

### 7.2 Async Consistency

Most of the codebase is properly async, but there are inconsistencies:
- `discover()` in `discovery.py` is synchronous (does file I/O)
- `_collect_file_mtimes()` in `reconciler.py` is synchronous (does file stat calls)
- `_parse_file()` in `discovery.py` is synchronous (reads files)

These synchronous file I/O operations run in the async event loop, blocking it during large scans.

### 7.3 Security

- CSRF middleware only checks `Origin` header — doesn't check `Referer` or use tokens.
- No authentication on any API endpoint. The web server binds to localhost by default, which is reasonable, but the `--bind 0.0.0.0` option exposes an unauthenticated API.
- `_workspace_path_to_disk_path` has path traversal protection via `.relative_to()`, which is good.
- `api_chat` and `api_respond` accept arbitrary JSON from the network with minimal validation.

### 7.4 Performance

- Every event append commits to SQLite individually
- Event bus creates asyncio.Tasks per handler per event
- SSE stream creates/cancels tasks per event
- `search_content` does linear scans of all files
- Discovery is synchronous and blocks the event loop

---

## 8. Severity Summary

| Severity | Count | Key Issues |
|----------|-------|------------|
| **HIGH** | 5 | CSTNode/Node duplication, string-based event dispatch, turn_executor complexity, reconciler size, web server monolith, externals rate limiter bug |
| **MEDIUM** | 8 | Config silent drops, EventStore per-event commits, subscription cache, graph batch/ROLLBACK, actor lambda wrappers, grail caching, private attribute access, service container nullability |
| **LOW** | 10+ | Outbox over-abstraction, metrics thread-safety assumption, discovery caches, minor style inconsistencies, async consistency |

**Overall Assessment: C+**

The architecture is sound in concept but the implementation has accumulated significant debt. The event-driven reactive pattern is well-chosen for the domain. However, the intern left behind several files that need decomposition (reconciler, web server, turn executor, externals), a dual-model problem that adds complexity for no benefit, and string-based dispatch that's a ticking time bomb. The test suite is comprehensive in coverage but poorly structured. The codebase needs a focused refactoring pass before it can scale to more complex use cases.
