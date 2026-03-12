"""Tree-sitter discovery of code/content nodes across multiple languages."""

from __future__ import annotations

import fnmatch
from functools import lru_cache
from pathlib import Path
from typing import Any

import tree_sitter_markdown
import tree_sitter_python
import tree_sitter_toml
from pydantic import BaseModel, ConfigDict
from tree_sitter import Language, Parser, Query, QueryCursor


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


_GRAMMAR_REGISTRY: dict[str, Any] = {
    "python": tree_sitter_python,
    "markdown": tree_sitter_markdown,
    "toml": tree_sitter_toml,
}

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
) -> list[CSTNode]:
    """Discover nodes in files using language-specific tree-sitter queries."""
    requested_languages = {name.lower() for name in languages} if languages else None
    effective_language_map = {
        ext.lower(): name.lower()
        for ext, name in (language_map or _DEFAULT_LANGUAGE_MAP).items()
    }
    effective_query_paths = [path.resolve() for path in (query_paths or [])]

    nodes: list[CSTNode] = []
    for source_file in _walk_source_files(paths, ignore_patterns):
        language = _detect_language(source_file, effective_language_map)
        if language is None:
            continue
        if requested_languages is not None and language not in requested_languages:
            continue
        if language not in _GRAMMAR_REGISTRY:
            continue
        nodes.extend(_parse_file(source_file, language, effective_query_paths))

    return sorted(nodes, key=lambda node: (node.file_path, node.start_byte, node.node_id))


def _walk_source_files(paths: list[Path], ignore_patterns: tuple[str, ...]) -> list[Path]:
    """Collect source files while respecting ignore patterns."""
    discovered: list[Path] = []
    seen: set[Path] = set()
    normalized_patterns = tuple(pattern.strip() for pattern in ignore_patterns if pattern.strip())

    def ignored(path: Path) -> bool:
        text = path.as_posix()
        parts = set(path.parts)
        for pattern in normalized_patterns:
            if pattern in parts:
                return True
            if fnmatch.fnmatch(text, pattern) or fnmatch.fnmatch(path.name, pattern):
                return True
            if fnmatch.fnmatch(text, f"*/{pattern}/*"):
                return True
        return False

    for raw in paths:
        root = raw.resolve()
        if not root.exists():
            continue
        if root.is_file():
            if root not in seen and not ignored(root):
                seen.add(root)
                discovered.append(root)
            continue
        for candidate in root.rglob("*"):
            if not candidate.is_file():
                continue
            if ignored(candidate):
                continue
            if candidate not in seen:
                seen.add(candidate)
                discovered.append(candidate)

    return sorted(discovered)


def _detect_language(path: Path, language_map: dict[str, str]) -> str | None:
    """Resolve a file extension into a registered language name."""
    return language_map.get(path.suffix.lower())


@lru_cache(maxsize=16)
def _get_language(name: str) -> Language:
    module = _GRAMMAR_REGISTRY[name]
    return Language(module.language())


@lru_cache(maxsize=16)
def _get_parser(language: str) -> Parser:
    return Parser(_get_language(language))


@lru_cache(maxsize=64)
def _load_query(language: str, query_file: str) -> Query:
    query_text = Path(query_file).read_text(encoding="utf-8")
    return Query(_get_language(language), query_text)


def _resolve_query_file(language: str, query_paths: list[Path]) -> Path:
    for query_dir in query_paths:
        candidate = query_dir / f"{language}.scm"
        if candidate.exists():
            return candidate

    default_candidate = Path(__file__).parent / "queries" / f"{language}.scm"
    if default_candidate.exists():
        return default_candidate
    raise FileNotFoundError(f"No query file found for language '{language}'")


def _parse_file(path: Path, language: str, query_paths: list[Path]) -> list[CSTNode]:
    source_bytes = path.read_bytes()
    parser = _get_parser(language)
    tree = parser.parse(source_bytes)

    query_file = _resolve_query_file(language, query_paths)
    query = _load_query(language, str(query_file.resolve()))
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

        cst_nodes.append(
            CSTNode(
                node_id=f"{file_path}::{full_name}",
                node_type=_resolve_node_type(language, node),
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


def _resolve_node_type(language: str, node: Any) -> str:
    if language == "python":
        if node.type == "class_definition":
            return "class"
        if node.type == "function_definition":
            return "method" if _has_class_ancestor(node) else "function"
        if node.type == "decorated_definition":
            target = _decorated_target(node)
            if target is not None and target.type == "class_definition":
                return "class"
            if target is not None and target.type == "function_definition":
                return "method" if _has_class_ancestor(node) else "function"
            return "function"
        return "function"
    if language == "markdown":
        return "section"
    if language == "toml":
        return "table"
    return node.type


def _has_class_ancestor(node: Any) -> bool:
    current = node.parent
    while current is not None:
        if current.type in {"class_definition", "decorated_definition"}:
            target = _decorated_target(current)
            if current.type == "class_definition" or (
                target is not None and target.type == "class_definition"
            ):
                return True
        current = current.parent
    return False


def _decorated_target(node: Any) -> Any | None:
    for child in node.children:
        if child.type in {"function_definition", "class_definition"}:
            return child
    return None


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


__all__ = ["CSTNode", "discover"]
