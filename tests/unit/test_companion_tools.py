"""Tests for companion KV tools."""

from __future__ import annotations

from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[2] / "bundles" / "system" / "tools"


def test_companion_summarize_exists() -> None:
    tool_path = TOOLS_DIR / "companion_summarize.pym"
    assert tool_path.exists(), f"Missing tool: {tool_path}"
    content = tool_path.read_text(encoding="utf-8")
    assert "companion/chat_index" in content
    assert "kv_set" in content
    assert "kv_get" in content


def test_companion_reflect_exists() -> None:
    tool_path = TOOLS_DIR / "companion_reflect.pym"
    assert tool_path.exists(), f"Missing tool: {tool_path}"
    content = tool_path.read_text(encoding="utf-8")
    assert "companion/reflections" in content
    assert "kv_set" in content


def test_companion_link_exists() -> None:
    tool_path = TOOLS_DIR / "companion_link.pym"
    assert tool_path.exists(), f"Missing tool: {tool_path}"
    content = tool_path.read_text(encoding="utf-8")
    assert "companion/links" in content
    assert "target_node_id" in content
