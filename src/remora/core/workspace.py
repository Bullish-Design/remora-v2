"""Cairn workspace integration for Remora agents."""

from __future__ import annotations

import asyncio
import hashlib
import re
from pathlib import Path
from typing import Any

import yaml
from cairn.runtime import workspace_manager as cairn_wm
from fsdantic import ViewQuery, Workspace

from remora.core.config import Config
from remora.core.metrics import Metrics


class AgentWorkspace:
    """Per-agent sandboxed filesystem backed by Cairn."""

    def __init__(self, workspace: Workspace, agent_id: str):
        self._workspace = workspace
        self._agent_id = agent_id
        self._lock = asyncio.Lock()

    async def read(self, path: str) -> str:
        """Read a file from the agent workspace."""
        async with self._lock:
            content = await self._workspace.files.read(path)
        if isinstance(content, bytes):
            return content.decode("utf-8", errors="replace")
        return str(content)

    async def write(self, path: str, content: str | bytes) -> None:
        """Write a file to the agent workspace."""
        async with self._lock:
            await self._workspace.files.write(path, content)

    async def exists(self, path: str) -> bool:
        """Check existence in the agent workspace."""
        async with self._lock:
            return await self._workspace.files.exists(path)

    async def list_dir(self, path: str = ".") -> list[str]:
        """List directory entries from the agent workspace."""
        async with self._lock:
            return sorted(await self._workspace.files.list_dir(path, output="name"))

    async def delete(self, path: str) -> None:
        """Delete a file from the agent workspace."""
        async with self._lock:
            await self._workspace.files.remove(path)

    async def list_all_paths(self) -> list[str]:
        """List all file paths in this workspace."""
        async with self._lock:
            query = ViewQuery(
                path_pattern="**/*",
                recursive=True,
                include_stats=False,
                include_content=False,
            )
            entries = await self._workspace.files.query(query)
            return sorted(
                str(getattr(entry, "path", "")).lstrip("/")
                for entry in entries
                if str(getattr(entry, "path", "")).lstrip("/")
            )

    async def kv_get(self, key: str) -> Any | None:
        """Get a value from the workspace KV store."""
        async with self._lock:
            return await self._workspace.kv.get(key, None)

    async def kv_set(self, key: str, value: Any) -> None:
        """Set a value in the workspace KV store."""
        async with self._lock:
            await self._workspace.kv.set(key, value)

    async def kv_delete(self, key: str) -> None:
        """Delete a value from the workspace KV store."""
        async with self._lock:
            await self._workspace.kv.delete(key)

    async def kv_list(self, prefix: str = "") -> list[str]:
        """List KV keys for a prefix."""
        async with self._lock:
            records = await self._workspace.kv.list(prefix=prefix)
        keys: list[str] = []
        for record in records:
            if isinstance(record, dict):
                key = record.get("key")
            else:
                key = getattr(record, "key", None)
            if key:
                keys.append(str(key))
        return sorted(keys)


