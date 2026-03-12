# Actor Model Implementation Guide

This guide provides step-by-step instructions for refactoring remora-v2's runtime to use the actor model described in `ACTOR_MODEL_CONCEPT.md`. Each step includes the exact files to create or modify, the changes to make, and the testing/validation required before moving to the next step.

**Ground rules:**
- Every step must pass all existing tests plus any new tests introduced in that step.
- No dead code, no backwards-compatibility shims, no dangling references. If something is replaced, delete the old version.
- Run the full test suite (`pytest`) at the end of every step. Do not move on until green.
- Read the referenced source files before modifying them. Understand existing code before changing it.

---

## Pre-Implementation: Understand the Codebase

Before writing any code, read and understand these files thoroughly:

| File | Why |
|---|---|
| `src/remora/core/runner.py` | This is the file being decomposed. Every line matters. |
| `src/remora/core/externals.py` | The agent API surface. Write methods move to outbox. |
| `src/remora/core/events/dispatcher.py` | The routing sink changes from global queue to per-actor inbox. |
| `src/remora/core/events/store.py` | Understand the append/fan-out flow. Not modified, but central to the design. |
| `src/remora/core/events/subscriptions.py` | Subscription matching. Not modified, but the actor model depends on it. |
| `src/remora/core/events/bus.py` | Broadcast mechanism. Not modified. |
| `src/remora/core/services.py` | Wiring container. Updated to pass actor registry reference. |
| `src/remora/core/graph.py` | NodeStore, AgentStore. Not modified, but actors use both. |
| `src/remora/core/workspace.py` | Workspace service. Not modified, but actors own workspace handles. |
| `src/remora/code/reconciler.py` | Emits discovery/removal events. Not modified in phase 1. |
| `src/remora/__main__.py` | Entry point. Minor update to `run_forever` semantics. |
| `src/remora/web/server.py` | Web server. Not modified (uses EventStore/NodeStore directly). |
| `src/remora/lsp/server.py` | LSP server. Not modified (uses EventStore/NodeStore directly). |

Also read every test file that will be affected:
- `tests/unit/test_runner.py`
- `tests/unit/test_externals.py`
- `tests/unit/test_event_store.py`
- `tests/integration/test_e2e.py`
- `tests/factories.py`

---

## Step 1: Create the Outbox

**Goal:** Create the `Outbox` class — a write-through emitter that wraps `EventStore.append()` with automatic metadata tagging. Also create `RecordingOutbox` for testing.

### 1.1 Create `src/remora/core/actor.py`

This file will contain `Outbox`, `RecordingOutbox`, and later `AgentActor`. Start with just the outbox.

```python
"""Actor model primitives: Outbox and AgentActor."""

from __future__ import annotations

import logging
from typing import Any

from remora.core.events.store import EventStore
from remora.core.events.types import Event

logger = logging.getLogger(__name__)


class Outbox:
    """Write-through emitter that tags events with actor metadata.

    Not a buffer — events reach EventStore immediately on emit().
    The outbox exists as an interception/tagging point, not as storage.
    """

    def __init__(
        self,
        actor_id: str,
        event_store: EventStore,
        correlation_id: str | None = None,
    ) -> None:
        self._actor_id = actor_id
        self._event_store = event_store
        self._correlation_id = correlation_id
        self._sequence = 0

    @property
    def actor_id(self) -> str:
        return self._actor_id

    @property
    def correlation_id(self) -> str | None:
        return self._correlation_id

    @correlation_id.setter
    def correlation_id(self, value: str | None) -> None:
        self._correlation_id = value

    @property
    def sequence(self) -> int:
        return self._sequence

    async def emit(self, event: Event) -> int:
        """Tag event with actor metadata and write through to EventStore."""
        self._sequence += 1
        if not event.correlation_id and self._correlation_id:
            event.correlation_id = self._correlation_id
        return await self._event_store.append(event)


class RecordingOutbox:
    """Test double that records emitted events without persisting.

    Drop-in replacement for Outbox in unit tests.
    """

    def __init__(self, actor_id: str = "test") -> None:
        self._actor_id = actor_id
        self._correlation_id: str | None = None
        self._sequence = 0
        self.events: list[Event] = []

    @property
    def actor_id(self) -> str:
        return self._actor_id

    @property
    def correlation_id(self) -> str | None:
        return self._correlation_id

    @correlation_id.setter
    def correlation_id(self, value: str | None) -> None:
        self._correlation_id = value

    @property
    def sequence(self) -> int:
        return self._sequence

    async def emit(self, event: Event) -> int:
        """Record event without persisting."""
        self._sequence += 1
        if not event.correlation_id and self._correlation_id:
            event.correlation_id = self._correlation_id
        self.events.append(event)
        return self._sequence
```

### 1.2 Create `tests/unit/test_actor.py`

Test the outbox in isolation:

```python
"""Tests for actor model primitives."""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

from remora.core.actor import Outbox, RecordingOutbox
from remora.core.db import AsyncDB
from remora.core.events import AgentStartEvent, AgentCompleteEvent, EventStore


@pytest_asyncio.fixture
async def outbox_env(tmp_path: Path):
    db = AsyncDB.from_path(tmp_path / "outbox.db")
    event_store = EventStore(db=db)
    await event_store.create_tables()
    outbox = Outbox(actor_id="agent-a", event_store=event_store, correlation_id="corr-1")
    yield outbox, event_store, db
    db.close()


@pytest.mark.asyncio
async def test_outbox_emit_persists_event(outbox_env) -> None:
    outbox, event_store, _db = outbox_env
    event_id = await outbox.emit(AgentStartEvent(agent_id="agent-a"))
    assert event_id == 1
    events = await event_store.get_events(limit=1)
    assert events[0]["event_type"] == "AgentStartEvent"


@pytest.mark.asyncio
async def test_outbox_tags_correlation_id(outbox_env) -> None:
    outbox, event_store, _db = outbox_env
    event = AgentStartEvent(agent_id="agent-a")
    assert event.correlation_id is None
    await outbox.emit(event)
    events = await event_store.get_events(limit=1)
    assert events[0]["correlation_id"] == "corr-1"


@pytest.mark.asyncio
async def test_outbox_preserves_existing_correlation_id(outbox_env) -> None:
    outbox, event_store, _db = outbox_env
    event = AgentStartEvent(agent_id="agent-a", correlation_id="original")
    await outbox.emit(event)
    events = await event_store.get_events(limit=1)
    assert events[0]["correlation_id"] == "original"


@pytest.mark.asyncio
async def test_outbox_increments_sequence(outbox_env) -> None:
    outbox, _event_store, _db = outbox_env
    assert outbox.sequence == 0
    await outbox.emit(AgentStartEvent(agent_id="agent-a"))
    assert outbox.sequence == 1
    await outbox.emit(AgentCompleteEvent(agent_id="agent-a"))
    assert outbox.sequence == 2


@pytest.mark.asyncio
async def test_outbox_correlation_id_setter(outbox_env) -> None:
    outbox, event_store, _db = outbox_env
    outbox.correlation_id = "new-corr"
    await outbox.emit(AgentStartEvent(agent_id="agent-a"))
    events = await event_store.get_events(limit=1)
    assert events[0]["correlation_id"] == "new-corr"


@pytest.mark.asyncio
async def test_recording_outbox_captures_events() -> None:
    outbox = RecordingOutbox(actor_id="test-agent")
    outbox.correlation_id = "corr-1"
    await outbox.emit(AgentStartEvent(agent_id="test-agent"))
    await outbox.emit(AgentCompleteEvent(agent_id="test-agent"))
    assert len(outbox.events) == 2
    assert outbox.events[0].event_type == "AgentStartEvent"
    assert outbox.events[1].event_type == "AgentCompleteEvent"
    assert all(e.correlation_id == "corr-1" for e in outbox.events)
    assert outbox.sequence == 2


@pytest.mark.asyncio
async def test_recording_outbox_no_persistence() -> None:
    outbox = RecordingOutbox()
    event_id = await outbox.emit(AgentStartEvent(agent_id="x"))
    assert event_id == 1  # sequence number, not DB id
    assert len(outbox.events) == 1
```

