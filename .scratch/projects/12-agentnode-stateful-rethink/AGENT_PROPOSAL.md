# AgentNode Rethink Proposal

## Executive Summary
The current runtime treats nearly every trigger as a request for a conversational completion. This causes directory agents to repeatedly produce explanatory prose when files change. The next iteration should make AgentNode behavior state-centric:

- Agents are long-lived subject matter experts for a specific CST node.
- Non-human triggers primarily update internal state and emit structured events.
- Human chat becomes one interaction channel that queries/uses that state.

Proposed core identity prompt for all nodes:

> You are a subject matter expert for the following node in a CST for a {filetype} file. Use your tools to better understand your own contents, how it interacts with related CST nodes in your subtree, and how it relates to the project graph.

## Problem Statement
Observed behavior today:

- `NodeChangedEvent` in a subtree triggers directory agents (`.` and nested directories).
- Triggered agents run a full model turn and often produce generic directory summaries.
- This creates noisy output and weak signal for autonomous operation.

Root causes:

- Trigger handling does not distinguish "state update" from "human response" mode.
- Directory prompts are static and generic for non-human triggers.
- There is no first-class internal state contract that each agent must maintain.

## Goals

- Make internal agent state the center of operation.
- Make non-human triggers produce structured state transitions, not chat-style narration.
- Preserve strict tool contracts and fail-fast validation.
- Improve graph awareness: node scope, subtree relationships, cross-node dependencies.
- Keep a clear migration path from current runtime.

## Non-Goals

- Removing LLM usage from the system entirely.
- Replacing the existing event store/actor runtime in one step.
- Introducing permissive input coercion that hides model mistakes.

## Required Behavior Shift

1. Agent role:
- From "chat responder for any trigger"
- To "stateful analyst/operator that can also answer chat"

2. Trigger semantics:
- Human trigger: produce user-facing response.
- System trigger: update state, optionally emit machine-readable events.

3. Output semantics:
- User-facing narrative is explicit and intentional.
- Internal work is represented as events/state deltas.

## Common State Model (Applies To All Options)

Each AgentNode keeps an internal state document (event-sourced or snapshot) with at least:

- `identity`: `node_id`, `node_type`, `file_path`, `language`, `bundle_name`
- `scope`: parent, children, sibling references, subtree summary hashes
- `observations`: recent facts from node/subtree/tool outputs
- `hypotheses`: inferred relationships or risk notes
- `tasks`: pending, in_progress, blocked, done
- `last_actions`: recent tool calls and outcomes
- `health`: confidence, stale flags, last refresh timestamp
- `chat_context`: optional user-facing context window metadata

## Trigger Policy Matrix (Target)

- `HumanChatEvent`
  - Action: reason over state + tools as needed
  - Output: user-facing response + optional state update
- `NodeChangedEvent` or `ContentChangedEvent`
  - Action: refresh facts, dependencies, and task queue
  - Output: state update event(s), no default chat narrative
- `AgentMessageEvent` from peers
  - Action: merge/update state and optionally ack with concise machine message
  - Output: structured inter-agent event
- Scheduled/internal maintenance trigger
  - Action: stale-state cleanup, summarization, confidence recalculation
  - Output: state maintenance event

## Option 1: Stateful Single-Loop Agent (Incremental)

### Description
Keep the current actor loop, but add a mode gate in turn execution:

- `mode=chat` for human events
- `mode=state_update` for system events

In `state_update` mode, agent does not emit chat prose by default. It writes internal state and emits structured events.

### Pros
- Minimal disruption to current architecture.
- Fastest path to reduce noisy directory narratives.
- Reuses existing actor/event infrastructure.

### Cons
- Chat and autonomous logic still share one execution lane.
- Prompt complexity grows because one agent prompt serves multiple modes.
- Harder long-term separation of concerns.

### Implications
- Need explicit turn policy in actor execution.
- Need new event type(s) for state change emissions.
- Need tests for "no narrative output on non-human trigger".

### Opportunities
- Quick quality win.
- Good stepping stone to stronger designs.

## Option 2: Dual-Lane AgentNode (Reactor + Chat Facade)

### Description
Split each agent into two internal capabilities:

- Reactor lane: event-driven state maintenance.
- Chat lane: user-facing conversational responses.

Both share a common state store. Reactor lane can run more frequently and cheaper; chat lane runs on demand.

