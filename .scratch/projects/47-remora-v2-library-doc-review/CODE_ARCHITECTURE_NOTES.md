# Code Architecture Notes

## High-level identity
- Package: `remora` (`0.5.0`).
- Description in packaging metadata: reactive agent swarm substrate for code/content nodes.
- Runtime shape: event-sourced-ish SQLite state + in-memory event bus + per-node actors + optional web/LSP/search.

## Startup and lifecycle
- CLI entrypoint: `src/remora/__main__.py`.
- `remora start` builds `RemoraLifecycle` and drives `start() -> run() -> shutdown()`.
- `RemoraLifecycle.start()`:
  - opens sqlite under `<project_root>/<workspace_root>/remora.db`
  - configures file logging at `<workspace_root>/remora.log`
  - initializes `RuntimeServices`
  - performs initial `reconciler.full_scan()` before background loops
  - starts actor pool loop, reconciler watch loop, optional web server, optional LSP server

## Runtime services composition
- `RuntimeServices` wires:
  - `EventBus`
  - `TriggerDispatcher`
  - `TransactionContext`
  - `SubscriptionRegistry`
  - `NodeStore`
  - `EventStore`
  - `CairnWorkspaceService`
  - `LanguageRegistry`
  - optional `SearchService`
  - `FileReconciler`
  - `ActorPool`
- `TriggerDispatcher.router` is set to actor pool routing callback.

## Persistent model and storage
- `nodes` table stores discovered + virtual + directory agents (`Node` model).
- `edges` table stores directed edges (primarily `contains`).
- `events` table stores append-only event rows with payload JSON and summary.
- status transition rules enforced in `NodeStore.transition_status()` via allowed-source update query.
- transaction batching (`TransactionContext.batch`) defers event fan-out until outer commit.

## Event flow
- `EventStore.append()` persists event row first.
- outside batch: commits and then emits to event bus and subscription dispatcher.
- inside batch: defers bus/dispatch fan-out to commit stage.
- subscription matching uses `SubscriptionPattern` on event type, from/to agents, path glob, tags.
- dispatcher routes matching events to actor inboxes through router callback.

## Discovery and reconciliation
- Tree-sitter discovery in `remora/code/discovery.py`:
  - language determined by extension -> configured language map
  - query captures `@node` + `@node.name`
  - hierarchical full names built from AST ancestor captures
  - node IDs are `<absolute_file_path>::<full_name>` (with byte suffix on collision)
- `FileReconciler`:
  - syncs declarative virtual agents (`VirtualAgentManager.sync()`) every cycle
  - materializes directory nodes (`DirectoryManager.materialize()`)
  - reconciles changed/new/deleted files
  - registers subscriptions for added/changed nodes
  - provisions bundle templates into per-agent workspaces
  - emits `node_discovered`, `node_changed`, `node_removed`
  - optional semantic index/deindex per file
- Watches filesystem with `watchfiles`; also subscribes to `content_changed` events for immediate reconcile.

## Actor execution model
- `ActorPool` lazily creates one `Actor` per node when first routed event arrives.
- each actor has bounded inbox queue and overflow policy (`drop_oldest`, `drop_new`, `reject`).
- trigger policy enforces cooldown and correlation-depth limits.
- one turn path:
  1. transition node status to `running`
  2. emit `agent_start`
  3. load bundle config from workspace `_bundle/bundle.yaml`
  4. create `TurnContext` capabilities + discover Grail tools from `_bundle/tools`
  5. build prompts (`PromptBuilder`) and run structured-agents kernel
  6. emit translated model/tool/turn observer events
  7. emit `agent_complete` with `tags=("primary",)` or reflection tags
  8. transition status back to `idle` in finally

## Workspace and bundles
- per-agent workspace path rooted under `<workspace_root>/agents/<safe-id-hash>`.
- bundle provisioning merges ordered `bundle.yaml` overlays and copies tool scripts into `_bundle/tools`.
- default ordering usually system bundle then role bundle.
- bundle fingerprint caching avoids unnecessary copy.
- bundle config supports `self_reflect`, prompt overlays, model/max_turn overrides.
- externals API version gate enforced at turn start (`bundle externals_version <= runtime EXTERNALS_VERSION`).

## Tool/runtime interface
- Grail tools loaded from workspace `_bundle/tools/*.pym`.
- tool externals come from capability groups: files, kv, graph, events, comms, search, identity.
- notable communication side effects:
  - `send_message` emits `agent_message`
  - `request_human_input` emits request event and waits on broker future
  - `propose_changes` emits rewrite proposal and sets status awaiting review

## Web and LSP surfaces
- Web (Starlette) routes:
  - `/api/nodes`, `/api/edges`, `/api/events`, `/api/chat`, proposal workflow routes, `/api/search`, `/api/health`, `/api/cursor`, `/sse`
- proposal accept path materializes workspace changes to disk and emits `content_changed`.
- SSE supports replay and Last-Event-ID catch-up.
- LSP (optional): code lens, hover, code actions, did-open/save/change hooks; can emit content-change and manual trigger events.

## Configuration model
- defaults loaded from `src/remora/defaults/defaults.yaml`, then deep-merged with `remora.yaml`.
- supports env expansion `${VAR:-default}`.
- search path entries support `@default` token.
- bundle resolution priority: first matching `bundle_rules`, then `bundle_overlays` by node type.

## Potential doc verification hotspots
- Node ID format and path semantics (absolute paths in discovery).
- Event behavior: persisted-first and immediate in-memory fan-out.
- directory and virtual agents being first-class node types.
- exact externals capability function names/signatures used by `.pym` scripts.
- search mode requirements (`search`, `search-local` extras and availability fallbacks).
- actor overflow/cooldown/depth policies and defaults.
- proposal workflow writes from workspace path mapping (`source/<node_id>` convention).
