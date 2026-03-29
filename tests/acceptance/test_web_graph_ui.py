from __future__ import annotations

import asyncio
import contextlib
import socket
import time
import uuid
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest
import pytest_asyncio
from tests.factories import write_file

from remora.__main__ import _configure_file_logging
from remora.core.model.config import load_config
from remora.core.services.lifecycle import RemoraLifecycle

playwright = pytest.importorskip("playwright.async_api")
expect = playwright.expect


def _reserve_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _write_graph_ui_project(root: Path) -> Path:
    write_file(
        root / "src" / "pricing.py",
        (
            "def apply_tax_rate(amount: float, rate: float = 0.07) -> float:\n"
            "    return amount * (1 + rate)\n\n"
            "def discount_for_tier(amount: float, tier: str = \"standard\") -> float:\n"
            "    return amount * (0.9 if tier == \"vip\" else 0.97)\n"
        ),
    )
    write_file(
        root / "src" / "orders.py",
        (
            "from pricing import apply_tax_rate, discount_for_tier\n"
            "from legacy_helpers import legacy_discount\n"
            "from observers.audit import AuditObserver\n\n"
            "class Order:\n"
            "    def total(self, subtotal: float) -> float:\n"
            "        discounted = discount_for_tier(subtotal, \"vip\")\n"
            "        taxed = apply_tax_rate(discounted)\n"
            "        observed = AuditObserver().notify(\"computed\")\n"
            "        if observed:\n"
            "            taxed = legacy_discount(taxed)\n"
            "        return round(taxed, 2)\n\n"
            "def apply_tax(amount: float) -> float:\n"
            "    return apply_tax_rate(amount)\n"
        ),
    )
    write_file(
        root / "src" / "legacy_helpers.py",
        (
            "def legacy_discount(amount: float) -> float:\n"
            "    return amount * 0.95\n"
        ),
    )
    write_file(
        root / "src" / "observers" / "__init__.py",
        "",
    )
    write_file(
        root / "src" / "observers" / "audit.py",
        (
            "class AuditObserver:\n"
            "    def notify(self, event: str) -> str:\n"
            "        return f\"audit:{event}\"\n"
        ),
    )

    bundles_root = root / "bundles"
    system = bundles_root / "system"
    code = bundles_root / "code-agent"
    (system / "tools").mkdir(parents=True, exist_ok=True)
    (code / "tools").mkdir(parents=True, exist_ok=True)
    write_file(system / "bundle.yaml", "name: system\nmax_turns: 4\n")
    write_file(code / "bundle.yaml", "name: code-agent\nmax_turns: 4\n")

    config_path = root / "remora.yaml"
    config_path.write_text(
        (
            "discovery_paths:\n"
            "  - src\n"
            "discovery_languages:\n"
            "  - python\n"
            "language_map:\n"
            "  .py: python\n"
            "query_search_paths:\n"
            "  - \"@default\"\n"
            "workspace_root: .remora-web-acceptance\n"
            "bundle_search_paths:\n"
            f"  - {bundles_root}\n"
            "  - \"@default\"\n"
            "max_turns: 4\n"
        ),
        encoding="utf-8",
    )
    return config_path


async def _wait_for_health(base_url: str, timeout_s: float = 20.0) -> None:
    deadline = time.monotonic() + timeout_s
    async with httpx.AsyncClient(base_url=base_url, timeout=2.0) as client:
        while time.monotonic() < deadline:
            try:
                response = await client.get("/api/health")
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.1)
    raise AssertionError(f"Runtime at {base_url} did not become healthy within {timeout_s}s")


async def _wait_for_nodes(base_url: str, timeout_s: float = 20.0) -> list[dict]:
    deadline = time.monotonic() + timeout_s
    async with httpx.AsyncClient(base_url=base_url, timeout=2.0) as client:
        while time.monotonic() < deadline:
            response = await client.get("/api/nodes")
            if response.status_code == 200:
                payload = response.json()
                if isinstance(payload, list) and payload:
                    return payload
            await asyncio.sleep(0.2)
    raise AssertionError("Timed out waiting for discovered graph nodes")


