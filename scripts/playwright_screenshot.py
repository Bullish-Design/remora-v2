#!/usr/bin/env python3
"""Capture a screenshot of a URL using Playwright Chromium."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Target URL to capture.")
    parser.add_argument(
        "--out",
        required=True,
        help="Output PNG path.",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=1600,
        help="Viewport width in pixels (default: 1600).",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=900,
        help="Viewport height in pixels (default: 900).",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=30000,
        help="Navigation/selector timeout in milliseconds (default: 30000).",
    )
    parser.add_argument(
        "--wait-until",
        choices=["load", "domcontentloaded", "networkidle", "commit"],
        default="domcontentloaded",
        help="Playwright wait strategy for page.goto (default: domcontentloaded).",
    )
    parser.add_argument(
        "--selector",
        default=None,
        help="Optional selector to wait for before screenshot.",
    )
    parser.add_argument(
        "--full-page",
        action="store_true",
        help="Capture full page instead of viewport only.",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run Chromium headed (default: headless).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON output.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=not args.headed)
            context = browser.new_context(
                viewport={"width": args.width, "height": args.height}
            )
            page = context.new_page()
            page.goto(args.url, wait_until=args.wait_until, timeout=args.timeout_ms)
            if args.selector:
                page.wait_for_selector(args.selector, timeout=args.timeout_ms)
            page.screenshot(path=str(out_path), full_page=args.full_page)
            context.close()
            browser.close()
    except PlaywrightTimeoutError as exc:
        print(f"Timed out while capturing screenshot: {exc}")
        return 2
    except Exception as exc:  # pragma: no cover - environment dependent
        print(f"Screenshot capture failed: {exc}")
        return 1

    payload = {
        "ok": True,
        "url": args.url,
        "path": str(out_path),
        "bytes": out_path.stat().st_size,
    }
    if args.json:
        print(json.dumps(payload))
    else:
        print(f"Saved screenshot: {out_path} ({payload['bytes']} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
