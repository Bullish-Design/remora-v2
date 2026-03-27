# Remora v2 — Comprehensive Deep-Dive Guide

> This document is written for someone who needs to understand Remora v2 deeply: what it is, the problem it solves, every major subsystem, how they connect, and how the underlying libraries (structured-agents, Grail, Cairn, fsdantic, embeddy) integrate into the whole.

---

## Table of Contents

1. [What Is Remora?](#1-what-is-remora)
   - 1.1 Core Idea
   - 1.2 The Reactive Loop
   - 1.3 Key Properties

2. [Architecture Overview](#2-architecture-overview)
   - 2.1 Component Map
   - 2.2 Data Flow Diagram
   - 2.3 Persistence Model

3. [Configuration System](#3-configuration-system)
   - 3.1 Config File Discovery
   - 3.2 Config Sub-Models
   - 3.3 Defaults Layer
   - 3.4 Environment Variable Expansion
   - 3.5 Bundle Resolution

4. [Code Discovery (tree-sitter)](#4-code-discovery-tree-sitter)
   - 4.1 LanguageRegistry and Plugins
   - 4.2 Tree-Sitter Query Files (.scm)
   - 4.3 Node ID Assignment
   - 4.4 Node Types
   - 4.5 Relationship Extraction

5. [FileReconciler — Keeping the Graph in Sync](#5-filereconciler--keeping-the-graph-in-sync)
   - 5.1 Full Scan
   - 5.2 Incremental Reconciliation
   - 5.3 Directory and Virtual Agent Materialization
   - 5.4 Bundle Provisioning During Reconcile
   - 5.5 File Locking and Generation Tracking
   - 5.6 ContentChangedEvent Integration

6. [Node Graph Storage (NodeStore)](#6-node-graph-storage-nodestore)
   - 6.1 Schema
   - 6.2 Status State Machine
   - 6.3 Edge Types
   - 6.4 TransactionContext and Batched Commits

7. [Event System](#7-event-system)
   - 7.1 Event Envelope Format
   - 7.2 EventStore — Append-Only Persistence
   - 7.3 EventBus — In-Process Pub/Sub
   - 7.4 TriggerDispatcher — Subscription Routing
   - 7.5 SubscriptionRegistry
   - 7.6 Complete Event Type Reference

8. [Actor Model — Agents as Actors](#8-actor-model--agents-as-actors)
   - 8.1 ActorPool — Registry and Router
   - 8.2 Actor — Inbox Loop
   - 8.3 TriggerPolicy — Cooldown and Depth Guards
   - 8.4 AgentTurnExecutor — The Turn Pipeline
   - 8.5 Two-Layer Reflection (Primary + Reflection Turns)
   - 8.6 Overflow Policies

9. [LLM Kernel (structured-agents)](#9-llm-kernel-structured-agents)
   - 9.1 What structured-agents Is
   - 9.2 AgentKernel — The Core Loop
   - 9.3 Tool Protocol
   - 9.4 ResponseParser and Model Adaptation
   - 9.5 OutboxObserver — Bridging Kernel Events to Remora Events
   - 9.6 How Remora Wraps the Kernel

10. [Tool System (Grail .pym)](#10-tool-system-grail-pym)
    - 10.1 What Grail Is
    - 10.2 .pym Script Format
    - 10.3 Input() and @external Declarations
    - 10.4 GrailTool — The Wrapper
    - 10.5 Tool Discovery from Workspaces
    - 10.6 Script Caching

11. [Workspace System (Cairn + fsdantic)](#11-workspace-system-cairn--fsdantic)
    - 11.1 What Cairn Is
    - 11.2 CairnWorkspaceService
    - 11.3 AgentWorkspace — Per-Agent Sandboxed FS
    - 11.4 Bundle Provisioning
    - 11.5 KV Store
    - 11.6 Companion Data Storage

12. [TurnContext and Capabilities API](#12-turncontext-and-capabilities-api)
    - 12.1 Capability Groups
    - 12.2 FileCapabilities
    - 12.3 KVCapabilities
    - 12.4 GraphCapabilities
    - 12.5 EventCapabilities
    - 12.6 CommunicationCapabilities
    - 12.7 SearchCapabilities
    - 12.8 IdentityCapabilities

13. [Bundle System](#13-bundle-system)
    - 13.1 Bundle Layout
    - 13.2 Layering: system + role
    - 13.3 bundle.yaml Fields
    - 13.4 Default Bundles
    - 13.5 Self-Reflection (Layer 2)
    - 13.6 Companion Bundle

14. [Virtual Agents](#14-virtual-agents)
    - 14.1 Declaration in remora.yaml
    - 14.2 VirtualAgentManager
    - 14.3 Subscription Patterns

15. [Directory Agents](#15-directory-agents)
    - 15.1 DirectoryManager
    - 15.2 Materialization
    - 15.3 Subscription Behavior

16. [Subscription System](#16-subscription-system)
    - 16.1 SubscriptionPattern Fields
    - 16.2 SubscriptionManager
    - 16.3 Default Subscriptions per Node Type
    - 16.4 Dynamic Subscriptions from Tools

17. [Web Server and SSE Streaming](#17-web-server-and-sse-streaming)
    - 17.1 Starlette App
    - 17.2 Route Inventory
    - 17.3 SSE Stream Protocol (Replay, Resume)
    - 17.4 Chat API
    - 17.5 CSRF Middleware
    - 17.6 Graph UI (Sigma.js)

18. [LSP Integration](#18-lsp-integration)
    - 18.1 Embedded vs. Standalone Mode
    - 18.2 LSP Features
    - 18.3 cursor_focus Events

19. [Semantic Search (embeddy)](#19-semantic-search-embeddy)
    - 19.1 What embeddy Is
    - 19.2 Remote vs. Local Modes
    - 19.3 SearchService
    - 19.4 Indexing
    - 19.5 semantic_search and find_similar_code

20. [Lifecycle and Runtime Startup/Shutdown](#20-lifecycle-and-runtime-startupshutdown)
    - 20.1 RemoraLifecycle
    - 20.2 Ordered Startup Sequence
    - 20.3 Ordered Shutdown Sequence
    - 20.4 Task Management Strategy

21. [CLI Commands](#21-cli-commands)

22. [Testing Infrastructure](#22-testing-infrastructure)
    - 22.1 Test Layers
    - 22.2 Doubles and Factories
    - 22.3 Running Tests

23. [Extension Points](#23-extension-points)
    - 23.1 Adding a New Event Type
    - 23.2 Adding a New Language
    - 23.3 Adding a New Bundle
    - 23.4 Adding a New API Endpoint
    - 23.5 Adding a New External Function

---

---

## 1. What Is Remora?

### 1.1 Core Idea

Remora is a **reactive agent substrate**. Given any codebase (or document tree), it:

1. **Discovers** code elements — functions, classes, methods, markdown sections, TOML tables, directories — using tree-sitter queries.
2. **Projects** each element into a SQLite graph as a **Node** with unique ID, source text, hash, and position metadata.
3. **Materializes** an **Actor** for every node. Each actor is an autonomous LLM agent that owns a sandboxed workspace.
4. **Reacts** to events — file changes, direct messages, custom events — by delivering those events to the relevant actor's inbox.
5. **Executes** agent turns: assemble a prompt, load tools, call the LLM, execute tool calls, persist results.
6. **Streams** all activity to a web UI, LSP clients, and any SSE subscribers.

The key mental model: **every code element is a living agent**. A Python function `calculate_total` in `src/billing.py` has its own ID (`src/billing.py::calculate_total`), its own workspace (`.remora/agents/<safe-id>/`), its own event history, its own KV memory, and its own LLM agent that can reason about it, respond to questions, detect changes, and coordinate with siblings.

### 1.2 The Reactive Loop

```
File system change
    │
    ▼
FileReconciler (watchfiles)
    │  reconcile_cycle() → discovers new/changed/deleted nodes
    │  emits NodeDiscoveredEvent, NodeChangedEvent, NodeRemovedEvent
    ▼
EventStore.append()
    │  persists event to SQLite
    │  fan-out to EventBus (in-process) and TriggerDispatcher (routing)
    ▼
TriggerDispatcher.dispatch()
    │  matches event against all SubscriptionPatterns
    │  calls router callback for each matching agent
    ▼
ActorPool._route_to_actor(agent_id, event)
    │  get-or-create Actor for agent_id
    │  enqueue event in actor.inbox
    ▼
Actor._run() loop
    │  dequeue event from inbox
    │  TriggerPolicy: check cooldown + max depth
    │  build Trigger + Outbox
    ▼
AgentTurnExecutor.execute_turn()
    │  look up Node in NodeStore
    │  transition status IDLE → RUNNING
    │  emit AgentStartEvent
    │  get/create AgentWorkspace (Cairn)
    │  read BundleConfig (bundle.yaml)
    │  build system prompt + user prompt
    │  discover tools (_bundle/tools/*.pym via Grail)
    │  call AgentKernel.run() (structured-agents)
    │     └─ LLM call → parse tool calls → execute GrailTools → repeat
    │  emit AgentCompleteEvent
    │  (optional) reflection turn with companion tools
    │  emit TurnDigestedEvent
    │  transition status RUNNING → IDLE
    ▼
Further events cascade through same loop
```

### 1.3 Key Properties

- **Self-contained runtime**: single `remora start` boots everything — file watcher, agent pool, web server, optional LSP.
- **Persistent graph**: SQLite with WAL mode; survives restart, retains full event history.
- **Sandboxed tools**: agent tools run as Grail `.pym` scripts in a Monty (sandboxed Python) interpreter. Tools cannot escape their workspace.
- **Proposal flow**: agents can propose file changes (`propose_changes`); changes only land in stable workspace when a human accepts via the web UI (`/api/proposals/{id}/accept`).
- **Multi-language**: tree-sitter queries for Python, Markdown, TOML by default; extensible.
- **Observable**: full SSE stream, structured logs, `/api/events`, `/api/health`, metrics.

---

## 2. Architecture Overview

### 2.1 Component Map

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ remora start (CLI)                                                          │
│                                                                             │
│  ┌──────────────────────┐     ┌──────────────────────┐                     │
│  │ RemoraLifecycle      │     │ RuntimeServices       │                     │
│  │  - startup sequence  │────▶│  - all service refs   │                     │
│  │  - shutdown order    │     │  - initialize()       │                     │
│  │  - task management   │     └──────────────────────┘                     │
│  └──────────────────────┘                │                                 │
│                                          │                                 │
│  ┌──────────────────────────────────────────────────────────────┐         │
│  │ Code Layer                                                    │         │
│  │  FileReconciler ──────────────────────────────────────────── │         │
│  │   ├─ FileWatcher (watchfiles)                                │         │
│  │   ├─ LanguageRegistry (tree-sitter plugins)                  │         │
│  │   ├─ discover() (tree-sitter queries → Nodes)                │         │
│  │   ├─ DirectoryManager (directory nodes)                      │         │
│  │   ├─ VirtualAgentManager (virtual nodes)                     │         │
│  │   └─ SubscriptionManager (registers subscriptions)           │         │
│  └──────────────────────────────────────────────────────────────┘         │
│                              │                                             │
│  ┌──────────────────────────────────────────────────────────────┐         │
│  │ Storage Layer                                                 │         │
│  │  NodeStore (nodes + edges SQLite)                            │         │
│  │  EventStore (events SQLite + fan-out)                        │         │
│  │  SubscriptionRegistry (subscription patterns SQLite)         │         │
│  │  CairnWorkspaceService (per-agent Cairn workspaces)          │         │
│  └──────────────────────────────────────────────────────────────┘         │
│                              │                                             │
│  ┌──────────────────────────────────────────────────────────────┐         │
│  │ Dispatch Layer                                                │         │
│  │  EventBus (in-process pub/sub, SSE streaming)                │         │
│  │  TriggerDispatcher (subscription matching → router)          │         │
│  └──────────────────────────────────────────────────────────────┘         │
│                              │                                             │
│  ┌──────────────────────────────────────────────────────────────┐         │
│  │ Execution Layer                                               │         │
│  │  ActorPool (actor registry, idle eviction)                   │         │
│  │   └─ Actor (inbox asyncio.Queue, _run loop)                  │         │
│  │       └─ AgentTurnExecutor                                   │         │
│  │           ├─ PromptBuilder                                   │         │
│  │           ├─ TriggerPolicy (depth + cooldown)                │         │
│  │           ├─ Outbox (event emission)                         │         │
│  │           ├─ CairnWorkspaceService (workspace)               │         │
│  │           ├─ discover_tools (Grail .pym)                     │         │
│  │           └─ AgentKernel (structured-agents)                 │         │
│  └──────────────────────────────────────────────────────────────┘         │
│                                                                             │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐        │
│  │ Web (Starlette)  │  │ LSP (pygls)      │  │ SearchService    │        │
│  │ SSE, REST, UI    │  │ CodeLens, Hover  │  │ (embeddy)        │        │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘        │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Data Flow Diagram

The canonical flow is described in §1.2. Here is the database perspective:

```
SQLite (.remora/remora.db)
├── nodes        ← canonical graph of all discovered code elements
├── edges        ← directed relationships (contains, imports, inherits)
├── events       ← append-only log of all runtime events
└── subscriptions← routing rules: which agent receives which events
```

The `EventStore` is the central nexus:
- It persists every event to `events`.
- It fans out to `EventBus` (sync handlers + SSE queues).
- It fans out to `TriggerDispatcher` (subscription matching → actor routing).

### 2.3 Persistence Model

**SQLite WAL mode** (`PRAGMA journal_mode=WAL`) is set on database open. This allows concurrent readers and a single writer, which is critical for the web API reading while agents write.

The `TransactionContext` (`src/remora/core/storage/transaction.py`) provides batched commits. During a `full_scan`, all node upserts and events for a single file are committed atomically, improving startup performance significantly.

---

## 3. Configuration System

### 3.1 Config File Discovery

`load_config()` in `src/remora/core/model/config.py`:
1. Loads `src/remora/defaults/defaults.yaml` as the base (lowest priority).
2. Walks up from the working directory looking for `remora.yaml` (or uses `--config` flag).
3. Deep-merges user config over defaults.
4. Expands `${VAR:-default}` shell-style env var references.
5. Returns a frozen `Config` Pydantic model.

### 3.2 Config Sub-Models

| Sub-model | Fields | Purpose |
|---|---|---|
| `ProjectConfig` | `discovery_paths`, `discovery_languages`, `workspace_ignore_patterns` | What to scan |
| `RuntimeConfig` | `max_concurrency`, `max_trigger_depth`, `trigger_cooldown_ms`, `actor_inbox_*`, `chat_*` | Agent execution controls |
| `InfraConfig` | `model_base_url`, `model_api_key`, `timeout_s`, `workspace_root` | LLM + filesystem paths |
| `BehaviorConfig` | `model_default`, `max_turns`, `bundle_search_paths`, `query_search_paths`, `bundle_overlays`, `bundle_rules`, `languages`, `language_map`, `prompt_templates` | Discovery and bundle behavior |
| `SearchConfig` | `enabled`, `mode`, `embeddy_url`, `collection_map` | Semantic search |
| `VirtualAgentConfig` | `id`, `role`, `subscriptions` | Declarative virtual agents |

`Config` is a `pydantic_settings.BaseSettings` with `REMORA_` env prefix, so `REMORA_MODEL_API_KEY` maps to `config.infra.model_api_key`.

### 3.3 Defaults Layer

`src/remora/defaults/defaults.yaml` establishes:
- Default `bundle_overlays`: functions/classes/methods → `code-agent`, directories → `directory-agent`.
- Default `language_map`: `.py` → python, `.md` → markdown, `.toml` → toml.
- Default `model_default`: `Qwen/Qwen3-4B`.
- Default `prompt_templates.user` and `prompt_templates.reflection`.

These are the lowest priority and are always overridable in `remora.yaml`.

### 3.4 Environment Variable Expansion

YAML values may contain `${VAR:-default}` syntax. This is expanded at `load_config` time via `expand_env_vars()`. For example:

```yaml
model_api_key: "${OPENAI_API_KEY:-}"
model_default: "${REMORA_MODEL:-Qwen/Qwen3-4B-Instruct-2507-FP8}"
```

The default model in bundle.yaml files also uses this: `"${REMORA_MODEL:-Qwen/Qwen3-4B-Instruct-2507-FP8}"`.

### 3.5 Bundle Resolution

`Config.resolve_bundle(node_type, node_name)` determines which bundle role to assign a node:

1. Check `bundle_rules` in order. Each rule has `node_type`, optional `name_pattern` (fnmatch glob), and `bundle`. First match wins.
2. Fall back to `bundle_overlays[node_type]` (exact type → bundle name map).
3. Return `None` if nothing matches (node gets only system bundle tools).

This means you can map `function` nodes named `test_*` to a `test-agent` bundle while all other functions go to `code-agent`.

---

## 4. Code Discovery (tree-sitter)

### 4.1 LanguageRegistry and Plugins

`LanguageRegistry` (`src/remora/code/languages.py`) holds `LanguagePlugin` instances. Each plugin wraps a tree-sitter language and provides:
- `get_language()` → tree-sitter `Language` object
- `get_query(query_paths)` → compiled `Query` from `.scm` file
- `resolve_node_type(ts_node)` → maps tree-sitter node types to `NodeType` enum
- `get_default_query_path()` → built-in query file location

Built-in plugins are registered for `python`, `markdown`, and `toml` via the `languages` config.

### 4.2 Tree-Sitter Query Files (.scm)

Stored in `src/remora/defaults/queries/`. Each query captures:
- `@node` — the AST node that becomes a Remora node
- `@node.name` — the name identifier

Example from `python.scm`:
```scheme
(function_definition name: (identifier) @node.name) @node
(class_definition name: (identifier) @node.name) @node
```

Custom query paths are resolved via `query_search_paths` in config. Remora walks the list and uses the first matching `.scm` file per language.

### 4.3 Node ID Assignment

Node IDs are deterministic strings: `"{file_path}::{full_name}"`.

`full_name` is built by walking the tree-sitter parent hierarchy:
- A method `calculate` inside class `Billing` → full_name `Billing.calculate` → node_id `src/billing.py::Billing.calculate`
- A function `run` at module level → full_name `run` → node_id `src/app.py::run`

If two nodes in the same file would generate the same ID (duplicate names), a byte-offset suffix is appended: `src/app.py::run@256`.

### 4.4 Node Types

```python
class NodeType(StrEnum):
    FUNCTION = "function"   # Python def, top-level functions
    CLASS = "class"         # Python class definitions
    METHOD = "method"       # Python methods inside a class
    SECTION = "section"     # Markdown headings
    TABLE = "table"         # TOML table headers
    DIRECTORY = "directory" # Synthesized directory nodes
    VIRTUAL = "virtual"     # Declarative virtual agents
```

### 4.5 Relationship Extraction

After node discovery for Python files, `FileReconciler._do_reconcile_file()` calls:

- `extract_imports(source_bytes, plugin, file_path, ...)` — uses `python_imports.scm` tree-sitter query to find import statements, returns raw relationships.
- `extract_inheritance(source_bytes, plugin, file_path, nodes_by_name, ...)` — uses `python_inheritance.scm` to find base class relationships.
- `resolve_relationships(raw_rels, name_index)` — resolves string names to node IDs using the in-memory `_name_index`.

Resulting edges are stored with `edge_type` = `"imports"` or `"inherits"`. These are cleared and re-extracted on every file reconcile.

---

## 5. FileReconciler — Keeping the Graph in Sync

`src/remora/code/reconciler.py`

### 5.1 Full Scan

`full_scan()` is called once at startup by `RemoraLifecycle.start()`. It calls `reconcile_cycle()` which:
1. Syncs virtual agents.
2. Collects current file mtimes via `FileWatcher.collect_file_mtimes()`.
3. Materializes directory nodes for all discovered file paths.
4. For each new/changed file: calls `_reconcile_file()`.
5. For each deleted file: removes all its nodes.
6. Sets `_bundles_bootstrapped = True` (subsequent scans don't re-copy identical bundles).

### 5.2 Incremental Reconciliation

`run_forever()` calls `FileWatcher.watch(callback)`, which uses `watchfiles` to get OS-native file change notifications. For each batch of changed files, `_handle_watch_changes()` is called.

`_reconcile_file(file_path, mtime_ns)`:
1. Acquires a per-file async lock (prevents concurrent reconciliation of the same file).
2. Calls `discover()` to parse the current file with tree-sitter.
3. Compares new node set vs. old node set (from `_file_state`).
4. Upserts changed nodes in NodeStore.
5. Extracts relationships (imports, inheritance) for Python files.
6. Emits node events in a batched transaction.
7. Indexes the file for semantic search.

### 5.3 Directory and Virtual Agent Materialization

**DirectoryManager** (`src/remora/code/directories.py`):
- Takes the set of all discovered file paths.
- Creates `directory`-type nodes for each unique directory component.
- Assigns `contains` edges from directory node to its children.
- Provisions the `directory-agent` bundle.

**VirtualAgentManager** (`src/remora/code/virtual_agents.py`):
- Reads `config.virtual_agents`.
- Creates/updates `virtual`-type nodes in NodeStore.
- Provisions their configured role bundles.
- Registers their declared subscriptions.

### 5.4 Bundle Provisioning During Reconcile

When a new node is discovered or a file is reconciled:
- `Config.resolve_bundle(node_type, name)` determines the role bundle.
- `_provision_bundle(node_id, role)` is called, which:
  1. Resolves template directories for `system` bundle first, then the role bundle.
  2. Calls `CairnWorkspaceService.provision_bundle(node_id, template_dirs)`.
  3. Reads the resulting `_bundle/bundle.yaml` and writes `_system/self_reflect` KV key.

Provisioning is fingerprinted (hash of template file contents). If the fingerprint hasn't changed since last provisioning, the copy is skipped.

### 5.5 File Locking and Generation Tracking

Each file gets an `asyncio.Lock` to prevent concurrent reconciliation. A generation counter tracks which files were touched in the current cycle. After the cycle, stale file locks (not accessed since the previous generation) are evicted up to a max of 500 locks.

### 5.6 ContentChangedEvent Integration

`start(event_bus)` subscribes to `ContentChangedEvent` events. This allows the LSP server and `rewrite_self` tool to trigger immediate reconciliation of specific files without waiting for the next watchfiles batch. The subscription is idempotent and cleaned up on `stop()`.

---

## 6. Node Graph Storage (NodeStore)

`src/remora/core/storage/graph.py`

### 6.1 Schema

**nodes table**:
```sql
CREATE TABLE nodes (
    node_id TEXT PRIMARY KEY,
    node_type TEXT NOT NULL,      -- function, class, method, section, table, directory, virtual
    name TEXT NOT NULL,           -- simple name (e.g. "calculate")
    full_name TEXT NOT NULL,      -- qualified name (e.g. "Billing.calculate")
    file_path TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    start_byte INTEGER DEFAULT 0,
    end_byte INTEGER DEFAULT 0,
    text TEXT NOT NULL,           -- full source text of the element
    source_hash TEXT NOT NULL,    -- sha256 of text, used for change detection
    parent_id TEXT,               -- parent node_id (method's class, or directory)
    status TEXT DEFAULT 'idle',   -- idle, running, awaiting_input, awaiting_review, error
    role TEXT                     -- bundle role name (e.g. "code-agent")
);
```

**edges table**:
```sql
CREATE TABLE edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id TEXT NOT NULL,
    to_id TEXT NOT NULL,
    edge_type TEXT NOT NULL,     -- contains, imports, inherits
    UNIQUE(from_id, to_id, edge_type)
);
```

### 6.2 Status State Machine

```
IDLE ──────────────────▶ RUNNING
 ▲                          │
 │                          ▼
 │         ┌──────── AWAITING_INPUT
 │         │                │
 │         ▼                ▼
 └──── ERROR ◀───────── AWAITING_REVIEW
```

Full transition table:
```python
STATUS_TRANSITIONS = {
    IDLE: {RUNNING},
    RUNNING: {IDLE, ERROR, AWAITING_INPUT, AWAITING_REVIEW},
    AWAITING_INPUT: {RUNNING, ERROR, IDLE},
    AWAITING_REVIEW: {RUNNING, IDLE},
    ERROR: {IDLE, RUNNING},
}
```

`transition_status()` is atomic: it uses a SQL UPDATE with a WHERE clause that only matches valid source states. If the node is in an unexpected state, it logs a warning and returns `False`.

### 6.3 Edge Types

| Edge type | Meaning |
|---|---|
| `contains` | directory/class → child (file members, subdirs) |
| `imports` | Python file/module → imported module |
| `inherits` | Python class → its base class |

`delete_edges_by_type()` is called before re-extracting imports/inheritance on each reconcile. This ensures stale relationships are cleared before fresh extraction.

### 6.4 TransactionContext and Batched Commits

`TransactionContext` (`src/remora/core/storage/transaction.py`) wraps the SQLite connection and provides a `batch()` async context manager. Within a batch:
- `NodeStore._maybe_commit()` skips individual commits.
- `EventStore.append()` defers event fan-out by accumulating events in `_deferred_events`.

When the batch exits, a single `COMMIT` is issued and all deferred events are emitted to the bus and dispatcher in order. This is used during `_reconcile_file()` to commit all nodes and events for a single file atomically.

---

## 7. Event System

### 7.1 Event Envelope Format

All events inherit from `Event` (Pydantic BaseModel):
```python
class Event(BaseModel):
    event_type: str        # stable snake_case identifier
    timestamp: float       # unix seconds
    event_id: int | None   # assigned by EventStore after persistence
    correlation_id: str | None  # causal chain ID (UUID)
    tags: tuple[str, ...]  # optional labels
```

When serialized to the API or SSE stream via `to_envelope()`:
```json
{
  "event_type": "agent_complete",
  "timestamp": 1710000000.123,
  "correlation_id": "abc-123",
  "tags": ["primary"],
  "payload": { "agent_id": "...", "result_summary": "..." }
}
```

### 7.2 EventStore — Append-Only Persistence

`src/remora/core/events/store.py`

`EventStore.append(event)`:
1. Inserts event row to SQLite `events` table.
2. Assigns `event.event_id = cursor.lastrowid`.
3. Increments `metrics.events_emitted_total`.
4. If inside a `TransactionContext.batch()`, defers fan-out.
5. Otherwise: `await db.commit()`, then `await event_bus.emit(event)`, then `await dispatcher.dispatch(event)`.

The events table has indexes on `event_type`, `agent_id`, and `correlation_id` for efficient filtering by the `/api/events` endpoint.

### 7.3 EventBus — In-Process Pub/Sub

`src/remora/core/events/bus.py`

`EventBus` provides:
- `subscribe(event_type, handler)` — type-specific handler
- `subscribe_all(handler)` — catch-all handler
- `unsubscribe(handler)` — remove from all registrations
- `emit(event)` — dispatch to matching handlers
- `stream(*event_types, max_buffer=1000)` — async context manager yielding an `AsyncIterator[Event]`

**Emission flow**:
1. Sync handlers are called inline.
2. Async handlers are run concurrently via `asyncio.TaskGroup`.
3. A semaphore (`max_concurrent_handlers=100`) throttles concurrency.
4. Errors in individual handlers are caught and logged; they don't abort other handlers.

**SSE streaming**: `stream()` creates a bounded asyncio Queue. Events are enqueued via a sync `enqueue` handler. If the queue is full, the event is dropped with a warning. This is how the web SSE endpoint gets a live event feed.

### 7.4 TriggerDispatcher — Subscription Routing

`src/remora/core/events/dispatcher.py`

`TriggerDispatcher.dispatch(event)` is called on every persisted event. It:
1. Loads all subscription patterns from `SubscriptionRegistry`.
2. For each pattern, checks if the event matches (event_type, from_agent, to_agent, path_glob, tags).
3. For each match, calls `self.router(agent_id, event)`.
4. The router is set to `ActorPool._route_to_actor` during initialization.

### 7.5 SubscriptionRegistry

`src/remora/core/events/subscriptions.py`

Stored in the `subscriptions` SQLite table. Each subscription has:
- `agent_id` — which node receives the matched events
- `pattern_json` — serialized `SubscriptionPattern`

`SubscriptionPattern` fields:
```python
class SubscriptionPattern(BaseModel):
    event_types: list[str] | None   # null = match all types
    from_agents: list[str] | None   # null = match any sender
    to_agent: str | None            # null = don't filter by recipient
    path_glob: str | None           # fnmatch against event.path or event.file_path
    tags: list[str] | None          # all tags must be present
```

`register(agent_id, pattern)` inserts or updates a subscription.
`unregister_by_agent(agent_id)` deletes all subscriptions for a node (called on node removal).

### 7.6 Complete Event Type Reference

| Event type | Key payload fields | Emitted by |
|---|---|---|
| `node_discovered` | `node_id`, `node_type`, `file_path`, `name` | FileReconciler |
| `node_changed` | `node_id`, `old_hash`, `new_hash`, `file_path` | FileReconciler |
| `node_removed` | `node_id`, `node_type`, `file_path`, `name` | FileReconciler |
| `content_changed` | `path`, `change_type`, `agent_id` | LSP, rewrite tools |
| `agent_start` | `agent_id`, `node_name` | AgentTurnExecutor |
| `agent_complete` | `agent_id`, `result_summary`, `full_response`, `user_message` | AgentTurnExecutor |
| `agent_error` | `agent_id`, `error`, `error_class`, `error_reason` | AgentTurnExecutor |
| `agent_message` | `from_agent`, `to_agent`, `content` | send_message/broadcast tools |
| `model_request` | `agent_id`, `model`, `tool_count`, `turn` | OutboxObserver |
| `model_response` | `agent_id`, `response_preview`, `duration_ms`, `turn` | OutboxObserver |
| `remora_tool_call` | `agent_id`, `tool_name`, `arguments_summary`, `turn` | OutboxObserver |
| `remora_tool_result` | `agent_id`, `tool_name`, `is_error`, `duration_ms`, `turn` | OutboxObserver |
| `turn_complete` | `agent_id`, `turn`, `tool_calls_count`, `errors_count` | OutboxObserver |
| `turn_digested` | `agent_id`, `digest_summary`, `has_reflection`, `has_links` | AgentTurnExecutor (reflection) |
| `human_input_request` | `agent_id`, `request_id`, `question`, `options` | request_human_input tool |
| `human_input_response` | `agent_id`, `request_id`, `response` | Web API |
| `rewrite_proposal` | `agent_id`, `proposal_id`, `files`, `reason` | propose_changes tool |
| `rewrite_accepted` | `agent_id`, `proposal_id` | Web API |
| `rewrite_rejected` | `agent_id`, `proposal_id`, `feedback` | Web API |
| `cursor_focus` | `file_path`, `line`, `character`, `node_id` | LSP cursor route |
| `custom` | arbitrary payload dict | event_emit tool |

---

## 8. Actor Model — Agents as Actors

### 8.1 ActorPool — Registry and Router

`src/remora/core/agents/runner.py`

`ActorPool` is the central execution registry:
- Holds a `dict[str, Actor]` keyed by `node_id`.
- Registers itself as `dispatcher.router` — the function called when an event matches a subscription.
- Creates `Actor` instances lazily on first routing.
- Runs an idle eviction loop every 1 second: actors inactive for `actor_idle_timeout_s` (default 300s) with empty inboxes are stopped and removed.
- `run_forever()` just ticks the eviction loop. Actors run their own tasks.

A shared `asyncio.Semaphore(max_concurrency)` is passed to all actors, limiting total concurrent LLM turns across the pool.

### 8.2 Actor — Inbox Loop

`src/remora/core/agents/actor.py`

Each `Actor` owns:
- An `asyncio.Queue` (inbox) with bounded size (`actor_inbox_max_items`, default 1000).
- A `list[Message]` (conversation history) — persists across turns within the same actor lifetime.
- A `SlidingWindowRateLimiter` for `send_message` calls.
- A `TriggerPolicy` instance (depth + cooldown tracking).
- An `AgentTurnExecutor` instance.

`start()` creates an asyncio Task running `_run()`. The loop:
1. `await inbox.get()` — blocks until an event arrives.
2. `None` sentinel → stop.
3. Updates `_last_active` (for idle eviction).
4. Checks `TriggerPolicy.should_trigger()` — skip if in cooldown or depth exceeded.
5. Creates `Outbox` and `Trigger` objects.
6. Calls `AgentTurnExecutor.execute_turn()`.

### 8.3 TriggerPolicy — Cooldown and Depth Guards

`src/remora/core/agents/trigger.py`

`TriggerPolicy` enforces two limits per correlation ID:

**Max trigger depth** (`max_trigger_depth`, default 5): Tracks how many times a given `correlation_id` has triggered this actor. If the count exceeds the max, the event is dropped. This prevents infinite trigger chains (agent A triggers agent B triggers agent A...).

**Max reactive turns per correlation** (`max_reactive_turns_per_correlation`, default 3): A stricter limit on reactive (non-chat) turns within the same correlation.

**Cooldown** (`trigger_cooldown_ms`, default 1000ms): After a turn completes, a per-agent cooldown window prevents re-triggering within `cooldown_ms`. Chat events bypass cooldown.

`should_trigger(correlation_id)` → returns True if the event should proceed.
`release_depth(correlation_id)` → decrements depth counter in the `finally` block of each turn.

### 8.4 AgentTurnExecutor — The Turn Pipeline

`src/remora/core/agents/turn.py`

`execute_turn(trigger, outbox)` — the core turn pipeline, always runs under the shared semaphore:

1. **`_start_agent_turn()`**: Fetches node from NodeStore. Transitions status IDLE → RUNNING. Emits `AgentStartEvent`. Gets `AgentWorkspace` and `BundleConfig`.

2. **Compatibility check**: If `bundle_config.externals_version > EXTERNALS_VERSION`, raises `IncompatibleBundleError`. This prevents old bundles from running against a newer runtime API.

3. **Prompt assembly**: `PromptBuilder.build_turn_config()` resolves system prompt and model. `build_user_prompt()` fills the prompt template with node metadata, event content, and companion context.

4. **Companion context**: Loads `companion/reflections`, `companion/chat_index`, `companion/links` from the agent's KV store and appends them to the system prompt if present (unless this is a reflection turn).

5. **Tool discovery**: `discover_tools(workspace, capabilities)` — loads all `_bundle/tools/*.pym` files, wraps each in a `GrailTool`.

6. **Kernel invocation**: `_run_kernel()` — creates an `AgentKernel` with the configured model, calls `kernel.run(messages, tool_schemas, max_turns)`. Supports retry with exponential backoff (up to `max_model_retries`, default 1).

7. **Completion**: Extracts response text. Emits `AgentCompleteEvent` with tags `("primary",)`.

8. **Reflection turn** (if `self_reflect.enabled` in bundle): If the triggering event is an `AgentCompleteEvent` with tag `"primary"`, this is a reflection turn. It uses different prompt (`reflection` prompt template), emits `AgentCompleteEvent` with tags `("reflection",)`, then calls `_emit_turn_digested()`.

9. **Status reset**: Transitions RUNNING → IDLE in `finally` block.

### 8.5 Two-Layer Reflection (Primary + Reflection Turns)

Bundles with `self_reflect.enabled: true` (like `code-agent`) implement a two-turn loop:

**Layer 1 (primary turn)**: Agent responds to the triggering event. Uses main system prompt. Emits `AgentCompleteEvent(tags=("primary",))`.

**Layer 2 (reflection turn)**: The `AgentCompleteEvent` with tag `"primary"` matches a subscription created for self-reflecting agents. It routes back to the same agent's inbox. When the actor processes it, `AgentTurnExecutor` detects `is_reflection_turn=True`, uses the reflection prompt, and expects the agent to use `companion_summarize`, `companion_reflect`, `companion_link` tools to update its companion memory.

After the reflection turn, `TurnDigestedEvent` is emitted with a summary and tags from the companion chat index. The companion virtual agent subscribes to `turn_digested` events and aggregates them for project-level analysis.

### 8.6 Overflow Policies

When an actor's inbox is full (`actor_inbox_max_items`), the overflow policy (`actor_inbox_overflow_policy`) applies:

| Policy | Behavior |
|---|---|
| `drop_new` (default) | Discard the incoming event. Metrics: `actor_inbox_dropped_new_total` |
| `drop_oldest` | Remove oldest item from inbox, enqueue new event. Metrics: `actor_inbox_dropped_oldest_total` |
| `reject` | Reject the event (no enqueue). Metrics: `actor_inbox_rejected_total` |

All overflow events are logged as warnings and tracked in `Metrics.actor_inbox_overflow_total`.

---

## 9. LLM Kernel (structured-agents)

Remora uses the `structured-agents` library as its LLM execution kernel. All model calls flow through a thin wrapper in `src/remora/core/agents/kernel.py`.

### 9.1 AgentKernel

`AgentKernel` (from `structured_agents`) drives the tool-calling loop:

```
run(messages, system_prompt, max_turns)
  └─ loop:
       step()  →  model API call
                  parse response
                  execute tool calls (if any)
                  append results
       until no tool calls OR max_turns reached
  └─ returns KernelResult with final_message
```

The kernel is stateless per-invocation; each call to `kernel.run()` starts fresh with the provided message history.

### 9.2 Kernel Construction

`create_kernel()` in `kernel.py`:

```python
client = build_client({
    "base_url": base_url,
    "api_key": api_key or "EMPTY",
    "model": model_name,
    "timeout": timeout,
})
response_parser = get_response_parser(model_name)
constraint_pipeline = ConstraintPipeline(grammar_config) if grammar_config else None

return AgentKernel(
    client=client,
    response_parser=response_parser,
    tools=tools or [],
    observer=observer or NullObserver(),
    constraint_pipeline=constraint_pipeline,
)
```

- `build_client()` creates an OpenAI-compatible async HTTP client.
- `get_response_parser()` selects the appropriate response parser for the model (handles tool-call JSON variants across providers/models).
- `constraint_pipeline` is optional; enables grammar-constrained decoding.
- `observer` receives lifecycle events (step started, tool call, step done); Remora passes `NullObserver()` by default.

### 9.3 Error Wrapping

`run_kernel()` wraps `kernel.run()` and converts all exceptions to `ModelError`:

```python
async def run_kernel(kernel, *args, **kwargs):
    try:
        return await kernel.run(*args, **kwargs)
    except Exception as exc:
        raise ModelError(f"Model call failed: {exc}") from exc
```

The `ModelError` boundary ensures turn executor error handling always catches a known type.

### 9.4 Response Text Extraction

`extract_response_text(result)` extracts the final text content from a `KernelResult`:

```python
if hasattr(result, "final_message"):
    final_message = result.final_message
    if hasattr(final_message, "content") and final_message.content:
        return final_message.content
return str(result)
```

### 9.5 Tool Integration

`AgentKernel` accepts a `tools` list conforming to the `Tool` protocol:

```python
class Tool(Protocol):
    @property
    def schema(self) -> ToolSchema: ...
    async def execute(self, arguments, context) -> ToolResult: ...
```

Remora's `GrailTool` implements this protocol (see Section 10). Tools are constructed fresh for each turn with the per-turn `TurnContext`-derived capabilities dict.

---

## 10. Tool System (Grail .pym)

Remora agents use **Grail** `.pym` scripts as tools. Grail wraps Monty, a sandboxed Python interpreter implemented in Rust.

### 10.1 .pym File Format

A `.pym` file is a sandboxed Python script with special declarations:

```python
"""Tool description shown to the LLM."""

from grail import Input, external

# Declare typed inputs (become LLM tool parameters)
path = Input(type="str", required=True)
limit = Input(type="int", default=50)

# Declare host-provided async functions
@external
async def read_file(path: str) -> str: ...

@external
async def list_dir(path: str) -> list[str]: ...

# Script body runs on execution
content = await read_file(path)
lines = content.splitlines()[:limit]
output = "\n".join(lines)
```

The script body is the tool implementation. `Input()` declarations become JSON Schema parameters. `@external` declarations are fulfilled by the host (Remora) at execution time.

### 10.2 GrailTool Wrapper

`GrailTool` in `src/remora/core/tools/grail.py` bridges Grail scripts to structured-agents:

```python
class GrailTool:
    def __init__(self, script, *, capabilities, name_override, agent_id, source, ...):
        self._schema = ToolSchema(
            name=name_override or script.name,
            description=_extract_description(script, source),
            parameters=_build_parameters(script),
        )

    async def execute(self, arguments, context) -> ToolResult:
        normalized_arguments = self._normalize_arguments(arguments)
        used_capabilities = {
            name: fn
            for name, fn in self._capabilities.items()
            if name in self._script.externals
        }
        result = await self._script.run(
            inputs=normalized_arguments,
            externals=used_capabilities,
        )
        ...
```

Key details:
- `_build_parameters()` converts `script.inputs` → JSON Schema (`str`→`"string"`, `int`→`"integer"`, etc.)
- `_extract_description()` reads the script's docstring, then falls back to first comment line
- Only capabilities declared as `@external` in the script are injected (security boundary)
- `_normalize_arguments()` fills in defaults for optional inputs not provided by the LLM

### 10.3 Script Loading and Cache

Scripts are loaded from source via `_load_script_from_source()`:

1. Compute SHA-256 hash of source text (first 16 hex chars as key)
2. Check `_PARSED_SCRIPT_CACHE` (LRU dict, max 256 entries)
3. If miss: write source to a temp file, call `grail.load(path)`, cache and return

This avoids re-parsing unchanged `.pym` files across turns.

### 10.4 Tool Discovery

`discover_tools(workspace, capabilities)` loads all `.pym` files from `_bundle/tools/` in an agent workspace:

```python
tool_files = await workspace.list_dir("_bundle/tools")
for filename in tool_files:
    if not filename.endswith(".pym"):
        continue
    source = await workspace.read(f"_bundle/tools/{filename}")
    script = _load_script_from_source(source, filename.removesuffix(".pym"))
    tools.append(GrailTool(script=script, capabilities=capabilities, ...))
```

Invalid scripts are skipped with a warning (error boundary), so one bad tool doesn't prevent others from loading.

---

## 11. Workspace System (Cairn + fsdantic)

Each agent gets a **sandboxed filesystem workspace** backed by Cairn (copy-on-write overlay) and fsdantic (file-system-backed Pydantic models).

### 11.1 Workspace Layout

Workspaces live at `.remora/agents/<safe-id>/` where `<safe-id>` is a deterministic filesystem-safe name derived from the node ID:

```python
normalized = re.sub(r"[^a-zA-Z0-9._-]+", "_", node_id).strip("._-")
digest = hashlib.sha256(node_id.encode()).hexdigest()[:16]
safe_id = f"{normalized[:80]}-{digest}"
```

Inside each workspace:
```
_bundle/
  bundle.yaml          # merged agent configuration
  tools/               # .pym tool scripts
  template_fingerprint  (KV key, not a file)
memory/                # agent-writable memory files
...                    # agent-writable general files
```

### 11.2 AgentWorkspace

`AgentWorkspace` is a thin async wrapper over a Cairn `Workspace`:

| Method | Description |
|---|---|
| `read(path)` | Read file content as string |
| `write(path, content)` | Write file to workspace |
| `exists(path)` | Check file existence |
| `list_dir(path)` | List directory entries (names only) |
| `delete(path)` | Remove a file |
| `list_all_paths()` | List all paths via `ViewQuery(path_pattern="**/*")` |
| `kv_get(key)` | Get KV store entry |
| `kv_set(key, value)` | Set KV store entry |
| `kv_delete(key)` | Delete KV entry |
| `kv_list(prefix)` | List KV keys by prefix |
| `get_companion_data()` | Read companion memory from KV (reflections, chat_index, links) |

### 11.3 CairnWorkspaceService

`CairnWorkspaceService` manages all per-agent workspaces:

- **Lazy creation**: `get_agent_workspace(node_id)` creates and caches on first call
- **Thread safety**: A single `asyncio.Lock` serializes workspace creation
- **Cairn manager**: `WorkspaceManager` tracks all open workspaces for clean shutdown
- **`provision_bundle(node_id, template_dirs)`**: Merges bundle configuration from multiple template dirs into the agent's `_bundle/` directory, using a SHA-256 fingerprint for deduplication (skips re-provisioning if unchanged)

### 11.4 Bundle Provisioning

`provision_bundle()` applies templates in order (system → role-specific):

```python
for template_dir in template_dirs:
    bundle_yaml = template_dir / "bundle.yaml"
    if bundle_yaml.exists():
        loaded = yaml.safe_load(...)
        merged_bundle = deep_merge(merged_bundle, loaded)
    tools_dir = template_dir / "tools"
    for pym_file in sorted(tools_dir.glob("*.pym")):
        await workspace.write(f"_bundle/tools/{pym_file.name}", ...)
if merged_bundle:
    await workspace.write("_bundle/bundle.yaml", yaml.safe_dump(merged_bundle))
await workspace.kv_set("_bundle/template_fingerprint", fingerprint)
```

`deep_merge` ensures later templates can override specific keys while inheriting the rest.

### 11.5 Cairn Under the Hood

Cairn provides:
- **Copy-on-write overlays**: Reads fall through to base layer; writes go to the top layer
- **Transaction semantics**: Changes can be accepted (merged down) or rejected (discarded)
- **Isolated sandboxing**: Each agent's overlay is completely separate from others
- **`workspace_manager`**: Async context manager for lifecycle management

---

## 12. TurnContext and Capabilities API

`TurnContext` (in `src/remora/core/tools/context.py`) is the per-turn object that wires all host capabilities to Grail tool externals.

### 12.1 Construction

Created fresh for each agent turn in `AgentTurnExecutor`:

```python
TurnContext(
    node_id=node.node_id,
    workspace=workspace,
    correlation_id=event.correlation_id,
    node_store=node_store,
    event_store=event_store,
    outbox=outbox,
    human_input_timeout_s=...,
    search_content_max_matches=...,
    broadcast_max_targets=...,
    send_message_limiter=...,
    search_service=...,
    broker=...,
)
```

### 12.2 Capability Groups

`TurnContext` composes 7 capability groups:

| Group | Class | Functions |
|---|---|---|
| Files | `FileCapabilities` | `read_file`, `write_file`, `list_dir`, `file_exists`, `search_files`, `search_content` |
| KV Store | `KVCapabilities` | `kv_get`, `kv_set`, `kv_delete`, `kv_list` |
| Graph | `GraphCapabilities` | `graph_get_node`, `graph_query_nodes`, `graph_get_edges`, `graph_get_children`, `graph_set_status`, `graph_get_importers`, `graph_get_dependencies`, `graph_get_edges_by_type` |
| Events | `EventCapabilities` | `event_emit`, `event_subscribe`, `event_unsubscribe`, `event_get_history` |
| Communication | `CommunicationCapabilities` | `send_message`, `broadcast`, `request_human_input`, `propose_changes` |
| Search | `SearchCapabilities` | `semantic_search`, `find_similar_code` |
| Identity | `IdentityCapabilities` | `get_node_source`, `my_node_id`, `my_correlation_id` |

`to_capabilities_dict()` merges all 7 `to_dict()` returns into a single flat dict of `{function_name: async_function}` passed to `GrailTool` at execution time.

### 12.3 Notable Implementations

**`search_content`**: Iterates all workspace paths, reads only text extensions (`.py`, `.md`, `.toml`, `.yaml`, `.yml`, `.json`, `.txt`, `.pym`), does literal string match per line. Returns `[{file, line, text}]` limited to `search_content_max_matches`.

**`graph_query_nodes`**: Full validation of `node_type` and `status` enum values with helpful error messages. Includes a compatibility fallback: if `node_type` is an unrecognized string, it's treated as a role filter.

**`broadcast`**: Fan-out `AgentMessageEvent` to multiple targets. Patterns: `"*"` or `"all"` (everyone), `"siblings"` (same file), `"file:<path>"`, or substring match on node IDs.

**`propose_changes`**: Transitions agent to `awaiting_review`, emits `RewriteProposalEvent` with all changed files. The human operator reviews and approves/rejects via the web UI.

**`request_human_input`**: Transitions agent to `awaiting_input`, emits `HumanInputRequestEvent`, awaits a `asyncio.Future` on `HumanInputBroker`. The human responds via the web chat UI, fulfilling the future.

**`event_emit`**: Wraps arbitrary payload as `CustomEvent` with current correlation ID.

**`event_subscribe`**: Registers a `SubscriptionPattern` for this agent — agents can dynamically subscribe to events from tool scripts.

### 12.4 Versioning

`EXTERNALS_VERSION = 3` is injected into agent system prompts to help agents know which capabilities are available when referencing the externals API documentation.

---

## 13. Bundle System

Bundles are the packaging mechanism for agent configuration + tool scripts. Every agent gets a **merged bundle** from multiple ordered template directories.

### 13.1 Bundle Directory Structure

```
bundles/
  system/              # Applied to ALL agents
    bundle.yaml
    tools/
      read_source.pym
      list_workspace.pym
      ...
  code-agent/          # Applied to function/class/method nodes
    bundle.yaml
    tools/
      propose_refactor.pym
      ...
  directory-agent/     # Applied to directory nodes
    bundle.yaml
    tools/
      ...
  companion/           # Applied to companion virtual agent
    bundle.yaml
    tools/
      companion_summarize.pym
      companion_reflect.pym
      companion_link.pym
```

### 13.2 bundle.yaml Schema

```yaml
# System prompt (Jinja2 template)
system_prompt: |
  You are an autonomous agent for {{ node_id }}...

# Model settings
model:
  name: "${REMORA_MODEL:-Qwen/Qwen3-4B-Instruct-2507-FP8}"
  base_url: "${REMORA_MODEL_URL:-http://remora-server:8000/v1}"
  api_key: "${REMORA_API_KEY:-EMPTY}"
  timeout: 300

# Turn limits
max_turns: 20

# Two-layer reflection control
self_reflect:
  enabled: true
  reflection_prompt: |
    Review your previous response and update your memory...
```

### 13.3 Bundle Resolution

`Config.resolve_bundle(node_type, role)` returns the ordered list of template dirs to merge:

1. **System bundle** (always first): `bundles/system/`
2. **Role bundle** (if `role` is set): `bundles/<role>/`
3. **Default type bundle** (if no role): `bundles/<node_type>/` (e.g. `bundles/code-agent/`)

The `FileReconciler` calls `workspace_service.provision_bundle(node_id, template_dirs)` during reconciliation, so bundles are automatically updated when code changes.

### 13.4 Runtime Bundle Reading

During a turn, `AgentTurnExecutor` reads the agent's provisioned bundle via `workspace_service.read_bundle_config(node_id)`:
- Reads `_bundle/bundle.yaml` from the workspace
- Expands `${ENV_VAR:-default}` references
- Validates as `BundleConfig` Pydantic model
- Returns model and prompt config for the turn

If `self_reflect.enabled` is false, the key is stripped entirely before validation to prevent accidental reflection turns.

---

## 14. Virtual Agents

Virtual agents are LLM agents that are not backed by any discovered code node. They are declared in `remora.yaml` and materialized by `VirtualAgentManager`.

### 14.1 Configuration

```yaml
virtual_agents:
  - id: "companion"
    role: "companion"
    subscriptions:
      - event_types: ["turn_digested"]
  - id: "review-agent"
    role: "review-agent"
    subscriptions:
      - event_types: ["agent_complete"]
        tags: ["proposed"]
```

Each `VirtualAgentConfig` has:
- `id`: Unique node ID (also used as the node name)
- `role`: Bundle role to provision (e.g. `"companion"` → `bundles/companion/`)
- `subscriptions`: List of `SubscriptionPattern` dicts

### 14.2 VirtualAgentManager.sync()

Called during lifecycle startup. Performs a diff-and-update:

1. Load existing `NodeType.VIRTUAL` nodes from DB
2. Compare with desired set from config
3. Delete stale virtual nodes (no longer in config)
4. For each desired virtual agent:
   - Create `Node(node_type=VIRTUAL, file_path="", text="", ...)`
   - Compute `source_hash` from `{role, subscriptions}` JSON
   - If new: upsert + register subscriptions + provision bundle + emit `NodeDiscoveredEvent`
   - If changed (hash differs): update node + re-provision + emit `NodeChangedEvent`
   - If unchanged: re-register subscriptions + re-provision (idempotent; fingerprint prevents actual copy)

### 14.3 Virtual Agent Lifecycle

Virtual agents respond to events just like code-backed agents. The key difference is their "source text" is empty — their identity comes entirely from their bundle configuration. The `companion` virtual agent is a built-in example: it receives `TurnDigestedEvent` from all agents doing self-reflection and accumulates project-level observations.

---

## 15. Directory Agents

Directory agents are automatically-created nodes that represent filesystem directories. They bridge the gap between file-level and function-level code agents.

### 15.1 DirectoryManager

`DirectoryManager` (in `src/remora/code/directories.py`) derives directory nodes from the set of discovered file paths. Called by `FileReconciler` during both `full_scan()` and post-reconciliation.

**`compute_hierarchy(file_paths)`**: Walks all discovered file paths upward to the root, collecting all intermediate directory paths. Returns `(dir_paths, children_by_dir)`.

**`materialize(file_paths, sync_existing_bundles)`**:
1. Compute desired directory hierarchy
2. Diff against existing `NodeType.DIRECTORY` nodes in DB
3. Remove stale directories (sorted deepest-first for correct deletion order)
4. Upsert each directory node: creates a `Node` where the `source_hash` is SHA-256 of sorted children list — any change in directory contents triggers a `NodeChangedEvent`

### 15.2 Directory Node Identity

- `node_id` = relative POSIX path from project root (e.g. `"src/remora/core"`)
- `node_type` = `NodeType.DIRECTORY`
- `file_path` = same as `node_id`
- `text` = empty
- Parent-child edges: `(parent_dir, child_dir, "contains")` stored in `NodeEdges` table

### 15.3 Directory Subscriptions

`SubscriptionManager` registers directory nodes for:
- `NodeChangedEvent` matching `path_glob="**/src/remora/core/**"` (subtree changes)
- `ContentChangedEvent` matching the same glob

This means a directory agent fires whenever any file in its subtree changes — enabling hierarchical analysis (e.g. "what changed in `src/remora/core/` this turn?").

---

## 16. Subscription System

The subscription system decides which agents receive which events. It is a filter registry that sits between the `EventStore` and the `TriggerDispatcher`.

### 16.1 SubscriptionRegistry

Lives at `event_store.subscriptions` (a `SubscriptionRegistry` instance backed by SQLite).

**`register(node_id, pattern)`**: Inserts a subscription row. Returns subscription ID (integer).

**`unregister(subscription_id)`**: Removes a specific subscription.

**`unregister_by_agent(node_id)`**: Removes all subscriptions for an agent. Called before re-registration on each reconcile cycle.

**`find_matching_agents(event)`**: The hot path — queries all subscriptions and returns node IDs of agents whose pattern matches the event.

### 16.2 SubscriptionPattern

```python
@dataclass
class SubscriptionPattern:
    event_types: list[str] | None = None   # None = match all
    from_agents: list[str] | None = None   # None = match all
    to_agent: str | None = None            # direct-addressed events
    path_glob: str | None = None           # fnmatch on event.path
    tags: list[str] | None = None          # any tag in event.tags
```

A pattern matches an event if **all** specified conditions are satisfied. `None` means "match any".

### 16.3 Default Subscriptions by Node Type

| Node Type | Default Subscriptions |
|---|---|
| Any | `to_agent=node_id` (direct addressing) |
| Code (function, class, etc.) | `ContentChangedEvent` matching `path_glob=node.file_path` |
| Code with self-reflect | Also: `AgentCompleteEvent` from self with tag `"primary"` |
| Directory | `NodeChangedEvent` + `ContentChangedEvent` matching subtree glob |
| Virtual | Explicitly declared patterns from `virtual_agents` config |

### 16.4 Subscription Lifecycle

Subscriptions are ephemeral per process but stored in SQLite. On each process start, `SubscriptionManager.register_for_node()` re-registers all subscriptions for every node (called during full scan and incremental reconcile). This ensures the subscription set always reflects the current node state and bundle configuration.

---

## 17. Web Server and SSE Streaming

Remora exposes a web interface via a Starlette ASGI application, served by Uvicorn.

### 17.1 Application Factory

`create_app()` in `src/remora/web/server.py` creates the Starlette app:
- Routes: `/`, `/nodes`, `/events`, `/chat`, `/proposals`, `/search`, `/health`, `/cursor`
- Middleware: `CSRFMiddleware` (token validation on mutating requests)
- Static files: `src/remora/web/static/` mounted at `/static`
- State: `app.state.deps = WebDeps(...)` — shared dependency container
- Lifespan: Sets `shutdown_event` on Starlette exit

### 17.2 Route Overview

| Route | Method | Description |
|---|---|---|
| `/` | GET | Serve `index.html` SPA |
| `/nodes` | GET | List all nodes as JSON |
| `/nodes/{id}` | GET | Get single node |
| `/nodes/{id}/status` | PUT | Set node status |
| `/events` | GET | SSE stream of all events |
| `/events` | GET `?after=N` | SSE replay from event ID N |
| `/chat/{node_id}` | POST | Send chat message to agent |
| `/chat/{node_id}/history` | GET | Get conversation history |
| `/proposals/{id}/accept` | POST | Accept a rewrite proposal |
| `/proposals/{id}/reject` | POST | Reject a rewrite proposal |
| `/search` | POST | Semantic search query |
| `/health` | GET | Health check + metrics |
| `/cursor` | GET | Get active cursor/focus node |

### 17.3 SSE Streaming

`src/remora/web/sse.py` implements Server-Sent Events:

```
GET /events
  → opens EventBus.stream() context manager
  → replays all events since `after` param (via EventStore.get_events_after())
  → then yields live events as JSON-encoded SSE data
  → client reconnects automatically using Last-Event-ID header
```

Each SSE message is:
```
id: 42
data: {"event_id": 42, "event_type": "agent_complete", "node_id": "...", ...}

```

The web UI uses this stream to update agent status indicators and event logs in real time.

### 17.4 Chat API

`POST /chat/{node_id}` with `{"message": "...", "conversation_id": "..."}`:
1. Rate-limit check per `node_id` using `SlidingWindowRateLimiter`
2. Validate message length (max `chat_message_max_chars`)
3. Append `AgentMessageEvent(from_agent="user", to_agent=node_id, content=message)`
4. Return `{"status": "sent"}`

The agent's actor picks up the message event from the subscription system (via `to_agent=node_id` match).

### 17.5 Web UI

The single-page application at `src/remora/web/static/index.html` is a self-contained HTML+JS file that:
- Subscribes to `/events` SSE stream
- Renders the node graph (status, type, file path)
- Shows per-agent event history
- Provides a chat panel for human interaction
- Shows proposal review UI (accept/reject)

---

## 18. LSP Integration

The optional LSP adapter lets editors (VS Code, Neovim, etc.) display Remora agent status directly in the code.

### 18.1 Starting the LSP

```bash
remora start --lsp           # start web + LSP together
remora lsp --db-path ...     # standalone LSP reading from existing DB
```

The `--lsp` flag causes `RemoraLifecycle` to start `pygls`'s TCP server alongside the web server.

### 18.2 LSP Features

**CodeLens** (`textDocument/codeLens`): For each node in the current file, returns a lens showing agent status:

```
○ my_function                   ← idle
▶ MyClass                       ← running
```

**Hover** (`textDocument/hover`): At the cursor position, shows:
- Node ID, type, status
- Caller/callee graph edges
- 5 most recent events

**CodeAction** (`textDocument/codeAction`): "Open chat" and "Trigger agent" quick actions at the cursor.

### 18.3 Event Forwarding

**`textDocument/didSave`**: Emits `ContentChangedEvent(path=file_path, change_type=MODIFIED)` — same as what `watchfiles` would emit. This means saving a file in the editor immediately triggers agent processing, even if the filesystem watcher hasn't fired yet.

**`textDocument/didOpen`**: Emits `ContentChangedEvent(change_type=OPENED)`.

**`textDocument/didChange`**: Updates in-memory `DocumentStore` (text tracking for accurate hover position calculation).

### 18.4 Custom Commands

**`remora.chat`**: Opens `http://localhost:8080/?node=<id>` in the browser — jumps to the chat panel for that agent.

**`remora.trigger`**: Sends an `AgentMessageEvent(from_agent="user", content="Manual trigger from editor")` to the agent — manually kicks off a turn.

### 18.5 Standalone vs Integrated Mode

- **Integrated**: `create_lsp_server(node_store=..., event_store=...)` shares in-memory stores with the running Remora instance.
- **Standalone**: `create_lsp_server(db_path=...)` opens its own read-only SQLite connections for CodeLens/Hover queries without running agents.

---

## 19. Semantic Search (embeddy)

Semantic search is an optional feature powered by the `embeddy` library. It enables agents to find semantically similar code using vector embeddings.

### 19.1 Two Deployment Modes

**Remote mode** (`search.mode: remote`):
- Connects to a running `embeddy` HTTP server
- Checks health on startup; degrades gracefully if unreachable
- All operations via HTTP (search, find_similar, index_file, delete_source)

**Local mode** (`search.mode: local`):
- Runs embeddy in-process with a local SQLite vector store
- Uses a local embedding model (e.g. `sentence-transformers/all-MiniLM-L6-v2`)
- Requires `uv sync --extra search-local`

### 19.2 SearchServiceProtocol

`SearchServiceProtocol` is a runtime-checkable Protocol defining the service boundary:

```python
class SearchServiceProtocol(Protocol):
    @property
    def available(self) -> bool: ...
    async def search(self, query, collection, top_k, mode) -> list[dict]: ...
    async def find_similar(self, chunk_id, collection, top_k) -> list[dict]: ...
    async def index_file(self, path, collection) -> None: ...
    async def delete_source(self, path, collection) -> None: ...
```

`SearchService` implements this protocol. When disabled or unavailable, `available=False` and all methods return `[]`.

### 19.3 Indexing

The `remora index` CLI command triggers directory indexing via `SearchService.index_directory()`. Files are also re-indexed during reconciliation when content changes (if search is enabled).

`collection_for_file(path)` maps file extensions to collection names via `search.collection_map` config. Defaults: all extensions → `search.default_collection`.

### 19.4 Search Modes

Embeddy supports three search modes:
- `"vector"`: Pure vector similarity search
- `"keyword"`: BM25 keyword search
- `"hybrid"` (default): Combines both with RRF (Reciprocal Rank Fusion)

### 19.5 Agent Usage

Agents call `semantic_search(query, collection, top_k, mode)` and `find_similar_code(chunk_id, collection, top_k)` via their tool externals. Results include chunk ID, content, score, source path, line numbers, and metadata.

---

## 20. Lifecycle and Runtime Startup/Shutdown

`RemoraLifecycle` in `src/remora/core/services/lifecycle.py` orchestrates the ordered startup and shutdown of all Remora components.

### 20.1 Startup Sequence

```
1. DB open              — AsyncDB open, create tables
2. Services init        — CairnWorkspaceService.initialize()
                          SearchService.initialize()
3. Virtual agents sync  — VirtualAgentManager.sync()
4. Full scan            — FileReconciler.full_scan()
                          (discovers all nodes, provisions bundles, registers subscriptions)
5. Directory materialize — DirectoryManager.materialize()
6. Background tasks:
   - Reconciler watch loop  (FileReconciler.start())
   - Uvicorn web server     (if not --no-web)
   - LSP TCP server          (if --lsp)
   - Metrics reporter        (periodic logging)
```

Steps 1-5 run sequentially at startup before serving any requests or processing any events. This guarantees the node graph is fully populated before agents begin firing.

### 20.2 Shutdown Sequence

Graceful shutdown is triggered by SIGINT/SIGTERM or Starlette lifespan exit:

```
1. FileReconciler.stop()    — stop watchfiles loop
2. ActorPool.drain()        — wait for all in-progress turns to complete
3. Web server exit          — signal Uvicorn to stop
4. SearchService.close()    — close embeddy connections
5. AsyncDB.close()          — flush WAL, close SQLite
6. Background tasks cancel  — cancel all asyncio Tasks
```

Order matters: the actor pool must drain before the DB closes, so no in-flight turn writes are lost.

### 20.3 RuntimeServices Container

`RuntimeServices` in `src/remora/core/services/container.py` is the dependency injection container. Created once and passed to the lifecycle:

```python
services = RuntimeServices(config, project_root)
await services.initialize()
# services.node_store, services.event_store, services.workspace_service,
# services.actor_pool, services.search_service, services.metrics, ...
```

All service dependencies are resolved in `initialize()`, creating a fully wired object graph.

### 20.4 TransactionContext

`TransactionContext` in `src/remora/core/storage/transaction.py` batches SQLite writes:

```python
async with TransactionContext(db) as tx:
    await tx.execute("INSERT INTO nodes ...", ...)
    await tx.execute("INSERT INTO events ...", ...)
# COMMIT here, then fan-out events to EventBus
```

Events are queued during the transaction and emitted to `EventBus` only after the SQLite commit succeeds. This prevents actors from receiving events for writes that were rolled back.

### 20.5 Manual Task Management

`RemoraLifecycle` maintains its own list of `asyncio.Task` objects rather than relying on a `TaskGroup`, allowing individual task failures to be isolated and logged without crashing the entire runtime.

---

## 21. CLI Commands

Remora's CLI is implemented with Typer in `src/remora/__main__.py`.

### 21.1 `remora start`

```bash
remora start [OPTIONS]
remora start --config remora.yaml --port 8080 --lsp --no-web
```

Options:
- `--config PATH`: Path to `remora.yaml` (default: auto-discovered)
- `--port INT`: Web server port (default: 8080)
- `--lsp`: Enable LSP server on port 2087
- `--lsp-port INT`: LSP TCP port (default: 2087)
- `--no-web`: Disable web server (agents-only mode)
- `--log-level`: Logging verbosity

Start sequence: load config → `RuntimeServices` → `RemoraLifecycle.start()` → `asyncio.run()`.

Structured JSON logging is injected when `--log-level` is set to `DEBUG` or `INFO`, replacing default Python logging with structured output.

### 21.2 `remora discover`

```bash
remora discover [--config PATH] [--output json|table]
```

Runs a one-shot discovery scan and prints discovered nodes. Does not start agents or the web server. Useful for debugging `discovery_paths` and tree-sitter queries.

### 21.3 `remora index`

```bash
remora index [--config PATH] [--path DIR] [--collection NAME]
```

Triggers semantic indexing of the specified directory (or the configured discovery paths) via `SearchService.index_directory()`. Only meaningful if search is configured.

### 21.4 `remora lsp`

```bash
remora lsp [--db-path PATH] [--web-port INT]
```

Starts a standalone LSP server that connects to an existing Remora SQLite database without running agents. Useful for read-only editor integration (CodeLens, Hover) alongside a separately-running `remora start`.

---

## 22. Testing Infrastructure

Remora has a layered test suite with four distinct profiles.

### 22.1 Test Structure

```
tests/
  unit/                    # Pure unit tests (no DB, no model)
    test_discovery.py
    test_reconciler.py
    test_actor.py
    test_turn.py
    ...
  integration/             # Integration tests (SQLite, no model)
    test_event_store.py
    test_node_store.py
    test_workspace.py
    test_llm_turn.py       # (real_llm marker)
    cairn/                 # Cairn-specific integration
  acceptance/              # Full process-boundary tests
    test_lifecycle.py
    test_lsp.py
    ...
  benchmarks/              # Performance benchmarks (skipped in CI)
```

### 22.2 Test Markers

| Marker | Description | Requires |
|---|---|---|
| *(no marker)* | Fast unit/integration tests | Nothing |
| `acceptance` | Process-boundary tests | Nothing special |
| `real_llm` | Tests making actual LLM calls | `REMORA_TEST_MODEL_URL` env var |

### 22.3 Test Profiles

**Core CI** (deterministic, no environment dependencies):
```bash
devenv shell -- pytest tests/ \
  --ignore=tests/benchmarks \
  --ignore=tests/integration/cairn \
  -m "not acceptance and not real_llm" -q
```

**Fast actor-level LLM checks**:
```bash
devenv shell -- env \
  REMORA_TEST_MODEL_URL='http://remora-server:8000/v1' \
  REMORA_TEST_MODEL_NAME='Qwen/Qwen3-4B-Instruct-2507-FP8' \
  pytest tests/integration/test_llm_turn.py -m real_llm -q -rs
```

**Process-boundary acceptance**:
```bash
devenv shell -- pytest tests/acceptance -m acceptance -q -rs
```

**Full real-world with model**:
```bash
devenv shell -- env \
  REMORA_TEST_MODEL_URL='...' REMORA_TEST_MODEL_NAME='...' \
  pytest tests/acceptance -m "acceptance and real_llm" -q -rs
```

### 22.4 Acceptance Test Design

Acceptance tests start real Remora processes (via subprocess or in-process async), send events, and poll for expected outcomes within strict timeouts. Key techniques:
- **Deterministic correlation IDs**: Tests inject known IDs to trace event chains
- **Polling with timeouts**: `await poll_until(condition, timeout=5.0)` avoids arbitrary sleeps
- **In-process isolation**: Each test gets a fresh SQLite DB in a temp directory
- **Event order verification**: Tests check both that events occurred and in the expected sequence

### 22.5 DevEnv

All tests run via `devenv shell -- pytest ...`. The `devenv` command activates the Nix-managed development environment that provides Python, tree-sitter language grammars, and all dependencies without requiring manual `pip install`.

---

## 23. Extension Points

Remora is designed to be extended at several well-defined seams.

### 23.1 Custom Tree-Sitter Queries

Override discovery queries per language by placing `.scm` files in directories listed in `query_search_paths`:

```yaml
query_search_paths:
  - ./my-queries
```

A file at `my-queries/python.scm` completely overrides the built-in Python query. Query files use standard tree-sitter S-expression syntax.

### 23.2 Custom Bundles

Create new bundle directories with `bundle.yaml` + `tools/` subdirectory:

```yaml
# remora.yaml
bundle_search_paths:
  - ./bundles
```

Reference custom bundles via `role` in `virtual_agents` or `bundle_map`:

```yaml
bundle_map:
  function: my-function-agent
  class: my-class-agent
```

### 23.3 Custom .pym Tools

Add `.pym` files to any bundle's `tools/` directory. The agent receives them automatically on next reconcile. Tools can declare any subset of the 28 externals — unused ones are not injected.

### 23.4 Virtual Agents

Add declarative agents with custom event subscriptions to handle cross-cutting concerns:

```yaml
virtual_agents:
  - id: "security-scanner"
    role: "security-scanner"
    subscriptions:
      - event_types: ["agent_complete"]
        tags: ["proposed"]
        path_glob: "src/**/*.py"
```

### 23.5 Custom Language Support

Add new languages to `language_map` in `remora.yaml`:

```yaml
language_map:
  ".rb": "ruby"
  ".go": "go"
```

Provide corresponding tree-sitter grammar and `.scm` query file.

### 23.6 External Capabilities (EXTERNALS_VERSION 3)

The 28 built-in externals cover files, KV, graph, events, communication, search, and identity. Additional capabilities can be added to `TurnContext` by:

1. Creating a new `XyzCapabilities` class with async methods and `to_dict()`
2. Composing it in `TurnContext.__init__()`
3. Merging it in `to_capabilities_dict()`
4. Bumping `EXTERNALS_VERSION`
5. Updating `docs/externals-api.md`

### 23.7 Custom Event Types

Agents can emit `CustomEvent` with arbitrary `event_type` strings and `payload` dicts. Other agents can subscribe to these custom types using `event_subscribe`. This creates a fully dynamic inter-agent protocol without requiring changes to the Remora codebase.

### 23.8 LLM Provider Swap

Any OpenAI-compatible API endpoint works. Change `model.base_url` in `bundle.yaml` or via environment variable `REMORA_MODEL_URL`. The `get_response_parser(model_name)` in structured-agents selects the correct response parsing strategy based on the model name.

### 23.9 Metrics and Observability

`Metrics` in `src/remora/core/services/metrics.py` tracks counters (turns completed, errors, inbox overflows, workspace cache hits, etc.). The `/health` endpoint exposes these as JSON. Integrate with external monitoring by scraping `/health` or extending the metrics reporter background task.

---

*End of Guide*

