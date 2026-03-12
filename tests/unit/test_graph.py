from __future__ import annotations

import pytest
from tests.factories import make_node

from remora.core.events import AgentStartEvent, EventStore
from remora.core.graph import NodeStore
from remora.core.types import NodeStatus


@pytest.mark.asyncio
async def test_nodestore_upsert_and_get(db) -> None:
    store = NodeStore(db)
    await store.create_tables()
    node = make_node("src/app.py::a")
    await store.upsert_node(node)
    got = await store.get_node(node.node_id)
    assert got is not None
    assert got.model_dump() == node.model_dump()


@pytest.mark.asyncio
async def test_nodestore_list_with_filters(db) -> None:
    store = NodeStore(db)
    await store.create_tables()
    await store.upsert_node(make_node("src/app.py::a", node_type="function", status="idle"))
    await store.upsert_node(make_node("src/app.py::B", node_type="class", status="running"))
    await store.upsert_node(
        make_node(
            "src/other.py::c",
            node_type="function",
            status="idle",
            file_path="src/other.py",
        )
    )

    by_type = await store.list_nodes(node_type="class")
    by_status = await store.list_nodes(status="running")
    by_path = await store.list_nodes(file_path="src/other.py")

    assert [n.node_id for n in by_type] == ["src/app.py::B"]
    assert [n.node_id for n in by_status] == ["src/app.py::B"]
    assert [n.node_id for n in by_path] == ["src/other.py::c"]


@pytest.mark.asyncio
async def test_nodestore_delete(db) -> None:
    store = NodeStore(db)
    await store.create_tables()
    await store.upsert_node(make_node("src/app.py::a"))
    await store.upsert_node(make_node("src/app.py::b"))
    await store.add_edge("src/app.py::a", "src/app.py::b", "calls")

    assert await store.delete_node("src/app.py::a")
    assert await store.get_node("src/app.py::a") is None
    assert await store.get_edges("src/app.py::a") == []


@pytest.mark.asyncio
async def test_nodestore_set_status(db) -> None:
    store = NodeStore(db)
    await store.create_tables()
    node = make_node("src/app.py::a", status="idle")
    await store.upsert_node(node)

    await store.set_status(node.node_id, "running")
    got = await store.get_node(node.node_id)
    assert got is not None
    assert got.status == "running"
    assert got.source_hash == node.source_hash


@pytest.mark.asyncio
async def test_nodestore_add_edge(db) -> None:
    store = NodeStore(db)
    await store.create_tables()
    await store.upsert_node(make_node("src/app.py::a"))
    await store.upsert_node(make_node("src/app.py::b"))

    await store.add_edge("src/app.py::a", "src/app.py::b", "calls")
    edges = await store.get_edges("src/app.py::a", direction="outgoing")
    assert len(edges) == 1
    assert edges[0].from_id == "src/app.py::a"
    assert edges[0].to_id == "src/app.py::b"
    assert edges[0].edge_type == "calls"


@pytest.mark.asyncio
async def test_nodestore_edge_directions(db) -> None:
    store = NodeStore(db)
    await store.create_tables()
    await store.upsert_node(make_node("src/app.py::a"))
    await store.upsert_node(make_node("src/app.py::b"))
    await store.upsert_node(make_node("src/app.py::c"))
    await store.add_edge("src/app.py::a", "src/app.py::b", "calls")
    await store.add_edge("src/app.py::c", "src/app.py::a", "calls")

    outgoing = await store.get_edges("src/app.py::a", direction="outgoing")
    incoming = await store.get_edges("src/app.py::a", direction="incoming")
    both = await store.get_edges("src/app.py::a", direction="both")

    assert len(outgoing) == 1
    assert outgoing[0].to_id == "src/app.py::b"
    assert len(incoming) == 1
    assert incoming[0].from_id == "src/app.py::c"
    assert len(both) == 2


@pytest.mark.asyncio
async def test_nodestore_edge_uniqueness(db) -> None:
    store = NodeStore(db)
    await store.create_tables()
    await store.upsert_node(make_node("src/app.py::a"))
    await store.upsert_node(make_node("src/app.py::b"))

    await store.add_edge("src/app.py::a", "src/app.py::b", "calls")
    await store.add_edge("src/app.py::a", "src/app.py::b", "calls")
    edges = await store.get_edges("src/app.py::a", direction="outgoing")
    assert len(edges) == 1


@pytest.mark.asyncio
async def test_shared_connection(db) -> None:
    node_store = NodeStore(db)
    event_store = EventStore(db=db)
    await node_store.create_tables()
    await event_store.create_tables()
    await node_store.upsert_node(make_node("src/app.py::a"))
    event_id = await event_store.append(AgentStartEvent(agent_id="src/app.py::a"))
    got = await node_store.get_node("src/app.py::a")

    assert got is not None
    assert event_id == 1
    assert node_store.db.connection is event_store.connection
    assert node_store.db.lock is event_store.lock


@pytest.mark.asyncio
async def test_nodestore_transition_status_valid(db) -> None:
    store = NodeStore(db)
    await store.create_tables()
    await store.upsert_node(make_node("src/app.py::a", status="idle"))

    assert await store.transition_status("src/app.py::a", NodeStatus.RUNNING)
    updated = await store.get_node("src/app.py::a")
    assert updated is not None
    assert updated.status == NodeStatus.RUNNING


@pytest.mark.asyncio
async def test_nodestore_transition_status_invalid(db) -> None:
    store = NodeStore(db)
    await store.create_tables()
    await store.upsert_node(make_node("src/app.py::a", status="idle"))

    assert not await store.transition_status("src/app.py::a", NodeStatus.ERROR)
    updated = await store.get_node("src/app.py::a")
    assert updated is not None
    assert updated.status == NodeStatus.IDLE


@pytest.mark.asyncio
async def test_nodestore_get_children(db) -> None:
    store = NodeStore(db)
    await store.create_tables()
    await store.upsert_node(
        make_node(
            "src",
            node_type="directory",
            file_path="src",
            parent_id=".",
            start_line=0,
            end_line=0,
            source_code="",
            source_hash="hash-src",
        )
    )
    await store.upsert_node(make_node("src/app.py::a", parent_id="src"))
    await store.upsert_node(make_node("src/lib", node_type="directory", parent_id="src"))

    children = await store.get_children("src")
    assert [node.node_id for node in children] == ["src/app.py::a", "src/lib"]
