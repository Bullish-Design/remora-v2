"""Tests for actor model primitives."""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

from remora.core.actor import Outbox, RecordingOutbox
from remora.core.db import AsyncDB
from remora.core.events import AgentCompleteEvent, AgentStartEvent, EventStore


@pytest_asyncio.fixture
async def outbox_env(tmp_path: Path):
    db = AsyncDB.from_path(tmp_path / "outbox.db")
    event_store = EventStore(db=db)
    await event_store.create_tables()
    outbox = Outbox(actor_id="agent-a", event_store=event_store, correlation_id="corr-1")
    yield outbox, event_store, db
    db.close()


@pytest.mark.asyncio
async def test_outbox_emit_persists_event(outbox_env) -> None:
    outbox, event_store, _db = outbox_env
    event_id = await outbox.emit(AgentStartEvent(agent_id="agent-a"))
    assert event_id == 1
    events = await event_store.get_events(limit=1)
    assert events[0]["event_type"] == "AgentStartEvent"


@pytest.mark.asyncio
async def test_outbox_tags_correlation_id(outbox_env) -> None:
    outbox, event_store, _db = outbox_env
    event = AgentStartEvent(agent_id="agent-a")
    assert event.correlation_id is None
    await outbox.emit(event)
    events = await event_store.get_events(limit=1)
    assert events[0]["correlation_id"] == "corr-1"


@pytest.mark.asyncio
async def test_outbox_preserves_existing_correlation_id(outbox_env) -> None:
    outbox, event_store, _db = outbox_env
    event = AgentStartEvent(agent_id="agent-a", correlation_id="original")
    await outbox.emit(event)
    events = await event_store.get_events(limit=1)
    assert events[0]["correlation_id"] == "original"


@pytest.mark.asyncio
async def test_outbox_increments_sequence(outbox_env) -> None:
    outbox, _event_store, _db = outbox_env
    assert outbox.sequence == 0
    await outbox.emit(AgentStartEvent(agent_id="agent-a"))
    assert outbox.sequence == 1
    await outbox.emit(AgentCompleteEvent(agent_id="agent-a"))
    assert outbox.sequence == 2


@pytest.mark.asyncio
async def test_outbox_correlation_id_setter(outbox_env) -> None:
    outbox, event_store, _db = outbox_env
    outbox.correlation_id = "new-corr"
    await outbox.emit(AgentStartEvent(agent_id="agent-a"))
    events = await event_store.get_events(limit=1)
    assert events[0]["correlation_id"] == "new-corr"


@pytest.mark.asyncio
async def test_recording_outbox_captures_events() -> None:
    outbox = RecordingOutbox(actor_id="test-agent")
    outbox.correlation_id = "corr-1"
    await outbox.emit(AgentStartEvent(agent_id="test-agent"))
    await outbox.emit(AgentCompleteEvent(agent_id="test-agent"))
    assert len(outbox.events) == 2
    assert outbox.events[0].event_type == "AgentStartEvent"
    assert outbox.events[1].event_type == "AgentCompleteEvent"
    assert all(event.correlation_id == "corr-1" for event in outbox.events)
    assert outbox.sequence == 2


@pytest.mark.asyncio
async def test_recording_outbox_no_persistence() -> None:
    outbox = RecordingOutbox()
    event_id = await outbox.emit(AgentStartEvent(agent_id="x"))
    assert event_id == 1
    assert len(outbox.events) == 1
