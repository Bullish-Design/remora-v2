# Remora Radical Simplification — Target Architecture

## Table of Contents

1. **One-Paragraph Vision** — What Remora becomes
2. **Current vs Target** — Side-by-side module comparison
3. **The Core Substrate** — 5 modules, ~1200 lines total
4. **The Externals Contract** — The API between Python and .pym tools
5. **The Code Plugin** — Tree-sitter discovery, CodeNode, rewrite proposals
6. **The Tool Bundles** — What ships as .pym scripts
7. **The Web Surface** — Real-time graph viz + companion UI
8. **The LSP Adapter** — Optional thin bridge
9. **What Gets Deleted** — Every module/concept that disappears
10. **Migration Strategy** — How to get from here to there
11. **Open Questions** — Things still to decide

---

## 1. One-Paragraph Vision

Remora is an **event-driven graph agent runner** where every node in a code graph
is a persistent agent with its own Cairn filesystem workspace. The Python library
provides exactly five things: a typed node model, an event store with subscription
routing, a node graph store, a Cairn workspace manager, and a single agent runner
that wires them together. Everything else — what agents *do* when triggered
(rewrite code, message peers, subscribe to events, summarize, categorize, link) —
is defined in `.pym` Grail tool scripts. The system ships with code-aware tools
as a first-class plugin, but the core engine has no knowledge of tree-sitter,
LSP, or source code semantics.

---

## 2. Current vs Target

### Current codebase: 72 Python files, ~19,400 lines

```
core/agents/          10 files, ~1,800 lines  (agent_node, cairn_bridge, cairn_externals,
                                                execution, kernel_factory, state_manager,
                                                swarm_executor, turn_context, workspace, agent_context)
core/events/           6 files, ~750 lines    (event_bus, subscriptions, agent/code/interaction/kernel events)
core/store/            5 files, ~600 lines    (event_store, node_store, schema, queries, connection)
core/code/             3 files, ~600 lines    (discovery, reconciler, projections)
core/tools/            4 files, ~550 lines    (grail, swarm, spawn_child)
runner/                8 files, ~900 lines    (agent_runner, turn_logic, tools, models, protocols, ...)
companion/            15 files, ~1,200 lines  (node_agent, swarms, sidebar, registry, ...)
lsp/                  15 files, ~2,500 lines  (server, db, handlers, background_scanner, ...)
service/               5 files, ~800 lines    (api, handlers, chat_service, datastar)
ui/                    7 files, ~500 lines    (projector, view, components)
cli/                   3 files, ~300 lines
utils/                 5 files, ~300 lines
```

### Target: ~25 Python files, ~4,000 lines

```
core/
  node.py             ~270 lines  CodeNode model (renamed AgentNode)
  events.py           ~500 lines  EventStore + EventBus + SubscriptionRegistry
  graph.py            ~200 lines  NodeStore (SQLite CRUD for CodeNode)
  runner.py           ~400 lines  Single AgentRunner (trigger → workspace → tools → LLM → events)
  workspace.py        ~350 lines  CairnWorkspaceService + AgentWorkspace
  config.py           ~170 lines  (stays as-is)
  manifest.py         ~120 lines  (stays as-is)
  kernel.py           ~90 lines   create_kernel + extract_response_text
  grail.py            ~240 lines  GrailTool, RemoraGrailTool, discover_grail_tools

code/
  discovery.py        ~350 lines  tree-sitter CSTNode discovery (stays)
  reconciler.py       ~250 lines  file watching + reconciliation (stays)
  projections.py      ~200 lines  CSTNode → CodeNode mapping (stays)

web/
  server.py           ~300 lines  HTTP + SSE (replaces service/ + companion UI)
  views.py            ~200 lines  graph visualization + companion panels

lsp/                  ~400 lines  optional thin adapter (drastically reduced from ~2,500)

cli/
  main.py             ~150 lines  (simplified — one startup path)

utils/                ~300 lines  (stays as-is)
```

**Reduction: ~19,400 → ~4,500 lines (77% less code)**

The missing ~15,000 lines are either:
- **Eliminated** (duplicate execution paths, intermediate abstractions, boilerplate tool classes)
- **Moved to .pym** (swarm tools, companion behaviors, rewrite proposals)

