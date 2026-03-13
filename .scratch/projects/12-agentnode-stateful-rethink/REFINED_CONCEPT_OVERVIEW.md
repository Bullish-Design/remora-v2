# Refined Concept Overview: Remora

## Table of Contents

1. **What Remora Is** — One-paragraph mental model.
2. **Core Concepts** — The five things a developer needs to understand.
3. **The Node Lifecycle** — From source file to living agent.
4. **The Event Model** — One messaging primitive, one dispatch path.
5. **The Workspace** — A node's persistent brain.
6. **The Turn** — What happens when a node wakes up.
7. **Turn Modes** — How trigger type shapes behavior.
8. **Tools** — What nodes can do.
9. **The Runtime** — How it all fits together.
10. **Appendix A: Simplification Ideas** — Brainstorm for a cleaner architecture.

---

## 1. What Remora Is

Remora turns source code into a graph of autonomous agents. Each function, class, method, file, and directory in your codebase becomes a **node** — a long-lived subject-matter expert that maintains its own understanding of what it is, how it relates to its neighbors, and what's happening around it. Nodes communicate through events, work through tools, and persist their understanding in isolated workspaces. A user can talk to any node, but user interaction is just one of many things a node does. Most of the time, nodes are quietly maintaining their own state — reacting to code changes, updating their knowledge, and coordinating with peers.

---

## 2. Core Concepts

A developer needs to hold five things in their head:

### 2.1 Node

A node is the atomic unit of Remora. It maps 1:1 to a concrete syntax tree (CST) element discovered by tree-sitter: a function, a class, a method, a markdown section, a TOML table, or a directory. Every node has:

- **Identity**: `node_id`, `node_type`, `name`, `file_path`, position in the CST.
- **Relationships**: `parent_id` linking it into a tree (directory → file → class → method).
- **Source**: the literal source code text (or empty for directories).
- **Status**: `idle`, `running`, or `error`.
- **Bundle**: which tool/prompt package it uses (e.g., `code-agent`, `directory-agent`).

A node is a Pydantic model persisted in SQLite. It is a **fact about the codebase** — discovered automatically by the reconciler. Nodes are never created manually by users or agents (spawning is a future concern, out of scope here).

### 2.2 Event

An event is an immutable record of something that happened. Events are the **only** way information moves through Remora. Every event is appended to the EventStore (an append-only SQLite log), broadcast on the EventBus (in-memory pub/sub), and dispatched to matching nodes via their subscriptions.

There is one messaging event type for all inter-entity communication: `AgentMessageEvent(from_agent, to_agent, content)`. A user message is `AgentMessageEvent(from_agent="user", ...)`. A peer message is `AgentMessageEvent(from_agent="src/foo.py::bar", ...)`. No special event class for human chat.

System events (`NodeChangedEvent`, `ContentChangedEvent`, `NodeDiscoveredEvent`, `NodeRemovedEvent`) represent codebase mutations detected by the reconciler.

Lifecycle events (`AgentStartEvent`, `AgentCompleteEvent`, `AgentErrorEvent`) are emitted by the actor during turn execution.

### 2.3 Workspace

Each node has an isolated Cairn workspace — a database-backed virtual filesystem powered by fsdantic. Under the hood, each workspace is a `.db` file (fsdantic/libsql) stored at `.remora/agents/{safe_node_id}.db`, with a shared `stable.db` providing read-through fallback for templates. The workspace exposes a familiar file API (`read`, `write`, `list_dir`, `exists`, `search`, `query`) plus a KV store, all backed by the database — not the real filesystem.

This is the node's **persistent brain**. Everything a node knows between turns lives here:

- `_bundle/bundle.yaml` — configuration (system prompt, model, max_turns).
- `_bundle/tools/*.pym` — Grail tool scripts.
- `state/` — the node's internal state files (knowledge, observations, tasks, health).
- Any other files the node creates for itself.

The stable workspace provides shared bundle templates; the agent workspace overlays it with per-node writes. Workspaces persist across turns, across sessions, across restarts. They are the node's long-term memory.

### 2.4 Tool

