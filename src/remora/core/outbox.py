"""Outbox primitives for actor event emission and observer translation."""

from __future__ import annotations

from typing import Any

from structured_agents.events import (
    ModelRequestEvent as SAModelRequestEvent,
)
from structured_agents.events import (
    ModelResponseEvent as SAModelResponseEvent,
)
from structured_agents.events import (
    ToolCallEvent as SAToolCallEvent,
)
from structured_agents.events import (
    ToolResultEvent as SAToolResultEvent,
)
from structured_agents.events import (
    TurnCompleteEvent as SATurnCompleteEvent,
)

from remora.core.events.store import EventStore
from remora.core.events.types import (
    Event,
    ModelRequestEvent,
    ModelResponseEvent,
    RemoraToolCallEvent,
    RemoraToolResultEvent,
    TurnCompleteEvent,
)


class Outbox:
    """Write-through emitter that tags events with actor metadata.

    Not a buffer - events reach EventStore immediately on emit().
    The outbox exists as an interception/tagging point, not as storage.
    """

    def __init__(
        self,
        actor_id: str,
        event_store: EventStore,
        correlation_id: str | None = None,
    ) -> None:
        self._actor_id = actor_id
        self._event_store = event_store
        self._correlation_id = correlation_id
        self._sequence = 0

    @property
    def actor_id(self) -> str:
        return self._actor_id

    @property
    def correlation_id(self) -> str | None:
        return self._correlation_id

    @correlation_id.setter
    def correlation_id(self, value: str | None) -> None:
        self._correlation_id = value

    @property
    def sequence(self) -> int:
        return self._sequence

    async def emit(self, event: Event) -> int:
        """Tag event with actor metadata and write through to EventStore."""
        self._sequence += 1
        if not event.correlation_id and self._correlation_id:
            event.correlation_id = self._correlation_id
        return await self._event_store.append(event)


class OutboxObserver:
    """Bridge structured-agents kernel observer events into Remora events."""

    def __init__(self, outbox: Outbox, agent_id: str) -> None:
        self._outbox = outbox
        self._agent_id = agent_id

    async def emit(self, event: Any) -> None:
        remora_event = self._translate(event)
        if remora_event is not None:
            await self._outbox.emit(remora_event)

    def _translate(self, event: Any) -> Event | None:
        if isinstance(event, SAModelRequestEvent):
            return ModelRequestEvent(
                agent_id=self._agent_id,
                model=str(getattr(event, "model", "")),
                tool_count=int(getattr(event, "tools_count", 0) or 0),
                turn=int(getattr(event, "turn", 0) or 0),
            )
        if isinstance(event, SAModelResponseEvent):
            return ModelResponseEvent(
                agent_id=self._agent_id,
                response_preview=str(getattr(event, "content", "") or "")[:200],
                duration_ms=int(getattr(event, "duration_ms", 0) or 0),
                tool_calls_count=int(getattr(event, "tool_calls_count", 0) or 0),
                turn=int(getattr(event, "turn", 0) or 0),
            )
        if isinstance(event, SAToolCallEvent):
            return RemoraToolCallEvent(
                agent_id=self._agent_id,
                tool_name=str(getattr(event, "tool_name", "")),
                arguments_summary=str(getattr(event, "arguments", {}))[:200],
                turn=int(getattr(event, "turn", 0) or 0),
            )
        if isinstance(event, SAToolResultEvent):
            return RemoraToolResultEvent(
                agent_id=self._agent_id,
                tool_name=str(getattr(event, "tool_name", "")),
                is_error=bool(getattr(event, "is_error", False)),
                duration_ms=int(getattr(event, "duration_ms", 0) or 0),
                output_preview=str(getattr(event, "output_preview", "") or "")[:200],
                turn=int(getattr(event, "turn", 0) or 0),
            )
        if isinstance(event, SATurnCompleteEvent):
            return TurnCompleteEvent(
                agent_id=self._agent_id,
                turn=int(getattr(event, "turn", 0) or 0),
                tool_calls_count=int(getattr(event, "tool_calls_count", 0) or 0),
                errors_count=int(getattr(event, "errors_count", 0) or 0),
            )
        return None


__all__ = ["Outbox", "OutboxObserver"]
