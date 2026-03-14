from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from structured_agents import Message
from structured_agents.types import ToolCall, ToolResult, ToolSchema
from tests.factories import write_file

from remora.code.reconciler import FileReconciler
from remora.core.actor import Outbox, Trigger
from remora.core.config import Config
from remora.core.db import AsyncDB
from remora.core.events import (
    AgentMessageEvent,
    ContentChangedEvent,
    EventBus,
    EventStore,
)
from remora.core.graph import AgentStore, NodeStore
from remora.core.runner import ActorPool
from remora.core.workspace import CairnWorkspaceService


def _write_bundles(root: Path) -> None:
    system = root / "system"
    code = root / "code-agent"
    (system / "tools").mkdir(parents=True, exist_ok=True)
    (code / "tools").mkdir(parents=True, exist_ok=True)

    write_file(
        system / "bundle.yaml",
        "name: system\nsystem_prompt: hi\nmodel: mock\nmax_turns: 2\n",
    )
    write_file(
        code / "bundle.yaml",
        "name: code-agent\nsystem_prompt: hi\nmodel: mock\nmax_turns: 2\n",
    )
    write_file(
        system / "tools" / "send_message.pym",
        "from grail import Input, external\n"
        "to_node_id: str = Input('to_node_id')\n"
        "content: str = Input('content')\n"
        "@external\nasync def send_message(to_node_id: str, content: str) -> bool: ...\n"
        "result = await send_message(to_node_id, content)\n"
        "if result:\n"
        "    message = f'Message sent to {to_node_id}'\n"
        "else:\n"
        "    message = f'Failed to send message to {to_node_id}'\n"
        "message\n",
    )
    write_file(
        code / "tools" / "rewrite_self.pym",
        "from grail import Input, external\n"
        "new_source: str = Input('new_source')\n"
        "@external\nasync def apply_rewrite(new_source: str) -> bool: ...\n"
        "applied = await apply_rewrite(new_source)\n"
        "str(applied)\n",
    )


async def _setup_runtime(tmp_path: Path):
    source_path = tmp_path / "src" / "app.py"
    write_file(
        source_path,
        "def alpha():\n    return 1\n\n"
        "def beta():\n    return 2\n",
    )

    bundles_root = tmp_path / "bundles"
    _write_bundles(bundles_root)

    db = AsyncDB.from_path(tmp_path / "e2e.db")
    event_bus = EventBus()
    node_store = NodeStore(db)
    agent_store = AgentStore(db)
    await node_store.create_tables()
    await agent_store.create_tables()
    event_store = EventStore(db=db, event_bus=event_bus)
    await event_store.create_tables()

    config = Config(
        discovery_paths=("src",),
        discovery_languages=("python",),
        workspace_root=".remora-e2e",
        bundle_root=str(bundles_root),
        model_default="mock",
    )
    workspace_service = CairnWorkspaceService(config, tmp_path)
    await workspace_service.initialize()
    reconciler = FileReconciler(
        config,
        node_store,
        agent_store,
        event_store,
        workspace_service,
        project_root=tmp_path,
    )
    code_nodes = await reconciler.full_scan()
    runner = ActorPool(event_store, node_store, agent_store, workspace_service, config)

    return {
        "source_path": source_path,
        "db": db,
        "event_bus": event_bus,
        "node_store": node_store,
        "agent_store": agent_store,
        "event_store": event_store,
        "workspace_service": workspace_service,
        "runner": runner,
        "reconciler": reconciler,
        "nodes": code_nodes,
        "config": config,
    }


@pytest.mark.asyncio
async def test_e2e_human_chat_to_rewrite(tmp_path: Path, monkeypatch) -> None:
    runtime = await _setup_runtime(tmp_path)
    node = next(node for node in runtime["nodes"] if node.node_type != "directory")

    workspace = await runtime["workspace_service"].get_agent_workspace(node.node_id)
    assert await workspace.exists("_bundle/bundle.yaml")
    assert await workspace.exists("_bundle/tools/rewrite_self.pym")

    trigger_event = AgentMessageEvent(from_agent="user", to_agent=node.node_id, content="please rewrite")
    await runtime["event_store"].append(trigger_event)

    class MockKernel:
        def __init__(self, tools):
            self._tools = tools

        async def run(self, messages, tool_schemas, max_turns=8):  # noqa: ANN001, ANN201
            del messages, tool_schemas, max_turns
            rewrite_tool = None
            for tool in self._tools:
                if tool.schema.name == "rewrite_self":
                    rewrite_tool = tool
                    break
            if rewrite_tool is not None:
                await rewrite_tool.execute(
                    {"new_source": "def alpha():\n    return 42\n"},
                    SimpleNamespace(id="call-1"),
                )
            return SimpleNamespace(final_message=Message(role="assistant", content="rewritten"))

        async def close(self) -> None:
            return None

    monkeypatch.setattr(
        "remora.core.actor.create_kernel",
        lambda **kwargs: MockKernel(kwargs.get("tools", [])),
    )
    class FakeRewriteTool:
        def __init__(self, capabilities):
            self._capabilities = capabilities

        @property
        def schema(self) -> ToolSchema:
            return ToolSchema(
                name="rewrite_self",
                description="Apply rewrite",
                parameters={
                    "type": "object",
                    "properties": {"new_source": {"type": "string"}},
                    "required": ["new_source"],
                },
            )

        async def execute(self, arguments, context):  # noqa: ANN001, ANN201
            applied = await self._capabilities["apply_rewrite"](arguments["new_source"])
            return ToolResult(
                call_id=getattr(context, "id", ""),
                name="rewrite_self",
                output=str(applied),
                is_error=False,
            )

    async def fake_discover_tools(_workspace, capabilities):  # noqa: ANN001, ANN202
        return [FakeRewriteTool(capabilities)]

    monkeypatch.setattr("remora.core.actor.discover_tools", fake_discover_tools)
    actor = runtime["runner"].get_or_create_actor(node.node_id)
    outbox = Outbox(
        actor_id=node.node_id,
        event_store=runtime["event_store"],
        correlation_id="corr-e2e",
    )
    await actor._execute_turn(
        Trigger(
            node_id=node.node_id,
            correlation_id="corr-e2e",
            event=trigger_event,
        ),
        outbox,
    )

    updated_source = runtime["source_path"].read_text(encoding="utf-8")
    assert "def alpha():\n    return 42\n" in updated_source
    assert "def beta():\n    return 2\n" in updated_source

    events_after = await runtime["event_store"].get_events(limit=50)
    assert any(event["event_type"] == "ContentChangedEvent" for event in events_after)

    await runtime["runner"].stop_and_wait()
    await runtime["workspace_service"].close()
    runtime["db"].close()


