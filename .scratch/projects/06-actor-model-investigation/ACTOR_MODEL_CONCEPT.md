# Actor Model Concept for remora-v2

## 1. Core Thesis

The actor model for remora is not a new system layered on top of the existing architecture. It is a **reconceptualization of existing components** with two concrete structural changes:

1. **Inbox**: Replace the single global queue in `TriggerDispatcher` with per-agent queues.
2. **Outbox**: Replace direct `EventStore.append()` calls from agents with a scoped write-through emitter that tags events with actor metadata and provides a policy interception point.

The EventStore remains the single source of truth. The EventBus remains the broadcast mechanism for non-actor consumers. Subscriptions remain the routing table. No parallel messaging system is introduced.

## 2. Design Decisions

These decisions were made through analysis of the existing codebase and its trajectory:

| Decision | Choice | Rationale |
|---|---|---|
| Actor scope | Every discovered node | Remora treats each code element as an autonomous agent; the model should match |
| Actor lifecycle | Lazy creation, idle eviction | Hundreds of nodes in a typical project; can't keep all in memory permanently |
| State persistence | Cairn workspace (filesystem + KV) | Agents already use Cairn workspaces; safe to evict and recreate actors since state lives in workspace |
| Mid-turn event visibility | Yes, write-through | Agents produce events during tool execution that other agents should react to before the turn completes |
| Agent-to-agent routing | Always mediated via event stream | Gives audit trail, subscription matching, and policy interception without added complexity |
| External state access | Direct reads, mediated writes | LLM-driven agents read context and emit actions; reads don't need isolation, writes need mediation |
| API surface | Layered (internal default, reachable for power users) | Don't lock into actor APIs before validating; consumers use bundles/events/subscriptions as today |
| Ordering | Per-agent FIFO sufficient | Outbox events carry sequence numbers; global cross-agent ordering is eventual |

## 3. Why This Architecture

### 3.1 What the Actor Model Solves

**Per-agent comprehensibility at scale.** Every node is an actor. A medium codebase has hundreds of functions and classes. The current single-queue, single-consumer-loop architecture works at small scale but becomes hard to reason about when hundreds of agents are active simultaneously. Per-agent mailboxes make behavior decomposable: inspect one actor's inbox, outbox, and state in isolation.

**Managed lifecycle.** Today, `AgentRunner.trigger()` calls `asyncio.create_task()` (runner.py:112) with no handle tracking. Actor tasks are named, tracked objects. Shutdown means "drain all mailboxes" or "cancel all actors" rather than hoping all fire-and-forget tasks complete.

**The outbox as interaction boundary.** Today, agents call `event_store.append()` directly during tool execution via `AgentContext` (externals.py:98-105, 126-135, 172-181). There is no seam between "agent decided to do something" and "system committed that action." The outbox provides a point to intercept, validate, rate-limit, tag, and test agent output without touching agent code or EventStore internals.

**Per-agent policy locality.** Cooldowns (`_cooldowns`), cascade depth (`_depths`), and concurrency limiting (`_semaphore`) currently live as global mutable state on `AgentRunner` (runner.py:65-66). With actors, these policies move to where they belong: each agent's own runtime context.

### 3.2 What the Actor Model Does NOT Solve

- **LLM latency** is the dominant cost per turn. Actors don't make LLM calls faster.
- **Throughput** is still bounded by `max_concurrency` (the semaphore). Actors change who manages the limit, not the limit itself.
- **Discovery accuracy** (tree-sitter parsing, node detection) is independent of execution model.

The actor model is an orchestration improvement, not a performance improvement.

## 4. Architecture

### 4.1 The Event Stream as Spine

The EventStore (append-only SQLite log) is the central primitive. Everything else is derived from it:

```
                          EventStore
                       (append-only log)
                      /        |        \
                     /         |         \
              Subscriptions  EventBus   Persistence
              (routing       (non-actor  (SQLite +
               table)        broadcast)  indexes)
                |
                v
           Per-agent inboxes
          (materialized views
           of the event stream
           filtered by subscription)
```

