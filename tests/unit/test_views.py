from __future__ import annotations

from pathlib import Path


def _index_html() -> str:
    html_path = Path("src/remora/web/static/index.html")
    return html_path.read_text(encoding="utf-8")


def test_graph_html_renders() -> None:
    html = _index_html()
    assert isinstance(html, str)
    assert html.strip()
    assert '<div id="graph"' in html
    assert "Remora" in html


def test_graph_html_has_sse_client() -> None:
    html = _index_html()
    assert "EventSource('/sse')" in html or 'EventSource("/sse' in html


def test_graph_html_escapes_source_rendering() -> None:
    html = _index_html()
    assert "<pre>${node.text}</pre>" not in html
    assert "pre.textContent = node.text" in html


def test_graph_html_uses_batch_edge_endpoint() -> None:
    html = _index_html()
    assert '/api/edges' in html


def test_graph_html_uses_vendored_script_paths() -> None:
    html = _index_html()
    assert '<script src="/static/vendor/graphology.umd.min.js"></script>' in html
    assert '<script src="/static/vendor/sigma.min.js"></script>' in html
    assert "unpkg.com" not in html


def test_graph_html_uses_box_labels_and_structured_layout() -> None:
    html = _index_html()
    assert "function drawNodeBoxLabel(" in html
    assert "defaultDrawNodeLabel: drawNodeBoxLabel" in html
    assert "const LAYOUT = Object.freeze({" in html
    assert "WRAP_TARGET_WIDTH" in html
    assert "ROW_BAND_GAP" in html
    assert "OCCUPANCY_TARGET_MIN" in html
    assert "OCCUPANCY_TARGET_MAX" in html
    assert "FIT_MIN_MEDIAN_LABEL_PX" in html
    assert "FIT_MARGIN_LEFT_UNITS" in html
    assert 'const LAYOUT_MODE = "v6_core_peripheral";' in html
    assert "function layoutNodes(nodes, nodeById, edges)" in html
    assert "if (LAYOUT_MODE === \"v4_file_wrap\") {" in html
    assert "function computeConnectedComponents(nodes, edges)" in html
    assert "function componentScore(component, componentStats)" in html
    assert "function normalizeLayoutOccupancy(positions, nodeById)" in html
    assert "function layoutNodesV5Component(nodes, nodeById, edges)" in html
    assert "const coreComponents = [];" in html
    assert "function ensureUniqueDisplayLabels(nodes, nodeById)" in html
    assert "function commonWorkspacePathPrefix(paths)" in html
    assert "function workspaceRelativePath(path, workspacePrefix)" in html
    assert "function compressPathSegments(path, maxSegments = 4)" in html
    assert "PERIPHERAL_GRID_MIN_CELL_WIDTH" in html
    assert "function peripheralComponentCellWidth(component, nodeById)" in html
    assert "CORE_ZONE_MIN_VERTICAL_RATIO" in html
    assert "function computeZoneBounds(positions, zoneByNode, zone, nodeById)" in html
    assert "coreZoneBounds = layout.coreBounds || null;" in html
    assert "zoneSeparatorY = Number.isFinite(layout.separatorY) ? layout.separatorY : null;" in html
    assert "\"supporting nodes\"" in html
    assert "Math.max(0.12, 0.18 - depthFade * 0.08)" in html
    assert "Math.max(0.40, 0.56 - depthFade * 0.12)" in html
    assert "\"116, 132, 168\"" in html
    assert "fallback to deterministic hash suffix" in html
    assert "function colorWithAlpha(hex, alpha)" in html
    assert "length_norm" in html
    assert "function buildDirectorySet(nodes, nodeById)" in html
    assert "__synthetic_dir__:" in html
    assert "renderEdgeLabels: true" in html
    assert "enableEdgeEvents: true" in html
    assert "hideEdgesOnMove: true" in html
    assert "hideLabelsOnMove: true" in html
    assert "cameraPanBoundaries: true" in html
    assert "defaultDrawNodeHover: drawDiscNodeHover || undefined" in html
    assert 'renderer.on("enterEdge"' in html
    assert 'renderer.on("leaveEdge"' in html
    assert 'renderer.on("clickEdge"' in html
    assert "function showEdge(edgeId)" in html
    assert "layout_zone" in html
    assert "peripheral_color" in html
    assert "context_tether" in html
    assert "showContextTethers" in html
    assert 'data-filter-tethers="context"' in html
    assert "const rows = [];" in html
    assert 'data-filter-edge-emphasis="cross-file"' in html
    assert "edgeEmphasisCrossFileOnly" in html
    assert "renderer.setCustomBBox(bbox || null);" in html
    assert "camera.setState({ x: 0.5, y: 0.5, ratio: 1, angle: 0 });" not in html
    assert "const nodeLabelHitboxes = new Map();" in html
    assert 'renderer.on("clickStage"' in html
    assert "event.x * pixelRatio" in html
