# Remora v2 vs v1 Concept: Comparison Report

> Detailed comparison of remora-v2 (implemented) against the remora v1 EventBased_Concept.md (design document).

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Architecture Core Comparison](#2-architecture-core-comparison)
   - 2.1 EventLog / EventStore
   - 2.2 Event Types
   - 2.3 Subscription System
   - 2.4 Discovery & Reconciliation
   - 2.5 Reactive Loop
   - 2.6 Cascade Safety
   - 2.7 Node Model (AgentNode vs Node)
3. [User Experience: Neovim Integration](#3-user-experience-neovim-integration)
   - 3.1 Code Lens
   - 3.2 Hover
   - 3.3 Code Actions
   - 3.4 Diagnostics & Proposals
   - 3.5 Cursor Tracking
   - 3.6 Sidebar Panel
   - 3.7 Chat / Human Input
4. [Web UI Comparison](#4-web-ui-comparison)
   - 4.1 v1 Web Components
   - 4.2 v2 Web UI
   - 4.3 Gap: Sidebar-in-Browser
5. [Agent Capabilities](#5-agent-capabilities)
   - 5.1 Bundle System
   - 5.2 Grail Tool Scripts
   - 5.3 Externals API
   - 5.4 Agent Communication
6. [Extension / Specialization System](#6-extension--specialization-system)
7. [Feature-by-Feature Gap Matrix](#7-feature-by-feature-gap-matrix)
8. [Conclusion](#8-conclusion)

---

## 1. Executive Summary

**Remora v1** (as described in `EventBased_Concept.md`) is an ambitious design document describing a fully-realized reactive agent swarm system with deep Neovim integration. It specifies a rich Neovim sidebar panel with chat, proposals, tools, and event history — plus a graph visualization in the browser.

**Remora v2** is a working implementation that delivers the core architecture described in v1 — event-driven reactive agents, tree-sitter discovery, subscription-based triggering, Grail tool scripts, and bundle-based agent configuration. However, it is **architecturally simpler** and has **significant gaps** in the user-facing interaction layer.

### Key Findings

| Dimension | v1 Concept | v2 Implementation | Parity? |
|-----------|-----------|-------------------|---------|
| Event system (EventLog, types, subscriptions) | Fully specified | Fully implemented | **YES** |
| Discovery (tree-sitter, CSTNode, languages) | Fully specified | Fully implemented | **YES** |
| Cascade safety (depth, cooldown, concurrency) | Fully specified | Fully implemented | **YES** |
| Agent execution (bundles, Grail, LLM loop) | Fully specified | Fully implemented | **YES** |
| Node model (unified read model) | Rich `AgentNode` (graph, extensions, LSP) | Lean `Node` (identity + status) | **PARTIAL** |
| Neovim CodeLens | Shows agent status per function | Shows node status per function | **YES** |
| Neovim Hover | Rich markdown with graph context + events | Basic markdown with ID, type, status | **PARTIAL** |
| Neovim Code Actions | Chat, rewrite, message, extension tools | None registered | **NO** |
| Neovim Diagnostics | Rewrite proposals as warning diagnostics | Not implemented | **NO** |
| Neovim Sidebar Panel | Full Nui panel: header, tools, chat, input | Not implemented in Neovim | **NO** |
| Human-in-the-loop (HumanInput events) | Full request/response cycle | Not implemented | **NO** |
| Rewrite Proposals | Full proposal → accept/reject workflow | `apply_rewrite` exists but no proposal UI | **PARTIAL** |
| Extension configs (.remora/models/) | Data-driven specialization system | Not implemented | **NO** |
| Web graph viewer | d3/Sigma force-directed | Sigma.js + ForceAtlas2 | **YES** |
| Web sidebar/chat | Not primary (Neovim sidebar is primary) | Has chat API + SSE + node detail sidebar | **YES** |
| Kernel events (subscription-eligible) | Full kernel event treatment | Not yet (events are simpler) | **PARTIAL** |
| Dynamic subscriptions at runtime | subscribe/unsubscribe tools | subscribe/unsubscribe tools | **YES** |

**Bottom line**: v2 has the **core engine** at full parity with the v1 concept — events, subscriptions, discovery, bundles, tools, cascade safety, and agent execution all work. What v2 is missing is the **interaction layer**: the rich Neovim experience (sidebar panel, code actions, diagnostics, human-in-the-loop) and the extension/specialization system that makes agents domain-aware.

The user's goal — "sidebar being in the web browser, not just in neovim" — means v2 should deliver the same rich agent interaction panel that v1 had in Neovim, but rendered in the browser. v2's web UI already has the graph visualization and basic node detail sidebar, but lacks the chat panel, event history, tool listing, and human-input workflows that v1's Nui panel provides.

---

## 2. Architecture Core Comparison

### 2.1 EventLog / EventStore

**v1 Concept**: A single SQLite `events` table with append-only semantics. Every event gets a monotonically increasing `id`, `timestamp`, `event_type`, and JSON `payload`. The EventLog replaces three previous components (EventBus, EventStore, SwarmState). Consumers read via cursor polling or in-process notifications.

**v2 Implementation**: `EventStore` (`src/remora/core/events/store.py`, 127 lines) backed by SQLite with `aiosqlite`. Same append-only semantics with `id`, `timestamp`, `event_type`, `correlation_id`, and JSON `payload`. The `EventBus` remains as a separate in-process pub/sub layer for SSE streaming. Events are stored in an `events` table and fanned out to both `EventBus` (for live consumers) and `TriggerDispatcher` (for subscription matching).

**Assessment**: **EQUIVALENT**. v2 kept the EventBus as a separate concern for streaming, which is actually a cleaner separation than v1's proposal to fold everything into the EventLog. The core semantics — append-only, immutable, queryable — are identical.

### 2.2 Event Types

**v1 Concept**: Four categories of events:
- **Agent lifecycle**: `AgentStartEvent`, `AgentCompleteEvent`, `AgentErrorEvent`
- **Human-in-the-loop**: `HumanInputRequestEvent`, `HumanInputResponseEvent`
- **Reactive swarm**: `AgentMessageEvent`, `FileSavedEvent`, `ContentChangedEvent`, `ManualTriggerEvent`
- **Kernel events**: `KernelStartEvent`, `KernelEndEvent`, `ToolCallEvent`, `ToolResultEvent`, `ModelRequestEvent`, `ModelResponseEvent`, `TurnCompleteEvent`

All kernel events receive "full event treatment" — subscription matching applies.

**v2 Implementation** (`src/remora/core/events/types.py`):
- **Agent lifecycle**: `AgentStartEvent`, `AgentCompleteEvent`, `AgentErrorEvent` ✅
- **Reactive swarm**: `AgentMessageEvent`, `ContentChangedEvent`, `CursorFocusEvent`, `CustomEvent`, `ToolResultEvent` ✅
- **Discovery**: `NodeDiscoveredEvent`, `NodeRemovedEvent`, `NodeChangedEvent` ✅
- **Missing**: `HumanInputRequestEvent`, `HumanInputResponseEvent`, `ManualTriggerEvent`, all kernel events ❌

**Assessment**: **PARTIAL**. Core agent and swarm events are present. Human-in-the-loop events and kernel-level events are missing entirely. The kernel events gap means v2 cannot support meta-agents that observe other agents' tool calls or model responses — a key v1 feature.

### 2.3 Subscription System

**v1 Concept**: `SubscriptionPattern` with five dimensions: `event_types`, `from_agents`, `to_agent`, `path_glob`, `tags`. Conjunctive matching (all non-None must match), disjunctive lists. SQLite-backed registry. Every agent gets two default subscriptions (direct message + source file changes). Agents can dynamically add/remove subscriptions at runtime. Also mentions a `tags` dimension for semantic routing.

**v2 Implementation** (`src/remora/core/events/subscriptions.py`):
- `SubscriptionPattern` with four dimensions: `event_types`, `from_agents`, `to_agent`, `path_glob` ✅
- SQLite-backed `SubscriptionRegistry` with event_type-indexed in-memory cache ✅
- Default subscriptions created per agent (via virtual agent declarative configs) ✅
- Dynamic subscribe/unsubscribe tools in bundle scripts ✅
- **Missing**: `tags` dimension ❌

**Assessment**: **NEARLY COMPLETE**. The only gap is the `tags` dimension, which enables semantic routing (e.g., tagging events as "scaffold", "review", "urgent"). This is important for multi-step chains like the v1 scaffold→interface→impl→test→validate→docs flow.

### 2.4 Discovery & Reconciliation

**v1 Concept**: Tree-sitter scanning with language-specific `.scm` query files. Supported languages: Python (function, method, class, file), Markdown (section, code_block, file), TOML (table, array_table, file). Deterministic `node_id` from `SHA256(file_path:name:start_line:end_line)[:16]`. Thread pool for parallel parsing.

**v2 Implementation** (`src/remora/code/`):
- `discovery.py`: Tree-sitter scanning with language plugins ✅
- `languages/`: Python, Markdown, TOML plugins ✅
- Deterministic node IDs ✅
- `reconciler.py`: File system watcher with mtime-based change detection and proper cleanup ✅

**Assessment**: **FULL PARITY**. Discovery and reconciliation are essentially identical in capability.

### 2.5 Reactive Loop

**v1 Concept**: Event → EventLog → Subscription matching → Trigger → AgentRunner → Bundle resolution → Prompt building → Kernel (LLM loop) → Kernel events → EventLog → (loop). A closed, self-sustaining reactive loop.

**v2 Implementation**:
- `EventStore.append()` → fans out to `EventBus` + `TriggerDispatcher` ✅
- `TriggerDispatcher` matches subscriptions, delivers to actor inboxes ✅
- `Actor` processes inbox events, runs LLM kernel turn ✅
- `ActorPool` manages actor lifecycle with lazy creation/idle eviction ✅
- Completion events emitted → can trigger other agents ✅

**Assessment**: **FULL PARITY**. The reactive loop is fully implemented and functioning.

### 2.6 Cascade Safety

**v1 Concept**: Four safety mechanisms: correlation ID tracking, depth limits (`max_trigger_depth` = 5), cooldown (`trigger_cooldown_ms` = 1000ms), concurrency semaphore (`max_concurrency` = 4).

**v2 Implementation** (in `actor.py` and `config.py`):
- `max_trigger_depth` (5) with depth tracking ✅
- `trigger_cooldown_ms` (1000ms) with per-agent cooldown ✅
- `max_concurrency` (4) with concurrency limiting ✅
- Correlation ID on events ✅
- Exponential backoff on LLM errors ✅ (bonus — not in v1 spec)

**Assessment**: **FULL PARITY** (with bonus retry logic).

### 2.7 Node Model (AgentNode vs Node)

**v1 Concept**: `AgentNode` is a rich Pydantic BaseModel serving three roles simultaneously:
1. **Database schema**: `model_dump()` ↔ `nodes` table, `from_row()` hydration
2. **Agent prompt context**: `to_system_prompt()` generates full LLM system prompt
3. **LSP protocol data**: `to_code_lens()`, `to_hover()`, `to_code_actions()`, `to_document_symbol()`

Key fields beyond identity: `caller_ids`, `callee_ids`, `extension_name`, `custom_system_prompt`, `mounted_workspaces`, `extra_tools`, `extra_subscriptions`, `last_trigger_event`, `last_completed_at`.

**v2 Implementation** (`src/remora/core/node.py`):
- `Node` is a lean Pydantic BaseModel with identity + status only
- Fields: `node_id`, `node_type`, `name`, `full_name`, `file_path`, `start_line`, `end_line`, `start_byte`, `end_byte`, `source_code`, `source_hash`, `parent_id`, `status`, `role`
- `to_row()` / `from_row()` for DB serialization ✅
- **Missing**: `caller_ids`, `callee_ids`, `extension_name`, `custom_system_prompt`, `extra_tools`, `extra_subscriptions`, `to_system_prompt()`, `to_code_actions()`, `to_document_symbol()` ❌
- `to_code_lens()` and `to_hover()` exist in `lsp/server.py` as standalone functions, not methods on Node ✅

**Assessment**: **PARTIAL**. v2's Node is intentionally lean — it stores the essentials and delegates behavior to the Actor and bundle system. The v1 approach of making AgentNode do everything (DB + prompt + LSP) is more integrated but also more coupled. v2's separation is arguably better engineering, but it means the extension/specialization data has no home yet.

---

## 3. User Experience: Neovim Integration

This is the largest gap area between v1 and v2. The v1 concept describes a deeply integrated Neovim experience with a Nui sidebar panel. The user wants this same level of capability, with the sidebar living in the web browser instead.

### 3.1 Code Lens

**v1**: `AgentNode.to_code_lens()` renders status icons (●, ▶, ⏸, ○) + node_id as a clickable CodeLens command (`remora.selectAgent`).

**v2**: `_node_to_lens()` in `lsp/server.py` renders `"Remora: {status}"` as a CodeLens command (`remora.showNode`).

**Assessment**: **FUNCTIONAL PARITY**. Both show agent status above functions/classes. v1 is slightly richer (icons + node_id vs text label).

### 3.2 Hover

**v1**: `AgentNode.to_hover()` shows rich markdown: name, ID, type, status, parent, callers, callees, extension name, and recent events (from EventLog query).

**v2**: `_node_to_hover()` shows basic markdown: full_name, node_id, type, status, file location. No graph context, no recent events.

**Assessment**: **PARTIAL**. v2's hover is functional but lacks the graph context (callers/callees) and recent event history that make v1's hover informative.

### 3.3 Code Actions

**v1**: Rich code action menu:
- "Chat with this agent" → `remora.chat`
- "Ask agent to rewrite itself" → `remora.requestRewrite`
- "Message another agent" → `remora.messageNode`
- Extension-provided tools appear as additional code actions
- Proposal accept/reject actions

All implemented via LSP command registration with custom `$/remora/requestInput` notification flow.

**v2**: **No code actions registered.** The LSP server only handles CodeLens, Hover, didSave, didOpen, didClose, didChange. No commands registered.

**Assessment**: **NOT IMPLEMENTED**. This is a significant interaction gap — users cannot trigger agents, chat, or accept proposals via Neovim.

### 3.4 Diagnostics & Proposals

**v1**: Full proposal workflow:
1. Agent produces rewrite → `RewriteProposalEvent` emitted
2. Proposal converted to LSP diagnostic (warning squiggles on affected lines)
3. Code action to accept → `RewriteAppliedEvent` + file modification
4. Code action to reject → `$/remora/requestInput` for feedback → `RewriteRejectedEvent`
5. Panel shows diffs with `DiffAdd`/`DiffDelete` highlighting

**v2**: `apply_rewrite()` exists in `externals.py` as a direct file write operation. No proposal intermediary, no accept/reject workflow, no LSP diagnostics.

**Assessment**: **NOT IMPLEMENTED**. The proposal workflow — arguably the most important user-facing feature for human-in-the-loop AI — does not exist in v2.

### 3.5 Cursor Tracking

**v1**: `CursorHold` autocmd → debounced 200ms → `$/remora/cursorMoved` notification → server emits `CursorFocusEvent`. Panel auto-refreshes when cursor moves to a different agent.

**v2**: LSP server has a `/api/cursor` POST endpoint for cursor tracking. `CursorFocusEvent` event type exists. No Neovim client-side integration (no Lua plugin), but the server-side support is ready.

**Assessment**: **PARTIAL**. Server-side support exists; client-side integration is missing.

### 3.6 Sidebar Panel

**v1** (`panel.lua`, 1131 lines): A sophisticated Nui-based Neovim sidebar:
- **Header section**: Agent name, type, status with colored icons
- **Tools section**: Collapsible list of available tools (name + description)
- **Chat history**: Full event history with per-event-type rendering:
  - `HumanChatEvent` → blue "You" messages
  - `AgentTextResponse` → green "Agent" messages
  - `HumanInputRequestEvent` → yellow "Question" prompts
  - `RewriteProposalEvent` → diff view with +/- highlighting
  - `AgentMessageEvent` → inter-agent messages
  - `ToolResultEvent` → compact grey tool call results
  - `AgentErrorEvent` → error summaries
- **Input buffer**: Separate split window for typing messages
- **Per-agent event cache**: Events cached per agent_id with LRU eviction (200 events)
- **Debounced refresh**: 300ms debounce on CursorHold/BufEnter
- **Human input flow**: Pending request detection, response submission via `$/remora/submitInput`
- **Keybindings**: `q` close, `t` toggle tools, `<CR>` send message

**v2**: **No Neovim sidebar panel.** The web UI has a sidebar with node detail (name, type, status, file info) and event log, but not a chat-focused panel.

**Assessment**: **NOT IMPLEMENTED** in Neovim. The web UI partially covers this (node detail + event stream) but lacks the per-agent chat interface with message history, input, and human-in-the-loop support.

### 3.7 Chat / Human Input

**v1**: Two-way chat flow:
1. User types in panel input → `$/remora/submitInput` notification → server emits `HumanChatEvent` → agent triggered
2. Agent runs LLM turn → `AgentTextResponse` event → panel renders response
3. Agent can request human input → `HumanInputRequestEvent` → panel shows question → user responds → `HumanInputResponseEvent` → agent continues
4. Rewrite proposals → accept/reject in panel

**v2**: Web `/api/chat` POST endpoint exists for sending messages to agents (emits `AgentMessageEvent`). Conversation history endpoint `/api/nodes/{id}/conversation` retrieves actor message history. But no interactive chat panel in either Neovim or web UI, and no human-input request/response cycle.

**Assessment**: **PARTIALLY IMPLEMENTED**. The plumbing exists (chat API, events) but the user-facing interface for interactive conversation is minimal.

---

## 4. Web UI Comparison

### 4.1 v1 Web Components

v1 used a Datastar-based web UI (`remora.yaml` specifies `remora serve` for HTTP):
- **SSE streaming**: `/subscribe` endpoint for Datastar patches, `/events` for raw JSON SSE
- **UI State Projector** (`ui/projector.py`): Reduces event stream into UI-ready snapshots with agent states, progress tracking, blocked requests, and results
- **Endpoints**: `/input` (human response), `/config`, `/snapshot`, `/swarm/agents`, `/swarm/events`, `/swarm/subscriptions/{id}`, `/replay` (event replay)
- **d3 graph viewer**: Force-directed visualization (mentioned in concept, not primary)

The v1 web UI was secondary to the Neovim experience. The primary interaction surface was the Nui sidebar in Neovim.

### 4.2 v2 Web UI

v2 has a full-featured web UI (`web/static/index.html`, 718 lines):
- **Sigma.js graph visualization**: ForceAtlas2 layout with node type coloring (function=blue, class=purple, method=teal)
- **File clustering**: Nodes grouped by directory with visual clusters
- **SSE streaming**: `/sse` endpoint with replay support + `Last-Event-ID` reconnection
- **Node detail sidebar**: Click a node → see name, type, status, file, line range, parent
- **Chat input**: Basic message box that POSTs to `/api/chat`
- **Event log**: Real-time event stream display
- **REST APIs**: `/api/nodes`, `/api/edges`, `/api/nodes/{id}`, `/api/nodes/{id}/edges`, `/api/nodes/{id}/conversation`, `/api/events`, `/api/health`, `/api/cursor`
- **Rate limiting**: 10 requests/60s on chat endpoint
- **Metrics**: Health endpoint with optional metrics snapshot

### 4.3 Gap: Sidebar-in-Browser

The user's stated goal: **"we want to ensure we have this level of capability, just with the sidebar being in the web browser, not just in neovim."**

What v1's Nui panel provided that v2's web UI does not:

| v1 Nui Panel Feature | v2 Web UI Status |
|----------------------|-----------------|
| Agent header with status icons | ✅ Node detail panel shows this |
| Collapsible tools list | ❌ No tools section |
| Per-agent chat history | ❌ No per-agent message history |
| Chat input with message sending | ✅ Basic chat input exists |
| Human-in-the-loop Q&A | ❌ No HumanInputRequest/Response UI |
| Rewrite proposal diffs | ❌ No proposal/diff display |
| Accept/Reject proposal actions | ❌ No proposal workflow |
| Inter-agent message display | ❌ Events show but not message-formatted |
| Tool call results display | ❌ Events show but not tool-formatted |
| Cursor-driven agent tracking | ❌ No auto-switch based on editor cursor |
| Event dedup / caching | ❌ No client-side event caching |

**The core gap**: v2's web UI is a **monitoring dashboard** (graph + events + node detail). v1's Nui panel was an **interaction surface** (chat + proposals + human input + tool visibility). The web UI needs to evolve from monitoring to interaction.

---

## 5. Agent Capabilities

### 5.1 Bundle System

**v1 Concept**: Bundles at `agents/{bundle_name}/bundle.yaml` with `system_prompt`, `model.id`, `agents_dir` (for Grail tools), `max_turns`. Mapped via `bundle_mapping` in `remora.yaml`.

**v2 Implementation**: Bundles at `bundles/{bundle_name}/bundle.yaml` with the same structure. Five bundles: `system`, `code-agent`, `directory-agent`, `review-agent`, `test-agent`. Virtual agents declared in YAML with bundle references and default subscriptions.

**Assessment**: **FULL PARITY**. The bundle system works identically. v2 has more built-in bundles and a virtual agent declaration system that v1 didn't specify.

### 5.2 Grail Tool Scripts

**v1 Concept**: `.pym` scripts with `@external` injected dependencies. Tools discovered from bundle's `agents_dir`. Five built-in swarm tools: `send_message`, `subscribe`, `unsubscribe`, `broadcast`, `query_agents`.

**v2 Implementation**: Full Grail runtime (`core/grail.py`) with `@external` injection, `Input()` parameter declarations, auto-extraction of tool descriptions. 26 `.pym` tool scripts across 5 bundles. Built-in swarm tools provided as `.pym` scripts in the `system` bundle.

**Assessment**: **FULL PARITY** (with more tools implemented).

### 5.3 Externals API

**v1 Concept**: Not detailed beyond mentioning injected dependencies like `write_file`, `run_command`, `read_file`.

**v2 Implementation** (`core/externals.py`, `TurnContext`): 24 capability functions:
- File operations: `read_file`, `write_file`, `list_dir`, `file_exists`, `search_files`, `search_content`
- KV store: `kv_get`, `kv_set`, `kv_delete`, `kv_list`
- Graph: `graph_get_node`, `graph_query_nodes`, `graph_get_edges`, `graph_get_children`, `graph_set_status`
- Events: `event_emit`, `event_subscribe`, `event_unsubscribe`, `event_get_history`
- Communication: `send_message`, `broadcast`
- Self-modification: `apply_rewrite`
- Identity: `my_node_id`

**Assessment**: **EXCEEDS v1**. The externals API is comprehensive and well-organized.

### 5.4 Agent Communication

**v1 Concept**: Three patterns — direct messaging (`send_message`), broadcasting (`broadcast` with patterns like "children", "siblings", "file:/path"), implicit observation (subscription to other agents' events).

**v2 Implementation**:
- Direct messaging: `send_message` tool ✅
- Broadcasting: `broadcast` with pattern resolution (`children`, `siblings`, etc.) ✅
- Implicit observation: via subscription patterns ✅
- Inter-agent coordination: Event-driven, via subscriptions ✅

**Assessment**: **FULL PARITY**.

---

## 6. Extension / Specialization System

**v1 Concept**: A data-driven extension system where `.remora/models/*.py` files define `AgentExtension` classes:
- `matches(node_type, name)` → pattern matching
- `get_extension_data()` → returns dict with `extension_name`, `custom_system_prompt`, `extra_tools`, `extra_subscriptions`, `mounted_workspaces`
- Applied at discovery time, populating `AgentNode` fields
- Examples: `TestFunction`, `ApiRoute`, `InitFile`, `TemplateScaffold`, `DirectoryManager`, `SwarmMonitor`, `ConfigTable`

This system is the key to making agents domain-aware. A test function agent gets test-running tools and watches source changes. A route handler agent gets endpoint-testing tools and watches model changes.

**v2 Implementation**: **NOT IMPLEMENTED.** v2 uses a fixed bundle-mapping approach instead:
- `remora.yaml` specifies `bundle_mapping` (node_type → bundle name)
- Virtual agents declared in YAML with per-agent subscriptions
- No runtime extension matching based on name/pattern
- No `extension_name`, `custom_system_prompt`, `extra_tools`, `extra_subscriptions` on Node model

The v2 approach achieves similar outcomes through different means:
- Different bundles provide different system prompts and tools
- Virtual agent declarations provide per-agent subscriptions
- The `role` field on Node could serve as a primitive extension marker

**Assessment**: **NOT IMPLEMENTED, but compensated**. v2's bundle system and virtual agents provide some of the same capabilities, but the data-driven extension system is a more flexible and powerful approach. The key loss is the ability to specialize agents based on naming patterns (test functions, API routes, etc.) without modifying bundle config.

---

## 7. Feature-by-Feature Gap Matrix

| # | Feature | v1 Status | v2 Status | Gap Severity |
|---|---------|-----------|-----------|-------------|
| 1 | Event append-only log | ✅ Specified | ✅ Implemented | None |
| 2 | Subscription matching | ✅ Specified | ✅ Implemented | None |
| 3 | Tree-sitter discovery | ✅ Specified | ✅ Implemented | None |
| 4 | Bundle-based agent config | ✅ Specified | ✅ Implemented | None |
| 5 | Grail tool scripts | ✅ Specified | ✅ Implemented | None |
| 6 | Cascade safety (depth/cooldown/concurrency) | ✅ Specified | ✅ Implemented | None |
| 7 | Dynamic subscribe/unsubscribe | ✅ Specified | ✅ Implemented | None |
| 8 | Agent-to-agent messaging | ✅ Specified | ✅ Implemented | None |
| 9 | Broadcasting | ✅ Specified | ✅ Implemented | None |
| 10 | File operations (read/write/list) | ✅ Specified | ✅ Implemented | None |
| 11 | Graph query API | ✅ Specified | ✅ Implemented | None |
| 12 | KV store for agent state | ❌ Not specified | ✅ Implemented | None (v2 bonus) |
| 13 | SSE event streaming | ✅ Specified | ✅ Implemented | None |
| 14 | Web graph visualization | ✅ Specified | ✅ Implemented | None |
| 15 | Cursor tracking | ✅ Specified | ✅ Server-side | Low |
| 16 | Code Lens | ✅ Specified | ✅ Implemented | None |
| 17 | Hover info | ✅ Rich (graph+events) | ✅ Basic (identity) | Low |
| 18 | `tags` on subscription patterns | ✅ Specified | ❌ Missing | Medium |
| 19 | Kernel events (full treatment) | ✅ Specified | ❌ Missing | Medium |
| 20 | Extension configs (.remora/models/) | ✅ Specified | ❌ Missing | Medium |
| 21 | Code Actions (chat/rewrite/message) | ✅ Specified | ❌ Missing | High |
| 22 | Diagnostics (proposal squiggles) | ✅ Specified | ❌ Missing | High |
| 23 | Rewrite proposal workflow | ✅ Specified | ❌ Missing | High |
| 24 | Human-in-the-loop events | ✅ Specified | ❌ Missing | **Critical** |
| 25 | Chat sidebar (Nui panel / web panel) | ✅ Specified (Nui) | ❌ Missing (web) | **Critical** |
| 26 | Per-agent chat history | ✅ Specified | ❌ Missing | **Critical** |
| 27 | Agent panel with tools/events/input | ✅ Specified (Nui) | ❌ Missing (web) | **Critical** |

---

## 8. Conclusion

### What v2 Does Well

The core architecture is **excellent** and at full parity with the v1 concept:
- Event-driven reactive agent system is complete and working
- Tree-sitter discovery with language plugins covers Python, Markdown, TOML
- Bundle system with Grail tool scripts is more mature than v1 specified
- Subscription-based triggering with cascade safety is robust
- Agent communication (messaging, broadcasting, observation) is fully implemented
- Web graph visualization with Sigma.js is polished
- Externals API is comprehensive (24 functions)
- KV store and metrics are v2 bonuses beyond v1 spec

### What v2 is Missing

The interaction layer — the features that make the system usable by a human — is the primary gap:

1. **Critical: Agent interaction panel in the browser** — v1 had a full Nui sidebar; v2 needs this in HTML/JS
2. **Critical: Human-in-the-loop workflow** — agents cannot ask questions or propose changes for approval
3. **Critical: Per-agent chat** — no way to have a conversation with a specific agent
4. **High: Rewrite proposal workflow** — agents can rewrite code but cannot propose changes for review
5. **High: LSP code actions** — no way to trigger agents from the editor
6. **Medium: Extension/specialization system** — agents cannot be domain-specialized based on code patterns
7. **Medium: Kernel events as first-class** — meta-agents cannot observe other agents' internal behavior
8. **Medium: Tags on subscriptions** — semantic routing for multi-step workflows

### Strategic Recommendation

Since the goal is to have the sidebar in the browser rather than Neovim, v2 should focus on:

1. **Building a rich web panel** that mirrors v1's Nui panel capabilities (chat, proposals, tools, events, human input)
2. **Adding human-in-the-loop events** (`HumanInputRequestEvent`, `HumanInputResponseEvent`) to the event system
3. **Implementing the proposal workflow** with accept/reject in the web UI
4. **Adding code actions to LSP** so the editor can trigger agent interactions that appear in the web panel
5. **Connecting cursor tracking** so the web panel auto-focuses on the agent at the editor cursor

This approach leverages v2's strong core engine while filling the interaction gap — and puts the interaction surface in the browser where it's more accessible than a Neovim-only Nui panel.

