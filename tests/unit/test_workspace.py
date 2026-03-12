from __future__ import annotations

import re
from pathlib import Path

import pytest
from cairn.runtime import workspace_manager as cairn_wm

from remora.core.config import Config
from remora.core.workspace import AgentWorkspace, CairnWorkspaceService


@pytest.mark.asyncio
async def test_workspace_write_read(tmp_path: Path) -> None:
    raw_ws = await cairn_wm.open_workspace(tmp_path / "agent-a")
    workspace = AgentWorkspace(raw_ws, "agent-a")
    await workspace.write("notes/a.txt", "hello")
    assert await workspace.read("notes/a.txt") == "hello"
    await raw_ws.close()


@pytest.mark.asyncio
async def test_workspace_exists(tmp_path: Path) -> None:
    raw_ws = await cairn_wm.open_workspace(tmp_path / "agent-a")
    workspace = AgentWorkspace(raw_ws, "agent-a")
    assert not await workspace.exists("notes/a.txt")
    await workspace.write("notes/a.txt", "hello")
    assert await workspace.exists("notes/a.txt")
    await raw_ws.close()


@pytest.mark.asyncio
async def test_workspace_list_dir(tmp_path: Path) -> None:
    raw_ws = await cairn_wm.open_workspace(tmp_path / "agent-a")
    workspace = AgentWorkspace(raw_ws, "agent-a")
    await workspace.write("notes/a.txt", "a")
    await workspace.write("notes/b.txt", "b")
    entries = await workspace.list_dir("notes")
    assert entries == ["a.txt", "b.txt"]
    await raw_ws.close()


@pytest.mark.asyncio
async def test_workspace_delete(tmp_path: Path) -> None:
    raw_ws = await cairn_wm.open_workspace(tmp_path / "agent-a")
    workspace = AgentWorkspace(raw_ws, "agent-a")
    await workspace.write("notes/a.txt", "a")
    assert await workspace.exists("notes/a.txt")
    await workspace.delete("notes/a.txt")
    assert not await workspace.exists("notes/a.txt")
    await raw_ws.close()


@pytest.mark.asyncio
async def test_workspace_list_all_paths(tmp_path: Path) -> None:
    stable_ws = await cairn_wm.open_workspace(tmp_path / "stable")
    agent_ws = await cairn_wm.open_workspace(tmp_path / "agent-a")
    await stable_ws.files.write("shared/base.txt", "base")
    await agent_ws.files.write("notes/a.txt", "a")

    workspace = AgentWorkspace(agent_ws, "agent-a", stable_ws)
    paths = await workspace.list_all_paths()

    assert "notes/a.txt" in paths
    assert "shared/base.txt" in paths
    await agent_ws.close()
    await stable_ws.close()


@pytest.mark.asyncio
async def test_workspace_stable_fallthrough(tmp_path: Path) -> None:
    stable_ws = await cairn_wm.open_workspace(tmp_path / "stable")
    agent_ws = await cairn_wm.open_workspace(tmp_path / "agent-a")
    await stable_ws.files.write("shared/config.txt", "stable-content")

    workspace = AgentWorkspace(agent_ws, "agent-a", stable_ws)
    assert await workspace.read("shared/config.txt") == "stable-content"

    await agent_ws.close()
    await stable_ws.close()


@pytest.mark.asyncio
async def test_workspace_cow_isolation(tmp_path: Path) -> None:
    stable_ws = await cairn_wm.open_workspace(tmp_path / "stable")
    agent_ws = await cairn_wm.open_workspace(tmp_path / "agent-a")
    await stable_ws.files.write("shared/config.txt", "stable-content")

    workspace = AgentWorkspace(agent_ws, "agent-a", stable_ws)
    await workspace.write("shared/config.txt", "agent-content")

    assert await workspace.read("shared/config.txt") == "agent-content"
    assert await stable_ws.files.read("shared/config.txt") == "stable-content"

    await agent_ws.close()
    await stable_ws.close()