### Pros
- Clear separation of autonomous behavior vs chat UX.
- Easier policy control and observability.
- Better fit for "chat is only one part" principle.

### Cons
- Higher implementation complexity.
- Requires more lifecycle/state synchronization code.
- More failure modes if lanes diverge.

### Implications
- Actor abstraction likely needs a lane-aware API.
- Metrics/logging must track lane-level execution.
- Bundle/tool configs may need lane-specific policy.

### Opportunities
- Strong foundation for robust autonomous agents.
- Easier to optimize cost/performance by lane.

## Option 3: Hierarchical Expert Network (Directory Supervisors)

### Description
Lean into directory nodes as supervisors:

- File/function/class nodes publish structured local insights.
- Directory nodes aggregate subtree state and compute rollups.
- Root project node focuses on repo-level topology and cross-domain concerns.

### Pros
- Natural mapping to tree structure.
- Better local-to-global reasoning flow.
- Reduces repeated broad queries from each node.

### Cons
- Requires coordination protocol between levels.
- Risk of stale rollups if child updates are delayed.
- More subscription and propagation rules to maintain.

### Implications
- Need explicit "upward summary" and "downward directive" events.
- Parent-child state contracts must be versioned.
- Directory bundle prompts/tools become supervisory and analytical.

### Opportunities
- Powerful project-level cognition model.
- Better support for repo entrypoint use case.

## Option 4: Deterministic State Projection + LLM Analyst

### Description
Move core node state updates into deterministic reducers/projections. LLM becomes an analyst/action suggester over projected state rather than primary state mutator.

### Pros
- Strongest reliability and auditability.
- Easiest to test and debug state transitions.
- Less model variability in operational behavior.

### Cons
- Largest redesign effort.
- Requires upfront schema and reducer design.
- Slower to deliver immediate improvements.

### Implications
- New state projection store and reducer pipeline.
- Existing prompts/tools must pivot to projection-aware behavior.
- Significant migration planning.

### Opportunities
- Enterprise-grade correctness and replayability.
- Excellent long-term maintainability.

## Side-by-Side Comparison

| Dimension | Option 1 | Option 2 | Option 3 | Option 4 |
|---|---|---|---|---|
| Time to value | Fast | Medium | Medium | Slow |
| Architectural change | Low | Medium | Medium/High | High |
| Noise reduction | High | High | High | High |
| Long-term scalability | Medium | High | High | Very High |
| Implementation risk | Low | Medium | Medium | High |

## Recommendation

Use a phased hybrid:

- Phase 1: Option 1 to immediately stop narrative output on non-human triggers and make state updates primary.
- Phase 2: Introduce Option 3 mechanics for directory supervisor behavior and subtree rollups.
- Phase 3: Evolve toward Option 2 lane separation where beneficial.
- Phase 4 (optional): adopt Option 4 deterministic projection model for high-assurance deployments.

This path gives immediate practical improvement without blocking on major rewrite.

## Concrete Policy Changes To Implement First

1. Turn policy gate:
- Non-human events default to `state_update` mode.
- Human events use `chat` mode.

2. Output gate:
- Only `chat` mode emits user-facing prose.
- `state_update` mode emits structured state events.

3. Prompt specialization:
- Prompt templates are mode-specific.
- Non-human mode prompt is analytical/action-oriented, not conversational.

4. Tool contract tightening:
- Keep strict enums and strict schemas.
- Add tool documentation/examples so model uses valid values and avoids `all`.

## Suggested New Event Types

- `AgentStateUpdatedEvent`: compact state delta and reason.
- `AgentInsightEvent`: structured insights with confidence.
- `AgentTaskQueuedEvent`: follow-up tasks generated from changes.
- `AgentTaskCompletedEvent`: completion with evidence/tool refs.

## Risks and Mitigations

- Risk: Silent behavior makes debugging harder.
  - Mitigation: verbose structured logs for state-mode turns.

- Risk: State drift over long sessions.
  - Mitigation: periodic consistency checks and confidence decay.

- Risk: Prompt/tool mismatch.
  - Mitigation: strict schema tests and runtime tool-call validation.

## Success Criteria

- File changes no longer produce repetitive conversational directory summaries by default.
- Directory nodes still maintain accurate subtree awareness.
- Human chat answers improve by referencing maintained internal state.
- Trigger-to-action behavior is predictable and test-covered.
