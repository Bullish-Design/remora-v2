"""EventStore persistence and fan-out."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Any

import aiosqlite

from remora.core.events.bus import EventBus
from remora.core.events.dispatcher import TriggerDispatcher
from remora.core.events.types import Event
from remora.core.services.metrics import Metrics
from remora.core.storage.transaction import TransactionContext


class EventStore:
    """Append-only SQLite event log with bus emission and trigger dispatch."""

    def __init__(
        self,
        db: aiosqlite.Connection,
        event_bus: EventBus,
        dispatcher: TriggerDispatcher,
        tx: TransactionContext,
        metrics: Metrics | None = None,
    ) -> None:
        self._db = db
        self._event_bus = event_bus
        self._dispatcher = dispatcher
        self._tx = tx
        self._metrics = metrics
        self._pending_responses: dict[str, asyncio.Future[str]] = {}

    @property
    def dispatcher(self) -> TriggerDispatcher:
        return self._dispatcher

    @property
    def subscriptions(self):  # noqa: ANN201
        return self._dispatcher.subscriptions

    async def create_tables(self) -> None:
        """Create event storage tables and indexes."""
        await self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                agent_id TEXT,
                from_agent TEXT,
                to_agent TEXT,
                correlation_id TEXT,
                timestamp REAL NOT NULL,
                tags TEXT NOT NULL DEFAULT '[]',
                payload TEXT NOT NULL,
                summary TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
            CREATE INDEX IF NOT EXISTS idx_events_agent ON events(agent_id);
            CREATE INDEX IF NOT EXISTS idx_events_correlation ON events(correlation_id);
            """
        )
        await self._db.commit()
        await self._dispatcher.subscriptions.create_tables()

    async def append(self, event: Event) -> int:
        """Append an event and fan-out to bus and matching subscription triggers."""
        envelope = event.to_envelope()
        payload = envelope["payload"]
        summary = event.summary()
        agent_id = payload.get("agent_id")
        from_agent = payload.get("from_agent")
        to_agent = payload.get("to_agent")

        cursor = await self._db.execute(
            """
            INSERT INTO events (
                event_type, agent_id, from_agent, to_agent,
                correlation_id, timestamp, tags, payload, summary
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                envelope["event_type"],
                agent_id,
                from_agent,
                to_agent,
                envelope["correlation_id"],
                envelope["timestamp"],
                json.dumps(envelope.get("tags", [])),
                json.dumps(payload),
                summary,
            ),
        )
        event_id = int(cursor.lastrowid)
        if self._metrics is not None:
            self._metrics.events_emitted_total += 1

        if self._tx.in_batch:
            self._tx.defer_event(event)
            return event_id

        await self._db.commit()
        await self._event_bus.emit(event)
        await self._dispatcher.dispatch(event)
        return event_id

    @asynccontextmanager
    async def batch(self):  # noqa: ANN201
        """Convenience alias for self._tx.batch()."""
        async with self._tx.batch():
            yield

    def create_response_future(self, request_id: str) -> asyncio.Future[str]:
        """Create and register a pending human-input response future."""
        future = asyncio.get_running_loop().create_future()
        self._pending_responses[request_id] = future
        return future

    def resolve_response(self, request_id: str, response: str) -> bool:
        """Resolve and remove a pending human-input response future."""
        future = self._pending_responses.pop(request_id, None)
        if future is None or future.done():
            return False
        future.set_result(response)
        return True

    def discard_response_future(self, request_id: str) -> bool:
        """Remove an unresolved pending future (e.g. timeout/cancel)."""
        future = self._pending_responses.pop(request_id, None)
        if future is None:
            return False
        if not future.done():
            future.cancel()
        return True

    async def get_events(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get recent events, newest first."""
        cursor = await self._db.execute(
            "SELECT * FROM events ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        result = [dict(row) for row in rows]
        for row in result:
            row["tags"] = json.loads(row.get("tags") or "[]")
            row["payload"] = json.loads(row["payload"])
        return result

    async def get_events_for_agent(
        self,
        agent_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get recent events that involve an agent as source, target, or owner."""
        cursor = await self._db.execute(
            """
            SELECT * FROM events
            WHERE agent_id = ? OR from_agent = ? OR to_agent = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (agent_id, agent_id, agent_id, limit),
        )
        rows = await cursor.fetchall()
        result = [dict(row) for row in rows]
        for row in result:
            row["tags"] = json.loads(row.get("tags") or "[]")
            row["payload"] = json.loads(row["payload"])
        return result

    async def get_latest_event_by_type(
        self,
        agent_id: str,
        event_type: str,
    ) -> dict[str, Any] | None:
        """Get the latest event of a specific type involving an agent."""
        cursor = await self._db.execute(
            """
            SELECT * FROM events
            WHERE (agent_id = ? OR from_agent = ? OR to_agent = ?)
              AND event_type = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (agent_id, agent_id, agent_id, event_type),
        )
        row = await cursor.fetchone()
        if row is None:
            return None

        result = dict(row)
        result["tags"] = json.loads(result.get("tags") or "[]")
        result["payload"] = json.loads(result["payload"])
        return result

    async def get_events_after(self, after_id: str, limit: int = 500) -> list[dict[str, Any]]:
        """Get events after a given event id, oldest first."""
        try:
            numeric_id = int(after_id)
        except (TypeError, ValueError):
            return []

        cursor = await self._db.execute(
            "SELECT * FROM events WHERE id > ? ORDER BY id ASC LIMIT ?",
            (numeric_id, limit),
        )
        rows = await cursor.fetchall()
        result = [dict(row) for row in rows]
        for row in result:
            row["tags"] = json.loads(row.get("tags") or "[]")
            row["payload"] = json.loads(row["payload"])
        return result


__all__ = ["EventStore"]
