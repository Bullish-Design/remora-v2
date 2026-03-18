"""In-memory event bus."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from remora.core.events.types import Event, EventHandler
from remora.core.model.errors import RemoraError

logger = logging.getLogger(__name__)


class EventBus:
    """In-memory event dispatch with exact-type subscriptions."""

    def __init__(self, max_concurrent_handlers: int = 100) -> None:
        self._handlers: dict[type[Event], list[EventHandler]] = {}
        self._all_handlers: list[EventHandler] = []
        self._semaphore = asyncio.Semaphore(max_concurrent_handlers)

    async def emit(self, event: Event) -> None:
        """Emit an event to exact-type, base Event, and global handlers."""
        event_type = type(event)
        await self._dispatch_handlers(self._handlers.get(event_type, []), event, self._semaphore)
        if event_type is not Event:
            await self._dispatch_handlers(self._handlers.get(Event, []), event, self._semaphore)
        await self._dispatch_handlers(self._all_handlers, event, self._semaphore)

    @staticmethod
    async def _dispatch_handlers(
        handlers: list[EventHandler],
        event: Event,
        semaphore: asyncio.Semaphore | None = None,
    ) -> None:
        tasks: list[asyncio.Task[Any]] = []
        for handler in handlers:
            if asyncio.iscoroutinefunction(handler):
                if semaphore is None:
                    tasks.append(asyncio.create_task(handler(event)))
                else:
                    tasks.append(
                        asyncio.create_task(EventBus._run_bounded(handler, event, semaphore))
                    )
                continue
            try:
                handler(event)
            except (RemoraError, OSError) as exc:
                logger.exception(
                    "Event handler failed for %s: %s",
                    event.event_type,
                    exc,
                    exc_info=exc,
                )
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

    @staticmethod
    async def _run_bounded(
        handler: Any,
        event: Event,
        semaphore: asyncio.Semaphore,
    ) -> None:
        async with semaphore:
            await handler(event)

    def subscribe(self, event_type: type[Event], handler: EventHandler) -> None:
        """Register a handler for a specific event type."""
        self._handlers.setdefault(event_type, []).append(handler)

    def subscribe_all(self, handler: EventHandler) -> None:
        """Register a handler for all event types."""
        self._all_handlers.append(handler)

    def unsubscribe(self, handler: EventHandler) -> None:
        """Remove a handler from all subscriptions."""
        empty_event_types: list[type[Event]] = []
        for event_type, handlers in self._handlers.items():
            remaining = [registered for registered in handlers if registered is not handler]
            if remaining:
                self._handlers[event_type] = remaining
            else:
                empty_event_types.append(event_type)
        for event_type in empty_event_types:
            del self._handlers[event_type]
        self._all_handlers = [
            registered for registered in self._all_handlers if registered is not handler
        ]

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
