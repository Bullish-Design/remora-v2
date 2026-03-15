"""Event system: types, bus, subscriptions, persistence, and dispatch."""

from remora.core.events.bus import EventBus
from remora.core.events.dispatcher import TriggerDispatcher
from remora.core.events.store import EventStore
from remora.core.events.subscriptions import (
    SubscriptionPattern,
    SubscriptionRegistry,
)
from remora.core.events.types import (
    AgentCompleteEvent,
    AgentErrorEvent,
    AgentMessageEvent,
    AgentStartEvent,
    ContentChangedEvent,
    CursorFocusEvent,
    CustomEvent,
    Event,
    EventHandler,
    NodeChangedEvent,
    NodeDiscoveredEvent,
    NodeRemovedEvent,
    ToolResultEvent,
)

__all__ = [
    "Event",
    "AgentStartEvent",
    "AgentCompleteEvent",
    "AgentErrorEvent",
    "AgentMessageEvent",
    "NodeDiscoveredEvent",
    "NodeRemovedEvent",
    "NodeChangedEvent",
    "ContentChangedEvent",
    "CursorFocusEvent",
    "CustomEvent",
    "ToolResultEvent",
    "EventHandler",
    "EventBus",
    "SubscriptionPattern",
    "SubscriptionRegistry",
    "EventStore",
    "TriggerDispatcher",
]
