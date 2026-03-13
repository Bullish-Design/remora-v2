# Concept Overview: Pydantic-First AgentNode Rewrite

## Vision
Rebuild Remora around typed, polymorphic AgentNodes where each node class owns its behavior, state model, and trigger policy.

The system is AgentNode-centric:
- Nodes are durable experts over a CST graph.
- User chat is one event source, not the control center.
- Internal state transitions are the primary output of runtime activity.

## Core Architectural Shift
Current-style centralized branching by `node_type` is replaced with subclass polymorphism.

### Proposed Model Hierarchy

- `AgentNode` (abstract base)
  - Shared identity, lifecycle, state envelope, event hooks.
- `DirectoryAgentNode`
  - Subtree topology, rollups, parent/child coordination.
- `FileAgentNode`
  - File-level semantic map and cross-symbol dependency context.
- `FunctionAgentNode`
  - Symbol-level intent, contracts, call impact, local rewrite plans.
- `ClassAgentNode`
  - API surface, methods, invariants, collaboration edges.

Each subclass has a dedicated `StateModel` and `plan_turn(event)` implementation.

## State-First Runtime
Every trigger produces a state decision first.

Turn contract:
1. Load current node state.
2. Run `plan_turn(event)` on subclass.
3. Execute tools/actions from returned plan.
4. Apply validated state delta.
5. Emit structured events.
6. Optionally emit user-facing response only when policy allows.

## Event Modes
Mode is derived from event source/type.

- `chat` mode: user message events.
- `reactive` mode: content/node change events.
- `coordination` mode: inter-agent message events.
- `maintenance` mode: periodic self-check/refresh.

Default policy:
- Non-chat modes do not emit conversational prose unless explicitly configured.

## Pydantic Design Patterns

- Use discriminated unions for node deserialization (`kind` discriminator).
- Use strict state models per subclass.
- Use validated `TurnPlan` and `StateDelta` models.
- Use typed tool input/output models per node class.

This makes behavior explicit and rejects malformed runtime data early.

## Runtime Components (Greenfield)

- `NodeRegistry`
  - Maps `kind` to concrete AgentNode subclass.
- `NodeRuntime`
  - Executes turn lifecycle with typed plans/deltas.
- `StateStore`
  - Versioned snapshots + event-linked deltas.
- `ProjectionEngine`
  - Builds query views from state/events.
- `PolicyEngine`
  - Global and per-class rules for turn/output behavior.

## Storage/Posture

Two viable storage approaches:

1. Event-sourced canonical state with projection tables.
2. Snapshot-first state table with append-only audit events.

For a rewrite, option 1 gives strongest replayability and observability.

## Opportunities Opened by Subclassing

- True polymorphic behavior instead of node-type if/else chains.
- Strongly typed state invariants per node kind.
- Cleaner tool surface specialization by node class.
- More predictable testing at class boundaries.
- Better plugin path for future node kinds.

## Risks

- Higher initial complexity (registry, unions, serializers).
- Migration cost from existing schema/runtime.
- Need disciplined shared contracts to avoid subclass drift.

## Success Criteria

- File/system events update state without chat noise.
- User questions are answered from maintained node state.
- Node-specific behavior is implemented via subclass methods, not centralized branching.
- Runtime traces show deterministic plan -> action -> state-delta flow.

## First Implementation Slice (If Proceeding)

1. Build base `AgentNode`, `TurnPlan`, `StateDelta` models.
2. Implement `DirectoryAgentNode` and `FunctionAgentNode` only.
3. Replace one end-to-end trigger path (`ContentChangedEvent`) with typed runtime.
4. Add event+state trace inspection endpoint.
5. Expand subclass coverage incrementally.
