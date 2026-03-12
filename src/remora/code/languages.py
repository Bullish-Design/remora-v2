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
    def name(self) -> str:
        ...

    @property
    def extensions(self) -> list[str]:
        ...

    def get_language(self) -> Language:
        ...

    def get_default_query_path(self) -> Path:
        ...

    def resolve_node_type(self, ts_node: Any) -> str:
        ...


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
        return Path(__file__).parent / "queries" / "python.scm"

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
        return Path(__file__).parent / "queries" / "markdown.scm"

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
        return Path(__file__).parent / "queries" / "toml.scm"

    def resolve_node_type(self, ts_node: Any) -> str:
        del ts_node
        return "table"


BUILTIN_PLUGINS: list[LanguagePlugin] = [PythonPlugin(), MarkdownPlugin(), TomlPlugin()]


class LanguageRegistry:
    """Registry of language plugins, resolved by name or extension."""

    def __init__(self, plugins: list[LanguagePlugin] | None = None):
        self._by_name: dict[str, LanguagePlugin] = {}
        self._by_ext: dict[str, LanguagePlugin] = {}
        for plugin in (plugins or BUILTIN_PLUGINS):
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


__all__ = [
    "LanguagePlugin",
    "PythonPlugin",
    "MarkdownPlugin",
    "TomlPlugin",
    "BUILTIN_PLUGINS",
    "LanguageRegistry",
]
