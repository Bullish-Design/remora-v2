from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest
import pytest_asyncio

from remora.code.discovery import CSTNode
from remora.code.projections import project_nodes
from remora.core.config import Config
from remora.core.graph import NodeStore
from remora.core.workspace import CairnWorkspaceService


def _make_cst(
    *,
    file_path: str,
    name: str,
    node_type: str = "function",
    text: str | None = None,
    parent_id: str | None = None,
) -> CSTNode:
    full_name = name
    node_id = f"{file_path}::{full_name}"
    source = text or f"def {name}():\n    return 1\n"
    return CSTNode(
        node_id=node_id,
        node_type=node_type,
        name=name,
        full_name=full_name,
        file_path=file_path,
        text=source,
        start_line=1,
        end_line=2,
        start_byte=0,
        end_byte=len(source),
        parent_id=parent_id,
    )


def _write_bundle_templates(root: Path, bundle_name: str = "code-agent") -> None:
    system = root / "system"
    code_bundle = root / bundle_name
    (system / "tools").mkdir(parents=True, exist_ok=True)
    (code_bundle / "tools").mkdir(parents=True, exist_ok=True)

    (system / "bundle.yaml").write_text("name: system\nmax_turns: 2\n", encoding="utf-8")
    (system / "tools" / "send_message.pym").write_text("return 'ok'\n", encoding="utf-8")
    (code_bundle / "bundle.yaml").write_text(
        f"name: {bundle_name}\nmax_turns: 8\n",
        encoding="utf-8",
    )
    (code_bundle / "tools" / "rewrite_self.pym").write_text("return 'ok'\n", encoding="utf-8")


@pytest_asyncio.fixture
async def projection_env(tmp_path: Path):
    conn = sqlite3.connect(str(tmp_path / "phase5.db"), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    lock = asyncio.Lock()

    node_store = NodeStore(conn, lock)
    await node_store.create_tables()

    bundles_root = tmp_path / "bundles"
    _write_bundle_templates(bundles_root, bundle_name="code-agent")

    config = Config(
        swarm_root=".remora-phase5",
        bundle_root=str(bundles_root),
        bundle_mapping={"function": "code-agent", "class": "code-agent", "method": "code-agent"},
    )
    workspace_service = CairnWorkspaceService(config, tmp_path)
    await workspace_service.initialize()

    yield node_store, workspace_service, config

    await workspace_service.close()
    conn.close()


@pytest.mark.asyncio
async def test_project_new_node(projection_env) -> None:
    node_store, workspace_service, config = projection_env
    cst = _make_cst(file_path="src/a.py", name="a")

    nodes = await project_nodes([cst], node_store, workspace_service, config)
    stored = await node_store.get_node(cst.node_id)
    workspace = await workspace_service.get_agent_workspace(cst.node_id)

    assert len(nodes) == 1
    assert stored is not None
    assert await workspace.exists("_bundle/bundle.yaml")


@pytest.mark.asyncio
async def test_project_unchanged_node(projection_env) -> None:
    node_store, workspace_service, config = projection_env
    cst = _make_cst(file_path="src/a.py", name="a")

    await project_nodes([cst], node_store, workspace_service, config)
    workspace = await workspace_service.get_agent_workspace(cst.node_id)
    await workspace.write("_bundle/bundle.yaml", "name: customized\n")

    await project_nodes([cst], node_store, workspace_service, config)
    bundle_text = await workspace.read("_bundle/bundle.yaml")

    assert "customized" in bundle_text


@pytest.mark.asyncio
async def test_project_changed_node(projection_env) -> None:
    node_store, workspace_service, config = projection_env
    first = _make_cst(file_path="src/a.py", name="a", text="def a():\n    return 1\n")
    second = _make_cst(file_path="src/a.py", name="a", text="def a():\n    return 2\n")

    await project_nodes([first], node_store, workspace_service, config)
    workspace = await workspace_service.get_agent_workspace(first.node_id)
    await workspace.write("_bundle/bundle.yaml", "name: customized\n")

    await project_nodes([second], node_store, workspace_service, config)
    stored = await node_store.get_node(first.node_id)
    bundle_text = await workspace.read("_bundle/bundle.yaml")

    assert stored is not None
    assert stored.source_code == second.text
    assert "customized" in bundle_text


@pytest.mark.asyncio
async def test_project_bundle_mapping(tmp_path: Path) -> None:
    conn = sqlite3.connect(str(tmp_path / "bundle-map.db"), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    lock = asyncio.Lock()
    node_store = NodeStore(conn, lock)
    await node_store.create_tables()

    bundles_root = tmp_path / "bundles"
    _write_bundle_templates(bundles_root, bundle_name="special-agent")
    config = Config(
        swarm_root=".remora-phase5",
        bundle_root=str(bundles_root),
        bundle_mapping={"function": "special-agent"},
    )
    workspace_service = CairnWorkspaceService(config, tmp_path)
    await workspace_service.initialize()

    cst = _make_cst(file_path="src/a.py", name="mapped")
    await project_nodes([cst], node_store, workspace_service, config)

    stored = await node_store.get_node(cst.node_id)
    workspace = await workspace_service.get_agent_workspace(cst.node_id)
    bundle_text = await workspace.read("_bundle/bundle.yaml")

    assert stored is not None
    assert stored.bundle_name == "special-agent"
    assert "special-agent" in bundle_text

    await workspace_service.close()
    conn.close()
