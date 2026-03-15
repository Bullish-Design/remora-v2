# Remora v1 → v2 Capability Gap Analysis

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Quantitative Overview](#2-quantitative-overview)
3. [Core Architecture Comparison](#3-core-architecture-comparison)
   - 3.1 Node Model
   - 3.2 Agent Execution
   - 3.3 Event System
   - 3.4 Workspace & Tools
   - 3.5 Discovery & Reconciliation
   - 3.6 Configuration & DI
4. [Surface Layer Comparison](#4-surface-layer-comparison)
   - 4.1 CLI
   - 4.2 Web UI & API
   - 4.3 LSP Server
   - 4.4 Neovim Integration
5. [Capabilities Preserved in v2](#5-capabilities-preserved-in-v2)
6. [Capabilities Missing from v2](#6-capabilities-missing-from-v2)
   - 6.1 Companion System
   - 6.2 Bootstrap & Coordinator
   - 6.3 Vector Search / Embeddy
   - 6.4 Server Deployment
   - 6.5 Browser Demo
   - 6.6 E2E Test Harness & Training Data
   - 6.7 Agent Type Library
   - 6.8 Advanced LSP Features
   - 6.9 RemoraService Layer
   - 6.10 Extension System
7. [Simplifications Achieved in v2](#7-simplifications-achieved-in-v2)
8. [Verdict: Did v2 Achieve Its Goal?](#8-verdict)
9. [Recommendations](#9-recommendations)

---

## 1. Executive Summary

Remora v2 achieves its stated goal of providing the same **core** functionality in a dramatically simpler mental model. The codebase shrinks from ~19,400 lines across ~120 files to ~5,500 lines across ~33 files — a 72% reduction — while preserving the fundamental reactive loop: tree-sitter discovery → node graph → actor execution → event-driven triggers → LLM turns with Grail tools in Cairn workspaces. All three interaction surfaces (CLI, Web, LSP) are present and functional.

However, v2 deliberately drops several v1 subsystems that were either experimental, deployment-specific, or represented design directions that were never fully stabilized:

- **Companion system** (persistent chat agents, MicroSwarms, sidebar composition) — the most significant omission
- **Bootstrap/coordinator** (automatic agent-to-node assignment) — replaced by declarative virtual agents and FileReconciler
- **Vector search** (embeddy integration) — no replacement
- **Server deployment** (Docker, adapter_manager) — no replacement
- **Browser demo**, **e2e harness**, **training data** — peripheral v1 artifacts, not core functionality
- **Agent type library** (15+ specialized agent directories) — replaced by configurable bundles
- **Advanced LSP features** (debounced reparse, background scanner, custom notifications, proposal diagnostics) — stripped to essentials

The key question is whether the dropped features represent *capability gaps* or *intentional pruning*. The answer is mostly the latter, with the companion system being the one genuinely missing capability that users of v1 would notice.

---

## 2. Quantitative Overview

| Metric | v1 | v2 | Delta |
|--------|-----|-----|-------|
| Python source files | ~120 | ~33 | -72% |
| Lines of code (src/) | ~19,400 | ~5,500 | -72% |
| Core modules | ~40 files | ~15 files | -63% |
| Event types | ~15 | ~22 | +47% |
| LSP files | 22 | 1 | -95% |
| Web server files | ~8 | 2 (server + static) | -75% |
| CLI entry points | 1 | 1 | — |
| Bundle directories | 0 (agents/ at root) | 5 | — |
| Neovim plugin files | ~6 | 2 | -67% |
| External dependencies | sqlite3 (stdlib) | aiosqlite | simpler async |
| Test files | ~50+ | ~30 | -40% |

The reduction is real and consistent across every layer. V2 isn't just v1 with files deleted — it's a genuine rewrite with different abstractions.

---

## 3. Core Architecture Comparison

### 3.1 Node Model

**V1 — `AgentNode` (core/agents/agent_node.py, ~200 lines):**
A monolithic Pydantic model that serves simultaneously as a database row, an LLM prompt source, and an LSP protocol response generator. Contains `to_system_prompt()`, `to_code_lens()`, `to_hover()`, `to_code_actions()`, `to_document_symbol()`. Carries graph context fields (caller_ids, callee_ids) and extension specialization fields directly on the model.

**V2 — `Node` (core/node.py, ~49 lines):**
A pure data model with no behavior beyond field storage. Uses `NodeType`/`NodeStatus` enums. No LSP methods, no graph context fields, no extension fields. Adds a `role` field (used for virtual agents). LSP presentation is handled entirely in the LSP server module. Graph relationships live in a separate edges table via `NodeStore`.

**Assessment:** V2's separation of concerns is a clear improvement. The v1 AgentNode violated SRP by mixing data, presentation, and domain logic. V2 splits these cleanly: Node holds data, NodeStore manages graph, LSP server handles presentation.

### 3.2 Agent Execution

**V1 — Dual execution paths:**
- `SwarmExecutor` (core/agents/swarm_executor.py): CLI/headless reactive execution with connection pooling.
- `AgentRunner` (runner/agent_runner.py, ~604 lines): Unified async coordinator with cascade prevention (depth tracking, cooldown, concurrency semaphore), command queue polling, proposal management, headless mode adapter.
- Both delegate to `execute_agent_turn()` (core/agents/execution.py): The shared pipeline handling bundle resolution, tool discovery, kernel wiring, and audit-trail recording.
- `TurnContext` (core/agents/turn_context.py): Assembly of bundle path, model name, prompt, tools, workspace.

**V2 — Single execution path:**
- `Actor` (core/actor.py, ~650 lines): Per-agent entity with inbox queue, sequential message processing, local cooldown/depth policies, conversation history, bundle config reading, and prompt building. The Actor IS the execution path — no separate runner or executor delegates to a shared pipeline.
- `ActorPool` (core/runner.py, ~137 lines): Lazy actor creation, event routing via dispatcher callback, idle eviction, metrics gauges. A registry, not a coordinator.
- `TurnContext` (core/externals.py, ~325 lines): Rich API surface for tools — file ops, KV store, graph queries, event management, messaging, broadcast, human input, rewrite proposals, content search.

**Assessment:** V2's actor model is conceptually simpler. In v1, understanding "how does an agent run?" requires tracing through SwarmExecutor → execute_agent_turn → TurnContext → kernel_factory, or AgentRunner → execute_agent_turn → TurnContext → kernel_factory. In v2, it's Actor.run_turn(). The Actor encapsulates its own lifecycle. The cost is that Actor.py at 650 lines is the densest single file in v2, but it's self-contained rather than scattered.

### 3.3 Event System

**V1:**
- `EventBus` (core/events/event_bus.py): Type-based subscriptions with MRO dispatch cache, `stream()`, `wait_for()`, `subscribe_all()`.
- `SubscriptionRegistry` (core/events/subscriptions.py): SQLite persistence with in-memory cache indexed by event_type, SubscriptionPattern matching.
- `EventStore` (core/store/event_store.py, ~658 lines): Heavyweight — separate read/write connections, trigger queue, NodeProjection support, batch_append, replay, correlation tracking, graph management, WAL checkpointing. This was one of the most complex files in v1.

**V2:**
- `EventBus` (core/events/bus.py, ~90 lines): Same concept, cleaner implementation. Inheritance-aware subscriptions, concurrent handler dispatch via `create_task`, `stream()`.
- `SubscriptionRegistry` (core/events/subscriptions.py, ~145 lines): aiosqlite-backed, event_type-indexed cache. Same pattern, less code.
- `EventStore` (core/events/store.py, ~180 lines): Dramatically simpler. Single aiosqlite connection, append with bus+dispatcher fan-out, human-input response futures, basic queries.
- `TriggerDispatcher` (core/events/dispatcher.py, ~57 lines): Extracted from EventStore — routes events to agent inboxes via subscription matching and router callback.

**Assessment:** The v2 event system is functionally equivalent for the core use case but drops NodeProjection, batch_append, replay, and WAL checkpointing. The extraction of TriggerDispatcher as a separate concern is a notable design improvement. The v1 EventStore was trying to be a database, an event bus, and a trigger dispatcher all at once.

### 3.4 Workspace & Tools

**V1:**
- `AgentWorkspace` (core/agents/workspace.py): Wraps Cairn with read/write/exists/list_dir/delete. `CairnDataProvider` for loading files for Grail execution. Has `stable_workspace` fallback and `ensure_file_synced`.
- Grail tool loading scattered across execution pipeline.

**V2:**
- `AgentWorkspace` (core/workspace.py, ~99 lines): Similar Cairn wrapper, cleaner API.
- `CairnWorkspaceService` (core/workspace.py, ~224 lines): Centralized workspace lifecycle — creation, bundle provisioning with template fingerprinting, KV store access.
- `GrailTool` + `discover_tools` (core/grail.py, ~202 lines): LRU-cached script loading, workspace-based tool discovery with clear separation.

**Assessment:** Functionally equivalent. V2 organizes workspace concerns more cleanly with the CairnWorkspaceService as a single point of workspace lifecycle management. Template fingerprinting for bundle provisioning is a v2 addition that prevents unnecessary re-provisioning.

### 3.5 Discovery & Reconciliation

**V1:**
- `seed_module_nodes_from_filesystem` / `seed_coordinator_node` (bootstrap/seed_graph.py): One-shot seeding.
- `BootstrapRunner` (bootstrap/runner.py): Ongoing agent-to-node assignment.
- `NodeProjection` (inside EventStore): Event-driven node materialization from ContentChanged events.
- No file watcher integration in core — the runner/companion polled or relied on LSP events.

**V2:**
- `FileReconciler` (code/reconciler.py, ~619 lines): Incremental reconciliation with watchfiles integration. Handles directory node materialization, virtual agent sync, bundle provisioning, subscription registration. This is the most complex single module in v2 but it replaces three separate v1 subsystems.
- `discover_nodes` (code/discovery.py, ~231 lines): Tree-sitter query-based node extraction with parent resolution and language plugin system.

**Assessment:** V2's FileReconciler is a genuine improvement. It unifies seeding, projection, and bootstrap into a single reconciliation loop driven by filesystem events. The watchfiles integration means v2 has real-time file watching where v1 relied on LSP events or polling.

### 3.6 Configuration & DI

**V1:**
- Configuration scattered across multiple initialization points. No unified DI container.
- `RemoraService` (service/api.py) acted as a partial service locator but was framework-specific.
- Extension system via `.remora/models` directory.

**V2:**
- `Config` (core/config.py, ~226 lines): pydantic-settings based, env var expansion, virtual agents, bundle overlay rules with pattern matching.
- `RuntimeServices` (core/services.py, ~87 lines): Clean DI container wiring all services (db, node_store, event_store, event_bus, subscription_registry, dispatcher, actor_pool, workspace_service, metrics).

**Assessment:** V2's configuration and DI are significantly cleaner. `RuntimeServices` makes the dependency graph explicit and testable. The v1 extension system is replaced by bundle_rules with pattern matching, which is more declarative and doesn't require a separate directory convention.

---

## 4. Surface Layer Comparison

### 4.1 CLI

**V1:** Typer-based CLI with commands for starting the system, running discovery, and launching LSP. Initialization logic spread across multiple modules.

**V2:** Typer-based CLI (`__main__.py`, ~348 lines) with `start`, `discover`, and `lsp` commands. The `start` command orchestrates RuntimeServices, watchfiles-based reconciler, uvicorn web server, and structured logging in a single coherent startup sequence. Cleaner integration of all subsystems at the CLI level.

**Assessment:** Functionally equivalent. V2's startup is more cohesive.

### 4.2 Web UI & API

**V1:**
- `RemoraService` (service/api.py): Framework-agnostic service API with SSE streams, companion integration, UI projector, event replay.
- Datastar-based UI projector for reactive HTML rendering.
- Separate web server wiring.

**V2:**
- `create_web_app` (web/server.py, ~494 lines): Starlette app with comprehensive REST API: node/edge/chat/respond/proposals/diff/accept/reject/events/health/conversation/cursor endpoints. SSE streaming with replay, rate limiting.
- Static HTML UI (web/static/index.html): Self-contained SPA with agent interaction panel.

**Assessment:** V2's web API is more complete and self-contained. It has explicit endpoints for every interaction (human input, rewrite proposals, cursor focus) that v1 handled through the companion system or custom notification channels. The loss of the Datastar UI projector is a trade-off — v2's static HTML is simpler but less reactive. However, the SSE stream provides real-time updates, so the practical difference is minimal.

### 4.3 LSP Server

**V1 — `RemoraLanguageServer` (lsp/server.py, ~330 lines + 21 supporting files):**
- Full pygls server with extensive handler decomposition across separate files.
- Background scanner for periodic graph refresh.
- Debounced reparse on document changes.
- Debounced cursor tracking.
- Custom LSP notifications (`$/remora/event`, `$/remora/agentsUpdated`) for real-time agent status.
- Proposal diagnostics displayed inline.
- Process lock for single-instance enforcement.
- `RemoraDB` and `LazyGraph` for lazy database/graph initialization.
- Runtime operations (create subscriptions, trigger agents) via custom commands.

**V2 — `create_lsp_server` (lsp/server.py, ~314 lines, single file):**
- Minimal pygls server with code_lens, hover, code_action, did_save/open/close/change.
- Two commands: `remora.chat` (opens web panel) and `remora.trigger` (sends manual trigger event).
- Shared stores or standalone DB path initialization.
- Document change tracking via `DocumentStore`.
- No background scanner, no debounce, no custom notifications, no proposal diagnostics.

**Assessment:** This is the area with the largest feature gap. V1's LSP was a rich editor integration layer that could show agent status changes in real-time, display proposal diffs as diagnostics, and maintain live graph state. V2's LSP is a thin query layer that delegates most interaction to the web UI via `remora.chat`. Whether this matters depends on the deployment model — if users primarily interact via the web panel, the thin LSP is sufficient. If users want a fully editor-native experience without a browser, v2's LSP is significantly less capable.

### 4.4 Neovim Integration

**V1:**
- `src/remora/lsp/nvim/lua/remora/` — Full Lua plugin: `init.lua` (LSP client setup, keybindings, autocommands), `panel.lua` (split-window agent panel with real-time status, chat history, input handling), `log.lua` (structured logging).
- `remora_demo/nvim-companion/` — Companion-specific Neovim plugin with additional UI panels.
- Rich editor experience: floating windows, status line integration, keybindings for agent interaction, live-updating panels.

**V2:**
- `contrib/neovim/remora.lua` — Minimal plugin: LSP client configuration, basic keybindings.
- `contrib/neovim/example-init.lua` — Example Neovim configuration.
- No panel, no floating windows, no companion integration, no live status updates.

**Assessment:** Significant reduction. V2's Neovim support is essentially "connect to the LSP server" with no custom UI. The expectation is that users open the web panel for rich interaction. This is a valid design choice but does reduce the "native editor" experience that v1 offered.

---

## 5. Capabilities Preserved in v2

The following v1 capabilities are fully present in v2, often in improved form:

| Capability | v1 Location | v2 Location | Notes |
|-----------|-------------|-------------|-------|
| Reactive agent loop | SwarmExecutor + AgentRunner | Actor + ActorPool | Simpler, single path |
| Tree-sitter discovery | discovery modules | code/discovery.py + reconciler.py | Improved with watchfiles |
| Node graph with edges | EventStore graph methods | NodeStore with edges table | First-class edges |
| Event persistence | EventStore (658 lines) | EventStore (180 lines) | Simpler, same core function |
| Subscription-based routing | SubscriptionRegistry + triggers | SubscriptionRegistry + TriggerDispatcher | Cleaner separation |
| EventBus pub/sub | EventBus | EventBus | Nearly identical |
| Cairn workspaces | AgentWorkspace | AgentWorkspace + CairnWorkspaceService | Better lifecycle mgmt |
| Grail tool scripts | Scattered loading | grail.py with LRU cache | Centralized |
| Bundle overlay system | bundle_overlays dict | bundle_overlays + bundle_rules | Enhanced with patterns |
| LLM kernel (structured-agents) | kernel_factory.py | kernel.py | Nearly identical |
| LSP code lens / hover / actions | lsp/server.py + handlers/ | lsp/server.py | Same features, less code |
| Web API with SSE | service/api.py | web/server.py | More endpoints |
| CLI (Typer) | __main__.py | __main__.py | Same framework |
| Human input request/response | Event-based | Event-based with futures | Improved async handling |
| Rewrite proposal flow | Runner-managed | Event-based with web API | More accessible |
| Cascade prevention | AgentRunner depth/cooldown | Actor local policies | Per-agent instead of global |
| Status transitions | Implicit | NodeStatus enum with validation | More rigorous |
| Metrics collection | Scattered | core/metrics.py | Centralized |
| Virtual/declarative agents | Not present | VirtualAgentConfig in config | New capability |

---

## 6. Capabilities Missing from v2

### 6.1 Companion System

**What it was:** The companion system (`companion/`) was v1's most distinctive feature — persistent per-CST-node agents that maintained ongoing conversation histories, ran post-exchange MicroSwarms (summarizer, categorizer, linker, reflection), composed sidebar content, and provided a chat-like interface for each code element.

**What's lost:**
- `NodeAgent`: Persistent chat agents with conversation memory and workspace-backed notes/snapshots.
- `MicroSwarm` protocol: Parallel post-exchange processing swarms for summarization, categorization, link discovery, and reflection.
- `NodeAgentRouter`: Event routing to per-node chat agents.
- Sidebar composition: Aggregated agent insights displayed in editor panels.
- Inter-agent messaging with memory: Agents could message each other and the messages persisted as part of the conversation.

**Impact: HIGH.** This was v1's unique value proposition — code elements that "think about themselves." V2's Actor model supports conversation history and messaging, but there's no equivalent of the MicroSwarm post-processing or sidebar composition. The building blocks exist in v2 (actors have conversation history, events support agent messaging), but the orchestration layer is absent.

**Mitigation:** The MicroSwarm pattern could be implemented as bundle scripts (Grail tools) that an agent calls after each turn. Sidebar composition could be a virtual agent that subscribes to AgentCompleteEvents. The v2 architecture can support these patterns — they just haven't been built yet.

### 6.2 Bootstrap & Coordinator

**What it was:** Automatic discovery of unassigned nodes and creation of agents to manage them (`bootstrap/runner.py`, `bootstrap/coordinator.py`, `bootstrap/seed_graph.py`).

**What's replaced by:** V2's FileReconciler handles node discovery and bundle provisioning directly. Virtual agents in config provide declarative agent creation. The reconciler registers subscriptions for discovered nodes automatically.

**Impact: LOW.** V2's approach is more deterministic and easier to reason about. The bootstrap system was essentially "discover nodes, then figure out which agent type to assign" — v2 collapses this into "discover nodes, apply bundle rules, provision workspace."

### 6.3 Vector Search / Embeddy

**What it was:** `IndexingService` in `companion/indexing_service.py` — embeddy-based vector indexing and hybrid search across code elements, with chunking, multiple collections, and semantic similarity.

**Impact: MEDIUM.** Semantic code search was a powerful capability for agents trying to understand codebases. V2 has no equivalent. However, this was tightly coupled to the companion system and embeddy (an external service). V2's TurnContext provides `search_content()` which does text-based search via the graph, which covers the basic use case.

### 6.4 Server Deployment

**What it was:** `server/` directory with Dockerfile, docker-compose.yml, adapter_manager.py, agents_server.py — Docker-based deployment of Remora as a service.

**Impact: LOW.** This was deployment infrastructure, not core functionality. V2 can be deployed via `remora start` and wrapped in a container trivially. The adapter_manager (for managing multiple model backends) could be useful but is orthogonal to the core.

### 6.5 Browser Demo

**What it was:** `browser_demo/` — Standalone package with clipper, fetcher, converter, store for capturing and analyzing web content.

**Impact: NEGLIGIBLE.** This was a demo/experiment, not core remora functionality.

### 6.6 E2E Test Harness & Training Data

**What it was:** `e2e/` — End-to-end testing harness with scenarios and orchestrated test runs. `training/` — Training data for agent evaluation.

**Impact: LOW for functionality, MEDIUM for quality assurance.** The e2e harness was valuable for validating agent behavior end-to-end. V2 has unit and integration tests but no equivalent e2e framework.

### 6.7 Agent Type Library

**What it was:** `agents/` at repo root — 15+ specialized agent type directories (apply_fix, article, chat, docstring, lint, test, etc.), each with their own prompts, tools, and configurations.

**What's replaced by:** V2's `bundles/` directory (code-agent, directory-agent, review-agent, system, test-agent) with system prompts and Grail tool scripts.

**Impact: LOW.** The v1 agent types were largely prompt variations. V2's bundle system is more flexible — you can create arbitrary bundles without modifying code. The 15+ v1 agent types can be recreated as bundle directories.

### 6.8 Advanced LSP Features

**What's missing:**
- Background scanner for periodic graph refresh
- Debounced reparse on document changes
- Debounced cursor tracking
- Custom LSP notifications (`$/remora/event`, `$/remora/agentsUpdated`)
- Proposal diagnostics displayed inline in the editor
- Process lock for single-instance enforcement
- Runtime operations via custom LSP commands (create subscriptions, etc.)

**Impact: MEDIUM.** The custom notifications and proposal diagnostics were genuinely useful for editor-native workflows. V2 compensates by routing interaction through the web panel, but users who prefer staying in their editor lose real-time agent status updates and inline proposal display.

### 6.9 RemoraService Layer

**What it was:** Framework-agnostic service API (`service/api.py`) that could be embedded in different web frameworks, with companion integration, UI projector, and event replay.

**Impact: LOW.** V2's `RuntimeServices` + Starlette web server provides the same functionality in a more direct way. The "framework-agnostic" abstraction in v1 was aspirational — in practice, it was only used with one framework.

### 6.10 Extension System

**What it was:** `.remora/models` directory convention for user-defined model configurations and agent extensions.

**What's replaced by:** `bundle_rules` with pattern matching in `remora.yaml`, virtual agents in config.

**Impact: LOW.** V2's declarative approach is more explicit and easier to understand.

---

## 7. Simplifications Achieved in v2

These are not just "fewer lines" — they represent genuine conceptual simplifications:

1. **One execution path, not two.** V1 had SwarmExecutor (CLI) and AgentRunner (interactive) both delegating to execute_agent_turn(). V2 has Actor. One concept, one path.

2. **Actor = agent.** In v1, the relationship between AgentNode, execution context, runner state, and companion agent was tangled. In v2, Actor IS the agent — it has an inbox, processes messages, maintains conversation history, and manages its own lifecycle.

3. **FileReconciler replaces three subsystems.** Bootstrap seeding + NodeProjection + coordinator = FileReconciler. One module that watches files, discovers nodes, provisions workspaces, and registers subscriptions.

4. **RuntimeServices makes DI explicit.** V1 had implicit service wiring scattered across initialization code. V2 has a single container that wires everything and can be inspected/tested.

5. **Events are the only coordination mechanism.** V1 had events, but also command queues, proposal managers, and direct method calls between subsystems. V2 routes everything through EventStore → EventBus → TriggerDispatcher → Actor inbox.

6. **Configuration is declarative.** Virtual agents, bundle rules, and subscription patterns are all defined in `remora.yaml`. V1 required code changes or directory conventions for equivalent customization.

7. **Single database abstraction.** V1 used raw sqlite3 with manual connection management, separate read/write connections, and manual WAL checkpointing. V2 uses aiosqlite throughout, which handles connection pooling and async natively.

8. **LSP is a thin view.** V1's LSP was a mini-application with its own database, graph, scanner, and notification system. V2's LSP is a pure query layer over shared stores, with rich interaction delegated to the web panel.

---

## 8. Verdict: Did v2 Achieve Its Goal?

**Yes, with caveats.**

V2 successfully provides the same **core reactive loop** — discover code elements, create node graph, assign agents via bundles, execute LLM turns with tools in sandboxed workspaces, react to events — in a dramatically simpler architecture. The 72% code reduction is genuine, not achieved by deleting features but by finding better abstractions (Actor model, FileReconciler, RuntimeServices, declarative config).

The mental model is clearer:
- **V1:** "There are nodes, agents, runners, executors, companions, swarms, projections, bootstrappers, and a service layer, and they all interact through events, queues, and direct calls."
- **V2:** "There are nodes in a graph. Events trigger actors. Actors run LLM turns with tools. Everything is wired through RuntimeServices."

**The caveats:**

1. **The companion system gap is real.** V1's MicroSwarm post-processing (summarize, categorize, link, reflect) and sidebar composition represented a vision of "agents that maintain ongoing understanding of code." V2 has the building blocks but not the orchestration. This is the one area where a v1 user would say "I can't do that anymore."

2. **LSP richness is reduced.** If your workflow is editor-first with no browser, v2's LSP provides less real-time feedback than v1's. This is a deliberate design choice (delegate to web panel) but it's a trade-off, not a simplification.

3. **No vector search.** Semantic code search was a differentiating capability. V2's text-based search is functional but less powerful for "find code that does something similar to X."

**Overall assessment:** V2 is a successful rewrite. It preserves the essential architecture, dramatically simplifies the mental model, and makes the system more maintainable. The missing capabilities are either (a) peripheral to the core mission, (b) implementable on top of v2's architecture without core changes, or (c) deliberate design choices that shift interaction to the web panel. The companion system is the only gap that would require significant new development to close.

---

## 9. Recommendations

### High Priority — Close the Companion Gap

1. **Implement post-turn processing hooks in Actor.** Add an optional `post_turn_hooks` mechanism that runs after each LLM turn — this enables MicroSwarm-equivalent processing (summarize, categorize, link) as bundle-defined Grail scripts rather than hardcoded swarm types.

2. **Create a "reflection" bundle.** A virtual agent that subscribes to `AgentCompleteEvent` and maintains cross-agent summaries — this replaces the sidebar composition pattern.

### Medium Priority — Enhance LSP

3. **Add custom LSP notifications for agent status.** A single `$/remora/agentStatus` notification when actor status changes would restore the real-time editor feedback that v1 had, without the full complexity of v1's LSP subsystem.

4. **Add proposal diagnostics.** When a rewrite proposal exists for a file, emit LSP diagnostics to highlight affected ranges. This is a small addition to the existing code_lens/hover infrastructure.

### Low Priority — Nice to Have

5. **Content search via embeddings.** If vector search is desired, it can be added as a Grail tool that agents call, rather than baked into the core. This keeps the architecture simple while restoring the capability.

6. **Richer Neovim plugin.** A panel.lua equivalent that shows agent status and conversation in a split window would significantly improve the editor-native experience. This is independent of the core and can be developed separately.

7. **E2E test harness.** As v2 stabilizes, an end-to-end testing framework similar to v1's `e2e/` would be valuable for regression testing agent behavior.
