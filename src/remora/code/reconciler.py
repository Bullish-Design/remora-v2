"""File reconciler that keeps discovered nodes in sync with source files."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path

from remora.code.discovery import discover
from remora.code.paths import resolve_discovery_paths, resolve_query_paths, walk_source_files
from remora.code.projections import project_nodes
from remora.core.config import Config
from remora.core.events import (
    ContentChangedEvent,
    EventBus,
    EventStore,
    NodeChangedEvent,
    NodeDiscoveredEvent,
    NodeRemovedEvent,
    SubscriptionPattern,
)
from remora.core.graph import AgentStore, NodeStore
from remora.core.node import CodeNode
from remora.core.workspace import CairnWorkspaceService

logger = logging.getLogger(__name__)


class FileReconciler:
    """Incremental file reconciler with add/change/delete handling."""

    def __init__(
        self,
        config: Config,
        node_store: NodeStore,
        agent_store: AgentStore,
        event_store: EventStore,
        workspace_service: CairnWorkspaceService,
        project_root: Path,
    ):
        self._config = config
        self._node_store = node_store
        self._agent_store = agent_store
        self._event_store = event_store
        self._workspace_service = workspace_service
        self._project_root = project_root.resolve()
        self._file_state: dict[str, tuple[int, set[str]]] = {}
        self._running = False

    async def full_scan(self) -> list[CodeNode]:
        """Perform a full startup scan and return current graph nodes."""
        await self.reconcile_cycle()
        return await self._node_store.list_nodes()

    async def reconcile_cycle(self) -> None:
        """Run one reconciliation cycle over changed/new/deleted files."""
        current_mtimes = self._collect_file_mtimes()
        changed_paths = [
            file_path
            for file_path, mtime_ns in current_mtimes.items()
            if file_path not in self._file_state or self._file_state[file_path][0] != mtime_ns
        ]
        deleted_paths = sorted(set(self._file_state) - set(current_mtimes))

        for file_path in sorted(changed_paths):
            await self._reconcile_file(file_path, current_mtimes[file_path])

        for file_path in deleted_paths:
            _mtime, node_ids = self._file_state[file_path]
            for node_id in sorted(node_ids):
                await self._remove_node(node_id)
            self._file_state.pop(file_path, None)

    async def run_forever(self) -> None:
        """Continuously reconcile changed files using watchfiles."""
        self._running = True
        try:
            await self._run_watching()
        finally:
            self._running = False

    def stop(self) -> None:
        self._running = False

    async def start(self, event_bus: EventBus) -> None:
        """Subscribe to content change events for immediate reconciliation."""
        event_bus.subscribe(ContentChangedEvent, self._on_content_changed)

    async def _run_watching(self) -> None:
        """Use filesystem events for immediate change detection."""
        import watchfiles

        paths_to_watch = resolve_discovery_paths(self._config, self._project_root)
        watch_paths = [str(path) for path in paths_to_watch if path.exists()]
        if not watch_paths:
            raise RuntimeError(
                "No discovery paths exist to watch. "
                "Create configured discovery paths before starting reconciler."
            )

        async for changes in watchfiles.awatch(*watch_paths, stop_event=self._stop_event()):
            if not self._running:
                break
            changed_files = {str(Path(path)) for _change_type, path in changes}
            try:
                for file_path in sorted(changed_files):
                    p = Path(file_path)
                    if p.exists() and p.is_file():
                        mtime = p.stat().st_mtime_ns
                        await self._reconcile_file(str(p), mtime)
                    elif str(p) in self._file_state:
                        _mtime, node_ids = self._file_state[str(p)]
                        for node_id in sorted(node_ids):
                            await self._remove_node(node_id)
                        self._file_state.pop(str(p), None)
            except Exception:  # noqa: BLE001 - isolate one watch batch failure
                logger.exception("Watch-triggered reconcile failed")

    def _stop_event(self):  # noqa: ANN201
        """Create a threading event set when reconciler is stopped."""
        import threading

        event = threading.Event()

        async def _checker() -> None:
            while self._running:
                await asyncio.sleep(0.5)
            event.set()

        asyncio.create_task(_checker())
        return event

    def _collect_file_mtimes(self) -> dict[str, int]:
        mtimes: dict[str, int] = {}
        discovery_paths = resolve_discovery_paths(self._config, self._project_root)
        for file_path in walk_source_files(
            discovery_paths,
            self._config.workspace_ignore_patterns,
        ):
            try:
                mtimes[str(file_path)] = file_path.stat().st_mtime_ns
            except FileNotFoundError:
                continue
        return mtimes

    async def _reconcile_file(self, file_path: str, mtime_ns: int) -> None:
        discovered = discover(
            [Path(file_path)],
            language_map=self._config.language_map,
            query_paths=resolve_query_paths(self._config, self._project_root),
            ignore_patterns=self._config.workspace_ignore_patterns,
            languages=(
                list(self._config.discovery_languages)
                if self._config.discovery_languages
                else None
            ),
        )
        old_ids = self._file_state.get(file_path, (0, set()))[1]
        new_ids = {node.node_id for node in discovered}

        old_hashes: dict[str, str] = {}
        for node_id in new_ids:
            existing = await self._node_store.get_node(node_id)
            if existing is not None:
                old_hashes[node_id] = existing.source_hash

        projected = await project_nodes(
            discovered,
            self._node_store,
            self._workspace_service,
            self._config,
        )
        projected_by_id = {node.node_id: node for node in projected}

        additions = sorted(new_ids - old_ids)
        removals = sorted(old_ids - new_ids)
        updates = sorted(new_ids & old_ids)

        for node_id in additions:
            node = projected_by_id[node_id]
            await self._register_subscriptions(node)
            await self._ensure_agent(node)
            await self._event_store.append(
                NodeDiscoveredEvent(
                    node_id=node.node_id,
                    node_type=node.node_type,
                    file_path=node.file_path,
                    name=node.name,
                )
            )

        for node_id in updates:
            node = projected_by_id[node_id]
            old_hash = old_hashes.get(node_id)
            new_hash = hashlib.sha256(node.source_code.encode("utf-8")).hexdigest()
            if old_hash is not None and old_hash != new_hash:
                await self._register_subscriptions(node)
                await self._ensure_agent(node)
                await self._event_store.append(
                    NodeChangedEvent(
                        node_id=node_id,
                        old_hash=old_hash,
                        new_hash=new_hash,
                    )
                )

        for node_id in removals:
            await self._remove_node(node_id)

        self._file_state[file_path] = (mtime_ns, new_ids)

    async def _remove_node(self, node_id: str) -> None:
        node = await self._node_store.get_node(node_id)
        if node is None:
            await self._event_store.subscriptions.unregister_by_agent(node_id)
            return

        await self._event_store.subscriptions.unregister_by_agent(node_id)
        await self._agent_store.delete_agent(node_id)
        await self._node_store.delete_node(node_id)
        await self._event_store.append(
            NodeRemovedEvent(
                node_id=node.node_id,
                node_type=node.node_type,
                file_path=node.file_path,
                name=node.name,
            )
        )

    async def _register_subscriptions(self, node: CodeNode) -> None:
        await self._event_store.subscriptions.unregister_by_agent(node.node_id)
        await self._event_store.subscriptions.register(
            node.node_id,
            SubscriptionPattern(to_agent=node.node_id),
        )
        await self._event_store.subscriptions.register(
            node.node_id,
            SubscriptionPattern(
                event_types=["ContentChangedEvent"],
                path_glob=node.file_path,
            ),
        )

    async def _ensure_agent(self, node: CodeNode) -> None:
        if await self._agent_store.get_agent(node.node_id) is None:
            await self._agent_store.upsert_agent(node.to_agent())

    async def _on_content_changed(self, event: ContentChangedEvent) -> None:
        """Immediately reconcile a file reported changed by upstream systems."""
        file_path = event.path
        p = Path(file_path)
        if p.exists() and p.is_file():
            try:
                mtime = p.stat().st_mtime_ns
                await self._reconcile_file(str(p), mtime)
            except Exception:  # noqa: BLE001 - isolate event failures
                logger.exception("Event-triggered reconcile failed for %s", file_path)
__all__ = ["FileReconciler"]
