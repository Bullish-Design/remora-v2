from __future__ import annotations

import asyncio

import pytest

from remora.core.events import AgentMessageEvent, AgentStartEvent, Event, EventBus


@pytest.mark.asyncio
async def test_bus_emit_subscribe() -> None:
    bus = EventBus()
    seen: list[str] = []

    def handler(event: AgentStartEvent) -> None:
        seen.append(event.agent_id)

    bus.subscribe(AgentStartEvent, handler)
    await bus.emit(AgentStartEvent(agent_id="node-1"))
    assert seen == ["node-1"]


@pytest.mark.asyncio
async def test_bus_mro_dispatch() -> None:
    bus = EventBus()
    seen: list[str] = []

    def handler(event: Event) -> None:
        seen.append(event.event_type)

    bus.subscribe(Event, handler)
    await bus.emit(AgentMessageEvent(from_agent="a", to_agent="b", content="hello"))
    assert seen == ["AgentMessageEvent"]


@pytest.mark.asyncio
async def test_bus_subscribe_all() -> None:
    bus = EventBus()
    seen: list[str] = []

    def handler(event: Event) -> None:
        seen.append(event.event_type)

    bus.subscribe_all(handler)
    await bus.emit(AgentStartEvent(agent_id="a"))
    await bus.emit(AgentMessageEvent(from_agent="user", to_agent="a", content="hi"))
    assert seen == ["AgentStartEvent", "AgentMessageEvent"]


@pytest.mark.asyncio
async def test_bus_unsubscribe() -> None:
    bus = EventBus()
    seen: list[str] = []

    def handler(event: Event) -> None:
        seen.append(event.event_type)

    bus.subscribe_all(handler)
    bus.unsubscribe(handler)
    await bus.emit(AgentStartEvent(agent_id="a"))
    assert seen == []


@pytest.mark.asyncio
async def test_bus_stream() -> None:
    bus = EventBus()
    async with bus.stream() as events:
        await bus.emit(AgentStartEvent(agent_id="stream-agent"))
        received = await asyncio.wait_for(anext(events), timeout=1.0)
    assert isinstance(received, AgentStartEvent)
    assert received.agent_id == "stream-agent"


@pytest.mark.asyncio
async def test_bus_stream_filtered() -> None:
    bus = EventBus()
    async with bus.stream(AgentStartEvent) as events:
        await bus.emit(AgentMessageEvent(from_agent="user", to_agent="x", content="skip"))
        await bus.emit(AgentStartEvent(agent_id="allowed"))
        received = await asyncio.wait_for(anext(events), timeout=1.0)
    assert isinstance(received, AgentStartEvent)
    assert received.agent_id == "allowed"


@pytest.mark.asyncio
async def test_failing_handler_does_not_crash_bus() -> None:
    bus = EventBus()
    calls: list[Event] = []

    async def bad_handler(_event: Event) -> None:
        raise ValueError("boom")

    async def good_handler(event: Event) -> None:
        calls.append(event)

    bus.subscribe_all(good_handler)
    bus.subscribe_all(bad_handler)

    event = AgentStartEvent(agent_id="test")
    await bus.emit(event)
    assert len(calls) == 1