A tool is a Grail script (`.pym` file) that gives a node the ability to act. Tools are discovered from the workspace's `_bundle/tools/` directory at the start of each turn. Each tool declares its inputs and which externals it needs. Externals are async functions provided by the runtime (file I/O, graph queries, messaging, etc.).

Tools are the node's hands. The LLM decides which tools to call; the Grail runtime executes them; the results flow back to the LLM for the next step.

### 2.5 Turn

A turn is one cycle of node activation. An event arrives in the node's inbox → the actor wakes up → builds a prompt → calls the LLM with available tools → the LLM reasons and calls tools → the turn completes. Turns are sequential per node (one at a time), concurrent across nodes (bounded by a semaphore).

---

## 3. The Node Lifecycle

### 3.1 Discovery

The `FileReconciler` watches source files via tree-sitter and `watchfiles`:

1. **Parse**: tree-sitter discovers CST elements (functions, classes, methods, sections, tables).
2. **Project**: each `CSTNode` is projected into a `CodeNode` and persisted in the NodeStore.
3. **Materialize directories**: for every file path, directory nodes are created up the tree.
4. **Provision workspace**: new nodes get a workspace with bundle templates copied from `bundles/system/` + `bundles/{bundle_name}/`.
5. **Register subscriptions**: each node gets default subscriptions (direct messages to self, content changes for its file, subtree changes for directories).
6. **Emit events**: `NodeDiscoveredEvent` for new nodes, `NodeChangedEvent` for modified source, `NodeRemovedEvent` for deleted elements.

### 3.2 Steady State

After discovery, nodes exist in the graph and react to events matching their subscriptions. A code node reacts to:
- Direct messages (`AgentMessageEvent` with `to_agent == self`).
- File content changes (`ContentChangedEvent` matching its file path).

A directory node also reacts to:
- Subtree content/node changes (via path glob subscriptions).

### 3.3 Removal

When a source element disappears (function deleted, file removed), the reconciler:
1. Unregisters all subscriptions.
2. Deletes the agent record.
3. Deletes the node from the graph.
4. Emits `NodeRemovedEvent`.

The workspace is not cleaned up automatically — it persists as a historical record.

---

## 4. The Event Model

### 4.1 Unified Messaging

All inter-entity communication uses one event type:

```
AgentMessageEvent(from_agent: str, to_agent: str, content: str)
```

- User → Node: `from_agent="user"`, `to_agent="src/app.py::main"`.
- Node → Node: `from_agent="src/app.py::main"`, `to_agent="src/app.py::helper"`.
- Node → User: `from_agent="src/app.py::main"`, `to_agent="user"`.

There is no `HumanChatEvent`. The `from_agent` field tells the node who's talking to it, and the node decides how to respond based on that (see Turn Modes below).

### 4.2 System Events

These are emitted by the reconciler, not by agents:

| Event | When | Fields |
|-------|------|--------|
| `NodeDiscoveredEvent` | New CST element found | node_id, node_type, file_path, name |
| `NodeChangedEvent` | Source hash changed | node_id, old_hash, new_hash, file_path |
| `NodeRemovedEvent` | CST element deleted | node_id, node_type, file_path, name |
| `ContentChangedEvent` | File content modified | path, change_type, agent_id, old_hash, new_hash |

### 4.3 Lifecycle Events

Emitted by the actor during turn execution:

| Event | When | Fields |
|-------|------|--------|
| `AgentStartEvent` | Turn begins | agent_id, node_name |
| `AgentCompleteEvent` | Turn succeeds | agent_id, result_summary |
| `AgentErrorEvent` | Turn fails | agent_id, error |

### 4.4 Event Flow

```
Something happens (file edit, user message, peer message)
  ↓
EventStore.append(event)           — persisted to SQLite
  ↓
EventBus.emit(event)               — in-memory fan-out to listeners
  ↓
TriggerDispatcher.dispatch(event)  — match against SubscriptionRegistry
  ↓
For each matching agent_id:
  AgentRunner._route_to_actor(agent_id, event)  — into actor inbox
  ↓
AgentActor._run() picks up event   — sequential processing
```

### 4.5 Subscriptions