### 1.3 Validation

Run:
```bash
pytest tests/unit/test_actor.py -v
pytest  # full suite — nothing should break
```

**Checklist:**
- [ ] `Outbox.emit()` persists events to EventStore and returns event_id.
- [ ] `Outbox` auto-tags correlation_id when event doesn't have one.
- [ ] `Outbox` preserves existing correlation_id on events that already have one.
- [ ] `Outbox.sequence` increments monotonically per emit.
- [ ] `RecordingOutbox` captures events without persistence.
- [ ] `RecordingOutbox` tags correlation_id the same way `Outbox` does.
- [ ] All existing tests still pass (no regressions).

---

## Step 2: Create the AgentActor

**Goal:** Create `AgentActor` — a per-agent processing loop with inbox queue, outbox, and local policy state (cooldown, depth). The actor reuses the turn execution logic currently in `AgentRunner._execute_turn`.

### 2.1 Add `AgentActor` to `src/remora/core/actor.py`

Add the following imports at the top of `actor.py`:

```python
import asyncio
import time
import uuid
from dataclasses import dataclass

import yaml
from fsdantic import FileNotFoundError as FsdFileNotFoundError
from structured_agents import Message

from remora.core.config import Config
from remora.core.events import (
    AgentCompleteEvent,
    AgentErrorEvent,
    AgentStartEvent,
)
from remora.core.externals import AgentContext
from remora.core.grail import discover_tools
from remora.core.graph import AgentStore, NodeStore
from remora.core.kernel import create_kernel, extract_response_text
from remora.core.node import CodeNode
from remora.core.types import NodeStatus
from remora.core.workspace import AgentWorkspace, CairnWorkspaceService
```

Then add the `AgentActor` class:

```python
@dataclass
class Trigger:
    """A trigger waiting to be executed."""

    node_id: str
    correlation_id: str
    event: Event | None = None


class AgentActor:
    """Per-agent actor with inbox, outbox, and sequential processing loop.

    Each actor processes one inbox message at a time. Cooldown and depth
    policies are local to the actor, not shared globally.
    """

    def __init__(
        self,
        node_id: str,
        event_store: EventStore,
        node_store: NodeStore,
        agent_store: AgentStore,
        workspace_service: CairnWorkspaceService,
        config: Config,
        semaphore: asyncio.Semaphore,
    ) -> None:
        self.node_id = node_id
        self.inbox: asyncio.Queue[Event] = asyncio.Queue()
        self._event_store = event_store
        self._node_store = node_store
        self._agent_store = agent_store
        self._workspace_service = workspace_service
        self._config = config
        self._semaphore = semaphore
        self._task: asyncio.Task | None = None
        self._last_active: float = time.time()

        # Per-actor policy state (moved from global runner dicts)
        self._last_trigger_ms: float = 0.0
        self._depths: dict[str, int] = {}

    @property
    def last_active(self) -> float:
        return self._last_active

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        """Launch the actor's processing loop as a managed asyncio.Task."""
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(), name=f"actor-{self.node_id}")

    async def stop(self) -> None:
        """Cancel the processing loop and wait for it to finish."""
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def _run(self) -> None:
        """Main processing loop: consume inbox events one at a time."""
        try:
            while True:
                event = await self.inbox.get()
                self._last_active = time.time()
                correlation_id = event.correlation_id or str(uuid.uuid4())

                if not self._should_trigger(correlation_id):
                    continue

                outbox = Outbox(
                    actor_id=self.node_id,
                    event_store=self._event_store,
                    correlation_id=correlation_id,
                )
                trigger = Trigger(
                    node_id=self.node_id,
                    correlation_id=correlation_id,
                    event=event,
                )
                await self._execute_turn(trigger, outbox)
        except asyncio.CancelledError:
            return

    def _should_trigger(self, correlation_id: str) -> bool:
        """Check cooldown and depth policies. Returns True if trigger should proceed."""
        now_ms = time.time() * 1000.0

        # Cooldown check
        if now_ms - self._last_trigger_ms < self._config.trigger_cooldown_ms:
            return False
        self._last_trigger_ms = now_ms

        # Depth check
        depth = self._depths.get(correlation_id, 0)
        if depth >= self._config.max_trigger_depth:
            return False
        self._depths[correlation_id] = depth + 1

        # Clean stale depth entries
        # (done here rather than on a timer to keep it simple)
        return True

    async def _execute_turn(self, trigger: Trigger, outbox: Outbox) -> None:
        """Execute one agent turn. Reuses logic from the old AgentRunner._execute_turn."""
        node_id = trigger.node_id
        depth_key = trigger.correlation_id

        async with self._semaphore:
            try:
                node = await self._node_store.get_node(node_id)
                if node is None:
                    logger.warning("Trigger for unknown node: %s", node_id)
                    return

                if await self._agent_store.get_agent(node_id) is None:
                    await self._agent_store.upsert_agent(node.to_agent())
                if not await self._agent_store.transition_status(node_id, NodeStatus.RUNNING):
                    logger.warning("Failed to transition node %s into running state", node_id)
                    return
                await self._node_store.transition_status(node_id, NodeStatus.RUNNING)
                await outbox.emit(
                    AgentStartEvent(
                        agent_id=node_id,
                        node_name=node.name,
                        correlation_id=trigger.correlation_id,
                    )
                )

                workspace = await self._workspace_service.get_agent_workspace(node_id)
                bundle_config = await self._read_bundle_config(workspace)
                system_prompt = bundle_config.get(
                    "system_prompt",
                    "You are an autonomous code agent.",
                )
                model_name = bundle_config.get("model", self._config.model_default)
                max_turns = int(bundle_config.get("max_turns", self._config.max_turns))

                context = AgentContext(
                    node_id=node_id,
                    workspace=workspace,
                    correlation_id=trigger.correlation_id,
                    node_store=self._node_store,
                    agent_store=self._agent_store,
                    event_store=self._event_store,
                    outbox=outbox,
                )
                externals = context.to_externals_dict()
                tools = await self._resolve_maybe_awaitable(discover_tools(workspace, externals))

                messages = [
                    Message(role="system", content=system_prompt),
                    Message(role="user", content=self._build_prompt(node, trigger)),
                ]

                kernel = create_kernel(
                    model_name=model_name,
                    base_url=self._config.model_base_url,
                    api_key=self._config.model_api_key,
                    timeout=self._config.timeout_s,
                    tools=tools,
                )
                try:
                    tool_schemas = [tool.schema for tool in tools]
                    result = await kernel.run(messages, tool_schemas, max_turns=max_turns)
                finally:
                    await kernel.close()

                response_text = extract_response_text(result)
                await outbox.emit(
                    AgentCompleteEvent(
                        agent_id=node_id,
                        result_summary=response_text[:200],
                        correlation_id=trigger.correlation_id,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - boundary should never crash loop
                logger.exception("Agent turn failed for %s", node_id)
                await self._agent_store.transition_status(node_id, NodeStatus.ERROR)
                await self._node_store.transition_status(node_id, NodeStatus.ERROR)
                await outbox.emit(
                    AgentErrorEvent(
                        agent_id=node_id,
                        error=str(exc),
                        correlation_id=trigger.correlation_id,
                    )
                )
            finally:
                try:
                    current_agent = await self._agent_store.get_agent(node_id)
                    if current_agent is not None and current_agent.status == NodeStatus.RUNNING:
                        await self._agent_store.transition_status(node_id, NodeStatus.IDLE)
                    current_node = await self._node_store.get_node(node_id)
                    if current_node is not None and current_node.status == NodeStatus.RUNNING:
                        await self._node_store.transition_status(node_id, NodeStatus.IDLE)
                except Exception:  # noqa: BLE001 - best effort cleanup
                    logger.exception("Failed to reset node status for %s", node_id)
                remaining = self._depths.get(depth_key, 1) - 1
                if remaining <= 0:
                    self._depths.pop(depth_key, None)
                else:
                    self._depths[depth_key] = remaining

    @staticmethod
    def _build_prompt(node: CodeNode, trigger: Trigger) -> str:
        """Build the turn prompt from node identity and trigger details."""
        parts = [
            f"# Node: {node.full_name}",
            f"Type: {node.node_type} | File: {node.file_path}:{node.start_line}-{node.end_line}",
            "",
            "## Source Code",
            "```",
            node.source_code,
            "```",
        ]
        if trigger.event is not None:
            parts.extend(["", "## Trigger", f"Event: {trigger.event.event_type}"])
            content = _event_content(trigger.event)
            if content:
                parts.append(f"Content: {content}")
        return "\n".join(parts)

    @staticmethod
    async def _resolve_maybe_awaitable(value: Any) -> Any:
        if asyncio.iscoroutine(value):
            return await value
        return value

    @staticmethod
    async def _read_bundle_config(workspace: AgentWorkspace) -> dict[str, Any]:
        try:
            text = await workspace.read("_bundle/bundle.yaml")
        except (FileNotFoundError, FsdFileNotFoundError):
            return {}
        return yaml.safe_load(text) or {}


