"""Persistent graph and agent stores."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import aiosqlite
from remora.core.node import Node
from remora.core.types import NodeStatus, NodeType, validate_status_transition

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Edge:
    """A directed edge between two nodes."""

    from_id: str
    to_id: str
    edge_type: str


class NodeStore:
    """SQLite-backed storage for the Node graph."""

    def __init__(self, db: aiosqlite.Connection):
        self._db = db

    async def create_tables(self) -> None:
        """Create nodes and edges tables with indexes."""
        await self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS nodes (
                node_id TEXT PRIMARY KEY,
                node_type TEXT NOT NULL,
                name TEXT NOT NULL,
                full_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                start_line INTEGER NOT NULL,
                end_line INTEGER NOT NULL,
                start_byte INTEGER DEFAULT 0,
                end_byte INTEGER DEFAULT 0,
                source_code TEXT NOT NULL,
                source_hash TEXT NOT NULL,
                parent_id TEXT,
                status TEXT DEFAULT 'idle',
                role TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(node_type);
            CREATE INDEX IF NOT EXISTS idx_nodes_file ON nodes(file_path);
            CREATE INDEX IF NOT EXISTS idx_nodes_status ON nodes(status);
            CREATE INDEX IF NOT EXISTS idx_nodes_parent ON nodes(parent_id);
            CREATE TABLE IF NOT EXISTS edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_id TEXT NOT NULL,
                to_id TEXT NOT NULL,
                edge_type TEXT NOT NULL,
                UNIQUE(from_id, to_id, edge_type)
            );
            CREATE INDEX IF NOT EXISTS idx_edges_from ON edges(from_id);
            CREATE INDEX IF NOT EXISTS idx_edges_to ON edges(to_id);
            """
        )
        await self._db.commit()

    async def upsert_node(self, node: Node) -> None:
        """Insert or replace a node by node_id."""
        row = node.to_row()
        columns = ", ".join(row.keys())
        placeholders = ", ".join("?" for _ in row)
        await self._db.execute(
            f"INSERT OR REPLACE INTO nodes ({columns}) VALUES ({placeholders})",
            tuple(row.values()),
        )
        await self._db.commit()

    async def get_node(self, node_id: str) -> Node | None:
        """Fetch a single node by ID."""
        cursor = await self._db.execute(
            "SELECT * FROM nodes WHERE node_id = ?",
            (node_id,),
        )
        row = await cursor.fetchone()
        return None if row is None else Node.from_row(row)

    async def list_nodes(
        self,
        node_type: str | NodeType | None = None,
        status: str | NodeStatus | None = None,
        file_path: str | None = None,
    ) -> list[Node]:
        """List nodes with optional filtering fields."""
        conditions: list[str] = []
        params: list[Any] = []
        if node_type is not None:
            conditions.append("node_type = ?")
            params.append(node_type.value if isinstance(node_type, NodeType) else node_type)
        if status is not None:
            conditions.append("status = ?")
            params.append(status.value if isinstance(status, NodeStatus) else status)
        if file_path is not None:
            conditions.append("file_path = ?")
            params.append(file_path)

        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
        sql = f"SELECT * FROM nodes{where_clause} ORDER BY node_id ASC"
        cursor = await self._db.execute(sql, tuple(params))
        rows = await cursor.fetchall()
        return [Node.from_row(row) for row in rows]

    async def get_children(self, parent_id: str) -> list[Node]:
        """Get all nodes whose parent_id matches."""
        cursor = await self._db.execute(
            "SELECT * FROM nodes WHERE parent_id = ? ORDER BY node_id ASC",
            (parent_id,),
        )
        rows = await cursor.fetchall()
        return [Node.from_row(row) for row in rows]

    async def delete_node(self, node_id: str) -> bool:
        """Delete a node and all edges connected to it."""
        await self._db.execute(
            "DELETE FROM edges WHERE from_id = ? OR to_id = ?",
            (node_id, node_id),
        )
        cursor = await self._db.execute(
            "DELETE FROM nodes WHERE node_id = ?",
            (node_id,),
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def set_status(self, node_id: str, status: str | NodeStatus) -> None:
        """Update a node status in-place."""
        status_value = status.value if isinstance(status, NodeStatus) else status
        await self._db.execute(
            "UPDATE nodes SET status = ? WHERE node_id = ?",
            (status_value, node_id),
        )
        await self._db.commit()

    async def transition_status(self, node_id: str, target: NodeStatus) -> bool:
        """Transition node status if the transition is valid."""
        node = await self.get_node(node_id)
        if node is None:
            return False
        current = node.status
        if not validate_status_transition(current, target):
            logger.warning(
                "Invalid status transition for %s: %s -> %s",
                node_id,
                current,
                target,
            )
            return False
        await self.set_status(node_id, target)
        return True

    async def add_edge(self, from_id: str, to_id: str, edge_type: str) -> None:
        """Insert an edge unless it already exists."""
        await self._db.execute(
            """
            INSERT OR IGNORE INTO edges (from_id, to_id, edge_type)
            VALUES (?, ?, ?)
            """,
            (from_id, to_id, edge_type),
        )
        await self._db.commit()

    async def get_edges(self, node_id: str, direction: str = "both") -> list[Edge]:
        """Get edges for a node in outgoing, incoming, or both directions."""
        if direction == "outgoing":
            sql = "SELECT from_id, to_id, edge_type FROM edges WHERE from_id = ? ORDER BY id ASC"
            params: tuple[Any, ...] = (node_id,)
        elif direction == "incoming":
            sql = "SELECT from_id, to_id, edge_type FROM edges WHERE to_id = ? ORDER BY id ASC"
            params = (node_id,)
        elif direction == "both":
            sql = (
                "SELECT from_id, to_id, edge_type FROM edges "
                "WHERE from_id = ? OR to_id = ? ORDER BY id ASC"
            )
            params = (node_id, node_id)
        else:
            raise ValueError("direction must be one of: outgoing, incoming, both")

        cursor = await self._db.execute(sql, params)
        rows = await cursor.fetchall()
        return [
            Edge(
                from_id=row["from_id"],
                to_id=row["to_id"],
                edge_type=row["edge_type"],
            )
            for row in rows
        ]

    async def delete_edges(self, node_id: str) -> int:
        """Delete all edges connected to a node and return deleted count."""
        cursor = await self._db.execute(
            "DELETE FROM edges WHERE from_id = ? OR to_id = ?",
            (node_id, node_id),
        )
        await self._db.commit()
        return cursor.rowcount

    async def list_all_edges(self) -> list[Edge]:
        """Return all edges in the graph."""
        cursor = await self._db.execute(
            "SELECT from_id, to_id, edge_type FROM edges ORDER BY id ASC"
        )
        rows = await cursor.fetchall()
        return [
            Edge(from_id=row["from_id"], to_id=row["to_id"], edge_type=row["edge_type"])
            for row in rows
        ]


__all__ = ["Edge", "NodeStore"]
