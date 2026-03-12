"""Code elements and agent models."""

from __future__ import annotations

import sqlite3
from typing import Any

from pydantic import BaseModel, ConfigDict

from remora.core.types import NodeStatus, NodeType


class CodeElement(BaseModel):
    """An immutable code structure discovered from source."""

    model_config = ConfigDict(frozen=True)

    element_id: str
    element_type: NodeType
    name: str
    full_name: str
    file_path: str
    start_line: int
    end_line: int
    start_byte: int = 0
    end_byte: int = 0
    source_code: str
    source_hash: str
    parent_id: str | None = None


class Agent(BaseModel):
    """An autonomous agent that may be attached to a code element."""

    model_config = ConfigDict(frozen=False)

    agent_id: str
    element_id: str | None = None
    status: NodeStatus = NodeStatus.IDLE
    bundle_name: str | None = None

    def to_row(self) -> dict[str, Any]:
        data = self.model_dump()
        data["status"] = data["status"].value if hasattr(data["status"], "value") else data["status"]
        return data

    @classmethod
    def from_row(cls, row: sqlite3.Row | dict[str, Any]) -> "Agent":
        return cls(**dict(row))


class CodeNode(BaseModel):
    """Combined view for migration and backwards compatibility."""

    model_config = ConfigDict(frozen=False)

    node_id: str
    node_type: NodeType
    name: str
    full_name: str
    file_path: str
    start_line: int
    end_line: int
    start_byte: int = 0
    end_byte: int = 0
    source_code: str
    source_hash: str
    parent_id: str | None = None
    status: NodeStatus = NodeStatus.IDLE
    bundle_name: str | None = None

    def to_element(self) -> CodeElement:
        return CodeElement(
            element_id=self.node_id,
            element_type=self.node_type,
            name=self.name,
            full_name=self.full_name,
            file_path=self.file_path,
            start_line=self.start_line,
            end_line=self.end_line,
            start_byte=self.start_byte,
            end_byte=self.end_byte,
            source_code=self.source_code,
            source_hash=self.source_hash,
            parent_id=self.parent_id,
        )

    def to_agent(self) -> Agent:
        return Agent(
            agent_id=self.node_id,
            element_id=self.node_id,
            status=self.status,
            bundle_name=self.bundle_name,
        )

    def to_row(self) -> dict[str, Any]:
        """Serialize the model into a sqlite-ready row."""
        data = self.model_dump()
        data["node_type"] = (
            data["node_type"].value if hasattr(data["node_type"], "value") else data["node_type"]
        )
        data["status"] = data["status"].value if hasattr(data["status"], "value") else data["status"]
        return data

    @classmethod
    def from_row(cls, row: sqlite3.Row | dict[str, Any]) -> "CodeNode":
        """Hydrate a model from a sqlite row representation."""
        data = dict(row)
        return cls(**data)


__all__ = ["CodeElement", "Agent", "CodeNode"]
