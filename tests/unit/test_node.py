from __future__ import annotations

import pytest
from pydantic import ValidationError

from remora.core.node import CodeNode


def _make_node() -> CodeNode:
    return CodeNode(
        node_id="src/auth.py::AuthService.validate_token",
        node_type="method",
        name="validate_token",
        full_name="AuthService.validate_token",
        file_path="src/auth.py",
        start_line=10,
        end_line=26,
        start_byte=120,
        end_byte=420,
        source_code="def validate_token(token: str) -> bool:\n    return True\n",
        source_hash="abc123",
        parent_id="src/auth.py::AuthService",
        caller_ids=["src/api.py::handle_request"],
        callee_ids=["src/auth.py::decode"],
        status="idle",
        bundle_name="code-agent",
    )


def test_codenode_creation() -> None:
    node = _make_node()
    assert node.node_id == "src/auth.py::AuthService.validate_token"
    assert node.node_type == "method"
    assert node.parent_id == "src/auth.py::AuthService"


def test_codenode_roundtrip() -> None:
    node = _make_node()
    row = node.to_row()
    restored = CodeNode.from_row(row)
    assert restored.model_dump() == node.model_dump()


def test_codenode_list_serialization() -> None:
    node = _make_node()
    row = node.to_row()
    assert isinstance(row["caller_ids"], str)
    assert isinstance(row["callee_ids"], str)
    restored = CodeNode.from_row(row)
    assert restored.caller_ids == ["src/api.py::handle_request"]
    assert restored.callee_ids == ["src/auth.py::decode"]


def test_codenode_rejects_invalid_status() -> None:
    with pytest.raises(ValidationError):
        CodeNode(
            node_id="src/a.py::a",
            node_type="function",
            name="a",
            full_name="a",
            file_path="src/a.py",
            start_line=1,
            end_line=2,
            source_code="def a():\n    return 1\n",
            source_hash="h-a",
            status="bogus",
        )
