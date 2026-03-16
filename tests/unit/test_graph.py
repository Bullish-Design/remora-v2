from __future__ import annotations

import asyncio

import pytest
from tests.factories import make_node

from remora.core.events import AgentStartEvent, EventStore
from remora.core.graph import NodeStore
from remora.core.types import NodeStatus, NodeType


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

    by_type = await store.list_nodes(node_type=NodeType.CLASS)
    by_status = await store.list_nodes(status=NodeStatus.RUNNING)
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

    await store.set_status(node.node_id, NodeStatus.RUNNING)
    got = await store.get_node(node.node_id)
    assert got is not None
    assert got.status == NodeStatus.RUNNING
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
async def test_shared_db_coexistence(db) -> None:
    node_store = NodeStore(db)
    event_store = EventStore(db=db)
    await node_store.create_tables()
    await event_store.create_tables()
    await node_store.upsert_node(make_node("src/app.py::a"))
    event_id = await event_store.append(AgentStartEvent(agent_id="src/app.py::a"))
    got = await node_store.get_node("src/app.py::a")

    assert got is not None
    assert event_id == 1


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
async def test_nodestore_transition_status_awaiting_input(db) -> None:
    store = NodeStore(db)
    await store.create_tables()
    await store.upsert_node(make_node("src/app.py::a", status="running"))

    assert await store.transition_status("src/app.py::a", NodeStatus.AWAITING_INPUT)
    paused = await store.get_node("src/app.py::a")
    assert paused is not None
    assert paused.status == NodeStatus.AWAITING_INPUT

    assert await store.transition_status("src/app.py::a", NodeStatus.RUNNING)
    resumed = await store.get_node("src/app.py::a")
    assert resumed is not None
    assert resumed.status == NodeStatus.RUNNING


@pytest.mark.asyncio
async def test_nodestore_transition_status_awaiting_review(db) -> None:
    store = NodeStore(db)
    await store.create_tables()
    await store.upsert_node(make_node("src/app.py::a", status="running"))

    assert await store.transition_status("src/app.py::a", NodeStatus.AWAITING_REVIEW)
    review = await store.get_node("src/app.py::a")
    assert review is not None
    assert review.status == NodeStatus.AWAITING_REVIEW

    assert await store.transition_status("src/app.py::a", NodeStatus.IDLE)
    idle = await store.get_node("src/app.py::a")
    assert idle is not None
    assert idle.status == NodeStatus.IDLE


@pytest.mark.asyncio
async def test_nodestore_transition_status_competing_updates_only_one_wins(db) -> None:
    store = NodeStore(db)
    await store.create_tables()
    await store.upsert_node(make_node("src/app.py::a", status="running"))

    results = await asyncio.gather(
        store.transition_status("src/app.py::a", NodeStatus.AWAITING_INPUT),
        store.transition_status("src/app.py::a", NodeStatus.ERROR),
    )

    assert sum(1 for result in results if result) == 1
    updated = await store.get_node("src/app.py::a")
    assert updated is not None
    assert updated.status in {NodeStatus.AWAITING_INPUT, NodeStatus.ERROR}


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


@pytest.mark.asyncio
async def test_nodestore_batch_commits_once_for_grouped_writes(db, monkeypatch) -> None:
    store = NodeStore(db)
    await store.create_tables()

    commit_calls = 0
    real_commit = db.commit

    async def counted_commit() -> None:
        nonlocal commit_calls
        commit_calls += 1
        await real_commit()

    monkeypatch.setattr(db, "commit", counted_commit)

    async with store.batch():
        await store.upsert_node(make_node("src/app.py::a"))
        await store.upsert_node(make_node("src/app.py::b"))
        await store.add_edge("src/app.py::a", "src/app.py::b", "calls")

    assert commit_calls == 1