def _event_content(event: Event) -> str:
    if hasattr(event, "content"):
        return str(event.content)
    if hasattr(event, "message"):
        return str(event.message)
    return ""
```

**Important:** The `AgentActor._execute_turn` method is essentially the same logic as the current `AgentRunner._execute_turn`, with two differences:
1. It uses `outbox.emit()` instead of `self._event_store.append()` for agent lifecycle events.
2. It passes `outbox` to `AgentContext` (see Step 3).

### 2.2 Update `__all__` in `src/remora/core/actor.py`

```python
__all__ = ["Outbox", "RecordingOutbox", "Trigger", "AgentActor"]
```

### 2.3 Add actor tests to `tests/unit/test_actor.py`

Add these tests after the existing outbox tests:

```python
from remora.core.actor import AgentActor, Trigger
from remora.core.config import Config
from remora.core.events import AgentMessageEvent, HumanChatEvent
from remora.core.graph import AgentStore, NodeStore
from remora.core.workspace import CairnWorkspaceService
from tests.factories import make_node


@pytest_asyncio.fixture
async def actor_env(tmp_path: Path):
    db = AsyncDB.from_path(tmp_path / "actor.db")
    node_store = NodeStore(db)
    agent_store = AgentStore(db)
    await node_store.create_tables()
    await agent_store.create_tables()
    event_store = EventStore(db=db)
    await event_store.create_tables()
    config = Config(
        swarm_root=".remora-actor-test",
        trigger_cooldown_ms=1000,
        max_trigger_depth=2,
    )
    workspace_service = CairnWorkspaceService(config, tmp_path)
    await workspace_service.initialize()
    semaphore = asyncio.Semaphore(4)

    yield {
        "db": db,
        "node_store": node_store,
        "agent_store": agent_store,
        "event_store": event_store,
        "config": config,
        "workspace_service": workspace_service,
        "semaphore": semaphore,
    }

    await workspace_service.close()
    db.close()


def _make_actor(env: dict, node_id: str = "src/app.py::a") -> AgentActor:
    return AgentActor(
        node_id=node_id,
        event_store=env["event_store"],
        node_store=env["node_store"],
        agent_store=env["agent_store"],
        workspace_service=env["workspace_service"],
        config=env["config"],
        semaphore=env["semaphore"],
    )


@pytest.mark.asyncio
async def test_actor_start_stop(actor_env) -> None:
    actor = _make_actor(actor_env)
    actor.start()
    assert actor.is_running
    await actor.stop()
    assert not actor.is_running


@pytest.mark.asyncio
async def test_actor_cooldown(actor_env) -> None:
    actor = _make_actor(actor_env)
    # First trigger should pass cooldown
    assert actor._should_trigger("c1")
    # Second trigger within cooldown window should fail
    assert not actor._should_trigger("c1")


@pytest.mark.asyncio
async def test_actor_depth_limit(actor_env) -> None:
    actor = _make_actor(actor_env)
    # max_trigger_depth=2, so first two pass, third fails
    assert actor._should_trigger("c1")
    # Reset cooldown by advancing _last_trigger_ms
    actor._last_trigger_ms = 0.0
    assert actor._should_trigger("c1")
    actor._last_trigger_ms = 0.0
    assert not actor._should_trigger("c1")  # depth=2, limit=2


@pytest.mark.asyncio
async def test_actor_processes_inbox_message(actor_env, monkeypatch) -> None:
    env = actor_env
    node = make_node("src/app.py::a")
    await env["node_store"].upsert_node(node)
    ws = await env["workspace_service"].get_agent_workspace(node.node_id)
    await ws.write("_bundle/bundle.yaml", "system_prompt: hi\nmodel: mock\nmax_turns: 1\n")

    from types import SimpleNamespace
    from structured_agents import Message

    class MockKernel:
        async def run(self, _messages, _tools, max_turns=20):
            del max_turns
            return SimpleNamespace(final_message=Message(role="assistant", content="ok"))
        async def close(self):
            return None

    monkeypatch.setattr("remora.core.actor.create_kernel", lambda **_kwargs: MockKernel())
    monkeypatch.setattr("remora.core.actor.discover_tools", lambda *_args, **_kwargs: [])

    actor = _make_actor(env, node.node_id)
    event = HumanChatEvent(to_agent=node.node_id, message="hello", correlation_id="corr-1")

    outbox = Outbox(actor_id=node.node_id, event_store=env["event_store"], correlation_id="corr-1")
    trigger = Trigger(node_id=node.node_id, correlation_id="corr-1", event=event)
    await actor._execute_turn(trigger, outbox)

    events = await env["event_store"].get_events(limit=10)
    event_types = [e["event_type"] for e in events]
    assert "AgentStartEvent" in event_types
    assert "AgentCompleteEvent" in event_types

    updated = await env["node_store"].get_node(node.node_id)
    assert updated is not None
    assert updated.status == "idle"


@pytest.mark.asyncio
async def test_actor_missing_node(actor_env) -> None:
    actor = _make_actor(actor_env, "missing-node")
    outbox = Outbox(actor_id="missing-node", event_store=actor_env["event_store"])
    trigger = Trigger(node_id="missing-node", correlation_id="c1")
    await actor._execute_turn(trigger, outbox)
    events = await actor_env["event_store"].get_events(limit=5)
    assert not any(e["event_type"] == "AgentStartEvent" for e in events)
