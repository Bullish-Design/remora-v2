"""Event subscription pattern and registry."""

from __future__ import annotations

import json
import time
from pathlib import PurePath

import aiosqlite
from pydantic import BaseModel

from remora.core.events.types import Event

_ANY_EVENT_KEY = "*"


class SubscriptionPattern(BaseModel):
    """Pattern for selecting events. None fields are wildcards."""

    event_types: list[str] | None = None
    from_agents: list[str] | None = None
    to_agent: str | None = None
    path_glob: str | None = None

    def matches(self, event: Event) -> bool:
        """Return True when the event matches this pattern."""
        if self.event_types and event.event_type not in self.event_types:
            return False

        if self.from_agents:
            from_agent = getattr(event, "from_agent", None)
            if from_agent not in self.from_agents:
                return False

        if self.to_agent:
            to_agent = getattr(event, "to_agent", None)
            if to_agent != self.to_agent:
                return False

        if self.path_glob:
            path = getattr(event, "path", None) or getattr(event, "file_path", None)
            if path is None or not PurePath(path).match(self.path_glob):
                return False

        return True


class SubscriptionRegistry:
    """SQLite-backed subscription store with event_type-indexed in-memory cache."""

    def __init__(self, db: aiosqlite.Connection):
        self._db = db
        self._cache: dict[str, list[tuple[str, SubscriptionPattern]]] | None = None

    async def create_tables(self) -> None:
        """Create subscription storage tables."""
        await self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                pattern_json TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_subs_agent ON subscriptions(agent_id);
            """
        )
        await self._db.commit()

    async def register(self, agent_id: str, pattern: SubscriptionPattern) -> int:
        """Register a subscription and return its primary-key ID."""
        cursor = await self._db.execute(
            """
            INSERT INTO subscriptions (agent_id, pattern_json, created_at)
            VALUES (?, ?, ?)
            """,
            (agent_id, json.dumps(pattern.model_dump()), time.time()),
        )
        await self._db.commit()
        self._cache = None
        return int(cursor.lastrowid)

    async def unregister(self, subscription_id: int) -> bool:
        """Remove a subscription by ID. Returns True when a row was deleted."""
        cursor = await self._db.execute(
            "DELETE FROM subscriptions WHERE id = ?",
            (subscription_id,),
        )
        await self._db.commit()
        if cursor.rowcount > 0:
            self._cache = None
        return cursor.rowcount > 0

    async def unregister_by_agent(self, agent_id: str) -> int:
        """Remove all subscriptions for an agent and return deleted count."""
        cursor = await self._db.execute(
            "DELETE FROM subscriptions WHERE agent_id = ?",
            (agent_id,),
        )
        await self._db.commit()
        if cursor.rowcount > 0:
            self._cache = None
        return cursor.rowcount

    async def get_matching_agents(self, event: Event) -> list[str]:
        """Resolve agent IDs whose patterns match the supplied event."""
        if self._cache is None:
            await self._rebuild_cache()

        cache = self._cache or {}
        candidates = [*cache.get(_ANY_EVENT_KEY, []), *cache.get(event.event_type, [])]
        seen: set[str] = set()
        result: list[str] = []
        for agent_id, pattern in candidates:
            if agent_id in seen:
                continue
            if pattern.matches(event):
                seen.add(agent_id)
                result.append(agent_id)
        return result

    async def _rebuild_cache(self) -> None:
        """Load all subscriptions and rebuild event_type-indexed cache."""
        cursor = await self._db.execute(
            "SELECT agent_id, pattern_json FROM subscriptions ORDER BY id ASC"
        )
        rows = await cursor.fetchall()

        cache: dict[str, list[tuple[str, SubscriptionPattern]]] = {}
        for row in rows:
            pattern_data = json.loads(row["pattern_json"])
            pattern = SubscriptionPattern.model_validate(pattern_data)
            key_types = pattern.event_types or [_ANY_EVENT_KEY]
            for event_type in key_types:
                cache.setdefault(event_type, []).append((row["agent_id"], pattern))
        self._cache = cache


__all__ = ["SubscriptionPattern", "SubscriptionRegistry"]
