"""Shared type definitions for Remora."""

from __future__ import annotations

from enum import Enum


class NodeStatus(str, Enum):
    """Valid states for a code node / agent."""

    IDLE = "idle"
    RUNNING = "running"
    ERROR = "error"


class NodeType(str, Enum):
    """Types of discovered code elements."""

    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"
    SECTION = "section"
    TABLE = "table"
    DIRECTORY = "directory"


class ChangeType(str, Enum):
    """Types of content changes."""

    MODIFIED = "modified"
    CREATED = "created"
    DELETED = "deleted"
    OPENED = "opened"


STATUS_TRANSITIONS: dict[NodeStatus, set[NodeStatus]] = {
    NodeStatus.IDLE: {NodeStatus.RUNNING},
    NodeStatus.RUNNING: {NodeStatus.IDLE, NodeStatus.ERROR},
    NodeStatus.ERROR: {NodeStatus.IDLE, NodeStatus.RUNNING},
}


def validate_status_transition(current: NodeStatus, target: NodeStatus) -> bool:
    """Return True if the transition is allowed."""
    return target in STATUS_TRANSITIONS.get(current, set())


__all__ = [
    "NodeStatus",
    "NodeType",
    "ChangeType",
    "STATUS_TRANSITIONS",
    "validate_status_transition",
]
