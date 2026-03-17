"""Starlette web server for graph APIs and live SSE events."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, StreamingResponse
from starlette.routing import Route
from starlette.staticfiles import StaticFiles

from remora import __version__
from remora.core.events import (
    AgentMessageEvent,
    ContentChangedEvent,
    CursorFocusEvent,
    HumanInputResponseEvent,
    RewriteAcceptedEvent,
    RewriteRejectedEvent,
)
from remora.core.events.bus import EventBus
from remora.core.events.store import EventStore
from remora.core.graph import NodeStore
from remora.core.metrics import Metrics
from remora.core.search import SearchServiceProtocol
from remora.core.types import ChangeType, NodeStatus, serialize_enum

if TYPE_CHECKING:
    from remora.core.runner import ActorPool
    from remora.core.workspace import CairnWorkspaceService

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


@dataclass
class WebDeps:
    """Shared dependencies for all web handlers."""

    event_store: EventStore
    node_store: NodeStore
    event_bus: EventBus
    metrics: Metrics | None
    actor_pool: ActorPool | None
    workspace_service: CairnWorkspaceService | None
    search_service: SearchServiceProtocol | None
    shutdown_event: asyncio.Event
    chat_limiter: RateLimiter


def _is_allowed_origin(origin: str) -> bool:
    parsed = urlparse(origin)
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    return host in {"localhost", "127.0.0.1"}


class CSRFMiddleware(BaseHTTPMiddleware):
    """Reject mutating requests from non-local browser origins."""

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001
        if request.method in {"POST", "PUT", "DELETE"}:
            origin = request.headers.get("origin", "").strip()
            if origin and not _is_allowed_origin(origin):
                return JSONResponse({"error": "CSRF rejected"}, status_code=403)
        return await call_next(request)


def _deps_from_request(request: Request) -> WebDeps:
    return request.app.state.deps


def _resolve_within_project_root(
    path: Path,
    workspace_path: str,
    workspace_service: CairnWorkspaceService | None,
) -> Path:
    candidate = path
    if workspace_service is not None and not candidate.is_absolute():
        candidate = workspace_service._project_root / candidate
    resolved = candidate.resolve()
    if workspace_service is None:
        return resolved
    project_root = workspace_service._project_root.resolve()
    try:
        resolved.relative_to(project_root)
    except ValueError as exc:
        raise ValueError(f"Path traversal attempt: {workspace_path}") from exc
    return resolved


def _workspace_path_to_disk_path(
    node_id: str,
    node_file_path: str,
    workspace_path: str,
    workspace_service: CairnWorkspaceService | None,
) -> Path:
    normalized = workspace_path.strip("/")
    result = Path(node_file_path)
    if normalized.startswith("source/"):
        source_path = normalized.removeprefix("source/")
        if source_path:
            if source_path.startswith("/"):
                result = Path(source_path)
            elif source_path in {node_id, node_file_path}:
                result = Path(node_file_path)
            else:
                result = Path(source_path)
    return _resolve_within_project_root(result, workspace_path, workspace_service)


async def _latest_rewrite_proposal(node_id: str, event_store: EventStore) -> dict | None:
    rows = await event_store.get_events_for_agent(node_id, limit=200)
    for row in rows:
        if row.get("event_type") == "RewriteProposalEvent":
            return row
    return None


async def index(_request: Request) -> HTMLResponse:
    return HTMLResponse(_INDEX_HTML)


async def api_nodes(request: Request) -> JSONResponse:
    deps = _deps_from_request(request)
    nodes = await deps.node_store.list_nodes()
    return JSONResponse([node.model_dump() for node in nodes])


async def api_node(request: Request) -> JSONResponse:
    deps = _deps_from_request(request)
    node_id = request.path_params["node_id"]
    node = await deps.node_store.get_node(node_id)
    if node is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(node.model_dump())


async def api_node_companion(request: Request) -> JSONResponse:
    deps = _deps_from_request(request)
    node_id = request.path_params["node_id"]
    if deps.workspace_service is None:
        return JSONResponse({"error": "No workspace service"}, status_code=503)

    workspace = await deps.workspace_service.get_agent_workspace(node_id)
    companion_data: dict[str, Any] = {}
    for key in ("companion/chat_index", "companion/reflections", "companion/links"):
        value = await workspace.kv_get(key)
        if value is not None:
            short_key = key.removeprefix("companion/")
            companion_data[short_key] = value

    return JSONResponse(companion_data)


async def api_edges(request: Request) -> JSONResponse:
    deps = _deps_from_request(request)
    node_id = request.path_params["node_id"]
    edges = await deps.node_store.get_edges(node_id)
    payload = [
        {"from_id": edge.from_id, "to_id": edge.to_id, "edge_type": edge.edge_type}
        for edge in edges
    ]
    return JSONResponse(payload)


async def api_all_edges(request: Request) -> JSONResponse:
    deps = _deps_from_request(request)
    edges = await deps.node_store.list_all_edges()
    payload = [
        {"from_id": edge.from_id, "to_id": edge.to_id, "edge_type": edge.edge_type}
        for edge in edges
    ]
    return JSONResponse(payload)


async def api_conversation(request: Request) -> JSONResponse:
    deps = _deps_from_request(request)
    if deps.actor_pool is None:
        return JSONResponse({"error": "No active actor for this node"}, status_code=404)

    node_id = request.path_params["node_id"]
    actor = deps.actor_pool.actors.get(node_id)
    if actor is None:
        return JSONResponse({"error": "No active actor for this node"}, status_code=404)
    history = [
        {
            "role": str(getattr(message, "role", "")),
            "content": str(getattr(message, "content", ""))[:2000],
        }
        for message in actor.history
    ]
    return JSONResponse({"node_id": node_id, "history": history})


async def api_chat(request: Request) -> JSONResponse:
    deps = _deps_from_request(request)
    if not deps.chat_limiter.allow():
        return JSONResponse(
            {"error": "Rate limit exceeded. Try again later."},
            status_code=429,
        )

    data = await request.json()
    node_id = str(data.get("node_id", "")).strip()
    message = str(data.get("message", "")).strip()
    if not node_id or not message:
        return JSONResponse({"error": "node_id and message are required"}, status_code=400)

    node = await deps.node_store.get_node(node_id)
    if node is None:
        return JSONResponse({"error": "node not found"}, status_code=404)

    await deps.event_store.append(
        AgentMessageEvent(from_agent="user", to_agent=node_id, content=message)
    )
    return JSONResponse({"status": "sent"})


async def api_respond(request: Request) -> JSONResponse:
    deps = _deps_from_request(request)
    data = await request.json()
    request_id = str(data.get("request_id", "")).strip()
    response_text = str(data.get("response", "")).strip()
    if not request_id or not response_text:
        return JSONResponse({"error": "request_id and response required"}, status_code=400)

    node_id = request.path_params["node_id"]
    resolved = deps.event_store.resolve_response(request_id, response_text)
    if not resolved:
        return JSONResponse({"error": "no pending request"}, status_code=404)

    await deps.event_store.append(
        HumanInputResponseEvent(
            agent_id=node_id,
            request_id=request_id,
            response=response_text,
        )
    )
    return JSONResponse({"status": "ok"})


async def api_cursor(request: Request) -> JSONResponse:
    deps = _deps_from_request(request)
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

    nodes = await deps.node_store.list_nodes(file_path=file_path)
    containing = [node for node in nodes if node.start_line <= line <= node.end_line]
    focused = (
        min(containing, key=lambda node: node.end_line - node.start_line) if containing else None
    )

    await deps.event_bus.emit(
        CursorFocusEvent(
            file_path=file_path,
            line=line,
            character=character,
            node_id=focused.node_id if focused else None,
            node_name=focused.full_name if focused else None,
            node_type=serialize_enum(focused.node_type) if focused is not None else None,
        )
    )
    return JSONResponse({"status": "ok", "node_id": focused.node_id if focused else None})


async def api_proposals(request: Request) -> JSONResponse:
    deps = _deps_from_request(request)
    pending = await deps.node_store.list_nodes(status=NodeStatus.AWAITING_REVIEW)
    payload: list[dict[str, object]] = []
    for node in pending:
        proposal_event = await _latest_rewrite_proposal(node.node_id, deps.event_store)
        event_payload = proposal_event.get("payload", {}) if proposal_event else {}
        payload.append(
            {
                "node_id": node.node_id,
                "status": str(node.status),
                "proposal_id": event_payload.get("proposal_id", ""),
                "reason": event_payload.get("reason", ""),
                "files": event_payload.get("files", []),
            }
        )
    return JSONResponse(payload)


async def api_proposal_diff(request: Request) -> JSONResponse:
    deps = _deps_from_request(request)
    if deps.workspace_service is None:
        return JSONResponse({"error": "workspace service unavailable"}, status_code=503)

    node_id = request.path_params["node_id"]
    node = await deps.node_store.get_node(node_id)
    if node is None:
        return JSONResponse({"error": "not found"}, status_code=404)

    proposal_event = await _latest_rewrite_proposal(node_id, deps.event_store)
    if proposal_event is None:
        return JSONResponse({"error": "no proposal found"}, status_code=404)

    proposal_payload = proposal_event.get("payload", {})
    files = proposal_payload.get("files", [])
    workspace = await deps.workspace_service.get_agent_workspace(node_id)
    diffs: list[dict[str, str]] = []
    for workspace_path in files:
        if not isinstance(workspace_path, str):
            continue
        try:
            new_source = await workspace.read(workspace_path)
        except FileNotFoundError:
            continue

        try:
            disk_path = _workspace_path_to_disk_path(
                node.node_id,
                node.file_path,
                workspace_path,
                deps.workspace_service,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        if disk_path.exists():
            old_source = disk_path.read_text(encoding="utf-8")
        else:
            old_source = ""
        diffs.append(
            {
                "workspace_path": workspace_path,
                "file": str(disk_path),
                "old": old_source,
                "new": new_source,
            }
        )

    return JSONResponse(
        {
            "node_id": node_id,
            "proposal_id": proposal_payload.get("proposal_id", ""),
            "reason": proposal_payload.get("reason", ""),
            "diffs": diffs,
        }
    )


async def api_proposal_accept(request: Request) -> JSONResponse:
    deps = _deps_from_request(request)
    if deps.workspace_service is None:
        return JSONResponse({"error": "workspace service unavailable"}, status_code=503)

    node_id = request.path_params["node_id"]
    node = await deps.node_store.get_node(node_id)
    if node is None:
        return JSONResponse({"error": "not found"}, status_code=404)

    proposal_event = await _latest_rewrite_proposal(node_id, deps.event_store)
    if proposal_event is None:
        return JSONResponse({"error": "no proposal found"}, status_code=404)

    proposal_payload = proposal_event.get("payload", {})
    proposal_id = str(proposal_payload.get("proposal_id", "")).strip()
    files = proposal_payload.get("files", [])
    workspace = await deps.workspace_service.get_agent_workspace(node_id)
    materialized: list[str] = []

    for workspace_path in files:
        if not isinstance(workspace_path, str):
            continue
        try:
            new_source = await workspace.read(workspace_path)
        except FileNotFoundError:
            continue

        try:
            disk_path = _workspace_path_to_disk_path(
                node.node_id,
                node.file_path,
                workspace_path,
                deps.workspace_service,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        old_bytes = disk_path.read_bytes() if disk_path.exists() else b""
        new_bytes = new_source.encode("utf-8")
        if old_bytes == new_bytes:
            continue

        disk_path.parent.mkdir(parents=True, exist_ok=True)
        disk_path.write_bytes(new_bytes)
        await deps.event_store.append(
            ContentChangedEvent(
                path=str(disk_path),
                change_type=ChangeType.MODIFIED,
                agent_id=node_id,
                old_hash=hashlib.sha256(old_bytes).hexdigest(),
                new_hash=hashlib.sha256(new_bytes).hexdigest(),
            )
        )
        materialized.append(str(disk_path))

    await deps.node_store.transition_status(node_id, NodeStatus.IDLE)
    await deps.event_store.append(
        RewriteAcceptedEvent(
            agent_id=node_id,
            proposal_id=proposal_id,
        )
    )
    return JSONResponse(
        {
            "status": "accepted",
            "proposal_id": proposal_id,
            "files": materialized,
        }
    )


async def api_proposal_reject(request: Request) -> JSONResponse:
    deps = _deps_from_request(request)
    node_id = request.path_params["node_id"]
    node = await deps.node_store.get_node(node_id)
    if node is None:
        return JSONResponse({"error": "not found"}, status_code=404)

    proposal_event = await _latest_rewrite_proposal(node_id, deps.event_store)
    if proposal_event is None:
        return JSONResponse({"error": "no proposal found"}, status_code=404)
    proposal_payload = proposal_event.get("payload", {})
    proposal_id = str(proposal_payload.get("proposal_id", "")).strip()

    data = await request.json()
    feedback = str(data.get("feedback", "")).strip()
    await deps.node_store.transition_status(node_id, NodeStatus.IDLE)
    await deps.event_store.append(
        RewriteRejectedEvent(
            agent_id=node_id,
            proposal_id=proposal_id,
            feedback=feedback,
        )
    )
    return JSONResponse({"status": "rejected", "proposal_id": proposal_id})


async def api_events(request: Request) -> JSONResponse:
    deps = _deps_from_request(request)
    raw_limit = request.query_params.get("limit", "50")
    try:
        limit = max(1, min(500, int(raw_limit)))
    except ValueError:
        return JSONResponse({"error": "invalid limit"}, status_code=400)
    return JSONResponse(await deps.event_store.get_events(limit=limit))


async def api_health(request: Request) -> JSONResponse:
    deps = _deps_from_request(request)
    cursor = await deps.node_store._db.execute("SELECT COUNT(*) FROM nodes")
    row = await cursor.fetchone()
    node_count = int(row[0]) if row is not None else 0
    health: dict[str, object] = {
        "status": "ok",
        "version": __version__,
        "nodes": node_count,
    }
    if deps.metrics is not None:
        health["metrics"] = deps.metrics.snapshot()
    return JSONResponse(health)


async def api_search(request: Request) -> JSONResponse:
    deps = _deps_from_request(request)
    if deps.search_service is None or not deps.search_service.available:
        return JSONResponse({"error": "Semantic search is not configured"}, status_code=503)

    data = await request.json()
    query = str(data.get("query", "")).strip()
    if not query:
        return JSONResponse({"error": "query is required"}, status_code=400)

    collection = data.get("collection") or "code"
    try:
        top_k = min(100, max(1, int(data.get("top_k", 10))))
    except (TypeError, ValueError):
        return JSONResponse({"error": "top_k must be an integer"}, status_code=400)

    mode = str(data.get("mode", "hybrid"))
    if mode not in {"vector", "fulltext", "hybrid"}:
        return JSONResponse(
            {"error": "mode must be vector, fulltext, or hybrid"},
            status_code=400,
        )

    start = time.perf_counter()
    results = await deps.search_service.search(query, collection, top_k, mode)
    elapsed_ms = (time.perf_counter() - start) * 1000

    return JSONResponse(
        {
            "results": results,
            "query": query,
            "collection": collection,
            "mode": mode,
            "total_results": len(results),
            "elapsed_ms": round(elapsed_ms, 1),
        }
    )


async def sse_stream(request: Request) -> StreamingResponse:
    deps = _deps_from_request(request)
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
            rows = await deps.event_store.get_events_after(last_event_id)
            for row in rows:
                event_name = row.get("event_type", "Event")
                event_id = row.get("id", "")
                replay_payload = {
                    "event_type": event_name,
                    "timestamp": row.get("timestamp"),
                    "correlation_id": row.get("correlation_id"),
                    "tags": row.get("tags", []),
                    "payload": row.get("payload", {}),
                }
                payload_text = json.dumps(replay_payload, separators=(",", ":"))
                yield f"id: {event_id}\nevent: {event_name}\ndata: {payload_text}\n\n"
        elif replay_limit > 0:
            rows = await deps.event_store.get_events(limit=replay_limit)
            for row in reversed(rows):
                event_name = row.get("event_type", "Event")
                event_id = row.get("id", "")
                replay_payload = {
                    "event_type": event_name,
                    "timestamp": row.get("timestamp"),
                    "correlation_id": row.get("correlation_id"),
                    "tags": row.get("tags", []),
                    "payload": row.get("payload", {}),
                }
                payload_text = json.dumps(replay_payload, separators=(",", ":"))
                yield f"id: {event_id}\nevent: {event_name}\ndata: {payload_text}\n\n"
        if once:
            return
        async with deps.event_bus.stream() as stream:
            stream_iterator = stream.__aiter__()
            while True:
                if await request.is_disconnected() or deps.shutdown_event.is_set():
                    break
                try:
                    event = await asyncio.wait_for(stream_iterator.__anext__(), timeout=0.25)
                except TimeoutError:
                    continue
                except StopAsyncIteration:
                    break
                payload = json.dumps(event.to_envelope(), separators=(",", ":"))
                yield f"id: {event.timestamp}\nevent: {event.event_type}\ndata: {payload}\n\n"
        if deps.shutdown_event.is_set():
            yield ": server-shutdown\n\n"

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=headers)


def create_app(
    event_store: EventStore,
    node_store: NodeStore,
    event_bus: EventBus,
    metrics: Metrics | None = None,
    actor_pool: ActorPool | None = None,
    workspace_service: CairnWorkspaceService | None = None,
    search_service: SearchServiceProtocol | None = None,
) -> Starlette:
    """Create Starlette app exposing graph APIs, events, and chat."""
    deps = WebDeps(
        event_store=event_store,
        node_store=node_store,
        event_bus=event_bus,
        metrics=metrics,
        actor_pool=actor_pool,
        workspace_service=workspace_service,
        search_service=search_service,
        shutdown_event=asyncio.Event(),
        chat_limiter=RateLimiter(max_requests=10, window_seconds=60.0),
    )

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        try:
            yield
        finally:
            deps.shutdown_event.set()

    routes = [
        Route("/", endpoint=index),
        Route("/api/nodes", endpoint=api_nodes),
        Route("/api/edges", endpoint=api_all_edges),
        Route("/api/nodes/{node_id:path}/edges", endpoint=api_edges),
        Route("/api/nodes/{node_id:path}/conversation", endpoint=api_conversation),
        Route("/api/nodes/{node_id:path}/companion", endpoint=api_node_companion),
        Route("/api/chat", endpoint=api_chat, methods=["POST"]),
        Route("/api/nodes/{node_id:path}/respond", endpoint=api_respond, methods=["POST"]),
        Route("/api/nodes/{node_id:path}", endpoint=api_node),
        Route("/api/proposals", endpoint=api_proposals),
        Route("/api/proposals/{node_id:path}/diff", endpoint=api_proposal_diff),
        Route(
            "/api/proposals/{node_id:path}/accept",
            endpoint=api_proposal_accept,
            methods=["POST"],
        ),
        Route(
            "/api/proposals/{node_id:path}/reject",
            endpoint=api_proposal_reject,
            methods=["POST"],
        ),
        Route("/api/events", endpoint=api_events),
        Route("/api/health", endpoint=api_health),
        Route("/api/search", endpoint=api_search, methods=["POST"]),
        Route("/api/cursor", endpoint=api_cursor, methods=["POST"]),
        Route("/sse", endpoint=sse_stream),
    ]
    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.deps = deps
    app.add_middleware(CSRFMiddleware)
    app.state.sse_shutdown_event = deps.shutdown_event
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
    return app


__all__ = ["CSRFMiddleware", "create_app"]
