from __future__ import annotations

import pytest
from pydantic import ValidationError

from remora.core.node import Agent, CodeElement, CodeNode


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


def test_codenode_element_and_agent_projection() -> None:
    node = _make_node()
    element = node.to_element()
    agent = node.to_agent()
    assert isinstance(element, CodeElement)
    assert isinstance(agent, Agent)
    assert element.element_id == node.node_id
    assert agent.agent_id == node.node_id


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
