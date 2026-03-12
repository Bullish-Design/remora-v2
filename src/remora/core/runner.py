"""The unified agent runner and externals contract."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

import yaml
from fsdantic import FileNotFoundError as FsdFileNotFoundError
from structured_agents import Message

from remora.core.config import Config
from remora.core.events import (
    AgentCompleteEvent,
    AgentErrorEvent,
    AgentStartEvent,
    Event,
    EventStore,
    TriggerDispatcher,
)
from remora.core.externals import AgentContext
from remora.core.grail import discover_tools
from remora.core.graph import AgentStore, NodeStore
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
        agent_store: AgentStore,
        workspace_service: CairnWorkspaceService,
        config: Config,
        dispatcher: TriggerDispatcher | None = None,
    ):
        self._event_store = event_store
        self._dispatcher = dispatcher or event_store.dispatcher
        self._node_store = node_store
        self._agent_store = agent_store
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

                if await self._agent_store.get_agent(node_id) is None:
                    await self._agent_store.upsert_agent(node.to_agent())
                if not await self._agent_store.transition_status(node_id, NodeStatus.RUNNING):
                    logger.warning("Failed to transition node %s into running state", node_id)
                    return
                await self._node_store.transition_status(node_id, NodeStatus.RUNNING)
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

                context = AgentContext(
                    node_id=node_id,
                    workspace=workspace,
                    correlation_id=trigger.correlation_id,
                    node_store=self._node_store,
                    agent_store=self._agent_store,
                    event_store=self._event_store,
                )
                externals = context.to_externals_dict()
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
                await self._agent_store.transition_status(node_id, NodeStatus.ERROR)
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
                    current_agent = await self._agent_store.get_agent(node_id)
                    if current_agent is not None and current_agent.status == NodeStatus.RUNNING:
                        await self._agent_store.transition_status(node_id, NodeStatus.IDLE)
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


__all__ = ["Trigger", "AgentRunner"]
