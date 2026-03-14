"""Shared test factories and helpers."""

from __future__ import annotations

from pathlib import Path

from remora.code.discovery import CSTNode
from remora.core.node import Node
from remora.core.types import NodeStatus, NodeType


def make_node(
    node_id: str,
    *,
    file_path: str = "src/app.py",
    node_type: str | NodeType = NodeType.FUNCTION,
    status: str | NodeStatus = NodeStatus.IDLE,
    source_code: str | None = None,
    **overrides,
) -> Node:
    name = node_id.split("::", maxsplit=1)[-1]
    data = {
        "node_id": node_id,
        "node_type": node_type,
        "name": name,
        "full_name": name,
        "file_path": file_path,
        "start_line": 1,
        "end_line": 4,
        "source_code": source_code or f"def {name}():\n    return 1\n",
        "source_hash": f"hash-{node_id}",
        "status": status,
    }
    data.update(overrides)
    return Node(**data)


def make_cst(
    *,
    file_path: str,
    name: str,
    node_type: str = "function",
    text: str | None = None,
    parent_id: str | None = None,
) -> CSTNode:
    source = text or f"def {name}():\n    return 1\n"
    return CSTNode(
        node_id=f"{file_path}::{name}",
        node_type=node_type,
        name=name,
        full_name=name,
        file_path=file_path,
        text=source,
        start_line=1,
        end_line=2,
        start_byte=0,
        end_byte=len(source),
        parent_id=parent_id,
    )


def write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_bundle_templates(root: Path, role: str = "code-agent") -> None:
    system = root / "system"
    bundle = root / role
    (system / "tools").mkdir(parents=True, exist_ok=True)
    (bundle / "tools").mkdir(parents=True, exist_ok=True)
    (system / "bundle.yaml").write_text("name: system\nmax_turns: 4\n", encoding="utf-8")
    (bundle / "bundle.yaml").write_text(
        f"name: {role}\nmax_turns: 8\n",
        encoding="utf-8",
    )
    (system / "tools" / "send_message.pym").write_text("result = 'ok'\nresult\n", encoding="utf-8")
    (bundle / "tools" / "rewrite_self.pym").write_text("result = 'ok'\nresult\n", encoding="utf-8")
