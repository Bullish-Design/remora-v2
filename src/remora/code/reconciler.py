"""File reconciler that keeps discovered nodes in sync with source files."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import yaml

from remora.code.directories import DirectoryManager
from remora.code.discovery import discover
from remora.code.languages import LanguageRegistry
from remora.code.paths import resolve_query_paths
from remora.code.virtual_agents import VirtualAgentManager
from remora.code.watcher import FileWatcher
from remora.core.config import Config, resolve_bundle_dirs, resolve_bundle_search_paths
from remora.core.events import (
    ContentChangedEvent,
    Event,
    EventBus,
    EventStore,
    NodeChangedEvent,
    NodeDiscoveredEvent,
    NodeRemovedEvent,
    SubscriptionPattern,
)
from remora.core.graph import NodeStore
from remora.core.node import Node
from remora.core.search import SearchServiceProtocol
from remora.core.types import EventType, NodeType, NodeStatus
from remora.core.workspace import CairnWorkspaceService

logger = logging.getLogger(__name__)


class FileReconciler:
    """Incremental file reconciler with add/change/delete handling."""

    def __init__(
        self,
        config: Config,
        node_store: NodeStore,
        event_store: EventStore,
        workspace_service: CairnWorkspaceService,
        project_root: Path,
        language_registry: LanguageRegistry,
        *,
        search_service: SearchServiceProtocol | None = None,
        tx: Any | None = None,
    ):
        self._config = config
        self._node_store = node_store
        self._event_store = event_store
        self._workspace_service = workspace_service
        self._project_root = project_root.resolve()
        self._language_registry = language_registry
        self._search_service = search_service
        self._tx = tx
        self._bundle_search_paths = resolve_bundle_search_paths(config, self._project_root)
        self._file_state: dict[str, tuple[int, set[str]]] = {}
        self._file_locks: dict[str, asyncio.Lock] = {}
        self._file_lock_generations: dict[str, int] = {}
        self._reconcile_generation = 0
        # Re-copy bundle templates once after startup so existing agent workspaces
        # pick up updated tool scripts.
        self._bundles_bootstrapped = False

        self._watcher = FileWatcher(config, project_root)
        self._directory_manager = DirectoryManager(
            config,
            node_store,
            event_store,
            workspace_service,
            project_root,
            remove_node=self._remove_node,
            register_subscriptions=self._register_subscriptions,
            provision_bundle=self._provision_bundle,
        )
        self._virtual_agent_manager = VirtualAgentManager(
            config,
            node_store,
            event_store,
            remove_node=self._remove_node,
            register_subscriptions=self._register_subscriptions,
            provision_bundle=self._provision_bundle,
        )

    async def full_scan(self) -> list[Node]:
        """Perform a full startup scan and return current graph nodes."""
        await self.reconcile_cycle()
        return await self._node_store.list_nodes()

    async def reconcile_cycle(self) -> None:
        """Run one reconciliation cycle over changed/new/deleted files."""
        generation = self._next_reconcile_generation()
        await self._virtual_agent_manager.sync()
        current_mtimes = self._watcher.collect_file_mtimes()
        sync_existing_bundles = not self._bundles_bootstrapped
        await self._directory_manager.materialize(
            set(current_mtimes.keys()),
            sync_existing_bundles=sync_existing_bundles,
        )

        changed_paths = [
            file_path
            for file_path, mtime_ns in current_mtimes.items()
            if file_path not in self._file_state or self._file_state[file_path][0] != mtime_ns
        ]
        deleted_paths = sorted(set(self._file_state) - set(current_mtimes))

        for file_path in sorted(changed_paths):
            await self._reconcile_file(
                file_path,
                current_mtimes[file_path],
                generation=generation,
                sync_existing_bundles=sync_existing_bundles,
            )

        for file_path in deleted_paths:
            _mtime, node_ids = self._file_state[file_path]
            for node_id in sorted(node_ids):
                await self._remove_node(node_id)
            await self._deindex_file_for_search(file_path)
            self._file_state.pop(file_path, None)

        self._bundles_bootstrapped = True
        self._evict_stale_file_locks(generation)

    async def run_forever(self) -> None:
        """Continuously reconcile changed files using watchfiles."""
        await self._watcher.watch(self._handle_watch_changes)

    def stop(self) -> None:
        self._watcher.stop()

    @property
    def stop_task(self) -> asyncio.Task | None:
        """Expose the current stop-event task for observers."""
        return self._watcher.stop_task

    async def start(self, event_bus: EventBus) -> None:
        """Subscribe to content change events for immediate reconciliation."""
        event_bus.subscribe(ContentChangedEvent, self._on_content_changed)

    async def _handle_watch_changes(self, changed_files: set[str]) -> None:
        """Process one watchfiles batch with isolated error handling."""
        generation = self._next_reconcile_generation()
        try:
            for file_path in sorted(changed_files):
                path = Path(file_path)
                if path.exists() and path.is_file():
                    mtime = path.stat().st_mtime_ns
                    await self._reconcile_file(str(path), mtime, generation=generation)
                elif str(path) in self._file_state:
                    _mtime, node_ids = self._file_state[str(path)]
                    for node_id in sorted(node_ids):
                        await self._remove_node(node_id)
                    await self._deindex_file_for_search(str(path))
                    self._file_state.pop(str(path), None)
            self._evict_stale_file_locks(generation)
        # Error boundary: one failed watch batch must not stop file watching.
        except Exception:  # noqa: BLE001 - isolate one watch batch failure
            logger.exception("Watch-triggered reconcile failed")

    async def _reconcile_file(
        self,
        file_path: str,
        mtime_ns: int,
        *,
        generation: int | None = None,
        sync_existing_bundles: bool = False,
    ) -> None:
        lock_generation = (
            generation if generation is not None else self._next_reconcile_generation()
        )
        async with self._file_lock(file_path, lock_generation):
            await self._do_reconcile_file(
                file_path,
                mtime_ns,
                sync_existing_bundles=sync_existing_bundles,
            )
        if generation is None:
            self._evict_stale_file_locks(lock_generation)

    async def _do_reconcile_file(
        self,
        file_path: str,
        mtime_ns: int,
        *,
        sync_existing_bundles: bool = False,
    ) -> None:
        discovered = discover(
            [Path(file_path)],
            language_map=self._config.behavior.language_map,
            language_registry=self._language_registry,
            query_paths=resolve_query_paths(self._config, self._project_root),
            ignore_patterns=self._config.project.workspace_ignore_patterns,
            languages=(
                list(self._config.project.discovery_languages)
                if self._config.project.discovery_languages
                else None
            ),
        )
        old_ids = self._file_state.get(file_path, (0, set()))[1]
        new_ids = {node.node_id for node in discovered}

        existing_nodes = await self._node_store.get_nodes_by_ids(sorted(new_ids))
        existing_by_id = {node.node_id: node for node in existing_nodes}
        old_hashes = {node.node_id: node.source_hash for node in existing_nodes}
        projected: list[Node] = []
        for node in discovered:
            existing = existing_by_id.get(node.node_id)

            if existing is not None and existing.source_hash == node.source_hash:
                if sync_existing_bundles:
                    template_dirs = self._resolve_bundle_template_dirs("system")
                    mapped_bundle = self._config.resolve_bundle(node.node_type, node.name)
                    role = mapped_bundle or existing.role
                    if role:
                        template_dirs.extend(self._resolve_bundle_template_dirs(role))
                    await self._workspace_service.provision_bundle(node.node_id, template_dirs)
                projected.append(existing)
                continue

            mapped_bundle = self._config.resolve_bundle(node.node_type, node.name)
            node.status = existing.status if existing is not None else NodeStatus.IDLE
            node.role = (
                mapped_bundle
                if mapped_bundle is not None
                else (existing.role if existing is not None else None)
            )
            await self._node_store.upsert_node(node)

            if existing is None:
                template_dirs = self._resolve_bundle_template_dirs("system")
                if mapped_bundle:
                    template_dirs.extend(self._resolve_bundle_template_dirs(mapped_bundle))
                await self._workspace_service.provision_bundle(node.node_id, template_dirs)

            projected.append(node)

        if self._tx is not None:
            async with self._tx.batch():
                dir_node_id = self._directory_manager.directory_id_for_file(file_path)
                for node in projected:
                    if node.parent_id is None:
                        node.parent_id = dir_node_id
                        await self._node_store.upsert_node(node)
                    if node.parent_id is not None:
                        await self._node_store.add_edge(node.parent_id, node.node_id, "contains")

                projected_by_id = {node.node_id: node for node in projected}

                additions = sorted(new_ids - old_ids)
                removals = sorted(old_ids - new_ids)
                updates = sorted(new_ids & old_ids)

                for node_id in additions:
                    node = projected_by_id[node_id]
                    await self._register_subscriptions(node)
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
                    new_hash = node.source_hash
                    if old_hash is not None and old_hash != new_hash:
                        await self._register_subscriptions(node)
                        await self._event_store.append(
                            NodeChangedEvent(
                                node_id=node_id,
                                old_hash=old_hash,
                                new_hash=new_hash,
                                file_path=node.file_path,
                            )
                        )

                for node_id in removals:
                    await self._remove_node(node_id)

        self._file_state[file_path] = (mtime_ns, new_ids)
        await self._index_file_for_search(file_path)

    async def _index_file_for_search(self, file_path: str) -> None:
        """Index a file for semantic search, logging failures without raising."""
        if self._search_service is None or not self._search_service.available:
            return
        try:
            await self._search_service.index_file(file_path)
        # Error boundary: indexing failures should not break reconcile flow.
        except Exception:  # noqa: BLE001
            logger.debug("Search indexing failed for %s", file_path, exc_info=True)

    async def _deindex_file_for_search(self, file_path: str) -> None:
        """Remove a file from semantic search, logging failures without raising."""
        if self._search_service is None or not self._search_service.available:
            return
        try:
            await self._search_service.delete_source(file_path)
        # Error boundary: deindex failures should not break reconcile flow.
        except Exception:  # noqa: BLE001
            logger.debug("Search deindexing failed for %s", file_path, exc_info=True)

    def _file_lock(self, file_path: str, generation: int) -> asyncio.Lock:
        lock = self._file_locks.get(file_path)
        if lock is None:
            lock = asyncio.Lock()
            self._file_locks[file_path] = lock
        self._file_lock_generations[file_path] = generation
        return lock

    def _next_reconcile_generation(self) -> int:
        self._reconcile_generation += 1
        return self._reconcile_generation

    def _evict_stale_file_locks(self, generation: int) -> None:
        stale_paths = [
            file_path
            for file_path, lock_generation in self._file_lock_generations.items()
            if lock_generation < generation
            and file_path in self._file_locks
            and not self._file_locks[file_path].locked()
        ]
        for file_path in stale_paths:
            self._file_locks.pop(file_path, None)
            self._file_lock_generations.pop(file_path, None)

    async def _remove_node(self, node_id: str) -> None:
        node = await self._node_store.get_node(node_id)
        if node is None:
            await self._event_store.subscriptions.unregister_by_agent(node_id)
            return

        await self._event_store.subscriptions.unregister_by_agent(node_id)
        await self._node_store.delete_node(node_id)
        await self._event_store.append(
            NodeRemovedEvent(
                node_id=node.node_id,
                node_type=node.node_type,
                file_path=node.file_path,
                name=node.name,
            )
        )

    async def _register_subscriptions(
        self,
        node: Node,
        *,
        virtual_subscriptions: tuple[SubscriptionPattern, ...] = (),
    ) -> None:
        await self._event_store.subscriptions.unregister_by_agent(node.node_id)
        await self._event_store.subscriptions.register(
            node.node_id,
            SubscriptionPattern(to_agent=node.node_id),
        )

        if node.node_type == NodeType.VIRTUAL:
            for pattern in virtual_subscriptions:
                await self._event_store.subscriptions.register(node.node_id, pattern)
            return

        if node.node_type == NodeType.DIRECTORY:
            subtree_glob = "**" if node.file_path == "." else f"**/{node.file_path}/**"
            await self._event_store.subscriptions.register(
                node.node_id,
                SubscriptionPattern(
                    event_types=[EventType.NODE_CHANGED],
                    path_glob=subtree_glob,
                ),
            )
            await self._event_store.subscriptions.register(
                node.node_id,
                SubscriptionPattern(
                    event_types=[EventType.CONTENT_CHANGED],
                    path_glob=subtree_glob,
                ),
            )
            return

        if self._workspace_service.has_workspace(node.node_id):
            workspace = await self._workspace_service.get_agent_workspace(node.node_id)
            self_reflect_config = await workspace.kv_get("_system/self_reflect")
            if isinstance(self_reflect_config, dict) and self_reflect_config.get("enabled"):
                await self._event_store.subscriptions.register(
                    node.node_id,
                    SubscriptionPattern(
                        event_types=[EventType.AGENT_COMPLETE],
                        from_agents=[node.node_id],
                        tags=["primary"],
                    ),
                )

        await self._event_store.subscriptions.register(
            node.node_id,
            SubscriptionPattern(
                event_types=[EventType.CONTENT_CHANGED],
                path_glob=node.file_path,
            ),
        )

    def _resolve_bundle_template_dirs(self, bundle_name: str) -> list[Path]:
        """Resolve a bundle name to template directories using search path."""
        return resolve_bundle_dirs(bundle_name, self._bundle_search_paths)

    async def _provision_bundle(self, node_id: str, role: str | None) -> None:
        template_dirs = self._resolve_bundle_template_dirs("system")
        if role:
            template_dirs.extend(self._resolve_bundle_template_dirs(role))
        await self._workspace_service.provision_bundle(node_id, template_dirs)

        workspace = await self._workspace_service.get_agent_workspace(node_id)
        try:
            text = await workspace.read("_bundle/bundle.yaml")
            loaded = yaml.safe_load(text) or {}
            self_reflect = loaded.get("self_reflect") if isinstance(loaded, dict) else None
            if isinstance(self_reflect, dict) and self_reflect.get("enabled"):
                await workspace.kv_set("_system/self_reflect", self_reflect)
            else:
                await workspace.kv_set("_system/self_reflect", None)
        # Error boundary: bundle metadata sync is best-effort during provisioning.
        except Exception:  # noqa: BLE001 - best effort bundle metadata sync
            logger.debug("Failed to sync self_reflect config for %s", node_id, exc_info=True)

    async def _on_content_changed(self, event: Event) -> None:
        """Immediately reconcile a file reported changed by upstream systems."""
        if not isinstance(event, ContentChangedEvent):
            return
        file_path = event.path
        path = Path(file_path)
        if path.exists() and path.is_file():
            try:
                mtime = path.stat().st_mtime_ns
                generation = self._next_reconcile_generation()
                await self._reconcile_file(str(path), mtime, generation=generation)
                self._evict_stale_file_locks(generation)
            # Error boundary: event-triggered reconcile failures are isolated per event.
            except Exception:  # noqa: BLE001 - isolate event failures
                logger.exception("Event-triggered reconcile failed for %s", file_path)


__all__ = ["FileReconciler"]
