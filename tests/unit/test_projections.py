from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from tests.factories import make_cst, write_bundle_templates

from remora.code.projections import project_nodes
from remora.core.config import Config
from remora.core.db import open_database
from remora.core.graph import NodeStore
from remora.core.workspace import CairnWorkspaceService


@pytest_asyncio.fixture
async def projection_env(tmp_path: Path):
    db = await open_database(tmp_path / "phase5.db")
    node_store = NodeStore(db)
    await node_store.create_tables()

    bundles_root = tmp_path / "bundles"
    write_bundle_templates(bundles_root, role="code-agent")

    config = Config(
        workspace_root=".remora-phase5",
        bundle_root=str(bundles_root),
        bundle_overlays={"function": "code-agent", "class": "code-agent", "method": "code-agent"},
    )
    workspace_service = CairnWorkspaceService(config, tmp_path)
    await workspace_service.initialize()

    yield node_store, workspace_service, config

    await workspace_service.close()
    await db.close()


@pytest.mark.asyncio
async def test_project_new_node(projection_env) -> None:
    node_store, workspace_service, config = projection_env
    cst = make_cst(file_path="src/a.py", name="a")

    nodes = await project_nodes([cst], node_store, workspace_service, config)
    stored = await node_store.get_node(cst.node_id)
    workspace = await workspace_service.get_agent_workspace(cst.node_id)

    assert len(nodes) == 1
    assert stored is not None
    assert await workspace.exists("_bundle/bundle.yaml")


@pytest.mark.asyncio
async def test_project_unchanged_node(projection_env) -> None:
    node_store, workspace_service, config = projection_env
    cst = make_cst(file_path="src/a.py", name="a")

    await project_nodes([cst], node_store, workspace_service, config)
    workspace = await workspace_service.get_agent_workspace(cst.node_id)
    await workspace.write("_bundle/bundle.yaml", "name: customized\n")

    await project_nodes([cst], node_store, workspace_service, config)
    bundle_text = await workspace.read("_bundle/bundle.yaml")

    assert "customized" in bundle_text


@pytest.mark.asyncio
async def test_project_changed_node(projection_env) -> None:
    node_store, workspace_service, config = projection_env
    first = make_cst(file_path="src/a.py", name="a", text="def a():\n    return 1\n")
    second = make_cst(file_path="src/a.py", name="a", text="def a():\n    return 2\n")

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
async def test_project_unchanged_node_can_sync_existing_bundle_tools(
    projection_env,
    tmp_path: Path,
) -> None:
    node_store, workspace_service, config = projection_env
    cst = make_cst(file_path="src/a.py", name="a")

    await project_nodes([cst], node_store, workspace_service, config)
    workspace = await workspace_service.get_agent_workspace(cst.node_id)
    await workspace.write("_bundle/tools/rewrite_self.pym", "result = 'stale'\nresult\n")

    bundle_tool = tmp_path / "bundles" / "code-agent" / "tools" / "rewrite_self.pym"
    bundle_tool.write_text("result = 'fresh'\nresult\n", encoding="utf-8")

    await project_nodes(
        [cst],
        node_store,
        workspace_service,
        config,
        sync_existing_bundles=True,
    )
    tool_text = await workspace.read("_bundle/tools/rewrite_self.pym")
    assert "fresh" in tool_text


@pytest.mark.asyncio
async def test_project_bundle_overlays(tmp_path: Path) -> None:
    db = await open_database(tmp_path / "bundle-map.db")
    node_store = NodeStore(db)
    await node_store.create_tables()

    bundles_root = tmp_path / "bundles"
    write_bundle_templates(bundles_root, role="special-agent")
    config = Config(
        workspace_root=".remora-phase5",
        bundle_root=str(bundles_root),
        bundle_overlays={"function": "special-agent"},
    )
    workspace_service = CairnWorkspaceService(config, tmp_path)
    await workspace_service.initialize()

    cst = make_cst(file_path="src/a.py", name="mapped")
    await project_nodes([cst], node_store, workspace_service, config)

    stored = await node_store.get_node(cst.node_id)
    workspace = await workspace_service.get_agent_workspace(cst.node_id)
    bundle_text = await workspace.read("_bundle/bundle.yaml")

    assert stored is not None
    assert stored.role == "special-agent"
    assert "special-agent" in bundle_text

    await workspace_service.close()
    await db.close()


@pytest.mark.asyncio
async def test_project_bundle_rules_override_overlays(tmp_path: Path) -> None:
    db = await open_database(tmp_path / "bundle-rules.db")
    node_store = NodeStore(db)
    await node_store.create_tables()

    bundles_root = tmp_path / "bundles"
    write_bundle_templates(bundles_root, role="code-agent")
    write_bundle_templates(bundles_root, role="test-agent")
    config = Config(
        workspace_root=".remora-phase5",
        bundle_root=str(bundles_root),
        bundle_overlays={"function": "code-agent"},
        bundle_rules=(
            {
                "node_type": "function",
                "name_pattern": "test_*",
                "bundle": "test-agent",
            },
        ),
    )
    workspace_service = CairnWorkspaceService(config, tmp_path)
    await workspace_service.initialize()

    cst = make_cst(file_path="src/a.py", name="test_mapped")
    await project_nodes([cst], node_store, workspace_service, config)

    stored = await node_store.get_node(cst.node_id)
    workspace = await workspace_service.get_agent_workspace(cst.node_id)
    bundle_text = await workspace.read("_bundle/bundle.yaml")

    assert stored is not None
    assert stored.role == "test-agent"
    assert "test-agent" in bundle_text

    await workspace_service.close()
    await db.close()
