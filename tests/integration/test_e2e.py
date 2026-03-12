from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from structured_agents import Message
from structured_agents.types import ToolResult, ToolSchema

from remora.code.reconciler import FileReconciler
from remora.core.config import Config
from remora.core.events import (
    AgentMessageEvent,
    ContentChangedEvent,
    EventBus,
    EventStore,
    HumanChatEvent,
)
from remora.core.graph import NodeStore
from remora.core.runner import AgentRunner, Trigger
from remora.core.workspace import CairnWorkspaceService
from remora.web.server import create_app


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_bundles(root: Path) -> None:
    system = root / "system"
    code = root / "code-agent"
    (system / "tools").mkdir(parents=True, exist_ok=True)
    (code / "tools").mkdir(parents=True, exist_ok=True)

    _write(system / "bundle.yaml", "name: system\nsystem_prompt: hi\nmodel: mock\nmax_turns: 2\n")
    _write(code / "bundle.yaml", "name: code-agent\nsystem_prompt: hi\nmodel: mock\nmax_turns: 2\n")
    _write(
        system / "tools" / "send_message.pym",
        "from grail import Input, external\n"
        "to_node_id: str = Input('to_node_id')\n"
        "content: str = Input('content')\n"
        "@external\nasync def send_message(to_node_id: str, content: str) -> bool: ...\n"
        "result = await send_message(to_node_id, content)\nreturn str(result)\n",
    )
    _write(
        code / "tools" / "rewrite_self.pym",
        "from grail import Input, external\n"
        "new_source: str = Input('new_source')\n"
        "@external\nasync def propose_rewrite(new_source: str) -> str: ...\n"
        "proposal_id = await propose_rewrite(new_source)\n"
        "return proposal_id\n",
    )


async def _setup_runtime(tmp_path: Path):
    source_path = tmp_path / "src" / "app.py"
    _write(
        source_path,
        "def alpha():\n    return 1\n\n"
        "def beta():\n    return 2\n",
    )

    bundles_root = tmp_path / "bundles"
    _write_bundles(bundles_root)

    conn = sqlite3.connect(str(tmp_path / "e2e.db"), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    lock = asyncio.Lock()
    event_bus = EventBus()
    node_store = NodeStore(conn, lock)
    await node_store.create_tables()
    event_store = EventStore(connection=conn, lock=lock, event_bus=event_bus)
    await event_store.initialize()

    config = Config(
        discovery_paths=("src",),
        discovery_languages=("python",),
        swarm_root=".remora-e2e",
        bundle_root=str(bundles_root),
        model_default="mock",
    )
    workspace_service = CairnWorkspaceService(config, tmp_path)
    await workspace_service.initialize()
    reconciler = FileReconciler(
        config,
        node_store,
        event_store,
        workspace_service,
        project_root=tmp_path,
    )
    code_nodes = await reconciler.full_scan()
    runner = AgentRunner(event_store, node_store, workspace_service, config)

    return {
        "source_path": source_path,
        "conn": conn,
        "event_bus": event_bus,
        "node_store": node_store,
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
    node = runtime["nodes"][0]

    workspace = await runtime["workspace_service"].get_agent_workspace(node.node_id)
    assert await workspace.exists("_bundle/bundle.yaml")
    assert await workspace.exists("_bundle/tools/rewrite_self.pym")

    await runtime["event_store"].append(
        HumanChatEvent(to_agent=node.node_id, message="please rewrite")
    )
    trigger_iter = runtime["event_store"].get_triggers()
    trigger_node_id, trigger_event = await asyncio.wait_for(trigger_iter.__anext__(), timeout=1.0)
    assert trigger_node_id == node.node_id

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
        "remora.core.runner.create_kernel",
        lambda **kwargs: MockKernel(kwargs.get("tools", [])),
    )
    class FakeRewriteTool:
        def __init__(self, externals):
            self._externals = externals

        @property
        def schema(self) -> ToolSchema:
            return ToolSchema(
                name="rewrite_self",
                description="Propose rewrite",
                parameters={
                    "type": "object",
                    "properties": {"new_source": {"type": "string"}},
                    "required": ["new_source"],
                },
            )

        async def execute(self, arguments, context):  # noqa: ANN001, ANN201
            proposal_id = await self._externals["propose_rewrite"](arguments["new_source"])
            return ToolResult(
                call_id=getattr(context, "id", ""),
                name="rewrite_self",
                output=proposal_id,
                is_error=False,
            )

    async def fake_discover_tools(_workspace, externals):  # noqa: ANN001, ANN202
        return [FakeRewriteTool(externals)]

    monkeypatch.setattr("remora.core.runner.discover_tools", fake_discover_tools)
    await runtime["runner"]._execute_turn(
        Trigger(
            node_id=node.node_id,
            correlation_id="corr-e2e",
            event=trigger_event,
        )
    )

    events = await runtime["event_store"].get_events(limit=50)
    proposal_events = [event for event in events if event["event_type"] == "RewriteProposalEvent"]
    assert proposal_events
    proposal_id = proposal_events[0]["payload"]["proposal_id"]

    app = create_app(
        runtime["event_store"],
        runtime["node_store"],
        runtime["event_bus"],
        project_root=tmp_path,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post("/api/approve", json={"proposal_id": proposal_id})
    assert response.status_code == 200
    updated_source = runtime["source_path"].read_text(encoding="utf-8")
    assert "def alpha():\n    return 42\n" in updated_source
    assert "def beta():\n    return 2\n" in updated_source

    events_after = await runtime["event_store"].get_events(limit=50)
    assert any(event["event_type"] == "ContentChangedEvent" for event in events_after)

    await runtime["workspace_service"].close()
    runtime["conn"].close()


@pytest.mark.asyncio
async def test_e2e_agent_message_chain(tmp_path: Path) -> None:
    runtime = await _setup_runtime(tmp_path)
    nodes = runtime["nodes"]
    source = nodes[0].node_id
    target = nodes[1].node_id

    await runtime["event_store"].append(
        AgentMessageEvent(from_agent=source, to_agent=target, content="hello")
    )
    trigger_iter = runtime["event_store"].get_triggers()
    trigger_node_id, trigger_event = await asyncio.wait_for(trigger_iter.__anext__(), timeout=1.0)
    assert trigger_node_id == target
    assert trigger_event.event_type == "AgentMessageEvent"

    await runtime["workspace_service"].close()
    runtime["conn"].close()


@pytest.mark.asyncio
async def test_e2e_file_change_triggers(tmp_path: Path) -> None:
    runtime = await _setup_runtime(tmp_path)
    node = runtime["nodes"][0]

    await runtime["event_store"].append(
        ContentChangedEvent(path=node.file_path, change_type="modified")
    )
    trigger_iter = runtime["event_store"].get_triggers()
    trigger_node_id, trigger_event = await asyncio.wait_for(trigger_iter.__anext__(), timeout=1.0)
    assert trigger_node_id == node.node_id
    assert trigger_event.event_type == "ContentChangedEvent"

    await runtime["workspace_service"].close()
    runtime["conn"].close()
