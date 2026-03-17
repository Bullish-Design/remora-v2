from __future__ import annotations

from pathlib import Path

from tests.factories import write_file

from remora.code.watcher import FileWatcher
from remora.core.config import Config


def _config() -> Config:
    return Config(
        discovery_paths=("src",),
        discovery_languages=("python",),
        language_map={".py": "python"},
        query_search_paths=("@default",),
        workspace_root=".remora-reconcile",
        bundle_search_paths=("bundles",),
    )


def test_file_watcher_collect_file_mtimes(tmp_path: Path) -> None:
    source = tmp_path / "src" / "app.py"
    write_file(source, "def a():\n    return 1\n")

    watcher = FileWatcher(_config(), tmp_path)
    mtimes = watcher.collect_file_mtimes()

    assert str(source) in mtimes
    assert mtimes[str(source)] > 0
