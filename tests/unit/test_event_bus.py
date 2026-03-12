from __future__ import annotations

import asyncio

import pytest

from remora.core.events import AgentMessageEvent, AgentStartEvent, Event, EventBus, HumanChatEvent


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
    await bus.emit(HumanChatEvent(to_agent="a", message="hi"))
    assert seen == ["AgentStartEvent", "HumanChatEvent"]


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
        await bus.emit(HumanChatEvent(to_agent="x", message="skip"))
        await bus.emit(AgentStartEvent(agent_id="allowed"))
        received = await asyncio.wait_for(anext(events), timeout=1.0)
    assert isinstance(received, AgentStartEvent)
    assert received.agent_id == "allowed"
