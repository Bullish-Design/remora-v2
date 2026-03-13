"""Tests for actor model primitives."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from structured_agents import Message
from tests.factories import make_node

from remora.core.actor import AgentActor, Outbox, RecordingOutbox, Trigger
from remora.core.config import Config
from remora.core.db import AsyncDB
from remora.core.events import (
    AgentCompleteEvent,
    AgentErrorEvent,
    AgentMessageEvent,
    AgentStartEvent,
    ContentChangedEvent,
    EventStore,
)
from remora.core.graph import AgentStore, NodeStore
from remora.core.types import NodeStatus
from remora.core.workspace import CairnWorkspaceService


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

    class MockKernel:
        async def run(self, _messages, _tools, max_turns=20):  # noqa: ANN001, ANN201
            del max_turns
            return SimpleNamespace(final_message=Message(role="assistant", content="ok"))

        async def close(self) -> None:
            return None

    monkeypatch.setattr("remora.core.actor.create_kernel", lambda **_kwargs: MockKernel())
    monkeypatch.setattr("remora.core.actor.discover_tools", lambda *_args, **_kwargs: [])

    actor = _make_actor(env, node.node_id)
    event = AgentMessageEvent(
        from_agent="user", to_agent=node.node_id, content="hello", correlation_id="corr-1"
    )

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


@pytest.mark.asyncio
async def test_read_bundle_config_expands_model_from_env_default(actor_env, monkeypatch) -> None:
    monkeypatch.delenv("REMORA_MODEL", raising=False)
    workspace = await actor_env["workspace_service"].get_agent_workspace("src/config.py::f")
    await workspace.write(
        "_bundle/bundle.yaml",
        'model: "${REMORA_MODEL:-Qwen/Qwen3-4B-Instruct-2507-FP8}"\n',
    )

    bundle_config = await AgentActor._read_bundle_config(workspace)
    assert bundle_config["model"] == "Qwen/Qwen3-4B-Instruct-2507-FP8"


@pytest.mark.asyncio
async def test_read_bundle_config_allows_env_override_for_placeholder(
    actor_env,
    monkeypatch,
) -> None:
    monkeypatch.setenv("REMORA_MODEL", "my-org/custom-model")
    workspace = await actor_env["workspace_service"].get_agent_workspace("src/config.py::g")
    await workspace.write("_bundle/bundle.yaml", 'model: "${REMORA_MODEL:-Qwen/Qwen3-4B}"\n')

    bundle_config = await AgentActor._read_bundle_config(workspace)
    assert bundle_config["model"] == "my-org/custom-model"


@pytest.mark.asyncio
async def test_read_bundle_config_literal_model_overrides_env(actor_env, monkeypatch) -> None:
    monkeypatch.setenv("REMORA_MODEL", "my-org/custom-model")
    workspace = await actor_env["workspace_service"].get_agent_workspace("src/config.py::h")
    await workspace.write("_bundle/bundle.yaml", "model: pinned/model\n")

    bundle_config = await AgentActor._read_bundle_config(workspace)
    assert bundle_config["model"] == "pinned/model"


@pytest.mark.asyncio
async def test_actor_logs_model_request_and_response(actor_env, monkeypatch, caplog) -> None:
    env = actor_env
    node = make_node("src/app.py::logged")
    await env["node_store"].upsert_node(node)
    ws = await env["workspace_service"].get_agent_workspace(node.node_id)
    await ws.write("_bundle/bundle.yaml", "system_prompt: hi\nmodel: mock\nmax_turns: 1\n")

    class MockKernel:
        async def run(self, _messages, _tools, max_turns=20):  # noqa: ANN001, ANN201
            del max_turns
            return SimpleNamespace(final_message=Message(role="assistant", content="ok"))

        async def close(self) -> None:
            return None

    monkeypatch.setattr("remora.core.actor.create_kernel", lambda **_kwargs: MockKernel())
    monkeypatch.setattr("remora.core.actor.discover_tools", lambda *_args, **_kwargs: [])

    actor = _make_actor(env, node.node_id)
    event = AgentMessageEvent(
        from_agent="user",
        to_agent=node.node_id,
        content="hello",
        correlation_id="corr-log",
    )
    outbox = Outbox(
        actor_id=node.node_id,
        event_store=env["event_store"],
        correlation_id="corr-log",
    )
    trigger = Trigger(node_id=node.node_id, correlation_id="corr-log", event=event)

    with caplog.at_level(logging.INFO, logger="remora.core.actor"):
        await actor._execute_turn(trigger, outbox)

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "Model request node=src/app.py::logged corr=corr-log" in message for message in messages
    )
    assert any(
        "Agent turn complete node=src/app.py::logged corr=corr-log response=ok" in message
        for message in messages
    )


@pytest.mark.asyncio
async def test_actor_logs_full_response_not_truncated(actor_env, monkeypatch, caplog) -> None:
    env = actor_env
    node = make_node("src/app.py::logged-long")
    await env["node_store"].upsert_node(node)
    ws = await env["workspace_service"].get_agent_workspace(node.node_id)
    await ws.write("_bundle/bundle.yaml", "system_prompt: hi\nmodel: mock\nmax_turns: 1\n")

    long_response = "r" * 1400 + "TAIL"

    class MockKernel:
        async def run(self, _messages, _tools, max_turns=20):  # noqa: ANN001, ANN201
            del max_turns
            return SimpleNamespace(final_message=Message(role="assistant", content=long_response))

        async def close(self) -> None:
            return None

    monkeypatch.setattr("remora.core.actor.create_kernel", lambda **_kwargs: MockKernel())
    monkeypatch.setattr("remora.core.actor.discover_tools", lambda *_args, **_kwargs: [])

    actor = _make_actor(env, node.node_id)
    event = AgentMessageEvent(
        from_agent="user",
        to_agent=node.node_id,
        content="hello",
        correlation_id="corr-long",
    )
    outbox = Outbox(
        actor_id=node.node_id,
        event_store=env["event_store"],
        correlation_id="corr-long",
    )
    trigger = Trigger(node_id=node.node_id, correlation_id="corr-long", event=event)

    with caplog.at_level(logging.INFO, logger="remora.core.actor"):
        await actor._execute_turn(trigger, outbox)

    messages = [record.getMessage() for record in caplog.records]
    completion = next(
        message
        for message in messages
        if "Agent turn complete node=src/app.py::logged-long corr=corr-long response=" in message
    )
    assert "TAIL" in completion
    assert "..." not in completion


@pytest.mark.asyncio
async def test_actor_execute_turn_emits_error_event_on_kernel_failure(actor_env, monkeypatch) -> None:
    env = actor_env
    node = make_node("src/app.py::kernel-fail")
    await env["node_store"].upsert_node(node)
    ws = await env["workspace_service"].get_agent_workspace(node.node_id)
    await ws.write("_bundle/bundle.yaml", "system_prompt: hi\nmodel: mock\nmax_turns: 1\n")

    def fail_create_kernel(**_kwargs):  # noqa: ANN003, ANN202
        raise ConnectionError("connection refused")

    monkeypatch.setattr("remora.core.actor.create_kernel", fail_create_kernel)
    monkeypatch.setattr("remora.core.actor.discover_tools", lambda *_args, **_kwargs: [])

    actor = _make_actor(env, node.node_id)
    event = AgentMessageEvent(
        from_agent="user",
        to_agent=node.node_id,
        content="hello",
        correlation_id="corr-fail",
    )
    outbox = Outbox(
        actor_id=node.node_id,
        event_store=env["event_store"],
        correlation_id="corr-fail",
    )
    trigger = Trigger(node_id=node.node_id, correlation_id="corr-fail", event=event)
    await actor._execute_turn(trigger, outbox)

    events = await env["event_store"].get_events(limit=10)
    event_types = [event["event_type"] for event in events]
    assert AgentStartEvent.__name__ in event_types
    assert AgentErrorEvent.__name__ in event_types
    assert AgentCompleteEvent.__name__ not in event_types

    error_event = next(event for event in events if event["event_type"] == AgentErrorEvent.__name__)
    assert "connection refused" in error_event["payload"]["error"]

    updated_node = await env["node_store"].get_node(node.node_id)
    updated_agent = await env["agent_store"].get_agent(node.node_id)
    assert updated_node is not None
    assert updated_agent is not None
    assert updated_node.status == NodeStatus.ERROR
    assert updated_agent.status == NodeStatus.ERROR


@pytest.mark.asyncio
async def test_actor_execute_turn_respects_shared_semaphore(actor_env, monkeypatch) -> None:
    env = actor_env
    node_a = make_node("src/app.py::sem-a")
    node_b = make_node("src/app.py::sem-b")
    await env["node_store"].upsert_node(node_a)
    await env["node_store"].upsert_node(node_b)

    ws_a = await env["workspace_service"].get_agent_workspace(node_a.node_id)
    ws_b = await env["workspace_service"].get_agent_workspace(node_b.node_id)
    await ws_a.write("_bundle/bundle.yaml", "system_prompt: hi\nmodel: mock\nmax_turns: 1\n")
    await ws_b.write("_bundle/bundle.yaml", "system_prompt: hi\nmodel: mock\nmax_turns: 1\n")

    gate = asyncio.Event()
    first_run_started = asyncio.Event()
    in_flight = 0
    max_in_flight = 0
    counter_lock = asyncio.Lock()

    class BlockingKernel:
        async def run(self, _messages, _tools, max_turns=20):  # noqa: ANN001, ANN201
            del max_turns
            nonlocal in_flight, max_in_flight
            async with counter_lock:
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
            first_run_started.set()
            await gate.wait()
            async with counter_lock:
                in_flight -= 1
            return SimpleNamespace(final_message=Message(role="assistant", content="ok"))

        async def close(self) -> None:
            return None

    monkeypatch.setattr("remora.core.actor.create_kernel", lambda **_kwargs: BlockingKernel())
    monkeypatch.setattr("remora.core.actor.discover_tools", lambda *_args, **_kwargs: [])

    shared_semaphore = asyncio.Semaphore(1)
    actor_a = AgentActor(
        node_id=node_a.node_id,
        event_store=env["event_store"],
        node_store=env["node_store"],
        agent_store=env["agent_store"],
        workspace_service=env["workspace_service"],
        config=env["config"],
        semaphore=shared_semaphore,
    )
    actor_b = AgentActor(
        node_id=node_b.node_id,
        event_store=env["event_store"],
        node_store=env["node_store"],
        agent_store=env["agent_store"],
        workspace_service=env["workspace_service"],
        config=env["config"],
        semaphore=shared_semaphore,
    )

    outbox_a = Outbox(actor_id=node_a.node_id, event_store=env["event_store"], correlation_id="corr-sem-a")
    outbox_b = Outbox(actor_id=node_b.node_id, event_store=env["event_store"], correlation_id="corr-sem-b")
    trigger_a = Trigger(
        node_id=node_a.node_id,
        correlation_id="corr-sem-a",
        event=AgentMessageEvent(from_agent="user", to_agent=node_a.node_id, content="go"),
    )
    trigger_b = Trigger(
        node_id=node_b.node_id,
        correlation_id="corr-sem-b",
        event=AgentMessageEvent(from_agent="user", to_agent=node_b.node_id, content="go"),
    )

    task_a = asyncio.create_task(actor_a._execute_turn(trigger_a, outbox_a))
    await asyncio.wait_for(first_run_started.wait(), timeout=1.0)
    task_b = asyncio.create_task(actor_b._execute_turn(trigger_b, outbox_b))
    await asyncio.sleep(0.05)
    assert not task_b.done()

    gate.set()
    await asyncio.gather(task_a, task_b)
    assert max_in_flight == 1


@pytest.mark.asyncio
async def test_actor_chat_mode_injects_prompt(actor_env, monkeypatch) -> None:
    env = actor_env
    node = make_node("src/app.py::mode-chat")
    await env["node_store"].upsert_node(node)
    ws = await env["workspace_service"].get_agent_workspace(node.node_id)
    await ws.write(
        "_bundle/bundle.yaml",
        (
            "system_prompt: base\n"
            "model: mock\n"
            "max_turns: 1\n"
            "prompts:\n"
            "  chat: CHAT_MODE\n"
            "  reactive: REACTIVE_MODE\n"
        ),
    )

    captured_system_prompt = ""

    class CapturingKernel:
        async def run(self, messages, _tools, max_turns=20):  # noqa: ANN001, ANN201
            nonlocal captured_system_prompt
            del max_turns
            captured_system_prompt = messages[0].content or ""
            return SimpleNamespace(final_message=Message(role="assistant", content="ok"))

        async def close(self) -> None:
            return None

    monkeypatch.setattr("remora.core.actor.create_kernel", lambda **_kwargs: CapturingKernel())
    monkeypatch.setattr("remora.core.actor.discover_tools", lambda *_args, **_kwargs: [])

    actor = _make_actor(env, node.node_id)
    event = AgentMessageEvent(
        from_agent="user",
        to_agent=node.node_id,
        content="hello",
        correlation_id="corr-mode-chat",
    )
    outbox = Outbox(
        actor_id=node.node_id,
        event_store=env["event_store"],
        correlation_id="corr-mode-chat",
    )
    trigger = Trigger(node_id=node.node_id, correlation_id="corr-mode-chat", event=event)
    await actor._execute_turn(trigger, outbox)

    assert "CHAT_MODE" in captured_system_prompt
    assert "REACTIVE_MODE" not in captured_system_prompt


@pytest.mark.asyncio
async def test_actor_reactive_mode_injects_prompt(actor_env, monkeypatch) -> None:
    env = actor_env
    node = make_node("src/app.py::mode-reactive")
    await env["node_store"].upsert_node(node)
    ws = await env["workspace_service"].get_agent_workspace(node.node_id)
    await ws.write(
        "_bundle/bundle.yaml",
        (
            "system_prompt: base\n"
            "model: mock\n"
            "max_turns: 1\n"
            "prompts:\n"
            "  chat: CHAT_MODE\n"
            "  reactive: REACTIVE_MODE\n"
        ),
    )

    captured_system_prompt = ""

    class CapturingKernel:
        async def run(self, messages, _tools, max_turns=20):  # noqa: ANN001, ANN201
            nonlocal captured_system_prompt
            del max_turns
            captured_system_prompt = messages[0].content or ""
            return SimpleNamespace(final_message=Message(role="assistant", content="ok"))

        async def close(self) -> None:
            return None

    monkeypatch.setattr("remora.core.actor.create_kernel", lambda **_kwargs: CapturingKernel())
    monkeypatch.setattr("remora.core.actor.discover_tools", lambda *_args, **_kwargs: [])

    actor = _make_actor(env, node.node_id)
    event = ContentChangedEvent(path=node.file_path, change_type="modified")
    outbox = Outbox(
        actor_id=node.node_id,
        event_store=env["event_store"],
        correlation_id="corr-mode-reactive",
    )
    trigger = Trigger(
        node_id=node.node_id,
        correlation_id="corr-mode-reactive",
        event=event,
    )
    await actor._execute_turn(trigger, outbox)

    assert "REACTIVE_MODE" in captured_system_prompt
    assert "CHAT_MODE" not in captured_system_prompt
