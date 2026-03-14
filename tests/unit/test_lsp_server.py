from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import pytest_asyncio
from lsprotocol import types as lsp
from pygls.lsp.server import LanguageServer

from remora.core.db import AsyncDB
from remora.core.events import EventStore
from remora.core.graph import NodeStore
from remora.lsp.server import (
    _find_node_at_line,
    _node_to_hover,
    _node_to_lens,
    create_lsp_server,
)
from tests.factories import make_node


@pytest_asyncio.fixture
async def lsp_env(tmp_path: Path):
    db = AsyncDB.from_path(tmp_path / "lsp.db")
    node_store = NodeStore(db)
    await node_store.create_tables()
    event_store = EventStore(db=db)
    await event_store.create_tables()
    yield node_store, event_store
    db.close()


@pytest.mark.asyncio
async def test_lsp_server_creates(lsp_env) -> None:
    node_store, event_store = lsp_env
    server = create_lsp_server(node_store, event_store)
    assert isinstance(server, LanguageServer)


def test_node_to_lens() -> None:
    node = make_node("src/app.py::a", file_path="src/app.py", start_line=2, end_line=5)
    lens = _node_to_lens(node)
    assert lens.range.start.line == node.start_line - 1
    assert lens.range.end.line == node.end_line - 1
    assert lens.command is not None
    assert node.status in lens.command.title


def test_node_to_hover() -> None:
    node = make_node("src/app.py::a", file_path="src/app.py", start_line=2, end_line=5)
    hover = _node_to_hover(node)
    assert isinstance(hover, lsp.Hover)
    assert node.node_id in hover.contents.value
    assert node.file_path in hover.contents.value


def test_find_node_at_line() -> None:
    node_a = make_node("src/app.py::a", file_path="src/app.py", start_line=2, end_line=5)
    node_b = make_node("src/app.py::b", file_path="src/app.py", start_line=2, end_line=5).model_copy(
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


@pytest.mark.asyncio
async def test_lsp_did_change_writes_file_and_emits_event(
    lsp_env,
    tmp_path: Path,
) -> None:
    node_store, event_store = lsp_env
    server = create_lsp_server(node_store, event_store)
    handlers = server._remora_handlers  # type: ignore[attr-defined]
    did_change = handlers["did_change"]

    file_path = tmp_path / "src" / "app.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("print('hello')\n", encoding="utf-8")
    change = lsp.TextDocumentContentChangeWholeDocument(
        text="print('goodbye')\n",
    )
    params = lsp.DidChangeTextDocumentParams(
        text_document=lsp.VersionedTextDocumentIdentifier(
            uri=f"file://{file_path}",
            version=2,
        ),
        content_changes=[change],
    )

    await did_change(params)
    assert file_path.read_text(encoding="utf-8") == "print('goodbye')\n"
    events = await event_store.get_events(limit=5)
    assert any(event["event_type"] == "ContentChangedEvent" for event in events)