Each node has subscription patterns that determine which events reach it. Patterns can filter on:

- `event_types`: which event classes to match.
- `from_agents`: which senders to match.
- `to_agent`: direct addressing.
- `path_glob`: file/directory path matching.

Default subscriptions (registered by the reconciler):
- **All nodes**: direct messages to self (`to_agent == node_id`).
- **Code nodes**: `ContentChangedEvent` matching their file path.
- **Directory nodes**: `NodeChangedEvent` and `ContentChangedEvent` matching subtree glob.

Nodes can dynamically add/remove subscriptions via the `event_subscribe`/`event_unsubscribe` externals.

---

## 5. The Workspace

### 5.1 Structure

A node's workspace is a Cairn/fsdantic database (`.db` file) that presents a virtual filesystem interface. Physically, each workspace is a single database file at `.remora/agents/{safe_node_id}.db`. Logically, the virtual filesystem looks like:

```
(virtual paths inside the workspace database)
├── _bundle/
│   ├── bundle.yaml          # Agent config: system_prompt, model, max_turns, mode prompts
│   └── tools/
│       ├── send_message.pym  # System tool (from bundles/system/)
│       ├── rewrite_self.pym  # Bundle-specific tool
│       └── ...
└── state/                    # Node's persistent internal state
    ├── knowledge.md          # Observations, facts, relationships
    ├── tasks.md              # Pending/active/done work items
    ├── health.json           # Confidence, staleness, last refresh
    └── ...                   # Whatever the node decides to create
```

The workspace also provides a KV store (`workspace.kv.get/set/delete/list`) for structured data that doesn't fit the file metaphor.

On disk, the full layout is:

```
.remora/
├── stable.db                 # Shared read-through workspace (bundle templates)
└── agents/
    ├── src_app_py--main-a1b2c3d4e5.db   # Per-node workspace databases
    ├── src_app_py--helper-f6g7h8i9j0.db
    └── ...
```

### 5.2 State as Workspace Files

The node's long-term memory lives in the Cairn workspace files. This is deliberate:

- **Inspectable**: a developer can query the Cairn workspace to see what a node knows.
- **No new infrastructure**: uses the existing Cairn read/write tools.
- **Agent-controlled**: the node decides what to remember and how to organize it.
- **Schema-free**: different node types can use different state structures. A directory node might maintain `state/subtree_summary.md`; a function node might maintain `state/dependencies.md`.

The system prompt instructs nodes to maintain their state files. The tools (`read_file`, `write_file`) already exist. No new externals needed.

### 5.3 Bundle Configuration

`bundle.yaml` defines the node's personality and capabilities:

```yaml
name: code-agent
system_prompt: |
  You are a subject-matter expert for a code element in a source tree.
  Maintain understanding of your own node, its relationships, and its role in the project.

  Use your workspace state/ directory to persist knowledge across turns.
  When triggered by a user message, respond conversationally.
  When triggered by a system event, update your state files silently.
model: "${REMORA_MODEL:-Qwen/Qwen3-4B-Instruct-2507-FP8}"
max_turns: 8
prompts:
  chat: "A user is speaking to you. Respond helpfully using your maintained state."
  reactive: "System event. Update your state/ files. Do not produce narrative output."
```

### 5.4 Workspace Layering

When a workspace read request can't find a file in the agent's database, `AgentWorkspace` falls through to the stable workspace database (shared templates). This means:
- Bundle tools are available immediately after provisioning.
- Nodes can override any file by writing their own version (writes go to the agent db only).
- Updates to bundle templates in `stable.db` propagate to nodes that haven't overridden them.

This is the same copy-on-write overlay pattern that Cairn uses for its own agent execution: agent overlays read through to stable, writes are isolated to the overlay.

---

## 6. The Turn

### 6.1 Turn Execution

When an event arrives in a node's inbox, the actor executes a turn:

1. **Policy check**: cooldown (minimum time between triggers) and depth (maximum recursive triggers per correlation chain). If either limit is hit, the event is dropped.

2. **Status transition**: node status moves from `idle` → `running`. `AgentStartEvent` is emitted.