- **Inbox** = subscription filter applied to event stream, materialized as an `asyncio.Queue` for each actor. The dispatcher performs this materialization.
- **Outbox** = the agent's write handle to the event stream, with automatic metadata tagging and policy interception. Write-through, not buffered.
- **Actor** = inbox consumer + turn executor + outbox producer. Processes one message at a time.
- **Router** = the component that materializes inboxes from the event stream. Today: `TriggerDispatcher` + `SubscriptionRegistry`. These stay as-is; only the sink changes from global queue to per-agent queues.

### 4.2 Current Flow vs. Actor Flow

**Current flow (runner.py):**

```
EventStore.append(event)
  -> EventBus.emit(event)                          # broadcast
  -> TriggerDispatcher.dispatch(event)              # subscription matching
     -> global_queue.put_nowait((agent_id, event))  # one queue for all

AgentRunner.run_forever():
  for agent_id, event in dispatcher.get_triggers(): # single consumer
    trigger(agent_id, correlation_id, event)
      -> check global _cooldowns dict
      -> check global _depths dict
      -> asyncio.create_task(_execute_turn(...))     # fire and forget
        -> acquire global _semaphore
        -> execute turn (LLM + tools)
        -> agent calls event_store.append() directly # no mediation
```

**Actor flow:**

```
EventStore.append(event)
  -> EventBus.emit(event)                           # broadcast (unchanged)
  -> TriggerDispatcher.dispatch(event)               # subscription matching (unchanged)
     -> find_or_create_actor(agent_id)
     -> actor.inbox.put_nowait(event)                # per-agent queue

AgentActor.run():
  for event in inbox:                                # per-agent consumer
    check local cooldown
    check local depth
    acquire concurrency permit
    execute turn (LLM + tools)
      -> agent calls outbox.emit(event)              # mediated write
        -> tag with actor_id, correlation_id, seq
        -> apply policies (rate limit, validation)
        -> EventStore.append(event)                  # write-through
```

The key structural changes are:
1. Dispatcher routes to per-agent queues instead of one global queue.
2. Each actor has its own processing loop instead of sharing the runner's loop.
3. Agent writes go through outbox (scoped emitter) instead of directly to EventStore.
4. Cooldown/depth/concurrency state moves from runner globals to per-actor locals.

### 4.3 Component Responsibilities

#### `AgentActor`

The core unit. One per active agent.

```
AgentActor
  inbox:    asyncio.Queue[Event]    # events routed by subscription match
  outbox:   Outbox                  # write-through emitter to event stream
  cooldown: float                   # last execution timestamp (ms)
  depths:   dict[str, int]          # cascade depth per correlation_id
  node_id:  str                     # identity
  task:     asyncio.Task | None     # managed processing loop
```

Responsibilities:
- Consume inbox events sequentially (one at a time).
- Apply per-agent trigger policies (cooldown, depth limiting).
- Execute turn logic (reuse current `_execute_turn` internals from runner.py).
- Emit events through outbox, never directly to EventStore.
- Sync status transitions via AgentStore/NodeStore.
- Self-report lifecycle state (idle/running/error).

The processing loop:

```python
async def run(self) -> None:
    while True:
        event = await self.inbox.get()
        if not self._should_trigger(event):
            continue
        try:
            self._status = "running"
            await self._execute_turn(event)
            self._status = "idle"
        except Exception:
            self._status = "error"
            await self.outbox.emit(AgentErrorEvent(...))
```

#### `Outbox`

A thin write-through emitter. Not a buffer — events reach EventStore immediately.

```
Outbox
  actor_id:       str               # owning actor
  correlation_id: str | None        # current turn's correlation
  sequence:       int               # monotonic per-actor counter
  event_store:    EventStore         # write target
  hooks:          list[OutboxHook]   # policy interception (optional)
```