```

### 2.4 Validation

```bash
pytest tests/unit/test_actor.py -v
pytest  # full suite
```

**Checklist:**
- [ ] `AgentActor` can start and stop its processing loop cleanly.
- [ ] `_should_trigger` enforces cooldown (rejects triggers within cooldown window).
- [ ] `_should_trigger` enforces depth limit (rejects after max_trigger_depth reached).
- [ ] `_execute_turn` runs a full turn lifecycle (start event, kernel execution, complete event, status reset).
- [ ] `_execute_turn` handles missing nodes gracefully (no crash, no start event).
- [ ] All events emitted during turn go through outbox, not direct EventStore.append().
- [ ] All existing tests still pass.

---

## Step 3: Wire Outbox into AgentContext

**Goal:** Modify `AgentContext` so that all write methods use the outbox instead of calling `event_store.append()` directly. Read methods remain unchanged (direct store access).

### 3.1 Modify `src/remora/core/externals.py`

**Change the constructor** to accept an optional `outbox` parameter:

In the `__init__` method, add `outbox` as the last parameter:

```python
def __init__(
    self,
    node_id: str,
    workspace: AgentWorkspace,
    correlation_id: str | None,
    node_store: NodeStore,
    agent_store: AgentStore,
    event_store: EventStore,
    outbox: Any | None = None,
) -> None:
    self.node_id = node_id
    self.workspace = workspace
    self.correlation_id = correlation_id
    self._node_store = node_store
    self._agent_store = agent_store
    self._event_store = event_store
    self._outbox = outbox
```

Add a helper property:

```python
async def _emit(self, event: Event) -> int:
    """Emit an event through outbox if available, otherwise direct to store."""
    if self._outbox is not None:
        return await self._outbox.emit(event)
    return await self._event_store.append(event)
```

**Note on `_emit` fallback:** The `if self._outbox is not None` branch exists only as a transitional measure during this step. By the end of the refactor (Step 6), every `AgentContext` will be constructed with an outbox, and the fallback to `event_store.append()` will be removed. The fallback is necessary now because existing tests construct `AgentContext` without an outbox.

**Change these methods** to use `self._emit()` instead of `self._event_store.append()`:

1. `event_emit` (line 98-105):
```python
async def event_emit(self, event_type: str, payload: dict[str, Any]) -> bool:
    event = CustomEvent(
        event_type=event_type,
        payload=payload,
        correlation_id=self.correlation_id,
    )
    await self._emit(event)
    return True
```

2. `send_message` (line 126-135):
```python
async def send_message(self, to_node_id: str, content: str) -> bool:
    await self._emit(
        AgentMessageEvent(
            from_agent=self.node_id,
            to_agent=to_node_id,
            content=content,
            correlation_id=self.correlation_id,
        )
    )
    return True
```

3. `broadcast` (line 137-149):
```python
async def broadcast(self, pattern: str, content: str) -> str:
    nodes = await self._node_store.list_nodes()
    target_ids = _resolve_broadcast_targets(self.node_id, pattern, nodes)
    for target_id in target_ids:
        await self._emit(
            AgentMessageEvent(
                from_agent=self.node_id,
                to_agent=target_id,
                content=content,
                correlation_id=self.correlation_id,
            )
        )
    return f"Broadcast sent to {len(target_ids)} agents"
```

4. `apply_rewrite` (line 151-182):
Change only the `event_store.append` call near the end:
```python
await self._emit(
    ContentChangedEvent(
        path=str(file_path),
        change_type="modified",
        agent_id=self.node_id,
        old_hash=old_hash,
        new_hash=new_hash,
        correlation_id=self.correlation_id,
    )
)
```

Also add the import for `Event` at the top if not already present:
```python
from remora.core.events.types import Event
```

**Methods that stay unchanged (direct reads):**
- `read_file`, `write_file`, `list_dir`, `file_exists`, `search_files`, `search_content` — workspace operations
- `graph_get_node`, `graph_query_nodes`, `graph_get_edges` — read from NodeStore
- `graph_set_status` — writes to stores directly (status transitions are not events going through the outbox)
- `event_get_history`, `get_node_source` — reads from stores
- `event_subscribe`, `event_unsubscribe` — writes to subscription registry (not event stream writes)

### 3.2 Update `tests/unit/test_externals.py`

Existing tests should continue to pass without modification because `outbox` defaults to `None` and the `_emit` helper falls back to `event_store.append()`.

Add one new test to verify outbox integration:

```python
from remora.core.actor import RecordingOutbox

@pytest.mark.asyncio
async def test_externals_emit_uses_outbox_when_provided(context_env) -> None:
    node_store, agent_store, event_store, workspace_service = context_env
    node = make_node("src/app.py::alpha")
    await node_store.upsert_node(node)
    await agent_store.upsert_agent(node.to_agent())
    ws = await workspace_service.get_agent_workspace(node.node_id)

    outbox = RecordingOutbox(actor_id=node.node_id)
    outbox.correlation_id = "corr-outbox"
    context = AgentContext(
        node_id=node.node_id,
        workspace=ws,
        correlation_id="corr-outbox",
        node_store=node_store,
        agent_store=agent_store,
        event_store=event_store,
        outbox=outbox,
    )
    externals = context.to_externals_dict()

    await externals["event_emit"]("CustomEvent", {"key": "val"})
    await externals["send_message"]("target-node", "hello")

    assert len(outbox.events) == 2
    assert outbox.events[0].event_type == "CustomEvent"
    assert outbox.events[1].event_type == "AgentMessageEvent"

    # Verify events did NOT go to EventStore
    stored = await event_store.get_events(limit=10)
    assert not any(e["event_type"] == "CustomEvent" for e in stored)
```

### 3.3 Validation

```bash
pytest tests/unit/test_externals.py -v
pytest tests/unit/test_actor.py -v
pytest  # full suite
```

**Checklist:**
- [ ] All existing externals tests pass unchanged (fallback to `event_store.append()` works).
- [ ] New test verifies that when an outbox is provided, write methods route through it.
- [ ] Read methods (`graph_get_node`, `event_get_history`, etc.) still read directly from stores.
- [ ] `RecordingOutbox` captures events emitted via `AgentContext`.
- [ ] Full suite passes.

---

## Step 4: Modify TriggerDispatcher to Route to Per-Agent Inboxes

**Goal:** Change `TriggerDispatcher` so that instead of putting all triggers in one global queue, it routes events to per-agent inbox queues via an actor registry callback.

### 4.1 Modify `src/remora/core/events/dispatcher.py`

Replace the entire file with:

```python
"""Trigger dispatch: routes events to matching agents via subscriptions."""

from __future__ import annotations

from collections.abc import Callable

from remora.core.events.subscriptions import SubscriptionRegistry
from remora.core.events.types import Event


class TriggerDispatcher:
    """Routes persisted events to agent inboxes via subscription matching.

    The dispatcher resolves which agents care about an event, then
    delivers the event to each agent's inbox via a router callback.
    """

    def __init__(
        self,
        subscriptions: SubscriptionRegistry,
        router: Callable[[str, Event], None] | None = None,
    ):
        self._subscriptions = subscriptions
        self._router = router

    @property
    def router(self) -> Callable[[str, Event], None] | None:
        return self._router

    @router.setter
    def router(self, value: Callable[[str, Event], None]) -> None:
        self._router = value

    async def dispatch(self, event: Event) -> None:
        """Match event against subscriptions and route to agent inboxes."""
        if self._router is None:
            return
        for agent_id in await self._subscriptions.get_matching_agents(event):
            self._router(agent_id, event)

    @property
    def subscriptions(self) -> SubscriptionRegistry:
        return self._subscriptions


