from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from tests.factories import make_node

from remora.core.actor import Actor
from remora.core.config import Config
from remora.core.db import open_database
from remora.core.events import (
    AgentMessageEvent,
    EventStore,
    SubscriptionPattern,
)
from remora.core.graph import NodeStore
from remora.core.runner import ActorPool
from remora.core.workspace import CairnWorkspaceService


@pytest_asyncio.fixture
async def runner_env(tmp_path: Path):
    db = await open_database(tmp_path / "runner.db")
    node_store = NodeStore(db)
    await node_store.create_tables()
    event_store = EventStore(db=db)
    await event_store.create_tables()
    config = Config(workspace_root=".remora-runner-test", trigger_cooldown_ms=1000, max_trigger_depth=2)
    workspace_service = CairnWorkspaceService(config, tmp_path)
    await workspace_service.initialize()
    runner = ActorPool(event_store, node_store, workspace_service, config)

    yield runner, node_store, event_store, workspace_service

    await runner.stop_and_wait()
    await workspace_service.close()
    await db.close()


@pytest.mark.asyncio
async def test_runner_creates_actor_on_route(runner_env) -> None:
    runner, _ns, _es, _ws = runner_env
    assert len(runner.actors) == 0
    actor = runner.get_or_create_actor("agent-a")
    assert isinstance(actor, Actor)
    assert actor.is_running
    assert "agent-a" in runner.actors


@pytest.mark.asyncio
async def test_runner_reuses_existing_actor(runner_env) -> None:
    runner, _ns, _es, _ws = runner_env
    actor1 = runner.get_or_create_actor("agent-a")
    actor2 = runner.get_or_create_actor("agent-a")
    assert actor1 is actor2


@pytest.mark.asyncio
async def test_runner_routes_dispatch_to_actor_inbox(runner_env) -> None:
    runner, _ns, event_store, _ws = runner_env
    actor = runner.get_or_create_actor("agent-x")
    await actor.stop()
    await event_store.subscriptions.register("agent-x", SubscriptionPattern(to_agent="x"))

    event = AgentMessageEvent(from_agent="a", to_agent="x", content="hello")
    await event_store.append(event)

    assert "agent-x" in runner.actors
    assert actor.inbox.qsize() >= 1


@pytest.mark.asyncio
async def test_runner_evicts_idle_actors(runner_env) -> None:
    runner, _ns, _es, _ws = runner_env
    actor = runner.get_or_create_actor("idle-agent")
    actor._last_active = 0.0
    await runner._evict_idle(max_idle_seconds=1.0)
    assert "idle-agent" not in runner.actors
    assert not actor.is_running


@pytest.mark.asyncio
async def test_runner_does_not_evict_busy_actors(runner_env) -> None:
    runner, _ns, _es, _ws = runner_env
    actor = runner.get_or_create_actor("busy-agent")
    actor._last_active = 0.0
    await actor.inbox.put(AgentMessageEvent(from_agent="a", to_agent="b", content="x"))
    await runner._evict_idle(max_idle_seconds=1.0)
    assert "busy-agent" in runner.actors


@pytest.mark.asyncio
async def test_runner_stop_and_wait(runner_env) -> None:
    runner, _ns, _es, _ws = runner_env
    runner.get_or_create_actor("a")
    runner.get_or_create_actor("b")
    assert len(runner.actors) == 2
    await runner.stop_and_wait()
    assert len(runner.actors) == 0


@pytest.mark.asyncio
async def test_runner_build_prompt_via_actor(runner_env) -> None:
    runner, node_store, _event_store, workspace_service = runner_env
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
            event=AgentMessageEvent(from_agent="user", to_agent=node.node_id, content="hello"),
        ),
    )
    assert node.full_name in prompt
    assert "hello" in prompt
    assert "Type: function | File: src/app.py" in prompt


@pytest.mark.asyncio
async def test_runner_build_prompt_for_virtual_node(runner_env) -> None:
    runner, node_store, _event_store, workspace_service = runner_env
    node = make_node(
        "test-agent",
        node_type="virtual",
        file_path="",
        source_code="",
        role="test-agent",
        name="test-agent",
        full_name="test-agent",
        start_line=0,
        end_line=0,
    )
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
            event=AgentMessageEvent(from_agent="user", to_agent=node.node_id, content="hello"),
        ),
    )
    assert "Type: virtual | File: " in prompt
    assert "## Role" in prompt
    assert "test-agent agent" in prompt