Responsibilities:
- Auto-tag events with `actor_id`, `correlation_id`, and sequence number.
- Pass events through policy hooks (rate limiting, validation, filtering) before writing.
- Call `EventStore.append()` synchronously (from the caller's perspective).
- Provide test seam: swap implementation for a recording outbox in tests.

```python
class Outbox:
    async def emit(self, event: Event) -> int:
        self._sequence += 1
        # tag metadata
        if not event.correlation_id:
            event.correlation_id = self.correlation_id
        # policy hooks
        for hook in self._hooks:
            event = hook(event)
            if event is None:
                return -1  # filtered
        return await self._event_store.append(event)
```

Why write-through (not buffered):
- The user requires mid-turn event visibility — other agents must see events emitted during a turn, not just after it completes.
- Buffering creates flush timing decisions (how often? what triggers?) that add complexity without value for this use case.
- The outbox's value is as a **seam** (interception, tagging, testing), not as storage.
- If transactional semantics are needed later (e.g., discard all events on turn failure), the outbox implementation changes without changing agent code.

#### `AgentContext` Changes

`AgentContext` (externals.py) is the API surface agents use during turns. Under the actor model:

**Unchanged (direct reads):**
- `graph_get_node()`, `graph_query_nodes()`, `graph_get_edges()` — read from NodeStore directly
- `event_get_history()` — read from EventStore directly
- `get_node_source()` — read from NodeStore directly
- `read_file()`, `write_file()`, `list_dir()`, etc. — workspace access (always free)

**Changed (mediated writes):**
- `event_emit()` — calls `outbox.emit()` instead of `event_store.append()`
- `send_message()` — calls `outbox.emit(AgentMessageEvent(...))` instead of direct append
- `broadcast()` — calls `outbox.emit()` per target instead of direct append
- `apply_rewrite()` — calls `outbox.emit(ContentChangedEvent(...))` instead of direct append
- `event_subscribe()` / `event_unsubscribe()` — writes to subscription registry, mediated

**Rationale for direct reads:** Remora agents are LLM-driven. They read context, reason, and emit actions. They don't do tight read-modify-write cycles where stale reads cause data corruption. The node graph changes slowly (reconciler-driven, tied to file saves). Event history is append-only. Agent status is advisory. Read isolation adds latency and complexity for no practical benefit.

**Rationale for mediated writes:** Writes are side effects. They need to be tagged, tracked, interceptable, and testable. The outbox provides all of this without changing the agent's calling convention — `outbox.emit(event)` has the same signature as the old direct `event_store.append(event)`.

### 4.4 Router Changes (TriggerDispatcher)

The dispatcher's job stays the same: match events against subscriptions, route to targets. The only change is the sink.

**Current (dispatcher.py:19-22):**
```python
async def dispatch(self, event: Event) -> None:
    for agent_id in await self._subscriptions.get_matching_agents(event):
        self._queue.put_nowait((agent_id, event))  # one global queue
```

**Actor model:**
```python
async def dispatch(self, event: Event) -> None:
    for agent_id in await self._subscriptions.get_matching_agents(event):
        actor = self._actor_registry.get_or_create(agent_id)
        actor.inbox.put_nowait(event)  # per-agent queue
```

The `get_triggers()` async generator (dispatcher.py:24-27) is no longer needed — each actor consumes its own inbox. The runner's `run_forever()` loop (runner.py:68-78) simplifies to actor lifecycle management.

### 4.5 Runner Evolution

The `AgentRunner` becomes an actor registry and lifecycle manager rather than a centralized executor.

**Current responsibilities that move to `AgentActor`:**
- Cooldown checking (runner.py:88-97) → actor-local
- Depth tracking (runner.py:99-111) → actor-local
- Turn execution (runner.py:114-211) → actor-local (reuse most of the method body)
- Status transitions → actor-local

**Current responsibilities that stay on the runner:**
- `run_forever()` — now starts/manages actor tasks instead of consuming a global queue
- `stop()` — now signals all actors to drain and stop
- Concurrency limiting — the semaphore can stay global (shared across actors) or become a distributed permit system
- Actor registry — `dict[str, AgentActor]` with lazy creation and idle eviction

```python
class AgentRunner:
    def __init__(self, ...):
        self._actors: dict[str, AgentActor] = {}
        self._semaphore = asyncio.Semaphore(config.max_concurrency)

    def get_or_create_actor(self, node_id: str) -> AgentActor:
        if node_id not in self._actors:
            actor = AgentActor(
                node_id=node_id,
                outbox=Outbox(node_id, self._event_store),
                semaphore=self._semaphore,  # shared concurrency permit
                node_store=self._node_store,
                agent_store=self._agent_store,
                workspace_service=self._workspace_service,
                config=self._config,
            )
            actor.start()  # launches actor.run() as managed asyncio.Task
            self._actors[node_id] = actor
        return self._actors[node_id]

    async def evict_idle(self, max_idle_seconds: float = 300.0) -> int:
        """Stop actors that have been idle longer than threshold."""
        ...
```

### 4.6 Agent-to-Agent Interaction

All agent-to-agent communication is mediated through the event stream.

```
Agent A (turn executing)
  -> outbox.emit(AgentMessageEvent(from_agent=A, to_agent=B, content="..."))
    -> EventStore.append(...)
      -> TriggerDispatcher.dispatch(...)
        -> SubscriptionRegistry matches B's direct subscription
          -> actor_B.inbox.put_nowait(event)

Agent B (idle, waiting on inbox)
  -> inbox.get() yields the AgentMessageEvent
  -> B begins its turn
```

This is the same path as today, with two changes:
1. A writes through its outbox instead of calling `event_store.append()` directly.
2. The dispatcher routes to B's inbox queue instead of a global queue.

The audit trail is preserved (event is persisted in EventStore). Subscription matching still applies. The system can intercept at the outbox (A's output policy) or at the inbox (B's input policy, if added later).

### 4.7 Lifecycle Integration with Reconciler

The reconciler (reconciler.py) already emits `NodeDiscoveredEvent` and `NodeRemovedEvent`. These hook naturally into actor lifecycle:

**On `NodeDiscoveredEvent`:** No eager actor creation needed. Actors are created lazily on first trigger. The reconciler registers subscriptions as it does today — when an event later matches, the dispatcher calls `get_or_create_actor()`.

**On `NodeRemovedEvent`:** If an actor exists for the removed node:
1. Signal the actor to stop (cancel its processing loop).
2. Drain or discard remaining inbox messages.
3. Remove from the actor registry.
4. The reconciler already handles subscription cleanup and agent/node deletion from stores.

**Idle eviction:** Actors that haven't processed a message in a configurable period (e.g., 5 minutes) are stopped and removed from the registry. Their Cairn workspace persists on disk — if they're triggered again, a new actor is created and the workspace is reloaded. This keeps memory bounded for large codebases.

## 5. Concurrency Model

### 5.1 Per-Actor Sequential Processing

Each actor processes one inbox message at a time. This is the fundamental guarantee: no concurrent turns for the same agent. Today this is enforced implicitly by status transitions (IDLE -> RUNNING prevents a second trigger from starting). With actors, it's structural — one consumer loop, one message at a time.

### 5.2 Global Concurrency Limit

The semaphore (`max_concurrency`) remains a shared resource. Multiple actors can run simultaneously, up to the limit. The semaphore is acquired inside the actor's processing loop before turn execution, same as today (runner.py:119).

This means: many actors may be waiting on their inbox (cheap — just a coroutine suspended on `queue.get()`), but only N are actively executing turns at any time.

### 5.3 Actor Task Management

Each actor's `run()` coroutine is launched as a named `asyncio.Task`, held in the registry. This replaces the unnamed fire-and-forget `create_task` pattern. Benefits:
- Tasks can be cancelled individually (stop one agent without affecting others).
- Task names appear in asyncio debug output and exception tracebacks.
- Shutdown can `await asyncio.gather(*actor_tasks)` for clean drain.

### 5.4 Cascading and Depth Limiting

When agent A emits an event (through outbox) that triggers agent B, the event carries A's `correlation_id`. B's actor checks its local depth counter for that correlation_id. If depth exceeds `max_trigger_depth`, B emits an `AgentErrorEvent` and skips the turn.

This is the same logic as today (runner.py:99-111), but the depth map is per-actor instead of per-runner. Cross-agent cascades work because the correlation_id flows through the event stream — A's outbox tags it, EventStore persists it, B's inbox delivers it.

## 6. Outbox Policy Hooks

The outbox provides a hook mechanism for system-level policies. Hooks are functions that inspect or transform events before they reach EventStore. This is the primary extensibility point.

**Built-in hooks (future, not phase 1):**
- **Rate limiter** — cap events per actor per second. Protects against chatty agents flooding the event stream.
- **Validator** — reject malformed events or events targeting non-existent agents.
- **Coalescer** — merge repeated `ContentChangedEvent` for the same file path within a time window.
- **Metrics** — count events emitted per actor, per type.

**Hook interface:**
```python
class OutboxHook:
    async def process(self, event: Event, actor_id: str) -> Event | None:
        """Return the event (possibly modified) or None to filter it."""
        ...
```

Hooks are optional. Phase 1 ships with no hooks — the outbox is pure pass-through with metadata tagging. Hooks are added when observed runtime behavior justifies them.

## 7. Testability

The inbox/outbox boundary is the primary test seam.

### 7.1 Unit Testing an Actor

```python
# Create actor with recording outbox (no real EventStore)
outbox = RecordingOutbox()
actor = AgentActor(node_id="test_func", outbox=outbox, ...)

# Push a message into the inbox
await actor.inbox.put(ContentChangedEvent(path="src/foo.py", ...))

# Let actor process one message
await actor.process_one()

# Assert on outbox contents
assert len(outbox.events) == 2
assert outbox.events[0].event_type == "AgentStartEvent"
assert outbox.events[1].event_type == "AgentCompleteEvent"

# All events are tagged
assert all(e.correlation_id is not None for e in outbox.events)
```

### 7.2 Integration Testing Agent Interaction

```python
# Two actors with real EventStore but test LLM kernel
actor_a = create_test_actor("agent_a", event_store=store)
actor_b = create_test_actor("agent_b", event_store=store)

# A sends message to B
await actor_a.outbox.emit(AgentMessageEvent(
    from_agent="agent_a", to_agent="agent_b", content="review this"
))

# Event persisted and routed
await asyncio.sleep(0)  # yield for dispatch
assert actor_b.inbox.qsize() == 1
```

### 7.3 Compared to Current Testing

Currently, testing agent execution requires wiring up `EventStore`, `EventBus`, `TriggerDispatcher`, `SubscriptionRegistry`, `NodeStore`, `AgentStore`, `CairnWorkspaceService`, and `AgentRunner`. The actor boundary reduces the wiring surface — an `AgentActor` needs its inbox, outbox, workspace, and store access. The outbox can be swapped for a recorder. The inbox is just a queue you push to.

## 8. Observability

Per-actor state gives natural introspection points:

| Metric | Source | Value |
|---|---|---|
| Inbox depth | `actor.inbox.qsize()` | Backpressure signal per agent |
| Outbox event count | `actor.outbox.sequence` | Agent activity level |
| Last message received | Actor local timestamp | Idle eviction decision |
| Current status | Actor local state | Running/idle/error dashboard |
| Turn duration | Actor local timing | Performance profiling per agent |
| Cooldown rejects | Actor local counter | Noise detection |
| Depth limit hits | Actor local counter | Cascade detection |

These can be exposed via the existing web API or a future actor inspector endpoint. Today, none of this per-agent data is available without querying the event log.

## 9. Migration Strategy

### Phase 1: AgentActor + Outbox (Minimal Viable Actor Model)

**Goal:** Per-agent inboxes, write-through outbox, runner as registry. Existing tests pass.

**Changes:**
- New: `AgentActor` class with inbox queue, processing loop, local cooldown/depth.
- New: `Outbox` class (write-through, metadata tagging, no hooks yet).
- Modified: `TriggerDispatcher.dispatch()` routes to per-agent inboxes via actor registry.
- Modified: `AgentRunner` becomes actor registry with `get_or_create_actor()`, `evict_idle()`.
- Modified: `AgentContext` write methods use outbox instead of direct `event_store.append()`.
- Removed: Global `_cooldowns` and `_depths` dicts from runner.
- Removed: `get_triggers()` async generator pattern (each actor consumes its own inbox).

**Files likely touched:**
- `src/remora/core/runner.py` — refactor to actor registry
- `src/remora/core/externals.py` — wire write methods to outbox
- `src/remora/core/events/dispatcher.py` — route to per-agent queues
- New file: `src/remora/core/actor.py` — AgentActor + Outbox

**Validation:** All existing runner and reconciler tests pass. New unit tests for actor inbox/outbox behavior.

### Phase 2: Idle Eviction + Lifecycle Hooks

**Goal:** Bounded memory under large codebases. Clean actor-reconciler integration.

**Changes:**
- Idle eviction timer on runner (configurable threshold).
- Actor stop/cleanup on `NodeRemovedEvent`.
- Metrics collection for inbox depth and turn timing.

### Phase 3: Outbox Policy Hooks + Backpressure

**Goal:** Production hardening for sustained operation.

**Changes:**
- Bounded inbox queues with configurable overflow policy (reject + diagnostic event).
- Outbox rate limiting hook.
- Event coalescing for noisy file-change triggers.
- Dead-letter event for dropped messages.

### Phase 4: Supervision (If Warranted)

**Goal:** Automatic recovery from actor failures.

**Changes:**
- Supervisor component that observes actor crashes.
- Restart with capped exponential backoff.
- Per-node-type supervision policies (configurable via bundles).

Phase 4 is intentionally deferred. The current exception handling in `_execute_turn` (runner.py:186-211) already catches errors, emits `AgentErrorEvent`, and resets status. This is adequate for initial operation. Supervision is added when we observe failure patterns that justify it.

## 10. Risks and Mitigations

### Memory pressure from many actors

- **Risk:** Hundreds of actors, each with inbox queue + state + workspace handle.
- **Mitigation:** Lazy creation + idle eviction. Actors waiting on empty inboxes are lightweight (one suspended coroutine + one empty queue). Workspace handles are cached by `CairnWorkspaceService` and can be released on eviction.

### Outbox drain ordering fairness

- **Risk:** Outbox is write-through, so ordering depends on which actor calls `emit()` first. A burst of events from one actor could delay visibility of events from other actors at the EventStore level.
- **Mitigation:** Write-through means each `emit()` is an individual `EventStore.append()` call. There's no batching to create unfairness. The SQLite WAL + lock serializes writes, giving natural interleaving. Per-agent ordering is preserved by the outbox sequence number.

### Mid-turn cascading

- **Risk:** Agent A emits an event mid-turn that triggers Agent B, which emits an event that triggers A. A's first turn hasn't finished, so the new trigger waits in A's inbox. When A processes it, context may be stale.
- **Mitigation:** This exists today and is handled by depth limiting. The actor model makes it more visible (A's inbox has a queued message) but doesn't change the fundamental behavior. Depth limits cap the cascade.

### Behavior drift during migration

- **Risk:** Subtle ordering or timing changes between centralized and per-actor execution.
- **Mitigation:** Phase 1 preserves all existing event contracts and subscription semantics. The change is structural (who owns the queue) not behavioral (what triggers what). Existing integration tests validate the event flow end-to-end.

### Complexity budget

- **Risk:** Building actor infrastructure when the bottleneck is elsewhere (LLM latency, discovery accuracy).
- **Mitigation:** Phase 1 is deliberately small — one new file, three modified files. The actor boundary provides value even if we never build phases 3-4. If the complexity doesn't pay for itself after phase 1, we stop.

## 11. What This Does NOT Include

Decisions explicitly deferred:

- **Supervisor trees** — not until we observe failure patterns that justify restart policies.
- **Message envelope types** (`TriggerMessage`, `StopMessage`, etc.) — existing `Event` types are sufficient. The inbox receives `Event` objects, same as today.
- **Actor-level priority queues** — standard FIFO inbox until we observe starvation patterns.
- **Remote/distributed actors** — strictly in-process. No transport layer, no serialization boundaries.
- **Outbox buffering/transactions** — write-through only. Transactional semantics (rollback on failure) are a future option if needed.
- **Custom actor subclasses** — power users can reach into actor internals (layered API), but no public subclassing contract yet.
