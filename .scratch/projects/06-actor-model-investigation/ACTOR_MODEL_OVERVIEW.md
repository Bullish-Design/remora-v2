# Actor Model Overview for remora-v2 (R27 Investigation)

## 1. Executive Summary

R27 recommends replacing the current centralized trigger orchestration (`TriggerDispatcher -> AgentRunner.trigger() -> create_task(_execute_turn)`) with per-agent actors that self-schedule and process one message at a time.

For `remora-v2`, this is a strong fit if implemented incrementally. The existing architecture already has event fan-out (`EventStore` + `TriggerDispatcher`) and per-agent identity (`AgentStore`, subscriptions, workspace roots), which are the hard prerequisites for an actor runtime.

The most practical path is an **actor-lite in-process model** first:
- Keep current SQLite/EventStore and subscription matching.
- Replace `AgentRunner`'s global cooldown/depth maps and fire-and-forget tasks with per-agent mailbox workers.
- Add supervisor + mailbox backpressure policies.

This preserves current behavior while improving isolation, lifecycle control, and testability.

## 2. Current Runtime Flow (Today)

### 2.1 Trigger Path

Current flow in runtime code:
1. `EventStore.append(event)` persists event, emits on `EventBus`, then dispatches via `TriggerDispatcher`.
2. `TriggerDispatcher.dispatch` resolves matching agent IDs using `SubscriptionRegistry` and enqueues `(agent_id, event)` in one global queue.
3. `AgentRunner.run_forever` consumes queue entries and calls `trigger(node_id, correlation_id, event)`.
4. `AgentRunner.trigger`:
   - checks global cooldown (`self._cooldowns[node_id]`),
   - checks global depth (`self._depths[f"{node_id}:{correlation_id}"]`),
   - launches `asyncio.create_task(self._execute_turn(...))`.
5. `_execute_turn` handles full turn lifecycle, tool execution, event emission, and status reset.

### 2.2 Strengths of Current Design

- Clear event-driven entrypoint via `EventStore` and subscriptions.
- Single turn implementation (`_execute_turn`) is already cohesive and reusable.
- Existing status transitions in `AgentStore`/`NodeStore` provide guardrails.

### 2.3 R27 Pain Points in Current Design

- Global mutable coordination state in runner (`_cooldowns`, `_depths`).
- Fire-and-forget `create_task` makes lifecycle and shutdown harder to reason about.
- Per-agent sequencing relies on status transitions and semaphore, not mailbox ownership.
- Harder to isolate per-agent failure/backpressure behavior without coupling all agents in runner logic.

## 3. Proposed Actor Model for remora-v2

## 3.1 Core Concept

Each agent (`agent_id == node_id`) becomes an actor with:
- its own mailbox (`asyncio.Queue`),
- its own trigger policy state (cooldown, depth map, retries),
- exactly one sequential processing loop,
- local lifecycle management (`idle/running/error`) with store synchronization.

The runner becomes an actor system/dispatcher rather than a centralized executor.

## 3.2 Suggested Components

### `ActorSystem` (new)

Responsibilities:
- Maintain actor registry: `agent_id -> AgentActor`.
- Create actors lazily on first trigger or eagerly on discovery.
- Route trigger messages from `TriggerDispatcher` to target actor mailboxes.
- Track actor tasks for graceful shutdown.
- Apply global policies (max actors, telemetry hooks).

### `AgentActor` (new)

Responsibilities:
- Own `mailbox` and per-agent state.
- Process one message at a time.
- Execute turn logic (reuse most of current `_execute_turn` internals).
- Emit events and sync status via `AgentStore`/`NodeStore`.
- Enforce cooldown/depth locally.

### `ActorSupervisor` (new, optional but recommended)

Responsibilities:
- Observe actor crashes.
- Restart with backoff policy.
- Route failed messages to dead-letter stream/event.

### `RunnerFacade` (compatibility layer)

Responsibilities:
- Keep `run_forever()`/`stop()` public API stable initially.
- Internally delegate to `ActorSystem`.

## 3.3 Message Model

