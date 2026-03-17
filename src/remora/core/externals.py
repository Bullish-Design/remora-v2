"""Agent externals - API surface available to agent tool scripts."""

from __future__ import annotations

import asyncio
import fnmatch
import uuid
from typing import TYPE_CHECKING, Any

from remora.core.events import (
    AgentMessageEvent,
    CustomEvent,
    HumanInputRequestEvent,
    RewriteProposalEvent,
    SubscriptionPattern,
)
from remora.core.events.store import EventStore
from remora.core.events.types import Event
from remora.core.graph import NodeStore
from remora.core.node import Node
from remora.core.rate_limit import SlidingWindowRateLimiter
from remora.core.search import SearchServiceProtocol
from remora.core.types import NodeStatus, NodeType, serialize_enum
from remora.core.workspace import AgentWorkspace

if TYPE_CHECKING:
    from remora.core.actor import Outbox


class TurnContext:
    """Per-turn context providing externals API for an agent's tools."""

    def __init__(
        self,
        node_id: str,
        workspace: AgentWorkspace,
        correlation_id: str | None,
        node_store: NodeStore,
        event_store: EventStore,
        outbox: Outbox,
        human_input_timeout_s: float = 300.0,
        search_content_max_matches: int = 1000,
        broadcast_max_targets: int = 50,
        send_message_limiter: SlidingWindowRateLimiter | None = None,
        search_service: SearchServiceProtocol | None = None,
    ) -> None:
        self.node_id = node_id
        self.workspace = workspace
        self.correlation_id = correlation_id
        self._node_store = node_store
        self._event_store = event_store
        self._outbox = outbox
        self._human_input_timeout_s = human_input_timeout_s
        self._search_content_max_matches = max(1, int(search_content_max_matches))
        self._broadcast_max_targets = max(1, int(broadcast_max_targets))
        self._send_message_limiter = send_message_limiter
        self._search_service = search_service

    async def _emit(self, event: Event) -> int:
        """Emit an event through the outbox."""
        return await self._outbox.emit(event)

    async def read_file(self, path: str) -> str:
        return await self.workspace.read(path)

    async def write_file(self, path: str, content: str) -> bool:
        await self.workspace.write(path, content)
        return True

    async def list_dir(self, path: str = ".") -> list[str]:
        return await self.workspace.list_dir(path)

    async def file_exists(self, path: str) -> bool:
        return await self.workspace.exists(path)

    async def search_files(self, pattern: str) -> list[str]:
        paths = await self.workspace.list_all_paths()
        return sorted(path for path in paths if fnmatch.fnmatch(path, f"*{pattern}*"))

    async def search_content(self, pattern: str, path: str = ".") -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        paths = await self.workspace.list_all_paths()
        for file_path in paths:
            normalized = file_path.strip("/")
            if path not in {".", "/", ""} and not normalized.startswith(path.strip("/")):
                continue
            try:
                content = await self.workspace.read(normalized)
            except FileNotFoundError:
                continue
            for index, line in enumerate(content.splitlines(), start=1):
                if pattern in line:
                    matches.append({"file": normalized, "line": index, "text": line})
                    if len(matches) >= self._search_content_max_matches:
                        return matches
        return matches

    async def kv_get(self, key: str) -> Any | None:
        return await self.workspace.kv_get(key)

    async def kv_set(self, key: str, value: Any) -> bool:
        await self.workspace.kv_set(key, value)
        return True

    async def kv_delete(self, key: str) -> bool:
        await self.workspace.kv_delete(key)
        return True

    async def kv_list(self, prefix: str = "") -> list[str]:
        return await self.workspace.kv_list(prefix)

    async def graph_get_node(self, target_id: str) -> dict[str, Any]:
        node = await self._node_store.get_node(target_id)
        return node.model_dump() if node is not None else {}

    async def graph_query_nodes(
        self,
        node_type: str | None = None,
        status: str | None = None,
        file_path: str | None = None,
    ) -> list[dict[str, Any]]:
        normalized_node_type: NodeType | None = None
        if node_type is not None:
            node_type_name = node_type.strip()
            valid_node_types = {serialize_enum(item) for item in NodeType}
            if node_type_name not in valid_node_types:
                choices = ", ".join(sorted(valid_node_types))
                raise ValueError(
                    f"Invalid node_type '{node_type}'. Expected one of: {choices}"
                )
            normalized_node_type = NodeType(node_type_name)

        normalized_status: NodeStatus | None = None
        if status is not None:
            status_name = status.strip()
            valid_statuses = {serialize_enum(item) for item in NodeStatus}
            if status_name not in valid_statuses:
                choices = ", ".join(sorted(valid_statuses))
                raise ValueError(f"Invalid status '{status}'. Expected one of: {choices}")
            normalized_status = NodeStatus(status_name)

        nodes = await self._node_store.list_nodes(
            node_type=normalized_node_type,
            status=normalized_status,
            file_path=file_path,
        )
        return [node.model_dump() for node in nodes]

    async def graph_get_edges(self, target_id: str) -> list[dict[str, Any]]:
        edges = await self._node_store.get_edges(target_id)
        return [
            {"from_id": edge.from_id, "to_id": edge.to_id, "edge_type": edge.edge_type}
            for edge in edges
        ]

    async def graph_get_children(self, parent_id: str | None = None) -> list[dict[str, Any]]:
        """Get child nodes. Defaults to current node's children."""
        target = parent_id or self.node_id
        children = await self._node_store.get_children(target)
        return [node.model_dump() for node in children]

    async def graph_set_status(self, target_id: str, new_status: str) -> bool:
        target_enum = NodeStatus(new_status.strip())
        return await self._node_store.transition_status(target_id, target_enum)

    async def event_emit(
        self,
        event_type: str,
        payload: dict[str, Any],
        tags: list[str] | None = None,
    ) -> bool:
        event = CustomEvent(
            event_type=event_type,
            payload=payload,
            correlation_id=self.correlation_id,
            tags=tuple(tags or ()),
        )
        await self._emit(event)
        return True

    async def event_subscribe(
        self,
        event_types: list[str] | None = None,
        from_agents: list[str] | None = None,
        path_glob: str | None = None,
        tags: list[str] | None = None,
    ) -> int:
        pattern = SubscriptionPattern(
            event_types=event_types,
            from_agents=from_agents,
            path_glob=path_glob,
            tags=tags,
        )
        return await self._event_store.subscriptions.register(self.node_id, pattern)

    async def event_unsubscribe(self, subscription_id: int) -> bool:
        return await self._event_store.subscriptions.unregister(subscription_id)

    async def event_get_history(self, target_id: str, limit: int = 20) -> list[dict[str, Any]]:
        return await self._event_store.get_events_for_agent(target_id, limit=limit)

    async def send_message(self, to_node_id: str, content: str) -> bool:
        if not self._allow_send_message():
            return False
        await self._emit(
            AgentMessageEvent(
                from_agent=self.node_id,
                to_agent=to_node_id,
                content=content,
                correlation_id=self.correlation_id,
            )
        )
        return True

    async def broadcast(self, pattern: str, content: str) -> str:
        nodes = await self._node_store.list_nodes()
        target_ids = _resolve_broadcast_targets(self.node_id, pattern, nodes)
        limited_targets = target_ids[: self._broadcast_max_targets]
        for target_id in limited_targets:
            await self._emit(
                AgentMessageEvent(
                    from_agent=self.node_id,
                    to_agent=target_id,
                    content=content,
                    correlation_id=self.correlation_id,
                )
            )
        return f"Broadcast sent to {len(limited_targets)} agents"

    def _allow_send_message(self) -> bool:
        if self._send_message_limiter is None:
            return True
        return self._send_message_limiter.allow(self.node_id)

    async def request_human_input(
        self,
        question: str,
        options: list[str] | None = None,
    ) -> str:
        request_id = str(uuid.uuid4())
        future = self._event_store.create_response_future(request_id)

        await self._node_store.transition_status(self.node_id, NodeStatus.AWAITING_INPUT)
        await self._emit(
            HumanInputRequestEvent(
                agent_id=self.node_id,
                request_id=request_id,
                question=question,
                options=tuple(options or ()),
                correlation_id=self.correlation_id,
            )
        )

        try:
            return await asyncio.wait_for(future, timeout=self._human_input_timeout_s)
        except TimeoutError:
            self._event_store.discard_response_future(request_id)
            raise
        finally:
            await self._node_store.transition_status(self.node_id, NodeStatus.RUNNING)

    async def propose_changes(self, reason: str = "") -> str:
        proposal_id = str(uuid.uuid4())
        changed_files = await self._collect_changed_files()
        await self._node_store.transition_status(self.node_id, NodeStatus.AWAITING_REVIEW)
        await self._emit(
            RewriteProposalEvent(
                agent_id=self.node_id,
                proposal_id=proposal_id,
                files=tuple(changed_files),
                reason=reason,
                correlation_id=self.correlation_id,
            )
        )
        return proposal_id

    async def _collect_changed_files(self) -> list[str]:
        all_paths = await self.workspace.list_all_paths()
        return sorted(path for path in all_paths if not path.startswith("_bundle/"))

    async def get_node_source(self, target_id: str) -> str:
        node = await self._node_store.get_node(target_id)
        return node.text if node is not None else ""

    async def my_node_id(self) -> str:
        return self.node_id

    async def my_correlation_id(self) -> str | None:
        return self.correlation_id

    async def semantic_search(
        self,
        query: str,
        collection: str | None = None,
        top_k: int = 10,
        mode: str = "hybrid",
    ) -> list[dict[str, Any]]:
        """Search the codebase using semantic similarity."""
        if self._search_service is None or not self._search_service.available:
            return []
        return await self._search_service.search(query, collection, top_k, mode)

    async def find_similar_code(
        self,
        chunk_id: str,
        collection: str | None = None,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """Find code chunks similar to an existing chunk."""
        if self._search_service is None or not self._search_service.available:
            return []
        return await self._search_service.find_similar(chunk_id, collection, top_k)

    def to_capabilities_dict(self) -> dict[str, Any]:
        return {
            "read_file": self.read_file,
            "write_file": self.write_file,
            "list_dir": self.list_dir,
            "file_exists": self.file_exists,
            "search_files": self.search_files,
            "search_content": self.search_content,
            "kv_get": self.kv_get,
            "kv_set": self.kv_set,
            "kv_delete": self.kv_delete,
            "kv_list": self.kv_list,
            "graph_get_node": self.graph_get_node,
            "graph_query_nodes": self.graph_query_nodes,
            "graph_get_edges": self.graph_get_edges,
            "graph_get_children": self.graph_get_children,
            "graph_set_status": self.graph_set_status,
            "event_emit": self.event_emit,
            "event_subscribe": self.event_subscribe,
            "event_unsubscribe": self.event_unsubscribe,
            "event_get_history": self.event_get_history,
            "send_message": self.send_message,
            "broadcast": self.broadcast,
            "request_human_input": self.request_human_input,
            "propose_changes": self.propose_changes,
            "get_node_source": self.get_node_source,
            "my_node_id": self.my_node_id,
            "my_correlation_id": self.my_correlation_id,
            "semantic_search": self.semantic_search,
            "find_similar_code": self.find_similar_code,
        }


def _resolve_broadcast_targets(
    source_id: str,
    pattern: str,
    nodes: list[Node],
) -> list[str]:
    all_ids = [node.node_id for node in nodes if node.node_id != source_id]
    if pattern in {"*", "all"}:
        return all_ids
    if pattern == "siblings":
        source_file = ""
        for node in nodes:
            if node.node_id == source_id:
                source_file = node.file_path
                break
        return [
            node.node_id
            for node in nodes
            if node.node_id != source_id and node.file_path == source_file
        ]
    if pattern.startswith("file:"):
        file_path = pattern.split(":", maxsplit=1)[1]
        return [
            node.node_id
            for node in nodes
            if node.node_id != source_id and node.file_path == file_path
        ]
    return [node_id for node_id in all_ids if pattern in node_id]

__all__ = ["TurnContext"]
