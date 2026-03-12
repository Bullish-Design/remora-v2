# Remora v2 — Implementation Plan

**REMINDER: NEVER use the Task (subagent) tool. Do all work directly.**

A phased, step-by-step plan for building Remora v2 from scratch in a new
greenfield repository. Each phase produces testable artifacts with explicit
exit criteria. No phase begins until the previous phase's tests pass.

---

## Table of Contents

### Phase 0: Repository Bootstrap
0.1 [Create repo, pyproject.toml, dev tooling](#01-repo-and-tooling) — Skeleton with CI-ready test runner
0.2 [Shared test fixtures (conftest.py)](#02-shared-test-fixtures) — tmp_path DB, async helpers
- **Testing**: `pytest` runs, `ruff check` passes, editable install works

### Phase 1: Core Data Models
1.1 [core/config.py](#11-config) — Config + load_config + env expansion
1.2 [core/node.py](#12-codenode) — CodeNode model + to_row/from_row
1.3 [core/events.py — Event types](#13-event-types) — Base Event + all concrete event Pydantic models
- **Testing**: Unit tests for config loading, CodeNode roundtrip, event serialization

### Phase 2: Persistence Layer
2.1 [core/events.py — EventBus](#21-eventbus) — In-memory pub/sub with MRO dispatch + stream()
2.2 [core/events.py — SubscriptionRegistry](#22-subscriptionregistry) — SQLite-backed pattern matching with cache
2.3 [core/events.py — EventStore](#23-eventstore) — Append-only SQLite + trigger queue integration
2.4 [core/graph.py — NodeStore](#24-nodestore) — SQLite CRUD for CodeNode + edges
- **Testing**: EventBus emit/subscribe, subscription matching, EventStore append→trigger flow, NodeStore CRUD + edge ops

### Phase 3: Workspace + Tools
3.1 [core/workspace.py — AgentWorkspace](#31-agentworkspace) — Cairn wrapper with read/write/list/exists/delete
3.2 [core/workspace.py — CairnWorkspaceService](#32-cairnworkspaceservice) — Lifecycle manager + provision_bundle()
3.3 [core/grail.py](#33-grail-tool-loading) — GrailTool + discover_tools from workspace
3.4 [core/kernel.py](#34-kernel) — create_kernel + extract_response_text wrappers
- **Testing**: Workspace CRUD, bundle provisioning + template layering, tool discovery from workspace, kernel creation with mock client

### Phase 4: Runner + Externals
4.1 [Externals builder (_build_externals)](#41-externals-builder) — All 16 externals as closures
4.2 [core/runner.py — AgentRunner](#42-agentrunner) — trigger(), execute_turn(), run_forever()
4.3 [System .pym tools](#43-system-pym-tools) — send_message, subscribe, unsubscribe, broadcast, query_agents
- **Testing**: Externals contract test (every external callable + returns expected types), runner cooldown/depth logic, full turn integration test with mock kernel

### Phase 5: Code Plugin
5.1 [code/discovery.py](#51-discovery) — CSTNode model + tree-sitter discover()
5.2 [code/projections.py](#52-projections) — CSTNode → CodeNode + workspace provisioning
5.3 [code/reconciler.py](#53-reconciler) — reconcile_on_startup + file watching
5.4 [Code .pym tools](#54-code-pym-tools) — rewrite_self, scaffold
- **Testing**: Python function/class discovery, projection hash-change detection, full reconciler pipeline, rewrite proposal flow

### Phase 6: Web Surface
6.1 [web/server.py](#61-web-server) — Starlette app + SSE + REST endpoints
6.2 [web/views.py](#62-graph-visualization) — Sigma.js/graphology HTML + JS
6.3 [Companion .pym tools](#63-companion-pym-tools) — summarize, categorize, find_links, reflect
- **Testing**: HTTP endpoint smoke tests, SSE stream validation, companion tool execution

### Phase 7: CLI + LSP
7.1 [CLI entry point (__main__.py)](#71-cli) — click group with `remora start`
7.2 [lsp/server.py](#72-lsp-adapter) — Optional thin LSP adapter
- **Testing**: CLI invocation smoke test, LSP code lens + hover rendering

### Phase 8: End-to-End Validation
8.1 [Full pipeline test](#81-full-pipeline) — Source files → discovery → graph → trigger → turn → rewrite → approval
8.2 [Performance baseline](#82-performance-baseline) — Graph with 100+ nodes, measure discovery + trigger latency
- **Testing**: E2E test passes, performance within acceptable bounds

---

## Phase 0: Repository Bootstrap

### 0.1 Repo and Tooling

**Create the new repository with:**

```
remora-v2/
├── pyproject.toml
├── remora.yaml.example
├── src/
│   └── remora/
│       ├── __init__.py          # version = "0.5.0"
│       ├── __main__.py          # placeholder: print("remora v2")
│       ├── core/
│       │   └── __init__.py
│       ├── code/
│       │   └── __init__.py
│       ├── web/
│       │   └── __init__.py
│       ├── lsp/
│       │   └── __init__.py
│       └── utils/
│           └── __init__.py
├── bundles/                     # empty template dirs, populated in Phase 4+5
│   ├── system/
│   │   ├── bundle.yaml
│   │   └── tools/
│   ├── code-agent/
│   │   ├── bundle.yaml
│   │   └── tools/
│   └── companion/
│       ├── bundle.yaml
│       └── tools/
└── tests/
    ├── conftest.py
    ├── unit/
    └── integration/
```

**pyproject.toml** — as specified in IMPLEMENTATION_GUIDE.md §5.2:
- Python >=3.13
- Dependencies: pydantic, pydantic-settings, pyyaml, structured-agents, cairn, grail, tree-sitter, starlette, uvicorn, click
- Optional deps: `lsp` (pygls, lsprotocol), `dev` (pytest, pytest-asyncio, ruff)
- Script entry: `remora = "remora.__main__:main"`
- Build system: hatchling

**Dev tooling:**
- `ruff.toml` with standard Python formatting rules
- `.gitignore` for Python projects + `.remora/`

### 0.2 Shared Test Fixtures

**tests/conftest.py:**

```python
import asyncio
import sqlite3
import pytest

@pytest.fixture
def db_connection(tmp_path):
    """Shared SQLite connection with WAL mode."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()

@pytest.fixture
def db_lock():
    """Shared asyncio lock for SQLite serialization."""
    return asyncio.Lock()
```

### Phase 0 — Testing Checklist

| Test | What it validates |
|------|-------------------|
| `pytest --co` | Test collection works (conftest loads) |
| `ruff check src/ tests/` | Linting passes on skeleton |
| `pip install -e ".[dev]"` | Editable install succeeds |
| `python -m remora` | Entry point runs without error |

**Exit criteria:** `pytest` collects 0 tests with no errors, `ruff` passes, editable install works.

---

## Phase 1: Core Data Models

### 1.1 Config

**File:** `src/remora/core/config.py`

Implement:
- `Config(BaseSettings)` with all fields from IMPLEMENTATION_GUIDE.md §6
- `load_config(path)` — YAML loading with directory walk-up
- `_expand_env_vars(data)` — `${VAR:-default}` expansion helper
- `_find_config_file()` — walk up from cwd to find `remora.yaml`

Key fields: `project_path`, `discovery_paths`, `discovery_languages`, `bundle_root`, `bundle_mapping`, `model_base_url`, `model_default`, `model_api_key`, `timeout_s`, `max_turns`, `swarm_root`, `max_concurrency`, `max_trigger_depth`, `trigger_cooldown_ms`, `workspace_ignore_patterns`

### 1.2 CodeNode

**File:** `src/remora/core/node.py`

Implement:
- `CodeNode(BaseModel)` with all fields from IMPLEMENTATION_GUIDE.md §7
- `to_row()` — serialize for SQLite, JSON-encode list fields
- `from_row(cls, row)` — hydrate from SQLite row, JSON-decode lists
- Identity fields: node_id, node_type, name, full_name, file_path, start_line, end_line, start_byte, end_byte, source_code, source_hash
- Graph context: parent_id, caller_ids, callee_ids
- Runtime: status, bundle_name

### 1.3 Event Types

**File:** `src/remora/core/events.py` (first section — event models only)

Implement:
- `Event(BaseModel)` base with event_type, timestamp, correlation_id
- `model_post_init` to auto-set event_type from class name
- All concrete event types from IMPLEMENTATION_GUIDE.md §8.1:
  - Agent lifecycle: `AgentStartEvent`, `AgentCompleteEvent`, `AgentErrorEvent`
  - Communication: `AgentMessageEvent`, `HumanChatEvent`, `AgentTextResponse`
  - Code changes: `NodeDiscoveredEvent`, `NodeChangedEvent`, `ContentChangedEvent`, `RewriteProposalEvent`
  - Tools: `ToolResultEvent`

### Phase 1 — Testing Checklist

| Test | What it validates |
|------|-------------------|
| `test_default_config()` | Config() creates with sensible defaults |
| `test_load_from_yaml(tmp_path)` | YAML file overrides defaults correctly |
| `test_env_var_expansion()` | `${VAR:-default}` resolves correctly |
| `test_find_config_file(tmp_path)` | Walk-up finds remora.yaml in parent dirs |
| `test_codenode_creation()` | CodeNode with all required fields validates |
| `test_codenode_roundtrip()` | to_row() → from_row() preserves all fields |
| `test_codenode_list_serialization()` | caller_ids/callee_ids JSON encode/decode |
| `test_event_base_auto_type()` | Event subclass auto-sets event_type to class name |
| `test_event_timestamp()` | Events get auto-timestamps |
| `test_event_serialization()` | model_dump() produces correct dict |
| `test_all_event_types_instantiate()` | Every concrete event type can be constructed |

**Exit criteria:** All 11 tests pass. Config, CodeNode, and all Event types are importable and serialize correctly.

---

## Phase 2: Persistence Layer

### 2.1 EventBus

**Add to:** `src/remora/core/events.py`

Implement:
- `EventBus` class with `_handlers` (type→list) and `_all_handlers`
- `emit(event)` — MRO-based dispatch, handles both sync and async handlers
- `subscribe(event_type, handler)` — register for a specific type
- `subscribe_all(handler)` — register for all events
- `unsubscribe(handler)` — remove from all subscription lists
- `stream(*event_types)` — async context manager yielding AsyncIterator[Event]

### 2.2 SubscriptionRegistry

**Add to:** `src/remora/core/events.py`

Implement:
- `SubscriptionPattern(BaseModel)` with event_types, from_agents, to_agent, path_glob
- `SubscriptionPattern.matches(event)` — field-by-field matching with None=match-all
- `SubscriptionRegistry` class with SQLite backend + in-memory cache
- `register(agent_id, pattern)` → subscription ID
- `unregister(subscription_id)` → bool
- `get_matching_agents(event)` → list[str]
- Cache: indexed by event_type, invalidated on mutation
- SQL: `subscriptions` table with agent_id, pattern_json, created_at

### 2.3 EventStore

**Add to:** `src/remora/core/events.py`

Implement:
- `EventStore` class with SQLite WAL-mode backend
- `initialize()` — create tables, set pragmas
- `append(event)` → event ID; after append: forward to EventBus + match subscriptions → enqueue triggers
- `get_events(limit)` → list[dict]
- `get_events_for_agent(agent_id, limit)` → list[dict]
- `get_triggers()` → AsyncIterator[tuple[str, Event]] (from trigger queue)
- Internal `_trigger_queue: asyncio.Queue`
- SQL: `events` table with id, event_type, agent_id, from_agent, to_agent, correlation_id, timestamp, payload, summary

### 2.4 NodeStore

**File:** `src/remora/core/graph.py`

Implement:
- `Edge` dataclass: from_id, to_id, edge_type
- `NodeStore` class with shared SQLite connection + lock
- `create_tables()` — nodes + edges tables
- `upsert_node(node)` — INSERT OR REPLACE
- `get_node(node_id)` → CodeNode | None
- `list_nodes(node_type, status, file_path)` → filtered list
- `delete_node(node_id)` — cascade delete edges
- `set_status(node_id, status)` — update single field
- `add_edge(from_id, to_id, edge_type)` — with UNIQUE constraint
- `get_edges(node_id, direction)` → list[Edge]
- `delete_edges(node_id)` → count

Shared DB: NodeStore and EventStore share the same SQLite connection and asyncio.Lock.

### Phase 2 — Testing Checklist

| Test | What it validates |
|------|-------------------|
| **EventBus** | |
| `test_bus_emit_subscribe()` | Handler called when matching event emitted |
| `test_bus_mro_dispatch()` | Subscribe to parent type receives child events |
| `test_bus_subscribe_all()` | subscribe_all handler receives all events |
| `test_bus_unsubscribe()` | Handler removed, no longer called |
| `test_bus_stream()` | stream() yields events via async iterator |
| `test_bus_stream_filtered()` | stream(EventType) only yields matching events |
| **SubscriptionRegistry** | |
| `test_subscription_pattern_matches_exact()` | Pattern with to_agent matches correctly |
| `test_subscription_pattern_matches_event_type()` | event_types filter works |
| `test_subscription_pattern_matches_path_glob()` | path_glob matching works |
| `test_subscription_pattern_none_matches_all()` | All-None pattern matches everything |
| `test_registry_register_and_match()` | Register → get_matching_agents finds agent |
| `test_registry_unregister()` | After unregister, agent no longer matched |
| `test_registry_cache_invalidation()` | Register after match invalidates cache |
| **EventStore** | |
| `test_eventstore_append_returns_id()` | append() returns incrementing IDs |
| `test_eventstore_query_events()` | get_events returns stored events |
| `test_eventstore_query_by_agent()` | get_events_for_agent filters correctly |
| `test_eventstore_trigger_flow()` | append → subscription match → trigger_queue.get() yields (agent_id, event) |
| `test_eventstore_forwards_to_bus()` | append() calls EventBus.emit() |
| **NodeStore** | |
| `test_nodestore_upsert_and_get()` | upsert → get returns same node |
| `test_nodestore_list_with_filters()` | list_nodes filters by type, status, file_path |
| `test_nodestore_delete()` | delete removes node and its edges |
| `test_nodestore_set_status()` | set_status updates only status field |
| `test_nodestore_add_edge()` | add_edge persists, get_edges retrieves |
| `test_nodestore_edge_directions()` | get_edges with direction="outgoing"/"incoming"/"both" |
| `test_nodestore_edge_uniqueness()` | Duplicate edge insert doesn't raise |
| `test_shared_connection()` | NodeStore and EventStore share one SQLite connection |

**Exit criteria:** All 25 tests pass. Can append events, match subscriptions, generate triggers, and CRUD nodes/edges.

---

## Phase 3: Workspace + Tools

### 3.1 AgentWorkspace

**File:** `src/remora/core/workspace.py`

Implement:
- `AgentWorkspace` class wrapping a Cairn workspace
- `read(path)` — with fall-through to stable workspace
- `write(path, content)` — copy-on-write isolated to agent
- `exists(path)` — checks agent then stable
- `list_dir(path)` — merges agent + stable entries
- `delete(path)` — removes from agent workspace
- All ops serialized via `asyncio.Lock` (Cairn/AgentFS requirement)

### 3.2 CairnWorkspaceService

**Add to:** `src/remora/core/workspace.py`

Implement:
- `CairnWorkspaceService` class
- `initialize()` — create stable workspace
- `get_agent_workspace(node_id)` — create or return cached AgentWorkspace
- `provision_bundle(node_id, template_dirs)` — copy template bundle files into workspace
  - Template layering: system tools first, then type-specific tools + config
  - bundle.yaml from later dirs overwrites earlier
- `close()` — cleanup
- `_safe_id(node_id)` — filesystem-safe name from node_id

### 3.3 Grail Tool Loading

**File:** `src/remora/core/grail.py`

Implement:
- `_build_parameters(script)` — JSON Schema from Grail Input() declarations
- `GrailTool` class:
  - `schema` property → ToolSchema
  - `execute(arguments, context)` → ToolResult
  - Only passes externals the script declares
- `discover_tools(workspace, externals)` → list[GrailTool]
  - Reads from `_bundle/tools/` in the workspace
  - Loads each `.pym` via `grail.loads(source, name=...)`

### 3.4 Kernel

**File:** `src/remora/core/kernel.py`

Implement:
- `create_kernel(model_name, base_url, api_key, timeout, tools, observer, grammar_config, client)` → AgentKernel
- `extract_response_text(result)` → str
- Wraps `structured_agents.build_client`, `get_response_parser`, `ConstraintPipeline`

### Phase 3 — Testing Checklist

| Test | What it validates |
|------|-------------------|
| **AgentWorkspace** | |
| `test_workspace_write_read()` | Write then read returns same content |
| `test_workspace_exists()` | exists() returns True after write, False before |
| `test_workspace_list_dir()` | list_dir() returns written files |
| `test_workspace_delete()` | delete() removes file, exists() returns False |
| `test_workspace_stable_fallthrough()` | read() falls through to stable workspace |
| `test_workspace_cow_isolation()` | Write to agent doesn't affect stable |
| **CairnWorkspaceService** | |
| `test_service_initialize()` | initialize() creates stable workspace |
| `test_service_get_workspace()` | get_agent_workspace returns AgentWorkspace |
| `test_service_workspace_caching()` | Same node_id returns same workspace instance |
| `test_service_provision_bundle()` | provision copies bundle.yaml + tools to workspace |
| `test_service_provision_layering()` | System tools + type tools merge; type bundle.yaml wins |
| `test_safe_id()` | _safe_id produces filesystem-safe strings |
| **GrailTool** | |
| `test_discover_tools_from_workspace()` | Discovers .pym files from _bundle/tools/ |
| `test_discover_tools_empty()` | Returns empty list if no _bundle/tools/ |
| `test_grail_tool_schema()` | GrailTool.schema has correct name, description, parameters |
| `test_grail_tool_execute()` | execute() runs script, calls externals, returns ToolResult |
| `test_grail_tool_error_handling()` | Script error returns ToolResult(is_error=True) |
| `test_build_parameters()` | Input declarations → JSON Schema mapping |
| **Kernel** | |
| `test_create_kernel()` | create_kernel returns AgentKernel with tools |
| `test_extract_response_text()` | Extracts text from various result shapes |

**Exit criteria:** All 20 tests pass. Can create workspaces, provision bundles with correct layering, discover and execute Grail tools, create LLM kernels.

---

## Phase 4: Runner + Externals

### 4.1 Externals Builder

**Add to:** `src/remora/core/runner.py` (as `_build_externals` method)

Implement all 16+ externals as closures:
- **Workspace ops** (6): read_file, write_file, list_dir, file_exists, search_files, search_content
- **Graph ops** (4): graph_get_node, graph_query_nodes, graph_get_edges, graph_set_status
- **Event ops** (4): event_emit, event_subscribe, event_unsubscribe, event_get_history
- **Communication** (2): send_message, broadcast
- **Code ops** (2): propose_rewrite, get_node_source
- **Identity** (2 constants): my_node_id, my_correlation_id

### 4.2 AgentRunner

**File:** `src/remora/core/runner.py`

Implement:
- `Trigger` dataclass: node_id, correlation_id, event
- `AgentRunner` class:
  - `__init__(event_store, node_store, workspace_service, config)` — with semaphore, cooldowns, depths
  - `run_forever()` — main loop consuming from EventStore trigger queue
  - `stop()` — set _running=False
  - `trigger(node_id, correlation_id, event)` — cooldown check, depth check, create task
  - `_execute_turn(trigger)` — the 9-step execution pipeline:
    1. Load node from NodeStore
    2. Set status to "running" + emit AgentStartEvent
    3. Get workspace from CairnWorkspaceService
    4. Read _bundle/bundle.yaml for system_prompt, model, max_turns
    5. Build externals via _build_externals
    6. Discover tools from workspace
    7. Build messages (system + user prompt)
    8. Create kernel + run
    9. Emit AgentCompleteEvent or AgentErrorEvent
  - `_build_prompt(node, trigger)` — node identity + trigger info
  - `_build_externals(node_id, workspace, correlation_id)` — from §4.1

### 4.3 System .pym Tools

**Files under** `bundles/system/tools/`:
- `send_message.pym` — Input(to_node_id, content), @external send_message
- `subscribe.pym` — Input(event_types, from_agents, path_glob), @external event_subscribe
- `unsubscribe.pym` — Input(subscription_id), @external event_unsubscribe
- `broadcast.pym` — Input(pattern, content), @external broadcast
- `query_agents.pym` — Input(node_type), @external graph_query_nodes

**File:** `bundles/system/bundle.yaml`:
```yaml
name: system
system_prompt: |
  You are a helpful assistant with access to swarm communication tools.
model: "${REMORA_MODEL:-Qwen/Qwen3-4B}"
max_turns: 4
```

### Phase 4 — Testing Checklist

| Test | What it validates |
|------|-------------------|
| **Externals contract** | |
| `test_externals_workspace_ops()` | read_file, write_file, list_dir, file_exists all work |
| `test_externals_graph_ops()` | graph_get_node, graph_query_nodes, graph_get_edges return correct types |
| `test_externals_event_ops()` | event_emit appends to store, event_subscribe registers pattern |
| `test_externals_communication()` | send_message creates AgentMessageEvent, broadcast hits multiple targets |
| `test_externals_code_ops()` | propose_rewrite creates RewriteProposalEvent + sets status |
| `test_externals_identity()` | my_node_id and my_correlation_id are correct strings |
| **AgentRunner** | |
| `test_runner_cooldown()` | Second trigger within cooldown_ms is skipped |
| `test_runner_depth_limit()` | Trigger at max depth emits AgentErrorEvent |
| `test_runner_trigger_executes()` | trigger() creates async task for execution |
| `test_runner_missing_node()` | Trigger for non-existent node logs error, no crash |
| `test_runner_status_lifecycle()` | Node status: idle → running → idle (or error) |
| `test_runner_build_prompt()` | Prompt includes node identity, source code, trigger info |
| **Integration: Full Turn** | |
| `test_full_turn_with_mock_kernel()` | trigger → load node → build externals → run kernel → emit events |
| `test_turn_emits_start_and_complete()` | AgentStartEvent and AgentCompleteEvent appear in store |
| `test_turn_with_tool_call()` | Kernel calls a tool, external executes, result stored |
| **System tools** | |
| `test_system_tools_parse()` | All .pym files load via grail.loads() without error |
| `test_system_bundle_yaml_valid()` | bundle.yaml is valid YAML with required fields |

**Exit criteria:** All 17 tests pass. Can trigger an agent, execute a full turn with mock kernel, and verify tool calls execute through the externals contract.

---

## Phase 5: Code Plugin

### 5.1 Discovery

**File:** `src/remora/code/discovery.py`

Implement:
- `CSTNode(BaseModel, frozen=True)` — node_id, node_type, name, full_name, file_path, text, start_line, end_line, start_byte, end_byte, parent_id
- `discover(paths, languages, ignore_patterns)` → list[CSTNode]
- `_walk_source_files(paths, ignore_patterns)` → iterator of Path
- `_detect_language(path)` → str | None (by extension)
- `_get_parser(language)` → cached tree-sitter Parser
- `_get_query(language)` → cached tree-sitter Query
- `_parse_file(path, language)` → list[CSTNode]
- Tree-sitter query files under `src/remora/code/queries/` (at minimum `python.scm`)

### 5.2 Projections

**File:** `src/remora/code/projections.py`

Implement:
- `project_nodes(cst_nodes, node_store, workspace_service, config)` → list[CodeNode]
- For each CSTNode:
  - Compute source_hash (SHA-256)
  - Check existing node in store
  - If new: create CodeNode, upsert, provision workspace with template bundle
  - If changed (hash differs): update CodeNode, do NOT re-provision
  - If unchanged: skip
- Bundle mapping from `config.bundle_mapping`

### 5.3 Reconciler

**File:** `src/remora/code/reconciler.py`

Implement:
- `reconcile_on_startup(config, node_store, event_store, workspace_service, project_root)` → list[CodeNode]
  - Run discovery on configured paths
  - Project nodes into graph
  - Register default subscriptions per node (direct messages + file changes)
  - Emit NodeDiscoveredEvent for each node
- `watch_and_reconcile(...)` — optional file watcher (polling or watchfiles)

### 5.4 Code .pym Tools

**Files under** `bundles/code-agent/tools/`:
- `rewrite_self.pym` — Input(new_source), @external propose_rewrite
- `scaffold.pym` — Input(intent, element_type), @external event_emit + my_node_id

**File:** `bundles/code-agent/bundle.yaml`:
```yaml
name: code-agent
system_prompt: |
  You are an autonomous AI agent embodying a code element.
  You have access to your own source code and can propose rewrites.
  ...
model: "${REMORA_MODEL:-Qwen/Qwen3-4B}"
max_turns: 8
```

### Phase 5 — Testing Checklist

| Test | What it validates |
|------|-------------------|
| **Discovery** | |
| `test_discover_python_function(tmp_path)` | Finds function, correct name/type/lines |
| `test_discover_python_class(tmp_path)` | Finds class, correct name/type |
| `test_discover_python_method(tmp_path)` | Finds method inside class, correct parent_id |
| `test_discover_ignores_patterns(tmp_path)` | Files matching ignore_patterns are skipped |
| `test_discover_multiple_files(tmp_path)` | Discovers nodes across multiple files |
| `test_discover_empty_dir(tmp_path)` | Returns empty list for empty directory |
| `test_cstnode_frozen()` | CSTNode is immutable |
| **Projections** | |
| `test_project_new_node()` | New CSTNode → CodeNode in store + workspace provisioned |
| `test_project_unchanged_node()` | Same hash → no upsert, no re-provision |
| `test_project_changed_node()` | Different hash → upsert but no re-provision |
| `test_project_bundle_mapping()` | Correct template bundle selected by node_type |
| **Reconciler** | |
| `test_reconcile_on_startup(tmp_path)` | Full pipeline: source files → nodes in graph |
| `test_reconcile_registers_subscriptions()` | Each node gets direct-message + file-change subscriptions |
| `test_reconcile_emits_discovery_events()` | NodeDiscoveredEvent emitted for each node |
| **Code tools** | |
| `test_code_tools_parse()` | rewrite_self.pym and scaffold.pym load via grail.loads() |
| `test_code_bundle_yaml_valid()` | bundle.yaml is valid YAML with required fields |

**Exit criteria:** All 16 tests pass. Can discover Python source files, project CSTNodes into CodeNodes in the graph, provision workspaces, and register default subscriptions. Full pipeline works: source files → nodes in graph → agents with workspaces.

---

## Phase 6: Web Surface

### 6.1 Web Server

**File:** `src/remora/web/server.py`

Implement:
- `create_app(event_store, node_store, event_bus, runner)` → Starlette
- Routes:
  - `GET /` — serve graph visualization HTML
  - `GET /api/nodes` — list all nodes as JSON
  - `GET /api/nodes/{node_id}` — single node details
  - `GET /api/nodes/{node_id}/edges` — edges for a node
  - `POST /api/chat` — send HumanChatEvent to an agent
  - `GET /api/events` — recent events list
  - `GET /sse` — SSE event stream (all events in real time)
  - `POST /api/approve` — approve a rewrite proposal (apply diff to disk)
  - `POST /api/reject` — reject a rewrite proposal (reset status to idle)

### 6.2 Graph Visualization

**File:** `src/remora/web/views.py`

Implement:
- `GRAPH_HTML` — HTML + JS string for the graph visualization page
- Uses Sigma.js + graphology for WebGL rendering
- SSE client listening to /sse for real-time updates
- Event handlers for NodeDiscoveredEvent, AgentStartEvent, AgentCompleteEvent, AgentErrorEvent
- Click handler showing node details + companion sidebar
- Chat input + send functionality
- Proposal review panel (approve/reject buttons)
- Force-directed layout (ForceAtlas2)
- Node coloring by type and status

### 6.3 Companion .pym Tools

**Files under** `bundles/companion/tools/`:
- `summarize.pym` — reads event history, writes notes/summary.md
- `categorize.pym` — reads node source, writes meta/categories.md
- `find_links.pym` — reads graph edges, writes meta/links.md
- `reflect.pym` — reads history + existing notes, appends notes/reflection.md

**File:** `bundles/companion/bundle.yaml`

### Phase 6 — Testing Checklist

| Test | What it validates |
|------|-------------------|
| **Web server** | |
| `test_api_nodes_returns_list()` | GET /api/nodes returns 200 + JSON list |
| `test_api_node_by_id()` | GET /api/nodes/{id} returns node details |
| `test_api_node_not_found()` | GET /api/nodes/{bad_id} returns 404 |
| `test_api_edges()` | GET /api/nodes/{id}/edges returns edge list |
| `test_api_chat_sends_event()` | POST /api/chat creates HumanChatEvent in store |
| `test_api_events()` | GET /api/events returns recent events |
| `test_sse_stream_connected()` | GET /sse establishes SSE connection |
| `test_sse_receives_events()` | Events appended to store appear in SSE stream |
| `test_api_approve_proposal()` | POST /api/approve applies rewrite to source file |
| `test_api_reject_proposal()` | POST /api/reject resets node status to idle |
| **Graph visualization** | |
| `test_graph_html_renders()` | GRAPH_HTML is non-empty string with expected elements |
| `test_graph_html_has_sse_client()` | HTML contains EventSource('/sse') |
| **Companion tools** | |
| `test_companion_tools_parse()` | All .pym files load via grail.loads() |
| `test_companion_bundle_yaml_valid()` | bundle.yaml is valid YAML |

**Exit criteria:** All 14 tests pass. Web server serves graph visualization, SSE streams events in real time, chat and proposal endpoints work. Can watch the graph live in a browser, chat with agents, review proposals.

---

## Phase 7: CLI + LSP

### 7.1 CLI

**File:** `src/remora/__main__.py`

Implement:
- `main()` click group
- `start` command:
  - Options: --project-root, --config, --port, --no-web
  - Initializes all components (shared SQLite, EventBus, NodeStore, EventStore, SubscriptionRegistry, CairnWorkspaceService)
  - Runs initial discovery via reconciler
  - Creates AgentRunner
  - Starts runner + web server concurrently via asyncio.gather
  - Handles Ctrl+C gracefully (stop runner, close workspaces)
- `discover` command (optional utility):
  - Runs discovery only, prints node summary
  - Useful for debugging

### 7.2 LSP Adapter

**File:** `src/remora/lsp/server.py`

Implement:
- `create_lsp_server(node_store, event_store, runner)` → pygls LanguageServer
- Features:
  - `TEXT_DOCUMENT_CODE_LENS` — show agent status per function/class
  - `TEXT_DOCUMENT_HOVER` — show agent details on hover
  - `TEXT_DOCUMENT_DID_SAVE` — emit ContentChangedEvent
  - `TEXT_DOCUMENT_DID_OPEN` — emit ContentChangedEvent("opened")
- Helper functions:
  - `_node_to_lens(node)` — CodeNode → CodeLens
  - `_node_to_hover(node)` — CodeNode → Hover
  - `_find_node_at_line(nodes, line)` — find node containing a line

### Phase 7 — Testing Checklist

| Test | What it validates |
|------|-------------------|
| **CLI** | |
| `test_cli_help()` | `remora --help` prints help text |
| `test_cli_start_help()` | `remora start --help` prints start options |
| `test_cli_start_smoke(tmp_path)` | Start with test config, verify components initialize, then stop |
| **LSP** | |
| `test_lsp_server_creates()` | create_lsp_server returns LanguageServer |
| `test_node_to_lens()` | CodeNode → CodeLens with correct range |
| `test_node_to_hover()` | CodeNode → Hover with agent details |
| `test_find_node_at_line()` | Finds correct node containing given line |
| `test_lsp_did_save_emits_event()` | did_save handler appends ContentChangedEvent |

**Exit criteria:** All 8 tests pass. Can start remora from terminal, graceful shutdown works. LSP adapter renders code lens and hover, forwards document events.

---

## Phase 8: End-to-End Validation

### 8.1 Full Pipeline Test

**File:** `tests/integration/test_e2e.py`

A comprehensive test that exercises the complete system:

```python
async def test_e2e_human_chat_to_rewrite(tmp_path):
    """Full pipeline: source → discovery → graph → human chat → agent turn → rewrite proposal → approval."""
    # 1. Create a Python source file in tmp_path
    # 2. Initialize all components (config, stores, workspace, runner)
    # 3. Run reconcile_on_startup → verify nodes in graph
    # 4. Verify workspaces provisioned with bundles
    # 5. Send HumanChatEvent to an agent
    # 6. Verify trigger generated from subscription match
    # 7. Execute turn (with mock kernel that calls rewrite_self)
    # 8. Verify RewriteProposalEvent in event store
    # 9. Approve proposal → verify source file updated on disk
    # 10. Verify ContentChangedEvent emitted after approval
```

### 8.2 Performance Baseline

**File:** `tests/integration/test_performance.py`

Measure and assert:
- Discovery: 100+ node project discovered in < 5 seconds
- NodeStore: 100 node upserts in < 1 second
- Subscription matching: 1000 events matched against 100 subscriptions in < 1 second
- Trigger throughput: 10 triggers enqueued and consumed in < 2 seconds

### Phase 8 — Testing Checklist

| Test | What it validates |
|------|-------------------|
| `test_e2e_human_chat_to_rewrite()` | Complete pipeline from source to approved rewrite |
| `test_e2e_agent_message_chain()` | Agent A sends message to Agent B, B is triggered |
| `test_e2e_file_change_triggers()` | File save → ContentChangedEvent → subscribed agents triggered |
| `test_perf_discovery_100_nodes()` | 100+ nodes discovered in < 5s |
| `test_perf_nodestore_100_upserts()` | 100 upserts in < 1s |
| `test_perf_subscription_matching()` | 1000 events × 100 subscriptions in < 1s |

**Exit criteria:** All 6 tests pass. The complete pipeline works end-to-end. Performance is within acceptable bounds.

---

## Summary: Test Count by Phase

| Phase | Tests | Cumulative |
|-------|-------|------------|
| 0: Repo Bootstrap | 4 (smoke) | 4 |
| 1: Core Data Models | 11 | 15 |
| 2: Persistence Layer | 25 | 40 |
| 3: Workspace + Tools | 20 | 60 |
| 4: Runner + Externals | 17 | 77 |
| 5: Code Plugin | 16 | 93 |
| 6: Web Surface | 14 | 107 |
| 7: CLI + LSP | 8 | 115 |
| 8: End-to-End | 6 | 121 |
| **Total** | **121 tests** | |

---

## Cross-Phase Principles

1. **No phase starts until the previous phase's tests all pass.** This is non-negotiable. If Phase 2 tests fail, do not begin Phase 3.

2. **Each module is tested in isolation first.** Use mock/stub dependencies (mock kernel, mock workspace) before integration.

3. **tmp_path for everything.** Every test gets its own temporary directory. No shared state between tests.

4. **Async-first testing.** Use `@pytest.mark.asyncio` and `pytest-asyncio`. All core APIs are async.

5. **Test the contract, not the implementation.** Test what externals return, not how the runner internally wires them.

6. **Regression safety.** When a bug is found in a later phase, add a regression test in the relevant earlier phase's test file.

---

**REMINDER: NEVER use the Task (subagent) tool. Do all work directly.**
