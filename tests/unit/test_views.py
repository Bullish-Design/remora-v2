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


def test_graph_html_uses_valid_cdn_script_paths() -> None:
    html = _index_html()
    assert "https://unpkg.com/sigma@3.0.0-beta.31/dist/sigma.min.js" in html
    assert (
        "https://unpkg.com/sigma@3.0.0-beta.31/build/sigma.min.js" not in html
    )
    assert (
        "https://unpkg.com/graphology-layout-forceatlas2@0.10.1/build/"
        "graphology-layout-forceatlas2.min.js"
        not in html
    )