3. **Context assembly**:
   - Load `bundle.yaml` from workspace.
   - Create `AgentContext` with externals (file I/O, graph queries, messaging, etc.).
   - Discover tools from `_bundle/tools/*.pym`.

4. **Prompt construction**:
   - System prompt from bundle config (with mode-specific instruction injected — see Turn Modes).
   - User prompt: node identity, source code (or structure summary for directories), trigger event details.

5. **Kernel execution**:
   - `create_kernel()` → `kernel.run(messages, tool_schemas, max_turns)`.
   - The LLM reasons, calls tools, receives results, iterates up to `max_turns`.

6. **Completion**: `AgentCompleteEvent` emitted with result summary. Status returns to `idle`.

7. **Error handling**: if anything throws, `AgentErrorEvent` is emitted, status moves to `error`, then best-effort reset to `idle`.

### 6.2 Sequential Processing

Each node processes one event at a time. The inbox is a FIFO queue. While a turn is running, new events queue up. This prevents conflicting concurrent mutations to workspace state.

### 6.3 Concurrency Across Nodes

A shared semaphore limits how many nodes can run turns simultaneously (`max_concurrency` in config). This bounds LLM API load and resource consumption.

---

## 7. Turn Modes

### 7.1 The Problem

Without mode awareness, every trigger produces the same behavior: the node runs a full LLM turn and generates conversational text. This causes directory agents to emit repetitive prose summaries when files change, wastes tokens on system events that only need state updates, and conflates user-facing responses with internal bookkeeping.

### 7.2 The Solution: Prompt-Level Mode Injection

The actor inspects the trigger event and injects a mode-specific instruction into the system prompt. No separate code paths, no lane architecture, no new event types.

**Mode determination** (in `_build_prompt` or `_execute_turn`):

```python
if isinstance(event, AgentMessageEvent) and event.from_agent == "user":
    mode = "chat"
else:
    mode = "reactive"
```

Two modes are sufficient. The intern's three-mode model (chat/reactive/coordination) over-segments — coordination between agents is just reactive behavior with a different trigger. A node reacting to a peer message and a node reacting to a file change should both prioritize state updates over prose. If the node needs to reply to a peer, it has `send_message` — it doesn't need a special "coordination mode" to do so.

**Mode prompt injection**:

The mode-specific prompt is loaded from `bundle.yaml` under `prompts.chat` or `prompts.reactive`, then prepended to the system prompt:

```
[System prompt from bundle.yaml]

[Mode instruction: "A user is speaking to you..." or "System event. Update state..."]
```

### 7.3 Why Prompt-Level Is Enough

- The problem is behavioral, not structural. Agents produce chatty output because nothing tells them not to. A clear instruction fixes this.
- If the model ignores the instruction, the fix is a better model or a better prompt — not more infrastructure.
- This approach is zero-infrastructure: one `if` statement, one string lookup from bundle config.
- It's easy to iterate: change the prompt wording without changing code.
- It preserves the ability to escalate to a structural turn policy gate later if prompt-level control proves insufficient (the `mode` variable is already computed — adding tool filtering or output gating later is additive, not a rewrite).

### 7.4 Expected Behavior by Mode

| Trigger | Mode | Node Behavior |
|---------|------|---------------|
| User message | `chat` | Read state files → reason → respond conversationally → optionally update state |
| File content changed | `reactive` | Read affected state → update knowledge/observations → write state files → done |
| Peer agent message | `reactive` | Read message → update state → optionally reply via `send_message` → done |
| Node discovered/changed/removed | `reactive` | Update topology state → done |

---

## 8. Tools

### 8.1 System Tools (All Nodes)

Available to every node regardless of bundle type:

| Tool | Purpose |
|------|---------|
| `send_message` | Send a direct message to another node (or "user") |
| `broadcast` | Send a message to nodes matching a pattern |
| `query_agents` | Query the node graph |
| `subscribe` | Register a new event subscription |
| `unsubscribe` | Remove an event subscription |

### 8.2 Code Agent Tools

Additional tools for function/class/method/file nodes:

| Tool | Purpose |
|------|---------|
| `rewrite_self` | Propose changes to own source code |
| `scaffold` | Request creation of a new code element |

