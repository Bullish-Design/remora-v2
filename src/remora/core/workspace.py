"""Cairn workspace integration for Remora agents."""

from __future__ import annotations

import asyncio
import hashlib
import re
from pathlib import Path
from typing import Any

from cairn.runtime import workspace_manager as cairn_wm
from fsdantic import FileNotFoundError as FsdFileNotFoundError
from fsdantic import ViewQuery

from remora.core.config import Config


class AgentWorkspace:
    """Per-agent sandboxed filesystem backed by Cairn."""

    def __init__(self, workspace: Any, agent_id: str, stable_workspace: Any | None = None):
        self._workspace = workspace
        self._agent_id = agent_id
        self._stable = stable_workspace
        self._lock = asyncio.Lock()

    async def read(self, path: str) -> str:
        """Read a file from the agent workspace, falling back to stable if needed."""
        async with self._lock:
            try:
                content = await self._workspace.files.read(path)
            except (FileNotFoundError, FsdFileNotFoundError):
                if self._stable is None:
                    raise
                content = await self._stable.files.read(path)
        if isinstance(content, bytes):
            return content.decode("utf-8", errors="replace")
        return str(content)

    async def write(self, path: str, content: str | bytes) -> None:
        """Write a file to the agent workspace."""
        async with self._lock:
            await self._workspace.files.write(path, content)

    async def exists(self, path: str) -> bool:
        """Check existence in agent workspace first, then stable workspace."""
        async with self._lock:
            if await self._workspace.files.exists(path):
                return True
            if self._stable is not None and await self._stable.files.exists(path):
                return True
            return False

    async def list_dir(self, path: str = ".") -> list[str]:
        """List merged directory entries from agent and stable workspaces."""
        async with self._lock:
            entries: set[str] = set()
            try:
                entries.update(await self._workspace.files.list_dir(path, output="name"))
            except (FileNotFoundError, FsdFileNotFoundError):
                pass

            if self._stable is not None:
                try:
                    entries.update(await self._stable.files.list_dir(path, output="name"))
                except (FileNotFoundError, FsdFileNotFoundError):
                    pass

            return sorted(entries)

    async def delete(self, path: str) -> None:
        """Delete a file from the agent workspace."""
        async with self._lock:
            await self._workspace.files.remove(path)

    async def list_all_paths(self) -> list[str]:
        """List all file paths visible to this workspace (agent + stable)."""
        async with self._lock:
            query = ViewQuery(
                path_pattern="**/*",
                recursive=True,
                include_stats=False,
                include_content=False,
            )
            merged_paths: set[str] = set()

            try:
                agent_entries = await self._workspace.files.query(query)
                merged_paths.update(
                    str(getattr(entry, "path", "")).lstrip("/")
                    for entry in agent_entries
                    if str(getattr(entry, "path", "")).lstrip("/")
                )
            except (FileNotFoundError, FsdFileNotFoundError):
                pass

            if self._stable is not None:
                try:
                    stable_entries = await self._stable.files.query(query)
                    merged_paths.update(
                        str(getattr(entry, "path", "")).lstrip("/")
                        for entry in stable_entries
                        if str(getattr(entry, "path", "")).lstrip("/")
                    )
                except (FileNotFoundError, FsdFileNotFoundError):
                    pass

            return sorted(merged_paths)


class CairnWorkspaceService:
    """Manages stable and per-agent Cairn workspaces."""

    def __init__(self, config: Config, project_root: Path):
        self._config = config
        self._project_root = project_root.resolve()
        self._swarm_root = self._project_root / config.swarm_root
        self._manager = cairn_wm.WorkspaceManager()
        self._stable: Any | None = None
        self._agent_workspaces: dict[str, AgentWorkspace] = {}
        self._raw_agent_workspaces: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Initialize the stable workspace used for shared read-through."""
        self._swarm_root.mkdir(parents=True, exist_ok=True)
        agents_root = self._swarm_root / "agents"
        agents_root.mkdir(parents=True, exist_ok=True)
        self._stable = await cairn_wm.open_workspace(str(self._swarm_root / "stable"))
        self._manager.track_workspace(self._stable)

    async def get_agent_workspace(self, node_id: str) -> AgentWorkspace:
        """Get or create an AgentWorkspace for the given node ID."""
        async with self._lock:
            cached = self._agent_workspaces.get(node_id)
            if cached is not None:
                return cached

            workspace_path = self._swarm_root / "agents" / self._safe_id(node_id)
            raw_workspace = await cairn_wm.open_workspace(str(workspace_path))
            self._manager.track_workspace(raw_workspace)

            agent_workspace = AgentWorkspace(raw_workspace, node_id, self._stable)
            self._raw_agent_workspaces[node_id] = raw_workspace
            self._agent_workspaces[node_id] = agent_workspace
            return agent_workspace

    async def provision_bundle(self, node_id: str, template_dirs: list[Path]) -> None:
        """Copy bundle.yaml and tool scripts from ordered template directories."""
        workspace = await self.get_agent_workspace(node_id)

        for template_dir in template_dirs:
            if not template_dir.exists():
                continue

            bundle_yaml = template_dir / "bundle.yaml"
            if bundle_yaml.exists():
                await workspace.write(
                    "_bundle/bundle.yaml",
                    bundle_yaml.read_text(encoding="utf-8"),
                )

            tools_dir = template_dir / "tools"
            if tools_dir.exists():
                for pym_file in sorted(tools_dir.glob("*.pym")):
                    await workspace.write(
                        f"_bundle/tools/{pym_file.name}",
                        pym_file.read_text(encoding="utf-8"),
                    )

    async def close(self) -> None:
        """Close and release tracked workspaces."""
        self._agent_workspaces.clear()
        self._raw_agent_workspaces.clear()
        self._stable = None
        await self._manager.close_all()

    @staticmethod
    def _safe_id(node_id: str) -> str:
        """Convert node ID to a filesystem-safe deterministic name."""
        normalized = re.sub(r"[^a-zA-Z0-9._-]+", "_", node_id).strip("._-")
        digest = hashlib.sha1(node_id.encode("utf-8")).hexdigest()[:10]
        prefix = normalized[:80] if normalized else "node"
        return f"{prefix}-{digest}"


__all__ = ["AgentWorkspace", "CairnWorkspaceService"]
