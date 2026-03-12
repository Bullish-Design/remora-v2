"""Starlette web server for graph APIs and live SSE events."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, StreamingResponse
from starlette.routing import Route

from remora.core.events import HumanChatEvent
from remora.web.views import GRAPH_HTML


def create_app(
    event_store: Any,
    node_store: Any,
    event_bus: Any,
    *,
    project_root: Path | None = None,
) -> Starlette:
    """Create Starlette app exposing graph, events, and chat APIs."""
    del project_root

    async def index(_request: Request) -> HTMLResponse:
        return HTMLResponse(GRAPH_HTML)

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

    async def api_chat(request: Request) -> JSONResponse:
        data = await request.json()
        node_id = str(data.get("node_id", "")).strip()
        message = str(data.get("message", "")).strip()
        if not node_id or not message:
            return JSONResponse({"error": "node_id and message are required"}, status_code=400)

        await event_store.append(HumanChatEvent(to_agent=node_id, message=message))
        return JSONResponse({"status": "sent"})

    async def api_events(request: Request) -> JSONResponse:
        raw_limit = request.query_params.get("limit", "50")
        try:
            limit = max(1, min(500, int(raw_limit)))
        except ValueError:
            return JSONResponse({"error": "invalid limit"}, status_code=400)
        return JSONResponse(await event_store.get_events(limit=limit))

    async def sse_stream(request: Request) -> StreamingResponse:
        once = request.query_params.get("once", "").lower() in {"1", "true", "yes"}
        replay_raw = request.query_params.get("replay", "0")
        try:
            replay_limit = max(0, min(500, int(replay_raw)))
        except ValueError:
            replay_limit = 0

        async def event_generator():
            # Send an initial heartbeat so clients establish the stream promptly.
            yield ": connected\n\n"
            if replay_limit > 0:
                rows = await event_store.get_events(limit=replay_limit)
                for row in reversed(rows):
                    payload = row.get("payload", {})
                    payload_text = json.dumps(payload, separators=(",", ":"))
                    event_name = row.get("event_type", "Event")
                    yield f"event: {event_name}\ndata: {payload_text}\n\n"
            if once:
                return
            async with event_bus.stream() as stream:
                async for event in stream:
                    if await request.is_disconnected():
                        break
                    payload = json.dumps(event.model_dump(), separators=(",", ":"))
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
        Route("/api/nodes/{node_id:path}/edges", endpoint=api_edges),
        Route("/api/nodes/{node_id:path}", endpoint=api_node),
        Route("/api/chat", endpoint=api_chat, methods=["POST"]),
        Route("/api/events", endpoint=api_events),
        Route("/sse", endpoint=sse_stream),
    ]
    return Starlette(routes=routes)


__all__ = ["create_app"]
