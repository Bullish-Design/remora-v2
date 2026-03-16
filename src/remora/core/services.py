"""Runtime service container for dependency injection."""

from __future__ import annotations

import asyncio
from pathlib import Path

import aiosqlite

from remora.code.languages import LanguageRegistry
from remora.code.reconciler import FileReconciler
from remora.core.config import Config
from remora.core.events import EventBus, EventStore, SubscriptionRegistry, TriggerDispatcher
from remora.core.graph import NodeStore
from remora.core.metrics import Metrics
from remora.core.runner import ActorPool
from remora.core.search import SearchService
from remora.core.workspace import CairnWorkspaceService


class RuntimeServices:
    """Central container holding runtime services."""

    def __init__(self, config: Config, project_root: Path, db: aiosqlite.Connection):
        self.config = config
        self.project_root = project_root.resolve()
        self.db = db

        self.metrics = Metrics()
        self.node_store = NodeStore(db)

        self.event_bus = EventBus()
        self.subscriptions = SubscriptionRegistry(db)
        self.dispatcher = TriggerDispatcher(self.subscriptions)
        self.event_store = EventStore(
            db=db,
            event_bus=self.event_bus,
            dispatcher=self.dispatcher,
            metrics=self.metrics,
        )

        self.workspace_service = CairnWorkspaceService(config, project_root, metrics=self.metrics)
        self.language_registry = LanguageRegistry()

        self.search_service: SearchService | None = None
        self.reconciler: FileReconciler | None = None
        self.runner: ActorPool | None = None

    async def initialize(self) -> None:
        """Create tables and initialize services."""
        await self.node_store.create_tables()
        await self.subscriptions.create_tables()
        await self.event_store.create_tables()
        await self.workspace_service.initialize()

        if self.config.search.enabled:
            self.search_service = SearchService(self.config.search, self.project_root)
            await self.search_service.initialize()

        self.reconciler = FileReconciler(
            self.config,
            self.node_store,
            self.event_store,
            self.workspace_service,
            self.project_root,
            search_service=self.search_service,
        )
        await self.reconciler.start(self.event_bus)

        self.runner = ActorPool(
            self.event_store,
            self.node_store,
            self.workspace_service,
            self.config,
            dispatcher=self.dispatcher,
            metrics=self.metrics,
            search_service=self.search_service,
        )

    async def close(self) -> None:
        """Shut down all services."""
        if self.reconciler is not None:
            self.reconciler.stop()
            stop_task = self.reconciler.stop_task
            if stop_task is not None:
                try:
                    await stop_task
                except asyncio.CancelledError:
                    pass
        if self.runner is not None:
            await self.runner.stop_and_wait()
        if self.search_service is not None:
            await self.search_service.close()
        await self.workspace_service.close()
        await self.db.close()


__all__ = ["RuntimeServices"]
