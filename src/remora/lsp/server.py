"""Thin pygls adapter for Remora graph data and events."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence
from urllib.parse import unquote, urlparse

from lsprotocol import types as lsp
from pygls.lsp.server import LanguageServer

from remora.core.events import ContentChangedEvent
from remora.core.node import Node


def create_lsp_server(
    node_store,
    event_store,
    workspace_service=None,
    db=None,
) -> LanguageServer:  # noqa: ANN001
    """Create an LSP server that projects Remora state into editor surfaces."""
    del workspace_service, db
    server = LanguageServer("remora", "2.0.0")

    @server.feature(lsp.TEXT_DOCUMENT_CODE_LENS)
    async def code_lens(params: lsp.CodeLensParams) -> list[lsp.CodeLens]:
        file_path = _uri_to_path(params.text_document.uri)
        nodes = await node_store.list_nodes(file_path=file_path)
        return [_node_to_lens(node) for node in nodes]

    @server.feature(lsp.TEXT_DOCUMENT_HOVER)
    async def hover(params: lsp.HoverParams) -> lsp.Hover | None:
        file_path = _uri_to_path(params.text_document.uri)
        nodes = await node_store.list_nodes(file_path=file_path)
        node = _find_node_at_line(nodes, params.position.line + 1)
        if node is None:
            return None
        return _node_to_hover(node)

    @server.feature(lsp.TEXT_DOCUMENT_DID_SAVE)
    async def did_save(params: lsp.DidSaveTextDocumentParams) -> None:
        file_path = _uri_to_path(params.text_document.uri)
        await event_store.append(ContentChangedEvent(path=file_path, change_type="modified"))

    @server.feature(lsp.TEXT_DOCUMENT_DID_OPEN)
    async def did_open(params: lsp.DidOpenTextDocumentParams) -> None:
        file_path = _uri_to_path(params.text_document.uri)
        await event_store.append(ContentChangedEvent(path=file_path, change_type="opened"))

    @server.feature(lsp.TEXT_DOCUMENT_DID_CHANGE)
    async def did_change(params: lsp.DidChangeTextDocumentParams) -> None:
        file_path = _uri_to_path(params.text_document.uri)
        new_text = _resolve_document_text(file_path, params.content_changes)
        path_obj = Path(file_path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        path_obj.write_text(new_text, encoding="utf-8")
        await event_store.append(ContentChangedEvent(path=file_path, change_type="modified"))
        if getattr(server, "_server", None) is not None:
            server.text_document_publish_diagnostics(
                lsp.PublishDiagnosticsParams(
                    uri=params.text_document.uri,
                    diagnostics=[],
                )
            )

    # Expose handlers for direct unit testing without spinning up an LSP transport.
    server._remora_handlers = {  # type: ignore[attr-defined]
        "code_lens": code_lens,
        "hover": hover,
        "did_save": did_save,
        "did_open": did_open,
        "did_change": did_change,
    }

    return server


def _node_to_lens(node: Node) -> lsp.CodeLens:
    """Map a Node to a CodeLens entry showing runtime status."""
    status = node.status.value if hasattr(node.status, "value") else str(node.status)
    return lsp.CodeLens(
        range=lsp.Range(
            start=lsp.Position(line=max(0, node.start_line - 1), character=0),
            end=lsp.Position(line=max(0, node.end_line - 1), character=0),
        ),
        command=lsp.Command(
            title=f"Remora: {status}",
            command="remora.showNode",
            arguments=[node.node_id],
        ),
        data={"node_id": node.node_id},
    )


def _node_to_hover(node: Node) -> lsp.Hover:
    """Map a Node to markdown hover details."""
    node_type = node.node_type.value if hasattr(node.node_type, "value") else str(node.node_type)
    status = node.status.value if hasattr(node.status, "value") else str(node.status)
    value = (
        f"### {node.full_name}\n"
        f"- Node ID: `{node.node_id}`\n"
        f"- Type: `{node_type}`\n"
        f"- Status: `{status}`\n"
        f"- File: `{node.file_path}:{node.start_line}-{node.end_line}`"
    )
    return lsp.Hover(
        contents=lsp.MarkupContent(
            kind=lsp.MarkupKind.Markdown,
            value=value,
        )
    )


def _find_node_at_line(nodes: list[Node], line: int) -> Node | None:
    """Find the narrowest node whose range contains the provided 1-based line."""
    containing = [node for node in nodes if node.start_line <= line <= node.end_line]
    if not containing:
        return None
    return min(containing, key=lambda node: node.end_line - node.start_line)


def _uri_to_path(uri: str) -> str:
    parsed = urlparse(uri)
    if parsed.scheme == "file":
        return str(Path(unquote(parsed.path)))
    return uri


def _resolve_document_text(
    file_path: str,
    changes: Sequence[lsp.TextDocumentContentChangeEvent],
) -> str:
    path = Path(file_path)
    current_text = path.read_text(encoding="utf-8") if path.exists() else ""
    if not changes:
        return current_text

    text = current_text
    for change in changes:
        change_text = getattr(change, "text", "") or ""
        range_value = getattr(change, "range", None)
        if range_value is None:
            text = change_text
            continue
        start = _position_to_offset(text, range_value.start)
        end = _position_to_offset(text, range_value.end)
        text = text[:start] + change_text + text[end:]
    return text


def _position_to_offset(text: str, position: lsp.Position) -> int:
    lines = text.splitlines(keepends=True)
    if not lines:
        lines = [""]
    line_index = min(position.line, len(lines) - 1)
    offset = sum(len(line) for line in lines[:line_index])
    line_text = lines[line_index]
    char_index = min(position.character, len(line_text))
    return offset + char_index


__all__ = ["create_lsp_server"]
