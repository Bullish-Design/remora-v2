from __future__ import annotations

from pathlib import Path

from remora.core.config import Config, _expand_env_vars, _find_config_file, load_config


def test_default_config(monkeypatch) -> None:
    monkeypatch.delenv("REMORA_MAX_TURNS", raising=False)
    monkeypatch.delenv("REMORA_MODEL_DEFAULT", raising=False)
    config = Config()
    assert config.max_turns == 8
    assert config.bundle_mapping["function"] == "code-agent"
    assert config.language_map[".py"] == "python"
    assert "queries/" in config.query_paths


def test_load_from_yaml(tmp_path: Path) -> None:
    yaml_path = tmp_path / "remora.yaml"
    yaml_path.write_text(
        "max_turns: 20\n"
        "model_default: gpt-4\n"
        "language_map:\n"
        "  .py: python\n"
        "  .md: markdown\n"
        "query_paths:\n"
        "  - custom-queries/\n",
        encoding="utf-8",
    )
    config = load_config(yaml_path)
    assert config.max_turns == 20
    assert config.model_default == "gpt-4"
    assert config.language_map[".md"] == "markdown"
    assert config.query_paths == ("custom-queries/",)


def test_env_var_expansion(monkeypatch) -> None:
    monkeypatch.setenv("TEST_MODEL", "gpt-5")
    data = {
        "model_default": "${TEST_MODEL:-fallback}",
        "model_api_key": "${MISSING_KEY:-default-key}",
        "nested": ["${MISSING_2:-x}", {"v": "${TEST_MODEL:-y}"}],
    }
    expanded = _expand_env_vars(data)
    assert expanded["model_default"] == "gpt-5"
    assert expanded["model_api_key"] == "default-key"
    assert expanded["nested"] == ["x", {"v": "gpt-5"}]


def test_find_config_file(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "root"
    nested = root / "a" / "b"
    nested.mkdir(parents=True)
    config_path = root / "remora.yaml"
    config_path.write_text("max_turns: 11", encoding="utf-8")

    monkeypatch.chdir(nested)
    found = _find_config_file()
    assert found == config_path
