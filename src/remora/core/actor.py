"""Actor model primitives: Outbox and AgentActor."""

from __future__ import annotations

import logging

from remora.core.events.store import EventStore
from remora.core.events.types import Event

logger = logging.getLogger(__name__)


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


class RecordingOutbox:
    """Test double that records emitted events without persisting.

    Drop-in replacement for Outbox in unit tests.
    """

    def __init__(self, actor_id: str = "test") -> None:
        self._actor_id = actor_id
        self._correlation_id: str | None = None
        self._sequence = 0
        self.events: list[Event] = []

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
        """Record event without persisting."""
        self._sequence += 1
        if not event.correlation_id and self._correlation_id:
            event.correlation_id = self._correlation_id
        self.events.append(event)
        return self._sequence


__all__ = ["Outbox", "RecordingOutbox"]
