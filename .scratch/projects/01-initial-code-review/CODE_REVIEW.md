# Remora v2 — Comprehensive Code Review

## Table of Contents

1. [Library Overview](#1-library-overview)
2. [Architecture Deep Dive](#2-architecture-deep-dive)
3. [Module-by-Module Review](#3-module-by-module-review)
4. [Bundle & Tooling System](#4-bundle--tooling-system)
5. [Test Suite Assessment](#5-test-suite-assessment)
6. [Bugs & Correctness Issues](#6-bugs--correctness-issues)
7. [Security Concerns](#7-security-concerns)
8. [Design & Architecture Issues](#8-design--architecture-issues)
9. [Performance Considerations](#9-performance-considerations)
10. [Recommendations Summary](#10-recommendations-summary)

---

## 1. Library Overview

### What Remora Is

Remora is a **reactive agent swarm substrate** that turns code elements (functions, classes, methods) into autonomous AI agents. Each code element discovered in a project becomes a `CodeNode` — a persistent entity with its own identity, workspace, tools, and the ability to communicate with other agents via an event-driven system.

The system is designed for a future where AI agents don't just analyze code from the outside, but *inhabit* it — each function or class gets its own LLM-backed agent that can:
- Receive messages from humans or other agents
- React to file changes in the codebase
- Propose rewrites to its own source code (subject to human approval)
- Subscribe to events and coordinate with sibling agents
- Maintain persistent working notes in a sandboxed filesystem

### What It Does (Functional Summary)

1. **Discovery**: Parses Python source files using `ast` to find functions, classes, and methods. Each gets a stable ID like `src/app.py::MyClass.my_method`.

2. **Projection**: Discovered code nodes (immutable `CSTNode`) are projected into mutable `CodeNode` records persisted in SQLite. On projection, each new node gets provisioned with a "bundle" — a set of tools and a system prompt.

3. **Event System**: An append-only SQLite event log (`EventStore`) records all system activity. An in-memory `EventBus` enables real-time dispatch. A `SubscriptionRegistry` lets agents register pattern-based subscriptions that trigger agent execution when matching events arrive.

4. **Agent Execution**: The `AgentRunner` consumes triggers from the event store's queue, loads the triggered agent's workspace and bundle config, discovers available tools, builds a prompt from the node's source and the triggering event, then runs an LLM turn via the `structured_agents` kernel. Results are appended back as events.

5. **Web Surface**: A Starlette app exposes REST APIs for querying nodes/edges/events, sending chat messages to agents, approving/rejecting rewrite proposals, and an SSE stream for live event updates. An inline HTML page renders a force-directed graph visualization using Sigma.js.

6. **LSP Server**: A pygls-based Language Server provides CodeLens (showing agent status inline in editors), Hover information, and emits events on file save/open.

7. **CLI**: A Typer-based CLI with `start` (runs the full system) and `discover` (prints discovered nodes) commands.

### How It Does It (Technical Stack)

| Layer | Technology |
|-------|-----------|
| Data models | Pydantic v2 (`BaseModel`, `BaseSettings`) |
| Config | YAML + env var expansion + `pydantic-settings` |
| Persistence | SQLite with WAL mode, asyncio Lock for serialization |
| Agent runtime | `structured_agents` (custom library) with `AgentKernel` |
| Tool scripts | `grail` (custom .pym script runner with `@external` bindings) |
| Agent workspaces | `cairn` workspace manager (fsdantic-backed sandboxed FS) |
| Code parsing | Python `ast` module (tree-sitter declared as dep but unused) |
| Web server | Starlette + Uvicorn |
| Graph viz | Sigma.js + Graphology (loaded from CDN) |
| LSP | pygls + lsprotocol |
| CLI | Typer |
| Testing | pytest + pytest-asyncio + httpx (ASGI transport) |

### Codebase Statistics

- **Source files**: 16 Python modules across 4 packages (`core`, `code`, `web`, `lsp`)
- **Test files**: 25 test modules (19 unit, 2 integration, 1 conftest)
- **Bundle files**: 3 bundles (system, code-agent, companion), 11 .pym tool scripts
- **Total source LoC**: ~1,700 (excluding tests and HTML)
- **Total test LoC**: ~1,400

---

## 2. Architecture Deep Dive

### Data Flow

```
Source Files
    │
    ▼
Discovery (ast.parse)
    │
    ▼
CSTNode (immutable, in-memory)
    │
    ▼
Projection (hash comparison, upsert)
    │
    ▼
CodeNode (mutable, SQLite-persisted)
    │
    ▼
SubscriptionRegistry (pattern-based triggers)
    │
    ▼
EventStore (append events → fan-out to bus + trigger queue)
    │
    ▼
AgentRunner (semaphore-gated, concurrent LLM turns)
    │
    ▼
AgentKernel (structured_agents) + GrailTools (externals)
    │
    ▼
Events (AgentComplete/Error → back into EventStore)
```

### Key Architectural Decisions

1. **Single SQLite database** shared across NodeStore, EventStore, and SubscriptionRegistry via a single `asyncio.Lock`. Simple but limits write throughput.

2. **Append-only event log** as the source of truth for all activity. Events are persisted then fanned out to the in-memory bus and trigger queue.

3. **Bundle-based provisioning**: Agents get their tools and prompts from layered template directories (system + type-specific). Tools are Grail `.pym` scripts with `@external` function bindings.

4. **Sandboxed workspaces**: Each agent gets a Cairn workspace with copy-on-write layering over a shared stable workspace.

5. **No subclasses for nodes**: `CodeNode` is a single flat model. Specialization is through `bundle_name` mapping and tool provisioning.

---

## 3. Module-by-Module Review

### `core/config.py` — Configuration

**Quality: Good**

- Clean Pydantic Settings model with frozen config.
- Shell-style `${VAR:-default}` env var expansion in YAML — well-implemented with regex.
- `_find_config_file` walks up directories — standard pattern.
- `isinstance` checks in `_expand_env_vars` are appropriate for YAML data traversal.

**Issues:**
- Minor: `_expand_env_vars` handles `tuple` but Pydantic/YAML won't produce tuples from loading. No harm, just dead code.

### `core/node.py` — CodeNode Model

**Quality: Good**

- Clean Pydantic model with JSON serialization for list fields (`caller_ids`, `callee_ids`) to fit SQLite.
- `from_row` handles both `sqlite3.Row` and `dict` — practical for testing.

**Issues:**
- `frozen=False` is intentional per REPO_RULES (single mutable model), but the code never actually mutates nodes in-place — all updates go through `upsert_node`. Could be frozen for safety.
- `status` field uses bare strings (`"idle"`, `"running"`, `"pending_approval"`, `"error"`) with no validation. A `Literal` or enum would prevent typos.

### `core/events.py` — Event System

**Quality: Very Good** — This is the most well-designed module.

- Clean event hierarchy using Pydantic models with automatic `event_type` tagging.
- `EventBus` supports MRO-aware dispatch, filtered streaming, and both sync and async handlers.
- `SubscriptionPattern` with flexible field-level matching (event types, from/to agents, path globs).
- `SubscriptionRegistry` with SQLite persistence and an event-type-indexed in-memory cache with proper invalidation.
- `EventStore` ties everything together: persist → bus → trigger queue.

**Issues:**
- **EventStore constructor is confusing**: accepts `db_path` OR `connection`, with `db_path` as positional and `connection` as keyword-only. The `assert` in `initialize()` is a code smell for a public API — should be a proper error.
- **`_summarize` uses `isinstance`** which contradicts REPO_RULES ("no isinstance in business logic"). This is borderline — it's event infrastructure, not "business logic" per se.
- **`get_triggers` is an infinite async generator** — callers must handle cancellation carefully. Works fine in the current runner but could surprise future consumers.

### `core/graph.py` — NodeStore

**Quality: Good**

- Straightforward SQLite CRUD with proper indexing.
- `Edge` as a frozen dataclass — clean.
- `delete_node` cascades edge deletion — correct.
- Dynamic SQL construction in `list_nodes` with parameterized queries — safe.

**Issues:**
- **f-string SQL construction** in `upsert_node`: `f"INSERT OR REPLACE INTO nodes ({columns}) VALUES ({placeholders})"`. The column names and placeholder names come from `node.to_row()` keys, which are model field names — safe from injection. But the pattern is fragile if a field name ever contained SQL metacharacters. A safer approach would be hardcoded SQL.
- **No transaction batching**: Each `upsert_node` call commits individually. During reconciliation with many nodes, this creates many small transactions.

### `core/workspace.py` — Cairn Workspace Integration

**Quality: Good**

- Clean copy-on-write layering: agent workspace falls through to stable workspace.
- `_safe_id` converts node IDs to filesystem-safe names with SHA1 digest suffix for uniqueness.
- Proper `asyncio.Lock` on all operations.

**Issues:**
- **SHA1 in `_safe_id`**: SHA1 is cryptographically broken. Here it's used only for filename uniqueness (not security), so it's functionally fine, but `hashlib.sha256` would be more conventional.
- **`close()` doesn't close raw workspaces individually** — it relies on `self._manager.close_all()`. If `close_all` skips any, workspace resources could leak.
- The `AgentWorkspace.__init__` takes `Any` for workspace types — no type safety on the Cairn workspace interface.

### `core/grail.py` — Grail Tool Loading

**Quality: Good**

- Clean bridge between Grail scripts and structured_agents ToolSchema/ToolResult.
- `_build_parameters` translates Grail input declarations to JSON Schema.
- `discover_tools` loads `.pym` files from agent workspaces with proper error handling.

**Issues:**
- **`_load_script_from_source` creates a temp directory for every script load**, writes the source to disk, loads it, then the temp dir is cleaned up. This happens for every tool on every agent turn. Performance impact scales with number of tools.
- **`_TYPE_MAP` is incomplete**: only maps `str`, `int`, `float`, `bool`. Any other Grail type annotation falls back to `"string"` silently.
- **Broad exception catch** in `discover_tools` (`except Exception`) — catches everything including `KeyboardInterrupt` (via `BaseException`). The `noqa: BLE001` acknowledges this.

### `core/kernel.py` — Structured Agents Wrapper

**Quality: Good** — Thin, focused wrapper.

- `extract_response_text` has a reasonable fallback chain.
- `api_key or "EMPTY"` — some LLM providers require a non-empty string even for local models.

**Issues:**
- `create_kernel` accepts `tools` but the `AgentRunner` passes tools separately via `kernel.run(messages, tool_schemas, ...)`. The `tools` parameter to `create_kernel` is always `None` in actual usage (only the test uses it). This is misleading.

### `core/runner.py` — Agent Runner

**Quality: Good overall, but the most complex module with several issues.**

- Trigger deduplication via cooldown and cascade depth limits — important safety features.
- `_build_externals` provides a rich set of 18+ external functions to Grail tools.
- `_execute_turn` has proper lifecycle: set running → execute → set idle, with error handling.

**Issues:**
- **`asyncio.create_task` without tracking** in `trigger()`: `asyncio.create_task(self._execute_turn(...))` — the task is fire-and-forget. If it raises, the exception is silently lost (Python 3.13 does log unhandled task exceptions, but they're easy to miss). Consider storing references.
- **Cooldown is per-node, not per-(node, correlation)**: Two different correlation chains triggering the same node within the cooldown window will have the second silently dropped, even though they're independent logical chains.
- **`_resolve_maybe_awaitable`** is called on `discover_tools(workspace, externals)`. Since `discover_tools` is an `async def`, calling it always returns a coroutine — this helper is unnecessary noise. The code should just `await discover_tools(...)`.
- **`event_emit` external silently discards the `payload` parameter**: `del payload` followed by creating an `Event(event_type=event_type)` with no payload. The scaffold tool passes a payload dict that gets thrown away.
- **`_workspace_file_paths` accesses private attributes** (`workspace._workspace`, `workspace._stable`) via `getattr` — breaks encapsulation. Should be a method on `AgentWorkspace`.
- **`_read_bundle_config` only catches `FileNotFoundError`**, not `FsdFileNotFoundError` from fsdantic. The workspace `read()` method raises `FsdFileNotFoundError` when the file doesn't exist in the Cairn filesystem.
- **`search_content` is O(N*M)** where N is files and M is file sizes — reads every file in the workspace for every search. No indexing.
- **Broadcast "siblings" pattern** looks up the source node's file in a linear scan of all nodes. Minor but could use a dict.

### `code/discovery.py` — Source Code Discovery

**Quality: Good**

- Python parsing via `ast` is robust and well-tested.
- Byte-accurate span calculation with proper UTF-8 handling.
- `CSTNode` is frozen (immutable) — correct for discovery output.

**Issues:**
- **tree-sitter is a hard dependency** (in `pyproject.toml`) but is **never used**. `_get_parser` returns `None` unconditionally. `_get_query` tries to load `.scm` files that don't exist (no `queries/` directory). This is dead infrastructure.
- **Only Python is actually supported**: `_parse_file` returns `[]` for all non-Python languages. The multi-language extension points exist but are stubs.
- **Only top-level definitions are discovered**: Nested functions, inner classes, and module-level assignments/constants are ignored. This is likely intentional but means the system misses decorators-as-wrappers and module-level orchestration code.
- **`__all__` exports private functions** (`_walk_source_files`, `_detect_language`, `_get_parser`, `_get_query`, `_parse_file`) — these are used by tests and reconciler, but exporting privates is unusual.

### `code/projections.py` — CST → CodeNode Projection

**Quality: Good**

- Hash-based change detection skips unchanged nodes — efficient.
- Bundle provisioning only happens for genuinely new nodes.
- Preserves existing `caller_ids`, `callee_ids`, and `status` on updates.

**Issues:**
- **No deletion of stale nodes**: If a function is removed from source, the corresponding `CodeNode` persists in the database forever. There's no "removed" reconciliation step.
- **`bundle_root` is relative** but never resolved against project root. If the config says `bundle_root: "bundles"` and you run from a different directory, the paths won't work.

### `code/reconciler.py` — Startup & Watch Reconciliation

**Quality: Adequate**

- `reconcile_on_startup` is a clean pipeline: discover → project → subscribe → emit events.
- `watch_and_reconcile` polls mtimes — simple and reliable.

**Issues:**
- **Discovery path construction is duplicated** between `reconciler.py`, `__main__.py._discover()`, and `__main__.py._start()`. Should be a shared utility.
- **`watch_and_reconcile` calls `reconcile_on_startup` on every change**, which re-discovers ALL files and re-projects ALL nodes. This is O(total codebase) on every single file change. Should diff only the changed files.
- **Subscriptions accumulate**: Every `reconcile_on_startup` call registers new subscriptions without cleaning up old ones. After several re-reconciliations, agents will have duplicate subscriptions.
- **`watch_and_reconcile` is never called** — the `_start` function in `__main__.py` doesn't launch it. The file watcher is dead code.

### `web/server.py` — Starlette Web API

**Quality: Good**

- Clean route structure with proper error handling.
- SSE stream with heartbeat, replay, and once mode.
- Proposal approval writes directly to disk with path traversal protection.

**Issues:**
- **`_find_proposal` scans the last 1000 events** linearly to find a proposal by ID. With many events, this becomes slow. Should use an indexed query.
- **`_resolve_file_path` path traversal protection** uses `relative_to()` check — correct approach. But if `root` is None, any absolute path is accepted. The root is always set from `__main__.py`, but it's worth noting.
- **`api_approve` writes the entire `new_source` as the file content**, replacing the whole file. If the proposal was for a single function in a multi-function file, the entire file gets replaced with just that function's source. This is a critical data loss risk. (The `RewriteProposalEvent` stores the whole file's new source, so this depends on what `propose_rewrite` puts in `new_source`.)
- **`del runner`** at the top of `create_app` — the runner parameter is accepted but immediately discarded. The function signature promises it uses the runner but doesn't.
- **XSS vulnerability** in `views.py`: The `showNode` function inserts `node.source_code` directly into `innerHTML` without escaping: `<pre>${node.source_code}</pre>`. If source code contains HTML/script tags, they will execute.

### `web/views.py` — HTML Template

**Quality: Adequate** — Functional but crude (inline HTML string).

- Force-directed graph layout with ForceAtlas2.
- Real-time SSE event handling updates node colors.
- CDN-loaded dependencies (graphology, sigma) pinned to specific versions.

**Issues:**
- **Monolithic HTML string** in Python — hard to maintain, no syntax highlighting in editor, no template engine benefits.
- **CDN dependencies without SRI hashes** — supply chain risk.
- **No error handling** in fetch calls or SSE reconnection logic.

### `lsp/server.py` — LSP Adapter

**Quality: Good**

- Clean mapping from CodeNode to LSP primitives (CodeLens, Hover).
- `_find_node_at_line` selects the narrowest containing node — correct.
- Exposes handlers for unit testing via `_remora_handlers`.

**Issues:**
- **`create_lsp_server` accepts `runner`** but immediately does `del runner`. Same as web server — unused parameter.
- **No `workspace/executeCommand` handler** for the `remora.showNode` command referenced in CodeLens. This is a known failure (per REPO_RULES).

---

## 4. Bundle & Tooling System

### Bundle Architecture

Three bundles ship with the system:

| Bundle | Purpose | Tools |
|--------|---------|-------|
| `system` | Base communication | `send_message`, `broadcast`, `subscribe`, `unsubscribe`, `query_agents` |
| `code-agent` | Code modification | `rewrite_self`, `scaffold` |
| `companion` | Reflection/metadata | `summarize`, `categorize`, `find_links`, `reflect` |

Bundles are layered: system tools are provisioned first, then type-specific tools overlay them.

### Tool Script Quality

The `.pym` scripts are generally clean and minimal. Each declares its inputs via `Input()`, binds externals via `@external`, and returns a result string.

**Issues:**
- **`scaffold.pym`** emits a `ScaffoldRequestEvent` but nothing in the system handles it. Dead feature.
- **`categorize.pym`** does naive keyword matching (`"test" in source_code`, `"http" in source_code`) — this is placeholder-quality classification.
- **`reflect.pym`** catches all exceptions with `except Exception` when reading the existing reflection file — should be `except FileNotFoundError`.
- **`query_agents.pym`** declares `graph_query_nodes(node_type, status)` but the external only passes `(node_type_value, None)` — the `status` parameter is always None with no way for the user to specify it.

---

## 5. Test Suite Assessment

### Coverage & Quality

The test suite is **comprehensive and well-structured**:

- **Unit tests** cover every module with good isolation using fixtures and monkeypatching.
- **Integration tests** include a full E2E test (`test_e2e_human_chat_to_rewrite`) that exercises the entire pipeline: discovery → reconciliation → human chat → trigger → mock LLM turn → rewrite proposal → web approval → file write.
- **Performance tests** verify sub-second operation for 100-node discovery, 100-node upserts, and 1000 subscription matches.
- **Web API tests** use httpx ASGI transport — no actual server needed.
- **Bundle validation tests** verify all `.pym` scripts parse and all `bundle.yaml` files are valid.

### Test Issues

- **Duplicate `_node` helper** defined in `test_runner.py`, `test_runner_externals.py`, `test_graph.py`, `test_web_server.py`, `test_lsp_server.py`, and `test_performance.py`. Should be a shared fixture in `conftest.py`.
- **Duplicate `runner_env` fixture** in `test_runner.py` and `test_runner_externals.py` — identical setup code.
- **No negative tests for config validation** — what happens with invalid YAML, wrong types, missing required fields?
- **No test for `watch_and_reconcile`** — but this is dead code anyway.
- **`test_cli_start_smoke`** runs for 0.1 seconds with `--run-seconds` — clever integration test.

---

## 6. Bugs & Correctness Issues

### Critical

1. **`event_emit` external discards payload** (`runner.py:269`): `del payload` means Grail tool scripts like `scaffold.pym` that pass payload data have it silently thrown away. The emitted event is a bare `Event(event_type=...)` with no content.

2. **`_read_bundle_config` missing `FsdFileNotFoundError`** (`runner.py:377`): Only catches `FileNotFoundError` but `AgentWorkspace.read()` can also raise `FsdFileNotFoundError`. This could crash agent turns when no bundle is provisioned.

3. **Subscriptions accumulate on re-reconciliation** (`reconciler.py:50-60`): Each call to `reconcile_on_startup` registers new subscriptions without cleaning up existing ones. After the watcher triggers re-reconciliation, agents get duplicate subscriptions and duplicate triggers.

### High

4. **No stale node cleanup**: Deleted functions remain as `CodeNode` records forever, accumulating zombie agents.

5. **Version mismatch**: `pyproject.toml` says `version = "0.5.0"`, `__init__.py` says `__version__ = "2.0.0"`. One is wrong.

6. **`approve` endpoint replaces entire file** (`server.py:120`): The approval writes `proposal["new_source"]` as the complete file. If the `RewriteProposalEvent` only contains one function's source (as `propose_rewrite` in the runner creates it with `node.source_code` as `old_source`), approving would destroy the rest of the file.

### Medium

7. **tree-sitter is a required dependency but never used**: Bloats the install for no reason.

8. **`_workspace_file_paths` accesses private attributes**: Breaks if `AgentWorkspace` internals change.

9. **Cooldown is node-scoped, not (node, correlation)-scoped**: Independent trigger chains can suppress each other.

---

## 7. Security Concerns

### XSS in Web UI

`views.py` line ~188: `node.source_code` is interpolated directly into `innerHTML`:
```javascript
document.getElementById("node-details").innerHTML = `
    ...
    <pre>${node.source_code}</pre>
`;
```
If source code contains `<script>alert(1)</script>` or similar, it executes in the browser. Fix: use `textContent` or escape HTML entities.

### Path Traversal (Mitigated)

The `_resolve_file_path` function in `server.py` correctly validates that approved file paths fall within the project root using `relative_to()`. This is properly implemented.

### SQL Injection (Not Present)

All SQL queries use parameterized queries. The f-string SQL in `upsert_node` uses model field names as column names, which are safe. No user input reaches SQL construction.

### Arbitrary Code Execution via `.pym` Scripts

Grail scripts are executable code loaded from agent workspaces. If an agent can write arbitrary files to its workspace, it could craft a malicious `.pym` script. Currently, agents can write files via the `write_file` external, but `discover_tools` only loads from `_bundle/tools/` — a fixed path. The risk is limited but worth noting.

---

## 8. Design & Architecture Issues

### 1. Single Lock Contention

All SQLite operations share one `asyncio.Lock`. With `max_concurrency=4` agents running turns simultaneously, they all contend on this lock for every database operation. Since `asyncio.to_thread` is used for SQLite calls, the lock serializes what should be parallel I/O.

**Recommendation**: Consider read-write lock separation, or use SQLite's WAL mode more aggressively (WAL already allows concurrent reads).

### 2. Event Store as Trigger Queue

The `EventStore._trigger_queue` is an in-memory `asyncio.Queue`. If the process crashes, pending triggers are lost. For a system designed around event sourcing, trigger state should be recoverable from the event log.

### 3. Bundle Config Read on Every Turn

Every agent turn reads `_bundle/bundle.yaml` from the workspace filesystem. This is a Cairn read (potentially hitting disk). Should be cached after first load for stable bundles.

### 4. No Agent Turn Timeout

`kernel.run()` has no explicit timeout beyond the HTTP timeout to the LLM provider (`timeout_s`). If the LLM hangs or returns an enormous response, the agent turn blocks indefinitely while holding the semaphore slot.

### 5. Missing Observability

No structured logging, no metrics, no tracing. The system logs with `logging.info`/`logging.warning` but provides no way to monitor agent turn latency, error rates, queue depth, or throughput.

---

## 9. Performance Considerations

### Good

- **Subscription cache**: `SubscriptionRegistry` caches subscriptions in memory, indexed by event type. Cache invalidation on register/unregister is correct.
- **Hash-based skip in projection**: Unchanged nodes skip the upsert entirely.
- **Semaphore-gated concurrency**: `max_concurrency` prevents resource exhaustion.
- **Performance tests** establish baseline expectations.

### Concerning

- **Full re-discovery on file change**: `watch_and_reconcile` runs the entire discovery pipeline on any change. For large codebases, this is prohibitive.
- **Linear proposal search**: `_find_proposal` scans 1000 events to find one proposal.
- **Workspace file listing for search**: `search_files` and `search_content` list and read all files in the workspace.
- **Individual commits per upsert**: No batch transaction support in `NodeStore`.
- **Temp file per script load**: `_load_script_from_source` creates and destroys a temp directory for each Grail script.

---

## 10. Recommendations Summary

### Must Fix (Bugs)

| # | Issue | Location |
|---|-------|----------|
| 1 | `event_emit` external silently discards payload | `runner.py:269` |
| 2 | Add `FsdFileNotFoundError` to `_read_bundle_config` catch | `runner.py:377-381` |
| 3 | Clean up old subscriptions before re-registration | `reconciler.py:49-60` |
| 4 | Fix version mismatch (0.5.0 vs 2.0.0) | `pyproject.toml` / `__init__.py` |
| 5 | Fix XSS in `showNode` (use textContent or escape) | `views.py:~188` |

### Should Fix (Design)

| # | Issue | Recommendation |
|---|-------|---------------|
| 6 | No stale node cleanup | Add deletion pass in reconciliation |
| 7 | tree-sitter unused but required | Move to optional dependency or remove |
| 8 | `approve` may truncate files | Verify `new_source` is full file content, or implement surgical replacement |
| 9 | `_workspace_file_paths` breaks encapsulation | Add a `list_all_paths()` method to `AgentWorkspace` |
| 10 | `watch_and_reconcile` never called | Wire it into `_start` or remove it |

### Nice to Have (Improvements)

| # | Issue | Recommendation |
|---|-------|---------------|
| 11 | Status field as bare strings | Use `Literal["idle", "running", ...]` |
| 12 | Shared `_node` test helper | Extract to conftest fixture |
| 13 | Discovery path construction duplicated | Extract to a config method |
| 14 | No agent turn timeout | Add `asyncio.wait_for` around `kernel.run()` |
| 15 | No structured observability | Add metrics/structured logging foundation |

### Overall Assessment

Remora v2 is a **well-architected early-stage system** with a clean separation of concerns and surprisingly comprehensive test coverage for its maturity level. The event-sourced architecture is sound, the workspace sandboxing is thoughtful, and the code is consistently well-formatted and readable.

The main risks are: (1) a few correctness bugs in the runner's externals and reconciler that would cause real problems in production use, (2) the XSS vulnerability in the web UI, and (3) performance characteristics that would degrade on medium-to-large codebases due to the full-re-discovery approach.

The dependency on three custom libraries (cairn, grail, structured_agents) is notable — the system's quality depends heavily on those libraries' maturity, and they represent a significant learning curve for contributors.
