from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import json
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from remora.core.events import AgentMessageEvent, EventBus, EventStore
from remora.core.db import open_database
from remora.core.graph import NodeStore
from remora.web.server import create_app
from tests.factories import make_node


@pytest_asyncio.fixture
async def web_env(tmp_path: Path):
    db = await open_database(tmp_path / "web.db")
    event_bus = EventBus()
    node_store = NodeStore(db)
    await node_store.create_tables()
    event_store = EventStore(db=db, event_bus=event_bus)
    await event_store.create_tables()

    source_path = tmp_path / "src" / "app.py"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("def a():\n    return 1\n", encoding="utf-8")

    node = make_node(
        "src/app.py::a",
        file_path=str(source_path),
        source_code="def a():\n    return 1\n",
        start_line=1,
        end_line=2,
    )
    await node_store.upsert_node(node)

    app = create_app(
        event_store,
        node_store,
        event_bus,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client, node_store, event_store, source_path

    await db.close()


@pytest.mark.asyncio
async def test_api_nodes_returns_list(web_env) -> None:
    client, _node_store, _event_store, _source_path = web_env
    response = await client.get("/api/nodes")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert payload and payload[0]["node_id"] == "src/app.py::a"


@pytest.mark.asyncio
async def test_api_node_by_id(web_env) -> None:
    client, _node_store, _event_store, _source_path = web_env
    response = await client.get("/api/nodes/src/app.py::a")
    assert response.status_code == 200
    payload = response.json()
    assert payload["node_id"] == "src/app.py::a"


@pytest.mark.asyncio
async def test_api_node_not_found(web_env) -> None:
    client, _node_store, _event_store, _source_path = web_env
    response = await client.get("/api/nodes/missing")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_api_edges(web_env) -> None:
    client, node_store, _event_store, source_path = web_env
    other = make_node(
        "src/app.py::b",
        file_path=str(source_path),
        source_code="def b():\n    return 2\n",
        start_line=1,
        end_line=2,
    )
    await node_store.upsert_node(other)
    await node_store.add_edge("src/app.py::a", "src/app.py::b", "calls")

    response = await client.get("/api/nodes/src/app.py::a/edges")
    assert response.status_code == 200
    payload = response.json()
    assert payload and payload[0]["edge_type"] == "calls"


@pytest.mark.asyncio
async def test_api_all_edges(web_env) -> None:
    client, node_store, _event_store, source_path = web_env
    other = make_node(
        "src/app.py::b",
        file_path=str(source_path),
        source_code="def b():\n    return 2\n",
        start_line=1,
        end_line=2,
    )
    await node_store.upsert_node(other)
    await node_store.add_edge("src/app.py::a", "src/app.py::b", "calls")

    response = await client.get("/api/edges")
    assert response.status_code == 200
    payload = response.json()
    assert payload and payload[0]["edge_type"] == "calls"


@pytest.mark.asyncio
async def test_api_chat_emits_agent_message_event(web_env) -> None:
    client, _node_store, event_store, _source_path = web_env
    response = await client.post(
        "/api/chat",
        json={"node_id": "src/app.py::a", "message": "hello"},
    )
    assert response.status_code == 200

    events = await event_store.get_events(limit=10)
    assert any(
        event["event_type"] == "AgentMessageEvent"
        and event["payload"].get("from_agent") == "user"
        and event["payload"].get("to_agent") == "src/app.py::a"
        and event["payload"].get("content") == "hello"
        for event in events
    )


@pytest.mark.asyncio
async def test_api_chat_missing_node_returns_404(web_env) -> None:
    client, _node_store, _event_store, _source_path = web_env
    response = await client.post(
        "/api/chat",
        json={"node_id": "missing-node", "message": "hello"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_api_events(web_env) -> None:
    client, _node_store, event_store, _source_path = web_env
    await event_store.append(
        AgentMessageEvent(from_agent="user", to_agent="src/app.py::a", content="ping")
    )

    response = await client.get("/api/events")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert payload and payload[0]["event_type"] == "AgentMessageEvent"


@pytest.mark.asyncio
async def test_api_cursor_resolves_node(web_env) -> None:
    client, _node_store, _event_store, source_path = web_env
    response = await client.post(
        "/api/cursor",
        json={
            "file_path": str(source_path),
            "line": 1,
            "character": 0,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["node_id"] == "src/app.py::a"


@pytest.mark.asyncio
async def test_api_cursor_requires_file_path(web_env) -> None:
    client, *_rest = web_env
    response = await client.post(
        "/api/cursor",
        json={"line": 1, "character": 0},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_sse_stream_connected(web_env) -> None:
    client, _node_store, _event_store, _source_path = web_env

    async with client.stream("GET", "/sse?once=1") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")


@pytest.mark.asyncio
async def test_sse_receives_events(web_env) -> None:
    client, _node_store, event_store, _source_path = web_env

    async def read_one_data_line(response: httpx.Response) -> str:
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                return line
        raise AssertionError("SSE stream closed before data line was received")

    await event_store.append(
        AgentMessageEvent(
            from_agent="user",
            to_agent="src/app.py::a",
            content="from-sse-test",
        )
    )
    async with client.stream("GET", "/sse?once=1&replay=5") as response:
        data_line = await asyncio.wait_for(read_one_data_line(response), timeout=2.0)

    payload = json.loads(data_line.removeprefix("data: ").strip())
    assert payload["event_type"] == "AgentMessageEvent"
    assert payload["payload"]["content"] == "from-sse-test"
    assert set(payload.keys()) == {"event_type", "timestamp", "correlation_id", "payload"}


@pytest.mark.asyncio
async def test_sse_replay_and_live_payload_shapes_match(web_env) -> None:
    _client, node_store, event_store, _source_path = web_env

    async def read_one_data_line(response: httpx.Response) -> str:
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                return line
        raise AssertionError("SSE stream closed before data line was received")

    await event_store.append(
        AgentMessageEvent(from_agent="user", to_agent="src/app.py::a", content="replay-shape")
    )

    async with _client.stream("GET", "/sse?once=1&replay=1") as replay_response:
        replay_line = await asyncio.wait_for(read_one_data_line(replay_response), timeout=2.0)

    class FakeEventBus:
        @asynccontextmanager
        async def stream(self) -> AsyncIterator[AsyncIterator[AgentMessageEvent]]:
            async def iterate() -> AsyncIterator[AgentMessageEvent]:
                yield AgentMessageEvent(
                    from_agent="user",
                    to_agent="src/app.py::a",
                    content="live-shape",
                )

            yield iterate()

    app = create_app(event_store, node_store, FakeEventBus())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with client.stream("GET", "/sse") as live_response:
            live_line = await asyncio.wait_for(read_one_data_line(live_response), timeout=2.0)

    replay_payload = json.loads(replay_line.removeprefix("data: ").strip())
    live_payload = json.loads(live_line.removeprefix("data: ").strip())
    assert set(replay_payload.keys()) == {"event_type", "timestamp", "correlation_id", "payload"}
    assert set(live_payload.keys()) == {"event_type", "timestamp", "correlation_id", "payload"}


@pytest.mark.asyncio
async def test_api_approve_endpoint_removed(web_env) -> None:
    client, *_rest = web_env
    response = await client.post("/api/approve", json={"id": "x"})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_api_reject_endpoint_removed(web_env) -> None:
    client, *_rest = web_env
    response = await client.post("/api/reject", json={"id": "x"})
    assert response.status_code == 404
