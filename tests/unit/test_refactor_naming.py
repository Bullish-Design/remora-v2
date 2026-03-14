from __future__ import annotations

from remora.core.config import Config
from remora.core.node import DiscoveredElement, Node


def test_new_core_symbols_exist() -> None:
    assert Node is not None
    assert DiscoveredElement is not None


def test_node_uses_role_field() -> None:
    node = Node(
        node_id="src/app.py::alpha",
        node_type="function",
        name="alpha",
        full_name="alpha",
        file_path="src/app.py",
        start_line=1,
        end_line=2,
        source_code="def alpha():\n    return 1\n",
        source_hash="hash-a",
        role="code-agent",
    )
    assert node.role == "code-agent"
    assert node.to_agent().role == "code-agent"


def test_config_workspace_root_aliases_legacy_swarm_root() -> None:
    config = Config(workspace_root=".remora-workspace")
    assert config.workspace_root == ".remora-workspace"

    legacy = Config(swarm_root=".remora-legacy")
    assert legacy.workspace_root == ".remora-legacy"
