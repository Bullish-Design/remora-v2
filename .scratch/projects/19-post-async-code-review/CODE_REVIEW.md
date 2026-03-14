# Remora v2 — Post-Async Code Review

## Table of Contents

1. **[Concept & Vision](#1-concept--vision)** — What Remora is and the problem it solves
2. **[Architecture Overview](#2-architecture-overview)** — Layered system design, data flow, key abstractions
3. **[Module-by-Module Analysis](#3-module-by-module-analysis)** — Deep review of every source module
   - 3.1 Core Types & Models (`core/types.py`, `core/node.py`)
   - 3.2 Configuration (`core/config.py`)
   - 3.3 Database Layer (`core/db.py`)
   - 3.4 Event System (`core/events/`)
   - 3.5 Graph & Agent Stores (`core/graph.py`)
   - 3.6 Actor Model (`core/actor.py`)
   - 3.7 Actor Pool / Runner (`core/runner.py`)
   - 3.8 Kernel Integration (`core/kernel.py`)
   - 3.9 Agent Externals (`core/externals.py`)
   - 3.10 Workspace (`core/workspace.py`)
   - 3.11 Grail Tool System (`core/grail.py`)
   - 3.12 Code Discovery (`code/discovery.py`, `code/languages.py`, `code/paths.py`)
   - 3.13 Projections (`code/projections.py`)
   - 3.14 File Reconciler (`code/reconciler.py`)
   - 3.15 Web Server (`web/server.py`)
   - 3.16 LSP Server (`lsp/server.py`)
   - 3.17 CLI Entry Point (`__main__.py`)
   - 3.18 Bundle System (`bundles/`)
4. **[Cross-Cutting Concerns](#4-cross-cutting-concerns)** — Patterns spanning multiple modules
5. **[Test Suite Assessment](#5-test-suite-assessment)** — Coverage, quality, gaps
6. **[Issues & Recommendations](#6-issues--recommendations)** — Prioritized list of fixes and improvements

---

## 1. Concept & Vision

Remora is a **reactive agent swarm substrate** — it transforms a codebase into a living network of autonomous AI agents. Every discoverable code element (function, class, method, markdown section, TOML table, directory) becomes a **node** in a persistent graph, and each node can be activated as an **agent** that reasons about, monitors, and rewrites its own source code.

### Core Idea

Traditional code analysis tools are passive — they run on demand and produce static reports. Remora inverts this: code elements are always-on entities that **react** to changes in real time. When a file changes, the affected nodes are notified via events, triggering agent turns that can update internal state, communicate with sibling nodes, or propose rewrites.

### Key Design Principles

- **Event-sourced truth**: Every state change is an event. The EventStore is the authoritative log; the node graph is a materialized view.
- **Per-element agents**: Each code element gets its own sandboxed workspace (via Cairn), tool inventory, and LLM context. This is radically fine-grained — a single function is an agent.
- **Pluggable tools via Grail**: Agent capabilities are defined in `.pym` scripts (Grail language), not hardcoded Python. Tools are discoverable, sandboxed, and use an `@external` bridge to access runtime capabilities.
- **Bundle-based configuration**: Agent behavior is configured through layered YAML bundles (system + role overlay), enabling different personas for code agents vs. directory agents.
- **Multi-surface**: The same runtime serves a web UI (Starlette + SSE), an LSP server (pygls), and a CLI (Typer).

### What It Enables

- Autonomous codebase monitoring with reactive agent swarms
- Agent-to-agent communication and coordination
- Self-modifying code proposals through the `rewrite_self` tool
- Real-time editor integration via LSP (code lenses, hover info)
- User-agent chat through web UI or direct messaging

---

## 2. Architecture Overview

### System Layers

```
┌─────────────────────────────────────────────────┐
│  Surfaces: CLI (__main__) │ Web (Starlette) │ LSP│
├─────────────────────────────────────────────────┤
│  RuntimeServices (DI container)                  │
├────────────┬────────────┬───────────────────────┤
│ ActorPool  │ Reconciler │ Workspace Service      │
│ (runner)   │ (code/)    │ (Cairn)                │
├────────────┴────────────┴───────────────────────┤
│  EventStore ─> EventBus + TriggerDispatcher      │
├─────────────────────────────────────────────────┤
│  NodeStore / AgentStore (graph.py)               │
├─────────────────────────────────────────────────┤
│  aiosqlite (WAL mode)                            │
└─────────────────────────────────────────────────┘
```

### Data Flow

1. **Discovery**: Tree-sitter parses source files → `CSTNode` list
2. **Projection**: CSTNodes are projected into `Node` models, persisted to `NodeStore`
3. **Bundle Provisioning**: Each node gets a Cairn workspace with system + role tools
4. **Reconciliation**: File watcher detects changes → incremental re-discovery → diff → events
5. **Event Dispatch**: Events are persisted → emitted on EventBus → matched against subscriptions → routed to actor inboxes
6. **Agent Turns**: Actor dequeues event → acquires semaphore → loads bundle config → discovers tools → runs LLM kernel → emits result events

### Key Abstractions

| Abstraction | Role |
|-------------|------|
| `Node` | Unified model: discovered element + agent state |
| `Actor` | Per-node asyncio task with inbox, outbox, and policy state |
| `ActorPool` | Lazy actor registry, routes events to inboxes |
| `EventStore` | Append-only SQLite log + fan-out to bus and dispatcher |
| `EventBus` | In-memory pub/sub for live event streaming |
| `TriggerDispatcher` | Matches events to subscriptions, routes to actor inboxes |
| `CairnWorkspaceService` | Manages per-agent sandboxed filesystems |
| `GrailTool` | Wrapper that bridges Grail scripts to structured-agents tool interface |
| `TurnContext` | Per-turn API surface available to agent tool scripts via externals |
| `FileReconciler` | Watches source files, diffs nodes, emits lifecycle events |

### External Dependencies

| Dependency | Purpose |
|------------|---------|
| `structured-agents` | LLM agent kernel (client, message loop, tool execution) |
| `cairn` | Sandboxed workspace filesystem per agent |
| `grail` | Tool script language (.pym files) with `@external` bridge |
| `fsdantic` | Filesystem data models (ViewQuery, etc.) |
| `tree-sitter` + language packs | Source code parsing and query-based node discovery |
| `aiosqlite` | Async SQLite for persistence |
| `pydantic` / `pydantic-settings` | Data models and config |
| `starlette` + `uvicorn` | Web API and SSE |
| `pygls` + `lsprotocol` | LSP server |
| `watchfiles` | Filesystem change detection |

---

## 3. Module-by-Module Analysis

### 3.1 Core Types & Models

**`core/types.py`** (54 lines) — Clean, minimal. Defines `NodeStatus`, `NodeType`, `ChangeType` enums and a status transition validator. Well-structured.

**`core/node.py`** (112 lines) — Three models: `DiscoveredElement` (immutable code structure), `Agent` (agent state), and `Node` (unified join of both).

**Issues:**

- **`Node` duplicates fields from both `DiscoveredElement` and `Agent`**: There are 14 fields on `Node`, manually mirrored in `to_element()` and `to_agent()`. This is a maintenance burden — any field addition must be updated in 3 places.
- **`sqlite3.Row` import in `from_row`**: The type hint references `sqlite3.Row`, but the actual rows come from `aiosqlite.Row`. This works because `aiosqlite.Row` is compatible, but it's misleading.
- **`to_row()` uses fragile `hasattr` checks**: `hasattr(data["status"], "value")` — this is defensive against receiving a plain string vs. an enum value. Since Pydantic should always produce enum instances, the hasattr dance is unnecessary noise.
- **`DiscoveredElement` appears unused outside `to_element()`**: Grepping shows `DiscoveredElement` is not used as a standalone type anywhere in the codebase. It exists as a concept but has no practical consumer.

### 3.2 Configuration

**`core/config.py`** (148 lines) — Pydantic-settings based config with YAML loading and `${VAR:-default}` env expansion. Clean design.

**Issues:**

- **No `model_validator` used despite import**: `model_validator` is imported but never used. Dead import.
- **`_find_config_file` walks up directories**: Good UX for CLI usage, but the function is only used when `path=None`. There's no caching, so each call re-walks.
- **`Config` has `model_config = SettingsConfigDict(frozen=True)`**: This is correct and prevents accidental mutation. Good.
- **`discovery_languages` is `tuple[str, ...] | None`**: Having `None` mean "all languages" is an implicit convention. A sentinel like `ALL` would be clearer but this is minor.

### 3.3 Database Layer

**`core/db.py`** (22 lines) — Minimal factory: opens aiosqlite connection with WAL mode and row factory. Clean.

**Issues:**

- **No `PRAGMA foreign_keys=ON`**: The `agents` table has a `FOREIGN KEY` constraint referencing `nodes(node_id)`, but without `foreign_keys=ON`, SQLite does not enforce it. This means the FK constraint in `graph.py:AgentStore.create_tables()` is decorative.
- **No connection pooling or lifecycle management**: Single connection is shared across all stores, event store, and subscriptions. For the current architecture (single-process, cooperative async), this works, but `commit()` calls scattered across every store operation mean high commit frequency.

### 3.4 Event System

**`core/events/types.py`** (129 lines) — Clean event hierarchy using Pydantic BaseModel. Auto-tagging of `event_type` from class name is elegant.

**`core/events/bus.py`** (79 lines) — In-memory event dispatch with MRO-based inheritance matching and async stream support.

**`core/events/dispatcher.py`** (57 lines) — Routes events to agent inboxes via subscription matching. Simple and focused.

**`core/events/subscriptions.py`** (139 lines) — SQLite-backed subscription registry with event_type-indexed cache.

**`core/events/store.py`** (127 lines) — Append-only event log with bus emission and trigger dispatch.

**Issues:**

- **`EventBus._dispatch_handlers` creates tasks for every coroutine handler**: This means N concurrent tasks for N handlers per event. For high-volume events, this creates significant task churn. There's no error handling for individual handler failures — a failing handler's exception is silently swallowed by `asyncio.gather`.
- **`EventStore.append()` commits after every single event**: This is correct for durability but may be a performance bottleneck under high event rates. Batch commits would help but add complexity.
- **`SubscriptionRegistry._rebuild_cache` loads ALL subscriptions**: Fine for small agent counts, but with thousands of nodes each having 2-3 subscriptions, this becomes a full table scan. The cache invalidation strategy (set to None on any mutation) is simple but aggressive.
- **`SubscriptionPattern.matches()` uses `getattr` for `from_agent`, `to_agent`, `path`**: This works but creates a duck-typing dependency — any event *might* have these fields. It would be cleaner if subscription matching operated on the event envelope (which is a dict) rather than probing the event object.
- **`to_envelope()` excludes event-type-specific fields then re-accesses them**: The pattern is: serialize to envelope (excluding base fields), then separately pull `payload.get("agent_id")` etc. This works but the store is reaching into the payload dict to extract fields that were on the original event object — a slight code smell.

### 3.5 Graph & Agent Stores

**`core/graph.py`** (305 lines) — `NodeStore` and `AgentStore` provide SQLite-backed CRUD with edge management.

**Issues:**

- **Redundant status tracking**: Both `NodeStore` and `AgentStore` track status independently. `Actor._reset_agent_state()` must update both. If they ever diverge, the system is in an inconsistent state. The code has logic to keep them in sync, but this is a design smell — status should live in one place.
- **`upsert_node` uses INSERT OR REPLACE**: This silently replaces on conflict, which is correct for the use case but means accidental ID collisions would silently overwrite data.
- **`list_nodes` builds SQL with string formatting**: The `f"SELECT * FROM nodes{where_clause}"` pattern is safe here (conditions use parameter binding), but the f-string SQL construction is fragile for future modifications.
- **`transition_status` does a read-then-write**: Fetches the node, checks validity, then updates. This is not atomic — concurrent operations could race. With single-connection aiosqlite, this is mitigated but not impossible.
- **`Edge` is a frozen dataclass**: Good. But edges have no metadata (weight, timestamp, properties). This limits the graph's expressiveness.
- **No cascading deletes for parent-child relationships**: Deleting a parent node leaves orphaned children with stale `parent_id` references.

### 3.6 Actor Model

**`core/actor.py`** (510 lines) — The largest and most complex module. Implements the per-agent actor with inbox processing, LLM turns, and lifecycle management.

**Issues:**

- **`RecordingOutbox` is a test double in production code**: It's used only in tests but lives in the main module. This is a minor layering concern.
- **`_should_trigger` cooldown check uses wall clock**: `time.time() * 1000.0` compared against `trigger_cooldown_ms`. This is correct but the float multiplication for ms conversion is inelegant — could use `time.monotonic()` for robustness against clock adjustments.
- **`_depths` dict grows unboundedly**: Depth entries are cleaned up after a turn completes, but if many unique correlation IDs trigger without completing, the dict grows. The `# Clean stale depth entries` comment suggests this was noticed but the cleanup was deferred.
- **`_read_bundle_config` is a static method that reads from workspace**: Correct separation, but the extensive validation logic (checking each key type, parsing max_turns, filtering prompts) is doing what a Pydantic model should do. A `BundleConfig` model would be cleaner.
- **`_build_prompt` constructs the entire user message inline**: The prompt template is hardcoded as f-string construction. For a system that emphasizes configurability via bundles, the prompt construction is surprisingly rigid.
- **`_execute_turn` is doing too many things**: It handles startup, config reading, context creation, tool discovery, kernel creation, message building, execution, completion, error handling, and cleanup — all in one method. While it's broken into helper methods, the orchestration logic is still dense.
- **`_resolve_maybe_awaitable` is a workaround**: The comment-free static method suggests `discover_tools` might return either a coroutine or a list depending on context. This ambiguity should be resolved at the source.

### 3.7 Actor Pool / Runner

**`core/runner.py`** (115 lines) — Clean actor registry with lazy creation and idle eviction.

**Issues:**

- **`run_forever` sleeps in a 1-second loop**: The main loop does `await asyncio.sleep(1.0)` then evicts idle actors. This is a polling pattern where an event-driven approach would be more elegant.
- **`_evict_idle` default of 300 seconds is hardcoded**: Not configurable. Should be in Config.
- **No back-pressure mechanism**: If events arrive faster than actors can process them, inbox queues grow unboundedly. There's no queue size limit or overflow policy.
- **Actor creation is synchronous within `_route_to_actor`**: The `get_or_create_actor` call is fine, but `actor.start()` creates an asyncio.Task. If called from a non-async context (the dispatcher router is a sync callback), this relies on an existing event loop — which is guaranteed in this architecture, but the sync-vs-async boundary is subtle.

### 3.8 Kernel Integration

**`core/kernel.py`** (59 lines) — Thin wrapper around `structured_agents.AgentKernel`. Clean delegation.

**Issues:**

- **`extract_response_text` uses duck typing**: `hasattr(result, "final_message")` — depends on the structured-agents API shape. A version change could silently break this.
- **`api_key or "EMPTY"`**: Passing "EMPTY" as a fallback API key for local models is pragmatic but should be documented.

### 3.9 Agent Externals

**`core/externals.py`** (303 lines) — The API surface available to agent tools. Large, flat class with many async methods.

**Issues:**

- **`TurnContext` is a god object**: 24 methods exposed via `to_capabilities_dict()`. It's the entire runtime API surface for agents. While this is necessary for the Grail bridge, the class has no logical grouping — filesystem ops, KV ops, graph ops, event ops, and messaging are all flat methods.
- **`search_content` loads all file paths then reads each one**: For large workspaces, this is an O(N*M) operation (N files, M lines each). No indexing or short-circuit.
- **`apply_rewrite` reads/writes files directly via Path**: This bypasses the workspace abstraction. The rewrite operates on the *real* filesystem (the source file), not the agent workspace. This is correct (agents rewrite real code), but the inconsistency with other file ops (which use the workspace) is worth noting.
- **`broadcast` fetches ALL nodes**: `list_nodes()` with no filters, then iterates to match pattern. For large graphs, this is expensive. The `_resolve_broadcast_targets` function handles special patterns (`*`, `siblings`, `file:path`) but the core pattern matching is substring-based — `pattern in node_id` — which is imprecise.
- **`graph_set_status` updates both agent_store and node_store**: More evidence of the dual-status tracking problem from 3.5.

### 3.10 Workspace

**`core/workspace.py`** (218 lines) — Per-agent sandboxed filesystem backed by Cairn.

**Issues:**

- **`AgentWorkspace` wraps every operation in `async with self._lock`**: This serializes all file operations per-agent. Correct for safety, but if multiple tool calls within a turn need concurrent file access, they'll be serialized.
- **`_safe_id` uses SHA-1**: SHA-1 is fine for non-security-critical hashing, but `hashlib.sha1` triggers security linters. Could use `hashlib.sha256` consistently (already used elsewhere).
- **`list_all_paths` constructs a `ViewQuery`**: This imports and uses `fsdantic.ViewQuery` — a tight coupling to the fsdantic API. If the ViewQuery interface changes, this breaks.
- **Bundle provisioning reads templates synchronously**: `pym_file.read_text()` and `bundle_yaml.read_text()` are sync I/O in an async method. For small bundle files this is fine, but it's technically blocking the event loop.
- **`_bundle_template_fingerprint` reads all template files synchronously**: Same issue. Sync file I/O in a method called from async context.

### 3.11 Grail Tool System

**`core/grail.py`** (172 lines) — Bridges Grail scripts to the structured-agents tool interface.

**Issues:**

- **`_cached_script` uses LRU cache with temp directory**: Each cache miss creates a temporary directory, writes the script, loads it, then the temp dir is cleaned up — but the loaded script object remains cached. This is clever but the temp dir creation per unique script is wasteful.
- **`GrailTool.execute` catches all exceptions**: Correct for a tool boundary, but the exception is logged with `logger.exception` (full traceback) which may be noisy for expected errors (e.g., file not found in a tool script).
- **Tool descriptions are generic**: `f"Tool: {script.name}"` — the LLM gets no meaningful description of what the tool does. The Grail script's docstring or a description field in bundle.yaml would be more useful.
- **`discover_tools` accesses `workspace._agent_id`**: Uses `getattr(workspace, "_agent_id", "?")` to read a private attribute. This violates encapsulation — `AgentWorkspace` should expose `agent_id` as a public property.

### 3.12 Code Discovery

**`code/discovery.py`** (231 lines) — Tree-sitter based node discovery with multi-language support.

**`code/languages.py`** (157 lines) — Plugin system for language-specific parsing.

**`code/paths.py`** (72 lines) — Path resolution and file walking.

**Issues:**

- **`discover()` uses module-level LRU caches**: `_get_language_registry()`, `_get_parser()`, `_load_query()` are all cached. This is efficient but means the caches are never cleared — if query files change at runtime, stale queries persist until process restart.
- **`_parse_file` rebuilds parent-child relationships from tree-sitter AST**: The algorithm walks the tree twice — once to collect entries, once to build parent links. This is correct but the code is dense with nested dict lookups (`by_key`, `parent_by_key`, `name_by_key`).
- **Duplicate ID handling is append-based**: `candidate_id = f"{file_path}::{full_name}@{node.start_byte}"` — appending `@byte_offset` for duplicates. This creates unstable IDs that change if the file content shifts.
- **`PythonPlugin.resolve_node_type` handles decorated definitions**: Good, but the logic for determining method vs. function via `_has_class_ancestor` walks up the tree. For deeply nested classes, this is O(depth) per node.
- **`LanguagePlugin` is a Protocol**: Clean design allowing structural typing. However, no runtime validation that plugins actually satisfy the protocol.

### 3.13 Projections

**`code/projections.py`** (79 lines) — Maps CSTNodes to persisted Nodes with bundle provisioning.

**Issues:**

- **Hash recomputation**: `hashlib.sha256(cst.text.encode("utf-8")).hexdigest()` is computed for every CSTNode, even when the existing node's hash matches. Minor optimization opportunity.
- **Bundle provisioning within projection**: The projection function has side effects (provisioning bundles, upserting to store). This mixes query (mapping) with command (persistence). A purer design would separate the mapping from the persistence.
- **`sync_existing_bundles` parameter**: This boolean flag controls whether existing nodes get their bundles re-synced. The dual-path logic (new node vs. existing node, with/without sync) is getting complex.

### 3.14 File Reconciler

**`code/reconciler.py`** (494 lines) — The second-largest module. Watches files, diffs nodes, manages directory nodes, emits lifecycle events.

**Issues:**

- **Massive responsibility**: This single class handles file watching, directory node materialization, file reconciliation, subscription registration, agent creation, bundle provisioning, and content change event handling. It's a god class.
- **`_materialize_directories` is complex**: ~80 lines of directory tree construction, comparison, and update logic. The algorithm builds `children_by_dir`, compares with existing, handles stale removal, creates new directories, checks metadata changes, and conditionally re-registers subscriptions. This is the most complex single method in the codebase.
- **Triple bootstrap flags**: `_subscriptions_bootstrapped`, `_bundles_bootstrapped`, and the implicit file-state bootstrap create three separate "first run" code paths. This tri-modal initialization is hard to reason about.
- **`_stop_event` creates a threading.Event polled by async task**: The reconciler uses `watchfiles.awatch` which needs a threading stop event, so an async task polls `self._running` every 0.5s and sets the threading event. This async-to-threading bridge is clunky but necessary.
- **`_file_locks` dict grows unboundedly**: A lock is created per file path and never cleaned up. For projects with many files being created and deleted, this leaks.
- **Directory subscription globs use `**` prefix**: `subtree_glob = "**" if node.file_path == "." else f"**/{node.file_path}/**"` — the `**/` prefix means these match paths anywhere, not just under the project root. For typical usage this works, but it's imprecise.

### 3.15 Web Server

**`web/server.py`** (141 lines) — Starlette app with REST APIs, SSE streaming, and chat endpoint.

**Issues:**

- **`_INDEX_HTML` loaded at module import time**: `(_STATIC_DIR / "index.html").read_text()` — this crashes at import if the HTML file is missing. Lazy loading would be safer.
- **No authentication or authorization**: The web server is bound to `127.0.0.1` (good), but any local process can send chat messages, query data, or stream events.
- **`api_chat` doesn't validate JSON**: `await request.json()` will raise a 500 on invalid JSON. Should catch `json.JSONDecodeError`.
- **SSE `event_generator` doesn't handle event serialization errors**: If `event.model_dump()` fails, the entire SSE stream breaks.
- **`del project_root` in `create_app`**: The parameter is accepted but immediately deleted. This suggests it was planned for use but never implemented. It should be removed from the signature if unused.
- **No CORS headers**: Fine for local-only use, but limits integration with external tools.

### 3.16 LSP Server

**`lsp/server.py`** (165 lines) — Thin pygls adapter providing code lenses, hover, and document sync.

**Issues:**

- **`_remora_handlers` monkey-patch for testing**: `server._remora_handlers = {...}` — storing test hooks on the server object is a code smell. A separate handler class would be cleaner.
- **`DocumentStore` is simple but doesn't integrate with the node graph**: It tracks raw text but doesn't trigger re-discovery. The `did_save` handler emits a `ContentChangedEvent`, but `did_change` (incremental edits) doesn't. This means the graph only updates on save, not on edit.
- **`_uri_to_path` doesn't handle Windows paths**: `unquote(parsed.path)` works for Unix but may produce `/C:/...` on Windows.
- **LSP is optional but `create_lsp_server` in `__init__.py` has a try/except ImportError**: This is the only place in the codebase with an import guard, contradicting REPO_RULES ("no try/except ImportError guards"). However, LSP is genuinely optional (it's in `[project.optional-dependencies]`), so this is a pragmatic exception.

### 3.17 CLI Entry Point

**`__main__.py`** (286 lines) — Typer-based CLI with `start` and `discover` commands.

**Issues:**

- **`_start` function is 120 lines**: It creates the config, opens the DB, initializes services, runs discovery, creates tasks, manages web/LSP servers, and handles shutdown. This is a lot for one function, but it's startup code — inherently linear.
- **Misaligned indentation on line 81-82**: The closing parenthesis for `asyncio.run(` is oddly indented. Cosmetic but inconsistent.
- **`_configure_logging` and `_configure_file_logging`**: Two separate logging setup functions. The file handler setup scans existing handlers to avoid duplicates, which is defensive but suggests the function may be called multiple times.
- **No graceful shutdown on SIGTERM**: Only `KeyboardInterrupt` (SIGINT) is caught. SIGTERM (from systemd, Docker, etc.) will cause an abrupt exit.

### 3.18 Bundle System

The bundle system (`bundles/`) contains three layers:

- **`system/`**: Base tools available to all agents (send_message, subscribe, kv_get/set, broadcast, reflect, etc.)
- **`code-agent/`**: Tools for code nodes (rewrite_self, scaffold)
- **`directory-agent/`**: Tools for directory nodes (list_children, broadcast_children, get_parent, summarize_tree)

**Issues:**

- **Tool scripts lack descriptions**: The Grail scripts don't include docstrings or description metadata. The LLM sees `"Tool: send_message"` which is minimally helpful.
- **`categorize.pym` uses naive heuristics**: `if "test" in source_code` — this categorization logic is rudimentary. It's a placeholder but ships as a real tool.
- **`reflect.pym` appends to notes/reflection.md**: Each reflection just appends "Reviewed recent activity" with the event count. The reflection doesn't actually analyze anything — it's a stub.
- **`scaffold.pym` emits a custom event but nothing handles it**: `ScaffoldRequestEvent` is emitted, but there's no subscriber or handler for this event type. Dead functionality.
- **Bundle YAML supports `system_prompt_extension` but not `system_prompt`**: The code-agent bundle uses `system_prompt_extension`, while the system bundle uses `system_prompt`. The `_build_system_prompt` method in `actor.py` composes them, but this layering isn't documented.

---

## 4. Cross-Cutting Concerns

### 4.1 Dual Status Tracking

Both `NodeStore` and `AgentStore` independently track agent status. Every status change must be applied to both stores, and the code has multiple places doing this:

- `Actor._start_agent_turn()`: transitions both stores to RUNNING
- `Actor._reset_agent_state()`: resets both stores to IDLE
- `Actor._execute_turn()` error handler: transitions both to ERROR
- `TurnContext.graph_set_status()`: updates both stores

This is the single most pervasive design smell in the codebase. If either update fails or is skipped, the stores diverge silently.

### 4.2 Commit-Per-Operation

Every store method calls `await self._db.commit()` after its operation. This means a single reconciliation cycle (which upserts nodes, registers subscriptions, creates agents, and emits events) triggers dozens of individual commits. This is correct for isolation but wasteful for performance. A "unit of work" pattern where operations are batched and committed together would be more efficient.

### 4.3 No Transaction Boundaries

Related to 4.2: there are no explicit transactions. Operations that should be atomic (e.g., "create node + create agent + register subscriptions") are done as separate commits. A failure partway through leaves the database in an inconsistent state.

### 4.4 Mixed Sync/Async I/O

Several modules perform synchronous file I/O within async methods:

- `workspace.py`: `pym_file.read_text()`, `bundle_yaml.read_text()`, `_bundle_template_fingerprint()`
- `discovery.py`: `path.read_bytes()`, `Path(query_file).read_text()`
- `reconciler.py`: `file_path.stat().st_mtime_ns` (via `_collect_file_mtimes`)
- `web/server.py`: `_INDEX_HTML` at module import

For the current scale (small-to-medium codebases, local files), this isn't a problem. But it technically blocks the event loop.

### 4.5 Error Handling Philosophy

The codebase uses broad exception catching (`except Exception`) at system boundaries:

- `Actor._execute_turn()`: catches all exceptions to prevent actor loop crashes
- `GrailTool.execute()`: catches all exceptions to return tool errors
- `FileReconciler._run_watching()`: catches all exceptions per watch batch
- `TurnContext.search_content()`: catches FileNotFoundError per file

This is the right philosophy for a reactive system — individual failures should not cascade. However, the `# noqa: BLE001` annotations suggest the linter disagrees. The broad catches are well-placed but should log with sufficient context for debugging.

### 4.6 Pydantic Model Consistency

The codebase uses Pydantic extensively but inconsistently:

- `Config` is `BaseSettings` (frozen=True) — correct
- `DiscoveredElement` is `BaseModel` (frozen=True) — correct
- `Node` is `BaseModel` (frozen=False) — necessary for mutation but surprising given Event is also mutable
- `Agent` is `BaseModel` (frozen=False) — same
- `Event` subtypes are `BaseModel` (mutable) — events are emitted once and shouldn't need mutation, but `correlation_id` is set post-construction by `Outbox.emit()`
- `CSTNode` is `BaseModel` (frozen=True) — correct
- `Edge` is a `dataclass` (frozen=True) — inconsistent with the Pydantic pattern elsewhere
- `SubscriptionPattern` is `BaseModel` — fine

The mix of frozen/mutable and Pydantic/dataclass is not necessarily wrong, but it creates cognitive load.

---

## 5. Test Suite Assessment

### Coverage

- **208 tests, all passing**, 4 skipped
- **3,790 lines** of test code for **4,346 lines** of source — an excellent ratio (0.87:1)
- Every module has at least one corresponding test file
- `test_actor.py` (689 lines) is the largest test file, reflecting the complexity of the actor module

### Strengths

- **Shared fixtures**: `conftest.py` provides a clean `db` fixture using `open_database`
- **Factory helpers**: `factories.py` provides `make_node`, `make_cst`, `write_file`, `write_bundle_templates` — reduces boilerplate
- **Async test support**: Uses `pytest-asyncio` throughout
- **Integration tests**: `test_e2e.py`, `test_llm_turn.py`, `test_grail_runtime_tools.py`, `test_performance.py`

### Gaps

- **No concurrent actor tests**: The actor pool routes events to inboxes, but there are no tests for concurrent actor execution with the semaphore
- **No crash recovery tests**: What happens when the process restarts mid-turn? The event store has committed events but the actor state may be inconsistent
- **No subscription cache stress tests**: The subscription registry cache is invalidated on every mutation — no test verifies behavior under rapid subscription changes
- **No SSE streaming integration test**: The web server test likely tests REST endpoints but SSE streaming with live events is harder to test
- **Reconciler tests are the most complex** (332 lines): The reconciler's complexity is reflected in its test suite, suggesting the module itself may be too complex

---

## 6. Issues & Recommendations

### Priority 1: Correctness Issues

| # | Issue | Location | Impact |
|---|-------|----------|--------|
| 1 | Foreign keys not enforced (no `PRAGMA foreign_keys=ON`) | `core/db.py` | FK constraints in `agents` table are decorative |
| 2 | Dual status tracking divergence risk | `graph.py`, `actor.py`, `externals.py` | Node/agent status can silently diverge |
| 3 | No transaction boundaries for multi-step operations | All store operations | Partial failures leave inconsistent state |
| 4 | `_depths` dict grows unboundedly on trigger flood | `core/actor.py` | Memory leak under sustained event pressure |
| 5 | `_file_locks` dict grows unboundedly | `code/reconciler.py` | Memory leak for projects with many file creates/deletes |

### Priority 2: Architecture Concerns

| # | Issue | Location | Impact |
|---|-------|----------|--------|
| 6 | FileReconciler is a god class (~500 lines, 7+ responsibilities) | `code/reconciler.py` | Hard to test, reason about, and modify |
| 7 | TurnContext is a god object (24 methods) | `core/externals.py` | Monolithic API surface, no logical grouping |
| 8 | RecordingOutbox (test double) lives in production code | `core/actor.py` | Layering violation |
| 9 | Commit-per-operation pattern | All stores | Performance bottleneck under load |
| 10 | No back-pressure on actor inbox queues | `core/runner.py` | Unbounded queue growth under event flood |

### Priority 3: Code Quality

| # | Issue | Location | Impact |
|---|-------|----------|--------|
| 11 | Dead import: `model_validator` in config.py | `core/config.py` | Unused import |
| 12 | `DiscoveredElement` class appears unused outside `to_element()` | `core/node.py` | Dead code |
| 13 | `del project_root` in `create_app` — unused parameter | `web/server.py` | Dead parameter |
| 14 | `scaffold.pym` emits unhandled event type | `bundles/code-agent/` | Dead functionality |
| 15 | Tool descriptions are generic (`"Tool: {name}"`) | `core/grail.py` | Poor LLM tool selection |
| 16 | `grail.py` accesses private `workspace._agent_id` | `core/grail.py` | Encapsulation violation |
| 17 | `_INDEX_HTML` loaded at import time | `web/server.py` | Crash on missing file |
| 18 | SHA-1 usage in `_safe_id` | `core/workspace.py` | Linter warnings |
| 19 | `time.time()` instead of `time.monotonic()` for cooldown | `core/actor.py` | Clock adjustment sensitivity |
| 20 | Sync file I/O in async methods | `workspace.py`, `discovery.py` | Event loop blocking (minor) |

### Priority 4: Missing Features / Hardcoded Values

| # | Issue | Location | Impact |
|---|-------|----------|--------|
| 21 | No SIGTERM handling | `__main__.py` | Abrupt exit in containers |
| 22 | Idle eviction timeout hardcoded to 300s | `core/runner.py` | Not configurable |
| 23 | No JSON validation on chat endpoint | `web/server.py` | 500 errors on invalid input |
| 24 | No CORS headers | `web/server.py` | Limits external integration |
| 25 | `api_chat` doesn't validate JSON input | `web/server.py` | Possible 500 errors |

---

*Review completed. Codebase is approximately 4,346 lines of source across 31 Python files with 208 passing tests. The architecture is sound and well-decomposed at the high level, with the event-driven reactive agent model being a genuinely novel approach. The main concerns are: dual status tracking, god classes (Reconciler, TurnContext), missing transaction boundaries, and several small correctness issues. The bundle/tool system is elegant in concept but the current tool implementations are mostly stubs.*
