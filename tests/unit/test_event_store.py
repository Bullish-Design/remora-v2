from __future__ import annotations

from pathlib import Path

import pytest

from remora.core.db import AsyncDB
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
    db = AsyncDB.from_path(tmp_path / "events.db")
    store = EventStore(db=db)
    await store.create_tables()
    first = await store.append(AgentStartEvent(agent_id="a"))
    second = await store.append(AgentStartEvent(agent_id="b"))
    assert first == 1
    assert second == 2
    db.close()


@pytest.mark.asyncio
async def test_eventstore_query_events(tmp_path: Path) -> None:
    db = AsyncDB.from_path(tmp_path / "events.db")
    store = EventStore(db=db)
    await store.create_tables()
    await store.append(AgentStartEvent(agent_id="a"))
    await store.append(AgentMessageEvent(from_agent="a", to_agent="b", content="hello"))
    events = await store.get_events(limit=2)
    assert len(events) == 2
    assert events[0]["event_type"] == "AgentMessageEvent"
    assert events[1]["event_type"] == "AgentStartEvent"
    db.close()


@pytest.mark.asyncio
async def test_eventstore_query_by_agent(tmp_path: Path) -> None:
    db = AsyncDB.from_path(tmp_path / "events.db")
    store = EventStore(db=db)
    await store.create_tables()
    await store.append(AgentStartEvent(agent_id="target"))
    await store.append(AgentMessageEvent(from_agent="x", to_agent="target", content="inbound"))
    await store.append(AgentMessageEvent(from_agent="x", to_agent="other", content="skip"))
    events = await store.get_events_for_agent("target", limit=10)
    event_types = [event["event_type"] for event in events]
    assert event_types.count("AgentStartEvent") == 1
    assert event_types.count("AgentMessageEvent") == 1
    db.close()


@pytest.mark.asyncio
async def test_eventstore_trigger_flow(tmp_path: Path) -> None:
    db = AsyncDB.from_path(tmp_path / "events.db")
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
    db.close()


@pytest.mark.asyncio
async def test_eventstore_forwards_to_bus(tmp_path: Path) -> None:
    bus = EventBus()
    seen: list[str] = []

    def handler(event) -> None:
        seen.append(event.event_type)

    bus.subscribe_all(handler)
    db = AsyncDB.from_path(tmp_path / "events.db")
    store = EventStore(db=db, event_bus=bus)
    await store.create_tables()
    await store.append(AgentStartEvent(agent_id="a"))
    assert seen == ["AgentStartEvent"]
    db.close()