---

## 3. The Core Substrate

### 3.1 `core/node.py` — CodeNode

The current `AgentNode` is renamed `CodeNode` and stays rich and typed. Since nodes
are always code nodes parsed from tree-sitter, we keep all the code-specific fields.

**What changes:** LSP rendering methods (`to_code_lens`, `to_hover`, `to_code_actions`,
`to_document_symbol`) move to `lsp/` adapter. The node model is purely data + serialization.

```python
class CodeNode(BaseModel):
    # Identity (from CSTNode via discovery)
    node_id: str
    node_type: str        # "function", "class", "method", "file"
    name: str
    full_name: str
    file_path: str
    start_line: int
    end_line: int
    source_code: str
    source_hash: str

    # Graph context
    parent_id: str | None = None
    caller_ids: list[str] = []
    callee_ids: list[str] = []

    # Runtime state
    status: str = "idle"

    # Agent config
    bundle_name: str | None = None
    system_prompt: str = ""
    subscriptions: list[SubscriptionPattern] = []

    # Serialization
    def to_row(self) -> dict: ...
    def from_row(cls, row) -> CodeNode: ...
```

**Not here:** No `to_system_prompt()` — the system prompt lives in the agent's
`_bundle/bundle.yaml` inside its workspace. The runner reads it from there and
can template in node identity fields. No LSP rendering methods (those move to
`lsp/server.py`). No `ToolSchema` inner class (use `structured_agents.ToolSchema`).

### 3.2 `core/events.py` — EventStore + EventBus + SubscriptionRegistry

Merges the current three separate modules into one. The interfaces are already
clean and stay mostly unchanged:

- **EventStore**: append-only SQLite, `append()`, `get_events_for_*()`, trigger queue
- **EventBus**: in-memory type-based pub/sub, `emit()`, `subscribe()`, `stream()`
- **SubscriptionRegistry**: persistent pattern matching, `register()`, `get_matching_agents()`

**What changes:** The SubscriptionRegistry drops its standalone-mode SQLite connection.
It always shares the EventStore's connection. One fewer database file.

### 3.3 `core/graph.py` — NodeStore

Extracted from the current `EventStore.nodes` pattern. Owns the `nodes` and `edges`
tables. CRUD for CodeNode instances.

```python
class NodeStore:
    async def upsert_node(self, node: CodeNode) -> None: ...
    async def get_node(self, node_id: str) -> CodeNode | None: ...
    async def list_nodes(self, **filters) -> list[CodeNode]: ...
    async def set_status(self, node_id: str, status: str) -> None: ...
    async def add_edge(self, from_id: str, to_id: str, edge_type: str) -> None: ...
    async def get_edges(self, node_id: str) -> list[Edge]: ...
```

### 3.4 `core/runner.py` — AgentRunner

**The biggest simplification.** Currently agent execution spans 7+ files
(agent_runner.py, turn_logic.py, execution.py, turn_context.py, swarm_executor.py,
headless.py, protocols.py). All of this collapses into one runner with one execution path.

```python
class AgentRunner:
    def __init__(self, event_store, node_store, workspace_service, config): ...

    async def run_forever(self) -> None:
        """Main loop: consume trigger queue, run turns."""

    async def trigger(self, node_id: str, correlation_id: str, event=None) -> None:
        """Enqueue a trigger with cooldown + depth checks."""

    async def execute_turn(self, trigger: Trigger) -> None:
        """Single turn: load node → build externals → discover tools → run kernel → emit results."""

    async def close(self) -> None: ...
```

**What disappears:**
- No `RunnerServer` protocol / `_HeadlessServer` adapter — the runner talks directly
  to EventStore and NodeStore
- No `turn_context.py` / `build_turn_context()` — the turn assembly is 40 lines inside
  `execute_turn()`, not a separate module
- No `execution.py` — merged into runner
- No `SwarmExecutor` — there's only `AgentRunner`
- No `runner/tools.py` with `build_lsp_tools()` — rewrite/message are .pym tools
- No `runner/event_emitter.py` — events are emitted via externals from .pym tools

