from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import pytest_asyncio

from remora.core.config import Config
from remora.core.db import AsyncDB
from remora.core.events import AgentMessageEvent, EventStore
from remora.core.graph import NodeStore
from remora.core.node import CodeNode
from remora.core.runner import AgentRunner
from remora.core.workspace import CairnWorkspaceService


def _node(node_id: str, file_path: str = "src/app.py", node_type: str = "function") -> CodeNode:
    name = node_id.split("::", maxsplit=1)[-1]
    return CodeNode(
        node_id=node_id,
        node_type=node_type,
        name=name,
        full_name=name,
        file_path=file_path,
        start_line=1,
        end_line=4,
        source_code=f"def {name}():\n    return 1\n",
        source_hash=f"h-{node_id}",
    )


@pytest_asyncio.fixture
async def runner_env(tmp_path: Path):
    db = AsyncDB.from_path(tmp_path / "phase4.db")
    node_store = NodeStore(db)
    await node_store.create_tables()
    event_store = EventStore(db=db)
    await event_store.create_tables()

    config = Config(swarm_root=".remora-phase4")
    workspace_service = CairnWorkspaceService(config, tmp_path)
    await workspace_service.initialize()

    runner = AgentRunner(event_store, node_store, workspace_service, config)
    yield runner, node_store, event_store, workspace_service

    await workspace_service.close()
    db.close()


@pytest.mark.asyncio
async def test_externals_workspace_ops(runner_env) -> None:
    runner, node_store, _event_store, workspace_service = runner_env
    node = _node("src/app.py::alpha")
    await node_store.upsert_node(node)
    ws = await workspace_service.get_agent_workspace(node.node_id)

    externals = runner._build_externals(node.node_id, ws, "corr-1")
    assert await externals["write_file"]("notes/a.txt", "hello")
    assert await externals["read_file"]("notes/a.txt") == "hello"
    assert await externals["file_exists"]("notes/a.txt") is True
    assert "a.txt" in await externals["list_dir"]("notes")
    assert "notes/a.txt" in await externals["search_files"]("a.txt")
    matches = await externals["search_content"]("hello", "notes")
    assert matches and matches[0]["file"] == "notes/a.txt"


@pytest.mark.asyncio
async def test_externals_graph_ops(runner_env) -> None:
    runner, node_store, _event_store, workspace_service = runner_env
    a = _node("src/app.py::a")
    b = _node("src/app.py::b")
    await node_store.upsert_node(a)
    await node_store.upsert_node(b)
    await node_store.add_edge(a.node_id, b.node_id, "calls")

    ws = await workspace_service.get_agent_workspace(a.node_id)
    externals = runner._build_externals(a.node_id, ws, "corr-1")

    got = await externals["graph_get_node"](a.node_id)
    listed = await externals["graph_query_nodes"]("function", None)
    edges = await externals["graph_get_edges"](a.node_id)
    assert got["node_id"] == a.node_id
    assert len(listed) == 2
    assert edges[0]["to_id"] == b.node_id
    assert await externals["graph_set_status"](a.node_id, "running")


@pytest.mark.asyncio
async def test_externals_event_ops(runner_env) -> None:
    runner, node_store, event_store, workspace_service = runner_env
    node = _node("src/app.py::alpha")
    await node_store.upsert_node(node)
    ws = await workspace_service.get_agent_workspace(node.node_id)
    externals = runner._build_externals(node.node_id, ws, "corr-1")

    sub_id = await externals["event_subscribe"](["AgentMessageEvent"], None, None)
    assert isinstance(sub_id, int)
    assert await externals["event_emit"]("CustomEvent", {"value": "x"})
    stored = await event_store.get_events(limit=10)
    custom = next(event for event in stored if event["event_type"] == "CustomEvent")
    assert custom["payload"]["payload"]["value"] == "x"
    history = await externals["event_get_history"](node.node_id, limit=10)
    assert isinstance(history, list)
    assert await externals["event_unsubscribe"](sub_id)

    # still functional after unregister
    await event_store.append(AgentMessageEvent(from_agent="a", to_agent=node.node_id, content="x"))
    got = await event_store.get_events_for_agent(node.node_id, limit=5)
    assert got


