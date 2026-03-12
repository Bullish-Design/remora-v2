from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from structured_agents import Message
from structured_agents.types import ToolResult

from remora.core.config import Config
from remora.core.db import AsyncDB
from remora.core.events import AgentMessageEvent, EventStore, HumanChatEvent
from remora.core.graph import AgentStore, NodeStore
from remora.core.runner import AgentRunner, Trigger
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
    config = Config(swarm_root=".remora-phase4", trigger_cooldown_ms=1000, max_trigger_depth=2)
    workspace_service = CairnWorkspaceService(config, tmp_path)
    await workspace_service.initialize()
    runner = AgentRunner(event_store, node_store, agent_store, workspace_service, config)

    yield runner, node_store, agent_store, event_store, workspace_service

    await workspace_service.close()
    db.close()


@pytest.mark.asyncio
async def test_runner_cooldown(runner_env, monkeypatch) -> None:
    runner, _node_store, _agent_store, _event_store, _workspace_service = runner_env
    called: list[str] = []

    async def fake_execute(trigger: Trigger) -> None:
        called.append(trigger.node_id)

    monkeypatch.setattr(runner, "_execute_turn", fake_execute)
    await runner.trigger("a", "c1", None)
    await runner.trigger("a", "c1", None)
    await asyncio.sleep(0.05)
    assert called == ["a"]


@pytest.mark.asyncio
async def test_runner_depth_limit(runner_env) -> None:
    runner, _node_store, _agent_store, event_store, _workspace_service = runner_env
    runner._depths["a:c1"] = runner._config.max_trigger_depth
    await runner.trigger("a", "c1", None)
    events = await event_store.get_events(limit=5)
    errors = [event for event in events if event["event_type"] == "AgentErrorEvent"]
    assert errors and errors[0]["payload"]["error"] == "Cascade depth limit exceeded"


@pytest.mark.asyncio
async def test_runner_trigger_executes(runner_env, monkeypatch) -> None:
    runner, _node_store, _agent_store, _event_store, _workspace_service = runner_env
    done = asyncio.Event()

    async def fake_execute(trigger: Trigger) -> None:
        del trigger
        done.set()

    monkeypatch.setattr(runner, "_execute_turn", fake_execute)
    await runner.trigger("a", "c1", None)
    await asyncio.wait_for(done.wait(), timeout=1.0)
    assert done.is_set()


@pytest.mark.asyncio
async def test_runner_missing_node(runner_env) -> None:
    runner, _node_store, _agent_store, event_store, _workspace_service = runner_env
    await runner._execute_turn(Trigger(node_id="missing", correlation_id="c1"))
    events = await event_store.get_events(limit=5)
    assert not any(event["event_type"] == "AgentStartEvent" for event in events)


@pytest.mark.asyncio
async def test_runner_status_lifecycle(runner_env, monkeypatch) -> None:
    runner, node_store, _agent_store, _event_store, workspace_service = runner_env
    node = make_node("src/app.py::a")
    await node_store.upsert_node(node)
    ws = await workspace_service.get_agent_workspace(node.node_id)
    await ws.write("_bundle/bundle.yaml", "system_prompt: hi\nmodel: mock\nmax_turns: 1\n")

    class MockKernel:
        async def run(self, _messages, _tools, max_turns=20):  # noqa: ANN001, ANN201
            del max_turns
            return SimpleNamespace(final_message=Message(role="assistant", content="ok"))

        async def close(self) -> None:
            return None

    monkeypatch.setattr("remora.core.runner.create_kernel", lambda **_kwargs: MockKernel())
    monkeypatch.setattr("remora.core.runner.discover_tools", lambda *_args, **_kwargs: [])
    await runner._execute_turn(Trigger(node_id=node.node_id, correlation_id="c1"))

    updated = await node_store.get_node(node.node_id)
    assert updated is not None
    assert updated.status == "idle"


@pytest.mark.asyncio
async def test_runner_only_resets_running_to_idle(runner_env, monkeypatch) -> None:
    runner, node_store, _agent_store, _event_store, workspace_service = runner_env
    node = make_node("src/app.py::a")
    await node_store.upsert_node(node)
    ws = await workspace_service.get_agent_workspace(node.node_id)
    await ws.write("_bundle/bundle.yaml", "system_prompt: hi\nmodel: mock\nmax_turns: 1\n")

    class MockKernel:
        async def run(self, _messages, _tools, max_turns=20):  # noqa: ANN001, ANN201
            del max_turns
            return SimpleNamespace(final_message=Message(role="assistant", content="done"))

        async def close(self) -> None:
            return None

    monkeypatch.setattr("remora.core.runner.create_kernel", lambda **_kwargs: MockKernel())
    monkeypatch.setattr("remora.core.runner.discover_tools", lambda *_args, **_kwargs: [])
    await runner._execute_turn(Trigger(node_id=node.node_id, correlation_id="c1"))

    updated = await node_store.get_node(node.node_id)
    assert updated is not None
    assert updated.status == "idle"


