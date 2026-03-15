"""Event types and base classes."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from remora.core.types import ChangeType


class Event(BaseModel):
    """Base event with automatic event_type tagging."""

    event_type: str = ""
    timestamp: float = Field(default_factory=time.time)
    correlation_id: str | None = None

    def model_post_init(self, __context: Any) -> None:
        if not self.event_type:
            self.event_type = type(self).__name__

    def summary(self) -> str:
        """Return a human-readable summary of this event."""
        return ""

    def to_envelope(self) -> dict[str, Any]:
        payload = self.model_dump(
            exclude={"event_type", "timestamp", "correlation_id"},
        )
        return {
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "correlation_id": self.correlation_id,
            "payload": payload,
        }


class AgentStartEvent(Event):
    agent_id: str
    node_name: str = ""


class AgentCompleteEvent(Event):
    agent_id: str
    result_summary: str = ""
    full_response: str = ""

    def summary(self) -> str:
        return self.result_summary


class AgentErrorEvent(Event):
    agent_id: str
    error: str

    def summary(self) -> str:
        return self.error


class AgentMessageEvent(Event):
    from_agent: str
    to_agent: str
    content: str

    def summary(self) -> str:
        return self.content


class NodeDiscoveredEvent(Event):
    node_id: str
    node_type: str
    file_path: str
    name: str


class NodeRemovedEvent(Event):
    node_id: str
    node_type: str
    file_path: str
    name: str


class NodeChangedEvent(Event):
    node_id: str
    old_hash: str
    new_hash: str
    file_path: str | None = None


class ContentChangedEvent(Event):
    path: str
    change_type: ChangeType = ChangeType.MODIFIED
    agent_id: str | None = None
    old_hash: str | None = None
    new_hash: str | None = None


class CustomEvent(Event):
    payload: dict[str, Any] = Field(default_factory=dict)


class ToolResultEvent(Event):
    agent_id: str
    tool_name: str
    result_summary: str = ""

    def summary(self) -> str:
        return self.result_summary


class CursorFocusEvent(Event):
    """Emitted when the editor cursor focuses on a code element."""

    file_path: str
    line: int
    character: int
    node_id: str | None = None
    node_name: str | None = None
    node_type: str | None = None


EventHandler = Callable[[Event], Any]


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
    "CustomEvent",
    "ToolResultEvent",
    "CursorFocusEvent",
    "EventHandler",
]
