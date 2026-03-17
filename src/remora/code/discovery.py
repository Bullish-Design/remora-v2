"""Tree-sitter discovery of code/content nodes across multiple languages."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict
from tree_sitter import Parser, Query, QueryCursor

from remora.code.languages import LanguagePlugin, LanguageRegistry
from remora.code.paths import walk_source_files


class CSTNode(BaseModel):
    """An immutable code/content element discovered from source."""

    model_config = ConfigDict(frozen=True)

    node_id: str
    node_type: str
    name: str
    full_name: str
    file_path: str
    text: str
    start_line: int
    end_line: int
    start_byte: int
    end_byte: int
    parent_id: str | None = None


_DEFAULT_LANGUAGE_MAP: dict[str, str] = {
    ".py": "python",
    ".md": "markdown",
    ".toml": "toml",
}


def discover(
    paths: list[Path],
    *,
    language_map: dict[str, str] | None = None,
    query_paths: list[Path] | None = None,
    ignore_patterns: tuple[str, ...] = (),
    languages: list[str] | None = None,
    language_registry: LanguageRegistry | None = None,
) -> list[CSTNode]:
    """Discover nodes in files using language-specific tree-sitter queries."""
    requested_languages = {name.lower() for name in languages} if languages else None
    effective_language_map = {
        ext.lower(): name.lower()
        for ext, name in (language_map or _DEFAULT_LANGUAGE_MAP).items()
    }
    effective_query_paths = [path.resolve() for path in (query_paths or [])]
    registry = language_registry or _get_language_registry()

    nodes: list[CSTNode] = []
    for source_file in walk_source_files(paths, ignore_patterns):
        ext = source_file.suffix.lower()
        language_name = effective_language_map.get(ext)
        if language_name is None:
            continue
        plugin = registry.get_by_name(language_name)
        if plugin is None:
            raise ValueError(
                f"Configured language '{language_name}' not found for extension '{ext}'"
            )
        if requested_languages is not None and plugin.name not in requested_languages:
            continue
        nodes.extend(_parse_file(source_file, plugin, effective_query_paths))

    return sorted(nodes, key=lambda node: (node.file_path, node.start_byte, node.node_id))


@lru_cache(maxsize=16)
def _get_registry_plugin(name: str) -> LanguagePlugin:
    plugin = _get_language_registry().get_by_name(name)
    if plugin is None:
        raise ValueError(f"Unknown language plugin: {name}")
    return plugin


@lru_cache(maxsize=1)
def _get_language_registry() -> LanguageRegistry:
    return LanguageRegistry()


@lru_cache(maxsize=16)
def _get_parser(language: str) -> Parser:
    plugin = _get_registry_plugin(language)
    return Parser(plugin.get_language())


@lru_cache(maxsize=64)
def _load_query(language: str, query_file: str) -> Query:
    plugin = _get_registry_plugin(language)
    query_text = Path(query_file).read_text(encoding="utf-8")
    return Query(plugin.get_language(), query_text)


def clear_caches() -> None:
    """Clear module-level discovery caches. Intended for tests."""
    _get_language_registry.cache_clear()
    _get_registry_plugin.cache_clear()
    _get_parser.cache_clear()
    _load_query.cache_clear()


def _resolve_query_file(plugin: LanguagePlugin, query_paths: list[Path]) -> Path:
    for query_dir in query_paths:
        candidate = query_dir / f"{plugin.name}.scm"
        if candidate.exists():
            return candidate

    default_candidate = plugin.get_default_query_path()
    if default_candidate.exists():
        return default_candidate
    raise FileNotFoundError(f"No query file found for language '{plugin.name}'")


def _parse_file(path: Path, plugin: LanguagePlugin, query_paths: list[Path]) -> list[CSTNode]:
    source_bytes = path.read_bytes()
    parser = _get_parser(plugin.name)
    tree = parser.parse(source_bytes)

    query_file = _resolve_query_file(plugin, query_paths)
    query = _load_query(plugin.name, str(query_file.resolve()))
    matches = QueryCursor(query).matches(tree.root_node)

    entries: list[dict[str, Any]] = []
    for _pattern_index, captures in matches:
        node_captures = captures.get("node", [])
        name_captures = captures.get("node.name", [])
        if not node_captures or not name_captures:
            continue
        node = node_captures[0]
        name_node = name_captures[0]
        name_text = _node_text(source_bytes, name_node).strip()
        if not name_text:
            continue
        entries.append({"node": node, "name_node": name_node, "name": name_text})

    if not entries:
        return []

    entries.sort(key=lambda entry: (entry["node"].start_byte, entry["node"].end_byte))
    by_key: dict[tuple[int, int, str], dict[str, Any]] = {}
    for entry in entries:
        key = _node_key(entry["node"])
        if key not in by_key:
            by_key[key] = entry

    parent_by_key: dict[tuple[int, int, str], tuple[int, int, str] | None] = {}
    name_by_key: dict[tuple[int, int, str], str] = {
        key: entry["name"] for key, entry in by_key.items()
    }

    for key, entry in by_key.items():
        parent_key: tuple[int, int, str] | None = None
        parent_node = entry["node"].parent
        while parent_node is not None:
            maybe_key = _node_key(parent_node)
            if maybe_key in by_key:
                parent_key = maybe_key
                break
            parent_node = parent_node.parent
        parent_by_key[key] = parent_key

    file_path = str(path)
    cst_nodes: list[CSTNode] = []
    seen_ids: set[str] = set()
    for key, entry in by_key.items():
        node = entry["node"]
        name_node = entry["name_node"]
        name = name_by_key[key]
        full_name = _build_name_from_tree(node, name_node, parent_by_key, name_by_key)
        parent_key = parent_by_key.get(key)
        parent_full_name = None
        if parent_key is not None:
            parent_entry = by_key[parent_key]
            parent_full_name = _build_name_from_tree(
                parent_entry["node"],
                parent_entry["name_node"],
                parent_by_key,
                name_by_key,
            )
        parent_id = f"{file_path}::{parent_full_name}" if parent_full_name else None
        candidate_id = f"{file_path}::{full_name}"
        if candidate_id in seen_ids:
            candidate_id = f"{file_path}::{full_name}@{node.start_byte}"
        seen_ids.add(candidate_id)

        cst_nodes.append(
            CSTNode(
                node_id=candidate_id,
                node_type=plugin.resolve_node_type(node),
                name=name,
                full_name=full_name,
                file_path=file_path,
                text=_node_text(source_bytes, node),
                start_line=node.start_point.row + 1,
                end_line=node.end_point.row + 1,
                start_byte=node.start_byte,
                end_byte=node.end_byte,
                parent_id=parent_id,
            )
        )

    return cst_nodes


def _build_name_from_tree(
    node: Any,
    name_node: Any,
    parent_by_key: dict[tuple[int, int, str], tuple[int, int, str] | None],
    name_by_key: dict[tuple[int, int, str], str],
) -> str:
    del name_node
    current_key = _node_key(node)
    parts = [name_by_key[current_key]]
    parent_key = parent_by_key.get(current_key)
    while parent_key is not None:
        parts.append(name_by_key[parent_key])
        parent_key = parent_by_key.get(parent_key)
    parts.reverse()
    return ".".join(parts)


def _node_text(source: bytes, node: Any) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _node_key(node: Any) -> tuple[int, int, str]:
    return (node.start_byte, node.end_byte, node.type)


__all__ = ["CSTNode", "clear_caches", "discover"]