async def _wait_for_event(
    base_url: str,
    predicate,
    *,
    timeout_s: float = 20.0,
) -> dict:
    deadline = time.monotonic() + timeout_s
    async with httpx.AsyncClient(base_url=base_url, timeout=2.0) as client:
        while time.monotonic() < deadline:
            response = await client.get("/api/events?limit=200")
            assert response.status_code == 200
            payload = response.json()
            assert isinstance(payload, list)
            for event in payload:
                if predicate(event):
                    return event
            await asyncio.sleep(0.2)
    raise AssertionError("Timed out waiting for matching event")


@contextlib.asynccontextmanager
async def _running_runtime(*, project_root: Path, config_path: Path, port: int):
    config = load_config(config_path)
    lifecycle = RemoraLifecycle(
        config=config,
        project_root=project_root,
        bind="127.0.0.1",
        port=port,
        no_web=False,
        log_events=False,
        lsp=False,
        configure_file_logging=_configure_file_logging,
    )
    base_url = f"http://127.0.0.1:{port}"
    await lifecycle.start()
    await _wait_for_health(base_url)
    try:
        yield base_url
    finally:
        await asyncio.wait_for(lifecycle.shutdown(), timeout=20.0)


@pytest_asyncio.fixture
async def chromium_page():
    try:
        async with playwright.async_playwright() as session:
            browser = await session.chromium.launch(headless=True)
            context = await browser.new_context(viewport={"width": 1400, "height": 900})
            page = await context.new_page()
            try:
                yield page
            finally:
                await context.close()
                await browser.close()
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"Playwright/Chromium unavailable: {exc}")


@pytest.mark.asyncio
@pytest.mark.acceptance
async def test_web_graph_clicking_label_hitbox_selects_node_and_updates_sidebar(
    tmp_path: Path,
    chromium_page,
) -> None:
    config_path = _write_graph_ui_project(tmp_path)
    port = _reserve_port()

    async with _running_runtime(
        project_root=tmp_path,
        config_path=config_path,
        port=port,
    ) as base_url:
        await _wait_for_nodes(base_url)
        page = chromium_page
        await page.goto(base_url, wait_until="domcontentloaded")
        await page.wait_for_selector("#graph canvas")
        await page.wait_for_function(
            "() => typeof nodeLabelHitboxes !== 'undefined' && nodeLabelHitboxes.size > 0",
            timeout=20000,
        )

        selection = await page.evaluate(
            """
            async () => {
              if (typeof nodeLabelHitboxes === "undefined") return null;
              if (typeof graph === "undefined") return null;
              if (typeof renderer === "undefined") return null;
              const ratio = renderer.getRenderParams().pixelRatio || window.devicePixelRatio || 1;
              for (const [nodeId, box] of nodeLabelHitboxes.entries()) {
                if (!graph.hasNode(nodeId)) continue;
                if (graph.getNodeAttribute(nodeId, "node_type") === "__label__") continue;
                const response = await fetch(`/api/nodes/${encodeURIComponent(nodeId)}`);
                if (!response.ok) continue;
                const node = await response.json();
                return {
                  nodeId,
                  fullName: String(node.full_name || ""),
                  x: (box.x + box.width / 2) / ratio,
                  y: (box.y + box.height / 2) / ratio
                };
              }
              return null;
            }
            """
        )

        assert selection is not None
        assert selection["nodeId"]
        assert selection["fullName"]
        graph_box = await page.locator("#graph").bounding_box()
        assert graph_box is not None
        click_x = max(5.0, min(float(selection["x"]), graph_box["width"] - 5.0))
        click_y = max(5.0, min(float(selection["y"]), graph_box["height"] - 5.0))
        await page.locator("#graph").click(position={"x": click_x, "y": click_y})

        await expect(page.locator("#node-name")).to_have_text(selection["fullName"], timeout=15000)
        await expect(page.locator("#agent-header")).to_contain_text(selection["fullName"])