__all__ = ["TriggerDispatcher"]
```

**What changed:**
- Removed the global `asyncio.Queue` (`self._queue`).
- Removed `get_triggers()` async generator (no longer needed — each actor has its own inbox).
- Added `router` callback: `Callable[[str, Event], None]` — called for each matching agent. The runner sets this to route events into actor inboxes.
- If no router is set, `dispatch()` is a no-op (safe default for tests that don't need routing).
- Removed the `asyncio` import (no longer needed).

### 4.2 Update `src/remora/core/events/store.py`

Remove the `get_triggers` method (lines 135-138), which was a backwards-compatible wrapper around `dispatcher.get_triggers()`:

Delete this method entirely:
```python
async def get_triggers(self) -> AsyncIterator[tuple[str, Event]]:
    """Backward-compatible trigger iterator."""
    async for item in self._dispatcher.get_triggers():
        yield item
```

Also remove the `AsyncIterator` import from the `collections.abc` import line since it's no longer used. Update the import to:
```python
from collections.abc import AsyncIterator  # REMOVE THIS
```

Check if `AsyncIterator` is used elsewhere in the file. If not, remove the import. (It is not used elsewhere — the only usage was in `get_triggers`.)

Also remove the unused `asyncio` import if it's only used by `get_triggers`. Check: `asyncio.Lock` is used via the `lock` property. So `asyncio` stays.

### 4.3 Update `tests/unit/test_event_store.py`

The test `test_eventstore_trigger_flow` (lines 60-72) uses `store.get_triggers()`, which no longer exists. **Replace it** with a test that verifies the dispatcher routes to a callback:

```python
@pytest.mark.asyncio
async def test_eventstore_trigger_routes_via_dispatcher(tmp_path: Path) -> None:
    db = AsyncDB.from_path(tmp_path / "events.db")
    store = EventStore(db=db)
    await store.create_tables()
    await store.subscriptions.register("agent-b", SubscriptionPattern(to_agent="b"))

    routed: list[tuple[str, Event]] = []
    store.dispatcher.router = lambda agent_id, event: routed.append((agent_id, event))

    event = AgentMessageEvent(from_agent="a", to_agent="b", content="hello")
    await store.append(event)

    assert len(routed) == 1
    assert routed[0][0] == "agent-b"
    assert routed[0][1] == event
    db.close()
```

### 4.4 Update `tests/integration/test_e2e.py`

Three tests use `runtime["event_store"].get_triggers()`:
- `test_e2e_human_chat_to_rewrite` (line 120-121)
- `test_e2e_agent_message_chain` (line 207-208)
- `test_e2e_file_change_triggers` (line 224-225)

These tests verify that events reach the right agent via subscription matching. Replace the `get_triggers()` pattern with a router callback pattern.

For each test that uses `get_triggers()`, replace the trigger consumption with a captured route list. Here's the pattern:

In `_setup_runtime`, add a route capture list after creating the runner:
```python
routed: list[tuple[str, Event]] = []
runtime["event_store"].dispatcher.router = lambda aid, evt: routed.append((aid, evt))
# ... return routed in the runtime dict
runtime["routed"] = routed
```

Wait — the runner will also set its own router (see Step 5). For e2e tests, we need to decide: do these tests exercise the full actor flow, or just subscription routing?

**The simplest approach:** In the e2e tests that only check routing (not full turn execution), set a recording router. In the test that checks full turn execution (`test_e2e_human_chat_to_rewrite`), use the runner's router.

Update `_setup_runtime` to store the routed events:
```python
routed: list[tuple[str, Any]] = []

def capture_route(agent_id: str, event: Any) -> None:
    routed.append((agent_id, event))

runtime["event_store"].dispatcher.router = capture_route
runtime["routed"] = routed
```

Then update the three tests:

**`test_e2e_agent_message_chain`:** Replace the `get_triggers()` usage:
```python
@pytest.mark.asyncio
async def test_e2e_agent_message_chain(tmp_path: Path) -> None:
    runtime = await _setup_runtime(tmp_path)
    nodes = runtime["nodes"]
    source = nodes[0].node_id
    target = nodes[1].node_id

    await runtime["event_store"].append(
        AgentMessageEvent(from_agent=source, to_agent=target, content="hello")
    )
    assert len(runtime["routed"]) >= 1
    routed_agent_id, routed_event = runtime["routed"][-1]
    assert routed_agent_id == target
    assert routed_event.event_type == "AgentMessageEvent"

    await runtime["workspace_service"].close()
    runtime["db"].close()
```

**`test_e2e_file_change_triggers`:** Same pattern:
```python
@pytest.mark.asyncio
async def test_e2e_file_change_triggers(tmp_path: Path) -> None:
    runtime = await _setup_runtime(tmp_path)
    node = runtime["nodes"][0]

    await runtime["event_store"].append(
        ContentChangedEvent(path=node.file_path, change_type="modified")
    )
    matching = [(aid, evt) for aid, evt in runtime["routed"] if aid == node.node_id and evt.event_type == "ContentChangedEvent"]
    assert len(matching) >= 1

    await runtime["workspace_service"].close()
    runtime["db"].close()
```

**`test_e2e_human_chat_to_rewrite`:** This test exercises full turn execution. It currently consumes from `get_triggers()` then manually calls `runner._execute_turn()`. Under the actor model, the dispatcher routes to the actor's inbox, and the actor runs the turn. For now (this step), keep the manual `_execute_turn` call but get the trigger info from the routed list:

```python
# Replace these lines:
#   trigger_iter = runtime["event_store"].get_triggers()
#   trigger_node_id, trigger_event = await asyncio.wait_for(trigger_iter.__anext__(), timeout=1.0)
#   assert trigger_node_id == node.node_id

# With:
await runtime["event_store"].append(
    HumanChatEvent(to_agent=node.node_id, message="please rewrite")
)
assert len(runtime["routed"]) >= 1
trigger_node_id, trigger_event = runtime["routed"][-1]
assert trigger_node_id == node.node_id
```

Remove the duplicate `await runtime["event_store"].append(HumanChatEvent(...))` if there was one before the old `get_triggers` call.

### 4.5 Validation

```bash
pytest tests/unit/test_event_store.py -v
pytest tests/integration/test_e2e.py -v
pytest  # full suite
```

**Checklist:**
- [ ] `TriggerDispatcher` no longer has a global queue or `get_triggers()`.
- [ ] `TriggerDispatcher` routes to a callback set via the `router` property.
- [ ] `EventStore.get_triggers()` is removed.
- [ ] All references to `get_triggers()` in tests are replaced with router callback assertions.
- [ ] `dispatch()` is a no-op when no router is set (safe for tests that don't care about routing).
- [ ] Full suite passes.

---

## Step 5: Refactor AgentRunner to Actor Registry

**Goal:** Replace `AgentRunner`'s centralized execution loop with an actor registry. The runner creates/manages `AgentActor` instances, sets itself as the dispatcher's router, and routes incoming events to per-agent inboxes.

### 5.1 Rewrite `src/remora/core/runner.py`

Replace the entire file with:

```python
"""Agent runner: actor registry and lifecycle manager."""

from __future__ import annotations

import asyncio
import logging
import time

from remora.core.actor import AgentActor, Trigger
from remora.core.config import Config
from remora.core.events import EventStore, TriggerDispatcher
from remora.core.events.types import Event
from remora.core.graph import AgentStore, NodeStore
from remora.core.workspace import CairnWorkspaceService

logger = logging.getLogger(__name__)