### 8.3 Directory Agent Tools

Additional tools for directory nodes:

| Tool | Purpose |
|------|---------|
| `list_children` | Get child nodes in the directory |
| `get_parent` | Get parent directory node |
| `broadcast_children` | Send message to all children |
| `summarize_tree` | Render subtree structure |

### 8.4 Externals

All tools access the runtime through externals — async functions injected by the `AgentContext`:

**File I/O**: `read_file`, `write_file`, `list_dir`, `file_exists`, `search_files`, `search_content`
**Graph**: `graph_get_node`, `graph_query_nodes`, `graph_get_edges`, `graph_get_children`, `graph_set_status`
**Events**: `event_emit`, `event_subscribe`, `event_unsubscribe`, `event_get_history`
**Messaging**: `send_message`, `broadcast`
**Code**: `apply_rewrite`, `get_node_source`
**Identity**: `my_node_id`, `my_correlation_id`

---

## 9. The Runtime

### 9.1 Component Map

```
RuntimeServices
├── Config                    — YAML config with env var expansion
├── AsyncDB                   — SQLite with WAL mode
├── NodeStore                 — Code graph persistence
├── AgentStore                — Agent status persistence
├── EventBus                  — In-memory pub/sub
├── SubscriptionRegistry      — SQLite-backed pattern matching
├── TriggerDispatcher         — Routes events to matching agents
├── EventStore                — Append-only event log + bus + dispatcher
├── CairnWorkspaceService     — Per-node isolated fsdantic databases
├── FileReconciler            — Watches files → discovers nodes → emits events
└── AgentRunner               — Actor registry, inbox routing, lifecycle
    └── AgentActor (per node) — Inbox queue, turn execution, cooldown/depth
        └── AgentContext      — Per-turn externals for tool scripts
```

### 9.2 Startup Sequence

1. Load config from `remora.yaml`.
2. Open SQLite database, create tables.
3. Initialize workspace service.
4. Create reconciler, subscribe to `ContentChangedEvent`.
5. Run full scan: discover all nodes, provision workspaces, register subscriptions.
6. Create runner with dispatcher.
7. Start web server (optional).
8. Start reconciler watch loop (optional).
9. System is live — events flow, nodes react.

### 9.3 The Web Layer

Starlette app providing:
- `GET /api/nodes` — list all nodes.
- `GET /api/nodes/{id}` — get one node.
- `GET /api/edges` — list all edges.
- `POST /api/chat` — send a message to a node (emits `AgentMessageEvent(from_agent="user")`).
- `GET /api/events` — recent event log.
- `GET /sse` — server-sent event stream for live updates.

---

## Appendix A: Simplification Ideas

Everything below is brainstorming. These are ideas for making the library's mental model smaller and the codebase cleaner. None are committed — they're a menu of options to evaluate.

### A1. Collapse NodeStore and AgentStore into One Store

**Current state**: `NodeStore` holds `CodeNode` records. `AgentStore` holds `Agent` records. Both are keyed by the same ID. Status is tracked in both and must be kept in sync (see `actor.py:322-338` where both are transitioned). This creates a synchronization problem and conceptual duplication.

**Idea**: Merge them. A node *is* an agent. One table, one model, one status field. The `CodeNode` already has `status` and `bundle_name` fields — the `Agent` model adds nothing that isn't already there.

**Benefit**: Eliminates an entire store class, removes all dual-transition code, removes the `_ensure_agent` calls during reconciliation. One fewer concept for developers to understand.

**Risk**: If we ever need agent-specific fields that don't belong on CodeNode. But YAGNI — we can split later if needed.

### A2. Eliminate the Stable Workspace Fallback

**Current state**: Workspaces have a two-layer read-through: agent db → stable db. The stable workspace database holds shared templates. Bundle provisioning writes templates into agent workspace databases.

**Idea**: Just write everything into the agent db at provision time. No fallback to stable db. Each workspace database is self-contained.

**Benefit**: Simpler mental model — "the workspace db *is* everything the node has." No confusion about where a file comes from. Easier to reason about workspace contents. Removes the dual-query pattern in `AgentWorkspace.read/exists/list_dir`.

