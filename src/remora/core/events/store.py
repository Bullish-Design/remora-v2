"""EventStore persistence and fan-out."""

from __future__ import annotations

import json
from typing import Any

from remora.core.db import AsyncDB
from remora.core.events.bus import EventBus
from remora.core.events.dispatcher import TriggerDispatcher
from remora.core.events.subscriptions import SubscriptionRegistry
from remora.core.events.types import Event


class EventStore:
    """Append-only SQLite event log with bus emission and trigger dispatch."""

    def __init__(
        self,
        db: AsyncDB,
        event_bus: EventBus | None = None,
        dispatcher: TriggerDispatcher | None = None,
    ) -> None:
        self._db = db
        self._event_bus = event_bus or EventBus()
        self._dispatcher = dispatcher or TriggerDispatcher(SubscriptionRegistry(db))

    @property
    def dispatcher(self) -> TriggerDispatcher:
        return self._dispatcher

    @property
    def subscriptions(self):  # noqa: ANN201
        return self._dispatcher.subscriptions

    async def create_tables(self) -> None:
        """Create event storage tables and indexes."""
        await self._db.execute_script(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                agent_id TEXT,
                from_agent TEXT,
                to_agent TEXT,
                correlation_id TEXT,
                timestamp REAL NOT NULL,
                payload TEXT NOT NULL,
                summary TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
            CREATE INDEX IF NOT EXISTS idx_events_agent ON events(agent_id);
            CREATE INDEX IF NOT EXISTS idx_events_correlation ON events(correlation_id);
            """
        )
        await self._dispatcher.subscriptions.create_tables()

    async def append(self, event: Event) -> int:
        """Append an event and fan-out to bus and matching subscription triggers."""
        envelope = event.to_envelope()
        payload = envelope["payload"]
        summary = event.summary()
        agent_id = payload.get("agent_id")
        from_agent = payload.get("from_agent")
        to_agent = payload.get("to_agent")

        event_id = await self._db.insert(
            """
            INSERT INTO events (
                event_type, agent_id, from_agent, to_agent,
                correlation_id, timestamp, payload, summary
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                envelope["event_type"],
                agent_id,
                from_agent,
                to_agent,
                envelope["correlation_id"],
                envelope["timestamp"],
                json.dumps(payload),
                summary,
            ),
        )

        await self._event_bus.emit(event)
        await self._dispatcher.dispatch(event)
        return event_id

    async def get_events(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get recent events, newest first."""
        rows = await self._db.fetch_all(
            "SELECT * FROM events ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        result = [dict(row) for row in rows]
        for row in result:
            row["payload"] = json.loads(row["payload"])
        return result

    async def get_events_for_agent(
        self,
        agent_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get recent events that involve an agent as source, target, or owner."""
        rows = await self._db.fetch_all(
            """
            SELECT * FROM events
            WHERE agent_id = ? OR from_agent = ? OR to_agent = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (agent_id, agent_id, agent_id, limit),
        )
        result = [dict(row) for row in rows]
        for row in result:
            row["payload"] = json.loads(row["payload"])
        return result

__all__ = ["EventStore"]
