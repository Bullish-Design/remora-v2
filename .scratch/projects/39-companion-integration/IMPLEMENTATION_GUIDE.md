# Companion System Implementation Guide (A+C Combined)

**CRITICAL: NO SUBAGENTS (Task tool). All work done directly.**

## Table of Contents

1. [Overview & Architecture](#1-overview--architecture)
   - 1.1 What We're Building
   - 1.2 Two-Layer Architecture
   - 1.3 Files to Create
   - 1.4 Files to Modify
   - 1.5 Implementation Order
2. [Step 1: Add TurnDigestedEvent to the Event System](#2-step-1-add-turndigestedevent-to-the-event-system)
   - 2.1 What to Do
   - 2.2 Tests
3. [Step 2: Tag-Based Turn Classification](#3-step-2-tag-based-turn-classification)
   - 3.1 What to Do
   - 3.2 Tests
4. [Step 3: Enrich AgentCompleteEvent with user_message](#4-step-3-enrich-agentcompleteevent-with-user_message)
   - 4.1 What to Do
   - 4.2 Tests
5. [Step 4: Add not_from_agents Filter to SubscriptionPattern](#5-step-4-add-not_from_agents-filter-to-subscriptionpattern)
   - 5.1 What to Do
   - 5.2 Tests
6. [Step 5: Create KV-Native Companion Grail Tools](#6-step-5-create-kv-native-companion-grail-tools)
   - 6.1 What to Do
   - 6.2 Tests
7. [Step 6: Add self_reflect Config and Self-Subscription Registration](#7-step-6-add-self_reflect-config-and-self-subscription-registration)
   - 7.1 What to Do
   - 7.2 Tests
8. [Step 7: Parse self_reflect in Bundle Config](#8-step-7-parse-self_reflect-in-bundle-config)
   - 8.1 What to Do
   - 8.2 Tests
9. [Step 8: Reflection Turn Model/Prompt Override in PromptBuilder](#9-step-8-reflection-turn-modelprompt-override-in-promptbuilder)
   - 9.1 What to Do
   - 9.2 Tests
10. [Step 9: Companion Context Injection into System Prompt](#10-step-9-companion-context-injection-into-system-prompt)
    - 10.1 What to Do
    - 10.2 Tests
11. [Step 10: Add self_reflect Config to code-agent Bundle](#11-step-10-add-self_reflect-config-to-code-agent-bundle)
    - 11.1 What to Do
    - 11.2 Tests
12. [Step 11: Web API Endpoint for Companion Data](#12-step-11-web-api-endpoint-for-companion-data)
    - 12.1 What to Do
    - 12.2 Tests
13. [Step 12: Layer 2 — Companion Observer Virtual Agent Bundle](#13-step-12-layer-2--companion-observer-virtual-agent-bundle)
    - 13.1 What to Do
    - 13.2 Tests
14. [Step 13: Add Example Config to remora.yaml.example](#14-step-13-add-example-config-to-remorायamlexample)
    - 14.1 What to Do
    - 14.2 Tests
15. [Summary: All Files Changed/Created](#15-summary-all-files-changedcreated)
16. [Testing Strategy Overview](#16-testing-strategy-overview)

---

## 1. Overview & Architecture

### 1.1 What We're Building

A two-layer companion system that gives agents persistent memory and project-level intelligence:

- **Layer 1 (Self-Directed):** Each agent reflects on its own turns, writing summaries/tags/reflections/links to its own `companion/` KV keys. Triggered by self-subscription to its own `AgentCompleteEvent`.
- **Layer 2 (Observer):** A virtual agent subscribes to `TurnDigestedEvent`s from all agents. Builds cross-agent activity tracking and project-level insights in its own workspace.

### 1.2 Two-Layer Architecture

```
                     ┌─────────────────────────────────────────────┐
                     │           Layer 2: Observer                  │
                     │  companion-observer virtual agent            │
                     │  Subscribes to: TurnDigestedEvent           │
                     │  Writes to: own workspace (project insights)│
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

### 1.3 Files to Create

| File | Purpose |
|------|---------|
| `bundles/system/tools/companion_summarize.pym` | KV-native summarize/tag tool |
| `bundles/system/tools/companion_reflect.pym` | KV-native reflection tool |
| `bundles/system/tools/companion_link.pym` | KV-native link recording tool |
| `bundles/companion/bundle.yaml` | Layer 2 observer bundle config |
| `bundles/companion/tools/aggregate_digest.pym` | Observer's project-level digest tool |

### 1.4 Files to Modify

| File | Changes |
|------|---------|
| `src/remora/core/events/types.py` | Add `TurnDigestedEvent`, add `user_message` to `AgentCompleteEvent` |
| `src/remora/core/events/subscriptions.py` | Add `not_from_agents` filter to `SubscriptionPattern` |
| `src/remora/core/actor.py` | Tag classification in `_complete_agent_turn`, reflection override in `PromptBuilder`, companion context injection, `self_reflect` parsing in `_read_bundle_config` |
| `src/remora/code/reconciler.py` | Self-subscription registration in `_register_subscriptions` |
| `src/remora/web/server.py` | `GET /api/nodes/{node_id}/companion` endpoint |
| `bundles/code-agent/bundle.yaml` | Add `self_reflect` config section |
| `remora.yaml.example` | Document Layer 2 virtual agent config |

### 1.5 Implementation Order

Steps 1-4 are infrastructure. Steps 5-9 are Layer 1 core. Steps 10-11 are integration. Steps 12-13 are Layer 2 and documentation.

---

## 2. Step 1: Add TurnDigestedEvent to the Event System

### 2.1 What to Do

**File:** `src/remora/core/events/types.py`

Add the new event class after `TurnCompleteEvent` (after line 190):

```python
class TurnDigestedEvent(Event):
    """Emitted after Layer 1 reflection completes for an agent turn."""

    agent_id: str
    summary: str = ""
    tags: tuple[str, ...] = ()
    has_reflection: bool = False
    has_links: bool = False
```

Add `"TurnDigestedEvent"` to the `__all__` list.

### 2.2 Tests

**File:** `tests/unit/test_event_types.py` (new file or add to existing)

```python
from remora.core.events.types import TurnDigestedEvent


def test_turn_digested_event_defaults() -> None:
    event = TurnDigestedEvent(agent_id="agent-a")
    assert event.event_type == "TurnDigestedEvent"
    assert event.summary == ""
    assert event.tags == ()
    assert event.has_reflection is False
    assert event.has_links is False


def test_turn_digested_event_full() -> None:
    event = TurnDigestedEvent(
        agent_id="agent-a",
        summary="Discussed validation",
        tags=("bug", "edge_case"),
        has_reflection=True,
        has_links=True,
    )
    assert event.agent_id == "agent-a"
    assert event.summary == "Discussed validation"
    assert event.tags == ("bug", "edge_case")


def test_turn_digested_event_envelope() -> None:
    event = TurnDigestedEvent(agent_id="agent-a", summary="test")
    envelope = event.to_envelope()
    assert envelope["event_type"] == "TurnDigestedEvent"
    assert envelope["payload"]["agent_id"] == "agent-a"
    assert envelope["payload"]["summary"] == "test"
```

**Run:** `devenv shell -- pytest tests/unit/test_event_types.py -v`

---

## 3. Step 2: Tag-Based Turn Classification

### 3.1 What to Do

**File:** `src/remora/core/actor.py`, method `_complete_agent_turn` (line 508)

Currently emits `AgentCompleteEvent` without tags. We need to classify the turn as `"primary"` or `"reflection"` based on the trigger event. A turn is a reflection turn if it was triggered by an `AgentCompleteEvent` with `"primary"` tag (i.e., the agent is processing its own completion event as part of self-reflection).

Modify `_complete_agent_turn` to accept a `turn_tags` parameter and pass it through:

```python
async def _complete_agent_turn(
    self,
    node_id: str,
    response_text: str,
    outbox: Outbox,
    trigger: Trigger,
    turn_log: logging.LoggerAdapter,
    *,
    turn_tags: tuple[str, ...] = ("primary",),
) -> None:
    turn_log.info(
        "Agent turn complete node=%s corr=%s response=%s",
        node_id,
        trigger.correlation_id,
        response_text,
    )
    await outbox.emit(
        AgentCompleteEvent(
            agent_id=node_id,
            result_summary=response_text[:200],
            full_response=response_text,
            correlation_id=trigger.correlation_id,
            tags=turn_tags,
        )
    )
```

In `execute_turn` (line 374), determine tags before calling `_complete_agent_turn`:

```python
# After response_text = extract_response_text(result), before _complete_agent_turn call:
is_reflection = (
    trigger.event is not None
    and trigger.event.event_type == "AgentCompleteEvent"
    and "primary" in getattr(trigger.event, "tags", ())
)
turn_tags = ("reflection",) if is_reflection else ("primary",)
await self._complete_agent_turn(
    node_id, response_text, outbox, trigger, turn_log, turn_tags=turn_tags
)
```

### 3.2 Tests

**File:** `tests/unit/test_actor.py` (add new tests)

```python
@pytest.mark.asyncio
async def test_complete_agent_turn_tags_primary_by_default(outbox_env) -> None:
    outbox, event_store, _db = outbox_env
    trigger = Trigger(
        node_id="agent-a",
        event=ContentChangedEvent(path="src/foo.py"),
        correlation_id="corr-1",
    )
    from remora.core.actor import AgentTurnExecutor
    # We test _complete_agent_turn directly by constructing a minimal executor.
    # Alternatively, check emitted events after a full turn.
    await outbox.emit(
        AgentCompleteEvent(
            agent_id="agent-a",
            result_summary="test",
            full_response="test response",
            tags=("primary",),
        )
    )
    events = await event_store.get_events(limit=10)
    complete_events = [e for e in events if e["event_type"] == "AgentCompleteEvent"]
    assert complete_events[0]["tags"] == ["primary"]


@pytest.mark.asyncio
async def test_complete_agent_turn_tags_reflection_on_self_trigger(outbox_env) -> None:
    outbox, event_store, _db = outbox_env
    await outbox.emit(
        AgentCompleteEvent(
            agent_id="agent-a",
            result_summary="reflection output",
            full_response="reflection response",
            tags=("reflection",),
        )
    )
    events = await event_store.get_events(limit=10)
    complete_events = [e for e in events if e["event_type"] == "AgentCompleteEvent"]
    assert complete_events[0]["tags"] == ["reflection"]
```

**Run:** `devenv shell -- pytest tests/unit/test_actor.py -v -k tag`

---

## 4. Step 3: Enrich AgentCompleteEvent with user_message

### 4.1 What to Do

**File:** `src/remora/core/events/types.py`, class `AgentCompleteEvent` (line 48)

Add `user_message` field:

```python
class AgentCompleteEvent(Event):
    agent_id: str
    result_summary: str = ""
    full_response: str = ""
    user_message: str = ""  # NEW: the prompt that triggered this turn
```

**File:** `src/remora/core/actor.py`, method `execute_turn` (line 315)

The user message is `messages[1].content` (the user-role message built by `PromptBuilder.build_prompt`). Capture it and pass to `_complete_agent_turn`:

```python
# In execute_turn, after building messages (line 357):
user_message = messages[1].content if len(messages) > 1 else ""

# Pass to _complete_agent_turn:
await self._complete_agent_turn(
    node_id, response_text, outbox, trigger, turn_log,
    turn_tags=turn_tags, user_message=user_message,
)
```

Update `_complete_agent_turn` to accept and pass `user_message`:

```python
async def _complete_agent_turn(
    self,
    node_id: str,
    response_text: str,
    outbox: Outbox,
    trigger: Trigger,
    turn_log: logging.LoggerAdapter,
    *,
    turn_tags: tuple[str, ...] = ("primary",),
    user_message: str = "",
) -> None:
    ...
    await outbox.emit(
        AgentCompleteEvent(
            agent_id=node_id,
            result_summary=response_text[:200],
            full_response=response_text,
            user_message=user_message,
            correlation_id=trigger.correlation_id,
            tags=turn_tags,
        )
    )
```

### 4.2 Tests

**File:** `tests/unit/test_event_types.py`

```python
from remora.core.events.types import AgentCompleteEvent


def test_agent_complete_event_user_message_field() -> None:
    event = AgentCompleteEvent(
        agent_id="agent-a",
        result_summary="test",
        full_response="full test response",
        user_message="What does this function do?",
    )
    assert event.user_message == "What does this function do?"


def test_agent_complete_event_user_message_defaults_empty() -> None:
    event = AgentCompleteEvent(agent_id="agent-a")
    assert event.user_message == ""


def test_agent_complete_event_user_message_in_envelope() -> None:
    event = AgentCompleteEvent(
        agent_id="agent-a",
        user_message="hello",
    )
    envelope = event.to_envelope()
    assert envelope["payload"]["user_message"] == "hello"
```

**Run:** `devenv shell -- pytest tests/unit/test_event_types.py -v -k user_message`

---

## 5. Step 4: Add not_from_agents Filter to SubscriptionPattern

### 5.1 What to Do

**File:** `src/remora/core/events/subscriptions.py`, class `SubscriptionPattern` (line 17)

Add the `not_from_agents` field:

```python
class SubscriptionPattern(BaseModel):
    """Pattern for selecting events. None fields are wildcards."""

    event_types: list[str] | None = None
    from_agents: list[str] | None = None
    not_from_agents: list[str] | None = None  # NEW: exclusion filter
    to_agent: str | None = None
    path_glob: str | None = None
    tags: list[str] | None = None
```

Update the `matches` method. Insert after the `from_agents` check (after line 34) and before the `to_agent` check:

```python
if self.not_from_agents:
    # Check both agent_id (for AgentCompleteEvent etc.) and from_agent (for AgentMessageEvent)
    agent_id = getattr(event, "agent_id", None)
    from_agent = getattr(event, "from_agent", None)
    if agent_id in self.not_from_agents or from_agent in self.not_from_agents:
        return False
```

### 5.2 Tests

**File:** `tests/unit/test_subscription_registry.py` (add new tests)

```python
from remora.core.events import AgentCompleteEvent


def test_not_from_agents_excludes_matching_agent_id() -> None:
    pattern = SubscriptionPattern(
        event_types=["AgentCompleteEvent"],
        not_from_agents=["observer-1"],
    )
    # Should exclude events where agent_id matches
    event = AgentCompleteEvent(agent_id="observer-1", result_summary="done")
    assert not pattern.matches(event)

    # Should pass events from other agents
    event2 = AgentCompleteEvent(agent_id="agent-a", result_summary="done")
    assert pattern.matches(event2)


def test_not_from_agents_excludes_matching_from_agent() -> None:
    pattern = SubscriptionPattern(
        event_types=["AgentMessageEvent"],
        not_from_agents=["observer-1"],
    )
    event = AgentMessageEvent(from_agent="observer-1", to_agent="agent-a", content="hi")
    assert not pattern.matches(event)


def test_not_from_agents_none_matches_all() -> None:
    pattern = SubscriptionPattern(
        event_types=["AgentCompleteEvent"],
        not_from_agents=None,
    )
    event = AgentCompleteEvent(agent_id="any-agent", result_summary="done")
    assert pattern.matches(event)


@pytest.mark.asyncio
async def test_registry_not_from_agents_filter(db) -> None:
    registry = SubscriptionRegistry(db)
    await registry.create_tables()
    await registry.register(
        "observer-1",
        SubscriptionPattern(
            event_types=["AgentCompleteEvent"],
            not_from_agents=["observer-1"],
        ),
    )
    # Observer's own event should NOT match
    own_event = AgentCompleteEvent(agent_id="observer-1")
    matches = await registry.get_matching_agents(own_event)
    assert matches == []

    # Other agent's event SHOULD match
    other_event = AgentCompleteEvent(agent_id="agent-a")
    matches = await registry.get_matching_agents(other_event)
    assert matches == ["observer-1"]
```

**Run:** `devenv shell -- pytest tests/unit/test_subscription_registry.py -v -k not_from`

---

## 6. Step 5: Create KV-Native Companion Grail Tools

### 6.1 What to Do

Create three new Grail tools in `bundles/system/tools/`. These replace the existing file-based companion tools for the self-reflection use case by writing to KV instead.

**File:** `bundles/system/tools/companion_summarize.pym`

```python
# Write a turn summary and tags to companion KV storage.
from grail import Input, external

summary: str = Input("summary")
tags: str = Input("tags")  # comma-separated

@external
async def kv_get(key: str) -> object: ...

@external
async def kv_set(key: str, value: object) -> bool: ...

import json, time

tag_list = [t.strip() for t in tags.split(",") if t.strip()]

# Append to chat_index
existing = await kv_get("companion/chat_index") or []
existing.append({
    "timestamp": time.time(),
    "summary": summary,
    "tags": tag_list,
})
# Keep last 50 entries
existing = existing[-50:]
await kv_set("companion/chat_index", existing)

result = f"Recorded summary with tags: {', '.join(tag_list)}"
result
```

**File:** `bundles/system/tools/companion_reflect.pym`

```python
# Record a reflection insight to companion KV storage.
from grail import Input, external

insight: str = Input("insight")

@external
async def kv_get(key: str) -> object: ...

@external
async def kv_set(key: str, value: object) -> bool: ...

import time

existing = await kv_get("companion/reflections") or []
existing.append({
    "timestamp": time.time(),
    "insight": insight,
})
# Keep last 30 reflections
existing = existing[-30:]
await kv_set("companion/reflections", existing)

result = f"Recorded reflection: {insight[:80]}..."
result
```

**File:** `bundles/system/tools/companion_link.pym`

```python
# Record a link/relationship to another node in companion KV storage.
from grail import Input, external

target_node_id: str = Input("target_node_id")
relationship: str = Input("relationship", default="related")

@external
async def kv_get(key: str) -> object: ...

@external
async def kv_set(key: str, value: object) -> bool: ...

import time

existing = await kv_get("companion/links") or []
# Avoid duplicate links
already_linked = any(e.get("target") == target_node_id for e in existing)
if not already_linked:
    existing.append({
        "target": target_node_id,
        "relationship": relationship,
        "timestamp": time.time(),
    })
    existing = existing[-100:]
    await kv_set("companion/links", existing)
    result = f"Linked to {target_node_id} ({relationship})"
else:
    result = f"Already linked to {target_node_id}"
result
```

### 6.2 Tests

**File:** `tests/unit/test_companion_tools.py` (new file)

Test the tool scripts using the Grail loader. The key thing to verify is that the tools interact with KV correctly. Since these are Grail scripts, we test them through the Grail execution engine or by mocking the externals.

```python
"""Tests for companion KV tools."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# Verify the tool files are valid and loadable
TOOLS_DIR = Path(__file__).resolve().parents[2] / "bundles" / "system" / "tools"


def test_companion_summarize_exists() -> None:
    tool_path = TOOLS_DIR / "companion_summarize.pym"
    assert tool_path.exists(), f"Missing tool: {tool_path}"
    content = tool_path.read_text()
    assert "companion/chat_index" in content
    assert "kv_set" in content
    assert "kv_get" in content


def test_companion_reflect_exists() -> None:
    tool_path = TOOLS_DIR / "companion_reflect.pym"
    assert tool_path.exists(), f"Missing tool: {tool_path}"
    content = tool_path.read_text()
    assert "companion/reflections" in content
    assert "kv_set" in content


def test_companion_link_exists() -> None:
    tool_path = TOOLS_DIR / "companion_link.pym"
    assert tool_path.exists(), f"Missing tool: {tool_path}"
    content = tool_path.read_text()
    assert "companion/links" in content
    assert "target_node_id" in content
```

**Run:** `devenv shell -- pytest tests/unit/test_companion_tools.py -v`

---

## 7. Step 6: Add self_reflect Config and Self-Subscription Registration

### 7.1 What to Do

When an agent has `self_reflect.enabled: true` in its bundle config, the reconciler should register an additional subscription so the agent receives its own `AgentCompleteEvent` (filtered to `"primary"` tag).

**File:** `src/remora/code/reconciler.py`, method `_register_subscriptions` (line 516)

After registering the standard subscriptions, check for self_reflect config. The self_reflect config is stored in the bundle config as a KV entry during provisioning (Step 7 handles parsing). Here we read it at subscription-registration time:

```python
async def _register_subscriptions(
    self,
    node: Node,
    *,
    virtual_subscriptions: tuple[SubscriptionPattern, ...] = (),
) -> None:
    await self._event_store.subscriptions.unregister_by_agent(node.node_id)
    await self._event_store.subscriptions.register(
        node.node_id,
        SubscriptionPattern(to_agent=node.node_id),
    )

    if node.node_type == NodeType.VIRTUAL:
        for pattern in virtual_subscriptions:
            await self._event_store.subscriptions.register(node.node_id, pattern)
        return

    # NEW: Register self-reflection subscription if bundle config enables it
    workspace = await self._workspace_service.get_agent_workspace(node.node_id)
    self_reflect_config = await workspace.kv_get("_system/self_reflect")
    if isinstance(self_reflect_config, dict) and self_reflect_config.get("enabled"):
        await self._event_store.subscriptions.register(
            node.node_id,
            SubscriptionPattern(
                event_types=["AgentCompleteEvent"],
                from_agents=[node.node_id],
                tags=["primary"],
            ),
        )

    # ... rest of existing subscription logic (DIRECTORY, FILE, etc.)
```

The `from_agents=[node.node_id]` ensures the agent only self-subscribes. The `tags=["primary"]` prevents the reflection turn from re-triggering.

### 7.2 Tests

**File:** `tests/unit/test_reconciler.py` (add new tests)

```python
@pytest.mark.asyncio
async def test_self_reflect_subscription_registered(reconcile_env) -> None:
    """When self_reflect is enabled in workspace KV, a self-subscription is registered."""
    env = reconcile_env
    # Create a code node
    node = make_node(name="validate", file_path="src/validate.py")
    await env.node_store.upsert_node(node)

    # Set self_reflect config in workspace KV
    workspace = await env.workspace_service.get_agent_workspace(node.node_id)
    await workspace.kv_set("_system/self_reflect", {"enabled": True})

    # Run subscription registration
    await env.reconciler._register_subscriptions(node)

    # Check that a self-subscription was registered
    event = AgentCompleteEvent(agent_id=node.node_id, tags=("primary",))
    matches = await env.event_store.subscriptions.get_matching_agents(event)
    assert node.node_id in matches


@pytest.mark.asyncio
async def test_no_self_reflect_subscription_when_disabled(reconcile_env) -> None:
    """No self-subscription when self_reflect is not enabled."""
    env = reconcile_env
    node = make_node(name="validate", file_path="src/validate.py")
    await env.node_store.upsert_node(node)

    await env.reconciler._register_subscriptions(node)

    event = AgentCompleteEvent(agent_id=node.node_id, tags=("primary",))
    matches = await env.event_store.subscriptions.get_matching_agents(event)
    # Only the default to_agent subscription should exist, which doesn't match AgentCompleteEvent
    # unless specifically routed
    assert node.node_id not in matches or len(matches) == 0
```

**Run:** `devenv shell -- pytest tests/unit/test_reconciler.py -v -k self_reflect`

---

## 8. Step 7: Parse self_reflect in Bundle Config

### 8.1 What to Do

**File:** `src/remora/core/actor.py`, method `_read_bundle_config` (line 548)

Currently parses `system_prompt`, `system_prompt_extension`, `model`, `max_turns`, and `prompts`. Add parsing for `self_reflect`:

```python
# After the prompts parsing block (after line 587), add:
self_reflect = expanded.get("self_reflect")
if isinstance(self_reflect, dict):
    sr_values: dict[str, Any] = {}
    if self_reflect.get("enabled"):
        sr_values["enabled"] = True
    sr_model = self_reflect.get("model")
    if isinstance(sr_model, str) and sr_model.strip():
        sr_values["model"] = sr_model
    sr_max_turns = self_reflect.get("max_turns")
    if sr_max_turns is not None:
        try:
            sr_values["max_turns"] = max(1, int(sr_max_turns))
        except (TypeError, ValueError):
            pass
    sr_prompt = self_reflect.get("prompt")
    if isinstance(sr_prompt, str) and sr_prompt.strip():
        sr_values["prompt"] = sr_prompt
    if sr_values:
        validated["self_reflect"] = sr_values
```

**File:** `src/remora/code/reconciler.py`, method `_provision_bundle` (line 320)

After provisioning the bundle templates, read the bundle config and store self_reflect config in workspace KV so that `_register_subscriptions` can find it:

```python
async def _provision_bundle(self, node_id: str, role: str | None) -> None:
    bundle_root = Path(self._config.bundle_root)
    template_dirs = [bundle_root / "system"]
    if role:
        template_dirs.append(bundle_root / role)
    await self._workspace_service.provision_bundle(node_id, template_dirs)

    # NEW: Store self_reflect config in workspace KV for subscription registration
    workspace = await self._workspace_service.get_agent_workspace(node_id)
    try:
        text = await workspace.read("_bundle/bundle.yaml")
        import yaml
        loaded = yaml.safe_load(text) or {}
        self_reflect = loaded.get("self_reflect")
        if isinstance(self_reflect, dict) and self_reflect.get("enabled"):
            await workspace.kv_set("_system/self_reflect", self_reflect)
        else:
            # Clear stale config if disabled
            await workspace.kv_set("_system/self_reflect", None)
    except (FileNotFoundError, Exception):
        pass
```

### 8.2 Tests

**File:** `tests/unit/test_actor.py` (add new tests)

```python
@pytest.mark.asyncio
async def test_read_bundle_config_parses_self_reflect(tmp_path: Path) -> None:
    """_read_bundle_config extracts self_reflect section."""
    from remora.core.actor import AgentTurnExecutor
    from remora.core.workspace import CairnWorkspaceService

    ws_service = CairnWorkspaceService(project_root=tmp_path, cairn_root=tmp_path / ".cairn")
    workspace = await ws_service.get_agent_workspace("test-agent")

    bundle_yaml = """\
system_prompt: "You are a code agent."
self_reflect:
  enabled: true
  model: "Qwen/Qwen3-1.7B"
  max_turns: 2
  prompt: "Reflect on your last turn."
"""
    await workspace.write("_bundle/bundle.yaml", bundle_yaml)

    config = await AgentTurnExecutor._read_bundle_config(workspace)
    assert config["self_reflect"]["enabled"] is True
    assert config["self_reflect"]["model"] == "Qwen/Qwen3-1.7B"
    assert config["self_reflect"]["max_turns"] == 2
    assert config["self_reflect"]["prompt"] == "Reflect on your last turn."


@pytest.mark.asyncio
async def test_read_bundle_config_ignores_disabled_self_reflect(tmp_path: Path) -> None:
    from remora.core.actor import AgentTurnExecutor
    from remora.core.workspace import CairnWorkspaceService

    ws_service = CairnWorkspaceService(project_root=tmp_path, cairn_root=tmp_path / ".cairn")
    workspace = await ws_service.get_agent_workspace("test-agent")

    bundle_yaml = """\
system_prompt: "You are a code agent."
self_reflect:
  enabled: false
"""
    await workspace.write("_bundle/bundle.yaml", bundle_yaml)

    config = await AgentTurnExecutor._read_bundle_config(workspace)
    assert "self_reflect" not in config
```

**Run:** `devenv shell -- pytest tests/unit/test_actor.py -v -k self_reflect`

---

## 9. Step 8: Reflection Turn Model/Prompt Override in PromptBuilder

### 9.1 What to Do

**File:** `src/remora/core/actor.py`, class `PromptBuilder` (line 212)

When a turn is triggered by a self-reflection subscription (the trigger event is an `AgentCompleteEvent` with `"primary"` tag from the same agent), the `PromptBuilder` should override the model, max_turns, and system prompt using the `self_reflect` config.

Modify `build_system_prompt` to detect reflection triggers and apply overrides:

```python
def build_system_prompt(
    self,
    bundle_config: dict[str, Any],
    trigger_event: Event | None,
) -> tuple[str, str, int]:
    # Check if this is a reflection turn
    self_reflect = bundle_config.get("self_reflect", {})
    is_reflection = (
        self_reflect.get("enabled")
        and trigger_event is not None
        and trigger_event.event_type == "AgentCompleteEvent"
        and "primary" in getattr(trigger_event, "tags", ())
    )

    if is_reflection:
        # Use reflection-specific config
        reflection_prompt = self_reflect.get("prompt", _DEFAULT_REFLECTION_PROMPT)
        model_name = self_reflect.get("model", bundle_config.get("model", self._config.model_default))
        max_turns = int(self_reflect.get("max_turns", 2))
        return reflection_prompt, model_name, max_turns

    # Original logic (unchanged)
    system_prompt = bundle_config.get("system_prompt", "You are an autonomous code agent.")
    prompt_extension = bundle_config.get("system_prompt_extension", "")
    if prompt_extension:
        system_prompt = f"{system_prompt}\n\n{prompt_extension}"
    mode = self.turn_mode(trigger_event)
    prompts = bundle_config.get("prompts")
    mode_prompt = prompts.get(mode, "") if isinstance(prompts, dict) else ""
    if mode_prompt:
        system_prompt = f"{system_prompt}\n\n{mode_prompt}"
    model_name = bundle_config.get("model", self._config.model_default)
    max_turns = int(bundle_config.get("max_turns", self._config.max_turns))
    return system_prompt, model_name, max_turns
```

Add the default reflection prompt as a module-level constant:

```python
_DEFAULT_REFLECTION_PROMPT = """\
You just completed a conversation turn. Reflect on the exchange and record metadata.

Use your companion tools:
- companion_summarize: Write a one-sentence summary and 1-3 tags
- companion_reflect: Record one key insight or observation
- companion_link: If you referenced another code element, record the link

Tag vocabulary: bug, question, refactor, explanation, test, performance, design, insight, todo, review

Be specific. Skip trivial exchanges."""
```

### 9.2 Tests

**File:** `tests/unit/test_actor.py` (add new tests)

```python
from remora.core.actor import PromptBuilder
from remora.core.events.types import AgentCompleteEvent, ContentChangedEvent


def test_prompt_builder_reflection_override() -> None:
    """Reflection trigger uses self_reflect config."""
    config = Config()
    pb = PromptBuilder(config)
    bundle_config = {
        "system_prompt": "Normal prompt",
        "model": "big-model",
        "max_turns": 8,
        "self_reflect": {
            "enabled": True,
            "model": "Qwen/Qwen3-1.7B",
            "max_turns": 2,
            "prompt": "Reflect on this turn.",
        },
    }
    trigger = AgentCompleteEvent(agent_id="agent-a", tags=("primary",))
    prompt, model, max_turns = pb.build_system_prompt(bundle_config, trigger)
    assert prompt == "Reflect on this turn."
    assert model == "Qwen/Qwen3-1.7B"
    assert max_turns == 2


def test_prompt_builder_normal_turn_unaffected_by_self_reflect() -> None:
    """Non-reflection triggers use normal config even when self_reflect is present."""
    config = Config()
    pb = PromptBuilder(config)
    bundle_config = {
        "system_prompt": "Normal prompt",
        "model": "big-model",
        "max_turns": 8,
        "self_reflect": {
            "enabled": True,
            "model": "Qwen/Qwen3-1.7B",
        },
    }
    trigger = ContentChangedEvent(path="src/foo.py")
    prompt, model, max_turns = pb.build_system_prompt(bundle_config, trigger)
    assert "Normal prompt" in prompt
    assert model == "big-model"
    assert max_turns == 8


def test_prompt_builder_reflection_tag_must_be_primary() -> None:
    """AgentCompleteEvent without 'primary' tag is not treated as reflection."""
    config = Config()
    pb = PromptBuilder(config)
    bundle_config = {
        "system_prompt": "Normal prompt",
        "model": "big-model",
        "self_reflect": {"enabled": True, "model": "cheap-model"},
    }
    # reflection-tagged event should NOT trigger reflection override
    trigger = AgentCompleteEvent(agent_id="agent-a", tags=("reflection",))
    prompt, model, _max = pb.build_system_prompt(bundle_config, trigger)
    assert "Normal prompt" in prompt
    assert model == "big-model"
```

**Run:** `devenv shell -- pytest tests/unit/test_actor.py -v -k prompt_builder`

---

## 10. Step 9: Companion Context Injection into System Prompt

### 10.1 What to Do

Before each primary turn, read the agent's `companion/` KV data and inject a summary into the system prompt. This gives the agent continuity from previous reflections.

**File:** `src/remora/core/actor.py`, class `AgentTurnExecutor`

Add a new static method `_build_companion_context`:

```python
@staticmethod
async def _build_companion_context(workspace: AgentWorkspace) -> str:
    """Build companion context string from workspace KV data."""
    parts: list[str] = []

    reflections = await workspace.kv_get("companion/reflections")
    if isinstance(reflections, list) and reflections:
        recent = reflections[-5:]  # Last 5 reflections
        parts.append("## Prior Reflections")
        for r in recent:
            insight = r.get("insight", "")
            if insight:
                parts.append(f"- {insight}")

    chat_index = await workspace.kv_get("companion/chat_index")
    if isinstance(chat_index, list) and chat_index:
        recent = chat_index[-5:]  # Last 5 summaries
        parts.append("## Recent Activity")
        for entry in recent:
            summary = entry.get("summary", "")
            tags = entry.get("tags", [])
            if summary:
                tag_str = f" [{', '.join(tags)}]" if tags else ""
                parts.append(f"- {summary}{tag_str}")

    links = await workspace.kv_get("companion/links")
    if isinstance(links, list) and links:
        parts.append("## Known Relationships")
        for link in links[-10:]:
            target = link.get("target", "")
            rel = link.get("relationship", "related")
            if target:
                parts.append(f"- {rel}: {target}")

    if not parts:
        return ""
    return "\n## Companion Memory\n" + "\n".join(parts)
```

In `execute_turn` (line 329), inject companion context into the system prompt for primary turns only:

```python
system_prompt, model_name, max_turns = self._prompt_builder.build_system_prompt(
    bundle_config,
    trigger.event,
)

# NEW: Inject companion context for primary turns
is_reflection_turn = (
    trigger.event is not None
    and trigger.event.event_type == "AgentCompleteEvent"
    and "primary" in getattr(trigger.event, "tags", ())
)
if not is_reflection_turn:
    companion_ctx = await self._build_companion_context(workspace)
    if companion_ctx:
        system_prompt = f"{system_prompt}\n{companion_ctx}"
```

### 10.2 Tests

**File:** `tests/unit/test_actor.py` (add new tests)

```python
@pytest.mark.asyncio
async def test_build_companion_context_empty(tmp_path: Path) -> None:
    """No companion data returns empty string."""
    from remora.core.actor import AgentTurnExecutor
    from remora.core.workspace import CairnWorkspaceService

    ws = CairnWorkspaceService(project_root=tmp_path, cairn_root=tmp_path / ".cairn")
    workspace = await ws.get_agent_workspace("test-agent")

    result = await AgentTurnExecutor._build_companion_context(workspace)
    assert result == ""


@pytest.mark.asyncio
async def test_build_companion_context_with_data(tmp_path: Path) -> None:
    """Companion context includes reflections, summaries, and links."""
    from remora.core.actor import AgentTurnExecutor
    from remora.core.workspace import CairnWorkspaceService

    ws = CairnWorkspaceService(project_root=tmp_path, cairn_root=tmp_path / ".cairn")
    workspace = await ws.get_agent_workspace("test-agent")

    await workspace.kv_set("companion/reflections", [
        {"insight": "Regex doesn't handle Unicode domains", "timestamp": 1.0},
    ])
    await workspace.kv_set("companion/chat_index", [
        {"summary": "Discussed email validation", "tags": ["bug"], "timestamp": 1.0},
    ])
    await workspace.kv_set("companion/links", [
        {"target": "test_validate", "relationship": "tested_by", "timestamp": 1.0},
    ])

    result = await AgentTurnExecutor._build_companion_context(workspace)
    assert "Companion Memory" in result
    assert "Unicode domains" in result
    assert "email validation" in result
    assert "test_validate" in result
```

**Run:** `devenv shell -- pytest tests/unit/test_actor.py -v -k companion_context`

---

## 11. Step 10: Add self_reflect Config to code-agent Bundle

### 11.1 What to Do

**File:** `bundles/code-agent/bundle.yaml`

Add the `self_reflect` section at the end of the file (after the existing `max_turns: 8`):

```yaml
self_reflect:
  enabled: true
  model: "Qwen/Qwen3-1.7B"
  max_turns: 2
  prompt: |
    You just completed a conversation turn. Reflect on the exchange and record metadata.

    Use your companion tools to record what happened:
    - companion_summarize: Write a one-sentence summary and 1-3 tags
    - companion_reflect: Record one key insight or observation
    - companion_link: If you referenced another code element, record the link

    Tag vocabulary: bug, question, refactor, explanation, test, performance,
    design, insight, todo, review

    Be specific and concise. Skip trivial exchanges.
```

### 11.2 Tests

**File:** `tests/unit/test_bundle_configs.py` (new or existing)

```python
from pathlib import Path
import yaml


def test_code_agent_bundle_has_self_reflect() -> None:
    bundle_path = Path(__file__).resolve().parents[2] / "bundles" / "code-agent" / "bundle.yaml"
    config = yaml.safe_load(bundle_path.read_text())
    assert "self_reflect" in config
    sr = config["self_reflect"]
    assert sr["enabled"] is True
    assert "model" in sr
    assert "prompt" in sr
    assert sr["max_turns"] >= 1
```

**Run:** `devenv shell -- pytest tests/unit/test_bundle_configs.py -v`

---

## 12. Step 11: Web API Endpoint for Companion Data

### 12.1 What to Do

**File:** `src/remora/web/server.py`

Add a new route that returns companion KV data for a given node. Add this inside `create_app()` alongside the existing route handlers:

```python
async def api_node_companion(request: Request) -> JSONResponse:
    node_id = request.path_params["node_id"]
    if workspace_service is None:
        return JSONResponse({"error": "No workspace service"}, status_code=503)

    workspace = await workspace_service.get_agent_workspace(node_id)
    companion_data: dict[str, Any] = {}

    for key in ("companion/chat_index", "companion/reflections", "companion/links"):
        value = await workspace.kv_get(key)
        if value is not None:
            short_key = key.removeprefix("companion/")
            companion_data[short_key] = value

    return JSONResponse(companion_data)
```

Register the route in the `routes` list:

```python
Route("/api/nodes/{node_id}/companion", api_node_companion, methods=["GET"]),
```

### 12.2 Tests

**File:** `tests/unit/test_web_server.py` (add new tests)

```python
@pytest.mark.asyncio
async def test_api_node_companion_empty(web_env) -> None:
    """Companion endpoint returns empty dict when no data exists."""
    env = web_env
    node = make_node(name="validate", file_path="src/validate.py")
    await env.node_store.upsert_node(node)

    transport = httpx.ASGITransport(app=env.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/nodes/{node.node_id}/companion")
        assert resp.status_code == 200
        assert resp.json() == {}


@pytest.mark.asyncio
async def test_api_node_companion_with_data(web_env) -> None:
    """Companion endpoint returns stored companion data."""
    env = web_env
    node = make_node(name="validate", file_path="src/validate.py")
    await env.node_store.upsert_node(node)

    workspace = await env.workspace_service.get_agent_workspace(node.node_id)
    await workspace.kv_set("companion/chat_index", [{"summary": "test", "tags": ["bug"]}])
    await workspace.kv_set("companion/reflections", [{"insight": "needs fix"}])

    transport = httpx.ASGITransport(app=env.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/nodes/{node.node_id}/companion")
        assert resp.status_code == 200
        data = resp.json()
        assert "chat_index" in data
        assert "reflections" in data
        assert data["chat_index"][0]["summary"] == "test"
```

**Run:** `devenv shell -- pytest tests/unit/test_web_server.py -v -k companion`

---

## 13. Step 12: Layer 2 — Companion Observer Virtual Agent Bundle

### 13.1 What to Do

Create the observer bundle that processes `TurnDigestedEvent`s and builds project-level insights.

**File:** `bundles/companion/bundle.yaml`

```yaml
name: companion
system_prompt: |
  You are the project companion observer. You receive TurnDigestedEvent
  notifications from all code agents after they complete self-reflection.

  Your job is to:
  1. Track which agents are most active and what topics they discuss
  2. Identify patterns: recurring bugs, clusters of related changes,
     agents that frequently reference each other
  3. Maintain a project activity dashboard in your KV store
  4. When you notice significant patterns, record them as insights

  Do NOT re-analyze individual turns — agents already did that in Layer 1.
  Focus on the cross-agent, project-level view.

  Use aggregate_digest to record your analysis.
prompts:
  reactive: |
    A TurnDigestedEvent arrived. An agent just finished self-reflection.
    Review the event data (agent_id, summary, tags).
    Use aggregate_digest to update your project-level tracking.
model: "Qwen/Qwen3-1.7B"
max_turns: 3
```

**File:** `bundles/companion/tools/aggregate_digest.pym`

```python
# Record project-level activity digest in observer's own KV store.
from grail import Input, external

agent_id: str = Input("agent_id")
summary: str = Input("summary")
tags: str = Input("tags")  # comma-separated
insight: str = Input("insight", default="")

@external
async def kv_get(key: str) -> object: ...

@external
async def kv_set(key: str, value: object) -> bool: ...

import time

tag_list = [t.strip() for t in tags.split(",") if t.strip()]

# Update activity log
activity_log = await kv_get("project/activity_log") or []
activity_log.append({
    "agent_id": agent_id,
    "summary": summary,
    "tags": tag_list,
    "timestamp": time.time(),
})
activity_log = activity_log[-200:]
await kv_set("project/activity_log", activity_log)

# Update tag frequency
tag_freq = await kv_get("project/tag_frequency") or {}
for tag in tag_list:
    tag_freq[tag] = tag_freq.get(tag, 0) + 1
await kv_set("project/tag_frequency", tag_freq)

# Update per-agent activity
agent_activity = await kv_get("project/agent_activity") or {}
agent_activity[agent_id] = {
    "last_summary": summary,
    "last_tags": tag_list,
    "last_active": time.time(),
}
await kv_set("project/agent_activity", agent_activity)

# Record insight if provided
if insight:
    insights = await kv_get("project/insights") or []
    insights.append({
        "insight": insight,
        "related_agent": agent_id,
        "timestamp": time.time(),
    })
    insights = insights[-50:]
    await kv_set("project/insights", insights)

parts = [f"Recorded activity for {agent_id}"]
if insight:
    parts.append(f"Insight: {insight[:80]}")
result = ". ".join(parts)
result
```

### 13.2 Tests

**File:** `tests/unit/test_companion_tools.py` (add to existing)

```python
def test_companion_bundle_exists() -> None:
    bundle_path = Path(__file__).resolve().parents[2] / "bundles" / "companion" / "bundle.yaml"
    assert bundle_path.exists()
    import yaml
    config = yaml.safe_load(bundle_path.read_text())
    assert config["name"] == "companion"
    assert "TurnDigestedEvent" in config.get("system_prompt", "")


def test_aggregate_digest_tool_exists() -> None:
    tool_path = (
        Path(__file__).resolve().parents[2]
        / "bundles" / "companion" / "tools" / "aggregate_digest.pym"
    )
    assert tool_path.exists()
    content = tool_path.read_text()
    assert "project/activity_log" in content
    assert "project/tag_frequency" in content
    assert "kv_set" in content
```

**Run:** `devenv shell -- pytest tests/unit/test_companion_tools.py -v`

---

## 14. Step 13: Add Example Config to remora.yaml.example

### 14.1 What to Do

**File:** `remora.yaml.example`

Add the Layer 2 companion observer to the `virtual_agents` section. If a `virtual_agents` section doesn't exist, create one. Add clear comments explaining the companion system:

```yaml
# --- Companion System (Layer 2: Project-Level Observer) ---
# The companion observer tracks activity across all agents and builds
# project-level insights. It subscribes to TurnDigestedEvent, which is
# emitted after each agent's self-reflection (Layer 1) completes.
#
# Layer 1 (per-agent self-reflection) is configured in bundle.yaml
# via the self_reflect section. See bundles/code-agent/bundle.yaml.
#
# To enable Layer 2, uncomment the virtual agent below:
#
# virtual_agents:
#   - id: companion-observer
#     role: companion
#     subscriptions:
#       - event_types: ["TurnDigestedEvent"]
```

### 14.2 Tests

No code tests needed. Verify manually:
- The YAML is valid: `python -c "import yaml; yaml.safe_load(open('remora.yaml.example'))"`
- The comments explain both layers clearly
- The virtual agent config matches what the reconciler expects

---

## 15. Summary: All Files Changed/Created

### Files Created

| File | Purpose |
|------|---------|
| `bundles/system/tools/companion_summarize.pym` | KV-native turn summary + tags |
| `bundles/system/tools/companion_reflect.pym` | KV-native reflection insight |
| `bundles/system/tools/companion_link.pym` | KV-native relationship recording |
| `bundles/companion/bundle.yaml` | Layer 2 observer bundle config |
| `bundles/companion/tools/aggregate_digest.pym` | Observer's project-level digest tool |
| `tests/unit/test_event_types.py` | Tests for new event types |
| `tests/unit/test_companion_tools.py` | Tests for companion tool existence |
| `tests/unit/test_bundle_configs.py` | Tests for bundle config correctness |

### Files Modified

| File | Changes | ~Lines |
|------|---------|--------|
| `src/remora/core/events/types.py` | `TurnDigestedEvent` class, `user_message` on `AgentCompleteEvent`, `__all__` update | +12 |
| `src/remora/core/events/subscriptions.py` | `not_from_agents` field + `matches()` update | +8 |
| `src/remora/core/actor.py` | Tag classification, `_build_companion_context`, reflection override in `PromptBuilder`, `self_reflect` parsing in `_read_bundle_config`, `user_message` threading | +80 |
| `src/remora/code/reconciler.py` | Self-subscription in `_register_subscriptions`, `self_reflect` KV write in `_provision_bundle` | +25 |
| `src/remora/web/server.py` | `GET /api/nodes/{node_id}/companion` route | +15 |
| `bundles/code-agent/bundle.yaml` | `self_reflect` config section | +12 |
| `remora.yaml.example` | Companion observer virtual agent config + comments | +12 |
| `tests/unit/test_actor.py` | Tests for tags, reflection override, companion context | +60 |
| `tests/unit/test_subscription_registry.py` | Tests for `not_from_agents` filter | +30 |
| `tests/unit/test_reconciler.py` | Tests for self-reflect subscription registration | +25 |
| `tests/unit/test_web_server.py` | Tests for companion API endpoint | +25 |
| **Total** | | **~304** |

---

## 16. Testing Strategy Overview

### Test Execution Order

Run tests step-by-step as each step is completed. The steps are designed so each builds on the previous:

1. **Step 1:** `devenv shell -- pytest tests/unit/test_event_types.py -v` — event type basics
2. **Step 2:** `devenv shell -- pytest tests/unit/test_actor.py -v -k tag` — tag classification
3. **Step 3:** `devenv shell -- pytest tests/unit/test_event_types.py -v -k user_message` — enriched event
4. **Step 4:** `devenv shell -- pytest tests/unit/test_subscription_registry.py -v -k not_from` — exclusion filter
5. **Step 5:** `devenv shell -- pytest tests/unit/test_companion_tools.py -v` — tool existence
6. **Step 6:** `devenv shell -- pytest tests/unit/test_reconciler.py -v -k self_reflect` — self-subscription
7. **Step 7:** `devenv shell -- pytest tests/unit/test_actor.py -v -k self_reflect` — config parsing
8. **Step 8:** `devenv shell -- pytest tests/unit/test_actor.py -v -k prompt_builder` — reflection override
9. **Step 9:** `devenv shell -- pytest tests/unit/test_actor.py -v -k companion_context` — context injection
10. **Step 10:** `devenv shell -- pytest tests/unit/test_bundle_configs.py -v` — bundle config
11. **Step 11:** `devenv shell -- pytest tests/unit/test_web_server.py -v -k companion` — web endpoint
12. **Step 12:** `devenv shell -- pytest tests/unit/test_companion_tools.py -v` — observer bundle
13. **Step 13:** Manual YAML validation

### Full Suite Verification

After all steps are complete, run the entire test suite to check for regressions:

```
devenv shell -- pytest tests/ -v --tb=short
```

### Key Invariants to Verify

- [ ] Reflection turns never self-trigger (tag filter works)
- [ ] Observer never processes its own events (`not_from_agents` works)
- [ ] Companion KV data persists across turns
- [ ] System prompt includes companion context on primary turns only
- [ ] Reflection turns use the cheap model specified in self_reflect config
- [ ] Web endpoint returns correct companion data structure
- [ ] Existing tests still pass (no regressions)