**Cost**: Slightly more database storage (duplicated templates). But templates are tiny and database storage is cheap. Updates to templates require re-provisioning, but that already happens on startup.

### A3. Make bundle.yaml Just Another Workspace File

**Current state**: `bundle.yaml` is read by `_read_bundle_config()` in the actor. It's treated as special configuration.

**Idea**: It's already a workspace file. Stop treating it as special. The system prompt, model name, and max_turns are just files the node can read and modify. A node could evolve its own system prompt over time.

**Benefit**: No special config parsing path. Everything is just workspace I/O. A node could `write_file("_bundle/bundle.yaml", ...)` to change its own personality.

**Risk**: Nodes could break themselves by writing bad config. Mitigated by validation at read time (which already exists).

### A4. Unify All Grail Tools into the System Bundle

**Current state**: Tools are split across `bundles/system/`, `bundles/code-agent/`, `bundles/directory-agent/`, `bundles/companion/`. Each bundle type gets different tools.

**Idea**: Put all tools in one place. Every node gets every tool. A code node having `list_children` doesn't hurt — it just won't use it. A directory node having `rewrite_self` is harmless — it has no source code to rewrite.

**Benefit**: Eliminates the bundle mapping system (`config.bundle_mapping`), the multi-directory template provisioning, and the concept of "bundle types" entirely. One set of tools, one provisioning path.

**Cost**: Slightly larger tool schemas sent to the LLM (more tokens). But the tools are small and models handle large tool sets well.

**Alternatively**: Keep the bundle system but make it purely additive — a `bundle_name` just means "also include tools from this directory." The system bundle is always included. This is essentially what it already does, just made explicit.

### A5. Drop the Companion Bundle

**Current state**: `bundles/companion/` has `reflect.pym`, `categorize.pym`, `find_links.pym`, `summarize.pym`. These are reflection/maintenance tools.

**Idea**: These should be system tools available to all nodes, not a separate bundle type. The `reflect.pym` tool (writing to `notes/reflection.md`) is a primitive version of what the state/ directory approach does better. The others are useful for any node type.

**Benefit**: Removes a bundle type. Useful capabilities become universal.

### A6. Replace Custom Event Types with a Single Envelope

**Current state**: 12 event classes, each a Pydantic model with specific fields.

**Idea**: One `Event` model with `event_type: str` and `payload: dict`. No subclasses.

```python
class Event(BaseModel):
    event_type: str
    timestamp: float
    correlation_id: str | None = None
    payload: dict[str, Any] = {}
```

**Benefit**: No class hierarchy. No `__all__` exports list. Adding a new event type means choosing a string name and a payload shape — no code change. Subscription matching already works on `event_type` strings. Dispatch already works on `event_type` strings.

**Cost**: Loss of type safety. `event.from_agent` becomes `event.payload["from_agent"]`. IDE autocomplete gets worse. Validation moves from Pydantic to runtime.

**Middle ground**: Keep the typed event classes but make them thin wrappers that serialize to the generic envelope for storage and dispatch. Best of both worlds — type safety in Python, schema-free in the event log.

### A7. Simplify the Subscription System

**Current state**: Subscriptions are a general pattern-matching system with `event_types`, `from_agents`, `to_agent`, and `path_glob`. Nodes register multiple patterns.

**Idea**: Most subscriptions follow two patterns: "messages to me" and "changes in my scope." Could simplify to two built-in subscription rules per node, derived from the node's position in the graph, with no explicit registration needed.

- **Direct**: any event where `to_agent == my_node_id` → always routed to me.
- **Scope**: any `ContentChangedEvent` or `NodeChangedEvent` where path is in my subtree → routed to me.

The reconciler already registers exactly these patterns. If we make them implicit (derived from graph position), we can eliminate the subscription registry entirely for the common case, and keep explicit subscriptions only for advanced use (agents subscribing to custom event types).

**Benefit**: Removes 90% of subscription management code. Removes the `_register_subscriptions` calls in the reconciler. Simpler mental model — "nodes hear about things in their scope."

