"""Trigger dispatch: routes events to matching agents via subscriptions."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from remora.core.events.subscriptions import SubscriptionRegistry
from remora.core.events.types import Event


class TriggerDispatcher:
    """Routes persisted events to agent trigger queues via subscription matching."""

    def __init__(self, subscriptions: SubscriptionRegistry):
        self._subscriptions = subscriptions
        self._queue: asyncio.Queue[tuple[str, Event]] = asyncio.Queue()

    async def dispatch(self, event: Event) -> None:
        """Match event against subscriptions and enqueue triggers."""
        for agent_id in await self._subscriptions.get_matching_agents(event):
            self._queue.put_nowait((agent_id, event))

    async def get_triggers(self) -> AsyncIterator[tuple[str, Event]]:
        """Yield queued (agent_id, event) pairs forever."""
        while True:
            yield await self._queue.get()

    @property
    def subscriptions(self) -> SubscriptionRegistry:
        return self._subscriptions


__all__ = ["TriggerDispatcher"]
