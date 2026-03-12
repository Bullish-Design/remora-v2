"""Code plugin package."""

from remora.code.discovery import CSTNode, discover
from remora.code.languages import LanguageRegistry
from remora.code.paths import resolve_discovery_paths, resolve_query_paths, walk_source_files
from remora.code.projections import project_nodes
from remora.code.reconciler import FileReconciler

__all__ = [
    "CSTNode",
    "discover",
    "project_nodes",
    "FileReconciler",
    "LanguageRegistry",
    "resolve_discovery_paths",
    "resolve_query_paths",
    "walk_source_files",
]
