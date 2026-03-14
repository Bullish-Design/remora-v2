# Remora v2 — Refactoring Opportunities

A comprehensive catalog of ideas for improving the codebase — from surgical cleanups to radical architectural changes. Each idea includes pros, cons, implications, and opportunities. **Backwards compatibility is explicitly NOT a constraint.**

## Table of Contents

1. **[Unify Node/Agent Status into Single Source of Truth](#1-unify-nodeagent-status-into-single-source-of-truth)** — Eliminate dual status tracking
2. **[Introduce Transaction/Unit-of-Work Pattern](#2-introduce-transactionunit-of-work-pattern)** — Batch commits, atomic operations
3. **[Decompose FileReconciler into Focused Services](#3-decompose-filereconciler-into-focused-services)** — Break the god class
4. **[Replace TurnContext God Object with Capability Groups](#4-replace-turncontext-god-object-with-capability-groups)** — Structured externals API
5. **[Introduce a BundleConfig Pydantic Model](#5-introduce-a-bundleconfig-pydantic-model)** — Replace ad-hoc dict parsing
6. **[Event Envelope as First-Class Type](#6-event-envelope-as-first-class-type)** — Clean event persistence boundary
7. **[Protocol-Based Store Abstractions](#7-protocol-based-store-abstractions)** — Decouple stores from SQLite
8. **[Merge Node and Agent into a Single Table](#8-merge-node-and-agent-into-a-single-table)** — Collapse the redundant split
9. **[Actor as a Pure Message Processor](#9-actor-as-a-pure-message-processor)** — Extract orchestration from Actor
10. **[Grail Tool Descriptor Metadata](#10-grail-tool-descriptor-metadata)** — Rich tool descriptions for LLMs
11. **[Async File I/O Everywhere](#11-async-file-io-everywhere)** — Eliminate sync I/O in async paths
12. **[Subscription Matching on Event Envelope](#12-subscription-matching-on-event-envelope)** — Replace getattr probing
13. **[Replace LRU Caches with Explicit Invalidation](#13-replace-lru-caches-with-explicit-invalidation)** — Controllable cache lifecycle
14. **[Eliminate DiscoveredElement Model](#14-eliminate-discoveredelement-model)** — Remove dead abstraction
15. **[Actor Inbox Back-Pressure](#15-actor-inbox-back-pressure)** — Bounded queues with overflow policy
16. **[Reconciler Directory Node as Projection](#16-reconciler-directory-node-as-projection)** — Derive directories from events
17. **[Configuration-Driven Prompt Templates](#17-configuration-driven-prompt-templates)** — Externalize prompt construction
18. **[Service Locator to Explicit Dependency Injection](#18-service-locator-to-explicit-dependency-injection)** — Clean RuntimeServices
19. **[Outbox Protocol for Testability](#19-outbox-protocol-for-testability)** — Protocol instead of test double in prod
20. **[Idempotent Event Processing](#20-idempotent-event-processing)** — Enable safe replay and crash recovery
21. **[Collapse CSTNode and Node into Unified Pipeline](#21-collapse-cstnode-and-node-into-unified-pipeline)** — Eliminate the projection step
22. **[Web Server as Thin Read Model](#22-web-server-as-thin-read-model)** — CQRS-inspired separation
23. **[Plugin-Based Language Support via Entry Points](#23-plugin-based-language-support-via-entry-points)** — Extensible language discovery
24. **[Workspace File Operations as Async Generators](#24-workspace-file-operations-as-async-generators)** — Streaming file operations
25. **[Global Error Taxonomy](#25-global-error-taxonomy)** — Structured error types instead of broad catches

---

## 1. Unify Node/Agent Status into Single Source of Truth

**Current state**: Both `NodeStore` (nodes table) and `AgentStore` (agents table) independently track `status`. Every status change must update both, creating 6+ coordination points across `actor.py`, `externals.py`, and `reconciler.py`. If either update fails, the stores silently diverge.

**Proposal**: Eliminate the `agents` table entirely. Store agent status directly on the `nodes` table. The `Agent` model becomes unnecessary — `Node` already carries all the fields.

**Pros**:
- Eliminates an entire class of consistency bugs (divergent status)
- Removes ~100 lines of agent store code and all dual-update callsites
- Simplifies `RuntimeServices` initialization (one less store to create/init)
- Reduces database commit frequency (half as many status writes)

**Cons**:
- Conceptual purity: "agent" and "code element" are logically distinct concepts that happen to share an ID
- If agents ever need to exist independent of code elements (e.g., virtual agents, user agents), the unified model would need extension

**Implications**:
- `AgentStore` deleted entirely
- `Node` gains sole ownership of status
- `Actor._start_agent_turn`, `_reset_agent_state`, `_execute_turn` error handler all simplified
- `TurnContext.graph_set_status` updates only NodeStore
- `FileReconciler._ensure_agent` becomes a no-op (or deleted)

**Opportunities**: With status in one place, add a `status_changed_at` timestamp to enable time-based queries ("which agents have been stuck in RUNNING for >60s?").

---

## 2. Introduce Transaction/Unit-of-Work Pattern

**Current state**: Every store method calls `await self._db.commit()` immediately. A single reconciliation cycle triggers dozens of individual commits. There are no transaction boundaries — multi-step operations (create node + register subscriptions + create agent + emit event) are not atomic.

**Proposal**: Introduce an async context manager `UnitOfWork` that batches operations and commits once at the end.

```python
async with unit_of_work(db) as uow:
    await node_store.upsert_node(node, uow)
    await subscriptions.register(node.node_id, pattern, uow)
    await event_store.append(event, uow)
    # Single commit at __aexit__
```

**Pros**:
- Atomic multi-step operations — partial failures roll back
- Massive reduction in commit frequency (10-50x fewer commits per reconcile cycle)
- Performance improvement from batched writes
- Enables proper foreign key enforcement (changes are visible within the transaction)

**Cons**:
- Adds a new abstraction that every store must support
- Longer-held transactions could increase contention (mitigated by single-connection architecture)
- Requires careful handling of EventBus emission timing (emit after commit, not before)

**Implications**:
- Every store method gains an optional `connection` parameter (defaults to `self._db`)
- `EventStore.append` must separate persistence from bus emission — persist in transaction, emit after commit
- `FileReconciler.reconcile_cycle` wraps its operations in a single UoW

**Opportunities**: Enables a "dry run" mode where you run a reconciliation cycle within a transaction, inspect changes, then roll back.

---

## 3. Decompose FileReconciler into Focused Services

**Current state**: `FileReconciler` (~500 lines) handles: file watching, mtime tracking, directory node materialization, file reconciliation, subscription registration, agent creation, bundle provisioning, and content change event handling. It has triple bootstrap flags (`_subscriptions_bootstrapped`, `_bundles_bootstrapped`, file-state initialization).

**Proposal**: Break into 3-4 focused services:

- **`FileWatcher`**: Owns `watchfiles` integration, mtime tracking, and the `run_forever` loop. Emits raw file change events.
- **`NodeReconciler`**: Takes file change events, runs discovery + projection, diffs against existing graph, emits node lifecycle events.
- **`DirectoryProjection`**: Materializes directory nodes from the set of known file paths. Runs as a reaction to node additions/removals.
- **`SubscriptionManager`**: Registers default subscriptions for new nodes. React to NodeDiscovered/NodeRemoved events.

**Pros**:
- Each service is independently testable with clear inputs/outputs
- Eliminates the triple bootstrap problem — each service initializes independently
- `FileWatcher` can be replaced with an LSP-driven change source without touching reconciliation logic
- Clearer responsibility boundaries

**Cons**:
- More classes to coordinate
- Inter-service ordering matters (e.g., nodes must exist before subscriptions are registered)
- Current reconciler's tight integration means changes propagate immediately; splitting requires event-driven coordination

**Implications**:
- `RuntimeServices.initialize()` creates and wires 3-4 new services instead of one reconciler
- The reconcile cycle becomes a pipeline: watch → discover → diff → persist → subscribe
- Directory materialization becomes reactive (triggered by NodeDiscovered events) instead of proactive

**Opportunities**: Opens the door to pluggable file sources (git hooks, CI triggers, remote file systems) by decoupling the source of change from the reconciliation logic.

---

## 4. Replace TurnContext God Object with Capability Groups

**Current state**: `TurnContext` exposes 24 methods via `to_capabilities_dict()`. All methods are flat — filesystem ops, KV ops, graph ops, event ops, messaging, and code ops share the same namespace.

**Proposal**: Group capabilities into namespaced capability objects:

```python
class FileCapabilities:
    async def read(self, path: str) -> str: ...
    async def write(self, path: str, content: str) -> bool: ...
    async def list_dir(self, path: str) -> list[str]: ...
    async def exists(self, path: str) -> bool: ...
    async def search(self, pattern: str) -> list[str]: ...

class GraphCapabilities:
    async def get_node(self, target_id: str) -> dict: ...
    async def query_nodes(self, ...) -> list[dict]: ...
    async def get_edges(self, target_id: str) -> list[dict]: ...
    async def get_children(self, parent_id: str | None) -> list[dict]: ...
    async def set_status(self, target_id: str, status: str) -> bool: ...

class EventCapabilities:
    async def emit(self, event_type: str, payload: dict) -> bool: ...
    async def subscribe(self, ...) -> int: ...
    async def unsubscribe(self, subscription_id: int) -> bool: ...
    async def get_history(self, target_id: str, limit: int) -> list[dict]: ...

class MessagingCapabilities:
    async def send(self, to_node_id: str, content: str) -> bool: ...
    async def broadcast(self, pattern: str, content: str) -> str: ...
```

**Pros**:
- Clear capability boundaries — tools declare which capability groups they need
- Enables fine-grained permission control (e.g., directory agents can't call `apply_rewrite`)
- Easier to document and discover capabilities
- Each group is independently testable

**Cons**:
- Grail's `@external` bridge currently maps flat names — would need namespace support (e.g., `file.read` instead of `read_file`)
- More objects to construct per turn
- Breaking change to all existing .pym tool scripts

**Implications**:
- All .pym tool scripts update their `@external` declarations
- `to_capabilities_dict()` produces nested dict or uses dotted names
- Grail must support namespaced externals (or capabilities are flattened with prefix)

**Opportunities**: Enables a capability-based security model where bundle config declares which capability groups a role can access. Code agents get `file.*` + `graph.*` + `code.*`; directory agents get `graph.*` + `messaging.*` but not `code.*`.

---

## 5. Introduce a BundleConfig Pydantic Model

**Current state**: Bundle configuration is parsed from YAML into a `dict[str, Any]`, then individual keys are extracted with type checks and fallbacks in `Actor._read_bundle_config()` (~40 lines of manual validation).

**Proposal**: Define a `BundleConfig` Pydantic model:

```python
class BundleConfig(BaseModel):
    name: str = ""
    system_prompt: str = "You are an autonomous code agent."
    system_prompt_extension: str = ""
    model: str | None = None
    max_turns: int = 4
    prompts: dict[str, str] = Field(default_factory=dict)
```

**Pros**:
- Type-safe access to all config fields
- Validation happens at parse time with clear error messages
- Eliminates the `_read_bundle_config` manual parsing
- Self-documenting schema

**Cons**:
- Pydantic will reject unknown keys by default (need `model_config = ConfigDict(extra="ignore")`)
- Minor: one more model class to maintain

**Implications**:
- `Actor._read_bundle_config` reduces to `BundleConfig.model_validate(yaml.safe_load(text))`
- `_build_system_prompt` takes `BundleConfig` instead of `dict[str, Any]`
- Bundle YAML schema is now explicitly defined and documented

**Opportunities**: Extend `BundleConfig` with `capabilities: list[str]` to declare which capability groups a role can access (ties into #4).

---

## 6. Event Envelope as First-Class Type

**Current state**: `Event.to_envelope()` returns a `dict[str, Any]` with `event_type`, `timestamp`, `correlation_id`, and `payload`. The `EventStore.append()` method then destructures this dict to extract specific fields. Subscription matching uses `getattr` on the event object.

**Proposal**: Define `EventEnvelope` as a Pydantic model:

```python
class EventEnvelope(BaseModel):
    event_type: str
    timestamp: float
    correlation_id: str | None
    agent_id: str | None = None
    from_agent: str | None = None
    to_agent: str | None = None
    path: str | None = None
    payload: dict[str, Any]
    summary: str = ""
```

**Pros**:
- Single representation for both in-memory dispatch and SQLite storage
- Subscription matching operates on typed fields instead of `getattr` probing
- Serialization/deserialization is handled by Pydantic
- Clear contract between event types and the persistence layer

**Cons**:
- Events must populate the envelope fields explicitly
- Slight overhead from an extra model construction per event

**Implications**:
- `EventStore.append` takes an `EventEnvelope` (or constructs one from an `Event`)
- `SubscriptionPattern.matches` takes an `EventEnvelope` — no more `getattr` duck typing
- `EventBus` can emit both the original `Event` (for typed handlers) and the envelope (for generic handlers)

**Opportunities**: The envelope is the natural unit for event replay, export, and cross-system integration.

---

## 7. Protocol-Based Store Abstractions

**Current state**: `NodeStore`, `AgentStore`, `EventStore`, and `SubscriptionRegistry` are concrete classes tightly coupled to aiosqlite. Testing them requires a real database connection.

**Proposal**: Define Protocol interfaces for each store:

```python
class NodeStoreProtocol(Protocol):
    async def upsert_node(self, node: Node) -> None: ...
    async def get_node(self, node_id: str) -> Node | None: ...
    async def list_nodes(self, ...) -> list[Node]: ...
    async def delete_node(self, node_id: str) -> bool: ...
    # etc.
```

**Pros**:
- Enables in-memory test implementations without database setup
- Decouples business logic from persistence technology
- Makes it possible to swap SQLite for PostgreSQL, DuckDB, etc.
- Cleaner type annotations throughout the codebase

**Cons**:
- More protocol definitions to maintain
- SQLite-specific optimizations (like `executescript` for table creation) become harder to express
- May be premature if SQLite will always be the backend

**Implications**:
- `Actor`, `FileReconciler`, `TurnContext` all type-hint against protocols
- `test/` can use lightweight in-memory store implementations
- `RuntimeServices` constructs concrete implementations

**Opportunities**: An in-memory store implementation would make tests ~10x faster by eliminating database I/O.

---

## 8. Merge Node and Agent into a Single Table

**Current state**: `nodes` and `agents` are separate tables. The `agents` table has `agent_id`, `element_id`, `status`, and `role`. The `nodes` table already has `status` and `role` fields. When they're joined, `agent_id == element_id == node_id`. The two tables always hold the same status.

**Proposal**: Delete the `agents` table. The `nodes` table is the single source of truth for all node and agent state.

**Pros**:
- Eliminates dual status tracking (the #1 design smell identified in the code review)
- Removes `AgentStore` entirely (~80 lines)
- Removes all dual-update coordination code
- Simpler schema, fewer tables, fewer indexes

**Cons**:
- Loses the conceptual distinction between "discovered code element" and "agent attached to it"
- If headless agents (not tied to code) are ever needed, they'd need a different mechanism

**Implications**:
- `AgentStore` deleted
- All references to `agent_store` replaced with `node_store` operations
- `Node.to_agent()` deleted
- `Agent` model potentially deleted (or kept as a view)
- `FileReconciler._ensure_agent` becomes unnecessary
- `RuntimeServices` drops `agent_store` attribute

**Opportunities**: Combined with #1, this removes an entire layer of abstraction and its associated complexity.

---

## 9. Actor as a Pure Message Processor

**Current state**: `Actor` class (~400 lines) handles inbox processing, trigger policy, LLM turn orchestration, bundle config reading, tool discovery, kernel creation, message construction, execution, and state management. It's the most complex class in the codebase.

**Proposal**: Split Actor into:

- **`Actor`** (~50 lines): Pure message processor. Owns inbox, processes events sequentially, delegates to a `TurnExecutor`.
- **`TurnExecutor`**: Handles a single agent turn — config loading, tool discovery, kernel creation, LLM execution, result handling.
- **`TriggerPolicy`**: Encapsulates cooldown, depth checking, and rate limiting logic.

```python
class Actor:
    def __init__(self, node_id, policy, executor, semaphore):
        self.inbox = asyncio.Queue()
        self._policy = policy
        self._executor = executor

    async def _run(self):
        while True:
            event = await self.inbox.get()
            if self._policy.should_trigger(event):
                async with self._semaphore:
                    await self._executor.execute(self.node_id, event)
```

**Pros**:
- Each component is independently testable
- `TriggerPolicy` can be unit-tested with simple in/out assertions
- `TurnExecutor` can be tested with mock LLM responses
- Actor loop logic is trivially simple
- `TurnExecutor` is reusable for manual/CLI-triggered turns

**Cons**:
- More classes to wire together
- `ActorPool` factory becomes slightly more complex

**Implications**:
- `test_actor.py` (689 lines) can be split into focused test files
- `TurnExecutor` owns the entire LLM interaction lifecycle
- `TriggerPolicy` is configurable per-role (different bundles might have different cooldown/depth settings)

**Opportunities**: A pluggable `TriggerPolicy` enables different activation strategies: rate-limited, debounced, priority-based, or manual-only.

---

## 10. Grail Tool Descriptor Metadata

**Current state**: Every tool gets the description `f"Tool: {script.name}"`. The LLM has no meaningful information about what a tool does or when to use it.

**Proposal**: Add a description declaration to Grail scripts:

```python
# In .pym files:
from grail import Description
description = Description("Send a message to another agent node by its ID")
```

Or parse it from the bundle YAML:

```yaml
# bundle.yaml
tools:
  send_message:
    description: "Send a message to another agent node by its ID"
  rewrite_self:
    description: "Propose a rewrite of this node's source code"
```

**Pros**:
- Dramatically improves LLM tool selection accuracy
- Self-documenting tool inventory
- Descriptions can include usage examples, parameter explanations

**Cons**:
- Requires changes to Grail's script metadata or bundle YAML schema
- All existing .pym files need description additions

**Implications**:
- `GrailTool.__init__` reads description from script metadata or config
- `ToolSchema.description` is populated with meaningful text
- Bundle YAML gains a `tools` section for per-tool configuration

**Opportunities**: With rich descriptions, the system can auto-generate API documentation, help text, and tool inventories.

---

## 11. Async File I/O Everywhere

**Current state**: Several async methods perform synchronous file I/O:
- `workspace.py`: `pym_file.read_text()`, `bundle_yaml.read_text()` in `provision_bundle`
- `discovery.py`: `path.read_bytes()`, query file reading
- `reconciler.py`: `file_path.stat()` in `_collect_file_mtimes`
- `web/server.py`: `_INDEX_HTML` at module import

**Proposal**: Use `asyncio.to_thread` or `aiofiles` for all file I/O in async contexts.

**Pros**:
- No event loop blocking, even with slow I/O (network filesystems, large files)
- Consistent async discipline throughout the codebase

**Cons**:
- `asyncio.to_thread` has overhead (~10-50μs per call) — for tiny files, this is slower than sync
- Adds complexity for simple reads
- `aiofiles` adds another dependency

**Implications**:
- `_collect_file_mtimes` uses `to_thread(os.stat, ...)` or runs in executor
- Discovery uses `to_thread(path.read_bytes)` for source files
- Bundle provisioning uses async file reads

**Opportunities**: Enables running Remora against network-mounted codebases or large repositories without blocking the event loop.

---

## 12. Subscription Matching on Event Envelope

**Current state**: `SubscriptionPattern.matches()` uses `getattr(event, "from_agent", None)` and similar to probe for fields that may or may not exist on the event object. This creates implicit duck-typing contracts.

**Proposal**: Subscription matching operates on the `EventEnvelope` (from #6) which has explicit typed fields:

```python
def matches(self, envelope: EventEnvelope) -> bool:
    if self.event_types and envelope.event_type not in self.event_types:
        return False
    if self.from_agents and envelope.from_agent not in self.from_agents:
        return False
    if self.to_agent and envelope.to_agent != self.to_agent:
        return False
    if self.path_glob and (envelope.path is None or not PurePath(envelope.path).match(self.path_glob)):
        return False
    return True
```

**Pros**:
- No more `getattr` probing — all fields are explicitly typed
- Clear contract: events must populate envelope fields to be matchable
- Easier to add new matching dimensions (correlation_id, tags, etc.)

**Cons**:
- Requires implementing #6 first (EventEnvelope)
- Events that don't populate envelope fields won't match subscriptions (explicit is good)

**Implications**:
- `TriggerDispatcher.dispatch` constructs an envelope before matching
- Or: `EventStore.append` creates the envelope, passes it to both persistence and dispatch

**Opportunities**: Envelope-based matching can be optimized with indexes — e.g., an in-memory `from_agent → patterns` index for O(1) lookups.

---

## 13. Replace LRU Caches with Explicit Invalidation

**Current state**: Discovery uses `@lru_cache` for parsers (16), queries (64), scripts (256), and the language registry (1). These caches never clear, so stale data persists until process restart.

**Proposal**: Replace module-level LRU caches with an explicit `DiscoveryCache` object:

```python
class DiscoveryCache:
    def __init__(self):
        self._parsers: dict[str, Parser] = {}
        self._queries: dict[str, Query] = {}
        self._scripts: dict[str, GrailScript] = {}

    def get_parser(self, language: str) -> Parser: ...
    def get_query(self, language: str, query_file: str) -> Query: ...
    def invalidate(self, language: str | None = None): ...
```

**Pros**:
- Controllable lifecycle — invalidate when query files change
- Testable — inject a fresh cache per test
- No module-level state — multiple independent instances possible

**Cons**:
- Must be threaded through to callsites (or stored on a service object)
- LRU cache is zero-configuration; explicit cache requires management

**Implications**:
- `discover()` takes a `cache` parameter
- `FileReconciler` owns the cache and can invalidate on query file changes
- Tests get isolated cache instances (no cross-test contamination)

**Opportunities**: A cache with hit/miss metrics enables profiling of discovery performance.

---

## 14. Eliminate DiscoveredElement Model

**Current state**: `DiscoveredElement` is a Pydantic model in `core/node.py` that's only used as the return type of `Node.to_element()`. No code in the codebase creates or consumes `DiscoveredElement` directly.

**Proposal**: Delete `DiscoveredElement`. If the concept of "immutable discovered data" is needed, use `CSTNode` directly (which already serves this purpose).

**Pros**:
- Removes dead code
- Eliminates a confusing near-duplicate of `CSTNode`
- `Node.to_element()` is also deleted

**Cons**:
- If future code needs to extract the discovery data from a `Node`, it would need to be re-added
- Minor: the conceptual purity of having "code element" and "agent" as separate types is reduced

**Implications**:
- `core/node.py` shrinks by ~20 lines
- `CSTNode` is the canonical "discovered element" type

**Opportunities**: Simplifies the mental model — there are exactly two stages: `CSTNode` (discovered) and `Node` (persisted).

---

## 15. Actor Inbox Back-Pressure

**Current state**: Actor inboxes are `asyncio.Queue()` with no size limit. If events arrive faster than an actor can process them, the queue grows unboundedly. There's no overflow policy, no priority ordering, and no monitoring.

**Proposal**: Use bounded queues with configurable overflow policy:

```python
class ActorInbox:
    def __init__(self, max_size: int = 100, overflow: str = "drop_oldest"):
        self._queue = asyncio.Queue(maxsize=max_size)
        self._overflow = overflow

    def put(self, event: Event) -> bool:
        if self._queue.full():
            if self._overflow == "drop_oldest":
                try: self._queue.get_nowait()
                except: pass
            elif self._overflow == "drop_newest":
                return False
        self._queue.put_nowait(event)
        return True
```

**Pros**:
- Prevents unbounded memory growth under event flood
- Configurable policy per actor or per role
- Enables monitoring (queue depth metrics)

**Cons**:
- Events can be dropped — must handle gracefully
- Adds complexity to the simple Queue model
- Need to decide on sensible defaults

**Implications**:
- `ActorPool._route_to_actor` checks return value of inbox put
- Config gains `inbox_max_size` and `inbox_overflow_policy` settings
- Dropped events could be logged for debugging

**Opportunities**: Priority queues could order events (user messages > system events > content changes), ensuring interactive chat isn't starved by bulk reconciliation events.

---

## 16. Reconciler Directory Node as Projection

**Current state**: `_materialize_directories` (~80 lines) in `FileReconciler` proactively builds directory nodes from the set of known file paths. It runs on every reconciliation cycle, comparing against existing directory nodes and emitting events for changes.

**Proposal**: Make directories a pure projection — derived automatically from the node graph rather than proactively materialized:

- When a file node is added/removed, a reactor creates/updates/removes the parent directory node
- Directory node's `source_hash` is derived from `SELECT source_hash FROM nodes WHERE parent_id = ?`
- No bulk directory materialization needed

**Pros**:
- Eliminates the most complex method in the codebase
- Directory state is always consistent with file nodes (no divergence possible)
- Simpler reconciliation cycle
- Directory changes are emitted as reactions to file changes (natural event flow)

**Cons**:
- Reactive directory materialization has latency — directory node might not exist when a file node references it as parent
- Need to handle ordering: file node needs parent_id, but parent directory might not exist yet
- More events emitted (each file change cascades to directory update)

**Implications**:
- `FileReconciler._materialize_directories` deleted
- A new `DirectoryProjection` service subscribes to NodeDiscovered/NodeRemoved events
- Directory nodes are created lazily on first file discovery in that directory
- `_subscriptions_bootstrapped` flag eliminated

**Opportunities**: Opens the door to other projection types — "module node" (aggregates all classes/functions in a file), "package node" (aggregates all files in a Python package), etc.

---

## 17. Configuration-Driven Prompt Templates

**Current state**: Prompt construction in `Actor._build_prompt` is hardcoded:
```python
parts = [f"# Node: {node.full_name}", f"Type: {node_type} | File: {node.file_path}"]
```

The system prompt comes from bundle YAML, but the user prompt (the actual turn prompt) is rigid.

**Proposal**: Define prompt templates in bundle YAML with Jinja2 or simple string formatting:

```yaml
# bundle.yaml
prompt_template: |
  # Node: {{ node.full_name }}
  Type: {{ node.node_type }} | File: {{ node.file_path }}

  {% if node.source_code %}
  ## Source Code
  ```
  {{ node.source_code }}
  ```
  {% endif %}

  {% if trigger.event %}
  ## Trigger
  Event: {{ trigger.event.event_type }}
  {% endif %}
```

**Pros**:
- Fully customizable per role — directory agents get different prompts than code agents
- Non-developers can modify prompt templates without touching Python
- Enables A/B testing of different prompt strategies
- Template validation at bundle load time

**Cons**:
- Jinja2 adds a dependency (or use Python's `string.Template`)
- Template errors become runtime failures
- More indirection between code and behavior

**Implications**:
- `Actor._build_prompt` becomes `template.render(node=node, trigger=trigger)`
- `BundleConfig` gains a `prompt_template` field
- Default template provides current behavior for backwards compatibility

**Opportunities**: Templates could include conditional sections based on node type, trigger type, or previous turn results.

---

## 18. Service Locator to Explicit Dependency Injection

**Current state**: `RuntimeServices` creates all services internally and wires them together. Components access services through the container. The `Actor` constructor takes 7 parameters because it needs direct references to stores and services.

**Proposal**: Use constructor injection throughout, with a factory module that wires everything:

```python
# factory.py
def create_runtime(config, project_root, db) -> Runtime:
    node_store = NodeStore(db)
    event_bus = EventBus()
    # ... wire everything ...
    return Runtime(node_store=node_store, event_bus=event_bus, ...)
```

**Pros**:
- Every dependency is explicit — no hidden service resolution
- Tests can inject mocks at any point in the graph
- No mutable state on the container after construction

**Cons**:
- Factory function becomes the new complexity hotspot
- Long parameter lists on constructors
- `RuntimeServices` is already doing this — the change is mostly about making it more explicit

**Implications**:
- `RuntimeServices` becomes an immutable data class (or `NamedTuple`) instead of having `initialize()` and `close()` methods
- Lifecycle management (init/close) moves to the factory or a separate lifecycle manager
- Clearer separation between construction and initialization

**Opportunities**: Enables building partial runtimes for testing (e.g., just the event system without discovery).

---

## 19. Outbox Protocol for Testability

**Current state**: `Outbox` and `RecordingOutbox` share the same interface but have no formal contract. `RecordingOutbox` is a test double that lives in production code (`core/actor.py`).

**Proposal**: Define an `OutboxProtocol`:

```python
class OutboxProtocol(Protocol):
    @property
    def actor_id(self) -> str: ...
    @property
    def correlation_id(self) -> str | None: ...
    @correlation_id.setter
    def correlation_id(self, value: str | None) -> None: ...
    async def emit(self, event: Event) -> int: ...
```

Move `RecordingOutbox` to `tests/`.

**Pros**:
- Clean separation between production and test code
- Formal contract makes it safe to create new outbox implementations
- Type checkers can verify that both implementations satisfy the protocol

**Cons**:
- Minimal practical impact — the current code works fine
- One more protocol to maintain

**Implications**:
- `Actor` type-hints outbox as `OutboxProtocol`
- `RecordingOutbox` moves to `tests/conftest.py` or `tests/factories.py`
- `core/actor.py` loses ~30 lines

**Opportunities**: Enables outbox variants like `FilteringOutbox` (drops certain event types), `ThrottlingOutbox` (rate limits emissions), or `LoggingOutbox` (adds audit logging).

---

## 20. Idempotent Event Processing

**Current state**: Events are processed exactly once by actors. If the process crashes mid-turn, the event has been persisted (committed to SQLite) but the agent turn is lost. On restart, there's no mechanism to replay unprocessed events or detect incomplete turns.

**Proposal**: Add an `event_cursor` per agent — a persistent marker of the last fully processed event:

```sql
ALTER TABLE nodes ADD COLUMN last_processed_event_id INTEGER DEFAULT 0;
```

On startup, each actor replays events since its cursor. Events are processed idempotently.

**Pros**:
- Crash recovery without data loss
- Enables "catch up" after downtime
- Provides visibility into processing lag per agent

**Cons**:
- Tool side effects (file writes, code rewrites) are NOT idempotent — replaying a rewrite_self could corrupt code
- Significant complexity for the "exactly once" guarantee
- Replay ordering matters for correctness

**Implications**:
- `Actor._run` loads cursor on start, updates after each successful turn
- `EventStore` gains a `get_events_since(event_id)` method
- Tool scripts must be designed for idempotent execution (or marked as non-replayable)

**Opportunities**: Enables offline processing — agents can "catch up" on events that occurred while they were stopped, enabling batch processing modes.

---

## 21. Collapse CSTNode and Node into Unified Pipeline

**Current state**: Discovery produces `CSTNode` objects, which are then "projected" into `Node` objects in `projections.py`. The projection step hashes source code, checks existing nodes, upserts, and provisions bundles. This creates two nearly-identical types (`CSTNode` and `Node`) with a complex bridging step.

**Proposal**: Discovery produces `Node` objects directly. The projection step becomes part of the persistence layer:

```python
# discovery returns Nodes directly
nodes = discover(paths, ...) -> list[Node]

# store handles upsert with hash comparison
for node in nodes:
    await node_store.upsert_if_changed(node)
```

**Pros**:
- Eliminates `CSTNode` as a separate type (or makes it internal to discovery)
- Removes the `projections.py` module entirely
- Single type throughout the pipeline
- `Node` is the only model to understand

**Cons**:
- Discovery would need to know about `Node` (imports from core)
- `Node` has `status` and `role` which don't come from discovery — defaults would be used
- Tight coupling between discovery and core models

**Implications**:
- `code/projections.py` deleted
- `code/discovery.py` returns `Node` objects with default status/role
- `FileReconciler._reconcile_file` simplifies (no projection step)
- Bundle provisioning moves to reconciler or a post-discovery hook

**Opportunities**: A single type simplifies serialization, debugging, and the mental model.

---

## 22. Web Server as Thin Read Model

**Current state**: The web server directly queries `NodeStore` and `EventStore` to serve API responses. It also writes to `EventStore` via the chat endpoint. There's no separation between read and write paths.

**Proposal**: The web server operates on a read-only view, with writes going through commands:

- **Read path**: Web server queries a read-optimized view (could even be a separate SQLite database or in-memory cache)
- **Write path**: Chat messages go through a `CommandBus` that validates and routes to the event store

**Pros**:
- Web server can't corrupt system state
- Read path can be optimized independently (denormalized views, caching)
- Clear security boundary — web endpoints are read-only by default
- Enables eventual consistency with faster reads

**Cons**:
- CQRS adds architectural complexity
- For a local-only tool, the security benefits are marginal
- Read/write separation requires synchronization logic

**Implications**:
- `create_app` takes a read-only store interface
- Chat endpoint goes through a `ChatCommand` that the runtime processes
- SSE stream comes from the EventBus (already working this way)

**Opportunities**: The read model could power a React/Vue frontend with optimistic updates, where the write path is async.

---

## 23. Plugin-Based Language Support via Entry Points

**Current state**: `LanguageRegistry` has hardcoded `BUILTIN_PLUGINS` list with Python, Markdown, and TOML. Adding a new language requires modifying `languages.py` and adding a new tree-sitter dependency.

**Proposal**: Use Python entry points (or a plugin directory) for language plugins:

```toml
# In a separate package:
[project.entry-points."remora.languages"]
javascript = "remora_js:JavaScriptPlugin"
rust = "remora_rust:RustPlugin"
```

```python
class LanguageRegistry:
    def __init__(self):
        for ep in entry_points(group="remora.languages"):
            plugin = ep.load()()
            self.register(plugin)
```

**Pros**:
- New languages can be added without modifying remora core
- Community-contributed language plugins
- Each language plugin is an independent package with its own tree-sitter dependency
- Core remora stays lean

**Cons**:
- Entry points are discovered at runtime — harder to debug missing plugins
- Plugin API must be stable (breaking changes affect all plugins)
- Packaging complexity for each language plugin

**Implications**:
- `tree-sitter-python`, `tree-sitter-markdown`, `tree-sitter-toml` move to optional dependencies
- `PythonPlugin`, `MarkdownPlugin`, `TomlPlugin` move to a `remora-builtin-languages` package (or stay as default)
- `LanguageRegistry` loads plugins from entry points

**Opportunities**: Enables specialized discovery for non-code content: YAML configs, Dockerfiles, SQL schemas, etc.

---

## 24. Workspace File Operations as Async Generators

**Current state**: `search_content` in `TurnContext` loads all file paths, then reads each file sequentially. For large workspaces, this is O(N*M) with all content loaded into memory.

**Proposal**: Use async generators for streaming file operations:

```python
async def search_content(self, pattern: str, path: str = ".") -> AsyncIterator[SearchResult]:
    async for file_path in self.workspace.walk(path):
        async for line_num, line in self.workspace.read_lines(file_path):
            if pattern in line:
                yield SearchResult(file=file_path, line=line_num, text=line)
```

**Pros**:
- Memory efficient — doesn't load entire workspace into memory
- Results stream as they're found
- Enables early termination (stop after N results)

**Cons**:
- Grail tools expect return values, not generators — would need `collect()` adapter
- More complex API surface
- May be premature optimization for typical workspace sizes

**Implications**:
- `AgentWorkspace` gains streaming read/walk methods
- `TurnContext.search_content` returns results lazily
- Grail tools use `collect(search_content(...))` to get list results

**Opportunities**: Streaming results enable real-time progress reporting during long searches.

---

## 25. Global Error Taxonomy

**Current state**: Error handling uses broad `except Exception` catches at system boundaries with `# noqa: BLE001` annotations. Errors are logged and either swallowed (in actors) or returned as strings (in tools).

**Proposal**: Define a hierarchy of domain-specific exceptions:

```python
class RemoraError(Exception): pass
class NodeNotFoundError(RemoraError): pass
class TurnExecutionError(RemoraError): pass
class ToolExecutionError(RemoraError): pass
class StoreError(RemoraError): pass
class WorkspaceError(RemoraError): pass
class DiscoveryError(RemoraError): pass
```

**Pros**:
- Catch-clauses can be precise: `except ToolExecutionError` instead of `except Exception`
- Error types carry semantic meaning for logging and metrics
- Enables structured error responses to the LLM (not just string dumps)
- Linter-friendly (no more `# noqa: BLE001`)

**Cons**:
- Exception hierarchies can become overly detailed
- External library exceptions (aiosqlite, Grail, structured-agents) still need broad catches at boundaries
- Adds boilerplate for raising custom exceptions

**Implications**:
- Store methods raise `StoreError` instead of propagating raw aiosqlite exceptions
- `GrailTool.execute` catches `ToolExecutionError` specifically, then `Exception` for unexpected errors
- `Actor._execute_turn` catches `TurnExecutionError` for expected failures
- Error events carry structured error types

**Opportunities**: Structured errors enable automated error recovery — e.g., a `NodeNotFoundError` during a turn could trigger re-discovery rather than failing silently.

---

## Summary Matrix

| # | Idea | Complexity | Impact | Dependencies |
|---|------|-----------|--------|-------------|
| 1 | Unify Node/Agent status | Low | High | None |
| 2 | Transaction/UoW pattern | Medium | High | None |
| 3 | Decompose FileReconciler | High | High | None |
| 4 | Capability groups for TurnContext | Medium | Medium | Grail changes |
| 5 | BundleConfig Pydantic model | Low | Medium | None |
| 6 | Event envelope type | Low | Medium | None |
| 7 | Protocol-based stores | Medium | Medium | None |
| 8 | Merge Node/Agent tables | Low | High | #1 |
| 9 | Actor → Actor + TurnExecutor + Policy | Medium | High | None |
| 10 | Grail tool descriptions | Low | High | Grail changes |
| 11 | Async file I/O | Low | Low | None |
| 12 | Subscription matching on envelope | Low | Medium | #6 |
| 13 | Explicit cache invalidation | Medium | Low | None |
| 14 | Eliminate DiscoveredElement | Trivial | Low | None |
| 15 | Actor inbox back-pressure | Medium | Medium | None |
| 16 | Directory nodes as projections | High | Medium | #3 |
| 17 | Configuration-driven prompts | Medium | Medium | #5 |
| 18 | Explicit DI over service locator | Medium | Low | None |
| 19 | Outbox protocol | Low | Low | None |
| 20 | Idempotent event processing | High | Medium | None |
| 21 | Collapse CSTNode/Node pipeline | Medium | Medium | None |
| 22 | Web server as read model | Medium | Low | None |
| 23 | Plugin-based language support | Medium | Medium | None |
| 24 | Streaming workspace ops | Medium | Low | None |
| 25 | Global error taxonomy | Medium | Medium | None |

### Recommended Execution Order

**Phase 1 — Quick wins with high impact** (can be done independently):
1. #1/#8: Merge Node/Agent (eliminates #1 design smell)
2. #5: BundleConfig model
3. #14: Delete DiscoveredElement
4. #19: Outbox protocol + move RecordingOutbox to tests
5. #10: Tool descriptions (if Grail supports it)

**Phase 2 — Structural improvements**:
6. #6: Event envelope type
7. #12: Subscription matching on envelope
8. #2: Transaction/UoW pattern
9. #9: Actor decomposition (Actor + TurnExecutor + Policy)

**Phase 3 — Architectural evolution**:
10. #3: Decompose FileReconciler
11. #16: Directory nodes as projections
12. #4: Capability groups for TurnContext
13. #17: Configuration-driven prompts
14. #25: Global error taxonomy

**Phase 4 — Forward-looking**:
15. #7: Protocol-based stores
16. #15: Inbox back-pressure
17. #20: Idempotent event processing
18. #23: Plugin-based language support
