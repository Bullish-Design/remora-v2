"""Tests for actor model primitives."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import pytest_asyncio

from remora.core.actor import AgentActor, Outbox, RecordingOutbox, Trigger
from remora.core.config import Config
from remora.core.db import AsyncDB
from remora.core.events import AgentCompleteEvent, AgentStartEvent, EventStore, HumanChatEvent
from remora.core.graph import AgentStore, NodeStore
from remora.core.workspace import CairnWorkspaceService
from tests.factories import make_node


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
    assert all(event.correlation_id == "corr-1" for event in outbox.events)
    assert outbox.sequence == 2


@pytest.mark.asyncio
async def test_recording_outbox_no_persistence() -> None:
    outbox = RecordingOutbox()
    event_id = await outbox.emit(AgentStartEvent(agent_id="x"))
    assert event_id == 1
    assert len(outbox.events) == 1


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
    assert actor._should_trigger("c1")
    assert not actor._should_trigger("c1")


@pytest.mark.asyncio
async def test_actor_depth_limit(actor_env) -> None:
    actor = _make_actor(actor_env)
    assert actor._should_trigger("c1")
    actor._last_trigger_ms = 0.0
    assert actor._should_trigger("c1")
    actor._last_trigger_ms = 0.0
    assert not actor._should_trigger("c1")


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
        async def run(self, _messages, _tools, max_turns=20):  # noqa: ANN001, ANN201
            del max_turns
            return SimpleNamespace(final_message=Message(role="assistant", content="ok"))

        async def close(self) -> None:
            return None

    monkeypatch.setattr("remora.core.actor.create_kernel", lambda **_kwargs: MockKernel())
    monkeypatch.setattr("remora.core.actor.discover_tools", lambda *_args, **_kwargs: [])

    actor = _make_actor(env, node.node_id)
    event = HumanChatEvent(to_agent=node.node_id, message="hello", correlation_id="corr-1")

    outbox = Outbox(actor_id=node.node_id, event_store=env["event_store"], correlation_id="corr-1")
    trigger = Trigger(node_id=node.node_id, correlation_id="corr-1", event=event)
    await actor._execute_turn(trigger, outbox)

    events = await env["event_store"].get_events(limit=10)
    event_types = [event["event_type"] for event in events]
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
    assert not any(event["event_type"] == "AgentStartEvent" for event in events)
