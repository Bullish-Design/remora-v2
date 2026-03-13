# Concept Refined: AgentNode-Centric Runtime

## Core Position
Remora is AgentNode-centric, not user-centric.

A `user` is one event source among many. The system should optimize for durable node expertise and autonomous graph-aware operation, with user interaction as a supported channel, not the organizing principle.

## Refinement Summary

- Keep one core AgentNode concept.
- Keep event-driven actor execution.
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
- Do not coerce invalid values (for example, `"all"` for `node_type`).
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
