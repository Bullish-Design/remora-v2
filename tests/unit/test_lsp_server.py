from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest
import pytest_asyncio
from lsprotocol import types as lsp
from pygls.lsp.server import LanguageServer

from remora.core.events import EventStore
from remora.core.graph import NodeStore
from remora.core.node import CodeNode
from remora.lsp.server import (
    _find_node_at_line,
    _node_to_hover,
    _node_to_lens,
    create_lsp_server,
)


def _node(node_id: str, file_path: str) -> CodeNode:
    name = node_id.split("::", maxsplit=1)[-1]
    return CodeNode(
        node_id=node_id,
        node_type="function",
        name=name,
        full_name=name,
        file_path=file_path,
        start_line=2,
        end_line=5,
        source_code=f"def {name}():\n    return 1\n",
        source_hash=f"h-{node_id}",
        status="idle",
    )


@pytest_asyncio.fixture
async def lsp_env(tmp_path: Path):
    conn = sqlite3.connect(str(tmp_path / "lsp.db"), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    lock = asyncio.Lock()
    node_store = NodeStore(conn, lock)
    await node_store.create_tables()
    event_store = EventStore(connection=conn, lock=lock)
    await event_store.initialize()
    yield node_store, event_store
    conn.close()


@pytest.mark.asyncio
async def test_lsp_server_creates(lsp_env) -> None:
    node_store, event_store = lsp_env
    server = create_lsp_server(node_store, event_store)
    assert isinstance(server, LanguageServer)


def test_node_to_lens() -> None:
    node = _node("src/app.py::a", "src/app.py")
    lens = _node_to_lens(node)
    assert lens.range.start.line == node.start_line - 1
    assert lens.range.end.line == node.end_line - 1
    assert lens.command is not None
    assert node.status in lens.command.title


def test_node_to_hover() -> None:
    node = _node("src/app.py::a", "src/app.py")
    hover = _node_to_hover(node)
    assert isinstance(hover, lsp.Hover)
    assert node.node_id in hover.contents.value
    assert node.file_path in hover.contents.value


def test_find_node_at_line() -> None:
    node_a = _node("src/app.py::a", "src/app.py")
    node_b = _node("src/app.py::b", "src/app.py").model_copy(
        update={"start_line": 10, "end_line": 12}
    )
    assert _find_node_at_line([node_a, node_b], 3) == node_a
    assert _find_node_at_line([node_a, node_b], 11) == node_b
    assert _find_node_at_line([node_a, node_b], 99) is None


@pytest.mark.asyncio
async def test_lsp_did_save_emits_event(lsp_env, tmp_path: Path) -> None:
    node_store, event_store = lsp_env
    server = create_lsp_server(node_store, event_store)
    handlers = server._remora_handlers  # type: ignore[attr-defined]
    did_save = handlers["did_save"]

    file_path = tmp_path / "src" / "app.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("def a():\n    return 1\n", encoding="utf-8")
    params = lsp.DidSaveTextDocumentParams(
        text_document=lsp.TextDocumentIdentifier(uri=f"file://{file_path}"),
    )

    await did_save(params)
    events = await event_store.get_events(limit=5)
    assert events
    assert events[0]["event_type"] == "ContentChangedEvent"
    assert events[0]["payload"]["path"] == str(file_path)
