# Remora v2 — Production Readiness Code Review

**Date:** 2026-03-14
**Scope:** Full codebase review against "semi-production" readiness for single-user local deployment
**Standard:** Can this system deliver the DEMO_PLAN.md scenarios in real-world usage with a local vLLM server on a personal tailnet?
**LSP Target:** Neovim only (no VS Code)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary) — Overall assessment, readiness rating, top blockers
2. [Architecture Overview](#2-architecture-overview) — System diagram, data flow, component relationships
3. [Module-by-Module Analysis](#3-module-by-module-analysis) — Deep review of every source module
   - 3.1 Core Types & Config
   - 3.2 Database Layer
   - 3.3 Node Model & Graph Store
   - 3.4 Event System (Types, Bus, Store, Subscriptions, Dispatcher)
   - 3.5 Workspace (Cairn Integration)
   - 3.6 Grail Tool System
   - 3.7 Kernel (LLM Integration)
   - 3.8 Actor Model & Runner
   - 3.9 Code Discovery & Reconciler
   - 3.10 LSP Server
   - 3.11 Web Server & UI
   - 3.12 CLI Entry Point
4. [Bundle & Tool Script Review](#4-bundle--tool-script-review) — Bundle configs, Grail tool scripts, prompt engineering
5. [Test Suite Assessment](#5-test-suite-assessment) — Coverage, gaps, reliability
6. [Demo Readiness Gap Analysis](#6-demo-readiness-gap-analysis) — What works now vs. what's needed for each demo act
7. [Critical Issues](#7-critical-issues) — Bugs, crashes, data loss risks
8. [High-Priority Improvements](#8-high-priority-improvements) — Functional gaps blocking demo readiness
9. [Medium-Priority Improvements](#9-medium-priority-improvements) — Quality, reliability, UX polish
10. [Low-Priority Improvements](#10-low-priority-improvements) — Nice-to-haves for post-demo
11. [Neovim Integration Strategy](#11-neovim-integration-strategy) — LSP client config, cursor tracking, companion panel
12. [Recommended Action Plan](#12-recommended-action-plan) — Prioritized work items with effort estimates

---

## 1. Executive Summary

### Overall Assessment: **Nearly Demo-Ready — 70% of target functionality works today**

Remora v2 is a well-structured, event-driven agent substrate with clean separation of concerns and solid fundamentals. The core pipeline — discovery → node graph → event-driven agent execution → web visualization — is functional end-to-end. The codebase is ~2,400 lines of production code with 207 passing tests.

### What Works Well
- **Architecture is sound.** The Event → Bus → Dispatcher → Actor inbox pipeline is clean and correct. Pydantic models, SQLite persistence, and the Cairn workspace abstraction are well-integrated.
- **Discovery pipeline is robust.** Tree-sitter based parsing with language plugins, reconciler with mtime tracking and watchfiles integration, and directory node materialization all work correctly.
- **Web UI is functional.** Sigma.js graph with real-time SSE updates, node inspection, chat input — the bones of a compelling demo are here.
- **Test suite is healthy.** 207 tests passing, good coverage of unit-level concerns, async fixtures are properly structured.

### Top Blockers for Demo Readiness

| # | Blocker | Severity | Est. Effort |
|---|---------|----------|-------------|
| 1 | **No chat response visibility** — `AgentCompleteEvent` and `send_message` to "user" results are not displayed anywhere in the web UI or SSE stream in a user-consumable way | **Critical** | 2-4 hrs |
| 2 | **LSP server is stdio-only** — Cannot run alongside web server in the same process without contention; neovim integration needs a TCP or pipe transport, or a separate process model | **Critical** | 3-6 hrs |
| 3 | **No cursor-following companion** — The "wow moment" from the demo plan (Act 2) requires `CursorFocusEvent`, LSP cursor tracking, and web UI companion panel — none exist | **High** | 8-14 hrs |
| 4 | **Agent responses are truncated to 200 chars** — `result_summary=response_text[:200]` in `AgentCompleteEvent` discards most of the agent's actual response | **High** | 30 min |
| 5 | **`remora.yaml` is missing `directory` overlay** — The shipped `remora.yaml` lacks the `directory: "directory-agent"` bundle overlay that `remora.yaml.example` has, so directory agents get no tools | **Medium** | 5 min |
| 6 | **`rewrite_self.pym` says "Rewrite applied" even on failure** — The tool returns `f"Rewrite applied: {success}"` which says "Rewrite applied: False" on failure rather than a clear error | **Low** | 10 min |

### Readiness by Demo Act

| Act | Description | Status |
|-----|-------------|--------|
| Act 1: Discovery & Graph | `remora start` → graph populates via SSE | **Ready** |
| Act 2: Companion Sidebar | Cursor-following companion panel | **Not Started** |
| Act 3: Live Reactivity | Edit → cascade → agents respond | **Partially Ready** (events fire, but agent responses aren't visible) |
| Act 4: Chat | Talk to a function, get a response | **Partially Ready** (chat sends, but response not displayed to user) |
| Act 5: Extensibility | Show bundles, tools, multi-language | **Ready** |

---

## 2. Architecture Overview

### System Diagram

```
┌──────────────┐     ┌─────────────┐     ┌───────────────┐
│  Source Code  │────▶│  Discovery   │────▶│  Node Store   │
│  (*.py, etc.) │     │  (tree-sitter)│    │  (SQLite)     │
└──────────────┘     └─────────────┘     └───────┬───────┘
       │                                          │
       ▼                                          ▼
┌──────────────┐     ┌─────────────┐     ┌───────────────┐
│  Watchfiles  │────▶│  Reconciler  │────▶│  Event Store  │
│  (filesystem) │    │  (diff/sync)  │    │  (SQLite)     │
└──────────────┘     └─────────────┘     └───────┬───────┘
                                                  │
                            ┌─────────────────────┤
                            ▼                     ▼
                     ┌─────────────┐     ┌───────────────┐
                     │  Event Bus  │     │  Dispatcher   │
                     │  (in-memory) │    │  (subs match)  │
                     └──────┬──────┘     └───────┬───────┘
                            │                     │
                            ▼                     ▼
                     ┌─────────────┐     ┌───────────────┐
                     │  SSE/Web UI │     │  Actor Pool   │
                     │  (Starlette) │    │  (per-node)    │
                     └─────────────┘     └───────┬───────┘
                                                  │
                     ┌─────────────┐              ▼
                     │  LSP Server │     ┌───────────────┐
                     │  (pygls)    │     │  LLM Kernel   │
                     └─────────────┘     │  (structured- │
                                         │   agents)     │
                                         └───────────────┘
```

### Data Flow
1. **Discovery:** Source files → tree-sitter parse → CSTNode → project_nodes → Node (SQLite)
2. **Reconciliation:** Watchfiles/LSP didSave → FileReconciler → NodeChanged/Discovered/Removed events
3. **Event Fan-out:** EventStore.append → EventBus.emit (SSE subscribers) + Dispatcher.dispatch (subscription matching → Actor inbox)
4. **Agent Execution:** Actor pops event from inbox → builds prompt from node + trigger → calls LLM kernel → emits completion events
5. **Visualization:** SSE stream → web UI updates graph node colors, event log

### Key Dependencies
- `structured-agents` — LLM kernel abstraction (custom, Bullish-Design)
- `cairn` — Workspace management (custom, Bullish-Design)
- `grail` — Tool scripting language (custom, Bullish-Design)
- `fsdantic` — Filesystem-backed Pydantic (custom, Bullish-Design)
- Standard ecosystem: `pydantic`, `aiosqlite`, `starlette`, `pygls`, `tree-sitter`, `watchfiles`

---

## 3. Module-by-Module Analysis

### 3.1 Core Types & Config (`core/types.py`, `core/config.py`)

**Status: Good**

`types.py` is clean — enums for `NodeStatus`, `NodeType`, `ChangeType` with a simple state machine. The status transition validation is correct and used consistently.

`config.py` is well-designed:
- Pydantic Settings with YAML + env var support
- Shell-style `${VAR:-default}` expansion
- Config file discovery walks up directory tree
- Validators are thorough

**Issues:**
- `VirtualAgentConfig.id` has no format restrictions — could contain characters that break filesystem paths or SQLite queries. The workspace `_safe_id()` method handles filesystem safety, but a `::` in the ID could create confusing node_id collisions with discovered nodes.
- `Config.model_config` uses `frozen=True` but the class has no `__hash__` — this is fine since Pydantic handles it, but worth noting Config objects can be used as dict keys.

### 3.2 Database Layer (`core/db.py`)

**Status: Good — minimal and correct**

Simple factory function, sets WAL mode and busy_timeout. Clean.

**Issues:**
- `busy_timeout=5000` (5 seconds) is fine for single-user but could log warnings under heavy agent concurrency if multiple actors commit simultaneously. For a demo this is fine.
- No connection pool — single connection shared across all async operations. aiosqlite handles this with internal locking, but it means all DB operations are effectively serialized. Not a problem at single-user scale.

### 3.3 Node Model & Graph Store (`core/node.py`, `core/graph.py`)

**Status: Good**

`Node` model is clean Pydantic with `to_row()`/`from_row()` serialization. `NodeStore` provides CRUD + edge operations with proper indexing.

**Issues:**
- `upsert_node` uses `INSERT OR REPLACE` which deletes-then-inserts, meaning any FK-like references from edges would be preserved (edges reference node_id as text, not FK). This is fine.
- `transition_status` is a read-then-write pattern without locking — two concurrent transitions could race. With aiosqlite's GIL-like behavior this is unlikely, but the semantic gap exists.
- `set_status` commits after every single status update — this generates a lot of WAL traffic during agent cascades. Batch commits would improve performance.
- **Missing: No `list_nodes` pagination.** For a demo project (~20 nodes) this is fine, but the API returns everything.

### 3.4 Event System (`core/events/`)

**Status: Good architecture, some rough edges**

The event system is the heart of Remora and it's well-designed:
- `Event` base with auto-tagging, envelope serialization
- `EventBus` for in-memory pub/sub with async stream support
- `EventStore` for SQLite persistence + fan-out to bus and dispatcher
- `SubscriptionRegistry` with event_type-indexed cache
- `TriggerDispatcher` routes to actor inboxes via callback

**Issues:**
- **`EventStore.append` does DB write → bus emit → dispatch all synchronously.** If the bus has a slow handler, it blocks dispatch. For a demo this is fine, but a production system would want async fire-and-forget for bus emission.
- **`SubscriptionRegistry._rebuild_cache` loads ALL subscriptions into memory.** Fine for demo scale, but no pruning or limits.
- **`EventBus._dispatch_handlers` creates asyncio tasks for coroutine handlers but doesn't handle exceptions** — a failing handler would cause an unhandled exception in a task. The `asyncio.gather` would collect it, but no logging.
- **No `AgentResponseEvent` type.** The `AgentCompleteEvent.result_summary` field is truncated to 200 chars. There's no dedicated event for "here's the full agent response" that the UI could display. This is the **biggest functional gap** for the chat demo.

### 3.5 Workspace (`core/workspace.py`)

**Status: Good**

Clean Cairn workspace abstraction with per-agent sandboxing, KV store, file operations. The `CairnWorkspaceService` handles provisioning, bundle template copying, and fingerprint-based cache invalidation.

**Issues:**
- `_safe_id` uses SHA1 — technically fine for filesystem naming but SHA1 is deprecated for security. Since this is just filesystem naming (not security), it's acceptable.
- `provision_bundle` is synchronous file reads (`pym_file.read_text()`) inside an async method — could block the event loop for large tool directories. At demo scale this is negligible.
- `_bundle_template_fingerprint` reads all files synchronously. Same concern.

### 3.6 Grail Tool System (`core/grail.py`)

**Status: Good**

Clean wrapping of Grail scripts as structured-agents `ToolSchema`/`ToolResult`. The `_cached_script` LRU cache with content hashing is smart — avoids re-parsing unchanged tools.

**Issues:**
- `_cached_script` writes to a temporary directory on every cache miss, then relies on LRU eviction. The tempdir is cleaned up immediately after `grail.load()`, so this is fine.
- Tool descriptions are generic: `f"Tool: {script.name}"`. The LLM gets no description of what the tool does beyond its name and parameter schema. **This significantly hurts tool selection quality** — the LLM must rely entirely on the tool name. For a 4B parameter model, this could lead to incorrect tool usage. Consider extracting descriptions from Grail script docstrings.
- `discover_tools` exception handling is broad (`except Exception`) — silently skips broken tools. Logging is present, which is good.

### 3.7 Kernel (`core/kernel.py`)

**Status: Good — thin wrapper**

Clean delegation to `structured_agents.AgentKernel`. The `extract_response_text` helper handles the response extraction.

**Issues:**
- `api_key or "EMPTY"` — vLLM typically doesn't require an API key, but some setups do. The fallback to "EMPTY" is fine.
- No retry logic for transient LLM failures. A single timeout or connection error kills the entire agent turn. For demo reliability, even one retry with backoff would help.

### 3.8 Actor Model & Runner (`core/actor.py`, `core/runner.py`)

**Status: Good architecture, needs polish**

The Actor model is well-designed:
- Per-actor inbox (asyncio.Queue)
- Sequential processing within an actor
- Cooldown and depth-based loop prevention
- Global semaphore for concurrency limiting
- Idle eviction

**Issues:**
- **`Actor._depths` dict grows unbounded.** The comment says "Clean stale depth entries (done here rather than on a timer to keep it simple)" but the cleanup never actually happens. Old correlation IDs are decremented in `_reset_agent_state` but only if they're referenced again. Over a long session, this dict accumulates. At demo scale it's fine, but it's a slow memory leak.
- **`_should_trigger` cooldown is per-actor, which means the *first* event after cooldown passes but all events during cooldown are silently dropped** (not queued). If a burst of changes happens to the same file, only the first triggers the agent. This is probably the intended behavior for reactive mode, but it means chat messages could be dropped if they arrive within the cooldown window.
- **`Actor._execute_turn` catches broad `Exception`** — good for crash prevention, but makes debugging harder. The logging is present which mitigates this.
- **`Outbox` has a `_sequence` counter that's never used** for anything visible. It could be useful for ordering but isn't currently.
- **`ActorPool.run_forever` just sleeps and evicts idle actors.** The actors themselves run as independent tasks. This means `run_forever` is essentially a maintenance loop. Clean, but the sleep(1.0) means up to 1 second latency for eviction. Fine for demo.

### 3.9 Code Discovery & Reconciler (`code/discovery.py`, `code/reconciler.py`, `code/projections.py`, `code/paths.py`, `code/languages.py`)

**Status: Good — the most mature subsystem**

Discovery is robust:
- Tree-sitter parsing with named query captures
- Proper parent-child relationship detection via AST walking
- Deduplication with `@start_byte` suffix for same-name nodes
- Language plugin system with Python, Markdown, TOML

Reconciler is solid:
- Mtime-based change detection with full scan on startup
- Incremental per-file reconciliation via watchfiles
- Directory node materialization from file paths
- Virtual agent synchronization
- ContentChangedEvent subscription for LSP-triggered reconciliation

**Issues:**
- **`discover()` uses `@lru_cache` for parsers and queries keyed on string paths.** If query file content changes but the path stays the same, the cache serves stale queries. This would bite during development but not during a demo.
- **`_parse_file` builds full name by walking the parent chain.** This produces correct dotted names (e.g., `MyClass.my_method`) but doesn't handle overloaded functions (same name, different signatures) — tree-sitter doesn't distinguish these anyway.
- **Reconciler `_file_locks` dict grows unbounded** — one Lock per file path, never cleaned up. Negligible memory at demo scale.
- **`reconcile_cycle` calls `discover()` per-file during incremental updates, which re-creates parser/query objects.** The LRU cache handles this, but it's worth noting the per-file overhead.
- **`_materialize_directories` re-registers subscriptions for ALL directory nodes on first startup** (`_subscriptions_bootstrapped` flag). This is O(N) subscription database operations on startup. Fine for ~10 directories.

### 3.10 LSP Server (`lsp/server.py`)

**Status: Functional but minimal**

Provides:
- CodeLens showing node status above each function/class
- Hover with node metadata (ID, type, status, file location)
- didSave → ContentChangedEvent (triggers reconciliation)
- didOpen/didClose/didChange document tracking

**Issues:**
- **stdio transport only.** The `__main__.py` wraps `lsp_server.start_io` in `asyncio.to_thread` — this blocks a thread. For neovim, this means the LSP server must run as a separate process spawned by neovim's LSP client. The `--lsp` flag on `remora start` runs it in the same process, which conflicts with stdout logging. **This needs rethinking for neovim.**
- **No cursor position tracking.** The LSP spec doesn't have a standard "cursor moved" notification. Neovim extensions would need to send custom notifications or use `textDocument/hover` requests to report cursor position. This is the gap for Act 2 (companion sidebar).
- **`_uri_to_path` returns an absolute path**, but `node_store.list_nodes(file_path=...)` expects the path to match what discovery stored — which is also absolute. This should work but is fragile if paths differ by symlink resolution.
- **CodeLens `remora.showNode` command is not implemented** — neovim won't do anything when the lens is clicked. Need to either implement the command or change to a display-only lens.
- **`DocumentStore` maintains in-memory text but it's never used** for anything beyond tracking. The reconciler re-reads from disk anyway. This is dead weight unless we add features like diffing against in-memory content.
- **LSP server has no type annotations** on `create_lsp_server` parameters (`node_store`, `event_store` are `Any`). Minor but makes the API contract unclear.
- **No diagnostic publishing.** An agent that finds issues could publish LSP diagnostics (warnings, errors) in the editor. This would be a powerful demo feature.

### 3.11 Web Server & UI (`web/server.py`, `web/static/index.html`)

**Status: Functional, needs UX work for demo**

Server provides:
- Node listing, single node fetch, edge listing
- Chat endpoint (POST /api/chat)
- Event listing with pagination
- SSE streaming with replay

UI provides:
- Sigma.js graph with force-directed layout
- Real-time SSE event handling (node add/remove, agent status colors)
- Node click → sidebar details
- Chat input

**Issues:**
- **No way to see agent responses.** The chat sends an `AgentMessageEvent` which triggers the agent, but the agent's response (sent via `send_message` to "user") appears only in the event log as raw JSON. There's no chat-like display. **This is the #1 UX blocker for the demo.**
- **`project_root` parameter is accepted but immediately discarded** (`del project_root`). If it was intended for something (like reading source files), it's not implemented.
- **`api_node` uses `{node_id:path}` path parameter** which handles slashes in node IDs correctly. Good.
- **SSE `replay` re-serializes events from DB** with inconsistent format — the replayed events include `event_type` in the payload while live events don't. This could confuse UI code.
- **Graph layout uses `forceatlas2` with a fixed iteration count** (configurable via `data-sigma-iterations`). No continuous/incremental layout, so adding nodes after initial layout doesn't look great.
- **No response/chat message display in UI** — the events panel shows raw event types but doesn't render `AgentMessageEvent` content in a readable way.
- **Static file serving is mounted at `/static`** but no static files exist besides `index.html` which is served from `/`. The mount is effectively unused.
- **No CORS headers.** If the web UI were served from a different origin (e.g., neovim webview), requests would fail. Not relevant for localhost same-origin.

### 3.12 CLI Entry Point (`__main__.py`)

**Status: Good**

Clean Typer-based CLI with `start` and `discover` commands. Proper logging configuration with file + stream handlers.

**Issues:**
- **LSP stdio conflict.** When `--lsp` is used, the LSP server reads from stdin/writes to stdout. But the stream logging handler also writes to stdout. The `_configure_logging` function doesn't suppress stdout when LSP mode is active. **This will corrupt the LSP JSON-RPC stream.** Need to either redirect logging to stderr/file-only when `--lsp` is active, or run LSP as a separate command.
- **`run_seconds` with value 0 means "run forever"** but `asyncio.gather(*tasks)` will block until any task fails. If the runner's `run_forever` never ends and no task crashes, this works. But if a task raises unexpectedly, the gather returns and cleanup begins — which is correct.
- **Shutdown sequence** calls `services.close()` then cancels tasks. The close method stops the reconciler and runner first, which is correct ordering.
- **No `--bind` option** — web server always binds to `127.0.0.1`. For tailnet access, this needs to be `0.0.0.0` or configurable.

---

## 4. Bundle & Tool Script Review

### Bundle Configs

| Bundle | System Prompt Quality | Max Turns | Issues |
|--------|----------------------|-----------|--------|
| `system` | Good base persona, instructs "use send_message to user" | 4 | Model env var has specific model name as default — should match `remora.yaml` config |
| `code-agent` | Good extension, clear rules | 8 | Says "rewrites require human approval" but `apply_rewrite` applies immediately |
| `directory-agent` | Good, clear role definition | 6 | No issues |
| `review-agent` | Empty (just a bundle.yaml placeholder) | - | Needs content or should be removed |
| `test-agent` | Empty placeholder | - | Same |

### Tool Scripts (Grail .pym)

**System tools (available to all agents):**

| Tool | Function | Issues |
|------|----------|--------|
| `broadcast.pym` | Broadcast to matching agents | Works |
| `categorize.pym` | Workspace categorization | Need to verify |
| `find_links.pym` | Find related links | Need to verify |
| `kv_get.pym` | KV store read | Works |
| `kv_set.pym` | KV store write | Works |
| `query_agents.pym` | Query node graph | Works |
| `reflect.pym` | Write reflection notes | Appends indefinitely — no size limit |
| `send_message.pym` | Send inter-agent messages | Works — critical for chat responses |
| `subscribe.pym` | Dynamic subscription | Works |
| `summarize.pym` | Summarize workspace | Need to verify |
| `unsubscribe.pym` | Dynamic unsubscription | Works |

**Code-agent tools:**

| Tool | Function | Issues |
|------|----------|--------|
| `rewrite_self.pym` | Apply source code rewrite | Success message is misleading on failure |
| `scaffold.pym` | Scaffold workspace files | Need to verify |

**Directory-agent tools:**

| Tool | Function | Issues |
|------|----------|--------|
| `broadcast_children.pym` | Message all children | Works |
| `get_parent.pym` | Get parent node info | Works |
| `list_children.pym` | List child nodes | Works |
| `summarize_tree.pym` | Summarize directory tree | Works |

### Prompt Engineering Assessment

The bundle prompts are functional but could be significantly improved for a 4B parameter model:
- **System prompts are vague.** "Maintain accurate local state" doesn't tell the agent *how*. For small models, explicit step-by-step instructions work much better.
- **No few-shot examples.** The prompts don't show the agent what a good tool call sequence looks like.
- **Chat vs reactive mode switching is good** — different prompts for user-initiated vs system-triggered turns.
- **Tool descriptions are auto-generated as just the name.** The LLM sees `"description": "Tool: send_message"` — no parameter descriptions, no usage examples. This is a major quality issue for small models.

---

## 5. Test Suite Assessment

**Overall: Strong — 207 passed, 5 skipped**

### Coverage by Component

| Component | Test File(s) | Coverage | Notes |
|-----------|-------------|----------|-------|
| Config | `test_config.py` | Good | Validates loaders, env expansion, virtual agents |
| DB | `test_db.py` | Good | WAL mode, pragmas |
| Node | `test_node.py` | Good | Serialization round-trips |
| Graph | `test_graph.py` | Good | CRUD, edges, status transitions |
| Events | `test_events.py`, `test_event_bus.py`, `test_event_store.py`, `test_subscription_registry.py` | Good | Types, bus dispatch, persistence, matching |
| Actor | `test_actor.py` | Good | Turn execution, cooldown, depth limiting |
| Runner | `test_runner.py` | Good | Actor lifecycle, eviction |
| Discovery | `test_discovery.py` | Good | File parsing, node extraction |
| Reconciler | `test_reconciler.py` | Good | Full scan, incremental, directory materialization |
| Languages | `test_languages.py` | Good | Plugin resolution |
| Paths | `test_paths.py` | Good | Walk, ignore patterns |
| Projections | `test_projections.py` | Good | CSTNode → Node projection |
| LSP | `test_lsp_server.py` | Good | CodeLens, hover, didSave events |
| Web | `test_web_server.py` | Good | API endpoints, SSE |
| CLI | `test_cli.py` | Basic | Smoke test of CLI invocation |
| Grail | `test_grail.py` | Good | Tool loading, execution |
| Externals | `test_externals.py` | Good | TurnContext API surface |
| Workspace | `test_workspace.py` | Good | Cairn integration |

### Gaps
- **No integration test for full chat flow** — sending a message → agent turn → response visible to user
- **No integration test for cascade** — file change → reconcile → NodeChanged → agent trigger → completion
- **`test_e2e.py` exists but is likely skipped** (the 5 skipped tests)
- **No performance/load tests** for concurrent agent execution
- **No test for LSP stdio corruption** when logging is enabled

---

## 6. Demo Readiness Gap Analysis

### Act 1: Discovery & The Living Graph (0:00-2:30) — **READY**

| Requirement | Status | Notes |
|------------|--------|-------|
| `remora start` discovers nodes | ✅ | Works |
| Web graph populates via SSE | ✅ | Real-time NodeDiscoveredEvent → graph node |
| Color by type | ✅ | function=blue, class=purple, method=teal |
| Click node → sidebar details | ✅ | Shows type, status, file, source code |
| Force-directed layout | ✅ | ForceAtlas2 with configurable iterations |

**Gaps:** Graph layout could be improved with continuous layout for a smoother demo feel. Nodes cluster randomly rather than by file. These are polish items.

### Act 2: Companion Sidebar (2:30-4:00) — **NOT STARTED**

| Requirement | Status | Notes |
|------------|--------|-------|
| LSP CodeLens annotations | ✅ | Shows "Remora: idle/running/error" above functions |
| LSP hover metadata | ✅ | Shows node ID, type, status, file |
| Cursor-following companion | ❌ | No CursorFocusEvent, no cursor tracking |
| Companion web panel | ❌ | No companion content generation or display |
| Neovim integration | ⚠️ | LSP works in theory but stdio conflicts with logging |

### Act 3: Live Reactivity (4:00-6:00) — **PARTIALLY READY**

| Requirement | Status | Notes |
|------------|--------|-------|
| File edit detected by watchfiles | ✅ | Works |
| Reconciler emits NodeChangedEvent | ✅ | Works |
| Agent turn triggered | ✅ | Via subscription matching + dispatcher |
| Node lights up orange | ✅ | AgentStartEvent → color change in UI |
| Node returns to blue | ✅ | AgentCompleteEvent → color reset |
| Agent response visible | ❌ | Response truncated and not displayed |
| Cascade to related agents | ⚠️ | Directory agents subscribe to subtree, but actual cascading depends on LLM behavior |

### Act 4: Chat (6:00-8:00) — **PARTIALLY READY**

| Requirement | Status | Notes |
|------------|--------|-------|
| Click node, type message | ✅ | Web UI chat input works |
| Message triggers agent | ✅ | AgentMessageEvent → subscription → inbox |
| Agent processes and responds | ✅ | LLM turn executes |
| Response displayed to user | ❌ | **Critical gap** — no chat message display |
| Agent-to-agent messaging | ✅ | `send_message` tool works |

### Act 5: Extensibility (8:00-10:00) — **READY**

| Requirement | Status | Notes |
|------------|--------|-------|
| Show bundle system | ✅ | bundle.yaml files are clean |
| Show tool scripts | ✅ | .pym files demonstrate Grail |
| Multi-language support | ✅ | Python, Markdown, TOML plugins with query files |

---

## 7. Critical Issues

### C1: Agent Chat Responses Are Invisible

**Location:** `core/actor.py:386-392`, `web/server.py`, `web/static/index.html`

The agent is instructed by its system prompt to "use send_message tool to address 'user'" when responding to chat. This emits an `AgentMessageEvent` with `to_agent="user"`. However:
1. The web UI has no handler for displaying messages to "user"
2. The `AgentCompleteEvent.result_summary` is truncated to 200 chars
3. The SSE stream sends the raw event but the UI just appends the event type name to the event log

**Fix:** Add a chat response display area in the web UI. Listen for `AgentMessageEvent` where `to_agent === "user"` and display the `content` field in a chat-like interface.

### C2: LSP Stdout Corruption

**Location:** `__main__.py:182-189`

When `--lsp` is used, `lsp_server.start_io` reads/writes on stdin/stdout. But `_configure_logging` installs a `StreamHandler` on the root logger which writes to stdout. Any log message will corrupt the JSON-RPC stream, crashing the neovim LSP client.

**Fix:** When `--lsp` is active, either:
- Remove the stream handler and only use file logging
- Redirect the stream handler to stderr
- Run LSP as a separate `remora lsp` command

### C3: Web Server Binds to Localhost Only

**Location:** `__main__.py:169-170`

The web server binds to `127.0.0.1` only. For a tailnet setup where the user accesses from another machine, this blocks access.

**Fix:** Add `--bind` option, default to `127.0.0.1`, document how to use `0.0.0.0` for tailnet.

---

## 8. High-Priority Improvements

### H1: Chat Response Display in Web UI

Add a chat panel that shows the conversation with the selected node. Display `AgentMessageEvent` content where `to_agent === "user"` as agent responses.

**Effort:** 2-4 hours

### H2: Fix LSP for Neovim Compatibility

Options:
1. **Separate command:** `remora lsp` that runs the LSP server standalone, connecting to a running Remora instance via HTTP API or shared SQLite
2. **Stderr logging only** when `--lsp` is active
3. **TCP transport** for pygls instead of stdio

Recommended: Option 2 (quickest) + Option 1 (cleanest long-term)

**Effort:** 2-4 hours for Option 2, 6-10 hours for Option 1

### H3: Full Agent Response Preservation

Remove the 200-char truncation on `AgentCompleteEvent.result_summary`. Either:
- Store full response in a separate field
- Add a new `AgentResponseEvent` type with the complete text
- Store in the agent's workspace (already happens via tools, but not for the final response)

**Effort:** 1-2 hours

### H4: Neovim LSP Client Configuration

Create a documented neovim LSP client configuration that:
- Starts the Remora LSP server
- Enables CodeLens display
- Shows hover metadata

**Effort:** 1-2 hours

### H5: Network Bind Configuration

Add `--bind` / `REMORA_BIND_ADDRESS` for the web server.

**Effort:** 30 minutes

---

## 9. Medium-Priority Improvements

### M1: Tool Descriptions for LLM Quality

Extract tool descriptions from Grail script comments/docstrings. Current descriptions are just "Tool: {name}" which gives the LLM no useful information.

**Effort:** 2-3 hours

### M2: Graph Clustering by File

Visual file boundaries on the graph — group nodes from the same file together with subtle background colors or convex hulls.

**Effort:** 2-3 hours

### M3: Directory Overlay in `remora.yaml`

The shipped `remora.yaml` is missing `directory: "directory-agent"` in `bundle_overlays`. Directory nodes get the system bundle only, missing directory-specific tools.

**Effort:** 5 minutes

### M4: LLM Retry Logic

Add a single retry with exponential backoff for transient LLM failures (timeouts, connection errors). This prevents a demo-killing failure from a momentary vLLM hiccup.

**Effort:** 1 hour

### M5: SSE Replay Format Consistency

The replayed events from `get_events()` have a different payload structure than live events. Normalize them.

**Effort:** 1 hour

### M6: Event Bus Error Handling

Add exception logging for failed event bus handlers. Currently, a handler that throws will cause an unhandled exception warning.

**Effort:** 30 minutes

### M7: Cleanup `rewrite_self.pym` Messaging

Change from `f"Rewrite applied: {success}"` to distinct success/failure messages.

**Effort:** 10 minutes

---

## 10. Low-Priority Improvements

### L1: Graph Continuous Layout
Use incremental ForceAtlas2 layout when nodes are added dynamically, rather than running layout only on initial load.

### L2: Agent-to-Agent Message Visualization
Animated edges on the graph when `AgentMessageEvent` flows between nodes.

### L3: Event Timeline
Scrollable timeline showing agent activity over time.

### L4: LSP Diagnostics
Agents could publish warnings/errors as LSP diagnostics shown inline in neovim.

### L5: Workspace Cleanup on Node Removal
When nodes are removed by reconciliation, their Cairn workspaces remain on disk. Add cleanup.

### L6: Depth Counter Cleanup
The `Actor._depths` dict slowly accumulates stale correlation IDs. Add periodic pruning.

### L7: Connection Pool for aiosqlite
For higher concurrency scenarios, consider multiple connections.

---

## 11. Neovim Integration Strategy

### LSP Client Setup

Neovim's built-in LSP client can attach to Remora's LSP server. The server needs to run as a subprocess spawned by neovim.

**Recommended approach:**
1. Create `remora lsp` command that runs LSP server standalone (or fix logging to stderr)
2. Neovim config uses `vim.lsp.start()` with `cmd = {"remora", "lsp", "--project-root", "."}`
3. Enable CodeLens via `vim.lsp.codelens.refresh()`

```lua
-- Example neovim config
vim.api.nvim_create_autocmd("FileType", {
  pattern = {"python", "markdown", "toml"},
  callback = function()
    vim.lsp.start({
      name = "remora",
      cmd = {"remora", "lsp", "--project-root", vim.fn.getcwd()},
      root_dir = vim.fs.root(0, {"remora.yaml"}),
      capabilities = vim.lsp.protocol.make_client_capabilities(),
    })
  end,
})
```

### Cursor Tracking for Companion Panel

The LSP spec doesn't include cursor position notifications. Options for neovim:

1. **CursorHold autocmd → HTTP POST** — Neovim sends cursor position to `POST /api/cursor` when the cursor rests for ~300ms. The web UI listens on SSE for `CursorFocusEvent`.
2. **Custom LSP notification** — Send `$/remora/cursorFocus` from neovim to the LSP server. The server maps it to the nearest node and broadcasts.
3. **Hover requests as proxy** — The LSP hover request already resolves cursor position to a node. The server could emit a `CursorFocusEvent` as a side effect of hover resolution.

**Recommended:** Option 1 (simplest, no LSP protocol extensions needed):

```lua
vim.api.nvim_create_autocmd("CursorHold", {
  callback = function()
    local cursor = vim.api.nvim_win_get_cursor(0)
    local file = vim.api.nvim_buf_get_name(0)
    -- POST to Remora web API
    vim.fn.jobstart({"curl", "-s", "-X", "POST", "http://localhost:8080/api/cursor",
      "-H", "Content-Type: application/json",
      "-d", vim.fn.json_encode({file_path = file, line = cursor[1], character = cursor[2]})
    })
  end,
})
```

### Companion Panel Display

Options:
1. **Web browser side panel** — The web UI shows companion content for the cursor-focused node
2. **Neovim floating window** — A Lua plugin fetches companion content via HTTP and displays in a floating window
3. **Neovim split** — A dedicated buffer that auto-updates with companion content

**Recommended:** Option 1 (web browser) for the demo. This gives the richest display and is already partially built. The web UI sidebar just needs to subscribe to `CursorFocusEvent` and update.

---

## 12. Recommended Action Plan

### Phase 1: Critical Fixes (Day 1 — ~4 hours)

| # | Item | Effort |
|---|------|--------|
| 1 | Fix LSP stdout corruption (redirect logging to stderr when `--lsp`) | 30 min |
| 2 | Add `--bind` option for web server | 30 min |
| 3 | Fix `remora.yaml` missing directory overlay | 5 min |
| 4 | Fix `rewrite_self.pym` messaging | 10 min |
| 5 | Remove 200-char truncation on AgentCompleteEvent (or add full-response event) | 1 hr |
| 6 | Add chat response display to web UI (AgentMessageEvent to="user") | 2-3 hrs |

### Phase 2: Neovim Integration (Day 2 — ~6 hours)

| # | Item | Effort |
|---|------|--------|
| 7 | Create `remora lsp` standalone command (connects to running instance) | 3-4 hrs |
| 8 | Write neovim LSP client config + docs | 1-2 hrs |
| 9 | Add `/api/cursor` endpoint + CursorFocusEvent | 1-2 hrs |

### Phase 3: Companion Panel (Day 3 — ~8 hours)

| # | Item | Effort |
|---|------|--------|
| 10 | Neovim CursorHold → POST /api/cursor integration | 1 hr |
| 11 | Web UI companion panel (subscribe to CursorFocusEvent, show node context) | 3-4 hrs |
| 12 | Companion content generation (agent turn or cached data) | 2-3 hrs |
| 13 | Tool description extraction for LLM quality | 2 hrs |

### Phase 4: Polish (Day 4 — ~4 hours)

| # | Item | Effort |
|---|------|--------|
| 14 | LLM retry logic | 1 hr |
| 15 | SSE format normalization | 1 hr |
| 16 | Graph layout improvements | 2 hrs |
| 17 | Event bus error handling | 30 min |

### Total Estimated Effort: ~22 hours across 4 focused days

This plan prioritizes making the existing features **visible and reliable** (Phase 1-2) before building new features (Phase 3-4). The demo can be compelling after Phase 1 alone, using only the web UI without neovim integration.

---

*End of Code Review*