### 3.5 `core/workspace.py` — CairnWorkspaceService + AgentWorkspace

Merges current `cairn_bridge.py` + `workspace.py` + `cairn_externals.py`. Same Cairn
functionality, one module.

```python
class AgentWorkspace:
    """Per-node Cairn workspace: read, write, list, delete, exists."""
    async def read(self, path) -> str: ...
    async def write(self, path, content) -> None: ...
    # ... same interface as today

class CairnWorkspaceService:
    """Manages stable + per-agent workspaces."""
    async def initialize(self) -> None: ...
    async def get_agent_workspace(self, node_id: str) -> AgentWorkspace: ...
    async def provision_bundle(self, node_id: str, template_dir: Path) -> None:
        """Copy a template bundle into the agent's workspace under _bundle/."""
    def build_externals(self, node_id: str, workspace: AgentWorkspace,
                         node_store: NodeStore, event_store: EventStore) -> dict[str, Any]:
        """Build the full externals dict for .pym tool execution."""
        # Merges workspace ops + graph ops + event ops into one dict
```

**Key changes:**
- `build_externals()` returns the *complete* externals dict including graph ops
  and event ops, not just filesystem ops. Single interface between Python and .pym.
- `provision_bundle()` copies a template bundle directory into the workspace's
  `_bundle/` path. Called once when a node is first discovered. After that, the
  agent reads/writes its own `_bundle/bundle.yaml` and `_bundle/tools/*.pym`.
- The runner reads bundle config from `workspace.read("_bundle/bundle.yaml")`,
  not from the project filesystem.

---

## 4. The Externals Contract

This is the API that `.pym` Grail scripts can call via `@external`. It replaces
both the old `CairnExternals.as_externals()` and the `AgentContext.as_externals()`.

### 4.1 Workspace Operations (from Cairn)

```
read_file(path: str) -> str
write_file(path: str, content: str) -> bool
list_dir(path: str) -> list[str]
file_exists(path: str) -> bool
search_files(pattern: str) -> list[str]
search_content(pattern: str, path: str) -> list[dict]
```

### 4.2 Graph Operations (new)

```
graph_get_node(node_id: str) -> dict
graph_query_nodes(node_type: str | None, status: str | None) -> list[dict]
graph_get_edges(node_id: str) -> list[dict]
graph_set_status(node_id: str, status: str) -> bool
```

### 4.3 Event Operations (new)

```
event_emit(event_type: str, payload: dict) -> bool
event_subscribe(event_types: list[str] | None, from_agents: list[str] | None, path_glob: str | None) -> int
event_unsubscribe(subscription_id: int) -> bool
event_get_history(node_id: str, limit: int) -> list[dict]
```

### 4.4 Communication (new — replaces SwarmTool classes)

```
send_message(to_node_id: str, content: str) -> bool
broadcast(pattern: str, content: str) -> str
```

### 4.5 Identity (new)

```
my_node_id: str                    # not a function, a constant
my_correlation_id: str | None      # current trigger's correlation
```

### 4.6 Code Operations (from code plugin — only present for code agents)

```
propose_rewrite(new_source: str) -> str     # returns proposal_id
get_node_source(node_id: str) -> str        # source code of any node
```

**Total: ~16 externals.** Compare to today's `AgentContext.as_externals()` which
flattens callbacks into an untyped dict. The new version is explicit and documented.

---

## 5. The Code Plugin

Three files that move out of `core/` into `code/`:

### 5.1 `code/discovery.py` — CSTNode + tree-sitter scanning

**Stays essentially as-is.** The `CSTNode` model, language-specific queries, and
`discover()` function are well-designed. They just move to a plugin directory.

### 5.2 `code/reconciler.py` — File watching + reconciliation

Watches the project for file changes, re-discovers CSTNodes, upserts CodeNodes
into the graph, and emits `NodeDiscoveredEvent` / `NodeChangedEvent`.

### 5.3 `code/projections.py` — CSTNode → CodeNode mapping

Maps discovery results into the graph store. Handles extension config matching.

**What changes:** The projection no longer lives inside EventStore as a callback.
The reconciler calls discovery, maps results through projections, and writes to
NodeStore directly.

---

