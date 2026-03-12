from __future__ import annotations

from pathlib import Path

import grail
import yaml


def test_directory_tools_parse() -> None:
    tools_dir = Path("bundles/directory-agent/tools")
    tool_files = sorted(tools_dir.glob("*.pym"))
    assert tool_files
    for tool_file in tool_files:
        script = grail.load(tool_file)
        assert script.name == tool_file.stem


def test_directory_bundle_yaml_valid() -> None:
    bundle_path = Path("bundles/directory-agent/bundle.yaml")
    data = yaml.safe_load(bundle_path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert "system_prompt" in data
    assert "model" in data
    assert "max_turns" in data