@pytest.mark.asyncio
async def test_externals_communication(runner_env) -> None:
    runner, node_store, event_store, workspace_service = runner_env
    sender = _node("src/app.py::sender")
    target_a = _node("src/app.py::target_a")
    target_b = _node("src/app.py::target_b")
    await node_store.upsert_node(sender)
    await node_store.upsert_node(target_a)
    await node_store.upsert_node(target_b)

    ws = await workspace_service.get_agent_workspace(sender.node_id)
    externals = runner._build_externals(sender.node_id, ws, "corr-1")

    assert await externals["send_message"](target_a.node_id, "direct")
    summary = await externals["broadcast"]("*", "all")
    assert "Broadcast sent to" in summary
    events = await event_store.get_events(limit=10)
    message_events = [event for event in events if event["event_type"] == "AgentMessageEvent"]
    assert len(message_events) >= 3


@pytest.mark.asyncio
async def test_externals_code_ops(runner_env) -> None:
    runner, node_store, event_store, workspace_service = runner_env
    source_path = workspace_service._project_root / "src" / "app.py"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    full_source = (
        "def alpha():\n"
        "    return 1\n\n"
        "def beta():\n"
        "    return 2\n"
    )
    source_path.write_text(full_source, encoding="utf-8")

    node = _node("src/app.py::alpha", file_path=str(source_path))
    node = node.model_copy(update={"source_code": "def alpha():\n    return 1\n"})
    await node_store.upsert_node(node)
    ws = await workspace_service.get_agent_workspace(node.node_id)
    externals = runner._build_externals(node.node_id, ws, "corr-1")

    assert await externals["apply_rewrite"]("def alpha():\n    return 2\n")

    source = await externals["get_node_source"](node.node_id)
    assert "def alpha" in source
    file_source = source_path.read_text(encoding="utf-8")
    assert "def alpha():\n    return 2\n" in file_source

    events = await event_store.get_events(limit=5)
    rewrite_events = [event for event in events if event["event_type"] == "ContentChangedEvent"]
    assert rewrite_events
    assert rewrite_events[0]["payload"]["path"] == str(source_path)


@pytest.mark.asyncio
async def test_apply_rewrite_duplicate_source_blocks(runner_env) -> None:
    runner, node_store, _event_store, workspace_service = runner_env
    source_path = workspace_service._project_root / "src" / "dup.py"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(
        "def helper():\n    return 1\n\ndef helper():\n    return 1\n",
        encoding="utf-8",
    )

    node = _node(f"{source_path}::helper_2", file_path=str(source_path))
    node = node.model_copy(
        update={
            "name": "helper",
            "full_name": "helper",
            "start_line": 4,
            "end_line": 5,
            "start_byte": 28,
            "end_byte": 55,
            "source_code": "def helper():\n    return 1\n",
        }
    )
    await node_store.upsert_node(node)
    ws = await workspace_service.get_agent_workspace(node.node_id)
    externals = runner._build_externals(node.node_id, ws, "corr-1")

    applied = await externals["apply_rewrite"]("def helper():\n    return 2\n")
    assert applied
    new_source = source_path.read_text(encoding="utf-8")
    assert "def helper():\n    return 1\n\ndef helper():\n    return 2\n" == new_source


@pytest.mark.asyncio
async def test_externals_identity(runner_env) -> None:
    runner, node_store, _event_store, workspace_service = runner_env
    node = _node("src/app.py::alpha")
    await node_store.upsert_node(node)
    ws = await workspace_service.get_agent_workspace(node.node_id)
    externals = runner._build_externals(node.node_id, ws, "corr-x")
    assert externals["my_node_id"] == node.node_id
    assert externals["my_correlation_id"] == "corr-x"
