#!/usr/bin/env python3
"""Create the primary Event Storm Control Room demo fixture project."""

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
        description="Set up the primary remora-v2 demo fixture project."
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path("/tmp/remora-demo-storm"),
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
        project_root / "src/billing/pricing.py",
        (
            "def compute_total(subtotal: float, tax_rate: float = 0.07) -> float:\n"
            "    return round(subtotal * (1.0 + tax_rate), 2)\n\n\n"
            "def apply_discount(total: float, percent: float) -> float:\n"
            "    return round(total * (1.0 - percent), 2)\n"
        ),
    )

    _write_text(
        project_root / "src/billing/discounts.py",
        (
            "def discount_for_tier(tier: str) -> float:\n"
            "    if tier == \"gold\":\n"
            "        return 0.15\n"
            "    if tier == \"silver\":\n"
            "        return 0.08\n"
            "    return 0.0\n"
        ),
    )

    _write_text(
        project_root / "src/risk/policy.py",
        (
            "def requires_manual_review(order_total: float, country: str) -> bool:\n"
            "    if order_total > 1500:\n"
            "        return True\n"
            "    return country not in {\"US\", \"CA\", \"UK\"}\n"
        ),
    )

    _write_text(
        project_root / "src/api/checkout.py",
        (
            "from billing.pricing import compute_total, apply_discount\n"
            "from billing.discounts import discount_for_tier\n"
            "from risk.policy import requires_manual_review\n\n\n"
            "def checkout(subtotal: float, tier: str, country: str) -> dict:\n"
            "    total = compute_total(subtotal)\n"
            "    discounted = apply_discount(total, discount_for_tier(tier))\n"
            "    return {\n"
            "        \"total\": discounted,\n"
            "        \"manual_review\": requires_manual_review(discounted, country),\n"
            "    }\n"
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
            "model_base_url: \"${REMORA_DEMO_MODEL_URL:-http://remora-server:8000/v1}\"\n"
            "model_default: \"${REMORA_DEMO_MODEL_NAME:-Qwen/Qwen3-4B-Instruct-2507-FP8}\"\n"
            "model_api_key: \"${REMORA_TEST_MODEL_API_KEY:-EMPTY}\"\n"
            "timeout_s: 60\n"
            "max_turns: 6\n"
            "workspace_root: \".remora-demo\"\n\n"
            "runtime:\n"
            "  max_concurrency: 4\n"
            "  max_trigger_depth: 5\n"
            "  max_reactive_turns_per_correlation: 3\n"
            "  trigger_cooldown_ms: 200\n\n"
            "virtual_agents:\n"
            "  - id: review-agent\n"
            "    role: review-agent\n"
            "    subscriptions:\n"
            "      - event_types: [\"node_changed\"]\n"
            "        path_glob: \"src/**\"\n"
            "  - id: companion\n"
            "    role: companion\n"
            "    subscriptions:\n"
            "      - event_types: [\"turn_digested\"]\n"
        ),
    )


def _print_next_steps(project_root: Path) -> None:
    print(f"Primary demo fixture created at: {project_root}")
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

