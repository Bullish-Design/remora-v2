"""Event subscription pattern and registry."""

from __future__ import annotations

import json
import time
from pathlib import PurePath

from pydantic import BaseModel

from remora.core.db import AsyncDB
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
            path = getattr(event, "path", None)
            if path is None or not PurePath(path).match(self.path_glob):
                return False

        return True


class SubscriptionRegistry:
    """SQLite-backed subscription store with event_type-indexed in-memory cache."""

    def __init__(self, db: AsyncDB):
        self._db = db
        self._cache: dict[str, list[tuple[str, SubscriptionPattern]]] | None = None

    @property
    def db(self) -> AsyncDB:
        return self._db

    async def create_tables(self) -> None:
        """Create subscription storage tables."""
        await self._db.execute_script(
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

    async def initialize(self) -> None:
        """Backward-compatible alias for create_tables."""
        await self.create_tables()

    async def register(self, agent_id: str, pattern: SubscriptionPattern) -> int:
        """Register a subscription and return its primary-key ID."""
        sub_id = await self._db.insert(
            """
            INSERT INTO subscriptions (agent_id, pattern_json, created_at)
            VALUES (?, ?, ?)
            """,
            (agent_id, json.dumps(pattern.model_dump()), time.time()),
        )
        self._cache = None
        return sub_id

    async def unregister(self, subscription_id: int) -> bool:
        """Remove a subscription by ID. Returns True when a row was deleted."""
        deleted = await self._db.delete(
            "DELETE FROM subscriptions WHERE id = ?",
            (subscription_id,),
        )
        if deleted:
            self._cache = None
        return deleted > 0

    async def unregister_by_agent(self, agent_id: str) -> int:
        """Remove all subscriptions for an agent and return deleted count."""
        deleted = await self._db.delete(
            "DELETE FROM subscriptions WHERE agent_id = ?",
            (agent_id,),
        )
        if deleted > 0:
            self._cache = None
        return deleted

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
        rows = await self._db.fetch_all(
            "SELECT agent_id, pattern_json FROM subscriptions ORDER BY id ASC"
        )

        cache: dict[str, list[tuple[str, SubscriptionPattern]]] = {}
        for row in rows:
            pattern_data = json.loads(row["pattern_json"])
            pattern = SubscriptionPattern.model_validate(pattern_data)
            key_types = pattern.event_types or [_ANY_EVENT_KEY]
            for event_type in key_types:
                cache.setdefault(event_type, []).append((row["agent_id"], pattern))
        self._cache = cache


__all__ = ["SubscriptionPattern", "SubscriptionRegistry"]
