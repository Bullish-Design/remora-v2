"""The unified agent runner and externals contract."""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from fsdantic import FileNotFoundError as FsdFileNotFoundError
from structured_agents import Message

from remora.core.config import Config
from remora.core.events import (
    AgentCompleteEvent,
    AgentErrorEvent,
    AgentMessageEvent,
    AgentStartEvent,
    ContentChangedEvent,
    CustomEvent,
    Event,
    EventStore,
    SubscriptionPattern,
    TriggerDispatcher,
)
from remora.core.grail import discover_tools
from remora.core.graph import NodeStore
from remora.core.kernel import create_kernel, extract_response_text
from remora.core.node import CodeNode
from remora.core.types import NodeStatus
from remora.core.workspace import AgentWorkspace, CairnWorkspaceService

logger = logging.getLogger(__name__)


@dataclass
class Trigger:
    """A trigger waiting to be executed."""

    node_id: str
    correlation_id: str
    event: Event | None = None


class AgentRunner:
    """Unified execution coordinator for all agent turns."""

    def __init__(
        self,
        event_store: EventStore,
        node_store: NodeStore,
        workspace_service: CairnWorkspaceService,
        config: Config,
        dispatcher: TriggerDispatcher | None = None,
    ):
        self._event_store = event_store
        self._dispatcher = dispatcher or event_store.dispatcher
        self._node_store = node_store
        self._workspace_service = workspace_service
        self._config = config
        self._running = False
        self._semaphore = asyncio.Semaphore(config.max_concurrency)
        self._cooldowns: dict[str, float] = {}
        self._depths: dict[str, int] = {}

    async def run_forever(self) -> None:
        """Consume triggers from EventStore until stopped."""
        self._running = True
        try:
            async for node_id, event in self._dispatcher.get_triggers():
                if not self._running:
                    break
                correlation_id = event.correlation_id or str(uuid.uuid4())
                await self.trigger(node_id, correlation_id, event)
        finally:
            self._running = False

    def stop(self) -> None:
        """Stop the run loop."""
        self._running = False

    async def trigger(
        self, node_id: str, correlation_id: str, event: Event | None = None
    ) -> None:
        """Enqueue a trigger with cooldown and depth checks."""
        now_ms = time.time() * 1000.0
        cutoff_ms = now_ms - 60_000.0
        stale_keys = [key for key, value in self._cooldowns.items() if value < cutoff_ms]
        for key in stale_keys:
            del self._cooldowns[key]

        last_ms = self._cooldowns.get(node_id, 0.0)
        if now_ms - last_ms < self._config.trigger_cooldown_ms:
            return
        self._cooldowns[node_id] = now_ms

        depth_key = f"{node_id}:{correlation_id}"
        depth = self._depths.get(depth_key, 0)
        if depth >= self._config.max_trigger_depth:
            await self._event_store.append(
                AgentErrorEvent(
                    agent_id=node_id,
                    error="Cascade depth limit exceeded",
                    correlation_id=correlation_id,
                )
            )
            return

        self._depths[depth_key] = depth + 1
        asyncio.create_task(self._execute_turn(Trigger(node_id, correlation_id, event)))

    async def _execute_turn(self, trigger: Trigger) -> None:
        """Execute one agent turn from trigger to completion/error events."""
        node_id = trigger.node_id
        depth_key = f"{node_id}:{trigger.correlation_id}"

        async with self._semaphore:
            try:
                node = await self._node_store.get_node(node_id)
                if node is None:
                    logger.warning("Trigger for unknown node: %s", node_id)
                    return

                if not await self._node_store.transition_status(node_id, NodeStatus.RUNNING):
                    logger.warning("Failed to transition node %s into running state", node_id)
                    return
                await self._event_store.append(
                    AgentStartEvent(
                        agent_id=node_id,
                        node_name=node.name,
                        correlation_id=trigger.correlation_id,
                    )
                )

                workspace = await self._workspace_service.get_agent_workspace(node_id)
                bundle_config = await self._read_bundle_config(workspace)
                system_prompt = bundle_config.get(
                    "system_prompt",
                    "You are an autonomous code agent.",
                )
                model_name = bundle_config.get("model", self._config.model_default)
                max_turns = int(bundle_config.get("max_turns", self._config.max_turns))

                externals = self._build_externals(node_id, workspace, trigger.correlation_id)
                tools = await self._resolve_maybe_awaitable(discover_tools(workspace, externals))

                messages = [
                    Message(role="system", content=system_prompt),
                    Message(role="user", content=self._build_prompt(node, trigger)),
                ]

                kernel = create_kernel(
                    model_name=model_name,
                    base_url=self._config.model_base_url,
                    api_key=self._config.model_api_key,
                    timeout=self._config.timeout_s,
                    tools=tools,
                )
                try:
                    tool_schemas = [tool.schema for tool in tools]
                    result = await kernel.run(messages, tool_schemas, max_turns=max_turns)
                finally:
                    await kernel.close()

                response_text = extract_response_text(result)
                await self._event_store.append(
                    AgentCompleteEvent(
                        agent_id=node_id,
                        result_summary=response_text[:200],
                        correlation_id=trigger.correlation_id,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - boundary should never crash loop
                logger.exception("Agent turn failed for %s", node_id)
                await self._node_store.transition_status(node_id, NodeStatus.ERROR)
                await self._event_store.append(
                    AgentErrorEvent(
                        agent_id=node_id,
                        error=str(exc),
                        correlation_id=trigger.correlation_id,
                    )
                )
            finally:
                try:
                    current_node = await self._node_store.get_node(node_id)
                    if current_node is not None and current_node.status == NodeStatus.RUNNING:
                        await self._node_store.transition_status(node_id, NodeStatus.IDLE)
                except Exception:  # noqa: BLE001 - best effort cleanup
                    logger.exception("Failed to reset node status for %s", node_id)
                remaining = self._depths.get(depth_key, 1) - 1
                if remaining <= 0:
                    self._depths.pop(depth_key, None)
                else:
                    self._depths[depth_key] = remaining

    def _build_prompt(self, node: CodeNode, trigger: Trigger) -> str:
        """Build the turn prompt from node identity and trigger details."""
        parts = [
            f"# Node: {node.full_name}",
            f"Type: {node.node_type} | File: {node.file_path}:{node.start_line}-{node.end_line}",
            "",
            "## Source Code",
            "```",
            node.source_code,
            "```",
        ]
        if trigger.event is not None:
            parts.extend(["", "## Trigger", f"Event: {trigger.event.event_type}"])
            content = self._event_content(trigger.event)
            if content:
                parts.append(f"Content: {content}")
        return "\n".join(parts)

    def _build_externals(
        self, node_id: str, workspace: AgentWorkspace, correlation_id: str | None
    ) -> dict[str, Any]:
        """Build the complete externals dictionary for Grail tools."""

        async def read_file(path: str) -> str:
            return await workspace.read(path)

        async def write_file(path: str, content: str) -> bool:
            await workspace.write(path, content)
            return True

        async def list_dir(path: str = ".") -> list[str]:
            return await workspace.list_dir(path)

        async def file_exists(path: str) -> bool:
            return await workspace.exists(path)

        async def search_files(pattern: str) -> list[str]:
            paths = await workspace.list_all_paths()
            return sorted(path for path in paths if fnmatch.fnmatch(path, f"*{pattern}*"))

        async def search_content(pattern: str, path: str = ".") -> list[dict[str, Any]]:
            matches: list[dict[str, Any]] = []
            paths = await workspace.list_all_paths()
            for file_path in paths:
                normalized = file_path.strip("/")
                if path not in {".", "/", ""} and not normalized.startswith(path.strip("/")):
                    continue
                try:
                    content = await workspace.read(normalized)
                except FileNotFoundError:
                    continue
                for index, line in enumerate(content.splitlines(), start=1):
                    if pattern in line:
                        matches.append({"file": normalized, "line": index, "text": line})
            return matches

        async def graph_get_node(target_id: str) -> dict[str, Any]:
            node = await self._node_store.get_node(target_id)
            return node.model_dump() if node is not None else {}

        async def graph_query_nodes(
            node_type: str | None = None,
            status: str | None = None,
            file_path: str | None = None,
        ) -> list[dict[str, Any]]:
            nodes = await self._node_store.list_nodes(
                node_type=node_type,
                status=status,
                file_path=file_path,
            )
            return [node.model_dump() for node in nodes]

        async def graph_get_edges(target_id: str) -> list[dict[str, Any]]:
            edges = await self._node_store.get_edges(target_id)
            return [
                {"from_id": edge.from_id, "to_id": edge.to_id, "edge_type": edge.edge_type}
                for edge in edges
            ]

        async def graph_set_status(target_id: str, new_status: str) -> bool:
            await self._node_store.set_status(target_id, new_status)
            return True

        async def event_emit(event_type: str, payload: dict[str, Any]) -> bool:
            event = CustomEvent(
                event_type=event_type,
                payload=payload,
                correlation_id=correlation_id,
            )
            await self._event_store.append(event)
            return True

        async def event_subscribe(
            event_types: list[str] | None = None,
            from_agents: list[str] | None = None,
            path_glob: str | None = None,
        ) -> int:
            pattern = SubscriptionPattern(
                event_types=event_types,
                from_agents=from_agents,
                path_glob=path_glob,
            )
            return await self._event_store.subscriptions.register(node_id, pattern)

        async def event_unsubscribe(subscription_id: int) -> bool:
            return await self._event_store.subscriptions.unregister(subscription_id)

        async def event_get_history(target_id: str, limit: int = 20) -> list[dict[str, Any]]:
            return await self._event_store.get_events_for_agent(target_id, limit=limit)

        async def send_message(to_node_id: str, content: str) -> bool:
            await self._event_store.append(
                AgentMessageEvent(
                    from_agent=node_id,
                    to_agent=to_node_id,
                    content=content,
                    correlation_id=correlation_id,
                )
            )
            return True

        async def broadcast(pattern: str, content: str) -> str:
            nodes = await self._node_store.list_nodes()
            target_ids = self._resolve_broadcast_targets(node_id, pattern, nodes)
            for target_id in target_ids:
                await self._event_store.append(
                    AgentMessageEvent(
                        from_agent=node_id,
                        to_agent=target_id,
                        content=content,
                        correlation_id=correlation_id,
                    )
                )
            return f"Broadcast sent to {len(target_ids)} agents"

        async def apply_rewrite(new_source: str) -> bool:
            node = await self._node_store.get_node(node_id)
            if node is None:
                return False

            try:
                file_path = Path(node.file_path)
                if not file_path.exists():
                    return False
                full_bytes = file_path.read_bytes()
            except OSError:
                return False

            if node.start_byte > 0 or node.end_byte > 0:
                before = full_bytes[: node.start_byte].decode("utf-8", errors="replace")
                after = full_bytes[node.end_byte :].decode("utf-8", errors="replace")
                next_text = before + new_source + after
            else:
                full_text = full_bytes.decode("utf-8", errors="replace")
                next_text = full_text.replace(node.source_code, new_source, 1)

            file_path.write_text(next_text, encoding="utf-8")
            await self._event_store.append(
                ContentChangedEvent(
                    path=str(file_path),
                    change_type="modified",
                    correlation_id=correlation_id,
                )
            )
            return True

        async def get_node_source(target_id: str) -> str:
            node = await self._node_store.get_node(target_id)
            return node.source_code if node is not None else ""

        return {
            "read_file": read_file,
            "write_file": write_file,
            "list_dir": list_dir,
            "file_exists": file_exists,
            "search_files": search_files,
            "search_content": search_content,
            "graph_get_node": graph_get_node,
            "graph_query_nodes": graph_query_nodes,
            "graph_get_edges": graph_get_edges,
            "graph_set_status": graph_set_status,
            "event_emit": event_emit,
            "event_subscribe": event_subscribe,
            "event_unsubscribe": event_unsubscribe,
            "event_get_history": event_get_history,
            "send_message": send_message,
            "broadcast": broadcast,
            "apply_rewrite": apply_rewrite,
            "get_node_source": get_node_source,
            "my_node_id": node_id,
            "my_correlation_id": correlation_id,
        }

    @staticmethod
    def _event_content(event: Event) -> str:
        if hasattr(event, "content"):
            return str(event.content)
        if hasattr(event, "message"):
            return str(event.message)
        return ""

    @staticmethod
    async def _resolve_maybe_awaitable(value: Any) -> Any:
        if asyncio.iscoroutine(value):
            return await value
        return value

    async def _read_bundle_config(self, workspace: AgentWorkspace) -> dict[str, Any]:
        try:
            text = await workspace.read("_bundle/bundle.yaml")
        except (FileNotFoundError, FsdFileNotFoundError):
            return {}
        return yaml.safe_load(text) or {}

    @staticmethod
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


__all__ = ["Trigger", "AgentRunner"]
