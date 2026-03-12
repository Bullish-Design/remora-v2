"""Runtime service container for dependency injection."""

from __future__ import annotations

from pathlib import Path

from remora.code.languages import LanguageRegistry
from remora.code.reconciler import FileReconciler
from remora.core.config import Config
from remora.core.db import AsyncDB
from remora.core.events import EventBus, EventStore, SubscriptionRegistry, TriggerDispatcher
from remora.core.graph import AgentStore, NodeStore
from remora.core.runner import AgentRunner
from remora.core.workspace import CairnWorkspaceService


class RuntimeServices:
    """Central container holding runtime services."""

    def __init__(self, config: Config, project_root: Path, db: AsyncDB):
        self.config = config
        self.project_root = project_root.resolve()
        self.db = db

        self.node_store = NodeStore(db)
        self.agent_store = AgentStore(db)

        self.event_bus = EventBus()
        self.subscriptions = SubscriptionRegistry(db)
        self.dispatcher = TriggerDispatcher(self.subscriptions)
        self.event_store = EventStore(
            db=db,
            event_bus=self.event_bus,
            dispatcher=self.dispatcher,
        )

        self.workspace_service = CairnWorkspaceService(config, project_root)
        self.language_registry = LanguageRegistry()

        self.reconciler: FileReconciler | None = None
        self.runner: AgentRunner | None = None

    async def initialize(self) -> None:
        """Create tables and initialize services."""
        await self.node_store.create_tables()
        await self.agent_store.create_tables()
        await self.subscriptions.create_tables()
        await self.event_store.create_tables()
        await self.workspace_service.initialize()

        self.reconciler = FileReconciler(
            self.config,
            self.node_store,
            self.agent_store,
            self.event_store,
            self.workspace_service,
            self.project_root,
        )
        await self.reconciler.start(self.event_bus)

        self.runner = AgentRunner(
            self.event_store,
            self.node_store,
            self.agent_store,
            self.workspace_service,
            self.config,
            dispatcher=self.dispatcher,
        )

    async def close(self) -> None:
        """Shut down all services."""
        if self.reconciler is not None:
            self.reconciler.stop()
        if self.runner is not None:
            await self.runner.stop_and_wait()
        await self.workspace_service.close()
        self.db.close()


__all__ = ["RuntimeServices"]
