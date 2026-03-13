# Concept Refined: AgentNode-Centric Runtime

## Core Position
Remora is AgentNode-centric, not user-centric.

A `user` is one event source among many. The system should optimize for durable node expertise and autonomous graph-aware operation, with user interaction as a supported channel, not the organizing principle.

## Refinement Summary

- Keep one core AgentNode concept.
- Keep event-driven actor execution.
- Keep Grail tools as primary source of agent functionality.
- Treat chat as standard event traffic.
- Use `user` terminology (not `human`).
- Make response behavior depend on trigger event type.
- Keep strict tool schemas and fail-fast validation.

## Identity of an AgentNode
Each AgentNode is a long-lived subject matter expert for a single CST node.

Baseline role statement:

> You are a subject matter expert for this CST node in a {filetype} source tree. Maintain accurate understanding of your own node, its subtree relationships, and cross-node interactions in the project graph.

## Event Model (User as Peer Source)

`user` events should flow through the same dispatch path as any other sender.

Preferred shape:

- `AgentMessageEvent(from_agent="user", to_agent=<node_id>, content=<message>)`

Implication:

- No separate conceptual lane for chat transport.
- One delivery/trigger mechanism for all interactive and autonomous stimuli.

## Trigger Semantics

The agent should process all triggers, but not always produce conversational prose.

### Mode by Event Type

- `AgentMessageEvent` where `from_agent == "user"`
  - Mode: `chat`
  - Behavior: produce user-facing response and optional state update.

- `NodeChangedEvent`, `ContentChangedEvent`
  - Mode: `reactive`
  - Behavior: update internal state, run tools if needed, emit structured results; no default narrative response.

- `AgentMessageEvent` from non-user agents
  - Mode: `coordination`
  - Behavior: concise machine-usable acknowledgment or action event.

## Internal State is Primary

Every turn should first be interpreted as a potential state transition.

Minimum persistent state domains per AgentNode:

- `identity`: node metadata and scope boundaries.
- `topology`: parent/children/sibling/related nodes.
- `knowledge`: observed facts and verified relationships.
- `work`: pending and active tasks.
- `evidence`: recent tool outputs and event references.
- `health`: confidence, stale markers, last refresh.

User response quality should derive from this maintained state, not from ad hoc one-shot prompt context.

## Prompting Policy

Prompt construction should include explicit mode and intent.

- `chat` mode prompt: explain/answer/action for user.
- `reactive` mode prompt: analyze/update/emit structured outcome.
- `coordination` mode prompt: interpret peer message and decide next event/action.

This avoids repeating generic directory explanation text on non-user triggers.

## Tool Contract Policy

Strict contracts remain mandatory.

- Invalid enum inputs must fail fast.
- Improve tool guidance/examples so model uses valid values intentionally.

## Why This Better Fits the Core Concept

- Preserves agent autonomy and graph semantics.
- Reduces noisy user-style outputs from system-triggered turns.
- Makes user interaction a first-class capability without making it the system center.
- Supports future evolution toward richer autonomous behaviors without changing the conceptual core.

## Success Signals

- File-change triggers no longer generate default conversational summaries.
- Directory and file agents still maintain accurate subtree/project understanding.
- User messages receive better, state-grounded responses.
- Event logs show clear distinction between `chat`, `reactive`, and `coordination` behaviors.

## Naming and Language Standard

Use `user` consistently in:

- event source naming
- docs and prompts
- examples and tests

Avoid `human` terminology going forward except for backward compatibility references.

## Appendix A: Ethos-Aligned Minimal Shape (No Class Explosion)

This appendix is the pragmatic alignment layer: keep Remora simple, event-native, and tool-driven.

### A1. What to Keep

- One AgentNode model.
- One actor loop.
- One event pipeline.
- Strict schemas and fail-fast validation.

No deep class hierarchy is required to get the behavior we want.

### A2. What to Change

- Treat `user` interaction as standard event traffic.
- Stop requiring prose outputs for every non-user trigger.
- Add a direct, explicit tool for user-directed replies.

### A3. User Reply as a Grail Tool

Yes: make "send message to user" a Grail tool.

Conceptually:

- Tool name: `send_message_to_user`
- Inputs:
  - `content: str`
  - `channel: str | None` (optional, for UI routing)
- Implementation behavior:
  - emits an event intended for UI/user sink (for example `AgentMessageEvent(from_agent=<node_id>, to_agent="user", content=...)` or a dedicated `AgentUserMessageEvent`)

Why this aligns:

- Keeps user output explicit and intentional.
- Avoids conflating internal reactive turns with chat responses.
- Uses the same event/tool primitives Remora already has.

### A4. Turn Policy (Minimal)

- On `AgentMessageEvent(from_agent="user")`:
  - agent may call `send_message_to_user`.
- On `NodeChangedEvent` / `ContentChangedEvent`:
  - default to internal state/tool work only.
  - no automatic user-facing message unless policy says otherwise.
- On peer agent messages:
  - produce machine-coordination events/messages.

This can be implemented with a small policy gate, not a new type system.

### A5. Recommended Prompt Contract

Use one compact instruction set:

- "You are a node expert. Maintain node/subtree/project understanding."
- "User messaging is explicit: call `send_message_to_user` when a user-facing reply is warranted."
- "For reactive system events, prioritize state updates and coordination over narrative output."

### A6. Observable Outcomes

- Fewer noisy directory summaries after file changes.
- Cleaner logs separating internal work from user replies.
- Better operator control: if a user reply happened, it was explicitly emitted.

### A7. Why This Is the Right Level of Change

- Preserves Remora's existing ethos: event-driven, composable primitives, incremental evolution.
- Avoids overengineering with class-heavy architecture.
- Delivers the behavioral correction you want with minimal surface area.