@pytest.mark.asyncio
async def test_runner_build_prompt(runner_env) -> None:
    runner, node_store, _agent_store, _event_store, _workspace_service = runner_env
    node = make_node("src/app.py::a")
    await node_store.upsert_node(node)
    prompt = runner._build_prompt(
        node,
        Trigger(
            node_id=node.node_id,
            correlation_id="c1",
            event=HumanChatEvent(to_agent=node.node_id, message="hello"),
        ),
    )
    assert node.full_name in prompt
    assert node.source_code.strip() in prompt
    assert "hello" in prompt


@pytest.mark.asyncio
async def test_full_turn_with_mock_kernel(runner_env, monkeypatch) -> None:
    runner, node_store, _agent_store, event_store, workspace_service = runner_env
    node = make_node("src/app.py::a")
    await node_store.upsert_node(node)
    ws = await workspace_service.get_agent_workspace(node.node_id)
    await ws.write("_bundle/bundle.yaml", "system_prompt: hi\nmodel: mock\nmax_turns: 1\n")

    class MockKernel:
        async def run(self, _messages, _tools, max_turns=20):  # noqa: ANN001, ANN201
            del max_turns
            return SimpleNamespace(final_message=Message(role="assistant", content="done"))

        async def close(self) -> None:
            return None

    monkeypatch.setattr("remora.core.runner.create_kernel", lambda **_kwargs: MockKernel())
    monkeypatch.setattr("remora.core.runner.discover_tools", lambda *_args, **_kwargs: [])
    await runner._execute_turn(
        Trigger(
            node_id=node.node_id,
            correlation_id="corr-1",
            event=AgentMessageEvent(from_agent="x", to_agent=node.node_id, content="hello"),
        )
    )
    events = await event_store.get_events_for_agent(node.node_id, limit=10)
    event_types = [event["event_type"] for event in events]
    assert "AgentStartEvent" in event_types
    assert "AgentCompleteEvent" in event_types


@pytest.mark.asyncio
async def test_turn_emits_start_and_complete(runner_env, monkeypatch) -> None:
    runner, node_store, _agent_store, event_store, workspace_service = runner_env
    node = make_node("src/app.py::a")
    await node_store.upsert_node(node)
    ws = await workspace_service.get_agent_workspace(node.node_id)
    await ws.write("_bundle/bundle.yaml", "system_prompt: hi\nmodel: mock\nmax_turns: 1\n")

    class MockKernel:
        async def run(self, _messages, _tools, max_turns=20):  # noqa: ANN001, ANN201
            del max_turns
            return SimpleNamespace(final_message=Message(role="assistant", content="ok"))

        async def close(self) -> None:
            return None

    monkeypatch.setattr("remora.core.runner.create_kernel", lambda **_kwargs: MockKernel())
    monkeypatch.setattr("remora.core.runner.discover_tools", lambda *_args, **_kwargs: [])
    await runner._execute_turn(Trigger(node_id=node.node_id, correlation_id="c1"))
    events = await event_store.get_events(limit=10)
    assert any(event["event_type"] == "AgentStartEvent" for event in events)
    assert any(event["event_type"] == "AgentCompleteEvent" for event in events)


@pytest.mark.asyncio
async def test_turn_with_tool_call(runner_env, monkeypatch) -> None:
    runner, node_store, _agent_store, event_store, workspace_service = runner_env
    node = make_node("src/app.py::a")
    await node_store.upsert_node(node)
    ws = await workspace_service.get_agent_workspace(node.node_id)
    await ws.write("_bundle/bundle.yaml", "system_prompt: hi\nmodel: mock\nmax_turns: 1\n")

    class FakeTool:
        @property
        def schema(self):  # noqa: ANN201
            from structured_agents.types import ToolSchema

            return ToolSchema(
                name="fake_tool",
                description="fake",
                parameters={"type": "object", "properties": {}},
            )

        async def execute(self, _arguments, _context) -> ToolResult:  # noqa: ANN001, ANN201
            return ToolResult(call_id="x", name="fake_tool", output="ran", is_error=False)

    class MockKernel:
        async def run(self, _messages, _tools, max_turns=20):  # noqa: ANN001, ANN201
            del max_turns
            return SimpleNamespace(final_message=Message(role="assistant", content="tool-ran"))

        async def close(self) -> None:
            return None

    async def fake_discover_tools(*_args, **_kwargs):  # noqa: ANN001, ANN202
        return [FakeTool()]

    monkeypatch.setattr("remora.core.runner.create_kernel", lambda **_kwargs: MockKernel())
    monkeypatch.setattr("remora.core.runner.discover_tools", fake_discover_tools)
    await runner._execute_turn(Trigger(node_id=node.node_id, correlation_id="c1"))
    events = await event_store.get_events(limit=10)
    assert any(event["event_type"] == "AgentCompleteEvent" for event in events)
