# CONCEPT: Self-Directed Companion & Scoped Delegation — Expanded Designs

## Table of Contents

1. [Purpose of This Document](#1-purpose-of-this-document)
2. [Design A Expanded: The Self-Directed Companion](#2-design-a-expanded-the-self-directed-companion)
   - 2.1 Philosophy: Why Self-Direction Matters
   - 2.2 Mechanism: Self-Subscription via Bundle Config
   - 2.3 The Reflection Turn in Detail
   - 2.4 Solving the Self-Trigger Loop
   - 2.5 Solving the Double-Turn Cost
   - 2.6 Upgraded Companion Tools (KV-Native)
   - 2.7 Prompt Engineering for Reliable Self-Reflection
   - 2.8 System Prompt Injection: Reading Companion Memory Back
   - 2.9 Concrete Code Walkthrough
   - 2.10 Strengths and Remaining Weaknesses
3. [Design C Expanded: Scoped Workspace Delegation](#3-design-c-expanded-scoped-workspace-delegation)
   - 3.1 Philosophy: Principled Cross-Agent Capability
   - 3.2 The Delegation Model in Detail
   - 3.3 Config Schema Changes
   - 3.4 Runtime Plumbing: Config → TurnContext
   - 3.5 The `delegated_kv_set` Capability
   - 3.6 Grail Tool: `delegated_kv_set.pym`
   - 3.7 Observer Bundle Design
   - 3.8 Solving the Self-Trigger Loop
   - 3.9 What the Observer Sees (AgentCompleteEvent Enrichment)
   - 3.10 Concrete Code Walkthrough
   - 3.11 Strengths and Remaining Weaknesses
4. [A+C Combined: Self-Directed Agents + Delegated Observer](#4-ac-combined-self-directed-agents--delegated-observer)
   - 4.1 Why Combine Them?
   - 4.2 Architecture: Two Layers of Companion Intelligence
   - 4.3 Layer 1: Self-Directed (Per-Agent, Every Turn)
   - 4.4 Layer 2: Delegated Observer (Cross-Agent, Periodic)
   - 4.5 How the Layers Interact
   - 4.6 Configuration for the Combined System
   - 4.7 Concrete Scenario Walkthrough
   - 4.8 Implementation Phasing
   - 4.9 Cost Analysis
   - 4.10 What This Enables That Neither Design Alone Can
5. [Comparison: A vs C vs A+C](#5-comparison-a-vs-c-vs-ac)

---

## 1. Purpose of This Document

APPROACH_COMPARISON.md identified Design A (Self-Directed Companion) and Design C (Scoped Workspace Delegation) as the most v2-aligned approaches to companion functionality. That document analyzed them briefly alongside two other options. This document expands each design into a concrete, implementable specification — individually and in combination — with enough detail to evaluate whether they're the right path forward.

**Design A** says: every agent should teach itself. Self-subscribe to your own completion events, run a reflection turn, use your own tools to record metadata in your own workspace. No external observers needed.

**Design C** says: a dedicated virtual agent observer with explicitly-granted, scoped permission to write companion data into other agents' workspaces. Cross-agent by design, principled in its sandboxing.

**A+C combined** says: agents teach themselves the basics (Layer 1), while a cross-agent observer identifies patterns that no single agent can see (Layer 2). Self-reflection for the individual, observation for the collective.

---

## 2. Design A Expanded: The Self-Directed Companion

### 2.1 Philosophy: Why Self-Direction Matters

The v2 ethos says "code elements are agents." An agent that needs an *external system* to tell it what it learned from a conversation is not autonomous — it's being managed. Self-directed reflection aligns with the deepest design principle: the agent IS the code element, and the code element should understand itself.

This matters beyond aesthetics. When an agent reflects on its own turn:
- It has full context: its own history, workspace state, prior reflections, the source code it embodies
- It can decide what's *important to remember* based on its own accumulated understanding
- The reflection quality improves over time as the agent's prompt includes prior reflections
- There's no data transfer problem — everything is local to the agent's workspace

An external observer, by contrast, sees only the event payload. It doesn't know the agent's history, doesn't see the workspace state, and can't make judgments informed by prior reflections. Self-direction produces richer, more contextual metadata.

### 2.2 Mechanism: Self-Subscription via Bundle Config

The core mechanism is a new bundle config key: `self_reflect`. When enabled, the bundle provisioning system auto-registers a subscription that routes the agent's own `AgentCompleteEvent` back to itself.

```yaml
# bundles/code-agent/bundle.yaml
self_reflect:
  enabled: true
  model: "Qwen/Qwen3-1.7B"  # cheaper model for reflection turns
  max_turns: 2                # reflection turns are short
```

During `FileReconciler._register_subscriptions()`, if the agent's bundle config has `self_reflect.enabled: true`, an additional subscription is registered:

```python
# In _register_subscriptions(), after existing subscriptions:
if bundle_config.get("self_reflect", {}).get("enabled"):
    await self._subscriptions.register(
        node_id,
        SubscriptionPattern(
            event_types=["AgentCompleteEvent"],
            from_agents=[node_id],  # only own events
            tags=["primary"],       # only primary turns, not reflections
        ),
    )
```

The `from_agents=[node_id]` filter ensures the agent only sees its own completions. The `tags=["primary"]` filter ensures reflection turns don't re-trigger themselves (see Section 2.4).

### 2.3 The Reflection Turn in Detail

When an agent completes a primary turn, the flow is:

```
Primary turn completes
  → _complete_agent_turn() emits AgentCompleteEvent(tags=("primary",))
  → TriggerDispatcher matches the self-subscription
  → Event lands back in the same actor's inbox
  → Actor._run() picks it up, creates a new Trigger
  → execute_turn() runs with the AgentCompleteEvent as trigger
  → PromptBuilder detects reactive mode (no from_agent="user")
  → Reflection-specific prompt is used
  → Agent calls kv_set, companion_reflect, etc. via tools
  → _complete_agent_turn() emits AgentCompleteEvent(tags=("reflection",))
  → Dispatcher checks subscriptions → no match (tag filter excludes "reflection")
  → Chain terminates
```

The reflection turn is a *real turn*. The agent sees:
- Its system prompt (including accumulated companion context from prior reflections)
- A user prompt built from the `AgentCompleteEvent`: `"Event: AgentCompleteEvent\nContent: <result_summary>"`
- Its full tool set (reflect, kv_set, categorize, etc.)

The LLM decides what metadata to extract and which tools to call. This is the "expensive but flexible" trade-off — the agent might produce richer reflections than a structured-output parser, but it might also waste tool calls or produce nothing useful.

### 2.4 Solving the Self-Trigger Loop

The appendix identified the self-trigger loop as Problem #2. Here's the concrete solution:

**Tag-based turn classification.** Add a `tags` field to `AgentCompleteEvent` (already exists on the base `Event` class). Primary turns are tagged `"primary"`, reflection turns are tagged `"reflection"`.

The change is in `AgentTurnExecutor._complete_agent_turn()`:

```python
async def _complete_agent_turn(self, node_id, response_text, outbox, trigger, turn_log):
    # Determine if this turn was itself triggered by a reflection
    is_reflection = (
        trigger.event is not None
        and trigger.event.event_type == "AgentCompleteEvent"
    )
    tags = ("reflection",) if is_reflection else ("primary",)

    await outbox.emit(
        AgentCompleteEvent(
            agent_id=node_id,
            result_summary=response_text[:200],
            full_response=response_text,
            correlation_id=trigger.correlation_id,
            tags=tags,
        )
    )
```

The self-subscription uses `tags=["primary"]`, so only primary turn completions trigger reflection. Reflection completions emit with `tags=("reflection",)` which doesn't match, ending the chain.

**Depth budget protection.** Even with tag filtering, `TriggerPolicy` provides a safety net. The reflection turn consumes one depth slot on the same correlation_id. With `max_trigger_depth: 5`, this leaves 4 slots for real reactive cascades. If the depth budget is tight, the reflection self-subscription could use a *fresh* correlation_id to avoid depleting the primary chain's depth budget:

```python
# In Actor._run(), when processing a self-reflected AgentCompleteEvent:
if event.event_type == "AgentCompleteEvent" and "primary" in event.tags:
    correlation_id = f"reflect-{uuid.uuid4()}"  # fresh correlation
```

This isolates reflection depth from primary turn depth.

### 2.5 Solving the Double-Turn Cost

The appendix identified double-turn cost as Problem #1. The full actor turn cycle (workspace lookup, tool discovery, kernel creation, structured-agents framework, LLM call, tool execution loop) is heavy for metadata extraction. Mitigation strategies:

**Strategy 1: Cheaper model.** The `self_reflect.model` config allows using a smaller, faster model for reflection turns. A 1.7B model for "extract a summary and three tags" is fast and cheap. The bundle config override in `PromptBuilder.build_system_prompt()` checks for a reflection-specific model:

```python
def build_system_prompt(self, bundle_config, trigger_event):
    # If this is a reflection turn, use the reflection model
    is_reflection = (
        trigger_event is not None
        and trigger_event.event_type == "AgentCompleteEvent"
        and "primary" in getattr(trigger_event, "tags", ())
    )
    if is_reflection:
        reflect_config = bundle_config.get("self_reflect", {})
        model_name = reflect_config.get("model", model_name)
        max_turns = reflect_config.get("max_turns", 2)
    ...
```

**Strategy 2: Reduced tool set.** The reflection turn doesn't need all tools. It only needs `kv_set`, `kv_get`, `kv_list`, and possibly `graph_get_edges`. A `self_reflect.tools` config could whitelist which tools are available during reflection turns, reducing tool schema overhead in the LLM request:

```yaml
self_reflect:
  enabled: true
  model: "Qwen/Qwen3-1.7B"
  max_turns: 2
  tools:
    - kv_set
    - kv_get
    - kv_list
```

**Strategy 3: Separate semaphore.** Reflection turns currently compete with primary turns for the global semaphore. A dedicated `reflection_semaphore` (with lower concurrency, e.g., 1-2 slots) ensures reflections never block primary work:

```python
# In ActorPool or RuntimeServices:
self._reflection_semaphore = asyncio.Semaphore(config.reflection_concurrency or 1)
```

The turn executor checks whether this is a reflection turn and picks the appropriate semaphore.

**Strategy 4: Debouncing.** If an agent receives multiple triggers in quick succession (e.g., during a file-save cascade), each primary turn produces an `AgentCompleteEvent`. Rather than reflecting on every single turn, batch reflections: the agent reflects on the *most recent* primary turn and skips older ones. This is naturally handled by `TriggerPolicy.trigger_cooldown_ms` — if reflection events arrive within the cooldown window, the later ones are dropped.

### 2.6 Upgraded Companion Tools (KV-Native)

The existing system tools (`reflect.pym`, `categorize.pym`, `find_links.pym`, `summarize.pym`) write to workspace files. For companion metadata, KV is the right storage — structured data with atomic access, no JSON parse/serialize overhead, no concurrent-write risk.

New or upgraded tools needed:

**`companion_reflect.pym`** — Record a reflection insight to KV:
```python
from grail import Input, external

insight: str = Input("insight")

@external
async def kv_get(key: str) -> object: ...

@external
async def kv_set(key: str, value: object) -> bool: ...

import time
reflections = (await kv_get("companion/reflections")) or []
reflections.append({"timestamp": time.time(), "insight": insight})
# Keep last 30
await kv_set("companion/reflections", reflections[-30:])
result = "Reflection recorded"
result
```

**`companion_summarize.pym`** — Record a turn summary:
```python
from grail import Input, external

summary: str = Input("summary")
tags: str = Input("tags", default="")  # comma-separated

@external
async def kv_get(key: str) -> object: ...

@external
async def kv_set(key: str, value: object) -> bool: ...

import time
tag_list = [t.strip() for t in tags.split(",") if t.strip()]
index = (await kv_get("companion/chat_index")) or []
index.append({
    "timestamp": time.time(),
    "summary": summary,
    "tags": tag_list,
})
await kv_set("companion/chat_index", index[-50:])
result = f"Summary recorded with tags: {tag_list}"
result
```

**`companion_link.pym`** — Record a discovered cross-node reference:
```python
from grail import Input, external

target_node_id: str = Input("target_node_id")

@external
async def kv_get(key: str) -> object: ...

@external
async def kv_set(key: str, value: object) -> bool: ...

import time
links = (await kv_get("companion/links")) or []
existing_targets = {link["target"] for link in links}
if target_node_id not in existing_targets:
    links.append({"target": target_node_id, "timestamp": time.time()})
    await kv_set("companion/links", links)
    result = f"Link to {target_node_id} recorded"
else:
    result = f"Link to {target_node_id} already exists"
result
```

These tools would live in `bundles/system/tools/` and be available to all agents. The existing `reflect.pym`, `categorize.pym`, etc. can remain for backward compatibility or be replaced.

### 2.7 Prompt Engineering for Reliable Self-Reflection

The appendix identified prompt engineering as Problem #4. The reflection turn's quality depends entirely on the system/user prompt. Here's a concrete prompt design:

**System prompt extension** (added to bundle config for reflection turns):

```yaml
# bundles/code-agent/bundle.yaml
self_reflect:
  enabled: true
  model: "Qwen/Qwen3-1.7B"
  max_turns: 2
  prompt: |
    You just completed a conversation turn. Your job now is to extract and
    record structured metadata about that exchange for future reference.

    You MUST call these tools in order:
    1. companion_summarize — with a one-sentence summary and 1-3 tags
    2. companion_reflect — with one concrete insight worth remembering
       (or skip if the exchange was trivial)
    3. companion_link — for each other node referenced in the exchange
       (skip if none)

    Tag vocabulary: bug, question, refactor, explanation, test, performance,
    design, insight, todo, review

    Be specific. "Discussed error handling" is bad.
    "Null input to validate_email() silently returns True" is good.

    If the exchange was trivial (greeting, acknowledgment, no substance),
    call companion_summarize with a brief note and skip the rest.
```

The key prompt engineering choices:
- **Explicit tool call ordering.** Don't let the LLM decide whether to summarize — tell it to always summarize.
- **Concrete vocabulary.** Enumerate the tag options to reduce hallucination.
- **Quality examples.** Show the difference between vague and specific reflections.
- **Escape hatch for trivial turns.** Prevent the LLM from over-reflecting on "ok, thanks" exchanges.
- **max_turns: 2.** The reflection should complete in 1-2 tool-calling rounds. If it hasn't extracted metadata by then, it won't.

### 2.8 System Prompt Injection: Reading Companion Memory Back

The companion system is useless if agents don't see their accumulated knowledge. The system prompt must inject companion context. This is a modification to `PromptBuilder.build_system_prompt()` or a new step in `AgentTurnExecutor`:

```python
async def _build_companion_context(self, workspace: AgentWorkspace) -> str:
    sections = []

    reflections = await workspace.kv_get("companion/reflections") or []
    if reflections:
        recent = reflections[-5:]
        lines = [f"- {r['insight']}" for r in recent]
        sections.append("## My Observations\n" + "\n".join(lines))

    index = await workspace.kv_get("companion/chat_index") or []
    if index:
        recent = index[-3:]
        lines = [f"- {entry['summary']}" for entry in recent]
        sections.append("## Recent Conversations\n" + "\n".join(lines))

    links = await workspace.kv_get("companion/links") or []
    if links:
        lines = [f"- {link['target']}" for link in links[:8]]
        sections.append("## Related Nodes\n" + "\n".join(lines))

    return "\n\n".join(sections)
```

This gets appended to the system prompt *before* the primary turn (not the reflection turn). The agent sees its accumulated knowledge and uses it to inform its responses.

**Important:** This helper reads KV data inside the turn executor, which already has access to the workspace. No new permissions or service access needed.

### 2.9 Concrete Code Walkthrough

Files changed and created for Design A:

| File | Change | ~Lines |
|------|--------|--------|
| `core/actor.py` (`AgentTurnExecutor._complete_agent_turn`) | Add `tags=("primary",)` / `tags=("reflection",)` to `AgentCompleteEvent` | +8 |
| `core/actor.py` (`AgentTurnExecutor.execute_turn`) | Build and inject companion context into system prompt before primary turns | +15 |
| `core/actor.py` (`PromptBuilder.build_system_prompt`) | Handle `self_reflect` config: model override, max_turns override, reflection prompt | +20 |
| `core/actor.py` (`AgentTurnExecutor._build_companion_context`) | NEW: Read KV companion data, format as system prompt section | +30 |
| `core/actor.py` (`AgentTurnExecutor._read_bundle_config`) | Parse `self_reflect` section from bundle.yaml | +10 |
| `code/reconciler.py` (`_register_subscriptions`) | If `self_reflect.enabled`, register self-subscription with tag filter | +15 |
| `code/reconciler.py` (`_provision_bundle`) | Read bundle.yaml to check self_reflect before subscription registration | +5 |
| `bundles/system/tools/companion_reflect.pym` | NEW: KV-native reflection tool | ~15 |
| `bundles/system/tools/companion_summarize.pym` | NEW: KV-native summary+tags tool | ~20 |
| `bundles/system/tools/companion_link.pym` | NEW: KV-native link recording tool | ~15 |
| `bundles/code-agent/bundle.yaml` | Add `self_reflect` section with prompt | +15 |
| `web/server.py` | Add `GET /api/nodes/{node_id}/companion` endpoint | +15 |
| **Total** | | **~183** |

### 2.10 Strengths and Remaining Weaknesses

**Strengths:**
- Purest v2 alignment — agents manage themselves, no external systems
- No cross-workspace access — each agent writes to its own KV
- No new core abstractions — uses subscriptions, bundles, tools, events
- Richer reflections — agent has full context (history, workspace, source code)
- Naturally per-bundle-configurable — bundles opt in via `self_reflect` section
- Progressive enhancement — existing agents gain companion memory just by enabling the config

**Remaining weaknesses:**
- **LLM reliability.** A small model might not consistently call the right tools or produce useful metadata. Prompt engineering helps but doesn't guarantee.
- **Cost.** Even with a cheap model, every primary turn triggers a reflection turn. For a project with 50 active agents, that's 50 additional LLM calls per activity burst.
- **No cross-agent view.** Each agent knows only itself. No system-wide patterns, no "which agents discussed similar topics," no project health dashboard.
- **Semaphore pressure.** Even with a dedicated reflection semaphore, reflection turns add to the total concurrent LLM calls.
- **Debugging.** When reflection metadata is wrong (bad summary, wrong tags), the debugging path is: read the agent's event history → find the reflection turn → read the LLM response → understand why it made bad tool calls. Harder to diagnose than a deterministic function.

---

## 3. Design C Expanded: Scoped Workspace Delegation

### 3.1 Philosophy: Principled Cross-Agent Capability

The v2 sandbox model exists for a good reason: agents shouldn't casually write to each other's state. But some system-level operations *need* cross-agent access. Bundle provisioning already does this — `FileReconciler` writes `_bundle/` files into agent workspaces during reconciliation. The question isn't "should cross-workspace access exist?" (it already does), but "how should it be governed?"

Design C's answer: **explicit, scoped, configuration-declared delegation.** An agent gets cross-workspace write access only if:
1. The project admin declares it in `remora.yaml`
2. The delegation specifies which KV prefix is writable
3. The delegation specifies which target agents are in scope

This is the principle of least privilege applied to the agent graph. It's more restrictive than `FileReconciler`'s implicit full-workspace access (which exists because bundle provisioning is a bootstrap concern, not a runtime concern).

### 3.2 The Delegation Model in Detail

A delegation grant has three components:

```
WHO can write  →  the delegating agent's ID (companion-observer)
WHERE they write →  target agents (scope: "all" | list of IDs | "virtual" | "code")
WHAT they write  →  KV key prefix (e.g., "companion/")
```

At runtime, when `companion-observer` calls `delegated_kv_set("agent-X", "companion/chat_index", [...])`:
1. TurnContext checks: does this agent have a delegation grant?
2. Does the grant's scope include `agent-X`?
3. Does the key `companion/chat_index` start with the grant's prefix `companion/`?
4. If all checks pass, write to agent-X's workspace KV via `CairnWorkspaceService`.

Reads follow the same pattern: `delegated_kv_get("agent-X", "companion/reflections")` checks scope and prefix before reading.

### 3.3 Config Schema Changes

**`VirtualAgentConfig` extension:**

```python
class WorkspaceDelegation(BaseModel):
    """Scoped cross-workspace access grant."""
    kv_prefix: str                                # e.g., "companion/"
    scope: str | tuple[str, ...] = "all"          # "all", node_type, or explicit IDs
    read: bool = True                             # allow delegated_kv_get
    write: bool = True                            # allow delegated_kv_set

class VirtualAgentConfig(BaseModel):
    id: str
    role: str
    subscriptions: tuple[VirtualSubscriptionConfig, ...] = ()
    workspace_delegations: tuple[WorkspaceDelegation, ...] = ()  # NEW
```

**Example configuration:**

```yaml
virtual_agents:
  - id: companion-observer
    role: companion
    subscriptions:
      - event_types: ["AgentCompleteEvent"]
    workspace_delegations:
      - kv_prefix: "companion/"
        scope: "all"
        read: true
        write: true
```

More restrictive example — only write to code agents, not virtual agents:

```yaml
    workspace_delegations:
      - kv_prefix: "companion/"
        scope: ["function", "class", "method", "file"]
        write: true
        read: true
```

### 3.4 Runtime Plumbing: Config → TurnContext

The challenge identified in the appendix: TurnContext is instantiated with raw parameters in `_prepare_turn_context()` and knows nothing about the agent's `VirtualAgentConfig`. We need to thread the delegation config through.

**Option A: Pass delegation config to TurnContext constructor.**

```python
class TurnContext:
    def __init__(
        self,
        ...
        workspace_delegations: tuple[WorkspaceDelegation, ...] = (),
        workspace_service: CairnWorkspaceService | None = None,
    ):
        self._workspace_delegations = workspace_delegations
        self._workspace_service = workspace_service
```

`AgentTurnExecutor._prepare_turn_context()` needs access to the delegation config. Since the executor already reads bundle config, the delegation config can be stored as a KV entry during bundle provisioning:

```python
# In FileReconciler._sync_virtual_agents(), after _provision_bundle():
if spec.workspace_delegations:
    workspace = await self._workspace_service.get_agent_workspace(spec.id)
    await workspace.kv_set(
        "_system/workspace_delegations",
        [d.model_dump() for d in spec.workspace_delegations],
    )
```

Then `_prepare_turn_context()` reads it:

```python
async def _prepare_turn_context(self, node_id, workspace, trigger, outbox):
    # Read delegation config from workspace KV
    raw_delegations = await workspace.kv_get("_system/workspace_delegations") or []
    delegations = tuple(WorkspaceDelegation(**d) for d in raw_delegations)

    context = TurnContext(
        ...
        workspace_delegations=delegations,
        workspace_service=self._workspace_service if delegations else None,
    )
```

`CairnWorkspaceService` is only passed to TurnContext when delegations exist. Regular agents never see it.

**Option B: Delegation registry as a service.**

Instead of passing delegation config per-turn, maintain a `DelegationRegistry` in `RuntimeServices` that TurnContext queries:

```python
class DelegationRegistry:
    async def check(self, caller_id: str, target_id: str, key: str) -> bool: ...
    async def get_workspace(self, target_id: str) -> AgentWorkspace: ...
```

This is cleaner but adds a new service to the runtime. Option A is simpler for a single use case.

**Recommendation: Option A.** Keep it simple. Store delegation config in the agent's workspace KV during provisioning, read it during turn context creation.

### 3.5 The `delegated_kv_set` Capability

New methods on `TurnContext`:

```python
async def delegated_kv_set(self, agent_id: str, key: str, value: Any) -> bool:
    """Write to another agent's KV store under a delegated prefix."""
    self._check_delegation(agent_id, key, write=True)
    workspace = await self._workspace_service.get_agent_workspace(agent_id)
    await workspace.kv_set(key, value)
    return True

async def delegated_kv_get(self, agent_id: str, key: str) -> Any | None:
    """Read from another agent's KV store under a delegated prefix."""
    self._check_delegation(agent_id, key, read=True)
    workspace = await self._workspace_service.get_agent_workspace(agent_id)
    return await workspace.kv_get(key)

def _check_delegation(self, target_id: str, key: str, read: bool = False, write: bool = False):
    """Verify this agent has delegation authority for the target + key."""
    if not self._workspace_delegations:
        raise PermissionError(f"No workspace delegations configured for this agent")

    for delegation in self._workspace_delegations:
        if not key.startswith(delegation.kv_prefix):
            continue
        if write and not delegation.write:
            continue
        if read and not delegation.read:
            continue
        if self._scope_matches(delegation.scope, target_id):
            return  # authorized

    raise PermissionError(
        f"No delegation grant covers agent={target_id} key={key}"
    )

def _scope_matches(self, scope: str | tuple[str, ...], target_id: str) -> bool:
    if scope == "all":
        return True
    if isinstance(scope, str):
        scope = (scope,)
    # scope entries can be node types or specific IDs
    # This would need node_store lookup to check node_type,
    # or the scope check can be done at a higher level
    return target_id in scope
```

These are added to `to_capabilities_dict()` only when delegations exist:

```python
def to_capabilities_dict(self) -> dict[str, Any]:
    caps = {
        "read_file": self.read_file,
        ...  # existing capabilities
    }
    if self._workspace_delegations:
        caps["delegated_kv_set"] = self.delegated_kv_set
        caps["delegated_kv_get"] = self.delegated_kv_get
    return caps
```

### 3.6 Grail Tool: `delegated_kv_set.pym`

```python
# Write companion data to another agent's KV store (requires delegation).
from grail import Input, external

agent_id: str = Input("agent_id")
key: str = Input("key")
value: str = Input("value")  # JSON string

@external
async def delegated_kv_set(agent_id: str, key: str, value: object) -> bool: ...

import json
parsed = json.loads(value)
success = await delegated_kv_set(agent_id, key, parsed)
result = f"KV set for {agent_id}/{key}: {'ok' if success else 'failed'}"
result
```

And a corresponding read tool:

```python
# Read companion data from another agent's KV store (requires delegation).
from grail import Input, external

agent_id: str = Input("agent_id")
key: str = Input("key")

@external
async def delegated_kv_get(agent_id: str, key: str) -> object: ...

data = await delegated_kv_get(agent_id, key)
import json
result = json.dumps(data) if data is not None else "null"
result
```

These tools live in `bundles/companion/tools/` — only provisioned to agents with the `companion` role.

### 3.7 Observer Bundle Design

```yaml
# bundles/companion/bundle.yaml
name: companion
system_prompt: |
  You are a companion observer agent. Your job is to analyze completed agent
  turns and extract structured metadata for the originating agent.

  When you receive an AgentCompleteEvent, you must:
  1. Read the agent_id and full_response from the event
  2. Use delegated_kv_get to read the agent's existing companion data
  3. Generate a one-sentence summary, 1-3 tags, and one insight
  4. Use delegated_kv_set to update the agent's companion KV data

  KV keys to write (under companion/ prefix):
  - companion/chat_index: list of {timestamp, summary, tags}
  - companion/reflections: list of {timestamp, insight}
  - companion/links: list of {target, timestamp}

  Tag vocabulary: bug, question, refactor, explanation, test, performance,
  design, insight, todo, review

  Be specific in summaries and reflections. Skip trivial exchanges.
prompts:
  reactive: |
    An agent just completed a turn. Analyze the exchange and record metadata.
    The agent_id and response content are in the trigger event.
    Use delegated_kv_get to read existing companion data, then use
    delegated_kv_set to append new entries.
model: "Qwen/Qwen3-1.7B"
max_turns: 4
```

### 3.8 Solving the Self-Trigger Loop

The observer subscribes to `AgentCompleteEvent`. When it finishes processing, it emits its own `AgentCompleteEvent`. Without filtering, the dispatcher routes this back to the observer (its subscription matches `AgentCompleteEvent`).

**Solution: Exclude self from subscription.**

The subscription pattern doesn't have a "not from" filter, but `AgentCompleteEvent` has an `agent_id` field. We can add a `not_from_agents` field to `SubscriptionPattern`:

```python
class SubscriptionPattern(BaseModel):
    event_types: list[str] | None = None
    from_agents: list[str] | None = None
    not_from_agents: list[str] | None = None  # NEW: exclusion filter
    to_agent: str | None = None
    path_glob: str | None = None
    tags: list[str] | None = None

    def matches(self, event: Event) -> bool:
        ...
        if self.not_from_agents:
            agent_id = getattr(event, "agent_id", None)
            if agent_id in self.not_from_agents:
                return False
        ...
```

Config:
```yaml
virtual_agents:
  - id: companion-observer
    role: companion
    subscriptions:
      - event_types: ["AgentCompleteEvent"]
        not_from_agents: ["companion-observer"]
```

**Alternative: Tag filtering.** If Design A's tag system is also implemented, the observer subscribes to `tags: ["primary"]` and never sees reflection events or its own events (which would be tagged differently).

### 3.9 What the Observer Sees (AgentCompleteEvent Enrichment)

Current `AgentCompleteEvent` fields:
- `agent_id: str` — which agent completed
- `result_summary: str` — first 200 chars of response
- `full_response: str` — complete response text
- `correlation_id: str | None`

**Missing: the user message.** The observer needs both sides of the exchange for good summaries. Solutions:

**Option 1: Add `user_message` to AgentCompleteEvent.**

```python
class AgentCompleteEvent(Event):
    agent_id: str
    result_summary: str = ""
    full_response: str = ""
    user_message: str = ""  # NEW
```

In `_complete_agent_turn()`, the user message is available as `messages[1].content` from the turn executor. Pass it through:

```python
await outbox.emit(
    AgentCompleteEvent(
        agent_id=node_id,
        result_summary=response_text[:200],
        full_response=response_text,
        user_message=user_message,  # from the trigger/messages
        correlation_id=trigger.correlation_id,
    )
)
```

**Cost:** Adds ~100-1000 bytes per event to SQLite storage. Acceptable — events already store `full_response` which can be much larger.

**Option 2: Observer queries event history.**

The observer uses `event_get_history(agent_id)` to find the preceding events and reconstruct the user message. More complex, adds latency, and the tool calling overhead may not be worth it.

**Recommendation: Option 1.** Simple, low cost, and useful beyond just the observer.

### 3.10 Concrete Code Walkthrough

Files changed and created for Design C:

| File | Change | ~Lines |
|------|--------|--------|
| `core/config.py` | Add `WorkspaceDelegation` model, `workspace_delegations` field to `VirtualAgentConfig` | +20 |
| `core/externals.py` (`TurnContext`) | Add `delegated_kv_set`, `delegated_kv_get`, `_check_delegation`, `_scope_matches`. Add `workspace_delegations` and `workspace_service` constructor params. Conditionally expose in `to_capabilities_dict()`. | +50 |
| `core/events/types.py` | Add `user_message` field to `AgentCompleteEvent` | +2 |
| `core/events/subscriptions.py` | Add `not_from_agents` field to `SubscriptionPattern`, update `matches()` | +8 |
| `core/actor.py` (`AgentTurnExecutor._complete_agent_turn`) | Pass `user_message` to `AgentCompleteEvent` | +3 |
| `core/actor.py` (`AgentTurnExecutor._prepare_turn_context`) | Read delegation config from workspace KV, pass to TurnContext | +10 |
| `core/actor.py` (`AgentTurnExecutor._build_companion_context`) | Same as Design A — read companion KV for system prompt injection | +30 |
| `code/reconciler.py` (`_sync_virtual_agents`) | Store delegation config in workspace KV during provisioning | +8 |
| `bundles/companion/bundle.yaml` | NEW: Observer bundle with system prompt | ~30 |
| `bundles/companion/tools/delegated_kv_set.pym` | NEW: Cross-workspace KV write tool | ~15 |
| `bundles/companion/tools/delegated_kv_get.pym` | NEW: Cross-workspace KV read tool | ~15 |
| `web/server.py` | Add `GET /api/nodes/{node_id}/companion` endpoint | +15 |
| **Total** | | **~206** |

### 3.11 Strengths and Remaining Weaknesses

**Strengths:**
- Observer is a first-class agent — visible in graph, has metrics, events, history
- Cross-agent by design — can read any agent's companion data to find patterns
- Principled sandboxing — delegation is explicit, scoped, revocable
- Behavior is fully bundle-configurable — prompt + tools, no core code for behavior changes
- `not_from_agents` subscription filter is generally useful beyond companion
- `user_message` on `AgentCompleteEvent` is generally useful beyond companion
- `WorkspaceDelegation` is a reusable primitive for future cross-agent features

**Remaining weaknesses:**
- **Full actor turn cost.** Semaphore slot, workspace setup, tool discovery, kernel, LLM call, tool execution. For metadata extraction, this is heavy.
- **New abstraction surface.** `WorkspaceDelegation`, `delegated_kv_set`, `not_from_agents` — three new concepts for one feature. If companion is the only consumer, the abstraction-to-use ratio is high.
- **Observer context poverty.** The observer sees event payloads, not agent state. It can `delegated_kv_get` to read prior companion data, but it doesn't see the agent's conversation history, workspace files, or source code. Reflection quality may be lower than self-directed (Design A) where the agent has full context.
- **Sequential bottleneck.** One observer processes all agents sequentially (single actor, single inbox). During active periods, the observer's inbox fills up and companion data lags.
- **Prompt/tool indirection.** The observer must decide to call `delegated_kv_get`, then `delegated_kv_set`, via LLM tool calling. Each tool call is a round trip through the structured-agents framework. A direct function call would be 10x faster.

---

## 4. A+C Combined: Self-Directed Agents + Delegated Observer

### 4.1 Why Combine Them?

Design A and Design C solve different problems:

| Problem | Design A (Self-Directed) | Design C (Observer) |
|---------|:-:|:-:|
| Per-agent reflection | ✅ Native | ⚠️ Works but lacks context |
| Per-agent memory accumulation | ✅ Direct KV access | ⚠️ Via delegation |
| Cross-agent pattern detection | ❌ Impossible | ✅ Sees all events |
| Project health dashboard | ❌ No aggregate view | ✅ Can build one |
| Relationship discovery across agents | ❌ Only own edges | ✅ Can correlate across |
| Behavior customizability | ⚠️ Via reflection prompt | ✅ Full bundle control |
| Context richness | ✅ Full agent state | ❌ Event payloads only |

Combining them creates a two-layer architecture where each layer does what it's best at:
- **Layer 1 (Self-Directed):** Each agent reflects on its own turns with full context. Produces per-agent metadata (summary, tags, reflection, links) in its own KV store.
- **Layer 2 (Observer):** A cross-agent observer reads `TurnDigestedEvent`s (or companion KV data) to build aggregate views. Detects patterns, correlates activity, builds project-level insights. Writes to its *own* workspace (no cross-workspace writes needed for aggregation).

### 4.2 Architecture: Two Layers of Companion Intelligence

```
                     ┌─────────────────────────────────────────────┐
                     │           Layer 2: Observer                  │
                     │  companion-observer virtual agent            │
                     │  Subscribes to: TurnDigestedEvent           │
                     │  Writes to: own workspace (project insights)│
                     │  Reads from: event payloads                 │
                     └─────────────┬───────────────────────────────┘
                                   │ reads TurnDigestedEvents
                     ┌─────────────┴───────────────────────────────┐
    ┌────────────────┤            Event Stream                      ├────────────────┐
    │                └─────────────────────────────────────────────┘                 │
    │ TurnDigestedEvent                                              TurnDigestedEvent
    │                                                                                │
┌───┴──────────────────┐                                     ┌──────────────────────┴───┐
│  Agent: validate()   │                                     │  Agent: test_validate()  │
│  Layer 1: self-reflect│                                    │  Layer 1: self-reflect    │
│  KV: companion/*     │                                     │  KV: companion/*          │
└──────────────────────┘                                     └──────────────────────────┘
```

### 4.3 Layer 1: Self-Directed (Per-Agent, Every Turn)

Exactly as described in Section 2. Each agent:
- Has `self_reflect.enabled: true` in its bundle config
- Self-subscribes to its own `AgentCompleteEvent` (tag-filtered to `"primary"`)
- Runs a reflection turn using companion tools (`companion_summarize`, `companion_reflect`, `companion_link`)
- Writes metadata to its own `companion/` KV keys
- Emits `TurnDigestedEvent` when reflection is complete

The `TurnDigestedEvent` is the bridge to Layer 2:

```python
class TurnDigestedEvent(Event):
    agent_id: str
    summary: str = ""
    tags: tuple[str, ...] = ()
    has_reflection: bool = False
    has_links: bool = False
```

This event is emitted by the reflection turn's companion tools (or by a final step in the reflection prompt). It carries just enough metadata for the observer to decide whether to investigate further.

### 4.4 Layer 2: Delegated Observer (Cross-Agent, Periodic)

The observer virtual agent subscribes to `TurnDigestedEvent` (not `AgentCompleteEvent`). This means:
- It only fires after Layer 1 has already extracted per-agent metadata
- The event payload includes pre-extracted summaries and tags (from Layer 1)
- The observer doesn't need to re-extract this metadata — it can focus on cross-agent analysis

The observer's job becomes:
1. Receive `TurnDigestedEvent` from various agents
2. Accumulate activity patterns in its own workspace KV
3. Periodically (or when triggered by volume thresholds) analyze cross-agent patterns
4. Write project-level insights to its own `project/` KV keys

**No cross-workspace writes needed.** The observer reads from event payloads (which already contain the summary and tags from Layer 1) and writes only to its own workspace. The delegation model from Section 3 is *not required* in the combined design.

The observer's bundle:

```yaml
# bundles/companion/bundle.yaml
name: companion
system_prompt: |
  You are the project companion observer. You see TurnDigestedEvent
  notifications from all agents. Your job is to:
  1. Track which agents are most active and what topics they discuss
  2. Identify patterns: recurring bugs, clusters of related changes,
     agents that frequently reference each other
  3. Maintain a project activity dashboard in your KV store
  4. When you notice significant patterns, emit insights

  Do NOT re-analyze individual turns — agents already did that.
  Focus on the cross-agent, project-level view.
```

### 4.5 How the Layers Interact

**Layer 1 feeds Layer 2 via events.** The observer never needs to read another agent's workspace. The event stream carries enough information.

**Layer 2 does not feed back to Layer 1.** Agents don't read the observer's insights. This avoids circular dependencies. If we later want agents to benefit from project-level insights, the observer can emit `ProjectInsightEvent`s that agents subscribe to — but that's a future enhancement.

**Timing:** Layer 1 completes first (milliseconds after the primary turn, since it's the next inbox event). Layer 2 fires after Layer 1 emits `TurnDigestedEvent`. There's a natural ordering without explicit coordination.

### 4.6 Configuration for the Combined System

```yaml
# remora.yaml

# Layer 2: Project-level observer (optional)
virtual_agents:
  - id: companion-observer
    role: companion
    subscriptions:
      - event_types: ["TurnDigestedEvent"]
```

```yaml
# bundles/code-agent/bundle.yaml

# Layer 1: Per-agent self-reflection
self_reflect:
  enabled: true
  model: "Qwen/Qwen3-1.7B"
  max_turns: 2
  prompt: |
    You just completed a conversation turn. Extract and record metadata...
```

Layer 1 and Layer 2 are independently configurable:
- Enable Layer 1 only: agents self-reflect, no project-level analysis
- Enable Layer 2 only: observer receives `AgentCompleteEvent` directly and does all extraction (falls back to Design C with delegation)
- Enable both: full two-layer companion system
- Enable neither: no companion features

### 4.7 Concrete Scenario Walkthrough

Scenario: A developer asks the `validate_email()` agent about an edge case with Unicode domain names.

**Step 1: Primary turn.**
- User sends message to `validate_email()` agent
- Agent runs LLM turn, uses tools, responds
- `_complete_agent_turn()` emits `AgentCompleteEvent(agent_id="validate_email", tags=("primary",), full_response="...", user_message="...")`

**Step 2: Self-reflection (Layer 1).**
- The `AgentCompleteEvent` matches validate_email's self-subscription (event_type match, from_agents match, tag match)
- Event lands in validate_email's inbox
- Agent runs reflection turn with cheaper model
- LLM calls:
  - `companion_summarize(summary="Discussed Unicode domain edge case in RFC 5321 validation", tags="bug,edge_case")`
  - `companion_reflect(insight="Current regex rejects valid internationalized domain names — needs IDN/punycode handling")`
  - `companion_link(target_node_id="test_validate_email")` (the test function was mentioned)
- Reflection turn emits `AgentCompleteEvent(tags=("reflection",))` — no self-trigger (tag filter)
- Reflection turn also emits `TurnDigestedEvent(agent_id="validate_email", summary="...", tags=("bug", "edge_case"), has_reflection=True, has_links=True)`

**Step 3: Observer analysis (Layer 2).**
- `TurnDigestedEvent` matches companion-observer's subscription
- Observer receives the event, notes: validate_email discussed a bug related to edge_case
- Observer updates its own KV:
  - `project/activity_log`: appends entry
  - `project/tag_frequency`: increments "bug" and "edge_case" counts
  - `project/agent_activity`: updates validate_email's last-active time and topic
- If observer has seen several "bug" tags recently, it might emit a `ProjectInsightEvent`: "Bug cluster detected in validation module — 3 agents reported bugs in the last hour"

**Step 4: Next primary turn.**
- When validate_email's next primary turn starts, `_build_companion_context()` reads:
  - `companion/reflections` → includes "Current regex rejects valid internationalized domain names"
  - `companion/chat_index` → includes the Unicode domain discussion summary
  - `companion/links` → includes reference to `test_validate_email`
- This context is injected into the system prompt
- The agent now knows about the IDN issue from its prior reflection — continuity across sessions

### 4.8 Implementation Phasing

**Phase 1: Self-Directed Foundation (Design A only)**
- Implement self_reflect bundle config
- Create companion_* Grail tools (KV-native)
- Tag-based turn classification (primary/reflection)
- Self-subscription registration in reconciler
- Companion context injection in system prompt
- Web endpoint for companion data
- `TurnDigestedEvent` emission

**Phase 2: Observer Layer (Design C addition)**
- companion-observer virtual agent config
- Companion bundle (prompt + tools)
- Observer subscribes to `TurnDigestedEvent`
- Observer builds project-level insights in own workspace
- Web endpoint for project-level companion data

**Phase 3: Advanced features (future)**
- Observer emits `ProjectInsightEvent` for agent consumption
- Cross-agent link correlation (observer notices when multiple agents reference the same targets)
- Activity anomaly detection
- Project health dashboard in web UI

Phase 1 is self-contained and delivers the core companion experience. Phase 2 adds cross-agent intelligence. Phase 3 builds on both.

### 4.9 Cost Analysis

**Per primary turn:**

| Component | LLM Calls | Semaphore Slots | Latency Added |
|-----------|:---------:|:---------------:|:-------------:|
| Layer 1 (self-reflect) | 1 (cheap model) | 1 (can be reflection-only) | 1-3s |
| Layer 2 (observer) | 1 (cheap model) | 1 | 1-3s |
| **A+C total** | **2** | **2** | **2-6s (parallel)** |
| Inline hooks (comparison) | 1 | 0 | <1s |

The combined approach is more expensive than inline hooks. The trade-off: richer per-agent context (Layer 1) and cross-agent intelligence (Layer 2) vs. lower cost (inline hooks).

**Cost mitigation:**
- Use very small models (1.7B) for both layers
- Layer 2 can batch: process every Nth digest event rather than every one
- Layer 1 reflection can be rate-limited via cooldown_ms
- Both layers use separate semaphore pools to avoid blocking primary work

### 4.10 What This Enables That Neither Design Alone Can

1. **Self-aware agents with project-wide context.** Agents know themselves (Layer 1) and the observer knows the project (Layer 2). Neither layer alone achieves both.

2. **Rich per-agent metadata WITH cross-agent correlation.** Layer 1 produces high-quality reflections (full agent context). Layer 2 correlates those reflections across the graph. "validate_email discovered an IDN bug" + "parse_domain also discussed IDN issues" → "IDN handling is a systemic gap in the validation module."

3. **Independent scaling.** Layer 1 scales with agent count (each agent reflects independently). Layer 2 is a single observer that can be tuned for throughput. Disable Layer 2 to cut costs without losing per-agent companion memory.

4. **No cross-workspace writes.** Unlike standalone Design C, the combined design doesn't need workspace delegation for the observer. Layer 1 writes to own workspace. Layer 2 reads from events and writes to own workspace. The delegation model becomes optional/future-only.

5. **Natural quality gradient.** Layer 1 reflections are rich (full context) but local. Layer 2 insights are thinner (event payloads only) but global. Users get the best of both: detailed agent-level companion data plus high-level project patterns.

---

## 5. Comparison: A vs C vs A+C

| Dimension | Design A (Self-Directed) | Design C (Observer) | A+C Combined |
|-----------|:-:|:-:|:-:|
| v2 alignment | ✅ Best | ⚠️ Good | ✅ Best |
| Per-agent reflection quality | ✅ Full context | ⚠️ Event payloads only | ✅ Full context (Layer 1) |
| Cross-agent intelligence | ❌ None | ✅ Native | ✅ Via Layer 2 |
| Cross-workspace writes needed | ❌ No | ✅ Yes (delegation) | ❌ No |
| New abstractions | Low (self_reflect config, tag filter) | High (delegation, scoped KV, new tools) | Low (Layer 2 uses standard virtual agent) |
| LLM cost per primary turn | 1 call | 1 call | 2 calls |
| Semaphore impact | 1 slot | 1 slot | 2 slots (separate pools) |
| Implementation complexity | ~183 lines | ~206 lines | ~230 lines (additive) |
| Phase 1 standalone value | ✅ Full companion experience | ⚠️ Needs delegation for KV writes | ✅ Full companion experience |
| Phase 2 enhancement | Add observer (A+C) | Already has observer | Already combined |
| Failure isolation | Agent-local | Observer failure affects all | Layer 1 independent, Layer 2 additive |
| Debugging | Read agent's reflection history | Read observer's history | Both available |

**Summary of trade-offs:**

- **Choose A alone** if: per-agent companion memory is the primary need, cost should be minimal, and cross-agent features aren't needed yet. Simplest path with strongest v2 alignment.

- **Choose C alone** if: cross-agent intelligence is the primary need and per-agent reflection quality can be lower. Requires the delegation model, which is more invasive.

- **Choose A+C** if: both per-agent and cross-agent companion features are desired, and the cost of two LLM calls per turn is acceptable. The combined design avoids the cross-workspace problem entirely (Layer 2 reads events, writes to own workspace) while delivering the richest companion experience. The main cost is two LLM calls instead of one — but both can use cheap models.