@pytest.mark.asyncio
async def test_e2e_agent_message_chain(tmp_path: Path) -> None:
    runtime = await _setup_runtime(tmp_path)
    nodes = [node for node in runtime["nodes"] if node.node_type != "directory"]
    source = nodes[0].node_id
    target = nodes[1].node_id

    actor = runtime["runner"].get_or_create_actor(target)
    await actor.stop()
    await runtime["event_store"].append(
        AgentMessageEvent(from_agent=source, to_agent=target, content="hello")
    )
    assert target in runtime["runner"].actors
    assert actor.inbox.qsize() >= 1

    await runtime["runner"].stop_and_wait()
    await runtime["workspace_service"].close()
    runtime["db"].close()


@pytest.mark.asyncio
async def test_e2e_file_change_triggers(tmp_path: Path) -> None:
    runtime = await _setup_runtime(tmp_path)
    node = next(node for node in runtime["nodes"] if node.node_type != "directory")

    actor = runtime["runner"].get_or_create_actor(node.node_id)
    await actor.stop()
    await runtime["event_store"].append(
        ContentChangedEvent(path=node.file_path, change_type="modified")
    )
    assert node.node_id in runtime["runner"].actors
    assert actor.inbox.qsize() >= 1

    await runtime["runner"].stop_and_wait()
    await runtime["workspace_service"].close()
    runtime["db"].close()


@pytest.mark.asyncio
async def test_e2e_two_agents_interact_via_send_message_tool(tmp_path: Path, monkeypatch) -> None:
    runtime = await _setup_runtime(tmp_path)
    node_by_name = {node.name: node for node in runtime["nodes"] if node.node_type != "directory"}
    alpha = node_by_name["alpha"]
    beta = node_by_name["beta"]

    class ScriptedKernel:
        def __init__(self, tools):
            self._tools = {tool.schema.name: tool for tool in tools}

        async def run(self, messages, tool_schemas, max_turns=8):  # noqa: ANN001, ANN201
            del tool_schemas, max_turns
            prompt = messages[1].content or ""
            if "# Node: alpha" in prompt and "Event: AgentMessageEvent" in prompt:
                await self._tools["send_message"].execute(
                    {"to_node_id": beta.node_id, "content": "ping"},
                    ToolCall(id="call-alpha-ping", name="send_message", arguments={}),
                )
                return SimpleNamespace(
                    final_message=Message(role="assistant", content="alpha sent ping")
                )
            if "# Node: beta" in prompt and "Content: ping" in prompt:
                await self._tools["send_message"].execute(
                    {"to_node_id": alpha.node_id, "content": "pong"},
                    ToolCall(id="call-beta-pong", name="send_message", arguments={}),
                )
                return SimpleNamespace(final_message=Message(role="assistant", content="beta sent pong"))
            return SimpleNamespace(final_message=Message(role="assistant", content="no-op"))

        async def close(self) -> None:
            return None

    monkeypatch.setattr(
        "remora.core.actor.create_kernel",
        lambda **kwargs: ScriptedKernel(kwargs.get("tools", [])),
    )

    async def wait_for_exchange(timeout_s: float = 2.0):  # noqa: ANN202
        deadline = asyncio.get_running_loop().time() + timeout_s
        while asyncio.get_running_loop().time() < deadline:
            events = await runtime["event_store"].get_events(limit=100)
            message_events = [event for event in events if event["event_type"] == "AgentMessageEvent"]
            ping_seen = any(
                event["payload"].get("from_agent") == alpha.node_id
                and event["payload"].get("to_agent") == beta.node_id
                and event["payload"].get("content") == "ping"
                for event in message_events
            )
            pong_seen = any(
                event["payload"].get("from_agent") == beta.node_id
                and event["payload"].get("to_agent") == alpha.node_id
                and event["payload"].get("content") == "pong"
                for event in message_events
            )
            if ping_seen and pong_seen:
                return events
            await asyncio.sleep(0.02)
        pytest.fail("Timed out waiting for alpha/beta message exchange")

    await runtime["event_store"].append(
        AgentMessageEvent(
            from_agent="user",
            to_agent=alpha.node_id,
            content="start handshake with beta",
            correlation_id="corr-agent-interaction",
        )
    )
    events_after = await wait_for_exchange()
    event_types = [event["event_type"] for event in events_after]
    assert "AgentErrorEvent" not in event_types
    assert "AgentCompleteEvent" in event_types

    complete_agents = {
        event["payload"]["agent_id"]
        for event in events_after
        if event["event_type"] == "AgentCompleteEvent"
    }
    assert alpha.node_id in complete_agents
    assert beta.node_id in complete_agents

    await runtime["runner"].stop_and_wait()
    await runtime["workspace_service"].close()
    runtime["db"].close()
