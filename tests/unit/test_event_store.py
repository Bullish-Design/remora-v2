from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from remora.core.events import (
    AgentMessageEvent,
    AgentStartEvent,
    EventBus,
    EventStore,
    SubscriptionPattern,
)


@pytest.mark.asyncio
async def test_eventstore_append_returns_id(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.db")
    await store.initialize()
    first = await store.append(AgentStartEvent(agent_id="a"))
    second = await store.append(AgentStartEvent(agent_id="b"))
    assert first == 1
    assert second == 2


@pytest.mark.asyncio
async def test_eventstore_query_events(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.db")
    await store.initialize()
    await store.append(AgentStartEvent(agent_id="a"))
    await store.append(AgentMessageEvent(from_agent="a", to_agent="b", content="hello"))
    events = await store.get_events(limit=2)
    assert len(events) == 2
    assert events[0]["event_type"] == "AgentMessageEvent"
    assert events[1]["event_type"] == "AgentStartEvent"


@pytest.mark.asyncio
async def test_eventstore_query_by_agent(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.db")
    await store.initialize()
    await store.append(AgentStartEvent(agent_id="target"))
    await store.append(AgentMessageEvent(from_agent="x", to_agent="target", content="inbound"))
    await store.append(AgentMessageEvent(from_agent="x", to_agent="other", content="skip"))
    events = await store.get_events_for_agent("target", limit=10)
    event_types = [event["event_type"] for event in events]
    assert event_types.count("AgentStartEvent") == 1
    assert event_types.count("AgentMessageEvent") == 1


@pytest.mark.asyncio
async def test_eventstore_trigger_flow(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.db")
    await store.initialize()
    await store.subscriptions.register("agent-b", SubscriptionPattern(to_agent="b"))

    event = AgentMessageEvent(from_agent="a", to_agent="b", content="hello")
    await store.append(event)

    agent_id, trigger_event = await asyncio.wait_for(anext(store.get_triggers()), timeout=1.0)
    assert agent_id == "agent-b"
    assert trigger_event == event


@pytest.mark.asyncio
async def test_eventstore_forwards_to_bus(tmp_path: Path) -> None:
    bus = EventBus()
    seen: list[str] = []

    def handler(event) -> None:
        seen.append(event.event_type)

    bus.subscribe_all(handler)
    store = EventStore(tmp_path / "events.db", event_bus=bus)
    await store.initialize()
    await store.append(AgentStartEvent(agent_id="a"))
    assert seen == ["AgentStartEvent"]
