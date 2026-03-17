"""Shared dependency objects for web handlers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from starlette.requests import Request

from remora.core.events.bus import EventBus
from remora.core.events.store import EventStore
from remora.core.graph import NodeStore
from remora.core.metrics import Metrics
from remora.core.rate_limit import SlidingWindowRateLimiter
from remora.core.search import SearchServiceProtocol

if TYPE_CHECKING:
    from remora.core.runner import ActorPool
    from remora.core.workspace import CairnWorkspaceService


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
    chat_limiters: dict[str, SlidingWindowRateLimiter]


def _deps_from_request(request: Request) -> WebDeps:
    return request.app.state.deps


def _get_chat_limiter(request: Request, deps: WebDeps) -> SlidingWindowRateLimiter:
    ip = request.client.host if request.client is not None else "unknown"
    limiter = deps.chat_limiters.get(ip)
    if limiter is None:
        limiter = SlidingWindowRateLimiter(max_requests=10, window_seconds=60.0)
        deps.chat_limiters[ip] = limiter
    return limiter


__all__ = ["WebDeps", "_deps_from_request", "_get_chat_limiter"]