class CairnWorkspaceService:
    """Manages per-agent Cairn workspaces."""

    def __init__(self, config: Config, project_root: Path, metrics: Metrics | None = None):
        self._config = config
        self._project_root = project_root.resolve()
        self._workspace_root = self._project_root / config.workspace_root
        self._manager = cairn_wm.WorkspaceManager()
        self._agent_workspaces: dict[str, AgentWorkspace] = {}
        self._raw_agent_workspaces: dict[str, Workspace] = {}
        self._metrics = metrics
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Initialize workspace root directories."""
        self._workspace_root.mkdir(parents=True, exist_ok=True)
        agents_root = self._workspace_root / "agents"
        agents_root.mkdir(parents=True, exist_ok=True)

    def has_workspace(self, node_id: str) -> bool:
        """Return whether a workspace already exists for this node."""
        if node_id in self._agent_workspaces:
            return True
        return self._workspace_path(node_id).exists()

    async def get_agent_workspace(self, node_id: str) -> AgentWorkspace:
        """Get or create an AgentWorkspace for the given node ID."""
        async with self._lock:
            cached = self._agent_workspaces.get(node_id)
            if cached is not None:
                if self._metrics is not None:
                    self._metrics.workspace_cache_hits += 1
                return cached

            workspace_path = self._workspace_path(node_id)
            raw_workspace = await cairn_wm.open_workspace(str(workspace_path))
            self._manager.track_workspace(raw_workspace)
            if self._metrics is not None:
                self._metrics.workspace_provisions_total += 1

            agent_workspace = AgentWorkspace(raw_workspace, node_id)
            self._raw_agent_workspaces[node_id] = raw_workspace
            self._agent_workspaces[node_id] = agent_workspace
            return agent_workspace

    async def provision_bundle(self, node_id: str, template_dirs: list[Path]) -> None:
        """Copy bundle.yaml and tool scripts from ordered template directories."""
        workspace = await self.get_agent_workspace(node_id)
        fingerprint = _bundle_template_fingerprint(template_dirs)
        existing_fingerprint = await workspace.kv_get("_bundle/template_fingerprint")
        if existing_fingerprint == fingerprint:
            return

        merged_bundle: dict[str, Any] = {}

        for template_dir in template_dirs:
            if not template_dir.exists():
                continue

            bundle_yaml = template_dir / "bundle.yaml"
            if bundle_yaml.exists():
                loaded = yaml.safe_load(bundle_yaml.read_text(encoding="utf-8")) or {}
                if isinstance(loaded, dict):
                    merged_bundle = _merge_dicts(merged_bundle, loaded)

            tools_dir = template_dir / "tools"
            if tools_dir.exists():
                for pym_file in sorted(tools_dir.glob("*.pym")):
                    await workspace.write(
                        f"_bundle/tools/{pym_file.name}",
                        pym_file.read_text(encoding="utf-8"),
                    )

        if merged_bundle:
            await workspace.write(
                "_bundle/bundle.yaml",
                yaml.safe_dump(merged_bundle, sort_keys=False),
            )
        await workspace.kv_set("_bundle/template_fingerprint", fingerprint)

    async def close(self) -> None:
        """Close and release tracked workspaces."""
        self._agent_workspaces.clear()
        self._raw_agent_workspaces.clear()
        await self._manager.close_all()

    @property
    def project_root(self) -> Path:
        """The resolved project root path."""
        return self._project_root

    @staticmethod
    def _safe_id(node_id: str) -> str:
        """Convert node ID to a filesystem-safe deterministic name."""
        normalized = re.sub(r"[^a-zA-Z0-9._-]+", "_", node_id).strip("._-")
        digest = hashlib.sha256(node_id.encode("utf-8")).hexdigest()[:10]
        prefix = normalized[:80] if normalized else "node"
        return f"{prefix}-{digest}"

    def _workspace_path(self, node_id: str) -> Path:
        return self._workspace_root / "agents" / self._safe_id(node_id)


__all__ = ["AgentWorkspace", "CairnWorkspaceService"]


def _merge_dicts(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _merge_dicts(existing, value)
        else:
            merged[key] = value
    return merged


def _bundle_template_fingerprint(template_dirs: list[Path]) -> str:
    hasher = hashlib.sha256()
    for template_dir in template_dirs:
        resolved_dir = template_dir.resolve()
        hasher.update(str(resolved_dir).encode("utf-8"))
        if not resolved_dir.exists():
            hasher.update(b"missing")
            continue

        bundle_yaml = resolved_dir / "bundle.yaml"
        if bundle_yaml.exists():
            hasher.update(b"bundle.yaml")
            hasher.update(bundle_yaml.read_bytes())

        tools_dir = resolved_dir / "tools"
        if tools_dir.exists():
            for pym_file in sorted(tools_dir.glob("*.pym")):
                hasher.update(pym_file.name.encode("utf-8"))
                hasher.update(pym_file.read_bytes())

    return hasher.hexdigest()