class AgentRunner:
    """Actor registry and lifecycle manager for agent execution.

    Creates AgentActor instances lazily on first trigger and routes
    events from the dispatcher to per-agent inboxes.
    """

    def __init__(
        self,
        event_store: EventStore,
        node_store: NodeStore,
        agent_store: AgentStore,
        workspace_service: CairnWorkspaceService,
        config: Config,
        dispatcher: TriggerDispatcher | None = None,
    ):
        self._event_store = event_store
        self._dispatcher = dispatcher or event_store.dispatcher
        self._node_store = node_store
        self._agent_store = agent_store
        self._workspace_service = workspace_service
        self._config = config
        self._running = False
        self._semaphore = asyncio.Semaphore(config.max_concurrency)
        self._actors: dict[str, AgentActor] = {}

        # Set ourselves as the dispatcher's router
        self._dispatcher.router = self._route_to_actor

    def _route_to_actor(self, agent_id: str, event: Event) -> None:
        """Route an event to the target agent's inbox, creating the actor if needed."""
        actor = self.get_or_create_actor(agent_id)
        actor.inbox.put_nowait(event)

    def get_or_create_actor(self, node_id: str) -> AgentActor:
        """Get an existing actor or create a new one for the given node."""
        if node_id not in self._actors:
            actor = AgentActor(
                node_id=node_id,
                event_store=self._event_store,
                node_store=self._node_store,
                agent_store=self._agent_store,
                workspace_service=self._workspace_service,
                config=self._config,
                semaphore=self._semaphore,
            )
            actor.start()
            self._actors[node_id] = actor
            logger.debug("Created actor for %s", node_id)
        return self._actors[node_id]

    async def run_forever(self) -> None:
        """Run until stopped. Actors process their own inboxes."""
        self._running = True
        try:
            while self._running:
                await asyncio.sleep(1.0)
                await self._evict_idle()
        except asyncio.CancelledError:
            pass
        finally:
            self._running = False

    def stop(self) -> None:
        """Signal the runner to stop."""
        self._running = False

    async def stop_and_wait(self) -> None:
        """Stop all actors and wait for them to finish."""
        self._running = False
        tasks = []
        for actor in self._actors.values():
            tasks.append(actor.stop())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._actors.clear()

    async def _evict_idle(self, max_idle_seconds: float = 300.0) -> None:
        """Stop and remove actors that have been idle longer than threshold."""
        now = time.time()
        to_evict = [
            node_id
            for node_id, actor in self._actors.items()
            if now - actor.last_active > max_idle_seconds and actor.inbox.empty()
        ]
        for node_id in to_evict:
            actor = self._actors.pop(node_id)
            await actor.stop()
            logger.debug("Evicted idle actor: %s", node_id)

    @property
    def actors(self) -> dict[str, AgentActor]:
        """Read-only access to actor registry (for observability)."""
        return dict(self._actors)


# Re-export Trigger for backwards compatibility with tests
# that import it from runner. This will be removed after test migration.
__all__ = ["AgentRunner", "Trigger"]
```

**What changed from the old runner:**
- Removed: `_cooldowns` dict, `_depths` dict (moved to per-actor state).
- Removed: `trigger()` method (actors handle their own trigger policy).
- Removed: `_execute_turn()` method (moved to `AgentActor`).
- Removed: `_build_prompt()`, `_event_content()`, `_read_bundle_config()`, `_resolve_maybe_awaitable()` (moved to `AgentActor`).
- Added: `_actors` registry dict.
- Added: `get_or_create_actor()` for lazy actor creation.
- Added: `_route_to_actor()` callback set on dispatcher.
- Added: `_evict_idle()` for memory management.
- Added: `stop_and_wait()` for clean shutdown.
- Changed: `run_forever()` no longer consumes a global queue. It runs a maintenance loop (idle eviction). Actual event processing happens in actor tasks.

**`Trigger` re-export:** The `Trigger` dataclass was moved to `actor.py`. The `from remora.core.runner import Trigger` import in tests still needs to work. We re-export it here temporarily. It will be cleaned up in Step 6.

### 5.2 Update `src/remora/core/services.py`

The `RuntimeServices.initialize()` method creates the runner. No changes needed to the constructor or initialization — the runner's constructor already sets itself as the dispatcher's router.

However, update the `close()` method to use `stop_and_wait()`:

```python
async def close(self) -> None:
    """Shut down all services."""
    if self.reconciler is not None:
        self.reconciler.stop()
    if self.runner is not None:
        await self.runner.stop_and_wait()
    await self.workspace_service.close()
    self.db.close()
```

Note: The old `close()` called `self.runner.stop()` (synchronous). The new version awaits `stop_and_wait()` to cleanly shut down all actor tasks.

### 5.3 Update `src/remora/__main__.py`

No changes needed. The `_start` function already calls `services.runner.run_forever()` and `services.close()`. The runner's `run_forever()` now does idle eviction instead of queue consumption, but the interface is the same. The `services.close()` call now awaits actor shutdown.

### 5.4 Rewrite `tests/unit/test_runner.py`

The existing tests test the old runner's `trigger()` method, `_execute_turn()`, `_cooldowns`, and `_depths` directly. These have all moved to `AgentActor`. Replace the runner tests with tests for the new runner's registry and routing behavior:

```python
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import pytest_asyncio

from remora.core.actor import AgentActor
from remora.core.config import Config
from remora.core.db import AsyncDB
from remora.core.events import AgentMessageEvent, EventStore, HumanChatEvent, SubscriptionPattern
from remora.core.graph import AgentStore, NodeStore
from remora.core.runner import AgentRunner
from remora.core.workspace import CairnWorkspaceService
from tests.factories import make_node


@pytest_asyncio.fixture
async def runner_env(tmp_path: Path):
    db = AsyncDB.from_path(tmp_path / "runner.db")
    node_store = NodeStore(db)
    agent_store = AgentStore(db)
    await node_store.create_tables()
    await agent_store.create_tables()
    event_store = EventStore(db=db)
    await event_store.create_tables()
    config = Config(swarm_root=".remora-runner-test", trigger_cooldown_ms=1000, max_trigger_depth=2)
    workspace_service = CairnWorkspaceService(config, tmp_path)
    await workspace_service.initialize()
    runner = AgentRunner(event_store, node_store, agent_store, workspace_service, config)

    yield runner, node_store, agent_store, event_store, workspace_service

    await runner.stop_and_wait()
    await workspace_service.close()
    db.close()


@pytest.mark.asyncio
async def test_runner_creates_actor_on_route(runner_env) -> None:
    runner, _ns, _as, _es, _ws = runner_env
    assert len(runner.actors) == 0
    actor = runner.get_or_create_actor("agent-a")
    assert isinstance(actor, AgentActor)
    assert actor.is_running
    assert "agent-a" in runner.actors


@pytest.mark.asyncio
async def test_runner_reuses_existing_actor(runner_env) -> None:
    runner, _ns, _as, _es, _ws = runner_env
    actor1 = runner.get_or_create_actor("agent-a")
    actor2 = runner.get_or_create_actor("agent-a")
    assert actor1 is actor2


@pytest.mark.asyncio
async def test_runner_routes_dispatch_to_actor_inbox(runner_env) -> None:
    runner, _ns, _as, event_store, _ws = runner_env
    await event_store.subscriptions.register("agent-x", SubscriptionPattern(to_agent="x"))
    event = AgentMessageEvent(from_agent="a", to_agent="x", content="hello")
    await event_store.append(event)

    # Dispatch should have created actor and put event in inbox
    assert "agent-x" in runner.actors
    actor = runner.actors["agent-x"]
    assert actor.inbox.qsize() >= 1