@pytest.mark.asyncio
@pytest.mark.acceptance
async def test_web_graph_has_visible_nodes_in_viewport_after_initial_load(
    tmp_path: Path,
    chromium_page,
) -> None:
    config_path = _write_graph_ui_project(tmp_path)
    port = _reserve_port()

    async with _running_runtime(
        project_root=tmp_path,
        config_path=config_path,
        port=port,
    ) as base_url:
        await _wait_for_nodes(base_url)
        page = chromium_page
        await page.goto(base_url, wait_until="domcontentloaded")
        await page.wait_for_selector("#graph canvas")
        await page.wait_for_function(
            "() => typeof graph !== 'undefined' && graph.order >= 2",
            timeout=20000,
        )
        await page.wait_for_function(
            "() => typeof window.__remora_layout_metrics === 'object' && !!window.__remora_layout_metrics && window.__remora_layout_metrics.ready === true",
            timeout=20000,
        )

        visibility = await page.evaluate(
            """
            () => {
              if (typeof graph === "undefined" || typeof renderer === "undefined") {
                return { total: 0, visible: 0, reason: "missing_runtime" };
              }
              const dims = renderer.getDimensions();
              const nodes = graph.nodes();
              let total = 0;
              let visible = 0;
              let absoluteLabelCount = 0;
              const labelCounts = new Map();
              const zoneCounts = { core: 0, peripheral: 0 };
              const makeBox = () => ({
                minX: Number.POSITIVE_INFINITY,
                minY: Number.POSITIVE_INFINITY,
                maxX: Number.NEGATIVE_INFINITY,
                maxY: Number.NEGATIVE_INFINITY,
                count: 0,
              });
              const extendBox = (box, point) => {
                box.minX = Math.min(box.minX, point.x);
                box.minY = Math.min(box.minY, point.y);
                box.maxX = Math.max(box.maxX, point.x);
                box.maxY = Math.max(box.maxY, point.y);
                box.count += 1;
              };
              const boxArea = (box) => {
                if (!box || box.count <= 0) return 0;
                const w = Math.max(1, box.maxX - box.minX);
                const h = Math.max(1, box.maxY - box.minY);
                return w * h;
              };
              const overallBox = makeBox();
              const zoneBoxes = {
                core: makeBox(),
                peripheral: makeBox(),
              };
              const absolutePathPattern = /^(\\/|[a-zA-Z]:[\\\\/])/;
              for (const nodeId of nodes) {
                const attrs = graph.getNodeAttributes(nodeId);
                if (attrs.hidden) continue;
                total += 1;
                const label = String(attrs.label || "");
                labelCounts.set(label, (labelCounts.get(label) || 0) + 1);
                if (absolutePathPattern.test(label)) absoluteLabelCount += 1;
                const p = renderer.graphToViewport({ x: attrs.x, y: attrs.y });
                extendBox(overallBox, p);
                const zone = attrs.layout_zone === "peripheral" ? "peripheral" : "core";
                zoneCounts[zone] += 1;
                extendBox(zoneBoxes[zone], p);
                if (p.x >= 0 && p.x <= dims.width && p.y >= 0 && p.y <= dims.height) {
                  visible += 1;
                }
              }

              const viewportArea = Math.max(1, dims.width * dims.height);
              const duplicates = [...labelCounts.values()].filter((count) => count > 1).length;

              const boxes =
                typeof nodeLabelHitboxes !== "undefined"
                  ? [...nodeLabelHitboxes.entries()]
                      .filter(([nodeId]) => graph.hasNode(nodeId) && !graph.getNodeAttribute(nodeId, "hidden"))
                      .map(([, box]) => box)
                  : [];
              let areaSum = 0;
              let overlapArea = 0;
              for (let i = 0; i < boxes.length; i++) {
                const a = boxes[i];
                const aArea = Math.max(0, a.width) * Math.max(0, a.height);
                areaSum += aArea;
                for (let j = i + 1; j < boxes.length; j++) {
                  const b = boxes[j];
                  const left = Math.max(a.x, b.x);
                  const top = Math.max(a.y, b.y);
                  const right = Math.min(a.x + a.width, b.x + b.width);
                  const bottom = Math.min(a.y + a.height, b.y + b.height);
                  const w = Math.max(0, right - left);
                  const h = Math.max(0, bottom - top);
                  overlapArea += w * h;
                }
              }
              const overallZoneArea = boxArea(overallBox);
              const coreZoneArea = boxArea(zoneBoxes.core);
              const peripheralZoneArea = boxArea(zoneBoxes.peripheral);
              const overlapRatio = areaSum > 0 ? overlapArea / areaSum : 0;
              const occupancy =
                areaSum > 0
                  ? Math.min(1, areaSum / viewportArea)
                  : (overallZoneArea > 0 ? Math.min(1, overallZoneArea / viewportArea) : 0);
              const coreZoneOccupancy = overallZoneArea > 0 ? coreZoneArea / overallZoneArea : 0;
              const peripheralZoneFootprint = overallZoneArea > 0 ? peripheralZoneArea / overallZoneArea : 0;
              const overallZoneHeight = Math.max(1, overallBox.maxY - overallBox.minY);
              const coreZoneHeight = zoneBoxes.core.count > 0 ? Math.max(1, zoneBoxes.core.maxY - zoneBoxes.core.minY) : 0;
              const coreZoneVerticalShare = coreZoneHeight / overallZoneHeight;
              const coreCentroidX =
                zoneBoxes.core.count > 0
                  ? (zoneBoxes.core.minX + zoneBoxes.core.maxX) / 2
                  : dims.width / 2;
              const coreCentroidY =
                zoneBoxes.core.count > 0
                  ? (zoneBoxes.core.minY + zoneBoxes.core.maxY) / 2
                  : dims.height / 2;
              const coreCentroidXRatio = dims.width > 0 ? coreCentroidX / dims.width : 0.5;
              const coreCentroidYRatio = dims.height > 0 ? coreCentroidY / dims.height : 0.5;
              const zoneGapPx =
                zoneBoxes.core.count > 0 && zoneBoxes.peripheral.count > 0
                  ? zoneBoxes.peripheral.minY - zoneBoxes.core.maxY
                  : 0;
              const zoneGapRatio = overallZoneHeight > 0 ? zoneGapPx / overallZoneHeight : 0;

              const peripheralBoxes =
                typeof nodeLabelHitboxes !== "undefined"
                  ? [...nodeLabelHitboxes.entries()]
                      .filter(([nodeId]) => {
                        if (!graph.hasNode(nodeId)) return false;
                        const attrs = graph.getNodeAttributes(nodeId);
                        return !attrs.hidden && attrs.layout_zone === "peripheral";
                      })
                      .map(([, box]) => box)
                  : [];
              let peripheralAreaSum = 0;
              let peripheralOverlapArea = 0;
              for (let i = 0; i < peripheralBoxes.length; i++) {
                const a = peripheralBoxes[i];
                peripheralAreaSum += Math.max(0, a.width) * Math.max(0, a.height);
                for (let j = i + 1; j < peripheralBoxes.length; j++) {
                  const b = peripheralBoxes[j];
                  const left = Math.max(a.x, b.x);
                  const top = Math.max(a.y, b.y);
                  const right = Math.min(a.x + a.width, b.x + b.width);
                  const bottom = Math.min(a.y + a.height, b.y + b.height);
                  peripheralOverlapArea += Math.max(0, right - left) * Math.max(0, bottom - top);
                }
              }
              const peripheralLabelOverlapRatio =
                peripheralAreaSum > 0 ? peripheralOverlapArea / peripheralAreaSum : 0;

              const edges = graph.edges();
              let edgeTotal = 0;
              let edgeSpanVisible = 0;
              let primaryChainEdgeCount = 0;
              let emphasizedEdgeCount = 0;
              for (const edgeId of edges) {
                const attrs = graph.getEdgeAttributes(edgeId);
                if (attrs.hidden) continue;
                const [sourceId, targetId] = graph.extremities(edgeId);
                if (!graph.hasNode(sourceId) || !graph.hasNode(targetId)) continue;
                const source = graph.getNodeAttributes(sourceId);
                const target = graph.getNodeAttributes(targetId);
                if (source.hidden || target.hidden) continue;
                edgeTotal += 1;
                const p1 = renderer.graphToViewport({ x: source.x, y: source.y });
                const p2 = renderer.graphToViewport({ x: target.x, y: target.y });
                const span = Math.hypot(p1.x - p2.x, p1.y - p2.y);
                if (span > 4) edgeSpanVisible += 1;
                if (attrs.is_primary_chain) primaryChainEdgeCount += 1;
                const display = typeof renderer.getEdgeDisplayData === "function"
                  ? renderer.getEdgeDisplayData(edgeId)
                  : null;
                const displaySize = Number(display?.size ?? attrs.size ?? 0);
                if (displaySize > 2.6) emphasizedEdgeCount += 1;
              }

              const renderEdgeLabelsEnabled =
                typeof renderer.getSetting === "function"
                  ? renderer.getSetting("renderEdgeLabels")
                  : null;
              const enableEdgeEventsEnabled =
                typeof renderer.getSetting === "function"
                  ? renderer.getSetting("enableEdgeEvents")
                  : null;
              const pixelRatio = renderer.getRenderParams().pixelRatio || window.devicePixelRatio || 1;
              const filterBar = document.getElementById("filter-bar");
              const filterRect = filterBar ? filterBar.getBoundingClientRect() : null;
              let coreClippedByViewportCount = 0;
              let coreOccludedByFilterCount = 0;
              if (typeof nodeLabelHitboxes !== "undefined") {
                for (const [nodeId, box] of nodeLabelHitboxes.entries()) {
                  if (!graph.hasNode(nodeId)) continue;
                  const attrs = graph.getNodeAttributes(nodeId);
                  if (attrs.hidden || attrs.layout_zone === "peripheral") continue;
                  const left = box.x / pixelRatio;
                  const top = box.y / pixelRatio;
                  const right = (box.x + box.width) / pixelRatio;
                  const bottom = (box.y + box.height) / pixelRatio;
                  const clipped =
                    left < 0 || top < 0 || right > dims.width || bottom > dims.height;
                  if (clipped) coreClippedByViewportCount += 1;
                  if (filterRect) {
                    const overlapW = Math.max(0, Math.min(right, filterRect.right) - Math.max(left, filterRect.left));
                    const overlapH = Math.max(0, Math.min(bottom, filterRect.bottom) - Math.max(top, filterRect.top));
                    if (overlapW > 0 && overlapH > 0) coreOccludedByFilterCount += 1;
                  }
                }
              }
              const sidebar = document.getElementById("sidebar");
              const sidebarWidthRatio =
                sidebar && window.innerWidth > 0
                  ? sidebar.getBoundingClientRect().width / window.innerWidth
                  : 0;
              const runtimeMetrics =
                typeof window.__remora_layout_metrics === "object" &&
                window.__remora_layout_metrics !== null
                  ? window.__remora_layout_metrics
                  : {};
              let applyTaxZone = null;
              for (const nodeId of nodes) {
                if (!String(nodeId).includes("apply_tax")) continue;
                const attrs = graph.getNodeAttributes(nodeId);
                applyTaxZone = attrs.layout_zone || null;
                break;
              }

              return {
                total,
                visible,
                occupancy,
                duplicate_labels: duplicates,
                absolute_label_count: absoluteLabelCount,
                core_zone_nodes: zoneCounts.core,
                peripheral_zone_nodes: zoneCounts.peripheral,
                core_zone_occupancy: coreZoneOccupancy,
                core_zone_vertical_share: coreZoneVerticalShare,
                core_centroid_x_ratio: coreCentroidXRatio,
                core_centroid_y_ratio: coreCentroidYRatio,
                zone_gap_px: zoneGapPx,
                zone_gap_ratio: zoneGapRatio,
                peripheral_zone_footprint: peripheralZoneFootprint,
                peripheral_label_overlap_ratio: peripheralLabelOverlapRatio,
                overlap_ratio: overlapRatio,
                edge_total: edgeTotal,
                edge_span_visible: edgeSpanVisible,
                primary_chain_edge_count: primaryChainEdgeCount,
                emphasized_edge_count: emphasizedEdgeCount,
                render_edge_labels_enabled: renderEdgeLabelsEnabled,
                enable_edge_events_enabled: enableEdgeEventsEnabled,
                core_clipped_label_count: coreClippedByViewportCount,
                core_occluded_by_filter_count: coreOccludedByFilterCount,
                sidebar_width_ratio: sidebarWidthRatio,
                apply_tax_zone: applyTaxZone,
                runtime_layout_metrics_ready: !!runtimeMetrics.ready,
                runtime_core_label_clipped_count:
                  Number.isFinite(runtimeMetrics.core_label_clipped_count)
                    ? runtimeMetrics.core_label_clipped_count
                    : null,
                runtime_core_occluded_by_filter_count:
                  Number.isFinite(runtimeMetrics.core_occluded_by_filter_count)
                    ? runtimeMetrics.core_occluded_by_filter_count
                    : null,
                runtime_core_centroid_x_ratio:
                  Number.isFinite(runtimeMetrics.core_centroid_x_ratio)
                    ? runtimeMetrics.core_centroid_x_ratio
                    : null,
                runtime_core_centroid_y_ratio:
                  Number.isFinite(runtimeMetrics.core_centroid_y_ratio)
                    ? runtimeMetrics.core_centroid_y_ratio
                    : null,
                runtime_zone_gap_ratio:
                  Number.isFinite(runtimeMetrics.zone_gap_ratio)
                    ? runtimeMetrics.zone_gap_ratio
                    : null,
                runtime_separator_visible: runtimeMetrics.separator_visible === true,
              };
            }
            """
        )

        assert visibility["total"] > 0, visibility
        assert visibility["visible"] > 0, visibility
        assert visibility["occupancy"] >= 0.002, visibility
        assert visibility["occupancy"] <= 0.92, visibility
        assert visibility["duplicate_labels"] == 0, visibility
        assert visibility["absolute_label_count"] == 0, visibility
        assert visibility["overlap_ratio"] < 0.45, visibility
        assert visibility["core_zone_nodes"] > 0, visibility
        assert visibility["core_zone_vertical_share"] >= 0.55, visibility
        assert 0.30 <= visibility["core_centroid_x_ratio"] <= 0.62, visibility
        assert 0.14 <= visibility["core_centroid_y_ratio"] <= 0.58, visibility
        assert visibility["zone_gap_px"] >= 10, visibility
        assert visibility["zone_gap_ratio"] <= 0.34, visibility
        assert visibility["peripheral_label_overlap_ratio"] < 0.02, visibility
        if visibility["peripheral_zone_nodes"] > 0:
            assert visibility["core_zone_occupancy"] >= 0.02, visibility
            assert visibility["peripheral_zone_footprint"] <= 0.95, visibility
        assert visibility["primary_chain_edge_count"] > 0, visibility
        assert visibility["emphasized_edge_count"] > 0, visibility
        assert visibility["render_edge_labels_enabled"] is True, visibility
        assert visibility["enable_edge_events_enabled"] is True, visibility
        assert visibility["core_clipped_label_count"] >= 0, visibility
        assert visibility["core_occluded_by_filter_count"] == 0, visibility
        assert visibility["sidebar_width_ratio"] <= 0.315, visibility
        assert visibility["runtime_layout_metrics_ready"] is True, visibility
        assert visibility["runtime_core_label_clipped_count"] is not None, visibility
        assert abs(
            visibility["runtime_core_label_clipped_count"] - visibility["core_clipped_label_count"]
        ) <= 1, visibility
        assert visibility["runtime_core_occluded_by_filter_count"] == visibility["core_occluded_by_filter_count"], visibility
        assert visibility["runtime_separator_visible"] is True, visibility
        assert visibility["runtime_core_centroid_x_ratio"] is not None, visibility
        assert visibility["runtime_core_centroid_y_ratio"] is not None, visibility
        assert visibility["runtime_zone_gap_ratio"] is not None, visibility
        assert abs(
            visibility["runtime_core_centroid_x_ratio"] - visibility["core_centroid_x_ratio"]
        ) <= 0.08, visibility
        assert abs(
            visibility["runtime_core_centroid_y_ratio"] - visibility["core_centroid_y_ratio"]
        ) <= 0.08, visibility
        assert abs(visibility["runtime_zone_gap_ratio"] - visibility["zone_gap_ratio"]) <= 0.10, visibility
        if visibility["apply_tax_zone"] is not None:
            assert visibility["apply_tax_zone"] in {"core", "peripheral"}, visibility
        if visibility["edge_total"] > 0:
            assert visibility["edge_span_visible"] > 0, visibility


