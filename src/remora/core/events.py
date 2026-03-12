"""Events, bus, subscriptions, and event persistence."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path, PurePath
from typing import Any

from pydantic import BaseModel, Field


class Event(BaseModel):
    """Base event with automatic event_type tagging."""

    event_type: str = ""
    timestamp: float = Field(default_factory=time.time)
    correlation_id: str | None = None

    def model_post_init(self, __context: Any) -> None:
        if not self.event_type:
            self.event_type = type(self).__name__


# Agent lifecycle


class AgentStartEvent(Event):
    agent_id: str
    node_name: str = ""


class AgentCompleteEvent(Event):
    agent_id: str
    result_summary: str = ""


class AgentErrorEvent(Event):
    agent_id: str
    error: str


# Communication


class AgentMessageEvent(Event):
    from_agent: str
    to_agent: str
    content: str


class HumanChatEvent(Event):
    to_agent: str
    message: str


class AgentTextResponse(Event):
    agent_id: str
    content: str


# Code changes


class NodeDiscoveredEvent(Event):
    node_id: str
    node_type: str
    file_path: str
    name: str


class NodeRemovedEvent(Event):
    node_id: str
    node_type: str
    file_path: str
    name: str


class NodeChangedEvent(Event):
    node_id: str
    old_hash: str
    new_hash: str


class ContentChangedEvent(Event):
    path: str
    change_type: str = "modified"


class RewriteProposalEvent(Event):
    agent_id: str
    proposal_id: str
    file_path: str
    old_source: str
    new_source: str
    diff: str = ""


class CustomEvent(Event):
    payload: dict[str, Any] = Field(default_factory=dict)


# Tool execution


class ToolResultEvent(Event):
    agent_id: str
    tool_name: str
    result_summary: str = ""


EventHandler = Callable[[Event], Any]
_ANY_EVENT_KEY = "*"


class EventBus:
    """In-memory event dispatch with inheritance-aware subscriptions."""

    def __init__(self) -> None:
        self._handlers: dict[type[Event], list[EventHandler]] = {}
        self._all_handlers: list[EventHandler] = []

    async def emit(self, event: Event) -> None:
        """Emit an event to all specific and global handlers."""
        for event_type in type(event).__mro__:
            handlers = self._handlers.get(event_type, [])
            for handler in handlers:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
        for handler in self._all_handlers:
            result = handler(event)
            if asyncio.iscoroutine(result):
                await result

    def subscribe(self, event_type: type[Event], handler: EventHandler) -> None:
        """Register a handler for a specific event type."""
        self._handlers.setdefault(event_type, []).append(handler)

    def subscribe_all(self, handler: EventHandler) -> None:
        """Register a handler for all event types."""
        self._all_handlers.append(handler)

    def unsubscribe(self, handler: EventHandler) -> None:
        """Remove a handler from all subscriptions."""
        for handlers in self._handlers.values():
            if handler in handlers:
                handlers.remove(handler)
        if handler in self._all_handlers:
            self._all_handlers.remove(handler)

    @asynccontextmanager
    async def stream(self, *event_types: type[Event]) -> AsyncIterator[AsyncIterator[Event]]:
        """Yield an async iterator of events for optional filtered types."""
        queue: asyncio.Queue[Event] = asyncio.Queue()
        filter_set = set(event_types) if event_types else None

        def enqueue(event: Event) -> None:
            matches_filter = filter_set is None or any(
                isinstance(event, event_type) for event_type in filter_set
            )
            if matches_filter:
                queue.put_nowait(event)

        self.subscribe_all(enqueue)

        async def iterate() -> AsyncIterator[Event]:
            while True:
                yield await queue.get()

        try:
            yield iterate()
        finally:
            self.unsubscribe(enqueue)


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

    def __init__(self, connection: sqlite3.Connection, lock: asyncio.Lock):
        self._conn = connection
        self._lock = lock
        self._cache: dict[str, list[tuple[str, SubscriptionPattern]]] | None = None
        self._initialized = False

    async def initialize(self) -> None:
        """Create subscription storage tables."""
        if self._initialized:
            return

        def run() -> None:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id TEXT NOT NULL,
                    pattern_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_subs_agent ON subscriptions(agent_id)"
            )
            self._conn.commit()

        async with self._lock:
            await asyncio.to_thread(run)
        self._initialized = True

    async def register(self, agent_id: str, pattern: SubscriptionPattern) -> int:
        """Register a subscription and return its primary-key ID."""
        await self.initialize()

        def run() -> int:
            cursor = self._conn.execute(
                """
                INSERT INTO subscriptions (agent_id, pattern_json, created_at)
                VALUES (?, ?, ?)
                """,
                (agent_id, json.dumps(pattern.model_dump()), time.time()),
            )
            self._conn.commit()
            return int(cursor.lastrowid)

        async with self._lock:
            sub_id = await asyncio.to_thread(run)
        self._cache = None
        return sub_id

    async def unregister(self, subscription_id: int) -> bool:
        """Remove a subscription by ID. Returns True when a row was deleted."""
        await self.initialize()

        def run() -> bool:
            cursor = self._conn.execute(
                "DELETE FROM subscriptions WHERE id = ?",
                (subscription_id,),
            )
            self._conn.commit()
            return cursor.rowcount > 0

        async with self._lock:
            deleted = await asyncio.to_thread(run)
        if deleted:
            self._cache = None
        return deleted

    async def unregister_by_agent(self, agent_id: str) -> int:
        """Remove all subscriptions for an agent and return deleted count."""
        await self.initialize()

        def run() -> int:
            cursor = self._conn.execute(
                "DELETE FROM subscriptions WHERE agent_id = ?",
                (agent_id,),
            )
            self._conn.commit()
            return int(cursor.rowcount)

        async with self._lock:
            deleted = await asyncio.to_thread(run)
        if deleted > 0:
            self._cache = None
        return deleted

    async def get_matching_agents(self, event: Event) -> list[str]:
        """Resolve agent IDs whose patterns match the supplied event."""
        await self.initialize()
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

        def run() -> list[sqlite3.Row]:
            cursor = self._conn.execute(
                "SELECT agent_id, pattern_json FROM subscriptions ORDER BY id ASC"
            )
            return cursor.fetchall()

        async with self._lock:
            rows = await asyncio.to_thread(run)

        cache: dict[str, list[tuple[str, SubscriptionPattern]]] = {}
        for row in rows:
            pattern_data = json.loads(row["pattern_json"])
            pattern = SubscriptionPattern.model_validate(pattern_data)
            key_types = pattern.event_types or [_ANY_EVENT_KEY]
            for event_type in key_types:
                cache.setdefault(event_type, []).append((row["agent_id"], pattern))
        self._cache = cache


class EventStore:
    """Append-only SQLite event log with subscription trigger queue."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        subscriptions: SubscriptionRegistry | None = None,
        event_bus: EventBus | None = None,
        *,
        connection: sqlite3.Connection | None = None,
        lock: asyncio.Lock | None = None,
    ) -> None:
        if connection is None and db_path is None:
            raise ValueError("EventStore requires either db_path or connection")

        self._db_path = Path(db_path) if db_path is not None else None
        self._conn = connection
        self._owns_connection = connection is None
        self._lock = lock or asyncio.Lock()
        self._subscriptions = subscriptions
        self._event_bus = event_bus or EventBus()
        self._trigger_queue: asyncio.Queue[tuple[str, Event]] = asyncio.Queue()
        self._initialized = False

    @property
    def subscriptions(self) -> SubscriptionRegistry:
        """Access the subscription registry for registration and matching."""
        if self._subscriptions is None:
            raise RuntimeError("EventStore not initialized")
        return self._subscriptions

    @property
    def connection(self) -> sqlite3.Connection | None:
        """Expose the underlying sqlite connection."""
        return self._conn

    @property
    def lock(self) -> asyncio.Lock:
        """Expose the shared lock used for sqlite operations."""
        return self._lock

    async def initialize(self) -> None:
        """Create tables and configure connection pragmas."""
        if self._initialized:
            return

        if self._conn is None:
            assert self._db_path is not None
            self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row

        conn = self._conn

        def run() -> None:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute(
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
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_agent ON events(agent_id)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_correlation ON events(correlation_id)"
            )
            conn.commit()

        async with self._lock:
            await asyncio.to_thread(run)

        if self._subscriptions is None:
            self._subscriptions = SubscriptionRegistry(conn, self._lock)
        await self._subscriptions.initialize()
        self._initialized = True

    async def append(self, event: Event) -> int:
        """Append an event and fan-out to bus and matching subscription triggers."""
        await self.initialize()
        assert self._conn is not None

        payload = event.model_dump()
        summary = self._summarize(event)
        agent_id = getattr(event, "agent_id", None)
        from_agent = getattr(event, "from_agent", None)
        to_agent = getattr(event, "to_agent", None)

        def run() -> int:
            cursor = self._conn.execute(
                """
                INSERT INTO events (
                    event_type, agent_id, from_agent, to_agent,
                    correlation_id, timestamp, payload, summary
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_type,
                    agent_id,
                    from_agent,
                    to_agent,
                    event.correlation_id,
                    event.timestamp,
                    json.dumps(payload),
                    summary,
                ),
            )
            self._conn.commit()
            return int(cursor.lastrowid)

        async with self._lock:
            event_id = await asyncio.to_thread(run)

        await self._event_bus.emit(event)

        for target_agent_id in await self.subscriptions.get_matching_agents(event):
            self._trigger_queue.put_nowait((target_agent_id, event))

        return event_id

    async def get_events(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get recent events, newest first."""
        await self.initialize()
        assert self._conn is not None

        def run() -> list[dict[str, Any]]:
            cursor = self._conn.execute(
                "SELECT * FROM events ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            rows = [dict(row) for row in cursor.fetchall()]
            for row in rows:
                row["payload"] = json.loads(row["payload"])
            return rows

        async with self._lock:
            return await asyncio.to_thread(run)

    async def get_events_for_agent(
        self, agent_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Get recent events that involve an agent as source, target, or owner."""
        await self.initialize()
        assert self._conn is not None

        def run() -> list[dict[str, Any]]:
            cursor = self._conn.execute(
                """
                SELECT * FROM events
                WHERE agent_id = ? OR from_agent = ? OR to_agent = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (agent_id, agent_id, agent_id, limit),
            )
            rows = [dict(row) for row in cursor.fetchall()]
            for row in rows:
                row["payload"] = json.loads(row["payload"])
            return rows

        async with self._lock:
            return await asyncio.to_thread(run)

    async def get_triggers(self) -> AsyncIterator[tuple[str, Event]]:
        """Yield queued (agent_id, event) pairs forever."""
        while True:
            yield await self._trigger_queue.get()

    @staticmethod
    def _summarize(event: Event) -> str:
        if isinstance(event, AgentCompleteEvent | ToolResultEvent):
            return event.result_summary
        if isinstance(event, AgentMessageEvent | AgentTextResponse):
            return event.content
        if isinstance(event, HumanChatEvent):
            return event.message
        if isinstance(event, AgentErrorEvent):
            return event.error
        return ""


__all__ = [
    "Event",
    "AgentStartEvent",
    "AgentCompleteEvent",
    "AgentErrorEvent",
    "AgentMessageEvent",
    "HumanChatEvent",
    "AgentTextResponse",
    "NodeDiscoveredEvent",
    "NodeRemovedEvent",
    "NodeChangedEvent",
    "ContentChangedEvent",
    "RewriteProposalEvent",
    "CustomEvent",
    "ToolResultEvent",
    "EventBus",
    "EventHandler",
    "SubscriptionPattern",
    "SubscriptionRegistry",
    "EventStore",
]
