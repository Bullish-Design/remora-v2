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
    assert seen == ["agent_message"]


@pytest.mark.asyncio
async def test_bus_does_not_dispatch_to_intermediate_base_classes() -> None:
    bus = EventBus()
    seen: list[str] = []

    class IntermediateEvent(Event):
        value: str

    class DerivedEvent(IntermediateEvent):
        pass

    def intermediate_handler(_event: IntermediateEvent) -> None:
        seen.append("intermediate")

    def base_handler(_event: Event) -> None:
        seen.append("base")

    bus.subscribe(IntermediateEvent, intermediate_handler)
    bus.subscribe(Event, base_handler)
    await bus.emit(DerivedEvent(value="x"))

    assert seen == ["base"]


@pytest.mark.asyncio
async def test_bus_subscribe_all() -> None:
    bus = EventBus()
    seen: list[str] = []

    def handler(event: Event) -> None:
        seen.append(event.event_type)

    bus.subscribe_all(handler)
    await bus.emit(AgentStartEvent(agent_id="a"))
    await bus.emit(AgentMessageEvent(from_agent="user", to_agent="a", content="hi"))
    assert seen == ["agent_start", "agent_message"]


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
async def test_bus_unsubscribe_clears_all_registrations_for_handler() -> None:
    bus = EventBus()
    seen: list[str] = []

    def handler(event: Event) -> None:
        seen.append(event.event_type)

    bus.subscribe(AgentStartEvent, handler)
    bus.subscribe(AgentStartEvent, handler)
    bus.subscribe(AgentMessageEvent, handler)
    bus.subscribe_all(handler)
    bus.subscribe_all(handler)

    bus.unsubscribe(handler)

    await bus.emit(AgentStartEvent(agent_id="a"))
    await bus.emit(AgentMessageEvent(from_agent="user", to_agent="a", content="hi"))
    assert seen == []
    assert AgentStartEvent not in bus._handlers
    assert AgentMessageEvent not in bus._handlers
    assert bus._all_handlers == []


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


@pytest.mark.asyncio
async def test_event_bus_limits_concurrent_handlers() -> None:
    bus = EventBus(max_concurrent_handlers=2)
    active = 0
    max_active = 0

    async def slow_handler(_event: Event) -> None:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1

    for _ in range(10):
        bus.subscribe_all(slow_handler)

    await bus.emit(AgentStartEvent(agent_id="concurrency"))
    assert max_active <= 2
