from __future__ import annotations

from pathlib import Path

from remora.code.paths import resolve_discovery_paths, resolve_query_paths, walk_source_files
from remora.core.config import Config


def test_resolve_paths_relative_to_project_root(tmp_path: Path) -> None:
    config = Config(discovery_paths=("src",), query_paths=("queries",))
    discovery = resolve_discovery_paths(config, tmp_path)
    queries = resolve_query_paths(config, tmp_path)
    assert discovery == [(tmp_path / "src").resolve()]
    assert queries == [(tmp_path / "queries").resolve()]


def test_walk_source_files_respects_ignore_patterns(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "a.py").write_text("print('a')\n", encoding="utf-8")
    ignored = tmp_path / ".git"
    ignored.mkdir(parents=True, exist_ok=True)
    (ignored / "hidden.py").write_text("print('x')\n", encoding="utf-8")

    files = walk_source_files([tmp_path], ignore_patterns=(".git",))
    paths = {p.relative_to(tmp_path).as_posix() for p in files}
    assert "src/a.py" in paths
    assert ".git/hidden.py" not in paths