## 6. The Tool Bundles

### 6.1 System tools (ship with Remora, available to every agent)

These replace the current 300+ lines of `SwarmTool` subclasses in `core/tools/swarm.py`:

```
bundles/system/
  send_message.pym      # @external send_message(to_node_id, content)
  subscribe.pym         # @external event_subscribe(event_types, ...)
  unsubscribe.pym       # @external event_unsubscribe(subscription_id)
  broadcast.pym         # @external broadcast(pattern, content)
  query_agents.pym      # @external graph_query_nodes(...)
```

Each is ~15-25 lines. The total is ~100 lines of .pym replacing ~300 lines of Python
boilerplate.

### 6.2 Code tools (ship with code plugin)

```
bundles/code/
  rewrite_self.pym      # @external propose_rewrite(new_source)
  scaffold.pym          # @external event_emit("ScaffoldRequest", ...)
  spawn_child.pym       # @external event_emit("SpawnChildRequest", ...)
```

### 6.3 Companion tools (ship with web plugin)

These replace the entire `companion/swarms/` package (~400 lines of Python):

```
bundles/companion/
  summarize.pym         # reads workspace, writes notes/summary.md
  categorize.pym        # reads source, writes meta/categories.md
  find_links.pym        # reads workspace, writes meta/links.md
  reflect.pym           # reads history, writes notes/reflection.md
```

### 6.4 User workspace tools

Users can still add their own `.pym` tools per workspace, discovered from a
configurable directory. This mechanism stays unchanged.

---

## 7. The Web Surface

Replaces both `service/` (5 files, ~800 lines) and `companion/` UI components
(sidebar, composer, etc.).

### 7.1 Real-time graph visualization

A web page (SSE-powered) that shows:
- All nodes as a live graph (d3/cytoscape.js or similar)
- Node status (idle / running / pending_approval / error)
- Edges (parent/child, caller/callee)
- Event stream as it flows through the system

### 7.2 Companion panel

When you click a node in the graph, a sidebar shows:
- Node identity (name, type, file, lines)
- Cairn workspace contents (notes, summaries, chat history)
- Chat interface (send messages to the agent)
- Pending proposals (approve/reject rewrites)

### 7.3 Implementation

Single `web/server.py` using Starlette + SSE (datastar pattern from current service/).
The EventBus `stream()` method feeds SSE events. Simple HTML templates.

**Total: ~500 lines** replacing ~2,000 lines across service/ + companion/ + ui/.

---

## 8. The LSP Adapter

Optional. A thin bridge that translates LSP protocol events into Remora events and
renders CodeNode data as LSP responses.

**Current:** 15 files, ~2,500 lines (server, handlers, db, background_scanner,
notifications, process_lock, etc.)

**Target:** ~400 lines total:
- LSP server that listens for document open/save/change → emits Remora events
- Code lens provider that reads NodeStore → returns CodeLens
- Hover provider that reads NodeStore → returns Hover
- No `lsp/db.py` (operational state managed by web/EventStore, not a separate DB)
- No `lsp/background_scanner.py` (reconciler handles this)

The LSP methods that currently live on `AgentNode` (`to_code_lens`, `to_hover`, etc.)
move here.

---

## 9. What Gets Deleted

### Entire packages removed:

| Package | Files | Lines | Replacement |
|---------|-------|-------|-------------|
| `core/agents/` | 10 | ~1,800 | Split: node.py (model), runner.py (execution), workspace.py (cairn) |
| `core/tools/swarm.py` | 1 | ~316 | 5 `.pym` tool scripts (~100 lines total) |
| `core/tools/spawn_child.py` | 1 | ~80 | 1 `.pym` script |
| `runner/` | 8 | ~900 | Merged into core/runner.py |
| `companion/` | 15 | ~1,200 | .pym tools + web UI |
| `service/` | 5 | ~800 | web/server.py |
| `ui/` | 7 | ~500 | web/views.py |
| `lsp/` (most of it) | 15 | ~2,500 | lsp/ (~400 lines) |

### Specific concepts eliminated:

