"""CodeNode - the unified agent data model."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from remora.core.types import NodeStatus, NodeType


class CodeNode(BaseModel):
    """A code element that is also an autonomous agent."""

    model_config = ConfigDict(frozen=False)

    # Identity
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

    # Graph context
    parent_id: str | None = None
    # TODO: remove caller/callee lists once edge-based projections fully replace them.
    caller_ids: list[str] = Field(default_factory=list)
    callee_ids: list[str] = Field(default_factory=list)

    # Runtime
    status: NodeStatus = NodeStatus.IDLE

    # Provisioning
    bundle_name: str | None = None

    def to_row(self) -> dict[str, Any]:
        """Serialize the model into a sqlite-ready row."""
        data = self.model_dump()
        data["node_type"] = (
            data["node_type"].value if hasattr(data["node_type"], "value") else data["node_type"]
        )
        data["status"] = data["status"].value if hasattr(data["status"], "value") else data["status"]
        data["caller_ids"] = json.dumps(data["caller_ids"])
        data["callee_ids"] = json.dumps(data["callee_ids"])
        return data

    @classmethod
    def from_row(cls, row: sqlite3.Row | dict[str, Any]) -> CodeNode:
        """Hydrate a model from a sqlite row representation."""
        data = dict(row)
        data["caller_ids"] = json.loads(data.get("caller_ids") or "[]")
        data["callee_ids"] = json.loads(data.get("callee_ids") or "[]")
        return cls(**data)