@pytest.mark.asyncio
async def test_runner_evicts_idle_actors(runner_env) -> None:
    runner, _ns, _as, _es, _ws = runner_env
    actor = runner.get_or_create_actor("idle-agent")
    # Backdate last_active to trigger eviction
    actor._last_active = 0.0
    await runner._evict_idle(max_idle_seconds=1.0)
    assert "idle-agent" not in runner.actors
    assert not actor.is_running


@pytest.mark.asyncio
async def test_runner_does_not_evict_busy_actors(runner_env) -> None:
    runner, _ns, _as, _es, _ws = runner_env
    actor = runner.get_or_create_actor("busy-agent")
    actor._last_active = 0.0
    await actor.inbox.put(AgentMessageEvent(from_agent="a", to_agent="b", content="x"))
    # inbox is not empty, so actor should not be evicted
    await runner._evict_idle(max_idle_seconds=1.0)
    assert "busy-agent" in runner.actors


@pytest.mark.asyncio
async def test_runner_stop_and_wait(runner_env) -> None:
    runner, _ns, _as, _es, _ws = runner_env
    runner.get_or_create_actor("a")
    runner.get_or_create_actor("b")
    assert len(runner.actors) == 2
    await runner.stop_and_wait()
    assert len(runner.actors) == 0


@pytest.mark.asyncio
async def test_runner_build_prompt_via_actor(runner_env, monkeypatch) -> None:
    runner, node_store, _as, event_store, workspace_service = runner_env
    node = make_node("src/app.py::a")
    await node_store.upsert_node(node)
    ws = await workspace_service.get_agent_workspace(node.node_id)
    await ws.write("_bundle/bundle.yaml", "system_prompt: hi\nmodel: mock\nmax_turns: 1\n")

    from remora.core.actor import Trigger
    actor = runner.get_or_create_actor(node.node_id)
    prompt = actor._build_prompt(
        node,
        Trigger(
            node_id=node.node_id,
            correlation_id="c1",
            event=HumanChatEvent(to_agent=node.node_id, message="hello"),
        ),
    )
    assert node.full_name in prompt
    assert "hello" in prompt
```

### 5.5 Update `tests/integration/test_e2e.py`

The e2e test `test_e2e_human_chat_to_rewrite` currently calls `runner._execute_turn()` directly. Under the actor model, turns are executed by actors. Update this test to use the actor:

In `_setup_runtime`, the runner now auto-sets itself as the dispatcher's router. Remove the `capture_route` code added in Step 4 for `_setup_runtime`. The runner's routing will create actors and fill their inboxes.

Update `_setup_runtime` to NOT set a manual router (the runner sets it):
```python
# Remove the routed capture code from Step 4.
# The runner's constructor sets dispatcher.router automatically.
# Don't override it here.
```

But the two routing-only tests (`test_e2e_agent_message_chain`, `test_e2e_file_change_triggers`) need to verify routing happened. They can check the actor inbox instead:

```python
@pytest.mark.asyncio
async def test_e2e_agent_message_chain(tmp_path: Path) -> None:
    runtime = await _setup_runtime(tmp_path)
    nodes = runtime["nodes"]
    source = nodes[0].node_id
    target = nodes[1].node_id

    await runtime["event_store"].append(
        AgentMessageEvent(from_agent=source, to_agent=target, content="hello")
    )
    assert target in runtime["runner"].actors
    actor = runtime["runner"].actors[target]
    assert actor.inbox.qsize() >= 1

    await runtime["runner"].stop_and_wait()
    await runtime["workspace_service"].close()
    runtime["db"].close()


@pytest.mark.asyncio
async def test_e2e_file_change_triggers(tmp_path: Path) -> None:
    runtime = await _setup_runtime(tmp_path)
    node = runtime["nodes"][0]

    await runtime["event_store"].append(
        ContentChangedEvent(path=node.file_path, change_type="modified")
    )
    assert node.node_id in runtime["runner"].actors
    actor = runtime["runner"].actors[node.node_id]
    assert actor.inbox.qsize() >= 1

    await runtime["runner"].stop_and_wait()
    await runtime["workspace_service"].close()
    runtime["db"].close()
```

For `test_e2e_human_chat_to_rewrite`, instead of calling `runner._execute_turn()` directly, call the actor's `_execute_turn()`:

```python
# Replace:
#   await runtime["runner"]._execute_turn(Trigger(...))
# With:
from remora.core.actor import Outbox, Trigger

actor = runtime["runner"].get_or_create_actor(node.node_id)
outbox = Outbox(
    actor_id=node.node_id,
    event_store=runtime["event_store"],
    correlation_id="corr-e2e",
)
await actor._execute_turn(
    Trigger(node_id=node.node_id, correlation_id="corr-e2e", event=trigger_event),
    outbox,
)
```

Also update the cleanup at the end of each test to call `runner.stop_and_wait()`:
```python
await runtime["runner"].stop_and_wait()
await runtime["workspace_service"].close()
runtime["db"].close()
```

### 5.6 Validation

```bash
pytest tests/unit/test_runner.py -v
pytest tests/unit/test_actor.py -v
pytest tests/integration/test_e2e.py -v
pytest  # full suite
```

**Checklist:**
- [ ] `AgentRunner` no longer has `trigger()`, `_execute_turn()`, `_cooldowns`, `_depths`, or `_build_prompt`.
- [ ] `AgentRunner` manages an actor registry via `get_or_create_actor()`.
- [ ] `AgentRunner` sets itself as the dispatcher's router on construction.
- [ ] Events dispatched by subscription matching arrive in the correct actor's inbox.
- [ ] Idle eviction removes actors that haven't been active.
- [ ] `stop_and_wait()` cleanly stops all actors.
- [ ] `RuntimeServices.close()` properly shuts down actors.
- [ ] All runner tests are rewritten to test registry behavior, not centralized execution.
- [ ] All e2e tests pass with actor-based execution.
- [ ] Full suite passes.

---

## Step 6: Cleanup — Remove All Dead Code and Transitional Shims

**Goal:** Remove all backwards-compatibility shims, dead imports, and transitional code. Ensure zero dangling references.

### 6.1 Remove `_emit` fallback in `src/remora/core/externals.py`

The `_emit` helper currently has a fallback: `if self._outbox is not None`. Now that all callers pass an outbox, remove the fallback:

```python
async def _emit(self, event: Event) -> int:
    """Emit an event through the outbox."""
    return await self._outbox.emit(event)
```

Make `outbox` a required parameter (remove `| None` and default):
```python
def __init__(
    self,
    node_id: str,
    workspace: AgentWorkspace,
    correlation_id: str | None,
    node_store: NodeStore,
    agent_store: AgentStore,
    event_store: EventStore,
    outbox: Any,  # Required, no default
) -> None:
```

### 6.2 Update `tests/unit/test_externals.py`

Every test that creates an `AgentContext` must now pass an outbox. Update the `_context` helper:

```python
from remora.core.actor import Outbox, RecordingOutbox

async def _context(
    node_id: str,
    workspace,
    node_store: NodeStore,
    agent_store: AgentStore,
    event_store: EventStore,
    correlation_id: str = "corr-1",
    outbox=None,
) -> AgentContext:
    if outbox is None:
        outbox = Outbox(actor_id=node_id, event_store=event_store, correlation_id=correlation_id)
    return AgentContext(
        node_id=node_id,
        workspace=workspace,
        correlation_id=correlation_id,
        node_store=node_store,
        agent_store=agent_store,
        event_store=event_store,
        outbox=outbox,
    )
