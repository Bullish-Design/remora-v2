"""Project-level configuration."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_VAR_PATTERN = re.compile(r"\$\{([^}:]+)(?::-([^}]*))?\}")


class Config(BaseSettings):
    """Remora configuration loaded from remora.yaml and environment variables."""

    model_config = SettingsConfigDict(env_prefix="REMORA_", frozen=True)

    # Project
    project_path: str = "."
    discovery_paths: tuple[str, ...] = ("src/",)
    discovery_languages: tuple[str, ...] | None = None
    language_map: dict[str, str] = Field(
        default_factory=lambda: {
            ".py": "python",
            ".md": "markdown",
            ".toml": "toml",
        }
    )
    query_paths: tuple[str, ...] = ("queries/",)

    # Bundles
    bundle_root: str = "bundles"
    bundle_mapping: dict[str, str] = Field(
        default_factory=lambda: {
            "function": "code-agent",
            "class": "code-agent",
            "method": "code-agent",
            "file": "code-agent",
            "directory": "directory-agent",
        }
    )

    # LLM
    model_base_url: str = "http://localhost:8000/v1"
    model_default: str = "Qwen/Qwen3-4B"
    model_api_key: str = ""
    timeout_s: float = 300.0
    max_turns: int = 8

    # Agent execution
    swarm_root: str = ".remora"
    max_concurrency: int = 4
    max_trigger_depth: int = 5
    trigger_cooldown_ms: int = 1000

    # Workspace
    workspace_ignore_patterns: tuple[str, ...] = (
        ".git",
        ".venv",
        "__pycache__",
        "node_modules",
        ".remora",
    )

    @field_validator("language_map")
    @classmethod
    def _validate_language_map(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for ext, language in value.items():
            if not isinstance(ext, str) or not ext.startswith("."):
                raise ValueError("language_map keys must be file extensions starting with '.'")
            if not isinstance(language, str) or not language.strip():
                raise ValueError("language_map values must be non-empty language names")
            normalized[ext.lower()] = language.lower()
        return normalized

    @field_validator("discovery_paths")
    @classmethod
    def _validate_discovery_paths(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("discovery_paths must not be empty")
        cleaned = tuple(path for path in value if isinstance(path, str) and path.strip())
        if not cleaned:
            raise ValueError("discovery_paths must contain at least one non-empty path")
        return cleaned

    @field_validator("query_paths")
    @classmethod
    def _validate_query_paths(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            return value
        cleaned = tuple(path for path in value if isinstance(path, str) and path.strip())
        return cleaned


def _expand_string(value: str) -> str:
    """Expand ${VAR:-default} shell-style values."""

    def replace(match: re.Match[str]) -> str:
        var_name = match.group(1)
        default = match.group(2) or ""
        env_value = os.getenv(var_name)
        return env_value if env_value is not None else default

    return _ENV_VAR_PATTERN.sub(replace, value)


def _expand_env_vars(data: Any) -> Any:
    """Recursively expand shell-style env vars in YAML-loaded objects."""
    if isinstance(data, dict):
        return {key: _expand_env_vars(value) for key, value in data.items()}
    if isinstance(data, list):
        return [_expand_env_vars(value) for value in data]
    if isinstance(data, tuple):
        return tuple(_expand_env_vars(value) for value in data)
    if isinstance(data, str):
        return _expand_string(data)
    return data


def _find_config_file(start: Path | None = None) -> Path | None:
    """Walk up directories looking for remora.yaml."""
    current = (start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent

    for directory in [current, *current.parents]:
        candidate = directory / "remora.yaml"
        if candidate.is_file():
            return candidate
    return None


def load_config(path: Path | None = None) -> Config:
    """Load config from remora.yaml, walking up directories when path is omitted."""
    config_path = path if path is not None else _find_config_file()
    if config_path is None:
        return Config()

    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return Config(**_expand_env_vars(data))


__all__ = ["Config", "load_config"]