@pytest.mark.asyncio
async def test_service_initialize(tmp_path: Path) -> None:
    config = Config(swarm_root=".remora-test")
    service = CairnWorkspaceService(config, tmp_path)
    await service.initialize()
    assert service._stable is not None
    assert (tmp_path / ".remora-test").exists()
    await service.close()


@pytest.mark.asyncio
async def test_service_get_workspace(tmp_path: Path) -> None:
    config = Config(swarm_root=".remora-test")
    service = CairnWorkspaceService(config, tmp_path)
    await service.initialize()
    workspace = await service.get_agent_workspace("src/app.py::a")
    assert isinstance(workspace, AgentWorkspace)
    await service.close()


@pytest.mark.asyncio
async def test_service_workspace_caching(tmp_path: Path) -> None:
    config = Config(swarm_root=".remora-test")
    service = CairnWorkspaceService(config, tmp_path)
    await service.initialize()
    first = await service.get_agent_workspace("src/app.py::a")
    second = await service.get_agent_workspace("src/app.py::a")
    assert first is second
    await service.close()


@pytest.mark.asyncio
async def test_service_provision_bundle(tmp_path: Path) -> None:
    config = Config(swarm_root=".remora-test")
    service = CairnWorkspaceService(config, tmp_path)
    await service.initialize()

    template = tmp_path / "bundle-template"
    (template / "tools").mkdir(parents=True)
    (template / "bundle.yaml").write_text("name: code-agent\nmax_turns: 5\n", encoding="utf-8")
    (template / "tools" / "echo.pym").write_text("from grail import Input\n", encoding="utf-8")

    node_id = "src/app.py::a"
    await service.provision_bundle(node_id, [template])
    workspace = await service.get_agent_workspace(node_id)

    bundle = await workspace.read("_bundle/bundle.yaml")
    tool = await workspace.read("_bundle/tools/echo.pym")
    assert "name: code-agent" in bundle
    assert "from grail import Input" in tool
    await service.close()


@pytest.mark.asyncio
async def test_service_provision_layering(tmp_path: Path) -> None:
    config = Config(swarm_root=".remora-test")
    service = CairnWorkspaceService(config, tmp_path)
    await service.initialize()

    system_template = tmp_path / "system-template"
    (system_template / "tools").mkdir(parents=True)
    (system_template / "bundle.yaml").write_text("name: system\nmax_turns: 2\n", encoding="utf-8")
    (system_template / "tools" / "shared.pym").write_text("return 'system'\n", encoding="utf-8")
    (system_template / "tools" / "only_system.pym").write_text(
        "return 'system-only'\n",
        encoding="utf-8",
    )

    type_template = tmp_path / "type-template"
    (type_template / "tools").mkdir(parents=True)
    (type_template / "bundle.yaml").write_text("name: code-agent\nmax_turns: 8\n", encoding="utf-8")
    (type_template / "tools" / "shared.pym").write_text("return 'type'\n", encoding="utf-8")
    (type_template / "tools" / "only_type.pym").write_text("return 'type-only'\n", encoding="utf-8")

    node_id = "src/app.py::a"
    await service.provision_bundle(node_id, [system_template, type_template])
    workspace = await service.get_agent_workspace(node_id)

    bundle = await workspace.read("_bundle/bundle.yaml")
    shared = await workspace.read("_bundle/tools/shared.pym")
    only_system = await workspace.read("_bundle/tools/only_system.pym")
    only_type = await workspace.read("_bundle/tools/only_type.pym")

    assert "name: code-agent" in bundle
    assert shared.strip() == "return 'type'"
    assert only_system.strip() == "return 'system-only'"
    assert only_type.strip() == "return 'type-only'"
    await service.close()


def test_safe_id() -> None:
    safe = CairnWorkspaceService._safe_id("src/auth/service.py::AuthService.validate_token")
    assert re.fullmatch(r"[a-zA-Z0-9._-]+", safe)
