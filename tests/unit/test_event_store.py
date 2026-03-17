from __future__ import annotations

from pathlib import Path

import pytest

from remora.core.db import open_database
from remora.core.events import (
    AgentMessageEvent,
    AgentStartEvent,
    Event,
    EventBus,
    EventStore,
    SubscriptionPattern,
)


@pytest.mark.asyncio
async def test_eventstore_append_returns_id(tmp_path: Path) -> None:
    db = await open_database(tmp_path / "events.db")
    store = EventStore(db=db)
    await store.create_tables()
    first = await store.append(AgentStartEvent(agent_id="a"))
    second = await store.append(AgentStartEvent(agent_id="b"))
    assert first == 1
    assert second == 2
    await db.close()


@pytest.mark.asyncio
async def test_eventstore_query_events(tmp_path: Path) -> None:
    db = await open_database(tmp_path / "events.db")
    store = EventStore(db=db)
    await store.create_tables()
    await store.append(AgentStartEvent(agent_id="a"))
    await store.append(AgentMessageEvent(from_agent="a", to_agent="b", content="hello"))
    events = await store.get_events(limit=2)
    assert len(events) == 2
    assert events[0]["event_type"] == "agent_message"
    assert events[1]["event_type"] == "agent_start"
    await db.close()


@pytest.mark.asyncio
async def test_eventstore_query_by_agent(tmp_path: Path) -> None:
    db = await open_database(tmp_path / "events.db")
    store = EventStore(db=db)
    await store.create_tables()
    await store.append(AgentStartEvent(agent_id="target"))
    await store.append(AgentMessageEvent(from_agent="x", to_agent="target", content="inbound"))
    await store.append(AgentMessageEvent(from_agent="x", to_agent="other", content="skip"))
    events = await store.get_events_for_agent("target", limit=10)
    event_types = [event["event_type"] for event in events]
    assert event_types.count("agent_start") == 1
    assert event_types.count("agent_message") == 1
    await db.close()


@pytest.mark.asyncio
async def test_eventstore_get_latest_event_by_type(tmp_path: Path) -> None:
    db = await open_database(tmp_path / "events.db")
    store = EventStore(db=db)
    await store.create_tables()
    await store.append(AgentStartEvent(agent_id="target"))
    await store.append(AgentMessageEvent(from_agent="x", to_agent="target", content="first"))
    await store.append(AgentMessageEvent(from_agent="target", to_agent="y", content="latest"))

    event = await store.get_latest_event_by_type("target", "agent_message")
    assert event is not None
    assert event["event_type"] == "agent_message"
    assert event["payload"]["content"] == "latest"
    await db.close()


@pytest.mark.asyncio
async def test_eventstore_get_latest_event_by_type_returns_none(tmp_path: Path) -> None:
    db = await open_database(tmp_path / "events.db")
    store = EventStore(db=db)
    await store.create_tables()
    await store.append(AgentStartEvent(agent_id="target"))

    event = await store.get_latest_event_by_type("target", "agent_message")
    assert event is None
    await db.close()


@pytest.mark.asyncio
async def test_eventstore_trigger_flow(tmp_path: Path) -> None:
    db = await open_database(tmp_path / "events.db")
    store = EventStore(db=db)
    await store.create_tables()
    await store.subscriptions.register("agent-b", SubscriptionPattern(to_agent="b"))
    routed: list[tuple[str, Event]] = []
    store.dispatcher.router = lambda agent_id, event: routed.append((agent_id, event))

    event = AgentMessageEvent(from_agent="a", to_agent="b", content="hello")
    await store.append(event)

    assert len(routed) == 1
    assert routed[0][0] == "agent-b"
    assert routed[0][1] == event
    await db.close()


@pytest.mark.asyncio
async def test_eventstore_forwards_to_bus(tmp_path: Path) -> None:
    bus = EventBus()
    seen: list[str] = []

    def handler(event) -> None:
        seen.append(event.event_type)

    bus.subscribe_all(handler)
    db = await open_database(tmp_path / "events.db")
    store = EventStore(db=db, event_bus=bus)
    await store.create_tables()
    await store.append(AgentStartEvent(agent_id="a"))
    assert seen == ["agent_start"]
    await db.close()


@pytest.mark.asyncio
async def test_eventstore_batch_uses_single_commit(tmp_path: Path) -> None:
    db = await open_database(tmp_path / "events.db")
    store = EventStore(db=db)
    await store.create_tables()

    commit_count = 0
    original_commit = db.commit

    async def counting_commit() -> None:
        nonlocal commit_count
        commit_count += 1
        await original_commit()

    db.commit = counting_commit  # type: ignore[method-assign]
    commit_count = 0

    async with store.batch():
        for index in range(10):
            await store.append(AgentStartEvent(agent_id=f"a{index}"))

    assert commit_count == 1
    await db.close()