@pytest.mark.asyncio
@pytest.mark.acceptance
async def test_web_graph_sidebar_send_updates_events_and_timeline(
    tmp_path: Path,
    chromium_page,
) -> None:
    config_path = _write_graph_ui_project(tmp_path)
    port = _reserve_port()

    async with _running_runtime(
        project_root=tmp_path,
        config_path=config_path,
        port=port,
    ) as base_url:
        nodes = await _wait_for_nodes(base_url)
        function_node = next(
            (node for node in nodes if node.get("node_type") == "function"),
            nodes[0],
        )
        node_id = str(function_node.get("node_id", "")).strip()
        expected_name = str(function_node.get("name", "")).strip() or node_id.split("::")[-1]
        assert node_id

        page = chromium_page
        await page.goto(
            f"{base_url}/?node={quote(node_id, safe='')}",
            wait_until="domcontentloaded",
        )
        await expect(page.locator("#agent-header")).to_contain_text(
            expected_name,
            timeout=15000,
        )

        token = f"ui-message-{uuid.uuid4().hex[:8]}"
        await page.fill("#chat-input", token)
        await page.click("#send-chat")

        await expect(page.locator("#events")).to_contain_text("agent_message", timeout=15000)
        await expect(page.locator("#timeline-container")).to_contain_text(
            "agent_message",
            timeout=15000,
        )
        await expect(page.locator("#timeline-container")).to_contain_text(token, timeout=15000)

        await _wait_for_event(
            base_url,
            lambda event: (
                event.get("event_type") == "agent_message"
                and event.get("payload", {}).get("to_agent") == node_id
                and event.get("payload", {}).get("content") == token
            ),
        )


