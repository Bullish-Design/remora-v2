"""Bundle configuration validation tests."""

from __future__ import annotations

from pathlib import Path

import yaml


def test_code_agent_bundle_has_self_reflect() -> None:
    bundle_path = Path(__file__).resolve().parents[2] / "bundles" / "code-agent" / "bundle.yaml"
    config = yaml.safe_load(bundle_path.read_text(encoding="utf-8"))
    assert "self_reflect" in config
    self_reflect = config["self_reflect"]
    assert self_reflect["enabled"] is True
    assert "model" in self_reflect
    assert "prompt" in self_reflect
    assert self_reflect["max_turns"] >= 1
