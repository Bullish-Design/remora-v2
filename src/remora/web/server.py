"""Starlette web server for graph APIs and live SSE events."""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, StreamingResponse
from starlette.routing import Route
from starlette.staticfiles import StaticFiles

from remora.core.events.bus import EventBus
from remora.core.events.store import EventStore
from remora.core.events import AgentMessageEvent, CursorFocusEvent
from remora.core.graph import NodeStore
from remora.core.metrics import Metrics

_STATIC_DIR = Path(__file__).parent / "static"
_INDEX_HTML = (_STATIC_DIR / "index.html").read_text(encoding="utf-8")


class RateLimiter:
    """Simple in-memory sliding window rate limiter."""

    def __init__(self, max_requests: int = 10, window_seconds: float = 60.0) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._timestamps: deque[float] = deque()

    def allow(self) -> bool:
        now = time.time()
        while self._timestamps and self._timestamps[0] < now - self._window_seconds:
            self._timestamps.popleft()
        if len(self._timestamps) >= self._max_requests:
            return False
        self._timestamps.append(now)
        return True


def create_app(
    event_store: EventStore,
    node_store: NodeStore,
    event_bus: EventBus,
    metrics: Metrics | None = None,
) -> Starlette:
    """Create Starlette app exposing graph APIs, events, and chat."""
    shutdown_event = asyncio.Event()
    chat_limiter = RateLimiter(max_requests=10, window_seconds=60.0)

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
        if not chat_limiter.allow():
            return JSONResponse(
                {"error": "Rate limit exceeded. Try again later."},
                status_code=429,
            )

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

    async def api_health(_request: Request) -> JSONResponse:
        node_count = len(await node_store.list_nodes())
        health: dict[str, object] = {
            "status": "ok",
            "version": "0.5.0",
            "nodes": node_count,
        }
        if metrics is not None:
            health["metrics"] = metrics.snapshot()
        return JSONResponse(health)

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
        last_event_id = request.headers.get("Last-Event-ID")
        try:
            replay_limit = max(0, min(500, int(replay_raw)))
        except ValueError:
            replay_limit = 0

        async def event_generator():
            yield ": connected\n\n"
            if last_event_id:
                rows = await event_store.get_events_after(last_event_id)
                for row in rows:
                    event_name = row.get("event_type", "Event")
                    event_id = row.get("id", "")
                    replay_payload = {
                        "event_type": event_name,
                        "timestamp": row.get("timestamp"),
                        "correlation_id": row.get("correlation_id"),
                        "payload": row.get("payload", {}),
                    }
                    payload_text = json.dumps(replay_payload, separators=(",", ":"))
                    yield f"id: {event_id}\nevent: {event_name}\ndata: {payload_text}\n\n"
            elif replay_limit > 0:
                rows = await event_store.get_events(limit=replay_limit)
                for row in reversed(rows):
                    event_name = row.get("event_type", "Event")
                    event_id = row.get("id", "")
                    replay_payload = {
                        "event_type": event_name,
                        "timestamp": row.get("timestamp"),
                        "correlation_id": row.get("correlation_id"),
                        "payload": row.get("payload", {}),
                    }
                    payload_text = json.dumps(replay_payload, separators=(",", ":"))
                    yield f"id: {event_id}\nevent: {event_name}\ndata: {payload_text}\n\n"
            if once:
                return
            async with event_bus.stream() as stream:
                stream_iterator = stream.__aiter__()
                while True:
                    if await request.is_disconnected() or shutdown_event.is_set():
                        break
                    try:
                        event = await asyncio.wait_for(stream_iterator.__anext__(), timeout=0.25)
                    except asyncio.TimeoutError:
                        continue
                    except StopAsyncIteration:
                        break
                    payload = json.dumps(event.to_envelope(), separators=(",", ":"))
                    yield f"id: {event.timestamp}\nevent: {event.event_type}\ndata: {payload}\n\n"
            if shutdown_event.is_set():
                yield ": server-shutdown\n\n"

        headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
        return StreamingResponse(event_generator(), media_type="text/event-stream", headers=headers)

    async def on_shutdown() -> None:
        shutdown_event.set()

    routes = [
        Route("/", endpoint=index),
        Route("/api/nodes", endpoint=api_nodes),
        Route("/api/edges", endpoint=api_all_edges),
        Route("/api/nodes/{node_id:path}/edges", endpoint=api_edges),
        Route("/api/nodes/{node_id:path}", endpoint=api_node),
        Route("/api/chat", endpoint=api_chat, methods=["POST"]),
        Route("/api/events", endpoint=api_events),
        Route("/api/health", endpoint=api_health),
        Route("/api/cursor", endpoint=api_cursor, methods=["POST"]),
        Route("/sse", endpoint=sse_stream),
    ]
    app = Starlette(routes=routes, on_shutdown=[on_shutdown])
    app.state.sse_shutdown_event = shutdown_event
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
    return app


__all__ = ["create_app"]
