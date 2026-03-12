"""Event types and base classes."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field


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


class AgentStartEvent(Event):
    agent_id: str
    node_name: str = ""


class AgentCompleteEvent(Event):
    agent_id: str
    result_summary: str = ""

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


class HumanChatEvent(Event):
    to_agent: str
    message: str

    def summary(self) -> str:
        return self.message


class AgentTextResponse(Event):
    agent_id: str
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


class ContentChangedEvent(Event):
    path: str
    change_type: str = "modified"


class RewriteProposalEvent(Event):
    agent_id: str
    proposal_id: str
    file_path: str
    old_source: str
    new_source: str
    diff: str = ""


class CustomEvent(Event):
    payload: dict[str, Any] = Field(default_factory=dict)


class ToolResultEvent(Event):
    agent_id: str
    tool_name: str
    result_summary: str = ""

    def summary(self) -> str:
        return self.result_summary


EventHandler = Callable[[Event], Any]


__all__ = [
    "Event",
    "AgentStartEvent",
    "AgentCompleteEvent",
    "AgentErrorEvent",
    "AgentMessageEvent",
    "HumanChatEvent",
    "AgentTextResponse",
    "NodeDiscoveredEvent",
    "NodeRemovedEvent",
    "NodeChangedEvent",
    "ContentChangedEvent",
    "RewriteProposalEvent",
    "CustomEvent",
    "ToolResultEvent",
    "EventHandler",
]
