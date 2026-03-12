"""Actor model primitives: Outbox and AgentActor."""

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
from remora.core.events import AgentCompleteEvent, AgentErrorEvent, AgentStartEvent
from remora.core.events.store import EventStore
from remora.core.events.types import Event
from remora.core.externals import AgentContext
from remora.core.grail import discover_tools
from remora.core.graph import AgentStore, NodeStore
from remora.core.kernel import create_kernel, extract_response_text
from remora.core.node import CodeNode
from remora.core.types import NodeStatus
from remora.core.workspace import AgentWorkspace, CairnWorkspaceService

logger = logging.getLogger(__name__)


class Outbox:
    """Write-through emitter that tags events with actor metadata.

    Not a buffer - events reach EventStore immediately on emit().
    The outbox exists as an interception/tagging point, not as storage.
    """

    def __init__(
        self,
        actor_id: str,
        event_store: EventStore,
        correlation_id: str | None = None,
    ) -> None:
        self._actor_id = actor_id
        self._event_store = event_store
        self._correlation_id = correlation_id
        self._sequence = 0

    @property
    def actor_id(self) -> str:
        return self._actor_id

    @property
    def correlation_id(self) -> str | None:
        return self._correlation_id

    @correlation_id.setter
    def correlation_id(self, value: str | None) -> None:
        self._correlation_id = value

    @property
    def sequence(self) -> int:
        return self._sequence

    async def emit(self, event: Event) -> int:
        """Tag event with actor metadata and write through to EventStore."""
        self._sequence += 1
        if not event.correlation_id and self._correlation_id:
            event.correlation_id = self._correlation_id
        return await self._event_store.append(event)


class RecordingOutbox:
    """Test double that records emitted events without persisting.

    Drop-in replacement for Outbox in unit tests.
    """

    def __init__(self, actor_id: str = "test") -> None:
        self._actor_id = actor_id
        self._correlation_id: str | None = None
        self._sequence = 0
        self.events: list[Event] = []

    @property
    def actor_id(self) -> str:
        return self._actor_id

    @property
    def correlation_id(self) -> str | None:
        return self._correlation_id

    @correlation_id.setter
    def correlation_id(self, value: str | None) -> None:
        self._correlation_id = value

    @property
    def sequence(self) -> int:
        return self._sequence

    async def emit(self, event: Event) -> int:
        """Record event without persisting."""
        self._sequence += 1
        if not event.correlation_id and self._correlation_id:
            event.correlation_id = self._correlation_id
        self.events.append(event)
        return self._sequence


@dataclass
class Trigger:
    """A trigger waiting to be executed."""

    node_id: str
    correlation_id: str
    event: Event | None = None


class AgentActor:
    """Per-agent actor with inbox, outbox, and sequential processing loop.

    Each actor processes one inbox message at a time. Cooldown and depth
    policies are local to the actor, not shared globally.
    """

    def __init__(
        self,
        node_id: str,
        event_store: EventStore,
        node_store: NodeStore,
        agent_store: AgentStore,
        workspace_service: CairnWorkspaceService,
        config: Config,
        semaphore: asyncio.Semaphore,
    ) -> None:
        self.node_id = node_id
        self.inbox: asyncio.Queue[Event] = asyncio.Queue()
        self._event_store = event_store
        self._node_store = node_store
        self._agent_store = agent_store
        self._workspace_service = workspace_service
        self._config = config
        self._semaphore = semaphore
        self._task: asyncio.Task | None = None
        self._last_active: float = time.time()

        # Per-actor policy state (moved from global runner dicts)
        self._last_trigger_ms: float = 0.0
        self._depths: dict[str, int] = {}

    @property
    def last_active(self) -> float:
        return self._last_active

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        """Launch the actor's processing loop as a managed asyncio.Task."""
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(), name=f"actor-{self.node_id}")

    async def stop(self) -> None:
        """Cancel the processing loop and wait for it to finish."""
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def _run(self) -> None:
        """Main processing loop: consume inbox events one at a time."""
        try:
            while True:
                event = await self.inbox.get()
                self._last_active = time.time()
                correlation_id = event.correlation_id or str(uuid.uuid4())

                if not self._should_trigger(correlation_id):
                    continue

                outbox = Outbox(
                    actor_id=self.node_id,
                    event_store=self._event_store,
                    correlation_id=correlation_id,
                )
                trigger = Trigger(
                    node_id=self.node_id,
                    correlation_id=correlation_id,
                    event=event,
                )
                await self._execute_turn(trigger, outbox)
        except asyncio.CancelledError:
            return

    def _should_trigger(self, correlation_id: str) -> bool:
        """Check cooldown and depth policies. Returns True if trigger should proceed."""
        now_ms = time.time() * 1000.0

        # Cooldown check
        if now_ms - self._last_trigger_ms < self._config.trigger_cooldown_ms:
            return False
        self._last_trigger_ms = now_ms

        # Depth check
        depth = self._depths.get(correlation_id, 0)
        if depth >= self._config.max_trigger_depth:
            return False
        self._depths[correlation_id] = depth + 1

        # Clean stale depth entries
        # (done here rather than on a timer to keep it simple)
        return True

    async def _execute_turn(self, trigger: Trigger, outbox: Outbox) -> None:
        """Execute one agent turn. Reuses logic from the old AgentRunner._execute_turn."""
        node_id = trigger.node_id
        depth_key = trigger.correlation_id

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
                await outbox.emit(
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
                await outbox.emit(
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
                await outbox.emit(
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

    @staticmethod
    def _build_prompt(node: CodeNode, trigger: Trigger) -> str:
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
            content = _event_content(trigger.event)
            if content:
                parts.append(f"Content: {content}")
        return "\n".join(parts)

    @staticmethod
    async def _resolve_maybe_awaitable(value: Any) -> Any:
        if asyncio.iscoroutine(value):
            return await value
        return value

    @staticmethod
    async def _read_bundle_config(workspace: AgentWorkspace) -> dict[str, Any]:
        try:
            text = await workspace.read("_bundle/bundle.yaml")
        except (FileNotFoundError, FsdFileNotFoundError):
            return {}
        return yaml.safe_load(text) or {}


def _event_content(event: Event) -> str:
    if hasattr(event, "content"):
        return str(event.content)
    if hasattr(event, "message"):
        return str(event.message)
    return ""


__all__ = ["Outbox", "RecordingOutbox", "Trigger", "AgentActor"]
