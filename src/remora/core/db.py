"""Async SQLite database wrapper with connection lifecycle management."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any


class AsyncDB:
    """Thin async wrapper around sqlite3 with lock + thread-hop + auto-commit."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        lock: asyncio.Lock | None = None,
    ) -> None:
        self._conn = connection
        self._lock = lock or asyncio.Lock()

    @classmethod
    def from_path(cls, db_path: Path | str) -> "AsyncDB":
        """Create an AsyncDB from a file path, configuring WAL mode."""
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.row_factory = sqlite3.Row
        return cls(conn)

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        """Execute SQL with auto-commit."""

        def run() -> sqlite3.Cursor:
            cursor = self._conn.execute(sql, params)
            self._conn.commit()
            return cursor

        async with self._lock:
            return await asyncio.to_thread(run)

    async def execute_script(self, sql: str) -> None:
        """Execute multiple SQL statements for schema creation."""

        def run() -> None:
            self._conn.executescript(sql)
            self._conn.commit()

        async with self._lock:
            await asyncio.to_thread(run)

    async def execute_many(self, statements: list[tuple[str, tuple[Any, ...]]]) -> None:
        """Execute multiple statements in a single transaction."""

        def run() -> None:
            for sql, params in statements:
                self._conn.execute(sql, params)
            self._conn.commit()

        async with self._lock:
            await asyncio.to_thread(run)

    async def fetch_one(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        """Fetch a single row."""

        def run() -> sqlite3.Row | None:
            return self._conn.execute(sql, params).fetchone()

        async with self._lock:
            return await asyncio.to_thread(run)

    async def fetch_all(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        """Fetch all rows."""

        def run() -> list[sqlite3.Row]:
            return self._conn.execute(sql, params).fetchall()

        async with self._lock:
            return await asyncio.to_thread(run)

    async def insert(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        """Execute an INSERT and return lastrowid."""

        def run() -> int:
            cursor = self._conn.execute(sql, params)
            self._conn.commit()
            return int(cursor.lastrowid)

        async with self._lock:
            return await asyncio.to_thread(run)

    async def delete(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        """Execute a DELETE and return rowcount."""

        def run() -> int:
            cursor = self._conn.execute(sql, params)
            self._conn.commit()
            return int(cursor.rowcount)

        async with self._lock:
            return await asyncio.to_thread(run)

    def close(self) -> None:
        """Close the underlying connection."""
        self._conn.close()


__all__ = ["AsyncDB"]