Define explicit actor messages (instead of passing raw events directly):
- `TriggerMessage(event, correlation_id, received_at)`
- `StopMessage(reason)`
- `SyncStatusMessage(status)` (optional)
- `FlushMessage` (for tests/drain)

Message envelopes can include metadata for tracing:
- `trace_id`, `source_component`, `attempt`, `deadline_ms`.

## 3.4 Event-to-Actor Routing

The existing dispatcher remains useful:

```text
EventStore.append -> TriggerDispatcher.dispatch -> ActorSystem.route(agent_id, event)
```

No immediate need to replace `TriggerDispatcher`; only change the sink from centralized runner trigger checks to per-actor mailbox enqueue.

## 4. How This Fits Existing remora-v2 Modules

## 4.1 `src/remora/core/runner.py`

Current `AgentRunner` can be split into:
- orchestration moved to `ActorSystem`,
- turn execution logic moved to `AgentActor._execute_turn` (or shared `TurnExecutor`).

Minimal-risk refactor:
- Keep `Trigger` dataclass and prompt/tool execution helpers.
- Extract `_execute_turn` into reusable class/service first.
- Then switch caller from `create_task` in runner to actor worker loop.

## 4.2 `src/remora/core/events/dispatcher.py`

No contract change required for phase 1:
- `get_triggers()` still yields `(agent_id, event)`.
- Consumer becomes `ActorSystem.run_forever`.

Later option:
- Replace global queue with direct routing callback to reduce one queue hop.

## 4.3 `src/remora/core/services.py`

`RuntimeServices` becomes the clean place to inject:
- `ActorSystem`,
- optional `ActorSupervisor`,
- actor metrics collector.

`services.runner` can stay as public field but point to actor-backed facade during migration.

## 4.4 `src/remora/code/reconciler.py`

Reconciler already creates/removes agent rows via discovery events. Actor model can hook here:
- On `NodeDiscoveredEvent`: optionally prewarm actor.
- On `NodeRemovedEvent`: stop actor and drain mailbox.

This creates tighter lifecycle coupling between graph state and runtime workers.

## 5. Reference Execution Flow Under Actor Model

```text
append(event)
  -> persist event
  -> emit bus subscribers
  -> match subscriptions
  -> for each target agent_id: actor_system.enqueue(TriggerMessage)

actor(agent_id) loop:
  msg = mailbox.get()
  if cooldown/depth reject: drop or defer + emit optional diagnostic
  else:
    transition status running
    execute turn (tools/kernel/events)
    transition status idle/error
```

Key behavior shift: all per-agent sequencing and policy checks live with the actor.

## 6. Pros, Cons, Implications, Opportunities

## 6.1 Pros

1. **Per-agent isolation**
- Failures, queue growth, and retries become local to one actor.

2. **Sequential processing guarantee per agent**
- One mailbox + one worker naturally enforces no concurrent turns for same agent.

3. **Better lifecycle control**
- Actor tasks are tracked objects, not unmanaged fire-and-forget calls.

4. **Policy locality**
- Cooldown/depth/backoff logic sits where it belongs (agent runtime), reducing global mutable maps.

5. **Testability**
- Actor behavior can be unit-tested with synthetic mailbox messages and deterministic assertions.

6. **Future scaling path**
- Actor boundary aligns with potential future sharding/distribution (if needed later).

## 6.2 Cons

1. **Higher runtime complexity**
- Adds actor registry, lifecycle semantics, supervision, and mailbox policy decisions.

2. **Potential memory overhead**
- Many discovered nodes may imply many actor objects/queues unless actors are lazily created/evicted.

3. **Operational surface area increases**
- Need metrics and introspection to debug queue states and actor health.

4. **Migration risk**
- Touches execution core; subtle behavior changes (ordering, cooldown semantics) can regress if not phased.

5. **Not a silver bullet for throughput**
- Sequential per-agent processing can still bottleneck chatty agents; global semaphore concerns shift but do not disappear.

## 6.3 Implications

1. **Ordering semantics become explicit**
- Per-actor ordering is strong; cross-actor global order remains eventual/non-deterministic.