**Cost**: Less flexible. Nodes can't subscribe to events outside their scope without explicit registration. But this might be fine — scope-based routing covers the primary use case.

### A8. Rename Everything to Match the Mental Model

Small naming improvements that reduce cognitive load:

| Current | Proposed | Why |
|---------|----------|-----|
| `CodeNode` | `Node` | It's not always code (directories aren't). Just "Node." |
| `CSTNode` | `DiscoveredElement` | What it actually is — a thing discovered by tree-sitter. |
| `AgentActor` | `NodeActor` or just `Actor` | "Agent" and "Node" are already synonymous in Remora. |
| `AgentContext` | `TurnContext` | It's per-turn, not per-agent. |
| `AgentRunner` | `ActorPool` | What it actually does — manages a pool of actors. |
| `create_kernel` | `create_llm` or `create_model` | "Kernel" is jargon from structured_agents. Remora doesn't need to leak it. |
| `externals` | `capabilities` or `api` | "Externals" is Grail jargon. In Remora's context, these are the node's capabilities. |
| `bundle_name` | `role` | A bundle determines a node's role (code-agent, directory-agent). "Role" is clearer. |
| `swarm_root` | `workspace_root` | It's where workspaces live. "Swarm" is vague. |

### A9. Make the Event Log the Only Source of Truth

**Current state**: NodeStore and EventStore are parallel. Nodes are stored as mutable rows. Events are append-only. When something changes, both are updated.

**Idea**: True event sourcing. The node graph is a *projection* of the event log. `NodeDiscoveredEvent` creates a node. `NodeChangedEvent` updates it. `NodeRemovedEvent` deletes it. The NodeStore becomes a read-optimized cache that can be rebuilt from events.

**Benefit**: One source of truth (the event log). Full audit trail. Time-travel debugging (replay events to any point). Simpler writes (just append an event; the projection handles the rest).

**Cost**: More complex reads (need to maintain projection). Slower cold start (rebuild from log). But SQLite is fast enough that this is unlikely to matter at Remora's scale.

### A10. Kill the `_preview_text` Logging Pattern

**Current state**: `actor.py` has `_preview_text()` that replaces newlines with `\n` for logging. Recent work explicitly ensured responses aren't truncated in logs.

**Idea**: Use structured logging (JSON). Log the full payload. Let log viewers handle formatting. Remove all manual log formatting.

**Benefit**: Cleaner actor code. Better log searchability. No more "is the log truncated?" questions.

### A11. Configuration as a Workspace File

**Current state**: `Config` is loaded from `remora.yaml` at startup and threaded through constructors. It's immutable after load.

**Idea**: Make config a workspace file in a "system" workspace. The runtime reads it from the workspace like any other file. Hot-reload becomes just "watch the config workspace."

**Benefit**: Unifies the config path with the workspace path. One file I/O mechanism for everything.

**Cost**: Chicken-and-egg problem — you need config to initialize the workspace service. Solvable with a bootstrap config that just specifies the workspace root.

### A12. Drop the LSP Server (For Now)

**Current state**: `lsp/server.py` provides hover and CodeLens for discovered nodes. It's 106 LOC with minimal test coverage.

**Idea**: The web UI + SSE stream provides equivalent observability. The LSP server adds maintenance burden for marginal value. Remove it and re-add when the core is stable and there's a clear IDE integration story.

**Benefit**: Less code to maintain. Fewer dependencies. Cleaner focus on the core runtime.

### A13. Implicit Node-to-User Responses via Event Convention

**Current state**: When a user sends a message and a node responds, the response text is buried in `AgentCompleteEvent.result_summary`. The web UI has to watch for completion events to show responses.

**Idea**: When a node receives `AgentMessageEvent(from_agent="user")`, the convention is that it should call `send_message("user", response)` to reply. This emits an `AgentMessageEvent(from_agent=node_id, to_agent="user")`. The web UI subscribes to events where `to_agent == "user"` and displays them.

**Benefit**: User replies become explicit, intentional, and visible in the event log as first-class messages. The `AgentTextResponse` event type becomes unnecessary — it's just an `AgentMessageEvent` to "user". The UI has a clean subscription pattern for user-facing messages.

