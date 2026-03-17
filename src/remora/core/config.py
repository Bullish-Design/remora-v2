"""Project-level configuration."""

from __future__ import annotations

import os
import re
from enum import StrEnum
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from remora.core.types import NodeType, serialize_enum

_ENV_VAR_PATTERN = re.compile(r"\$\{([^}:]+)(?::-([^}]*))?\}")
_VALID_PROMPT_KEYS = frozenset({"chat", "reactive"})


class VirtualSubscriptionConfig(BaseModel):
    """Declarative subscription pattern for a virtual agent."""

    event_types: tuple[str, ...] | None = None
    from_agents: tuple[str, ...] | None = None
    to_agent: str | None = None
    path_glob: str | None = None
    tags: tuple[str, ...] | None = None


class VirtualAgentConfig(BaseModel):
    """Declarative virtual agent definition."""

    id: str
    role: str
    subscriptions: tuple[VirtualSubscriptionConfig, ...] = ()

    @field_validator("id", "role")
    @classmethod
    def _validate_non_empty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("virtual agent id/role must be non-empty")
        return cleaned


class BundleOverlayRule(BaseModel):
    """Bundle resolution rule matching node type and optional name glob."""

    node_type: str
    name_pattern: str | None = None
    bundle: str

    @field_validator("node_type", "bundle")
    @classmethod
    def _validate_required_values(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("bundle overlay rule values must be non-empty")
        return cleaned


class SearchMode(StrEnum):
    REMOTE = "remote"
    LOCAL = "local"


class SearchConfig(BaseModel):
    """Configuration for semantic search via embeddy."""

    enabled: bool = False
    mode: SearchMode = SearchMode.REMOTE
    embeddy_url: str = "http://localhost:8585"
    timeout: float = 30.0
    default_collection: str = "code"
    collection_map: dict[str, str] = Field(
        default_factory=lambda: {
            ".py": "code",
            ".md": "docs",
            ".toml": "config",
            ".yaml": "config",
            ".yml": "config",
            ".json": "config",
        }
    )
    # Local mode settings
    db_path: str = ".remora/embeddy.db"
    model_name: str = "Qwen/Qwen3-VL-Embedding-2B"
    embedding_dimension: int = 2048


class SelfReflectConfig(BaseModel):
    """Self-reflection configuration within a bundle."""

    enabled: bool = False
    model: str | None = None
    max_turns: int = 2
    prompt: str | None = None

    @field_validator("max_turns")
    @classmethod
    def _validate_max_turns(cls, value: int) -> int:
        return max(1, value)


class BundleConfig(BaseModel):
    """Agent bundle configuration loaded from bundle.yaml."""

    system_prompt: str = "You are an autonomous code agent."
    system_prompt_extension: str = ""
    model: str | None = None
    max_turns: int = 8
    prompts: dict[str, str] = Field(default_factory=dict)
    self_reflect: SelfReflectConfig | None = None

    @field_validator("max_turns")
    @classmethod
    def _validate_max_turns(cls, value: int) -> int:
        return max(1, value)

    @field_validator("prompts")
    @classmethod
    def _validate_prompts(cls, value: dict[str, str]) -> dict[str, str]:
        unknown = set(value) - _VALID_PROMPT_KEYS
        if unknown:
            valid_keys = ", ".join(sorted(_VALID_PROMPT_KEYS))
            unknown_keys = ", ".join(sorted(unknown))
            raise ValueError(f"Unknown prompt keys: {unknown_keys}. Valid keys: {valid_keys}")
        return {k: v for k, v in value.items() if v.strip()}


class Config(BaseSettings):
    """Remora configuration loaded from remora.yaml and environment variables."""

    model_config = SettingsConfigDict(env_prefix="REMORA_", frozen=True, populate_by_name=True)

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
    bundle_overlays: dict[str, str] = Field(
        default_factory=lambda: {
            "function": "code-agent",
            "class": "code-agent",
            "method": "code-agent",
            "directory": "directory-agent",
        }
    )
    bundle_rules: tuple[BundleOverlayRule, ...] = ()

    # LLM
    model_base_url: str = "http://localhost:8000/v1"
    model_default: str = "Qwen/Qwen3-4B"
    model_api_key: str = ""
    timeout_s: float = 300.0
    max_turns: int = 8

    # Agent execution
    workspace_root: str = ".remora"
    max_concurrency: int = 4
    max_trigger_depth: int = 5
    trigger_cooldown_ms: int = 1000
    human_input_timeout_s: float = 300.0
    search_content_max_matches: int = 1000
    broadcast_max_targets: int = 50
    actor_idle_timeout_s: float = 300.0
    send_message_rate_limit: int = 10
    send_message_rate_window_s: float = 1.0

    # Search (optional embeddy integration)
    search: SearchConfig = Field(default_factory=SearchConfig)

    # Workspace
    workspace_ignore_patterns: tuple[str, ...] = (
        ".git",
        ".venv",
        "__pycache__",
        "node_modules",
        ".remora",
    )
    virtual_agents: tuple[VirtualAgentConfig, ...] = ()

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

    @field_validator("virtual_agents")
    @classmethod
    def _validate_virtual_agents(
        cls, value: tuple[VirtualAgentConfig, ...]
    ) -> tuple[VirtualAgentConfig, ...]:
        seen: set[str] = set()
        for item in value:
            if item.id in seen:
                raise ValueError(f"Duplicate virtual agent id: {item.id}")
            seen.add(item.id)
        return value

    def resolve_bundle(self, node_type: NodeType | str, node_name: str | None = None) -> str | None:
        """Resolve bundle by priority: first matching rule, then type overlays."""
        normalized_type = serialize_enum(node_type)
        normalized_name = node_name or ""

        for rule in self.bundle_rules:
            if rule.node_type != normalized_type:
                continue
            if rule.name_pattern is None or fnmatch(normalized_name, rule.name_pattern):
                return rule.bundle

        return self.bundle_overlays.get(normalized_type)


def expand_string(value: str) -> str:
    """Expand ${VAR:-default} shell-style values."""

    def replace(match: re.Match[str]) -> str:
        var_name = match.group(1)
        default = match.group(2) or ""
        env_value = os.getenv(var_name)
        return env_value if env_value is not None else default

    return _ENV_VAR_PATTERN.sub(replace, value)


def expand_env_vars(data: Any) -> Any:
    """Recursively expand shell-style env vars in YAML-loaded objects."""
    if isinstance(data, dict):
        return {key: expand_env_vars(value) for key, value in data.items()}
    if isinstance(data, list):
        return [expand_env_vars(value) for value in data]
    if isinstance(data, tuple):
        return tuple(expand_env_vars(value) for value in data)
    if isinstance(data, str):
        return expand_string(data)
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
    return Config(**expand_env_vars(data))


__all__ = [
    "BundleConfig",
    "BundleOverlayRule",
    "SearchConfig",
    "SearchMode",
    "SelfReflectConfig",
    "VirtualSubscriptionConfig",
    "VirtualAgentConfig",
    "Config",
    "expand_env_vars",
    "expand_string",
    "load_config",
]
