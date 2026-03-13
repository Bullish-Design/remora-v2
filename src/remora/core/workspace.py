"""Cairn workspace integration for Remora agents."""

from __future__ import annotations

import asyncio
import hashlib
import re
from pathlib import Path
from typing import Any

from cairn.runtime import workspace_manager as cairn_wm
from fsdantic import ViewQuery

from remora.core.config import Config


class AgentWorkspace:
    """Per-agent sandboxed filesystem backed by Cairn."""

    def __init__(self, workspace: Any, agent_id: str):
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


class CairnWorkspaceService:
    """Manages per-agent Cairn workspaces."""

    def __init__(self, config: Config, project_root: Path):
        self._config = config
        self._project_root = project_root.resolve()
        self._swarm_root = self._project_root / config.swarm_root
        self._manager = cairn_wm.WorkspaceManager()
        self._agent_workspaces: dict[str, AgentWorkspace] = {}
        self._raw_agent_workspaces: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Initialize workspace root directories."""
        self._swarm_root.mkdir(parents=True, exist_ok=True)
        agents_root = self._swarm_root / "agents"
        agents_root.mkdir(parents=True, exist_ok=True)

    async def get_agent_workspace(self, node_id: str) -> AgentWorkspace:
        """Get or create an AgentWorkspace for the given node ID."""
        async with self._lock:
            cached = self._agent_workspaces.get(node_id)
            if cached is not None:
                return cached

            workspace_path = self._swarm_root / "agents" / self._safe_id(node_id)
            raw_workspace = await cairn_wm.open_workspace(str(workspace_path))
            self._manager.track_workspace(raw_workspace)

            agent_workspace = AgentWorkspace(raw_workspace, node_id)
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
        await self._manager.close_all()

    @staticmethod
    def _safe_id(node_id: str) -> str:
        """Convert node ID to a filesystem-safe deterministic name."""
        normalized = re.sub(r"[^a-zA-Z0-9._-]+", "_", node_id).strip("._-")
        digest = hashlib.sha1(node_id.encode("utf-8")).hexdigest()[:10]
        prefix = normalized[:80] if normalized else "node"
        return f"{prefix}-{digest}"


__all__ = ["AgentWorkspace", "CairnWorkspaceService"]