### A14. Separate "What a Node Knows" from "What a Node Is"

**Current state**: `CodeNode` mixes identity fields (node_id, name, file_path) with content fields (source_code, source_hash) with runtime fields (status, bundle_name). All in one flat model.

**Idea**: Conceptually (not necessarily in code), distinguish:
- **Identity**: node_id, node_type, name, file_path, parent_id. Set at discovery, rarely changes.
- **Content**: source_code, source_hash, byte positions. Updated when source changes.
- **Runtime**: status, bundle_name. Managed by the actor/runner.

This could remain one model in code but with clear field grouping. Or it could split into a normalized schema where identity and content are separate tables, reducing write amplification when only status changes.

### A15. Consider Whether Directories Need to Be Nodes

**Current state**: Directories are synthesized as nodes during reconciliation. They get workspaces, actors, subscriptions, and LLM turns — the full treatment. This is expensive (every file change triggers directory node turns up the tree).

**Idea**: Maybe directories should be lightweight structural metadata in the graph, not full agent nodes. They provide topology (parent/child relationships) but don't run LLM turns on every subtree change. If a user wants to talk to a directory, the runtime could synthesize a turn on demand rather than maintaining a persistent actor.

**Benefit**: Dramatically reduces LLM calls on file changes. Simpler graph (fewer nodes). Directories still exist as structural entities for navigation.

**Cost**: Loses autonomous directory-level reasoning. But the current directory agent behavior (chatty summaries on file changes) is exactly what CONCEPT_REFINED identified as the problem. Maybe the fix isn't "make directory agents quieter" — it's "directories aren't agents."

**Middle ground**: Directories are nodes in the graph (for topology) but don't have actors by default. They only spin up an actor when directly addressed by a user or peer. This is "lazy activation" — the actor exists only while processing a message, then evicts immediately.

### A16. Use the Workspace KV Store for Structured Node State

**Current state**: Remora only uses the fsdantic file API (`workspace.files.read/write/query`). But fsdantic workspaces also expose a KV store (`workspace.kv.get/set/delete/list`) with typed repositories — Cairn itself uses this for agent lifecycle metadata (`SubmissionRecord`). Remora ignores this entirely.

**Idea**: Use the KV store for structured node state that benefits from typed access and efficient queries. The file API stays for unstructured content (markdown notes, source code). The KV store handles structured data:

```python
# Instead of: await workspace.write("state/health.json", json.dumps(health))
# Use:        await workspace.kv.repository(prefix="state", model_type=NodeHealth).save("health", health)
```

**Benefit**: Type-safe state persistence with Pydantic models. No manual JSON serialization. Query capabilities (list all keys with a prefix). Atomic updates. The KV store is already part of the fsdantic API — we're just not using it.

**Cost**: Adds a new external surface (nodes need `kv_get`, `kv_set` externals or a Grail tool). But this is a small addition.

**Opportunity**: The KV store could replace the SQLite-based NodeStore entirely for agent runtime state, leaving SQLite for the event log and graph topology only. Each node's workspace db already exists — why maintain a separate central database for per-node state?

### A17. Use fsdantic Overlay Semantics Instead of Rolling Our Own

**Current state**: `AgentWorkspace` manually implements read-through fallback: try agent db, catch `FileNotFoundError`, try stable db. `list_dir` merges entries from both. `list_all_paths` queries both and deduplicates. This is ~110 lines of hand-rolled overlay logic.

**Idea**: fsdantic already has overlay operations (`workspace.overlay.merge/list_changes/reset`). Cairn uses these for its accept/reject flow. Remora could use the same overlay primitives instead of reimplementing them in `AgentWorkspace`.

**Benefit**: Removes `AgentWorkspace` entirely or reduces it to a thin wrapper. Uses battle-tested overlay logic from fsdantic. Potentially enables "accept" semantics — a node's state changes could be reviewed and merged into stable, mirroring Cairn's human-in-the-loop pattern.

**Cost**: Need to verify fsdantic's overlay API covers all Remora's use cases (merged directory listings, path queries, etc.). May require fsdantic version bump.

