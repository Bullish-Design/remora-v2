# Approach Comparison: Inline Hooks vs Virtual Agent Observer

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Approach Overview: Recommended (Inline Post-Turn Hooks)](#2-approach-overview-recommended-inline-post-turn-hooks)
   - 2.1 How It Works
   - 2.2 Integration Points in Current Code
   - 2.3 New Code Required
3. [Approach Overview: Virtual Agent Observer (Approach A)](#3-approach-overview-virtual-agent-observer-approach-a)
   - 3.1 How It Works
   - 3.2 Integration Points in Current Code
   - 3.3 New Code Required
4. [Deep Comparison: Architecture](#4-deep-comparison-architecture)
   - 4.1 Coupling to Actor Internals
   - 4.2 Separation of Concerns
   - 4.3 Event System Leverage
5. [Deep Comparison: Operational Characteristics](#5-deep-comparison-operational-characteristics)
   - 5.1 Latency & Cost
   - 5.2 Concurrency Impact
   - 5.3 Failure Modes
   - 5.4 Resource Overhead
6. [Deep Comparison: Configurability & Extensibility](#6-deep-comparison-configurability-extensibility)
   - 6.1 Per-Bundle Configuration
   - 6.2 Adding New Hook Behaviors
   - 6.3 Cross-Agent Aggregation
7. [The Cross-Workspace Problem](#7-the-cross-workspace-problem)
   - 7.1 Why It Matters
   - 7.2 Solution Options for Approach A
   - 7.3 Impact on Architecture
8. [Hybrid Possibilities](#8-hybrid-possibilities)
   - 8.1 Inline Hooks for Per-Agent Memory + Observer for Cross-Agent
   - 8.2 Phased Rollout
9. [Recommendation & Trade-off Summary](#9-recommendation-trade-off-summary)
10. [Appendix A: First-Principles Redesign of the Observer](#appendix-a-first-principles-redesign-of-the-observer)
    - A.1 The v2 Ethos: What Are We Actually Building?
    - A.2 What the Observer Really Wants to Do
    - A.3 Existing Primitives We Haven't Fully Exploited
    - A.4 Design A: The Agent That Teaches Itself (Self-Directed Companion)
    - A.5 Design B: EventBus Listener + Direct KV (Non-Actor Observer)
    - A.6 Design C: Scoped Workspace Delegation (Sanctioned Cross-Write)
    - A.7 Design D: Event Enrichment Pipeline (No Observer At All)
    - A.8 Synthesis: What Aligns Best With v2?

---

## 1. Executive Summary

The companion system's core job is: after an agent completes an LLM turn, extract structured metadata (summary, tags, reflections, cross-node links) and persist it so the agent accumulates knowledge over time. Two viable approaches emerge from the brainstorming document:

**Recommended: Inline Post-Turn Hooks** — After `_complete_agent_turn()` in `AgentTurnExecutor`, fire a background `asyncio.create_task` that makes one LLM call to produce a `TurnDigest`, then writes the results to the agent's own workspace KV store. ~255 lines of new code, modifying `actor.py` and adding `core/hooks.py`.

**Approach A: Virtual Agent Observer** — Define a virtual agent in `remora.yaml` that subscribes to `AgentCompleteEvent`. When any agent finishes a turn, the event routes through the existing dispatch pipeline to the observer, which runs its own full actor turn to produce the digest. ~50 lines of new core code, plus a new bundle and system prompt.

The fundamental trade-off: **inline hooks are faster, simpler, and self-contained** but couple companion logic into the actor execution path. **The observer is more decoupled and naturally cross-agent**, but introduces latency, workspace access complications, and consumes concurrency slots.

This document analyzes both in detail against the actual remora-v2 codebase to inform the decision.

---

## 2. Approach Overview: Recommended (Inline Post-Turn Hooks)

### 2.1 How It Works

After the existing `_complete_agent_turn()` emits `AgentCompleteEvent`, a new code path checks bundle config for `post_turn.enabled`. If enabled, it spawns a background task:

```
execute_turn()
  → _run_kernel()            # existing: runs LLM turn
  → _complete_agent_turn()   # existing: emits AgentCompleteEvent
  → asyncio.create_task(     # NEW: fire-and-forget
      _run_post_turn_hooks(
          user_message, response_text, workspace, outbox, bundle_config
      )
    )
```

The hook makes a single LLM call (using a potentially different, cheaper model configured in `post_turn.model`) that returns structured JSON:

```json
{
  "summary": "Discussed null-input edge case in error handler",
  "tags": ["bug", "edge_case"],
  "reflection": "This function silently swallows FileNotFoundError",
  "links": ["test_error_handler"]
}
```

Results are written to the agent's own KV store under `companion/` keys, and a `TurnDigestedEvent` is emitted for downstream consumers.

### 2.2 Integration Points in Current Code

| File | What Changes | Why |
|------|-------------|-----|
| `core/actor.py` (`AgentTurnExecutor`) | Add `_run_post_turn_hooks()`, `_should_run_post_turn()`. Call after `_complete_agent_turn()` at line 372. | This is where the turn lifecycle lives. The hook runs inside the same `async with self._semaphore` block but as a detached task, so it doesn't block. |
| `core/actor.py` (`PromptBuilder`) | Add `_build_companion_context()` to inject accumulated companion memory into system prompts. | Agents need to see their accumulated knowledge. `PromptBuilder.build_system_prompt()` is the natural injection point. |
| `core/actor.py` (`AgentTurnExecutor._read_bundle_config`) | Parse `post_turn` section from bundle.yaml. | Currently only parses `system_prompt`, `model`, `max_turns`, `prompts`. Needs to also extract `post_turn` config. |
| `core/events/types.py` | Add `TurnDigestedEvent` | Downstream consumers (web UI SSE, other virtual agents) need notification that companion data was updated. |
| `web/server.py` | Add `GET /api/nodes/{node_id}/companion` endpoint | Web UI needs to read companion KV data for display. |

**New file:** `core/hooks.py` — Contains `TurnDigest` dataclass, `digest_turn()` (the LLM call), and `apply_turn_digest()` (the KV writes).

### 2.3 New Code Required

| Component | ~Lines | Complexity |
|-----------|--------|------------|
| `core/hooks.py` (TurnDigest, digest_turn, apply_turn_digest) | ~120 | Medium — LLM call with structured output parsing |
| `actor.py` changes (hook execution, companion context, config parsing) | ~80 | Low — wiring code, KV reads |
| `TurnDigestedEvent` | ~10 | Trivial |
| `web/server.py` endpoint | ~15 | Trivial — read KV, return JSON |
| Bundle config docs | ~20 | N/A |
| **Total** | **~255** | |

---

## 3. Approach Overview: Virtual Agent Observer (Approach A)

### 3.1 How It Works

A virtual agent is declared in `remora.yaml`:

```yaml
virtual_agents:
  - id: companion-observer
    role: companion
    subscriptions:
      - event_types: ["AgentCompleteEvent"]
```

The existing infrastructure handles everything:
1. `FileReconciler._sync_virtual_agents()` materializes this as a `VIRTUAL` node with subscriptions.
2. When any agent emits `AgentCompleteEvent`, `TriggerDispatcher.dispatch()` matches it against the observer's subscription.
3. `ActorPool._route_to_actor()` creates/retrieves the observer's Actor and puts the event on its inbox.
4. The observer Actor runs a full turn: reads the event payload, makes an LLM call via its system prompt + tools, writes the digest.

The observer's bundle would include a system prompt instructing it to extract metadata, plus Grail tools for writing to KV stores.

```
AgentCompleteEvent (from any agent)
  → EventStore.append()
  → TriggerDispatcher.dispatch()
  → SubscriptionRegistry.get_matching_agents() → ["companion-observer"]
  → ActorPool._route_to_actor("companion-observer", event)
  → Actor inbox → execute_turn()
  → LLM call (system prompt: "extract summary, tags, reflection, links")
  → Tool calls: write to originating agent's KV store
```

### 3.2 Integration Points in Current Code

| File | What Changes | Why |
|------|-------------|-----|
| `remora.yaml` | Add `companion-observer` virtual agent definition | Declarative — no code changes |
| `bundles/companion/bundle.yaml` | NEW: System prompt, model, tools config for the observer | Defines the observer's LLM behavior |
| `bundles/companion/tools/*.pym` | NEW: Grail tools for writing companion data | The observer needs to write to target KV stores |
| `core/externals.py` (`TurnContext`) | Add `kv_set_foreign(agent_id, key, value)` or similar cross-workspace method | **Critical:** The observer needs to write to OTHER agents' KV stores |
| `core/events/types.py` | Enrich `AgentCompleteEvent` with `user_message` field (currently only has `full_response`) | Observer needs both sides of the exchange |
| `web/server.py` | Add `GET /api/nodes/{node_id}/companion` endpoint | Same as inline — web UI needs the data |

### 3.3 New Code Required

| Component | ~Lines | Complexity |
|-----------|--------|------------|
| `remora.yaml` config addition | ~8 | Trivial |
| `bundles/companion/bundle.yaml` | ~30 | Medium — careful prompt engineering |
| `bundles/companion/tools/write_companion_data.pym` | ~30 | Low |
| Cross-workspace KV access in TurnContext | ~20 | **High** — breaks sandboxing model |
| `AgentCompleteEvent` enrichment | ~5 | Low |
| `web/server.py` endpoint | ~15 | Trivial |
| **Total** | **~108** | But high-impact changes |

---

## 4. Deep Comparison: Architecture

### 4.1 Coupling to Actor Internals

**Inline hooks:** Tightly coupled. The hook code lives inside `AgentTurnExecutor` and has direct access to `workspace`, `outbox`, `user_message`, and `response_text`. It reads bundle config that's already parsed. It writes to the same KV store the agent owns. This coupling is a *feature* — it's the simplest path from "turn complete" to "metadata persisted."

**Observer:** Loosely coupled. The observer knows nothing about `AgentTurnExecutor` internals. It receives an `AgentCompleteEvent` envelope and works from there. However, it needs `full_response` AND `user_message` on the event — currently `AgentCompleteEvent` only has `full_response` and `result_summary`. This means either:
- Enrich the event (adds data to every `AgentCompleteEvent` even when no observer exists)
- Have the observer query event history to reconstruct the user message (adds latency and complexity)

**Verdict:** Inline hooks have natural coupling that simplifies the code. The observer's loose coupling comes at the cost of needing richer events or event-history queries, plus the cross-workspace problem (Section 7).

### 4.2 Separation of Concerns

**Inline hooks:** Companion logic is distributed across `actor.py` (execution, config parsing) and `hooks.py` (the actual digest logic). This is two files in the core package — not a separate module. If companion behavior ever needs to diverge significantly between bundles, the inline approach makes it harder to customize (it's code, not config+prompt).

**Observer:** Companion logic lives entirely in a bundle directory. The system prompt, model choice, and tool behavior are all bundle-configurable. A different project could swap in a completely different companion bundle without touching core code. This is a genuinely powerful property — but only matters if companion behavior needs to vary significantly across deployments.

**Verdict:** Observer wins on separation of concerns. But the question is: does the companion system *need* that degree of configurability? The brainstorming doc suggests a fixed pipeline (summarize, tag, reflect, link) that's the same everywhere. If the behavior is fixed, the observer's flexibility is YAGNI.

### 4.3 Event System Leverage

**Inline hooks:** Partially uses the event system — emits `TurnDigestedEvent` for downstream consumers, but the hook itself runs outside the event pipeline. It's invoked directly, not through subscription matching.

**Observer:** Fully event-driven. Uses the complete pipeline: event emission → subscription matching → dispatch → inbox → turn execution. This means:
- The observer can be monitored via the same observability tools as any other agent (metrics, event history, web UI)
- The observer's execution is visible in the event stream (AgentStartEvent, AgentCompleteEvent for the observer itself)
- But: the observer's own `AgentCompleteEvent` could re-trigger itself (infinite loop) unless subscription patterns exclude self-events

**Infinite loop risk:** If `companion-observer` subscribes to `AgentCompleteEvent` and then emits its own `AgentCompleteEvent` when its turn completes, the dispatcher will route that event back to the observer. The subscription would need `from_agents` filtering to exclude itself — but `AgentCompleteEvent` doesn't have a `from_agent` field, it has `agent_id`. The subscription pattern matching code checks `getattr(event, "from_agent", None)` which won't match `agent_id`. So either:
- Add `from_agent` aliasing for `agent_id` in `AgentCompleteEvent`
- Use a `tags`-based filter
- Add custom logic to the subscription matcher

This is a real implementation complexity that the brainstorming doc doesn't address.

**Verdict:** Observer leverages the event system more fully, but introduces the self-trigger loop problem which requires careful handling.

---

## 5. Deep Comparison: Operational Characteristics

### 5.1 Latency & Cost

**Inline hooks:** The LLM call happens in a background task immediately after the turn. The call context is small (just user_message + response_text + a structured output prompt). Latency: whatever the LLM inference takes (likely 1-3 seconds with a small model). This runs concurrently with the next inbox event processing.

**Observer:** The event must traverse: EventStore.append → EventBus broadcast → TriggerDispatcher.dispatch → SubscriptionRegistry.get_matching_agents → ActorPool._route_to_actor → Actor inbox queue → wait for semaphore → _start_agent_turn → _prepare_turn_context (discover tools, build capabilities dict) → _build_system_prompt → PromptBuilder → create Messages → create_kernel → LLM call → extract response → _complete_agent_turn → emit events. This is a *full actor turn cycle*. Even if the LLM call is fast, the overhead of workspace setup, tool discovery, kernel creation, and semaphore acquisition adds up.

**LLM cost:** Roughly equivalent — both make one LLM call per primary agent turn. The observer's call has slightly more overhead (system prompt + tool schemas in the request) but the content to analyze is the same.

**Verdict:** Inline hooks are significantly lower latency. The observer's full-turn overhead is unnecessary for what amounts to "call LLM with structured output, write results to KV."

### 5.2 Concurrency Impact

**Inline hooks:** The background task runs outside the semaphore (the `asyncio.create_task` is fire-and-forget). The LLM call doesn't compete with real agent turns for concurrency slots. The only contention is on the LLM server itself.

Wait — let me re-examine. Looking at `execute_turn()` in `actor.py` line 320: the entire turn runs inside `async with self._semaphore`. If the post-turn hook is spawned as `asyncio.create_task` inside that block, the task runs independently and the semaphore releases when `execute_turn` returns. So the hook does NOT hold the semaphore. Correct.

**Observer:** The observer IS an actor. It acquires a semaphore slot via `async with self._semaphore` in its own `execute_turn()`. With `max_concurrency: 4`, every companion digest consumes one of four slots. If agents are active and producing events faster than the observer can digest them, the observer queues up in its inbox AND competes with real agents for semaphore slots.

**Verdict:** Inline hooks are clearly better — zero concurrency impact. The observer's concurrency consumption is a real problem for busy systems.

### 5.3 Failure Modes

**Inline hooks:** If the hook LLM call fails, the background task catches the exception and logs it. The primary turn already completed successfully. Failure is invisible to the user — they just don't get companion metadata for that turn. Retry logic can be added to the hook itself.

**Observer:** If the observer's turn fails, it emits `AgentErrorEvent`. The observer shows up in the web UI as "error" state. The failed event stays unprocessed. The observer must be manually recovered (or auto-recovers on next event). More visible, but also more alarming for failures that don't actually matter.

**Verdict:** Inline hooks fail more gracefully. The observer's failure is noisier than warranted for optional metadata.

### 5.4 Resource Overhead

**Inline hooks:** No additional actors, no additional workspace, no additional subscriptions. The hook is a function call, not an entity.

**Observer:** One additional actor in the pool (with inbox, history, workspace), one additional set of subscriptions in the registry, one additional node in the node store. Small individually, but it's a permanent resident that processes every agent turn completion.

**Verdict:** Inline hooks are lighter. The observer's overhead is modest but permanent.

---

## 6. Deep Comparison: Configurability & Extensibility

### 6.1 Per-Bundle Configuration

**Inline hooks:** Bundle config controls enablement and model choice:
```yaml
# bundle.yaml
post_turn:
  enabled: true
  model: "Qwen/Qwen3-1.7B"
  tag_vocabulary: [bug, question, refactor, ...]
```
Different bundles can enable/disable hooks and choose different models. But the *behavior* is hardcoded in `hooks.py` — every bundle gets the same summarize/tag/reflect/link pipeline.

**Observer:** The bundle defines the entire behavior via system prompt and tools. You could have a "code-companion" bundle that focuses on code quality insights and a "docs-companion" that focuses on documentation completeness. Different observer bundles are completely different behaviors, controlled entirely via prompt + tools.

**Verdict:** Observer is much more configurable. But: can we imagine actually wanting different companion behaviors per bundle? The brainstorming doc doesn't suggest this need. If we do, the inline approach can be extended later by making the digest prompt itself bundle-configurable (a string template in `post_turn.prompt`).

### 6.2 Adding New Hook Behaviors

**Inline hooks:** Adding a new post-turn behavior (e.g., "detect test coverage gaps") requires modifying `hooks.py` — adding fields to `TurnDigest`, updating the prompt, updating `apply_turn_digest()`. Code changes, PR, deploy.

**Observer:** Adding new behavior means updating the system prompt in the bundle and possibly adding a new tool script. No core code changes. This is the power of the agent-as-observer pattern — it's as extensible as the LLM's capabilities allow.

**Verdict:** Observer is more extensible for behavior changes. Inline hooks require code changes.

### 6.3 Cross-Agent Aggregation

**Inline hooks:** Each agent processes its own turn. There's no natural place for "look at what ALL agents have been doing and find patterns." A separate virtual agent could still be added for this purpose, but it's outside the companion system.

**Observer:** The observer sees ALL `AgentCompleteEvent` events. It can naturally build cross-agent views: "which agents are most active?", "what topics cluster together?", "are there patterns in errors?" This is genuinely powerful for project-level insights.

**Verdict:** Observer wins decisively for cross-agent aggregation. This is its strongest advantage.

---

## 7. The Cross-Workspace Problem

### 7.1 Why It Matters

The companion system's primary output is KV data written to each agent's workspace: `companion/chat_index`, `companion/reflections`, `companion/links`. This data must live in the *originating agent's* workspace, because:
- The agent's system prompt reads its own workspace KV to build companion context
- The web API endpoint reads workspace KV by node_id
- The data belongs to the agent, not to the observer

**Inline hooks:** No problem. The hook runs with direct access to the agent's `workspace: AgentWorkspace`. KV writes are local.

**Observer:** The observer has its own workspace (`companion-observer`). To write to agent X's workspace, it needs cross-workspace access. The current `TurnContext` API is sandboxed — `kv_set(key, value)` writes to `self.workspace`, period.

### 7.2 Solution Options for Approach A

**Option 1: Add `kv_set_foreign(agent_id, key, value)` to TurnContext.**
- Requires `CairnWorkspaceService` to be accessible from TurnContext
- Breaks the workspace sandboxing model — any agent could write to any other agent's KV store
- Security concern: agents could corrupt each other's state

**Option 2: Two-hop event pattern.**
The observer emits a new event type (e.g., `CompanionDigestReadyEvent`) containing the digest. Each agent subscribes to this event type and self-applies the digest to its own KV store in its next turn.
- Doubles the event hops (AgentCompleteEvent → observer → CompanionDigestReadyEvent → originating agent)
- Adds significant latency (two full turn cycles)
- The originating agent must handle this event type, which means modifying actor behavior anyway
- If the agent is idle, the digest sits in its inbox until the next trigger

**Option 3: Observer writes via workspace service directly (bypass TurnContext).**
- Give the observer's tools access to `CairnWorkspaceService` rather than just its own workspace
- Less sandboxing violation than Option 1 (only the observer has this power), but still requires a new Grail capability
- Requires a new `@external` in TurnContext: `write_foreign_kv(agent_id, key, value)`

**Option 4: Shared KV namespace.**
- Instead of per-workspace KV, companion data lives in a shared KV store (e.g., a new table in the SQLite DB)
- The system prompt builder reads from the shared store by agent_id
- Avoids cross-workspace access entirely
- But: introduces a new storage layer that duplicates what workspace KV already does

### 7.3 Impact on Architecture

Every solution for Approach A's cross-workspace problem adds complexity that undermines the "less core code" advantage:

| Option | New Core Code | Sandboxing Impact |
|--------|:------------:|:-----------------:|
| 1. Foreign KV | ~20 lines | **Breaks model** — any agent can write to any other |
| 2. Two-hop events | ~40 lines + subscription wiring | Preserves model, but doubles latency |
| 3. Bypass TurnContext | ~30 lines | Partial break — only observer has power |
| 4. Shared KV | ~60 lines | Preserves model, but new storage layer |

The brainstorming doc acknowledged this: *"This requires either: (a) adding a write_to_foreign_workspace capability, which breaks the sandboxing model; or (b) having the observer emit a new event that the originating actor picks up and self-applies, which adds a second event hop and more latency."*

**Verdict:** The cross-workspace problem is Approach A's Achilles heel. Every solution adds complexity and trade-offs that erode its "zero core code changes" advantage.

---

## 8. Hybrid Possibilities

### 8.1 Inline Hooks for Per-Agent Memory + Observer for Cross-Agent

The strongest argument for both approaches is that they solve different problems:

- **Inline hooks** solve per-agent memory (summary, tags, reflection, links for THIS agent)
- **Observer** solves cross-agent aggregation (project-wide patterns, activity dashboards, inter-agent insights)

A hybrid approach uses inline hooks as the primary companion system (Phase 1) and optionally adds an observer virtual agent for cross-agent features (Phase 2). The observer in this case does NOT need to write to foreign workspaces — it reads `AgentCompleteEvent` payloads to build its own aggregate view in its own workspace.

```
Phase 1: Inline hooks → per-agent companion memory
Phase 2: Observer → reads AgentCompleteEvents → builds project-level insights in own workspace
```

This gives the observer a clean role (aggregate analyzer, not per-agent writer) and avoids the cross-workspace problem entirely.

### 8.2 Phased Rollout

**Phase 1 (inline hooks):**
- `core/hooks.py` — TurnDigest, digest_turn, apply_turn_digest
- `actor.py` modifications — hook execution, companion context in system prompt
- `TurnDigestedEvent`
- Web endpoint for companion data
- Bundle config for enablement

**Phase 2 (optional observer):**
- `companion-observer` virtual agent
- Bundle with system prompt focused on cross-agent analysis
- Subscribes to `TurnDigestedEvent` (not `AgentCompleteEvent` — avoids seeing raw turns)
- Builds aggregate views in its own workspace
- Web endpoint for project-level companion insights

Phase 2 is entirely additive and can be deferred indefinitely without affecting Phase 1.

---

## 9. Recommendation & Trade-off Summary

### Comparison Matrix

| Dimension | Inline Hooks | Observer | Winner |
|-----------|:----------:|:--------:|:------:|
| Core code changes | ~255 lines in 3 files | ~108 lines + bundle + cross-workspace | Inline (simpler despite more lines) |
| Latency | Background task, ms | Full turn cycle, seconds | **Inline** |
| Concurrency impact | Zero | Consumes semaphore slot | **Inline** |
| Failure mode | Silent, graceful | Visible error, requires recovery | **Inline** |
| Cross-workspace | Not needed | **Major problem** | **Inline** |
| Separation of concerns | Moderate (core/hooks.py) | Excellent (entirely in bundle) | Observer |
| Cross-agent aggregation | Not supported | Native | **Observer** |
| Configurability | Via bundle.yaml fields | Via bundle prompt + tools | Observer |
| Extensibility | Code changes needed | Prompt/tool changes only | Observer |
| Self-trigger loop risk | None | Must be handled | **Inline** |
| Observability | Emits TurnDigestedEvent | Full actor visibility | Observer |

### Recommendation

**Use inline hooks (the recommended approach) for the companion system.** The rationale:

1. **The primary need is per-agent memory**, which inline hooks handle perfectly with zero architectural complications.
2. **The cross-workspace problem** makes the observer approach significantly more complex than it appears. Every solution either breaks sandboxing or adds latency.
3. **The concurrency impact** of the observer is a real operational concern — companion processing should never compete with real agent work.
4. **The observer's strengths** (cross-agent aggregation, configurability) are Phase 2 features that can be added later without any rework, using `TurnDigestedEvent` as the hook point.
5. **Simplicity.** One file + a few modifications vs. a new subsystem with cross-workspace access, event loop risks, and concurrency contention.

The observer pattern remains available for future cross-agent features, building on top of the inline hooks rather than replacing them.

---

## Appendix A: First-Principles Redesign of the Observer

### Table of Contents

- A.1 [The v2 Ethos: What Are We Actually Building?](#a1-the-v2-ethos-what-are-we-actually-building)
- A.2 [What the Observer Really Wants to Do](#a2-what-the-observer-really-wants-to-do)
- A.3 [Existing Primitives We Haven't Fully Exploited](#a3-existing-primitives-we-havent-fully-exploited)
- A.4 [Design A: The Agent That Teaches Itself (Self-Directed Companion)](#a4-design-a-the-agent-that-teaches-itself-self-directed-companion)
- A.5 [Design B: EventBus Listener + Direct KV (Non-Actor Observer)](#a5-design-b-eventbus-listener--direct-kv-non-actor-observer)
- A.6 [Design C: Scoped Workspace Delegation (Sanctioned Cross-Write)](#a6-design-c-scoped-workspace-delegation-sanctioned-cross-write)
- A.7 [Design D: Event Enrichment Pipeline (No Observer At All)](#a7-design-d-event-enrichment-pipeline-no-observer-at-all)
- A.8 [Synthesis: What Aligns Best With v2?](#a8-synthesis-what-aligns-best-with-v2)

---

### A.1 The v2 Ethos: What Are We Actually Building?

Before designing the observer, we need to state what remora-v2 *is* at the philosophical level, because the right design flows from first principles, not from jamming v1 concepts into v2 plumbing.

**v2's core axioms, as evidenced by the code:**

1. **Code elements are agents.** Every function, class, method, file, and directory IS an actor. There is no separation between "the code" and "the agent that manages it." `PromptBuilder.build_prompt()` says *"# Node: {node.full_name}"* — the agent IS the node. `code-agent/bundle.yaml` says *"You ARE the code element. Speak in the first person."*

2. **One agent, one workspace, one identity.** Each actor has a sandboxed `AgentWorkspace` at `.remora/agents/<safe_id>/`. KV store, files, bundle config — all scoped to that one identity. There is no shared state between agents except through events.

3. **Events are the only inter-agent channel.** Agents don't call each other. They emit events, subscribe to events, and send messages (which are events). The `TriggerDispatcher` is the only way one agent's action causes another agent to act. The subscription system is the permission model.

4. **Bundles define behavior, not code.** An agent's personality, capabilities, and response patterns come from its bundle (system prompt, tool scripts, model choice). The Actor class is generic — behavior lives in configuration. The `system` bundle layers underneath role-specific bundles.

5. **Virtual agents extend the graph without code elements.** `VirtualAgentConfig` lets you define agents that don't map to source code. They get subscriptions, bundles, workspaces — everything a real agent gets. They're first-class graph citizens with `NodeType.VIRTUAL`.

6. **Tools are the agent's hands.** Grail `.pym` scripts are the mechanism through which agents act on the world. The `@external` pattern maps tool calls to `TurnContext` capabilities. Agents can only do what their tools allow.

Now: how do these axioms constrain and enable the observer?

---

### A.2 What the Observer Really Wants to Do

Strip away the implementation debates and state what the observer's *job* is:

> **After an agent completes a turn, extract structured metadata (summary, tags, reflections, cross-node links) and persist that metadata so the originating agent can build on it in future turns.**

Decompose this into primitives:

1. **Trigger:** An agent completed a turn → `AgentCompleteEvent` was emitted.
2. **Input:** The user message and assistant response from that turn.
3. **Processing:** One LLM call with a structured output request.
4. **Output:** Structured metadata (summary, tags, reflection, links).
5. **Persistence:** Write to the originating agent's KV store.
6. **Feedback loop:** The originating agent's system prompt reads back the accumulated metadata.

The question is: *who* does steps 2-5, and *where* does that processing live?

The main document's Approach A (virtual agent observer) says "a separate virtual agent." The recommended approach says "inline in the originating agent's turn executor." But there are other answers that flow from first principles.

---

### A.3 Existing Primitives We Haven't Fully Exploited

Before inventing new machinery, audit what already exists:

**Discovery 1: Companion tools already exist in `bundles/system/tools/`.**

The system bundle already ships:
- `reflect.pym` — Writes reflection notes to workspace files
- `summarize.pym` — Generates an activity summary from event history
- `categorize.pym` — Tags the code element by heuristic keyword matching
- `find_links.pym` — Records graph edges to workspace files

These tools are **already available to every agent** (system bundle layers under all role bundles). They write to workspace files (`notes/reflection.md`, `notes/summary.md`, `meta/categories.md`, `meta/links.md`) rather than KV, and they're heuristic-based rather than LLM-based. But they exist and they work.

This means every agent *already has* companion-like capabilities. They just don't *use* them automatically after each turn.

**Discovery 2: The `reactive` prompt mode already handles post-event behavior.**

`PromptBuilder.build_system_prompt()` selects between `chat` and `reactive` prompts based on whether the trigger event has a `from_agent == "user"`. The reactive prompt in `code-agent/bundle.yaml` says:

> *"A change was detected in your code or a related element. Review what happened. Use reflect to update your understanding."*

Agents already have instructions to self-reflect when triggered by events. The infrastructure for "do companion work after something happens" exists in the prompt system.

**Discovery 3: `EventBus` supports non-actor listeners.**

`EventBus.subscribe()` and `EventBus.subscribe_all()` accept any `EventHandler` callable. `EventBus.stream()` yields an async iterator. These don't route through the actor system at all — they're direct in-process event listeners. The SSE endpoint in `web/server.py` uses `event_bus.stream()` to watch events. A companion processor could do the same.

**Discovery 4: `CairnWorkspaceService.get_agent_workspace()` is a service-level call.**

Any code that holds a reference to `CairnWorkspaceService` can call `get_agent_workspace(node_id)` for *any* agent. The sandboxing is at the `TurnContext` level (tools can only access `self.workspace`), not at the service level. The service itself has no sandboxing — it's already used by `FileReconciler` to provision bundles for arbitrary agents.

This means a non-actor companion processor that holds `CairnWorkspaceService` can write to any agent's KV store without breaking any actual sandbox boundary. The workspace sandbox is a tool-level abstraction, not a storage-level one.

---

### A.4 Design A: The Agent That Teaches Itself (Self-Directed Companion)

**Core idea:** Don't add an observer at all. Instead, make agents *teach themselves* by expanding the reactive turn to include self-reflection.

**How it works:**

After `AgentCompleteEvent` is emitted, the same agent receives it as a self-trigger (via a self-subscription). The agent runs a *second turn* in reactive mode, where its system prompt instructs it to:
1. Review the exchange it just completed
2. Use its existing tools (`reflect.pym`, `categorize.pym`, `kv_set.pym`) to record metadata
3. Update its own understanding

```yaml
# In remora.yaml or via subscription setup
# Each agent subscribes to its own AgentCompleteEvents
```

Or: add a `self_subscribe` flag in bundle config that auto-registers a subscription for the agent's own `AgentCompleteEvent` during bundle provisioning.

**Alignment with v2 ethos:**

- ✅ **Code elements are agents:** The agent is reflecting on *itself*. No external entity needed.
- ✅ **One agent, one workspace:** Writes to its own KV. No cross-workspace access.
- ✅ **Events are the channel:** Uses the existing subscription + dispatch system.
- ✅ **Bundles define behavior:** The self-reflection behavior is controlled via the reactive prompt and tool availability.
- ✅ **Tools are the hands:** Uses existing `reflect.pym`, `kv_set.pym`, etc.

**Problems:**

1. **Double turn cost.** Every agent turn triggers a second turn (the self-reflection). That's 2x LLM calls, 2x semaphore acquisition, 2x the latency. The second turn uses the full actor machinery (workspace lookup, tool discovery, kernel creation, structured-agents framework) for what amounts to "call LLM once with a structured output request."

2. **Trigger depth.** The self-reflection turn emits its own `AgentCompleteEvent`, which could trigger another self-reflection. The `TriggerPolicy.max_trigger_depth` bounds this, but it wastes a depth slot. Need either: tags to distinguish "primary turn" from "reflection turn", or a `post_turn` flag on `AgentCompleteEvent` that subscriptions can filter on.

3. **Tool overhead.** The LLM in the reflection turn must *decide* which tools to call (kv_set, reflect, etc.) and call them individually via the structured-agents tool-calling loop. This is heavier than a single `digest_turn()` function call that directly writes to KV. The agent might make bad tool choices, call too many tools, or hallucinate — all the failure modes of agentic LLM usage apply.

4. **Prompt engineering burden.** Getting the reflection prompt right — so the agent consistently produces useful summaries and doesn't just say "I reviewed the activity, everything looks fine" — is a prompt engineering challenge that doesn't exist with structured output parsing.

**Verdict:** Philosophically the most v2-aligned approach. Practically, it's expensive and fragile. The agent-as-self-reflector idea is beautiful but the overhead of running a full agentic turn for metadata extraction is disproportionate.

---

### A.5 Design B: EventBus Listener + Direct KV (Non-Actor Observer)

**Core idea:** Use `EventBus.subscribe()` to register a plain async function (not an actor) that listens for `AgentCompleteEvent`, makes an LLM call directly, and writes to the originating agent's KV via `CairnWorkspaceService`.

**How it works:**

```python
# core/companion.py

class CompanionListener:
    def __init__(
        self,
        workspace_service: CairnWorkspaceService,
        config: Config,
    ):
        self._workspace_service = workspace_service
        self._config = config

    async def on_agent_complete(self, event: Event) -> None:
        if not isinstance(event, AgentCompleteEvent):
            return
        # Make LLM call for structured digest
        digest = await digest_turn(
            agent_id=event.agent_id,
            response_text=event.full_response,
            model_name=self._config.post_turn_model,
            config=self._config,
        )
        # Write directly to the originating agent's workspace KV
        workspace = await self._workspace_service.get_agent_workspace(event.agent_id)
        await apply_turn_digest(workspace, digest)
```

Registered during startup:
```python
listener = CompanionListener(services.workspace_service, services.config)
services.event_bus.subscribe(AgentCompleteEvent, listener.on_agent_complete)
```

**Alignment with v2 ethos:**

- ⚠️ **Not an agent.** The listener is infrastructure, like the EventStore or TriggerDispatcher. It doesn't have an identity, a workspace, or a conversation history. This is intentional — it's a system service, not a participant.
- ✅ **Events are the channel.** Uses `EventBus.subscribe()` — the same mechanism the web SSE endpoint uses. No new event routing concepts.
- ✅ **No concurrency contention.** Doesn't acquire the semaphore. Runs independently of the actor pool.
- ⚠️ **Cross-workspace writes.** Uses `CairnWorkspaceService.get_agent_workspace()` to write to any agent's KV. This doesn't break the tool-level sandbox (TurnContext still restricts tool access), but it does mean a service-level component writes to agent-owned state. This is analogous to how `FileReconciler` provisions bundles into agent workspaces — existing precedent for service-level workspace writes.

**Key insight:** `CairnWorkspaceService.get_agent_workspace()` is already called by `FileReconciler._provision_bundle()` which writes `_bundle/bundle.yaml` and `_bundle/tools/*.pym` into agent workspaces. The companion listener would be doing the exact same thing — a service-level component writing structured data into agent workspaces. The sandboxing boundary isn't violated because the boundary is at the TurnContext level, and this code doesn't go through TurnContext.

**Problems:**

1. **No user_message on AgentCompleteEvent.** `AgentCompleteEvent` has `full_response` and `result_summary`, but not the user message. The digest LLM call ideally needs both sides of the exchange for good summaries. Solutions:
   - Enrich `AgentCompleteEvent` with a `user_message` field (adds ~100 chars per event to storage)
   - Have the listener query `event_store.get_events_for_agent()` to reconstruct context (adds latency)
   - Accept lower-quality digests based only on the response (simpler, may be sufficient)

2. **Not observable in the agent graph.** The listener isn't a node — it doesn't show up in the web UI's node list, doesn't emit its own events, doesn't have metrics. It's invisible infrastructure. This may be fine (the EventStore is also invisible) or may be a problem (can't monitor companion processing health).

3. **Direct LLM calls outside the kernel system.** The listener makes LLM calls without going through `create_kernel()` / structured-agents. It needs its own httpx client or a simpler LLM call wrapper. This is a new code path for LLM interaction.

**Verdict:** Pragmatic and well-aligned. Uses existing event infrastructure without creating a new actor. The cross-workspace write follows the `FileReconciler` precedent. The main weakness is lack of observability and the need for a standalone LLM call path.

---

### A.6 Design C: Scoped Workspace Delegation (Sanctioned Cross-Write)

**Core idea:** Extend the virtual agent model with a new capability: *delegated workspace write access*. A virtual agent can be granted explicit write permission to specific KV prefixes in other agents' workspaces, declared in the configuration.

**How it works:**

```yaml
virtual_agents:
  - id: companion-observer
    role: companion
    subscriptions:
      - event_types: ["AgentCompleteEvent"]
    workspace_delegation:
      kv_prefix: "companion/"
      scope: "all"  # or list of specific agent IDs
```

This tells the system: "the `companion-observer` agent is allowed to write KV keys under `companion/` in any agent's workspace." A new `TurnContext` method is exposed:

```python
async def delegated_kv_set(self, agent_id: str, key: str, value: Any) -> bool:
    """Write to another agent's KV store under a delegated prefix."""
```

The method checks the caller's delegation scope (from its `VirtualAgentConfig`) before allowing the write. Only the declared prefix is writable. The tool is only available to agents that have delegation configured.

**Alignment with v2 ethos:**

- ✅ **The observer is a real agent.** Virtual agent with identity, workspace, subscriptions — first-class graph citizen.
- ✅ **Events are the channel.** Standard subscription routing.
- ✅ **Bundles define behavior.** The observer's behavior comes from its bundle's system prompt and tools.
- ⚠️ **Sandboxing is loosened, not broken.** The delegation is explicit, scoped, and declared in configuration. Unlike a blanket `kv_set_foreign()`, this limits writes to a specific prefix (`companion/`) for specific agents. The admin explicitly grants this power.
- ✅ **Discoverable.** The observer is visible in the node graph, emits events, has metrics.

**New concepts introduced:**

1. `workspace_delegation` in `VirtualAgentConfig` — new config field
2. `delegated_kv_set` / `delegated_kv_get` in `TurnContext` — new capabilities
3. Delegation check logic in TurnContext (read delegation scope from config)
4. A new Grail tool: `delegated_kv_set.pym`

**Problems:**

1. **Config-to-runtime plumbing.** The `VirtualAgentConfig.workspace_delegation` must flow through: `FileReconciler._sync_virtual_agents()` → `_provision_bundle()` → somehow into the `TurnContext` that gets created for the observer's turns. Currently, `TurnContext` knows nothing about the agent's config — it gets instantiated with raw parameters. We'd need to either pass the delegation config into TurnContext or have a registry that TurnContext queries.

2. **Still a full actor turn.** Same overhead as Approach A: semaphore slot, workspace setup, tool discovery, kernel creation. The delegation solves the cross-workspace problem but doesn't solve the cost problem.

3. **Self-trigger loop.** Still present. The observer's `AgentCompleteEvent` must be filtered.

4. **Complexity budget.** A new config concept, new TurnContext method, new capability, new tool — for something that could be a 5-line function call in the turn executor. The abstraction carries weight proportional to a feature that's used by exactly one agent.

**Verdict:** The most architecturally principled solution to the cross-workspace problem. If you *must* have a virtual agent observer, this is how to do it right. But the overhead of the full actor turn cycle and the new config/capability surface area are significant costs for what remains a metadata extraction task.

---

### A.7 Design D: Event Enrichment Pipeline (No Observer At All)

**Core idea:** Abandon the "observer" framing entirely. Instead, treat companion metadata as *event enrichment* — a processing pipeline that annotates events before they're persisted, similar to how a database trigger enriches rows on insert.

**How it works:**

Add an optional enrichment step in `EventStore.append()`:

```python
async def append(self, event: Event) -> int:
    # Existing: persist, bus emit, dispatch
    event_id = await self._persist(event)
    await self._event_bus.emit(event)
    await self._dispatcher.dispatch(event)

    # NEW: post-persist enrichment (fire-and-forget)
    if self._enrichment_pipeline:
        asyncio.create_task(
            self._enrichment_pipeline.process(event, event_id)
        )
    return event_id
```

The enrichment pipeline is a simple list of async processors:

```python
class CompanionEnricher:
    """Enriches AgentCompleteEvents with companion metadata."""

    async def process(self, event: Event, event_id: int) -> None:
        if not isinstance(event, AgentCompleteEvent):
            return
        digest = await digest_turn(event.agent_id, event.full_response, ...)
        workspace = await self._workspace_service.get_agent_workspace(event.agent_id)
        await apply_turn_digest(workspace, digest)
```

**Alignment with v2 ethos:**

- ✅ **Events as the backbone.** The enrichment IS the event system doing its job — events flow through a pipeline and get annotated along the way.
- ⚠️ **Not an agent.** Like Design B, this is infrastructure, not an entity.
- ✅ **Zero concurrency impact.** Fire-and-forget task, no semaphore.
- ⚠️ **Modifies EventStore.** Adds a new concept (enrichment pipeline) to the event persistence layer.

**Problems:**

1. **EventStore scope creep.** EventStore currently does exactly three things: persist, bus-emit, dispatch. Adding enrichment makes it a four-stage pipeline. The enrichment is conceptually separate from event persistence — it's a downstream consumer, not a persistence concern.

2. **Same cross-workspace pattern as Design B.** Uses `CairnWorkspaceService` directly. Same precedent, same trade-offs.

3. **Ordering guarantees.** If the enrichment is fire-and-forget, there's no guarantee the companion data is written before the next turn reads it. For a system prompt that reads companion context, this means the most recent exchange's digest might not be available. (This is also true of Design B and the inline hooks approach — all fire-and-forget.)

**Verdict:** Clean concept but wrong placement. The EventStore shouldn't grow responsibilities. The enrichment logic belongs at a higher layer — which is essentially what the inline hooks approach or Design B already are.

---

### A.8 Synthesis: What Aligns Best With v2?

Let's score each design against the v2 axioms:

| Axiom | Self-Directed (A) | EventBus Listener (B) | Scoped Delegation (C) | Event Enrichment (D) |
|-------|:-:|:-:|:-:|:-:|
| Code elements are agents | ✅ Best | ❌ Not an agent | ✅ Virtual agent | ❌ Not an agent |
| One agent, one workspace | ✅ Own workspace | ⚠️ Writes to others (precedented) | ⚠️ Scoped cross-write | ⚠️ Writes to others |
| Events are the channel | ✅ Self-subscription | ✅ EventBus.subscribe | ✅ Subscription dispatch | ✅ Event pipeline |
| Bundles define behavior | ✅ Prompt-driven | ❌ Code-driven | ✅ Prompt-driven | ❌ Code-driven |
| Tools are the hands | ✅ Uses existing tools | ❌ Direct function call | ✅ New delegated tool | ❌ Direct function call |
| Practical cost | ❌ 2x turns | ✅ Minimal overhead | ⚠️ Full turn + new concepts | ✅ Minimal overhead |

**The philosophical winner is Design A (self-directed)** — it's the most v2-native because the agent teaches itself using its own tools, workspace, and event subscriptions. No new concepts needed. It's what the system was *designed* for.

**The practical winner is Design B (EventBus listener)** — it's the lightest-weight implementation that uses existing infrastructure (EventBus.subscribe, CairnWorkspaceService) with clear precedent (FileReconciler already writes to agent workspaces).

**The compromise winner is Design C (scoped delegation)** — it solves the cross-workspace problem properly and keeps the observer as a first-class agent. But the implementation cost is high for a v1 feature.

**The "maybe later" insight:** Designs A and C are most interesting when companion behavior needs to be *customizable per deployment*. If different projects want different reflection strategies, the agent-based approaches let you swap bundles rather than code. But if the companion pipeline is the same everywhere (summarize + tag + reflect + link), the code-based approaches (B, or the original inline hooks) are simpler.

### The Real First-Principles Answer

If we truly start from v2's ethos, the answer is this:

**The companion system shouldn't be a separate subsystem at all.** v2 was designed so that every agent IS a companion to its code element. The system bundle already ships `reflect.pym`, `categorize.pym`, `find_links.pym`, `summarize.pym`. The `code-agent` bundle's reactive prompt already says *"Use reflect to update your understanding."*

The gap isn't "we need a companion system." The gap is:
1. **Agents don't self-reflect reliably** — they need better prompts and possibly a post-turn reactive trigger
2. **The existing tools write to files instead of KV** — should be updated to use `kv_set`
3. **There's no mechanism to auto-trigger self-reflection** — agents only reflect when the LLM decides to call the tool during a turn

The minimal v2-aligned intervention is:
- Update `reflect.pym`, `summarize.pym`, `categorize.pym`, `find_links.pym` to use `kv_set` instead of `write_file`
- Add a `post_turn_self_trigger` config option that auto-fires a self-subscription for `AgentCompleteEvent`
- Improve reactive prompts to consistently produce useful reflections
- Accept the 2x turn cost as the price of staying within v2's model

OR: accept that post-turn metadata extraction is an *infrastructure concern* (like bundle provisioning, event persistence, or subscription matching) and implement it as infrastructure — which is exactly what the inline hooks approach does.

Both are honest answers to "what does v2 want?" The choice depends on whether you believe companion metadata is an *agent behavior* (→ self-directed) or an *infrastructure service* (→ inline hooks / EventBus listener).
