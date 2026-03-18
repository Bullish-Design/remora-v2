"""Event subscription pattern and registry."""

from __future__ import annotations

import json
import time
from pathlib import PurePath
from typing import Any
from pydantic import BaseModel

from remora.core.events.types import Event

_ANY_EVENT_KEY = "*"


class SubscriptionPattern(BaseModel):
    """Pattern for selecting events. None fields are wildcards."""

    event_types: list[str] | None = None
    from_agents: list[str] | None = None
    not_from_agents: list[str] | None = None
    to_agent: str | None = None
    path_glob: str | None = None
    tags: list[str] | None = None

    def matches(self, event: Event) -> bool:
        """Return True when the event matches this pattern."""
        if self.event_types and event.event_type not in self.event_types:
            return False

        if self.from_agents:
            from_agent = getattr(event, "from_agent", None)
            agent_id = getattr(event, "agent_id", None)
            if from_agent not in self.from_agents and agent_id not in self.from_agents:
                return False

        if self.not_from_agents:
            agent_id = getattr(event, "agent_id", None)
            from_agent = getattr(event, "from_agent", None)
            if agent_id in self.not_from_agents or from_agent in self.not_from_agents:
                return False

        if self.to_agent:
            to_agent = getattr(event, "to_agent", None)
            if to_agent != self.to_agent:
                return False

        if self.path_glob:
            path = getattr(event, "path", None) or getattr(event, "file_path", None)
            if path is None or not PurePath(path).match(self.path_glob):
                return False

        if self.tags:
            event_tags = set(getattr(event, "tags", ()))
            if not event_tags.intersection(self.tags):
                return False

        return True


class SubscriptionRegistry:
    """SQLite-backed subscription store with event_type-indexed in-memory cache."""

    def __init__(self, db: aiosqlite.Connection):
        self._db = db
        self._tx: "TransactionContext | None" = None
        self._cache: dict[str, list[tuple[int, str, SubscriptionPattern]]] | None = None

    def set_tx(self, tx: "TransactionContext") -> None:
        """Wire the TransactionContext after construction (breaks init cycle)."""
        self._tx = tx

    async def _maybe_commit(self) -> None:
        if self._tx is not None and self._tx.in_batch:
            return
        await self._db.commit()

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
        await self._maybe_commit()

    async def register(self, agent_id: str, pattern: SubscriptionPattern) -> int:
        """Register a subscription and return its primary-key ID."""
        cursor = await self._db.execute(
            """
            INSERT INTO subscriptions (agent_id, pattern_json, created_at)
            VALUES (?, ?, ?)
            """,
            (agent_id, json.dumps(pattern.model_dump()), time.time()),
        )
        await self._maybe_commit()
        sub_id = int(cursor.lastrowid)
        if self._cache is not None:
            self._cache_add(sub_id, agent_id, pattern)
        return sub_id

    async def unregister(self, subscription_id: int) -> bool:
        """Remove a subscription by ID. Returns True when a row was deleted."""
        cursor = await self._db.execute(
            "DELETE FROM subscriptions WHERE id = ?",
            (subscription_id,),
        )
        await self._maybe_commit()
        if cursor.rowcount > 0:
            self._cache_remove_subscription(subscription_id)
        return cursor.rowcount > 0

    async def unregister_by_agent(self, agent_id: str) -> int:
        """Remove all subscriptions for an agent and return deleted count."""
        cursor = await self._db.execute(
            "DELETE FROM subscriptions WHERE agent_id = ?",
            (agent_id,),
        )
        await self._maybe_commit()
        if cursor.rowcount > 0:
            self._cache_remove_agent(agent_id)
        return cursor.rowcount

    async def get_matching_agents(self, event: Event) -> list[str]:
        """Resolve agent IDs whose patterns match the supplied event."""
        if self._cache is None:
            await self._rebuild_cache()

        cache = self._cache or {}
        candidates = [*cache.get(_ANY_EVENT_KEY, []), *cache.get(event.event_type, [])]
        seen: set[str] = set()
        result: list[str] = []
        for _subscription_id, agent_id, pattern in candidates:
            if agent_id in seen:
                continue
            if pattern.matches(event):
                seen.add(agent_id)
                result.append(agent_id)
        return result

    async def _rebuild_cache(self) -> None:
        """Load all subscriptions and rebuild event_type-indexed cache."""
        cursor = await self._db.execute(
            "SELECT id, agent_id, pattern_json FROM subscriptions ORDER BY id ASC"
        )
        rows = await cursor.fetchall()

        cache: dict[str, list[tuple[int, str, SubscriptionPattern]]] = {}
        for row in rows:
            pattern_data = json.loads(row["pattern_json"])
            pattern = SubscriptionPattern.model_validate(pattern_data)
            key_types = pattern.event_types or [_ANY_EVENT_KEY]
            for event_type in key_types:
                cache.setdefault(event_type, []).append((int(row["id"]), row["agent_id"], pattern))
        self._cache = cache

    def _cache_add(self, sub_id: int, agent_id: str, pattern: SubscriptionPattern) -> None:
        if self._cache is None:
            return
        key_types = pattern.event_types or [_ANY_EVENT_KEY]
        for event_type in key_types:
            self._cache.setdefault(event_type, []).append((sub_id, agent_id, pattern))

    def _cache_remove_subscription(self, subscription_id: int) -> None:
        if self._cache is None:
            return
        for event_type, entries in list(self._cache.items()):
            filtered = [entry for entry in entries if entry[0] != subscription_id]
            if filtered:
                self._cache[event_type] = filtered
            else:
                self._cache.pop(event_type, None)

    def _cache_remove_agent(self, agent_id: str) -> None:
        if self._cache is None:
            return
        for event_type, entries in list(self._cache.items()):
            filtered = [entry for entry in entries if entry[1] != agent_id]
            if filtered:
                self._cache[event_type] = filtered
            else:
                self._cache.pop(event_type, None)


__all__ = ["SubscriptionPattern", "SubscriptionRegistry"]