2. **Backpressure policy becomes mandatory**
- Need bounded mailbox size and overflow behavior:
  - reject new,
  - drop oldest,
  - coalesce redundant `ContentChangedEvent` messages.

3. **Status transitions should stay store-backed**
- Actor local state should mirror `AgentStore`/`NodeStore`, not replace them.

4. **Shutdown semantics improve but must be defined**
- Decide whether stop drains mailboxes or cancels in-flight turns.

5. **Observability requirements increase**
- Add metrics like mailbox depth, turn latency, reject counts, restart counts.

## 6.4 Opportunities

1. **Coalescing noisy triggers**
- Actors can merge repeated file-change events before running expensive turns.

2. **Priority scheduling**
- Add priority mailbox classes (e.g., human chat > file sync noise).

3. **Adaptive cooldowns**
- Per-agent dynamic cooldown based on recent failures or token cost.

4. **Supervisor policies by node type**
- Different restart/backoff for `function` agents vs docs/table agents.

5. **Better dev UX tooling**
- Actor inspector endpoint: queue depth, last run, last error, last event type.

## 7. Recommended Migration Strategy (Incremental)

## Phase A: Extract Turn Execution Boundary

- Extract `_execute_turn` core into `TurnExecutor` service with same dependencies.
- Keep existing runner behavior intact.
- Add regression tests around turn lifecycle and status transitions.

## Phase B: Introduce `ActorSystem` Behind Runner Facade

- Implement actor registry + per-agent mailbox worker.
- Runner still consumes dispatcher queue but now calls `actor_system.enqueue(...)`.
- Preserve existing public APIs and event contracts.

## Phase C: Move Cooldown/Depth Into Actors

- Remove `_cooldowns` and `_depths` from centralized runner.
- Add actor-local equivalents.
- Add tests for per-agent cooldown/depth and correlation propagation.

## Phase D: Add Backpressure + Supervision

- Make mailbox bounded.
- Add overflow policy (start with reject + diagnostic event).
- Add dead-letter event for dropped messages.
- Add supervisor restart with capped exponential backoff.

## Phase E: Lifecycle Hooks with Reconciler

- On node removal, stop actor and flush/drop mailbox explicitly.
- Optionally prewarm actors for newly discovered nodes.

## 8. Concrete Refactor Surface (Likely Files)

Potential additions:
- `src/remora/core/actors/messages.py`
- `src/remora/core/actors/agent_actor.py`
- `src/remora/core/actors/system.py`
- `src/remora/core/actors/supervisor.py`

Likely updates:
- `src/remora/core/runner.py` (facade + compatibility layer)
- `src/remora/core/services.py` (wire actor system)
- `src/remora/__main__.py` (startup naming/logging only)
- `src/remora/code/reconciler.py` (actor lifecycle hooks)

Test impact:
- New unit suite for actor behavior (`tests/unit/test_actor_system.py`, `test_agent_actor.py`).
- Existing runner tests can mostly migrate to facade compatibility tests.

## 9. Risks and Mitigations

1. **Risk: behavior drift during migration**
- Mitigation: keep runner facade and feature flag (`use_actor_runtime`) for staged rollout.

2. **Risk: too many idle actors**
- Mitigation: lazy creation + idle eviction timeout.

3. **Risk: mailbox overflow under event storms**
- Mitigation: bounded queues + coalescing + metrics alerts.

4. **Risk: hard-to-debug distributed style complexity in one process**
- Mitigation: strict scope: in-process actors only, no remote transport in initial rollout.

## 10. Recommendation for remora-v2

Recommended decision: **Proceed with actor-lite refactor, but only through Phases A-C first**.

Rationale:
- Captures the highest-value benefits (local state, sequential processing, managed lifecycle).
- Minimizes destabilization by preserving current EventStore/subscription contracts.
- Creates a foundation for supervision/backpressure as a second wave, based on observed runtime behavior.

Pragmatic threshold before full adoption:
- actor-backed runtime passes all existing runner/reconciler integration tests,
- no regression in end-to-end flow,
- clear observability for mailbox depth and turn errors.

---

This investigation aligns with R27 and suggests a concrete migration path that keeps remora-v2 stable while moving to a cleaner per-agent execution model.
