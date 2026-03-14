# Remora v2 — Code Review

**Version:** 0.5.0
**Date:** 2026-03-13
**Codebase:** ~4,500 lines source / ~4,800 lines tests
**Test results:** 201 passed, 4 skipped

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Architecture Overview](#2-architecture-overview)
3. [Module-by-Module Review](#3-module-by-module-review)
   - 3.1 Core Types & Models
   - 3.2 Database Layer
   - 3.3 Graph & Agent Stores
   - 3.4 Event System
   - 3.5 Actor & Runner
   - 3.6 Workspace Integration (Cairn)
   - 3.7 Code Discovery (Tree-sitter)
   - 3.8 Reconciler & Projections
   - 3.9 Grail Tool System
   - 3.10 LSP Server
   - 3.11 Web Server & UI
   - 3.12 CLI
   - 3.13 Bundle System
4. [Cross-Cutting Concerns](#4-cross-cutting-concerns)
5. [Test Suite Assessment](#5-test-suite-assessment)
6. [Demo Readiness Assessment](#6-demo-readiness-assessment)
7. [Strengths](#7-strengths)
8. [Issues & Recommendations](#8-issues--recommendations)

---

## 1. Executive Summary

Remora v2 is a reactive agent substrate that transforms code elements (functions, classes, methods, directories) into autonomous AI agents communicating via an event-driven architecture. The system discovers code using tree-sitter, materializes nodes into a SQLite graph, and runs LLM-powered agent turns triggered by events. It provides web and LSP surfaces for observability and interaction.

**Overall assessment: The core architecture is sound, well-structured, and ready for production-quality demos.** The codebase is clean, well-tested (201 tests, >95% core coverage), and follows consistent patterns. The main gaps are in the LSP and web integrations, which are functional but thin — sufficient for basic demos but requiring extension for the proposed "companion sidebar" demo.

---

## 2. Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                          CLI (Typer)                             │
│                   remora start / remora discover                 │
├──────────────┬──────────────────┬────────────────────────────────┤
│  Web Server  │   LSP Server     │         RuntimeServices        │
│  (Starlette) │   (pygls)        │    (central DI container)      │
├──────────────┴──────────────────┤                                │
│                                 │                                │
│  ┌───────────┐  ┌────────────┐  │  ┌──────────────────────────┐  │
│  │ EventBus  │←→│ EventStore │  │  │   FileReconciler         │  │
│  └───────────┘  │ (SQLite)   │  │  │   (watchfiles + scan)    │  │
│                 └─────┬──────┘  │  └──────────────────────────┘  │
│                       │         │                                │
│           ┌───────────▼──────┐  │  ┌──────────────────────────┐  │
│           │TriggerDispatcher │──│──│ ActorPool                │  │
│           │ (subscriptions)  │  │  │  └─ Actor (per node_id)  │  │
│           └──────────────────┘  │  │     ├─ inbox (Queue)     │  │
│                                 │  │     ├─ outbox (EventStore)│  │
│  ┌──────────────────────────┐   │  │     ├─ kernel (LLM)     │  │
│  │ NodeStore + AgentStore   │   │  │     └─ tools (Grail)    │  │
│  │ (SQLite graph)           │   │  └──────────────────────────┘  │
│  └──────────────────────────┘   │                                │
│                                 │  ┌──────────────────────────┐  │
│  ┌──────────────────────────┐   │  │ CairnWorkspaceService    │  │
│  │ Discovery (tree-sitter)  │   │  │ (per-agent sandboxed fs) │  │
│  │ Python / Markdown / TOML │   │  └──────────────────────────┘  │
│  └──────────────────────────┘   │                                │
└─────────────────────────────────┴────────────────────────────────┘
```

### Data Flow

1. **Discovery**: Tree-sitter parses source files → `CSTNode` list
2. **Projection**: `CSTNode` → `Node` (persisted to SQLite `nodes` table)
3. **Reconciliation**: `FileReconciler` detects changes (mtime + watchfiles) → emits `NodeDiscoveredEvent`, `NodeChangedEvent`, `NodeRemovedEvent`
4. **Subscription matching**: `TriggerDispatcher` resolves which agents care about an event via `SubscriptionRegistry`
5. **Actor execution**: Events routed to `Actor.inbox` → semaphore-gated LLM turn with Grail tools
6. **Fan-out**: Actor's `Outbox` emits new events → cycle continues

---

## 3. Module-by-Module Review

### 3.1 Core Types & Models (`core/types.py`, `core/node.py`)

**Quality: Good**

- Clean enum definitions (`NodeStatus`, `NodeType`, `ChangeType`) with explicit status transition validation.
- Three model tiers: `DiscoveredElement` (immutable, discovery-time), `Agent` (runtime state), and `Node` (combined view with SQLite round-trip).
- Legacy migration handled via `model_validator` for `bundle_name` → `role` rename.
- `CodeElement`/`CodeNode` aliases kept for backwards compatibility.

**Issues:**
- `Node` has both `to_element()` and `to_agent()` decomposition methods but `Node` itself is still used everywhere — the decomposition isn't fully leveraged.
- `NodeType.SECTION` and `NodeType.TABLE` are defined but `NodeType.DIRECTORY` is used extensively for reconciler-materialized directories, which is good.
- Minor: `to_row()` methods use `hasattr(data["status"], "value")` checks which are always true for enum values — could be simplified.

### 3.2 Database Layer (`core/db.py`)

**Quality: Very Good**

- Clean async wrapper over synchronous sqlite3 with `asyncio.Lock` + `asyncio.to_thread`.
- WAL mode and busy timeout configured by default — good for concurrent read/write.
- Simple API: `execute`, `fetch_one`, `fetch_all`, `insert`, `delete`, `execute_script`, `execute_many`.
- Auto-commit after each operation (individual transaction per call).

**Issues:**
- No connection pooling — single connection shared via lock. Fine for current scale but will bottleneck under heavy concurrent load.
- `execute_many` wraps multiple statements in a single transaction — good, but `execute` does individual commits which means no multi-statement atomicity outside `execute_many`.
- No WAL checkpoint management — long-running processes may accumulate WAL segments.

### 3.3 Graph & Agent Stores (`core/graph.py`)

**Quality: Good**

- `NodeStore`: CRUD + status transitions + edge management. SQL schema is well-indexed.
- `AgentStore`: Separate persistence for agent state with foreign key to `nodes` table.
- Status transition validation using `validate_status_transition()` — prevents illegal state jumps.
- Runtime schema migration for `bundle_name` → `role` column rename.

**Issues:**
- `NodeStore.create_tables()` also creates the `agents` table — duplicated with `AgentStore.create_tables()`. Both are called during `RuntimeServices.initialize()`. The `CREATE TABLE IF NOT EXISTS` prevents errors, but the duplication is confusing.
- `Edge` is a frozen dataclass but has no persistence beyond the SQLite table — no corresponding Pydantic model. This is fine but inconsistent with the rest of the model layer.
- SQL injection is theoretically possible via f-string column interpolation in `upsert_node()`, but since columns come from `model_dump()` keys (not user input), it's safe in practice.

### 3.4 Event System (`core/events/`)

**Quality: Very Good**

- **Types** (`types.py`): Clean event hierarchy rooted at `Event` base class. Auto-populates `event_type` from class name. `to_envelope()` provides clean serialization.
- **Bus** (`bus.py`): In-memory pub/sub with MRO-aware dispatch. Supports type-specific subscriptions, global handlers, and async streaming via `stream()` context manager. Clean and minimal.
- **Store** (`store.py`): Append-only SQLite event log with dual fan-out: emits to in-memory `EventBus` AND dispatches through `TriggerDispatcher` for subscription matching.
- **Subscriptions** (`subscriptions.py`): Pattern-based matching with event_type, from_agents, to_agent, and path_glob filters. Cached in memory with invalidation on mutation.
- **Dispatcher** (`dispatcher.py`): Routes events to agents via a pluggable `router` callback. Clean separation.

**Issues:**
- `EventBus.emit()` is sequential — each handler is awaited one at a time. Under high event throughput, a slow handler blocks all subsequent handlers.
- `SubscriptionRegistry._rebuild_cache()` loads ALL subscriptions on every cache miss. Could use incremental updates for large subscription counts.
- No event schema versioning or migration strategy.
- `EventStore` exposes `connection` and `lock` properties — leaking internal db state. Only used by tests but should be refactored.

### 3.5 Actor & Runner (`core/actor.py`, `core/runner.py`)

**Quality: Good**

- **Actor**: Per-agent processing loop with inbox queue, outbox emitter, cooldown policy, and depth tracking. Clean lifecycle management (`start()`/`stop()`).
- **Outbox**: Write-through tagging point (not a buffer) — events reach EventStore immediately. Good for consistency.
- **RecordingOutbox**: Test double — well-designed for unit testing.
- **ActorPool**: Lazy actor creation, dispatcher routing, idle eviction (300s timeout). Clean actor lifecycle management.

**Issues:**
- `Actor._execute_turn()` is a ~120-line method doing: status transition → workspace access → bundle config loading → prompt building → kernel creation → LLM call → result processing → error handling → cleanup. This is the most complex method in the codebase and would benefit from decomposition.
- `Actor._read_bundle_config()` explicitly validates each key (`system_prompt`, `system_prompt_extension`, `model`, `max_turns`, `prompts`) — any new bundle.yaml key requires code changes. Consider a more permissive loading approach.
- `rewrite_self.pym` calls `propose_rewrite` but `TurnContext` exposes `apply_rewrite` — there's a naming mismatch. The tool script won't actually work because `propose_rewrite` isn't in the capabilities dict.
- Depth tracking in `finally` block decrements depth, but this happens after the turn completes — the depth check in `_should_trigger` only prevents *new* triggers, not in-flight ones.
- `ActorPool.run_forever()` sleeps 1 second between eviction checks — this is the only thing it does, making it essentially a timer. The actual work happens in Actor tasks.

### 3.6 Workspace Integration (`core/workspace.py`)

**Quality: Good**

- `AgentWorkspace`: Per-agent sandboxed filesystem backed by Cairn. Clean async API with per-workspace locking.
- `CairnWorkspaceService`: Manages workspace lifecycle, caching, and bundle provisioning. Template merging with ordered overlay support.
- KV store operations (`kv_get`, `kv_set`, `kv_delete`, `kv_list`) recently added and well-integrated.

**Issues:**
- `_safe_id()` uses SHA-1 for filesystem naming — fine for this purpose but technically deprecated for security contexts.
- `provision_bundle()` reads and re-writes files every time (no caching of already-provisioned bundles). This is called during reconciliation which can be frequent.
- `close()` clears dictionaries but doesn't `await` individual workspace cleanup — relies on `_manager.close_all()`.
- Lock contention: Each `AgentWorkspace` operation acquires its lock independently. Sequential operations (read-modify-write) aren't atomic.

### 3.7 Code Discovery (`code/discovery.py`, `code/languages.py`)

**Quality: Very Good**

- Clean plugin architecture via `LanguagePlugin` protocol. Python, Markdown, and TOML plugins built-in.
- Tree-sitter query files (`.scm`) are externalized and overridable via `query_paths` config.
- Hierarchical parent resolution via tree walking. Deterministic node IDs (`file_path::full_name`).
- LRU caching for parsers and queries — good for performance.

**Issues:**
- `discover()` creates a new `LanguageRegistry` on every call instead of reusing one. The registry is lightweight but the pattern is wasteful.
- `_parse_file()` reads the entire file into memory as bytes — fine for typical source files but no size guard.
- Duplicate node ID resolution (`@start_byte` suffix) is fragile — if two identically-named functions exist at different byte offsets after a rename, old IDs become orphans.
- `_build_name_from_tree()` accepts `name_node` parameter but immediately `del`s it — unused parameter kept for interface consistency.

### 3.8 Reconciler & Projections (`code/reconciler.py`, `code/projections.py`)

**Quality: Good**

- `FileReconciler`: Full startup scan + continuous watchfiles-based reconciliation. Handles add/change/delete with proper event emission.
- Directory materialization derives directory nodes from file paths — elegant approach for implicit hierarchy.
- Bundle provisioning and subscription registration are co-located with node lifecycle — keeps the system consistent.
- `_on_content_changed()` subscriber enables immediate reconciliation from upstream events (e.g., LSP did_save).

**Issues:**
- `_materialize_directories()` is the longest method (~100 lines) and handles both creation and updates with complex conditional logic. Would benefit from splitting.
- `_subscriptions_bootstrapped` and `_bundles_bootstrapped` flags create a "first run is different" code path that adds complexity.
- `reconcile_cycle()` acquires no lock — concurrent calls could interleave. In practice, only the initial `full_scan()` and `run_forever()` call it, but `_on_content_changed` also triggers reconciliation.
- `_collect_file_mtimes()` uses `st_mtime_ns` for change detection. This misses same-mtime changes (e.g., `touch` immediately after write) but is practical.
- `_stop_event()` creates an `asyncio.Task` that's never stored — it could be garbage collected or leak.

### 3.9 Grail Tool System (`core/grail.py`)

**Quality: Good**

- `GrailTool` wraps Grail scripts as structured-agents tools. Clean schema generation from Grail input declarations.
- Content-hash caching of compiled scripts avoids re-parsing identical tools.
- `discover_tools()` loads `.pym` files from `_bundle/tools/` in agent workspaces.
- Capabilities filtering: only passes externals that the script actually declares with `@external`.

**Issues:**
- `_load_script_from_source()` writes to a temp directory for every cache miss — Grail's `load()` requires a file path. This is a design constraint from Grail.
- `_SCRIPT_CACHE` is module-level and never cleared — memory leak in long-running processes with many unique scripts.
- `GrailTool.execute()` catches all exceptions and returns `ToolResult(is_error=True)` — good for isolation, but stack traces are logged at exception level which could be noisy.
- Type mapping (`_TYPE_MAP`) only handles `str`, `int`, `float`, `bool` — no support for `list`, `dict`, or complex types.

### 3.10 LSP Server (`lsp/server.py`)

**Quality: Adequate — but thin**

- Implements four LSP features: `textDocument/codeLens`, `textDocument/hover`, `textDocument/didSave`, `textDocument/didOpen`.
- CodeLens shows node status inline. Hover shows node metadata. Save/open events forward to EventStore.
- `_remora_handlers` dict exposes handlers for direct testing — pragmatic.

**Issues:**
- **No `textDocument/didChange` handler** — cursor movement tracking is NOT implemented. This is critical for the proposed demo.
- **No custom commands** — `remora.showNode` command is referenced in CodeLens but never registered. Clicking a code lens would fail.
- **No cursor position tracking** — there's no `textDocument/didFocus`, `window/didChangeActiveTextEditor`, or custom notification for cursor position. The LSP spec doesn't natively support "cursor moved" events; this would need a custom notification or polling via an editor extension.
- **No WebSocket/SSE bridge** — LSP state doesn't flow to the web server. There's no mechanism for the web frontend to know which file/line the cursor is on.
- `_uri_to_path()` has redundant path handling — the `file://` prefix removal is done twice (once via urlparse, once via removeprefix).
- `_find_node_at_line()` returns the narrowest node but doesn't handle overlapping decorator nodes well.
- The LSP server is optional (`pygls` is in `[project.optional-dependencies].lsp`) but the `create_lsp_server()` import is unconditional in `__init__.py`.
- **Not started by the CLI** — `remora start` only starts the web server and runner, not the LSP server. There's no integration point.

### 3.11 Web Server & UI (`web/server.py`, `web/static/index.html`)

**Quality: Good for MVP**

- Starlette app with REST API (`/api/nodes`, `/api/edges`, `/api/chat`, `/api/events`) and SSE streaming (`/sse`).
- Chat endpoint sends `AgentMessageEvent(from_agent="user", to_agent=node_id)` — clean integration with event system.
- SSE includes event replay for late joiners.
- Frontend: Force-directed graph (Sigma.js + graphology), node detail sidebar, chat input, live event log.

**Issues:**
- **No cursor focus endpoint** — no API for receiving or broadcasting cursor position from an editor.
- **No "companion node" sidebar** — the sidebar shows node details and a chat box, but there's no concept of an agent-authored companion view.
- Graph layout uses random initial positions + 30 ForceAtlas2 iterations — layout quality depends on node count and may be unstable.
- No authentication or CORS configuration — fine for local use.
- `_INDEX_HTML` is loaded at import time — file changes require process restart.
- `api_node` uses path parameter `{node_id:path}` which correctly handles `/` in node IDs (like `src/app.py::func`).
- SSE `event_generator()` has an inner `if once: return` after replay — useful for testing but the generator's `await request.is_disconnected()` could block indefinitely if the client stays connected.

### 3.12 CLI (`__main__.py`)

**Quality: Good**

- Two commands: `start` (full runtime) and `discover` (scan-only).
- Clean async orchestration: runner + reconciler + web server as managed asyncio tasks.
- Rotating file logging + optional event activity logging.
- Graceful shutdown with task cancellation.

**Issues:**
- `--run-seconds` for smoke testing is nice but doesn't test the LSP path.
- No `remora lsp` command to start the LSP server — it's completely disconnected from the CLI.
- `_configure_file_logging()` compares handler paths with `Path.resolve()` to avoid duplicates — defensive but the `OSError` catch suggests fragility.

### 3.13 Bundle System (`bundles/`)

**Quality: Good**

- Three-tier overlay: `system` (always loaded) → role-specific (e.g., `code-agent`, `directory-agent`).
- Bundle YAML configures: `system_prompt`, `system_prompt_extension`, `prompts.chat`, `prompts.reactive`, `model`, `max_turns`.
- Grail `.pym` scripts provide tools. System tools (12 scripts) cover: messaging, subscriptions, reflection, workspace, and graph queries.
- Role-specific tools: code-agents get `rewrite_self` + `scaffold`; directory-agents get `list_children`, `get_parent`, `broadcast_children`, `summarize_tree`.

**Issues:**
- `rewrite_self.pym` references `propose_rewrite` external which doesn't exist in `TurnContext.to_capabilities_dict()`. The actual capability is `apply_rewrite`. This tool will fail at runtime.
- `scaffold.pym` — not reviewed but likely has similar external reference issues.
- `kv_get.pym` and `kv_set.pym` are simple wrappers — the overhead of Grail script parsing for trivial delegation is questionable.
- No tool documentation beyond the script source — agents discover tool capabilities from Grail's `Input()` declarations only.

---

## 4. Cross-Cutting Concerns

### Configuration
- Single `Config` (Pydantic BaseSettings) loaded from `remora.yaml` with env var expansion.
- Frozen model — no runtime mutation. Clean.
- Legacy field migration (`bundle_mapping` → `bundle_overlays`, `swarm_root` → `workspace_root`).

### Error Handling
- Broad `except Exception` (with `# noqa: BLE001`) at all boundary points: actor turn, tool execution, reconciler watch, content change handler.
- This is the right pattern for a long-running system — individual failures shouldn't crash the runtime.
- Errors are logged at `exception` level with full tracebacks.

### Concurrency
- Global semaphore (`max_concurrency`) limits concurrent LLM turns.
- Per-actor inbox queue ensures sequential processing within each agent.
- Cooldown and depth limits prevent runaway event cascades.
- SQLite access is serialized via `asyncio.Lock`.

### Naming Consistency
- Recent refactor renamed `bundle_name` → `role`, `AgentNode` → `Node`, `AgentRunner` → `ActorPool`.
- Backward-compatible aliases maintained (`CodeNode`, `AgentActor`, `AgentRunner`, `AgentContext`).
- Naming is internally consistent within the current version.

### Dependencies
- Core: Pydantic, PyYAML, tree-sitter (with language packages), SQLite (stdlib)
- Custom: structured-agents, cairn, grail, fsdantic — all from Bullish-Design GitHub
- Web: Starlette + uvicorn
- LSP: pygls + lsprotocol (optional)
- Dev: pytest, pytest-asyncio, ruff

---

## 5. Test Suite Assessment

**201 tests passed, 4 skipped, in 16.4 seconds.**

### Coverage by Module

| Module | Tests | Lines | Quality |
|--------|-------|-------|---------|
| Actor | 689 | test_actor.py | Thorough — covers lifecycle, outbox, build_prompt, bundle config |
| Reconciler | 353 | test_reconciler.py | Good — full scan, incremental, deletes, directories |
| Externals | 342 | test_externals.py | Good — all capabilities, broadcast patterns |
| Grail | 240 | test_grail.py | Good — schema generation, tool execution, capabilities filtering |
| Workspace | 221 | test_workspace.py | Good — read/write/list/KV operations |
| Web Server | 195 | test_web_server.py | Good — all endpoints, SSE streaming, chat |
| Graph | 182 | test_graph.py | Good — CRUD, edges, status transitions |
| Discovery | 160 | test_discovery.py | Good — multi-language, hierarchy, deduplication |
| Integration (E2E) | 333 | test_e2e.py | Comprehensive — full pipeline tests |
| Integration (Grail Runtime) | 150 | test_grail_runtime_tools.py | Good — tool script execution |
| Integration (LLM Turn) | 483 | test_llm_turn.py | Thorough — full turn simulation |

### Test Quality
- Factory helpers (`make_node`, `make_cst`, `write_bundle_templates`) reduce boilerplate.
- Tests use real SQLite (via `tmp_path`) — no mocking of the database layer.
- Integration tests simulate full pipeline from discovery to agent execution.
- 4 skipped tests are likely for optional dependencies or platform-specific features.

### Gaps
- No load/stress tests (there's a `test_performance.py` at 78 lines but it's basic).
- No tests for concurrent actor execution or semaphore contention.
- LSP tests (`test_lsp_server.py`, 86 lines) are thin — only basic handler invocation.
- No end-to-end test that starts the web server and makes HTTP requests.

---

## 6. Demo Readiness Assessment

### Proposed Demo: Cursor-Following Companion Sidebar

The demo concept: LSP tracks cursor movement in the editor → web page sidebar shows an agent-created "companion node" that updates as the cursor moves between code elements.

#### What Remora Provides Today

| Capability | Status | Notes |
|-----------|--------|-------|
| Code discovery (functions/classes/methods) | **Complete** | Tree-sitter based, multi-language |
| Node graph persistence | **Complete** | SQLite with full CRUD |
| Event-driven agent triggers | **Complete** | Subscription-based dispatch |
| LLM-powered agent turns | **Complete** | structured-agents kernel |
| Agent workspace (sandboxed fs + KV) | **Complete** | Cairn-backed |
| Web UI with live graph | **Complete** | Sigma.js + SSE streaming |
| Chat with individual agents | **Complete** | Web API + event routing |
| Real-time event streaming | **Complete** | SSE with replay |
| LSP code lens (status badges) | **Complete** | Shows idle/running/error per node |
| LSP hover (node metadata) | **Complete** | Shows ID, type, status, location |
| LSP save/open → event forwarding | **Complete** | ContentChangedEvent emission |
| **LSP cursor position tracking** | **Not Implemented** | No didChange/cursor handler |
| **LSP → Web bridge (cursor focus)** | **Not Implemented** | No shared state or API |
| **Companion node concept** | **Not Implemented** | No agent-authored sidebar content |
| **Agent-generated UI content** | **Not Implemented** | Agents write to workspace, not to web |

#### What Needs to Be Built for the Demo

1. **Cursor Focus Tracking (LSP side)**
   - Add `textDocument/didChange` handler or a custom notification to track cursor position.
   - Resolve cursor position → node_id mapping (already have `_find_node_at_line`).
   - Emit a `CursorFocusEvent` with `file_path`, `line`, `node_id`.

2. **Cursor Focus → Web Bridge**
   - Add `/api/cursor` endpoint (POST from LSP or editor extension, GET for web).
   - Store current cursor focus in-memory or in EventStore.
   - SSE broadcast `CursorFocusEvent` to web clients.

3. **Companion Node / Sidebar Content**
   - When cursor focus changes, trigger a "companion" agent turn for the focused node.
   - Agent writes structured content to its workspace (e.g., `companion/summary.md`).
   - New web API endpoint `/api/nodes/{node_id}/companion` reads companion content.
   - Sidebar auto-fetches companion content on `CursorFocusEvent`.

4. **Editor Extension (VS Code)**
   - Need a VS Code extension that:
     - Starts the Remora LSP server.
     - Sends cursor position changes to the LSP server or directly to the web API.
     - Opens a webview panel showing the companion sidebar.

#### Effort Estimate

| Component | Effort | Complexity |
|-----------|--------|------------|
| CursorFocusEvent + LSP handler | Small | Low |
| Web API for cursor focus | Small | Low |
| Companion content rendering | Medium | Medium |
| Agent companion turn logic | Medium | Medium — needs prompt engineering |
| VS Code extension (basic) | Medium-Large | Medium — boilerplate heavy |
| **Total** | **2-4 days focused work** | |

#### Alternative Demo Approaches (Less Building Required)

**Option A: "Chat with Your Code" (minimal new code)**
- Use existing web UI as-is
- Demo: Open web UI → graph populates → click a function node → chat with it → agent responds
- Show live SSE events as agent processes
- Demonstrate agent-to-agent messaging
- **Wow factor:** Moderate. Shows the reactive event system well.

**Option B: "Live Code Change Cascade" (no new code)**
- Start Remora watching a project
- Edit a function in the editor → watchfiles detects change → reconciler updates node → event fires → agent activates → agent examines the change and updates its state
- Web UI shows nodes lighting up in real-time as agents activate
- **Wow factor:** Good. Very visual with the graph animations.

**Option C: "Full Companion Sidebar" (proposed demo, requires building)**
- Needs VS Code extension + LSP cursor tracking + companion agent + web sidebar
- **Wow factor:** Excellent, but significant build effort.

**Recommended:** Combine Option A + B for immediate impact, then build toward Option C incrementally.

---

## 7. Strengths

1. **Clean architecture**: Clear separation between discovery, persistence, events, execution, and surfaces. The `RuntimeServices` container provides clean dependency injection.

2. **Event-driven consistency**: Everything flows through `EventStore` → `EventBus` + `TriggerDispatcher`. No direct coupling between components.

3. **Pragmatic database design**: SQLite with WAL mode is the right choice for a single-process, local-first system. No ORM overhead.

4. **Extensible language support**: Plugin-based tree-sitter discovery with external query overrides. Adding a new language requires only a `LanguagePlugin` class and a `.scm` query file.

5. **Actor model with policy**: Per-actor cooldown and depth tracking prevent runaway cascades without global coordination.

6. **Bundle overlay system**: Three-tier configuration (system → role → agent instance) provides good defaults with full customizability.

7. **Comprehensive test suite**: 201 tests covering every module, with both unit and integration tests. Factory helpers reduce boilerplate.

8. **Grail tool isolation**: Tool scripts run in sandboxed workspaces with filtered capabilities — agents can't access each other's state directly.

9. **SSE streaming**: Real-time event propagation to web clients with replay for late joiners.

10. **Small codebase**: ~4,500 lines for this level of functionality is impressive. No bloat.

---

## 8. Issues & Recommendations

### Critical (must fix)

1. **`rewrite_self.pym` broken**: References `propose_rewrite` external which doesn't exist. Should reference `apply_rewrite` from `TurnContext`. This is a runtime error waiting to happen.

2. **LSP server not started by CLI**: `remora start` doesn't launch the LSP server. There's no way to use it without custom integration code. Need either a `remora lsp` command or `--lsp` flag on `start`.

### High Priority

3. **`Actor._execute_turn()` too complex**: 120-line method handling 7+ responsibilities. Extract: `_build_context()`, `_resolve_tools()`, `_run_llm_turn()`, `_handle_completion()`, `_handle_error()`.

4. **NodeStore/AgentStore table duplication**: Both create the `agents` table. Consolidate to one owner.

5. **`_SCRIPT_CACHE` memory leak**: Module-level dict never cleared. Add LRU eviction or periodic cleanup.

6. **Reconciler race condition**: `_on_content_changed()` and `run_forever()` can trigger concurrent `_reconcile_file()` calls for the same file. Add per-file locking or deduplication.

### Medium Priority

7. **EventBus sequential emission**: `emit()` awaits each handler sequentially. Consider `asyncio.gather()` for independent handlers.

8. **Missing `textDocument/didChange` LSP handler**: Required for any cursor-tracking demo. Should at least log/track cursor position.

9. **Web UI graph stability**: Random initial positions + fixed iteration count produces inconsistent layouts. Consider deterministic initial layout (e.g., hierarchy-based) or continuous FA2.

10. **No request validation on web API**: `/api/chat` validates `node_id` and `message` presence but doesn't verify the node exists. `/api/nodes/{node_id:path}` returns 404 correctly.

### Low Priority

11. **Backward-compat aliases**: `CodeElement`, `CodeNode`, `AgentActor`, `AgentRunner`, `AgentContext` — consider a deprecation timeline.

12. **`_uri_to_path()` redundancy**: Dual path handling in LSP server.

13. **Bundle provisioning on every reconcile**: Consider fingerprinting to skip re-provisioning unchanged bundles.

14. **`_stop_event()` task leak**: The asyncio task created for stop signaling is never stored or cancelled.

15. **Tree-sitter query hardcoding**: While queries are overridable, the default query path (`code/queries/`) is hardcoded relative to the package. Consider making this configurable.

---

*End of Code Review*
