from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from remora.core.config import Config, SearchConfig, expand_env_vars, _find_config_file, load_config


def test_default_config(monkeypatch) -> None:
    monkeypatch.delenv("REMORA_MAX_TURNS", raising=False)
    monkeypatch.delenv("REMORA_MODEL_DEFAULT", raising=False)
    config = Config()
    assert config.max_turns == 8
    assert config.bundle_overlays["function"] == "code-agent"
    assert config.bundle_overlays["directory"] == "directory-agent"
    assert config.language_map[".py"] == "python"
    assert "queries/" in config.query_paths


def test_legacy_bundle_mapping_key_rejected() -> None:
    """Old 'bundle_mapping' key is no longer silently migrated."""
    with pytest.raises(ValidationError):
        Config(bundle_mapping={"function": "special-agent"})


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


def test_load_virtual_agents_from_yaml(tmp_path: Path) -> None:
    yaml_path = tmp_path / "remora.yaml"
    yaml_path.write_text(
        "virtual_agents:\n"
        "  - id: test-agent\n"
        "    role: test-agent\n"
        "    subscriptions:\n"
        "      - event_types: [NodeChangedEvent]\n"
        "        path_glob: src/**\n"
        "        tags: [scaffold, ci]\n",
        encoding="utf-8",
    )
    config = load_config(yaml_path)
    assert len(config.virtual_agents) == 1
    assert config.virtual_agents[0].id == "test-agent"
    assert config.virtual_agents[0].role == "test-agent"
    assert config.virtual_agents[0].subscriptions[0].event_types == ("NodeChangedEvent",)
    assert config.virtual_agents[0].subscriptions[0].tags == ("scaffold", "ci")


def test_env_var_expansion(monkeypatch) -> None:
    monkeypatch.setenv("TEST_MODEL", "gpt-5")
    data = {
        "model_default": "${TEST_MODEL:-fallback}",
        "model_api_key": "${MISSING_KEY:-default-key}",
        "nested": ["${MISSING_2:-x}", {"v": "${TEST_MODEL:-y}"}],
    }
    expanded = expand_env_vars(data)
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


def test_invalid_language_map_rejected() -> None:
    with pytest.raises(ValidationError):
        Config(language_map={"py": "python"})


def test_empty_discovery_paths_rejected() -> None:
    with pytest.raises(ValidationError):
        Config(discovery_paths=())


def test_bundle_rules_override_type_overlays() -> None:
    config = Config(
        bundle_overlays={"function": "code-agent"},
        bundle_rules=(
            {
                "node_type": "function",
                "name_pattern": "test_*",
                "bundle": "test-agent",
            },
        ),
    )
    assert config.resolve_bundle("function", "test_alpha") == "test-agent"
    assert config.resolve_bundle("function", "alpha") == "code-agent"


def test_search_config_defaults() -> None:
    search = SearchConfig()
    assert search.enabled is False
    assert search.mode == "remote"
    assert search.embeddy_url == "http://localhost:8585"
    assert search.timeout == 30.0
    assert search.default_collection == "code"
    assert search.collection_map[".py"] == "code"
    assert search.db_path == ".remora/embeddy.db"
    assert search.model_name == "Qwen/Qwen3-VL-Embedding-2B"
    assert search.embedding_dimension == 2048


def test_search_config_invalid_mode_rejected() -> None:
    with pytest.raises(ValidationError):
        SearchConfig(mode="invalid")


def test_config_parses_search_dict() -> None:
    config = Config(
        search={
            "enabled": True,
            "mode": "remote",
            "embeddy_url": "http://localhost:8585",
            "timeout": 45.0,
            "default_collection": "code",
            "collection_map": {".py": "python-code", ".md": "docs"},
        }
    )
    assert config.search.enabled is True
    assert config.search.mode == "remote"
    assert config.search.timeout == 45.0
    assert config.search.collection_map[".py"] == "python-code"


def test_load_from_yaml_with_search_section(tmp_path: Path) -> None:
    yaml_path = tmp_path / "remora.yaml"
    yaml_path.write_text(
        "search:\n"
        "  enabled: true\n"
        "  mode: remote\n"
        "  embeddy_url: http://localhost:9595\n"
        "  timeout: 60.0\n"
        "  default_collection: code\n"
        "  collection_map:\n"
        "    .py: code\n"
        "    .md: docs\n",
        encoding="utf-8",
    )
    config = load_config(yaml_path)
    assert config.search.enabled is True
    assert config.search.mode == "remote"
    assert config.search.embeddy_url == "http://localhost:9595"
    assert config.search.timeout == 60.0
    assert config.search.collection_map[".md"] == "docs"
