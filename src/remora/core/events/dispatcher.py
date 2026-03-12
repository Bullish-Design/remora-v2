"""Trigger dispatch: routes events to matching agents via subscriptions."""

from __future__ import annotations

from collections.abc import Callable

from remora.core.events.subscriptions import SubscriptionRegistry
from remora.core.events.types import Event


class TriggerDispatcher:
    """Routes persisted events to agent inboxes via subscription matching.

    The dispatcher resolves which agents care about an event, then
    delivers the event to each agent's inbox via a router callback.
    """

    def __init__(
        self,
        subscriptions: SubscriptionRegistry,
        router: Callable[[str, Event], None] | None = None,
    ):
        self._subscriptions = subscriptions
        self._router = router

    @property
    def router(self) -> Callable[[str, Event], None] | None:
        return self._router

    @router.setter
    def router(self, value: Callable[[str, Event], None]) -> None:
        self._router = value

    async def dispatch(self, event: Event) -> None:
        """Match event against subscriptions and route to agent inboxes."""
        if self._router is None:
            return
        for agent_id in await self._subscriptions.get_matching_agents(event):
            self._router(agent_id, event)

    @property
    def subscriptions(self) -> SubscriptionRegistry:
        return self._subscriptions


__all__ = ["TriggerDispatcher"]