- **`AgentContext`**: Replaced by the externals dict built in `workspace.py`
- **`SwarmExecutor`**: Merged into single `AgentRunner`
- **`_HeadlessServer`**: Runner doesn't need a server adapter
- **`RunnerServer` protocol**: Runner talks to stores directly
- **`TurnContext` dataclass**: Inlined into `execute_turn()`
- **`build_turn_context()` 80-arg function**: Eliminated
- **`RunnerEventEmitter`**: Events emitted by .pym tools via externals
- **`CairnExternals` class**: Merged into `workspace.build_externals()`
- **`CairnDataProvider`**: Simplified into `workspace.load_files()`
- **`NodeProjection` as EventStore callback**: Reconciler writes to NodeStore directly
- **`RemoraDB` (lsp/db.py)**: Eliminated (all state in EventStore or NodeStore)
- **`NodeAgent` class + `NodeMessage`**: Chat handled by web UI + .pym tools
- **Companion swarm classes** (Summarizer/Linker/Categorizer/Reflection): .pym tools
- **`companion/sidebar/`**: web/views.py
- **`companion/registry.py`**: NodeStore replaces this
- **`lsp/background_scanner.py`**: Reconciler handles this
- **`lsp/process_lock.py`**: Simplified or removed
- **Prompt building (`_build_prompt()`)**: Bundle.yaml system_prompt + event content

---

## 10. Implementation Order (Greenfield)

Built from scratch in a new repo. Each phase produces a testable artifact.

### Phase 1: Foundation (core substrate)
1. `core/config.py` — Config model with pydantic-settings
2. `core/node.py` — CodeNode pydantic model + serialization
3. `core/events.py` — Event types (pydantic), EventBus, EventStore (SQLite), SubscriptionRegistry
4. `core/graph.py` — NodeStore (SQLite CRUD for CodeNode + edges)
5. `core/kernel.py` — thin create_kernel wrapper around structured_agents
6. Tests for all of the above

**Exit criteria:** Can create nodes, append events, match subscriptions, run kernels.

### Phase 2: Workspace + Externals
1. `core/workspace.py` — CairnWorkspaceService, AgentWorkspace, bundle-in-workspace
2. `core/grail.py` — GrailTool, discover_grail_tools from workspace `_bundle/tools/`
3. Externals builder: the complete dict of ~16 externals
4. Tests: workspace CRUD, externals contract, tool discovery

**Exit criteria:** Can create a workspace, populate it with a template bundle,
discover tools, and build the full externals dict.

### Phase 3: Runner
1. `core/runner.py` — AgentRunner with trigger queue, depth/cooldown, execute_turn
2. Wire: trigger → load node → get workspace → discover tools → run kernel → emit events
3. Template bundles: `bundles/system/` with the 5 system .pym tools
4. Integration test: trigger an agent, verify it runs a tool via externals

**Exit criteria:** Can trigger an agent and execute a full turn with .pym tools.

### Phase 4: Code plugin
1. `code/discovery.py` — tree-sitter scanning → CSTNode
2. `code/projections.py` — CSTNode → CodeNode + template bundle copy
3. `code/reconciler.py` — watch project → discover → upsert into graph
4. Template bundles: `bundles/code-agent/` with rewrite_self.pym etc.
5. Integration test: point at a Python project, verify nodes appear in graph

**Exit criteria:** Full pipeline: source files → nodes in graph → agents with workspaces.

### Phase 5: Web surface
1. `web/server.py` — Starlette + SSE event stream
2. `web/views.py` — graph visualization (WebGL-based) + companion panel
3. Chat interface (send messages to agents via web)
4. Proposal review (approve/reject rewrites via web)

**Exit criteria:** Can watch the graph live in a browser, chat with agents, review proposals.

### Phase 6: CLI + LSP (optional)
1. `__main__.py` — CLI entry point (`remora start`, `remora discover`, etc.)
2. `lsp/server.py` — thin LSP adapter (code lens, hover, document events)

**Exit criteria:** Can start remora from terminal and optionally connect Neovim.

---

## 11. Resolved Design Decisions

1. **Event types**: Consolidate into a single `core/events.py` using Pydantic
   models for type checking and LSP integration. One file, one import.

2. **Extension config**: Folded into `remora.yaml`. No separate extensions system.
   `bundle_mapping` in config maps node_type → template bundle directory.

