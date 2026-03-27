#!/usr/bin/env python3
"""Create the backup Graph Boot + Event Time-Travel demo fixture project."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Set up the backup remora-v2 demo fixture project."
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path("/tmp/remora-demo-backup"),
        help="Target directory to create.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete project-root first if it already exists.",
    )
    return parser.parse_args()


def _validate_target(project_root: Path, force: bool) -> None:
    resolved = project_root.resolve()
    if resolved.exists():
        if not force:
            raise SystemExit(
                f"Refusing to overwrite existing directory: {resolved}\n"
                "Re-run with --force to replace it."
            )
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True, exist_ok=True)


def _create_fixture(project_root: Path) -> None:
    _write_text(
        project_root / "src/catalog/items.py",
        (
            "def item_price(sku: str) -> float:\n"
            "    pricing = {\"A-100\": 19.0, \"A-200\": 42.0, \"A-300\": 65.0}\n"
            "    return pricing.get(sku, 0.0)\n"
        ),
    )

    _write_text(
        project_root / "src/orders/quote.py",
        (
            "from catalog.items import item_price\n\n\n"
            "def quote_total(lines: list[tuple[str, int]]) -> float:\n"
            "    return sum(item_price(sku) * qty for sku, qty in lines)\n"
        ),
    )

    _write_text(
        project_root / "remora.yaml",
        (
            "project_path: \".\"\n"
            "discovery_paths:\n"
            "  - src\n"
            "discovery_languages:\n"
            "  - python\n"
            "language_map:\n"
            "  \".py\": \"python\"\n"
            "query_search_paths:\n"
            "  - \"@default\"\n"
            "bundle_search_paths:\n"
            "  - \"@default\"\n"
            "bundle_overlays:\n"
            "  function: \"code-agent\"\n"
            "  class: \"code-agent\"\n"
            "  method: \"code-agent\"\n"
            "  file: \"code-agent\"\n"
            "  directory: \"directory-agent\"\n\n"
            "workspace_root: \".remora-demo\"\n"
            "max_turns: 2\n\n"
            "runtime:\n"
            "  max_concurrency: 2\n"
            "  max_trigger_depth: 4\n"
            "  max_reactive_turns_per_correlation: 2\n"
            "  trigger_cooldown_ms: 300\n"
        ),
    )


def _print_next_steps(project_root: Path) -> None:
    print(f"Backup demo fixture created at: {project_root}")
    print()
    print("Start command:")
    print(
        "devenv shell -- remora start "
        f"--project-root {project_root} "
        f"--config {project_root / 'remora.yaml'} "
        "--port 8080 --bind 127.0.0.1 --log-level INFO --log-events"
    )
    print("Open: http://127.0.0.1:8080")


def main() -> int:
    args = _parse_args()
    project_root = args.project_root.resolve()
    _validate_target(project_root, args.force)
    _create_fixture(project_root)
    _print_next_steps(project_root)
    return 0


if __name__ == "__main__":
    sys.exit(main())