```

This uses a real `Outbox` (write-through to EventStore) by default, so existing tests that check EventStore contents still work.

For the `test_externals_emit_uses_outbox_when_provided` test from Step 3, pass a `RecordingOutbox` explicitly.

### 6.3 Remove `Trigger` re-export from `src/remora/core/runner.py`

Remove the `Trigger` import and re-export. Update `__all__`:

```python
__all__ = ["AgentRunner"]
```

Update all files that import `Trigger` from `runner`:

In `tests/unit/test_runner.py`:
```python
# Change: from remora.core.runner import AgentRunner, Trigger
# To: from remora.core.runner import AgentRunner
# And: from remora.core.actor import Trigger
```

In `tests/integration/test_e2e.py`:
```python
# Change: from remora.core.runner import AgentRunner, Trigger
# To: from remora.core.runner import AgentRunner
# And: from remora.core.actor import Trigger
```

### 6.4 Verify no dead imports remain

Search the entire codebase for references to removed APIs:

```bash
# These should return zero results:
grep -r "get_triggers" src/ tests/
grep -r "_cooldowns" src/ tests/
grep -r "_depths" src/remora/core/runner.py
grep -r "from remora.core.runner import.*Trigger" src/ tests/
grep -r "self._queue" src/remora/core/events/dispatcher.py
```

### 6.5 Verify `AsyncIterator` import removal in `store.py`

Confirm that `AsyncIterator` is no longer imported in `src/remora/core/events/store.py` (removed in Step 4.2). If the import line was `from collections.abc import AsyncIterator`, it should be gone.

### 6.6 Verify no unused imports in modified files

Run your linter (ruff, flake8, or similar) on all modified files:

```bash
ruff check src/remora/core/runner.py src/remora/core/externals.py src/remora/core/actor.py src/remora/core/events/dispatcher.py src/remora/core/events/store.py src/remora/core/services.py
```

Fix any unused import warnings.

### 6.7 Validation

```bash
pytest  # full suite
ruff check src/ tests/  # or your project's linter
```

**Checklist:**
- [ ] `AgentContext` requires `outbox` parameter (no `None` default, no fallback).
- [ ] All test `AgentContext` constructions pass an outbox.
- [ ] `Trigger` is only imported from `remora.core.actor`, never from `remora.core.runner`.
- [ ] `runner.py` has no `__all__` entry for `Trigger`.
- [ ] No references to `get_triggers` anywhere in `src/` or `tests/`.
- [ ] No references to `_cooldowns` or `_depths` in `runner.py`.
- [ ] No `AsyncIterator` import in `store.py`.
- [ ] No `self._queue` in `dispatcher.py`.
- [ ] Linter passes with zero warnings on modified files.
- [ ] Full test suite passes.

---

## Step 7: Final Verification

**Goal:** Confirm the entire codebase is consistent, clean, and fully aligned with the actor model.

### 7.1 Architectural Consistency Check

Verify these invariants hold:

| Invariant | How to verify |
|---|---|
| No direct `event_store.append()` calls from agent code | `grep -r "event_store.append" src/remora/core/externals.py` returns nothing |
| All agent writes go through outbox | Read `externals.py` — every write method calls `self._emit()` |
| No global mutable state in runner | Read `runner.py` — no `_cooldowns`, `_depths`, or `_semaphore` used for policy (semaphore is still there for concurrency limiting, which is correct) |
| Per-agent policy state lives in actors | Read `actor.py` — `_last_trigger_ms`, `_depths` are on `AgentActor` |
| Dispatcher routes to actors, not a global queue | Read `dispatcher.py` — no `asyncio.Queue`, uses router callback |
| EventStore is unchanged | Read `store.py` — append/fan-out flow is the same, minus `get_triggers()` |
| Web server unaffected | Read `server.py` — no references to runner, actor, or outbox |
| LSP server unaffected | Read `lsp/server.py` — no references to runner, actor, or outbox |
| Reconciler unaffected | Read `reconciler.py` — no references to runner, actor, or outbox |

### 7.2 File Inventory

After the refactor, the source tree should contain:

**New files:**
- `src/remora/core/actor.py` — `Outbox`, `RecordingOutbox`, `Trigger`, `AgentActor`
- `tests/unit/test_actor.py` — Tests for outbox and actor behavior

**Modified files:**
- `src/remora/core/runner.py` — Refactored to actor registry
- `src/remora/core/externals.py` — Write methods use outbox
- `src/remora/core/events/dispatcher.py` — Routes via callback, no global queue
- `src/remora/core/events/store.py` — Removed `get_triggers()`
- `src/remora/core/services.py` — `close()` awaits actor shutdown
- `tests/unit/test_runner.py` — Tests registry/routing behavior
- `tests/unit/test_externals.py` — All contexts pass outbox
- `tests/unit/test_event_store.py` — Trigger flow test uses router callback
- `tests/integration/test_e2e.py` — Uses actor-based execution

**Unchanged files (verify no accidental modifications):**
- `src/remora/core/events/types.py`
- `src/remora/core/events/bus.py`
- `src/remora/core/events/subscriptions.py`
- `src/remora/core/events/__init__.py`
- `src/remora/core/graph.py`
- `src/remora/core/node.py`
- `src/remora/core/types.py`
- `src/remora/core/config.py`
- `src/remora/core/db.py`
- `src/remora/core/kernel.py`
- `src/remora/core/workspace.py`
- `src/remora/core/grail.py`
- `src/remora/__main__.py`
- `src/remora/web/server.py`
- `src/remora/lsp/server.py`
- `src/remora/code/reconciler.py`
- `tests/factories.py`

### 7.3 Run Full Test Suite

```bash
pytest -v --tb=short
```

Every test must pass. No skips, no xfails introduced by this refactor.

### 7.4 Smoke Test

If possible, run the system end-to-end:

```bash
cd /path/to/test-project
remora start --project-root . --run-seconds 10
```

Verify in the logs:
- Reconciler discovers nodes.
- Events are dispatched.
- Actor tasks are created (`actor-<node_id>` names in debug logs).
- No errors or tracebacks.

---

## Summary: What Changed and Why

| Before | After | Why |
|---|---|---|
| One global queue in `TriggerDispatcher` | Per-agent inbox queues via router callback | Per-agent isolation and sequential processing |
| `AgentRunner._execute_turn()` | `AgentActor._execute_turn()` | Turn execution belongs with the agent, not a central coordinator |
| `AgentRunner._cooldowns` / `_depths` (global dicts) | `AgentActor._last_trigger_ms` / `_depths` (per-actor) | Policy state belongs with the agent |
| `event_store.append()` called directly from `AgentContext` | `outbox.emit()` called from `AgentContext` | Mediated writes provide interception, tagging, and test seams |
| Fire-and-forget `asyncio.create_task()` in runner | Named managed tasks in actor registry | Lifecycle tracking, clean shutdown |
| `EventStore.get_triggers()` async generator | Dispatcher routes directly to actor inboxes | Removes unnecessary indirection |

**What was NOT changed:**
- EventStore (append-only log, fan-out to bus + dispatcher)
- EventBus (in-memory broadcast)
- SubscriptionRegistry (pattern matching)
- Event types (all existing types unchanged)
- NodeStore / AgentStore (persistence layer)
- Reconciler (file watching, node discovery)
- Web server (API endpoints)
- LSP server (editor integration)
- Workspace service (Cairn filesystem)
- Configuration model
