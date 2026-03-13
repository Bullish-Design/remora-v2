"""Agent externals - API surface available to agent tool scripts."""

from __future__ import annotations

import fnmatch
import hashlib
from pathlib import Path
from typing import Any

from remora.core.events import (
    AgentMessageEvent,
    ContentChangedEvent,
    CustomEvent,
    SubscriptionPattern,
)
from remora.core.events.store import EventStore
from remora.core.events.types import Event
from remora.core.graph import AgentStore, NodeStore
from remora.core.node import CodeNode
from remora.core.types import NodeStatus, NodeType
from remora.core.workspace import AgentWorkspace


class AgentContext:
    """Per-turn context providing externals API for an agent's tools."""

    def __init__(
        self,
        node_id: str,
        workspace: AgentWorkspace,
        correlation_id: str | None,
        node_store: NodeStore,
        agent_store: AgentStore,
        event_store: EventStore,
        outbox: Any,
    ) -> None:
        self.node_id = node_id
        self.workspace = workspace
        self.correlation_id = correlation_id
        self._node_store = node_store
        self._agent_store = agent_store
        self._event_store = event_store
        self._outbox = outbox

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
        return matches

    async def graph_get_node(self, target_id: str) -> dict[str, Any]:
        node = await self._node_store.get_node(target_id)
        return node.model_dump() if node is not None else {}

    async def graph_query_nodes(
        self,
        node_type: str | None = None,
        status: str | None = None,
        file_path: str | None = None,
    ) -> list[dict[str, Any]]:
        normalized_node_type: str | None = None
        if node_type is not None:
            normalized_node_type = node_type.strip()
            valid_node_types = {item.value for item in NodeType}
            if normalized_node_type not in valid_node_types:
                choices = ", ".join(sorted(valid_node_types))
                raise ValueError(
                    f"Invalid node_type '{node_type}'. Expected one of: {choices}"
                )

        normalized_status: str | None = None
        if status is not None:
            normalized_status = status.strip()
            valid_statuses = {item.value for item in NodeStatus}
            if normalized_status not in valid_statuses:
                choices = ", ".join(sorted(valid_statuses))
                raise ValueError(f"Invalid status '{status}'. Expected one of: {choices}")

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
        await self._agent_store.set_status(target_id, new_status)
        await self._node_store.set_status(target_id, new_status)
        return True

    async def event_emit(self, event_type: str, payload: dict[str, Any]) -> bool:
        event = CustomEvent(
            event_type=event_type,
            payload=payload,
            correlation_id=self.correlation_id,
        )
        await self._emit(event)
        return True

    async def event_subscribe(
        self,
        event_types: list[str] | None = None,
        from_agents: list[str] | None = None,
        path_glob: str | None = None,
    ) -> int:
        pattern = SubscriptionPattern(
            event_types=event_types,
            from_agents=from_agents,
            path_glob=path_glob,
        )
        return await self._event_store.subscriptions.register(self.node_id, pattern)

    async def event_unsubscribe(self, subscription_id: int) -> bool:
        return await self._event_store.subscriptions.unregister(subscription_id)

    async def event_get_history(self, target_id: str, limit: int = 20) -> list[dict[str, Any]]:
        return await self._event_store.get_events_for_agent(target_id, limit=limit)

    async def send_message(self, to_node_id: str, content: str) -> bool:
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
        for target_id in target_ids:
            await self._emit(
                AgentMessageEvent(
                    from_agent=self.node_id,
                    to_agent=target_id,
                    content=content,
                    correlation_id=self.correlation_id,
                )
            )
        return f"Broadcast sent to {len(target_ids)} agents"

    async def apply_rewrite(self, new_source: str) -> bool:
        node = await self._node_store.get_node(self.node_id)
        if node is None:
            return False

        file_path = Path(node.file_path)
        if not file_path.exists():
            return False

        full_bytes = file_path.read_bytes()
        if node.start_byte > 0 or node.end_byte > 0:
            before = full_bytes[: node.start_byte].decode("utf-8", errors="replace")
            after = full_bytes[node.end_byte :].decode("utf-8", errors="replace")
            next_text = before + new_source + after
        else:
            full_text = full_bytes.decode("utf-8", errors="replace")
            next_text = full_text.replace(node.source_code, new_source, 1)

        old_hash = hashlib.sha256(full_bytes).hexdigest()
        new_hash = hashlib.sha256(next_text.encode("utf-8")).hexdigest()
        file_path.write_text(next_text, encoding="utf-8")
        await self._emit(
            ContentChangedEvent(
                path=str(file_path),
                change_type="modified",
                agent_id=self.node_id,
                old_hash=old_hash,
                new_hash=new_hash,
                correlation_id=self.correlation_id,
            )
        )
        return True

    async def get_node_source(self, target_id: str) -> str:
        node = await self._node_store.get_node(target_id)
        return node.source_code if node is not None else ""

    async def my_node_id(self) -> str:
        return self.node_id

    async def my_correlation_id(self) -> str | None:
        return self.correlation_id

    def to_externals_dict(self) -> dict[str, Any]:
        return {
            "read_file": self.read_file,
            "write_file": self.write_file,
            "list_dir": self.list_dir,
            "file_exists": self.file_exists,
            "search_files": self.search_files,
            "search_content": self.search_content,
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
            "apply_rewrite": self.apply_rewrite,
            "get_node_source": self.get_node_source,
            "my_node_id": self.my_node_id,
            "my_correlation_id": self.my_correlation_id,
        }


def _resolve_broadcast_targets(
    source_id: str,
    pattern: str,
    nodes: list[CodeNode],
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


__all__ = ["AgentContext"]
