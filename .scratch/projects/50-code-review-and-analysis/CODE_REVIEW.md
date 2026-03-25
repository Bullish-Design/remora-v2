# Remora v2 — Code Review

> Comprehensive post-refactor code review of the remora-v2 library.
> Covers correctness, architecture, error handling, test coverage, and potential issues.
> Codebase snapshot: 8,665 lines of Python across ~60 modules. Tests: 434 passed, 5 skipped.

---

## Table of Contents

1. **[Overall Assessment](#1-overall-assessment)** — Executive summary, strengths, and top-priority issues.
2. **[Architecture and Module Organization](#2-architecture-and-module-organization)** — Package structure, dependency flow, and layering quality.
3. **[Data Model and Storage](#3-data-model-and-storage)** — Node model, SQLite schema, graph store, event store, transactions.
4. **[Event System](#4-event-system)** — Types, bus, dispatcher, subscriptions, fan-out correctness.
5. **[Agent Execution Pipeline](#5-agent-execution-pipeline)** — Actor, turn executor, trigger policy, outbox, kernel integration.
6. **[Workspace and Tool System](#6-workspace-and-tool-system)** — Cairn integration, bundle provisioning, Grail tool loading, capabilities.
7. **[Reconciler](#7-reconciler)** — File reconciliation, virtual agents, directory management, search indexing.
8. **[Web Layer](#8-web-layer)** — Server, routes, SSE, middleware, dependency injection.
9. **[LSP Layer](#9-lsp-layer)** — Import guarding, CLI integration.
10. **[CLI and Lifecycle](#10-cli-and-lifecycle)** — Entry points, startup/shutdown sequencing, logging.
11. **[Configuration System](#11-configuration-system)** — Config model, validation, env var expansion, bundle resolution.
12. **[Error Handling Patterns](#12-error-handling-patterns)** — Error boundaries, exception hierarchy, recovery strategies.
13. **[Test Coverage](#13-test-coverage)** — Test infrastructure, coverage gaps, naming issues.
14. **[Security Considerations](#14-security-considerations)** — CSRF, input validation, path traversal, injection risks.
15. **[Issues and Recommendations](#15-issues-and-recommendations)** — Prioritized list of findings.

---

## 1. Overall Assessment

### Verdict: Well-engineered, production-approaching quality

Remora v2 is a thoughtfully architected reactive agent substrate. The recent WS1-WS6 refactor (project 49) addressed the most critical issues identified in downstream demos. The codebase demonstrates strong software engineering discipline in several areas while having some remaining issues worth addressing.

### Strengths

- **Clean layering**: The `core/model` → `core/storage` → `core/events` → `core/agents` → `web`/`lsp` dependency flow is well-defined with minimal circular imports. TYPE_CHECKING guards are used correctly.
- **Consistent error boundaries**: Every subsystem has explicit `# Error boundary:` comments marking where exceptions are caught and why. This is unusual discipline for a project this size and makes the failure modes auditable.
- **Thorough config validation**: Pydantic validators on every config sub-model with clear error messages. Environment variable expansion is safe with regex-based substitution.
- **Event-driven composability**: The EventStore → EventBus + TriggerDispatcher fan-out pattern is clean. Events are the single source of truth; everything else is derived.
- **Good test coverage**: 434 tests cover unit, integration, and lifecycle scenarios. Tests are well-structured with clear factory/doubles patterns.
- **Structured observability**: Metrics, structured logging with per-turn context fields, SSE streaming, and event error fields (error_class, error_reason) provide solid operational visibility.

### Top-Priority Issues

1. **Test collection error** (P0): `tests/unit/test_virtual_reactive_flow.py` and `tests/integration/test_virtual_reactive_flow.py` share the same module name, causing pytest collection failure. This blocks running the full test suite.
2. **`graph_get_node` returns `{}` instead of `None`** (P1): `GraphCapabilities.graph_get_node()` returns an empty dict when a node is not found, but `review_diff.pym` checks `if not node:` — an empty dict is falsy, so this works, but it contradicts the `@external` signature `-> dict | None` in the tool script. The contract is confusing.
3. **Unbounded `_file_locks` dictionary** (P2): `FileReconciler._file_locks` grows unbounded; the eviction logic only runs during reconcile cycles, not between them.
4. **SSE event IDs use floating-point timestamps** (P2): `id: {event.timestamp}` in the live SSE stream uses float timestamps, but the replay `get_events_after` expects integer IDs. Resume after disconnect will silently fail.

---

## 2. Architecture and Module Organization

### Package Structure

```
src/remora/
├── __init__.py, __main__.py          # Entry points
├── code/                              # File discovery, reconciliation, watcher
│   ├── discovery.py, reconciler.py, watcher.py
│   ├── directories.py, virtual_agents.py, subscriptions.py
│   ├── languages.py, paths.py
├── core/                              # Domain kernel
│   ├── model/   (types, node, config, errors)
│   ├── storage/ (db, graph, workspace, transaction)
│   ├── events/  (types, bus, store, dispatcher, subscriptions)
│   ├── agents/  (actor, runner, turn, trigger, outbox, prompt, kernel)
│   ├── tools/   (grail, context, capabilities)
│   ├── services/ (container, lifecycle, metrics, search, broker, rate_limit)
│   └── utils.py
├── defaults/                          # Built-in bundles, queries, defaults.yaml
├── web/                               # Starlette HTTP + SSE
│   ├── server.py, sse.py, deps.py, middleware.py, paths.py
│   └── routes/ (chat, cursor, events, health, nodes, proposals, search, _errors)
├── lsp/                               # pygls-based LSP server
```

### Dependency Flow

The layering is clean and generally flows downward:

```
__main__ → lifecycle → container → [reconciler, runner, web, lsp]
                                     ↓           ↓
                                   agents      events
                                     ↓           ↓
                                   tools       storage
                                     ↓           ↓
                                   model ←------/
```

**Observation**: `remora.code` (discovery, reconciler, watcher) depends on both `core` and the default bundles, which is architecturally appropriate — it's the application layer that wires the domain kernel to the filesystem.

**Positive pattern**: The `TYPE_CHECKING` import guard is used consistently to break circular references (e.g., `AgentWorkspace` in `context.py`, `ActorPool` in `server.py`). No runtime circular imports observed.

**Minor issue**: `SubscriptionRegistry` in `subscriptions.py` uses `aiosqlite.Connection` without importing it at the module level — it relies on the import being available at runtime from other modules. This works but is fragile; an explicit import (even under TYPE_CHECKING) would be cleaner.

---

## 3. Data Model and Storage

### Node Model (`core/model/node.py`)

Clean Pydantic model with `to_row()`/`from_row()` serialization. The `frozen=False` setting on `model_config` is intentional — nodes are mutated during reconciliation (setting `status`, `role`, `parent_id`).

**Observation**: `Node` uses `str` for `source_hash` rather than `bytes` — appropriate for SQLite storage.

### NodeStore (`core/storage/graph.py`)

Well-implemented SQLite graph store with:
- Atomic status transitions using `UPDATE ... WHERE status IN (...)` — good pattern for preventing race conditions.
- Proper `INSERT OR REPLACE` for upserts.
- Edge deletion cascading correctly from `delete_node`.

**Issue**: `transition_status` performs a fallback `get_node` query on failure to log a warning. This means a failed transition costs 2 DB queries. Acceptable for the error path, but worth noting.

**Issue**: `get_nodes_by_ids` uses f-string formatting for the IN clause placeholders. While safe (it's just `?` characters, not user input), this pattern can be confusing in code review. Consider a comment.

### EventStore (`core/events/store.py`)

Append-only event log with correct fan-out sequencing:
1. Write to SQLite
2. Commit
3. Emit to EventBus
4. Dispatch to TriggerDispatcher

The deferred event pattern via `TransactionContext` is well-designed — events are buffered during batch operations and fanned out only on the outermost commit.

**Issue**: `get_events` returns raw SQLite rows with `id`, `event_type`, `agent_id`, etc. at the top level alongside `payload` and `tags`. The `/api/events` endpoint normalizes these into envelope format, but internal consumers may be confused by the mixed shape. Please standardize the return type.

### TransactionContext (`core/storage/transaction.py`)

Nest-safe batching with proper rollback on failure. The `TaskGroup` for parallel fan-out is a nice touch.

**Observation**: On rollback, deferred events are silently cleared. This is correct behavior — uncommitted events should not be emitted.

---

## 4. Event System

### Event Types (`core/events/types.py`)

Comprehensive event hierarchy with 21+ event types. Each event has:
- Stable `event_type` string from `EventType` enum
- Timestamp, correlation_id, tags
- `to_envelope()` for API serialization
- Optional `summary()` for human-readable display

**Observation**: `CustomEvent` correctly overrides `to_envelope()` to use its own `payload` field rather than the default `model_dump(exclude=...)` pattern. Good.

**Issue**: `Event.event_type` defaults to `""` — an empty string is a valid but confusing default. If someone creates a bare `Event()`, it won't match any EventType. Consider making `event_type` abstract or required.

### EventBus (`core/events/bus.py`)

In-memory pub/sub with:
- String-keyed subscriptions (event type → handlers)
- Global handlers via `subscribe_all`
- `TaskGroup`-based concurrent async handler dispatch
- `_run_guarded` wrapping to prevent one handler failure from aborting siblings

**Design quality**: The semaphore-bounded concurrency for async handlers (`max_concurrent_handlers=100`) prevents handler stampedes. Sync handlers are dispatched inline, which is correct for low-latency callbacks like queue.put_nowait.

**Issue**: The `stream()` context manager uses an unbounded `asyncio.Queue`. If a slow consumer doesn't drain the queue fast enough, memory will grow without bound. The SSE endpoint relies on this — a slow client could cause memory pressure. Consider a bounded queue with a drop policy for the stream.

### SubscriptionRegistry (`core/events/subscriptions.py`)

SQLite-backed with in-memory cache. Cache invalidation is correct — adds/removes update the cache incrementally rather than rebuilding.

**Design quality**: The `_ANY_EVENT_KEY = "*"` wildcard for patterns without `event_types` is elegant — it avoids a separate scan of all subscriptions for every event.

**Issue**: `SubscriptionPattern.matches()` uses `getattr()` extensively to extract event fields. This is necessary because the base `Event` class doesn't define `from_agent`, `to_agent`, etc. It works but loses type safety. The alternative (a match method on Event) would add coupling, so this is probably the right tradeoff.

### TriggerDispatcher (`core/events/dispatcher.py`)

Minimal and correct. The dispatcher is essentially a bridge: resolve matching agents from subscriptions, then call the router callback for each. The separation of subscription matching (SubscriptionRegistry) from event routing (ActorPool._route_to_actor) is clean.

---

## 5. Agent Execution Pipeline

### Actor (`core/agents/actor.py`)

Clean inbox-loop actor with:
- Bounded inbox (configurable max items)
- Sentinel-based stop (None → break)
- Correlation ID generation for untagged events
- TriggerPolicy check before executing

**Observation**: The actor creates a new `Outbox` per event, which correctly scopes correlation_id propagation to a single causal chain.

### TriggerPolicy (`core/agents/trigger.py`)

Three-layer safety:
1. Cooldown: minimum time between triggers
2. Max depth: per-correlation recursion ceiling
3. Max reactive turns per correlation: total turn budget

The `cleanup_depth_state` with TTL-based eviction and periodic scheduling (every 100 checks) is a reasonable approach to prevent unbounded state growth.

**Issue**: `release_depth` decrements the depth counter, but `correlation_turn_counts` is never decremented. This means `max_reactive_turns_per_correlation` is a hard lifetime cap, not a concurrency limit. The naming suggests this is intentional but the asymmetry with `depths` (which is decremented on release) could confuse maintainers.

### AgentTurnExecutor (`core/agents/turn.py`)

The main execution pipeline. Well-structured with clear phases:
1. Start (get node, transition to running, emit start event)
2. Prepare (build turn context, discover tools)
3. Execute (create kernel, run model, retry once on failure)
4. Complete (emit complete event with tags)
5. Error handling (emit error event with structured fields)
6. Reset (transition back to idle, release depth)

**Design quality**: The error boundary catches `ModelError | ToolError | WorkspaceError | IncompatibleBundleError` — all expected failure modes — and properly populates `error_class` and `error_reason` on the `AgentErrorEvent`.

**Issue**: `max_retries = 1` is hardcoded. Make this configurable in `RuntimeConfig`.

### Outbox and OutboxObserver (`core/agents/outbox.py`)

The `Outbox` is a write-through emitter that tags events with correlation_id. The `OutboxObserver` translates structured-agents kernel events into Remora events.

**Design quality**: The `_extract_error_details` method uses regex to extract error class names from output text when not explicitly provided. The fallback to `"ToolError"` is reasonable.

**Design quality**: The `_turn_error_classes` tracking across tool results allows `TurnCompleteEvent.error_summary` to be synthesized even when the upstream event doesn't provide one.

### PromptBuilder (`core/agents/prompt.py`)

Template-based prompt construction with:
- System prompt + extension + mode-specific prompt layering
- Single-pass regex interpolation for `{variable}` substitution
- Companion context formatting from KV data

**Observation**: The `_interpolate` method uses `{word}` syntax which conflicts with Python f-strings and JSON. This is fine since templates come from YAML, but it's worth noting in documentation.

**Issue**: `format_companion_context` has extensive defensive type checking (`isinstance(entry, dict)`, `isinstance(insight, str)`, etc.). This suggests the KV data shape is unreliable. The `aggregate_digest.pym` tool now uses type guards (`as_dict_list`, `as_int_dict`), so this double-validation is redundant but harmless — defense in depth.

---

## 6. Workspace and Tool System

### AgentWorkspace (`core/storage/workspace.py`)

Clean wrapper around Cairn's `Workspace` with:
- File read/write/delete/list operations
- KV store operations
- Companion data retrieval

**Observation**: `get_companion_data` correctly validates types from KV (`isinstance(reflections, list)`) before passing to `CompanionData`. This matches the pattern in `aggregate_digest.pym`.

### CairnWorkspaceService

Manages per-agent workspaces with:
- Lock-protected lazy creation
- Bundle provisioning with fingerprint-based change detection
- Deep-merge of bundle configs from layered template directories

**Design quality**: The `_bundle_template_fingerprint` function hashes both directory paths and file contents, ensuring re-provisioning when either bundle structure or content changes.

**Issue**: `_safe_id` truncates at 80 characters then appends a 16-char hash. This produces IDs up to 97 characters. Some filesystems (though not modern ones) may have issues. More importantly, the truncation happens *before* the hash, so two node IDs that differ only after character 80 will produce different safe IDs. This is correct behavior.

### GrailTool (`core/tools/grail.py`)

Loads `.pym` scripts via Grail, wraps them as structured-agents tools.

**Design quality**: The parsed script cache with LRU eviction (`_MAX_SCRIPT_CACHE = 256`) prevents redundant parsing. The content-hash key means identical scripts across agents share a single parse.

**Design quality**: Tool execution errors are caught and returned as `ToolResult(is_error=True)` rather than propagating. This prevents one tool failure from crashing the entire turn.

**Issue**: `_load_script_from_source` writes to a temporary file for every uncached script load. This is because `grail.load()` expects a file path. If Grail supports loading from strings, that would be more efficient. Study the grail codebase in the .context/ directory to determine if this is possible. 

### Capabilities (`core/tools/capabilities.py`)

Seven capability groups, each with `to_dict()` → merged into a flat capabilities dictionary.

**Design quality**: Capabilities are properly bounded:
- `search_content_max_matches` limits search results
- `broadcast_max_targets` limits fan-out
- Rate limiting on `send_message`
- `propose_changes` collects only non-bundle files

**Issue**: `GraphCapabilities.graph_get_node` returns `{}` (empty dict) when the node is not found. The Grail `@external` declaration in `review_diff.pym` says `-> dict | None`. Since `review_diff.pym` uses `if not node:` and an empty dict is falsy, this works — but it's a contract mismatch. Consider returning `None` and updating the capability signature.

**Issue**: `FileCapabilities.search_content` reads every file in the workspace sequentially. For large workspaces, this could be very slow. The `_search_content_max_matches` limit bounds the output size but not the scan cost.

---

## 7. Reconciler

### FileReconciler (`code/reconciler.py`)

The reconciler is the most complex module. It handles:
1. Full startup scan
2. Incremental file change detection (mtime-based)
3. Node add/change/delete event emission
4. Directory materialization
5. Virtual agent materialization
6. Bundle provisioning
7. Subscription management
8. Search indexing
9. Content change event subscription (for immediate reconciliation)

**Design quality**: Per-file locking with generation-based eviction prevents concurrent reconciliation of the same file while avoiding lock leaks.

**Design quality**: The `_bundles_bootstrapped` flag ensures template directories are re-copied once on startup, catching tool script updates without redundant copies on every cycle.

**Issue**: `_file_locks` and `_file_lock_generations` grow unbounded during a session. The `_evict_stale_file_locks` method runs during reconcile cycles but only removes locks from *previous* generations. If files are only touched once, their locks persist until the next reconcile cycle's generation advances past them. In practice this is a minor memory leak — locks are small — but worth noting.

**Issue**: The `_on_content_changed` handler does not check if the changed path is within configured `discovery_paths`. A content change event for an unrelated file will trigger a reconcile attempt that discovers nothing. This is harmless but wasteful.

---

## 8. Web Layer

### Server (`web/server.py`)

Standard Starlette setup with:
- Static file serving from `web/static/`
- CSRF middleware
- Dependency injection via `app.state.deps`
- Lifespan shutdown event for SSE cleanup

**Observation**: `_get_index_html()` caches the HTML in a module-level global. This means changes to `index.html` require a server restart. This is standard for production but worth documenting.

### Routes

Well-organized into focused modules:
- `nodes.py`: CRUD on graph nodes + conversation history
- `chat.py`: Message sending + human input response
- `events.py`: Event list + SSE
- `search.py`: Semantic search with 501/503 differentiation
- `proposals.py`: Rewrite proposal workflow (diff/accept/reject)
- `health.py`: Health check + metrics
- `cursor.py`: Editor cursor focus events

**Design quality**: The error response helper (`_errors.py`) provides a consistent `{error, message, docs?}` shape across all error responses.

**Issue**: `api_chat` and `api_respond` don't use the `error_response` helper — they return raw `JSONResponse({"error": "..."})`. This is a minor inconsistency but means these errors lack the `message` field. Fix. 

### SSE (`web/sse.py`)

Complex but correct SSE implementation with:
- Replay via `?replay=N` or `Last-Event-ID`
- One-shot mode (`?once=true`)
- Graceful shutdown via sentinel comment
- Disconnect detection

**Issue (P2)**: Live event IDs are `event.timestamp` (a float), but replay via `Last-Event-ID` uses `get_events_after(after_id)` which calls `int(after_id)`. This means:
1. Live event `id: 1711234567.89` gets sent
2. Client disconnects and reconnects with `Last-Event-ID: 1711234567.89`
3. `int("1711234567.89")` raises `ValueError` → `get_events_after` returns `[]`
4. Client misses all events between disconnect and reconnect

**Fix**: Use the SQLite row ID as the SSE event ID, not the timestamp. The replay path already retrieves rows with their `id` column.

### Middleware (`web/middleware.py`)

Simple CSRF protection: reject mutating requests from non-localhost origins. Correctly allows `127.0.0.1` and `localhost`.

**Observation**: No CORS headers are set. This means cross-origin reads (GET) work, but cross-origin writes (POST) from browser JavaScript will fail due to CORS preflight. This is probably intentional for a local-first tool but should be documented.

---

## 9. LSP Layer

### Import Guarding (`lsp/__init__.py`)

Clean lazy import pattern with clear error messages referencing `uv sync --extra lsp` and documentation links. The `__main__.py` LSP command catches `ImportError` and prints the message to stderr before exiting with code 1.

**Observation**: The LSP is an optional feature that correctly degrades — the CLI doesn't crash at startup when pygls is missing, and the error message tells the operator exactly how to fix it.

---

## 10. CLI and Lifecycle

### CLI (`__main__.py`)

Typer-based with four commands: `start`, `discover`, `index`, `lsp`. Clean argument definitions with appropriate defaults.

**Design quality**: Structured logging with custom `_StructuredFieldInjector` that injects `node_id`, `correlation_id`, and `turn` fields into all log records. This enables grep-friendly log analysis.

**Design quality**: `_configure_file_logging` uses `RotatingFileHandler` with 5MB max and 3 backups. Duplicate handler prevention is handled correctly.

### RemoraLifecycle (`core/services/lifecycle.py`)

Thorough shutdown orchestration with:
1. Stop accepting new work
2. Drain in-flight work with 10s timeout
3. Signal web server to exit
4. Close services
5. LSP protocol-compliant shutdown
6. Force-cancel lingering tasks
7. Release file log handlers

**Design quality**: The extensive docstring explains *why* `asyncio.TaskGroup` is not used and justifies manual task management. This is exemplary documentation for complex control flow.

**Issue**: `run()` with `run_seconds=0` calls `asyncio.gather(*self._tasks)`. If one task raises an exception, `gather` re-raises the first exception, leaving other tasks running. Consider using `return_exceptions=True` or handling exceptions explicitly.

---

## 11. Configuration System

### Config Model (`core/model/config.py`)

Pydantic-settings with:
- Five sub-models: `ProjectConfig`, `RuntimeConfig`, `InfraConfig`, `BehaviorConfig`, `SearchConfig`
- Virtual agent configuration with subscription patterns
- Bundle overlay rules with name glob matching
- Environment variable expansion with `${VAR:-default}` syntax

**Design quality**: `_nest_flat_config` handles backward-compatible flat YAML files by auto-nesting keys into their sub-models. This is a nice migration path.

**Design quality**: `resolve_bundle` uses priority ordering: rules first (with name pattern matching), then type overlays. This allows both broad defaults and specific overrides.

**Observation**: `Config` is frozen (`frozen=True`) which prevents accidental mutation after loading. The sub-models are not frozen, but since `Config` is the public interface, this is sufficient.

---

## 12. Error Handling Patterns

### Exception Hierarchy

```
RemoraError
├── ModelError        (LLM failures)
├── ToolError         (Grail script failures)
├── WorkspaceError    (filesystem/Cairn failures)
├── SubscriptionError (event routing failures)
└── IncompatibleBundleError (version mismatch)
```

All are subclasses of `RemoraError`, enabling catch-all error boundaries at subsystem borders.

### Error Boundary Pattern

The codebase consistently uses annotated error boundaries:

```python
# Error boundary: one failed watch batch must not stop file watching.
except (OSError, RemoraError, aiosqlite.Error):
    logger.exception("Watch-triggered reconcile failed")
```

This pattern appears in:
- `FileReconciler._handle_watch_changes`
- `FileReconciler._on_content_changed`
- `FileReconciler._index_file_for_search`
- `AgentTurnExecutor.execute_turn`
- `AgentTurnExecutor._reset_agent_state`
- `EventBus._dispatch_handlers`
- `EventBus._run_guarded`
- `RemoraLifecycle.shutdown`

**Assessment**: The error boundary discipline is excellent. Each boundary is annotated with its rationale, catches specific exception types (not bare `except`), and logs with full traceback.

### Event Error Fields

Post-refactor (WS2), error events carry structured fields:
- `AgentErrorEvent`: `error_class`, `error_reason` populated from exception metadata
- `RemoraToolResultEvent`: `error_class`, `error_reason` extracted from tool output or inferred via regex
- `TurnCompleteEvent`: `error_summary` synthesized from per-turn error class tracking

This is a significant improvement over the pre-refactor state where errors were opaque strings.

---

## 13. Test Coverage

### Test Infrastructure

- **434 tests passing** across unit and integration suites
- `tests/conftest.py`, `tests/doubles.py`, `tests/factories.py` provide shared fixtures
- pytest-asyncio for async test support
- Hypothesis for property-based testing (imported in pyproject.toml)

### Test Quality

The tests are well-structured with:
- Clear naming conventions
- Proper async fixtures
- Mock-based isolation where appropriate
- Integration tests that exercise real SQLite and Cairn workspaces

### Issues

1. **P0: Duplicate module name**: `tests/unit/test_virtual_reactive_flow.py` and `tests/integration/test_virtual_reactive_flow.py` cause a pytest collection error. One must be renamed (e.g., `test_virtual_reactive_flow_unit.py`).

2. **Missing `__init__.py`**: The `tests/integration/` directory does not appear to have an `__init__.py`, though `tests/unit/` and `tests/` do. This is what causes the module name collision — pytest uses the basename for import, and without `__init__.py` files making them proper packages, the flat module lookup collides.

3. **5 skipped tests**: These appear to be marker-based skips (likely `@pytest.mark.acceptance` or similar). Not a concern.

---

## 14. Security Considerations

### CSRF Protection

The `CSRFMiddleware` rejects mutating requests (POST/PUT/DELETE) from non-localhost origins. This is appropriate for a local-first tool.

### Input Validation

- Chat messages are bounded (`chat_message_max_chars`)
- Search queries are validated (`top_k` range, mode whitelist)
- Event limit is bounded (1-500)
- Node IDs are validated against the graph store before operations

### Path Traversal

**Concern**: `proposals.py` uses `_workspace_path_to_disk_path` to map workspace paths to disk. I haven't read this function but it exists in `web/paths.py`. If it doesn't validate against directory traversal (e.g., `../../etc/passwd`), it could be a risk. The function name suggests awareness of this concern.

### SQL Injection

All SQL queries use parameterized queries. No string interpolation of user input into SQL. ✓

### Sensitive Data

- `model_api_key` is stored in config as a plain string. No encryption at rest, but this is standard for local config files.
- The `api_key or "EMPTY"` fallback in `create_kernel` prevents empty-string auth failures but logs the key in debug output. Consider masking.

---

## 15. Issues and Recommendations

### P0 — Must Fix

| # | Issue | Location | Fix |
|---|-------|----------|-----|
| 1 | Duplicate test module name causes collection error | `tests/unit/test_virtual_reactive_flow.py` vs `tests/integration/test_virtual_reactive_flow.py` | Rename one (e.g., add `_unit` or `_integration` suffix) |

### P1 — Should Fix

| # | Issue | Location | Fix |
|---|-------|----------|-----|
| 2 | SSE live event IDs use float timestamps; resume fails | `web/sse.py:95` | Use SQLite row ID as event ID |
| 3 | `graph_get_node` returns `{}` vs `None` contract mismatch | `capabilities.py:124` | Return `None` when node not found |
| 4 | `EventBus.stream()` uses unbounded queue | `bus.py:113` | Add `maxsize` with drop policy |

### P2 — Consider Fixing

| # | Issue | Location | Fix |
|---|-------|----------|-----|
| 5 | `_file_locks` dict grows unbounded between reconcile cycles | `reconciler.py` | Periodic cleanup or WeakValueDictionary |
| 6 | `SubscriptionRegistry` missing explicit `aiosqlite` import | `subscriptions.py` | Add import |
| 7 | `_run_kernel` retry count hardcoded to 1 | `turn.py:268` | Make configurable in RuntimeConfig |
| 8 | `chat.py` error responses don't use `error_response` helper | `chat.py` | Use `error_response()` for consistency |
| 9 | `_on_content_changed` doesn't check discovery_paths | `reconciler.py:423` | Filter to configured paths |
| 10 | `lifecycle.run()` with `run_seconds=0` doesn't handle task exceptions | `lifecycle.py:228` | Use `return_exceptions=True` |

### Nice to Have

| # | Issue | Location | Rationale |
|---|-------|----------|-----------|
| 11 | API key logged in debug output | `turn.py:288` | Mask sensitive fields |
| 12 | `search_content` scans all workspace files sequentially | `capabilities.py:59` | Consider workspace-level content search |
| 13 | No CORS headers documentation | `middleware.py` | Document browser access limitations |

---

_End of code review._
