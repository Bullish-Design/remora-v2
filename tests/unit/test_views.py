from __future__ import annotations

from remora.web.views import GRAPH_HTML


def test_graph_html_renders() -> None:
    assert isinstance(GRAPH_HTML, str)
    assert GRAPH_HTML.strip()
    assert "<div id=\"graph\"" in GRAPH_HTML
    assert "Remora" in GRAPH_HTML


def test_graph_html_has_sse_client() -> None:
    assert "EventSource('/sse')" in GRAPH_HTML or 'EventSource("/sse")' in GRAPH_HTML


def test_graph_html_escapes_source_rendering() -> None:
    assert "<pre>${node.source_code}</pre>" not in GRAPH_HTML
    assert "pre.textContent = node.source_code" in GRAPH_HTML