@pytest.mark.asyncio
@pytest.mark.acceptance
async def test_web_graph_sse_status_indicator_changes_on_error_and_recovery(
    tmp_path: Path,
    chromium_page,
) -> None:
    config_path = _write_graph_ui_project(tmp_path)
    port = _reserve_port()

    async with _running_runtime(
        project_root=tmp_path,
        config_path=config_path,
        port=port,
    ) as base_url:
        page = chromium_page
        await page.add_init_script(
            """
            (() => {
              const NativeEventSource = window.EventSource;
              window.__remora_event_sources = [];
              function WrappedEventSource(...args) {
                const es = new NativeEventSource(...args);
                window.__remora_event_sources.push(es);
                return es;
              }
              WrappedEventSource.prototype = NativeEventSource.prototype;
              WrappedEventSource.CONNECTING = NativeEventSource.CONNECTING;
              WrappedEventSource.OPEN = NativeEventSource.OPEN;
              WrappedEventSource.CLOSED = NativeEventSource.CLOSED;
              window.EventSource = WrappedEventSource;
            })();
            """
        )
        await page.goto(base_url, wait_until="domcontentloaded")
        await page.wait_for_selector("#connection-status.connected", timeout=15000)
        await page.wait_for_function(
            "() => window.__remora_event_sources && window.__remora_event_sources.length > 0"
        )

        errored = await page.evaluate(
            """
            () => {
              const es = window.__remora_event_sources?.[0];
              if (!es || typeof es.onerror !== "function") return false;
              es.onerror(new Event("error"));
              return true;
            }
            """
        )
        assert errored is True
        await page.wait_for_selector("#connection-status.disconnected", timeout=15000)

        reopened = await page.evaluate(
            """
            () => {
              const es = window.__remora_event_sources?.[0];
              if (!es || typeof es.onopen !== "function") return false;
              es.onopen(new Event("open"));
              return true;
            }
            """
        )
        assert reopened is True
        await page.wait_for_selector("#connection-status.connected", timeout=15000)
