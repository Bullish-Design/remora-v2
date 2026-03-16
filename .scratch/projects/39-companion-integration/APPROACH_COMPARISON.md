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
