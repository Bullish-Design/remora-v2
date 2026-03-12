"""Persistent graph store for CodeNode agents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from remora.core.db import AsyncDB
from remora.core.node import CodeNode


@dataclass(frozen=True)
class Edge:
    """A directed edge between two nodes."""

    from_id: str
    to_id: str
    edge_type: str


class NodeStore:
    """SQLite-backed storage for the CodeNode graph."""

    def __init__(self, db: AsyncDB):
        self._db = db

    @property
    def db(self) -> AsyncDB:
        return self._db

    async def create_tables(self) -> None:
        """Create nodes and edges tables with indexes."""
        await self._db.execute_script(
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
                caller_ids TEXT DEFAULT '[]',
                callee_ids TEXT DEFAULT '[]',
                status TEXT DEFAULT 'idle',
                bundle_name TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(node_type);
            CREATE INDEX IF NOT EXISTS idx_nodes_file ON nodes(file_path);
            CREATE INDEX IF NOT EXISTS idx_nodes_status ON nodes(status);
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

    async def upsert_node(self, node: CodeNode) -> None:
        """Insert or replace a node by node_id."""
        row = node.to_row()
        columns = ", ".join(row.keys())
        placeholders = ", ".join("?" for _ in row)
        await self._db.execute(
            f"INSERT OR REPLACE INTO nodes ({columns}) VALUES ({placeholders})",
            tuple(row.values()),
        )

    async def get_node(self, node_id: str) -> CodeNode | None:
        """Fetch a single node by ID."""
        row = await self._db.fetch_one("SELECT * FROM nodes WHERE node_id = ?", (node_id,))
        return None if row is None else CodeNode.from_row(row)

    async def list_nodes(
        self,
        node_type: str | None = None,
        status: str | None = None,
        file_path: str | None = None,
    ) -> list[CodeNode]:
        """List nodes with optional filtering fields."""
        conditions: list[str] = []
        params: list[Any] = []
        if node_type is not None:
            conditions.append("node_type = ?")
            params.append(node_type)
        if status is not None:
            conditions.append("status = ?")
            params.append(status)
        if file_path is not None:
            conditions.append("file_path = ?")
            params.append(file_path)

        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
        sql = f"SELECT * FROM nodes{where_clause} ORDER BY node_id ASC"
        rows = await self._db.fetch_all(sql, tuple(params))
        return [CodeNode.from_row(row) for row in rows]

    async def delete_node(self, node_id: str) -> bool:
        """Delete a node and all edges connected to it."""
        await self._db.execute(
            "DELETE FROM edges WHERE from_id = ? OR to_id = ?",
            (node_id, node_id),
        )
        deleted = await self._db.delete("DELETE FROM nodes WHERE node_id = ?", (node_id,))
        return deleted > 0

    async def set_status(self, node_id: str, status: str) -> None:
        """Update a node status in-place."""
        await self._db.execute(
            "UPDATE nodes SET status = ? WHERE node_id = ?",
            (status, node_id),
        )

    async def add_edge(self, from_id: str, to_id: str, edge_type: str) -> None:
        """Insert an edge unless it already exists."""
        await self._db.execute(
            """
            INSERT OR IGNORE INTO edges (from_id, to_id, edge_type)
            VALUES (?, ?, ?)
            """,
            (from_id, to_id, edge_type),
        )

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

        rows = await self._db.fetch_all(sql, params)
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
        return await self._db.delete(
            "DELETE FROM edges WHERE from_id = ? OR to_id = ?",
            (node_id, node_id),
        )


__all__ = ["Edge", "NodeStore"]
