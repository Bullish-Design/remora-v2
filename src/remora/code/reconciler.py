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
from remora.core.types import NodeType
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
        # Re-register directory subscriptions once after startup so older
        # subscription shapes are migrated without requiring a DB reset.
        self._subscriptions_bootstrapped = False
        # Re-copy bundle templates once after startup so existing agent workspaces
        # pick up updated tool scripts.
        self._bundles_bootstrapped = False

    async def full_scan(self) -> list[CodeNode]:
        """Perform a full startup scan and return current graph nodes."""
        await self.reconcile_cycle()
        return await self._node_store.list_nodes()

    async def reconcile_cycle(self) -> None:
        """Run one reconciliation cycle over changed/new/deleted files."""
        current_mtimes = self._collect_file_mtimes()
        sync_existing_bundles = not self._bundles_bootstrapped
        await self._materialize_directories(
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
                sync_existing_bundles=sync_existing_bundles,
            )

        for file_path in deleted_paths:
            _mtime, node_ids = self._file_state[file_path]
            for node_id in sorted(node_ids):
                await self._remove_node(node_id)
            self._file_state.pop(file_path, None)
        self._bundles_bootstrapped = True

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

    async def _materialize_directories(
        self,
        file_paths: set[str],
        *,
        sync_existing_bundles: bool,
    ) -> None:
        """Derive directory nodes from the set of discovered file paths."""
        file_rel_paths = {self._relative_file_path(path) for path in file_paths}
        dir_paths: set[str] = {"."}

        for rel_file_path in file_rel_paths:
            parent = Path(rel_file_path).parent
            current = parent
            while True:
                dir_id = self._normalize_dir_id(current)
                dir_paths.add(dir_id)
                if dir_id == ".":
                    break
                current = current.parent

        children_by_dir: dict[str, list[str]] = {dir_id: [] for dir_id in dir_paths}
        for dir_id in dir_paths:
            if dir_id == ".":
                continue
            parent_id = self._parent_dir_id(dir_id)
            children_by_dir.setdefault(parent_id, []).append(dir_id)
        for rel_file_path in file_rel_paths:
            parent_id = self._parent_dir_id(rel_file_path)
            children_by_dir.setdefault(parent_id, []).append(rel_file_path)

        existing_dirs = await self._node_store.list_nodes(node_type=NodeType.DIRECTORY)
        existing_by_id = {node.node_id: node for node in existing_dirs}
        desired_ids = set(dir_paths)

        stale_ids = sorted(
            set(existing_by_id) - desired_ids,
            key=lambda node_id: node_id.count("/"),
            reverse=True,
        )
        for node_id in stale_ids:
            await self._remove_node(node_id)

        for dir_id in sorted(dir_paths):
            parent_id = None if dir_id == "." else self._parent_dir_id(dir_id)
            name = "." if dir_id == "." else Path(dir_id).name
            children = sorted(children_by_dir.get(dir_id, []))
            source_hash = hashlib.sha256("\n".join(children).encode("utf-8")).hexdigest()
            existing = existing_by_id.get(dir_id)
            mapped_bundle = self._config.bundle_overlays.get(NodeType.DIRECTORY.value)
            refresh_subscriptions = not self._subscriptions_bootstrapped
            refresh_bundle = sync_existing_bundles

            directory_node = CodeNode(
                node_id=dir_id,
                node_type=NodeType.DIRECTORY,
                name=name,
                full_name=dir_id,
                file_path=dir_id,
                start_line=0,
                end_line=0,
                source_code="",
                source_hash=source_hash,
                parent_id=parent_id,
                status=existing.status if existing is not None else "idle",
                bundle_name=(
                    mapped_bundle
                    if mapped_bundle is not None
                    else (existing.bundle_name if existing is not None else None)
                ),
            )

            if existing is None:
                await self._node_store.upsert_node(directory_node)
                await self._register_subscriptions(directory_node)
                await self._ensure_agent(directory_node)
                await self._provision_bundle(directory_node.node_id, directory_node.bundle_name)
                await self._event_store.append(
                    NodeDiscoveredEvent(
                        node_id=directory_node.node_id,
                        node_type=directory_node.node_type,
                        file_path=directory_node.file_path,
                        name=directory_node.name,
                    )
                )
                continue

            metadata_changed = (
                existing.parent_id != directory_node.parent_id
                or existing.file_path != directory_node.file_path
                or existing.name != directory_node.name
                or existing.full_name != directory_node.full_name
                or existing.bundle_name != directory_node.bundle_name
            )
            hash_changed = existing.source_hash != source_hash
            if metadata_changed or hash_changed:
                await self._node_store.upsert_node(directory_node)

            if refresh_subscriptions:
                await self._register_subscriptions(directory_node)
                await self._ensure_agent(directory_node)
            if refresh_bundle:
                await self._provision_bundle(directory_node.node_id, directory_node.bundle_name)

            if hash_changed:
                await self._register_subscriptions(directory_node)
                await self._ensure_agent(directory_node)
                await self._event_store.append(
                    NodeChangedEvent(
                        node_id=directory_node.node_id,
                        old_hash=existing.source_hash,
                        new_hash=directory_node.source_hash,
                        file_path=directory_node.file_path,
                    )
                )

        self._subscriptions_bootstrapped = True

    async def _provision_bundle(self, node_id: str, bundle_name: str | None) -> None:
        bundle_root = Path(self._config.bundle_root)
        # System tools/config are always included; role bundle overlays them.
        template_dirs = [bundle_root / "system"]
        if bundle_name:
            template_dirs.append(bundle_root / bundle_name)
        await self._workspace_service.provision_bundle(node_id, template_dirs)

    def _relative_file_path(self, file_path: str) -> str:
        absolute = Path(file_path).resolve()
        try:
            relative = absolute.relative_to(self._project_root)
            return relative.as_posix()
        except ValueError:
            return Path(file_path).as_posix()

    @staticmethod
    def _normalize_dir_id(path: Path | str) -> str:
        value = Path(path).as_posix() if isinstance(path, Path) else Path(path).as_posix()
        return "." if value in {"", "."} else value

    @staticmethod
    def _parent_dir_id(path_like: str) -> str:
        parent = Path(path_like).parent
        parent_str = parent.as_posix()
        return "." if parent_str in {"", "."} else parent_str

    def _directory_id_for_file(self, file_path: str) -> str:
        rel_file_path = self._relative_file_path(file_path)
        return self._parent_dir_id(rel_file_path)

    async def _reconcile_file(
        self,
        file_path: str,
        mtime_ns: int,
        *,
        sync_existing_bundles: bool = False,
    ) -> None:
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
            sync_existing_bundles=sync_existing_bundles,
        )

        dir_node_id = self._directory_id_for_file(file_path)
        for node in projected:
            if node.parent_id is None:
                node.parent_id = dir_node_id
                await self._node_store.upsert_node(node)

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
            new_hash = node.source_hash
            if old_hash is not None and old_hash != new_hash:
                await self._register_subscriptions(node)
                await self._ensure_agent(node)
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

        if node.node_type == NodeType.DIRECTORY:
            subtree_glob = "**" if node.file_path == "." else f"**/{node.file_path}/**"
            await self._event_store.subscriptions.register(
                node.node_id,
                SubscriptionPattern(
                    event_types=["NodeChangedEvent"],
                    path_glob=subtree_glob,
                ),
            )
            await self._event_store.subscriptions.register(
                node.node_id,
                SubscriptionPattern(
                    event_types=["ContentChangedEvent"],
                    path_glob=subtree_glob,
                ),
            )
            return

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
