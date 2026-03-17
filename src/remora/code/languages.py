"""Language plugin system for tree-sitter based discovery."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

import tree_sitter_markdown
import tree_sitter_python
import tree_sitter_toml
from tree_sitter import Language


class LanguagePlugin(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def extensions(self) -> list[str]: ...

    def get_language(self) -> Language: ...

    def get_default_query_path(self) -> Path: ...

    def resolve_node_type(self, ts_node: Any) -> str: ...


# Special-case plugins that need custom Python logic
ADVANCED_PLUGINS: dict[str, type] = {}


class PythonPlugin:
    @property
    def name(self) -> str:
        return "python"

    @property
    def extensions(self) -> list[str]:
        return [".py"]

    def get_language(self) -> Language:
        return Language(tree_sitter_python.language())

    def get_default_query_path(self) -> Path:
        from remora.defaults import default_queries_dir

        return default_queries_dir() / "python.scm"

    def resolve_node_type(self, ts_node: Any) -> str:
        if ts_node.type == "class_definition":
            return "class"
        if ts_node.type == "function_definition":
            return "method" if self._has_class_ancestor(ts_node) else "function"
        if ts_node.type == "decorated_definition":
            target = self._decorated_target(ts_node)
            if target and target.type == "class_definition":
                return "class"
            if target and target.type == "function_definition":
                return "method" if self._has_class_ancestor(ts_node) else "function"
        return "function"

    @staticmethod
    def _has_class_ancestor(node: Any) -> bool:
        current = node.parent
        while current is not None:
            if current.type == "class_definition":
                return True
            if current.type == "decorated_definition":
                for child in current.children:
                    if child.type == "class_definition":
                        return True
            current = current.parent
        return False

    @staticmethod
    def _decorated_target(node: Any) -> Any | None:
        for child in node.children:
            if child.type in {"function_definition", "class_definition"}:
                return child
        return None


class GenericLanguagePlugin:
    """Config-driven language plugin for simple languages."""

    def __init__(
        self,
        name: str,
        extensions: list[str],
        query_path: Path,
        node_type_rules: dict[str, str] | None = None,
        default_node_type: str = "function",
    ):
        self._name = name
        self._extensions = extensions
        self._query_path = query_path
        self._node_type_rules = node_type_rules or {}
        self._default_node_type = default_node_type

    @property
    def name(self) -> str:
        return self._name

    @property
    def extensions(self) -> list[str]:
        return self._extensions

    def get_language(self) -> Language:
        # Dynamic import: tree_sitter_{name}
        import importlib

        mod = importlib.import_module(f"tree_sitter_{self._name}")
        return Language(mod.language())

    def get_default_query_path(self) -> Path:
        return self._query_path

    def resolve_node_type(self, ts_node: Any) -> str:
        return self._node_type_rules.get(ts_node.type, self._default_node_type)


# Add PythonPlugin to advanced plugins after its definition
ADVANCED_PLUGINS["python"] = PythonPlugin


class MarkdownPlugin:
    @property
    def name(self) -> str:
        return "markdown"

    @property
    def extensions(self) -> list[str]:
        return [".md"]

    def get_language(self) -> Language:
        return Language(tree_sitter_markdown.language())

    def get_default_query_path(self) -> Path:
        from remora.defaults import default_queries_dir

        return default_queries_dir() / "markdown.scm"

    def resolve_node_type(self, ts_node: Any) -> str:
        del ts_node
        return "section"


class TomlPlugin:
    @property
    def name(self) -> str:
        return "toml"

    @property
    def extensions(self) -> list[str]:
        return [".toml"]

    def get_language(self) -> Language:
        return Language(tree_sitter_toml.language())

    def get_default_query_path(self) -> Path:
        from remora.defaults import default_queries_dir

        return default_queries_dir() / "toml.scm"

    def resolve_node_type(self, ts_node: Any) -> str:
        del ts_node
        return "table"


class LanguageRegistry:
    """Registry of language plugins, resolved by name or extension."""

    def __init__(self, plugins: list[LanguagePlugin] | None = None):
        self._by_name: dict[str, LanguagePlugin] = {}
        self._by_ext: dict[str, LanguagePlugin] = {}
        if plugins is not None:
            for plugin in plugins:
                self.register(plugin)

    def register(self, plugin: LanguagePlugin) -> None:
        self._by_name[plugin.name.lower()] = plugin
        for ext in plugin.extensions:
            self._by_ext[ext.lower()] = plugin

    def get_by_name(self, name: str) -> LanguagePlugin | None:
        return self._by_name.get(name.lower())

    def get_by_extension(self, ext: str) -> LanguagePlugin | None:
        return self._by_ext.get(ext.lower())

    @property
    def names(self) -> list[str]:
        return list(self._by_name.keys())

    @classmethod
    def from_config(
        cls,
        language_defs: dict[str, dict[str, Any]],
        query_search_paths: list[Path],
    ) -> LanguageRegistry:
        """Build a registry from YAML language definitions."""
        registry = cls(plugins=[])
        for lang_name, lang_config in language_defs.items():
            if lang_name in ADVANCED_PLUGINS:
                plugin = ADVANCED_PLUGINS[lang_name]()
            else:
                query_file = lang_config.get("query_file", f"{lang_name}.scm")
                query_path = _resolve_query_file(query_file, query_search_paths)
                plugin = GenericLanguagePlugin(
                    name=lang_name,
                    extensions=lang_config.get("extensions", []),
                    query_path=query_path,
                    node_type_rules=lang_config.get("node_type_rules"),
                    default_node_type=lang_config.get("default_node_type", "function"),
                )
            registry.register(plugin)
        return registry


def _resolve_query_file(filename: str, search_paths: list[Path]) -> Path:
    """Find a query file in the search paths."""
    for search_dir in search_paths:
        candidate = search_dir / filename
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Query file {filename} not found in {search_paths}")


__all__ = [
    "LanguagePlugin",
    "GenericLanguagePlugin",
    "PythonPlugin",
    "MarkdownPlugin",
    "TomlPlugin",
    "ADVANCED_PLUGINS",
    "LanguageRegistry",
]