3. **`structured_agents` dependency**: Keep and lean on it. `AgentKernel`,
   `build_client`, `Message`, `ToolSchema`, `ToolResult`, `ToolCall` are all used.
   Cairn and Grail are also core dependencies. Do NOT reimplement.

4. **Graph visualization**: Use the most performant option for large graphs
   (likely Sigma.js / graphology for WebGL rendering, or Cytoscape.js).
   Decision deferred to implementation of web surface.

5. **Tree-sitter scanning**: Stays in Python. It's core functionality that
   provides all parsing. Not pushed to .pym.

6. **Bundle resolution — BUNDLE-IN-WORKSPACE**: Template bundles get copied
   into each node's Cairn workspace under `_bundle/` on first discovery.
   From then on, the agent owns its own config. The runner reads
   `_bundle/bundle.yaml` from the workspace, not the filesystem. Agents
   can self-modify their system_prompt, tools, model, etc. by writing to
   their own `_bundle/` directory.

---

## 12. New Repo — Greenfield Implementation

This will be built **from scratch** in a new repository. No migration from
the existing codebase — clean interfaces, clean dependencies, no legacy baggage.

### Key External Dependencies

- `structured_agents` — AgentKernel, build_client, Message, ToolSchema/Result/Call
- `cairn` — workspace_manager, open_workspace, CairnExternalFunctions
- `grail` — GrailScript, load(), Limits
- `tree_sitter` — Language, Parser, QueryCursor
- `pydantic` / `pydantic_settings` — all models and config
- `starlette` — web server
- `lsprotocol` / `pygls` — optional LSP adapter
- `sqlite3` — all persistence (stdlib)

### Repository Structure

```
remora/
├── pyproject.toml
├── remora.yaml.example
├── src/
│   └── remora/
│       ├── __init__.py
│       ├── __main__.py          # CLI entry
│       ├── core/
│       │   ├── __init__.py
│       │   ├── config.py        # Config (pydantic-settings)
│       │   ├── node.py          # CodeNode model
│       │   ├── events.py        # EventStore + EventBus + SubscriptionRegistry + event types
│       │   ├── graph.py         # NodeStore (SQLite CRUD)
│       │   ├── runner.py        # AgentRunner (single execution path)
│       │   ├── workspace.py     # CairnWorkspaceService + AgentWorkspace + externals builder
│       │   ├── kernel.py        # create_kernel wrapper (thin)
│       │   └── grail.py         # GrailTool, discover_grail_tools
│       ├── code/
│       │   ├── __init__.py
│       │   ├── discovery.py     # tree-sitter CSTNode scanning
│       │   ├── reconciler.py    # file watching → graph updates
│       │   └── projections.py   # CSTNode → CodeNode
│       ├── web/
│       │   ├── __init__.py
│       │   ├── server.py        # Starlette + SSE
│       │   └── views.py         # graph viz + companion panels
│       ├── lsp/                 # optional
│       │   ├── __init__.py
│       │   └── server.py        # thin LSP adapter
│       └── utils/
│           ├── __init__.py
│           ├── fs.py
│           └── paths.py
├── bundles/                     # template bundles (copied into workspaces)
│   ├── system/
│   │   ├── bundle.yaml
│   │   └── tools/
│   │       ├── send_message.pym
│   │       ├── subscribe.pym
│   │       ├── unsubscribe.pym
│   │       ├── broadcast.pym
│   │       └── query_agents.pym
│   ├── code-agent/
│   │   ├── bundle.yaml
│   │   └── tools/
│   │       ├── rewrite_self.pym
│   │       └── scaffold.pym
│   └── companion/
│       ├── bundle.yaml
│       └── tools/
│           ├── summarize.pym
│           ├── categorize.pym
│           ├── find_links.pym
│           └── reflect.pym
└── tests/
    ├── unit/
    │   ├── test_node.py
    │   ├── test_events.py
    │   ├── test_graph.py
    │   ├── test_runner.py
    │   ├── test_workspace.py
    │   └── test_discovery.py
    └── integration/
        ├── test_turn_execution.py
        └── test_reconciler.py
```
