"""Event list and SSE routes."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from remora.web.deps import _deps_from_request
from remora.web.sse import sse_stream


async def api_events(request: Request) -> JSONResponse:
    deps = _deps_from_request(request)
    raw_limit = request.query_params.get("limit", "50")
    try:
        limit = max(1, min(500, int(raw_limit)))
    except ValueError:
        return JSONResponse({"error": "invalid limit"}, status_code=400)
    return JSONResponse(await deps.event_store.get_events(limit=limit))


def routes() -> list[Route]:
    return [
        Route("/api/events", endpoint=api_events),
        Route("/sse", endpoint=sse_stream),
    ]


__all__ = ["api_events", "routes"]
