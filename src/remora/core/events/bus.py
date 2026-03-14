"""In-memory event bus."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from remora.core.events.types import Event, EventHandler

logger = logging.getLogger(__name__)


class EventBus:
    """In-memory event dispatch with inheritance-aware subscriptions."""

    def __init__(self) -> None:
        self._handlers: dict[type[Event], list[EventHandler]] = {}
        self._all_handlers: list[EventHandler] = []

    async def emit(self, event: Event) -> None:
        """Emit an event to all specific and global handlers."""
        for event_type in type(event).__mro__:
            await self._dispatch_handlers(self._handlers.get(event_type, []), event)
        await self._dispatch_handlers(self._all_handlers, event)

    @staticmethod
    async def _dispatch_handlers(
        handlers: list[EventHandler], event: Event
    ) -> None:
        tasks: list[asyncio.Task[Any]] = []
        for handler in handlers:
            result = handler(event)
            if asyncio.iscoroutine(result):
                tasks.append(asyncio.create_task(result))
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    logger.exception(
                        "Event handler failed for %s: %s",
                        event.event_type,
                        result,
                        exc_info=result,
                    )

    def subscribe(self, event_type: type[Event], handler: EventHandler) -> None:
        """Register a handler for a specific event type."""
        self._handlers.setdefault(event_type, []).append(handler)

    def subscribe_all(self, handler: EventHandler) -> None:
        """Register a handler for all event types."""
        self._all_handlers.append(handler)

    def unsubscribe(self, handler: EventHandler) -> None:
        """Remove a handler from all subscriptions."""
        for handlers in self._handlers.values():
            if handler in handlers:
                handlers.remove(handler)
        if handler in self._all_handlers:
            self._all_handlers.remove(handler)

    @asynccontextmanager
    async def stream(self, *event_types: type[Event]) -> AsyncIterator[AsyncIterator[Event]]:
        """Yield an async iterator of events for optional filtered types."""
        queue: asyncio.Queue[Event] = asyncio.Queue()
        filter_set = set(event_types) if event_types else None

        def enqueue(event: Event) -> None:
            matches_filter = filter_set is None or any(
                isinstance(event, event_type) for event_type in filter_set
            )
            if matches_filter:
                queue.put_nowait(event)

        self.subscribe_all(enqueue)

        async def iterate() -> AsyncIterator[Event]:
            while True:
                yield await queue.get()

        try:
            yield iterate()
        finally:
            self.unsubscribe(enqueue)


__all__ = ["EventBus"]
