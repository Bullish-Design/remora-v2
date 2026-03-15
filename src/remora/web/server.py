"""Starlette web server for graph APIs and live SSE events."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, StreamingResponse
from starlette.routing import Route
from starlette.staticfiles import StaticFiles

from remora.core.events import AgentMessageEvent, CursorFocusEvent

_STATIC_DIR = Path(__file__).parent / "static"
_INDEX_HTML = (_STATIC_DIR / "index.html").read_text(encoding="utf-8")


def create_app(
    event_store: Any,
    node_store: Any,
    event_bus: Any,
) -> Starlette:
    """Create Starlette app exposing graph APIs, events, and chat."""

    async def index(_request: Request) -> HTMLResponse:
        return HTMLResponse(_INDEX_HTML)

    async def api_nodes(_request: Request) -> JSONResponse:
        nodes = await node_store.list_nodes()
        return JSONResponse([node.model_dump() for node in nodes])

    async def api_node(request: Request) -> JSONResponse:
        node_id = request.path_params["node_id"]
        node = await node_store.get_node(node_id)
        if node is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse(node.model_dump())

    async def api_edges(request: Request) -> JSONResponse:
        node_id = request.path_params["node_id"]
        edges = await node_store.get_edges(node_id)
        payload = [
            {"from_id": edge.from_id, "to_id": edge.to_id, "edge_type": edge.edge_type}
            for edge in edges
        ]
        return JSONResponse(payload)

    async def api_all_edges(_request: Request) -> JSONResponse:
        edges = await node_store.list_all_edges()
        payload = [
            {"from_id": edge.from_id, "to_id": edge.to_id, "edge_type": edge.edge_type}
            for edge in edges
        ]
        return JSONResponse(payload)

    async def api_chat(request: Request) -> JSONResponse:
        data = await request.json()
        node_id = str(data.get("node_id", "")).strip()
        message = str(data.get("message", "")).strip()
        if not node_id or not message:
            return JSONResponse({"error": "node_id and message are required"}, status_code=400)

        node = await node_store.get_node(node_id)
        if node is None:
            return JSONResponse({"error": "node not found"}, status_code=404)

        await event_store.append(
            AgentMessageEvent(from_agent="user", to_agent=node_id, content=message)
        )
        return JSONResponse({"status": "sent"})

    async def api_events(request: Request) -> JSONResponse:
        raw_limit = request.query_params.get("limit", "50")
        try:
            limit = max(1, min(500, int(raw_limit)))
        except ValueError:
            return JSONResponse({"error": "invalid limit"}, status_code=400)
        return JSONResponse(await event_store.get_events(limit=limit))

    async def api_cursor(request: Request) -> JSONResponse:
        data = await request.json()
        file_path = str(data.get("file_path", "")).strip()
        line_raw = data.get("line", 0)
        character_raw = data.get("character", 0)

        try:
            line = int(line_raw)
            character = int(character_raw)
        except (TypeError, ValueError):
            return JSONResponse({"error": "line and character must be integers"}, status_code=400)

        if not file_path:
            return JSONResponse({"error": "file_path is required"}, status_code=400)

        nodes = await node_store.list_nodes(file_path=file_path)
        containing = [node for node in nodes if node.start_line <= line <= node.end_line]
        focused = (
            min(containing, key=lambda node: node.end_line - node.start_line)
            if containing
            else None
        )

        await event_bus.emit(
            CursorFocusEvent(
                file_path=file_path,
                line=line,
                character=character,
                node_id=focused.node_id if focused else None,
                node_name=focused.full_name if focused else None,
                node_type=(
                    focused.node_type.value
                    if focused is not None and hasattr(focused.node_type, "value")
                    else None
                ),
            )
        )
        return JSONResponse({"status": "ok", "node_id": focused.node_id if focused else None})

    async def sse_stream(request: Request) -> StreamingResponse:
        once = request.query_params.get("once", "").lower() in {"1", "true", "yes"}
        replay_raw = request.query_params.get("replay", "0")
        try:
            replay_limit = max(0, min(500, int(replay_raw)))
        except ValueError:
            replay_limit = 0

        async def event_generator():
            yield ": connected\n\n"
            if replay_limit > 0:
                rows = await event_store.get_events(limit=replay_limit)
                for row in reversed(rows):
                    event_name = row.get("event_type", "Event")
                    replay_payload = {
                        "event_type": event_name,
                        "timestamp": row.get("timestamp"),
                        "correlation_id": row.get("correlation_id"),
                        "payload": row.get("payload", {}),
                    }
                    payload_text = json.dumps(replay_payload, separators=(",", ":"))
                    yield f"event: {event_name}\ndata: {payload_text}\n\n"
            if once:
                return
            async with event_bus.stream() as stream:
                async for event in stream:
                    if await request.is_disconnected():
                        break
                    payload = json.dumps(event.to_envelope(), separators=(",", ":"))
                    yield f"event: {event.event_type}\ndata: {payload}\n\n"

        headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
        return StreamingResponse(event_generator(), media_type="text/event-stream", headers=headers)

    routes = [
        Route("/", endpoint=index),
        Route("/api/nodes", endpoint=api_nodes),
        Route("/api/edges", endpoint=api_all_edges),
        Route("/api/nodes/{node_id:path}/edges", endpoint=api_edges),
        Route("/api/nodes/{node_id:path}", endpoint=api_node),
        Route("/api/chat", endpoint=api_chat, methods=["POST"]),
        Route("/api/events", endpoint=api_events),
        Route("/api/cursor", endpoint=api_cursor, methods=["POST"]),
        Route("/sse", endpoint=sse_stream),
    ]
    app = Starlette(routes=routes)
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
    return app


__all__ = ["create_app"]
