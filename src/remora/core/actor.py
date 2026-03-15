"""Actor model primitives: Outbox and Actor."""

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

from remora.core.config import Config, _expand_env_vars
from remora.core.events import AgentCompleteEvent, AgentErrorEvent, AgentStartEvent
from remora.core.events.store import EventStore
from remora.core.events.types import Event
from remora.core.externals import TurnContext
from remora.core.grail import GrailTool, discover_tools
from remora.core.graph import NodeStore
from remora.core.kernel import create_kernel, extract_response_text
from remora.core.node import Node
from remora.core.types import NodeStatus, NodeType
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


class Actor:
    """Per-agent actor with inbox, outbox, and sequential processing loop.

    Each actor processes one inbox message at a time. Cooldown and depth
    policies are local to the actor, not shared globally.
    """

    def __init__(
        self,
        node_id: str,
        event_store: EventStore,
        node_store: NodeStore,
        workspace_service: CairnWorkspaceService,
        config: Config,
        semaphore: asyncio.Semaphore,
    ) -> None:
        self.node_id = node_id
        self.inbox: asyncio.Queue[Event] = asyncio.Queue()
        self._event_store = event_store
        self._node_store = node_store
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
        """Execute one agent turn."""
        node_id = trigger.node_id
        depth_key = trigger.correlation_id

        async with self._semaphore:
            try:
                start_result = await self._start_agent_turn(node_id, trigger, outbox)
                if start_result is None:
                    return
                node, workspace, bundle_config = start_result

                system_prompt, model_name, max_turns = self._build_system_prompt(
                    bundle_config,
                    trigger,
                )

                _, tools = await self._prepare_turn_context(
                    node_id,
                    workspace,
                    trigger,
                    outbox,
                )

                logger.info(
                    "Agent turn start node=%s corr=%s model=%s tools=%d max_turns=%d trigger=%s",
                    node_id,
                    trigger.correlation_id,
                    model_name,
                    len(tools),
                    max_turns,
                    trigger.event.event_type if trigger.event is not None else "manual",
                )

                messages = [
                    Message(role="system", content=system_prompt),
                    Message(role="user", content=self._build_prompt(node, trigger)),
                ]

                result = await self._run_kernel(
                    node_id,
                    trigger,
                    system_prompt,
                    messages,
                    model_name,
                    tools,
                    max_turns,
                )

                response_text = extract_response_text(result)
                await self._complete_agent_turn(node_id, response_text, outbox, trigger)
            except Exception as exc:  # noqa: BLE001 - boundary should never crash loop
                logger.exception("Agent turn failed for %s", node_id)
                await self._node_store.transition_status(node_id, NodeStatus.ERROR)
                await outbox.emit(
                    AgentErrorEvent(
                        agent_id=node_id,
                        error=str(exc),
                        correlation_id=trigger.correlation_id,
                    )
                )
            finally:
                await self._reset_agent_state(node_id, depth_key)

    async def _start_agent_turn(
        self, node_id: str, trigger: Trigger, outbox: Outbox
    ) -> tuple[Node, AgentWorkspace, dict[str, Any]] | None:
        node = await self._node_store.get_node(node_id)
        if node is None:
            logger.warning("Trigger for unknown node: %s", node_id)
            return None

        if not await self._node_store.transition_status(node_id, NodeStatus.RUNNING):
            logger.warning("Failed to transition node %s into running state", node_id)
            return None

        await outbox.emit(
            AgentStartEvent(
                agent_id=node_id,
                node_name=node.name,
                correlation_id=trigger.correlation_id,
            )
        )

        workspace = await self._workspace_service.get_agent_workspace(node_id)
        bundle_config = await self._read_bundle_config(workspace)
        return node, workspace, bundle_config

    def _build_system_prompt(
        self,
        bundle_config: dict[str, Any],
        trigger: Trigger,
    ) -> tuple[str, str, int]:
        system_prompt = bundle_config.get(
            "system_prompt",
            "You are an autonomous code agent.",
        )
        prompt_extension = bundle_config.get("system_prompt_extension", "")
        if prompt_extension:
            system_prompt = f"{system_prompt}\n\n{prompt_extension}"
        mode = self._turn_mode(trigger.event)
        prompts = bundle_config.get("prompts") or {}
        mode_prompt = prompts.get(mode, "") if hasattr(prompts, "get") else ""
        if mode_prompt:
            system_prompt = f"{system_prompt}\n\n{mode_prompt}"
        model_name = bundle_config.get("model", self._config.model_default)
        max_turns = int(bundle_config.get("max_turns", self._config.max_turns))
        return system_prompt, model_name, max_turns

    async def _prepare_turn_context(
        self, node_id: str, workspace: AgentWorkspace, trigger: Trigger, outbox: Outbox
    ) -> tuple[TurnContext, list[GrailTool]]:
        context = TurnContext(
            node_id=node_id,
            workspace=workspace,
            correlation_id=trigger.correlation_id,
            node_store=self._node_store,
            event_store=self._event_store,
            outbox=outbox,
        )
        capabilities = context.to_capabilities_dict()
        tools = await self._resolve_maybe_awaitable(discover_tools(workspace, capabilities))
        return context, tools

    async def _run_kernel(
        self,
        node_id: str,
        trigger: Trigger,
        system_prompt: str,
        messages: list[Message],
        model_name: str,
        tools: list[GrailTool],
        max_turns: int,
    ) -> Any:
        max_retries = 1
        last_exc: Exception | None = None
        tool_schemas = [tool.schema for tool in tools]

        for attempt in range(max_retries + 1):
            kernel = create_kernel(
                model_name=model_name,
                base_url=self._config.model_base_url,
                api_key=self._config.model_api_key,
                timeout=self._config.timeout_s,
                tools=tools,
            )
            try:
                if attempt == 0:
                    logger.info(
                        (
                            "Model request node=%s corr=%s base_url=%s model=%s "
                            "tools=%s system=%s user=%s"
                        ),
                        node_id,
                        trigger.correlation_id,
                        self._config.model_base_url,
                        model_name,
                        [schema.name for schema in tool_schemas],
                        system_prompt,
                        messages[1].content or "",
                    )
                else:
                    logger.warning(
                        "Retrying model request node=%s attempt=%d/%d",
                        node_id,
                        attempt + 1,
                        max_retries + 1,
                    )
                return await kernel.run(messages, tool_schemas, max_turns=max_turns)
            except Exception as exc:
                last_exc = exc
                if attempt < max_retries:
                    backoff = 2.0**attempt
                    logger.warning(
                        "Model request failed node=%s attempt=%d, retrying in %.1fs: %s",
                        node_id,
                        attempt + 1,
                        backoff,
                        exc,
                    )
                    await asyncio.sleep(backoff)
                    continue
                raise
            finally:
                await kernel.close()

        raise RuntimeError(str(last_exc) if last_exc is not None else "kernel run failed")

    async def _complete_agent_turn(
        self, node_id: str, response_text: str, outbox: Outbox, trigger: Trigger
    ) -> None:
        logger.info(
            "Agent turn complete node=%s corr=%s response=%s",
            node_id,
            trigger.correlation_id,
            response_text,
        )
        await outbox.emit(
            AgentCompleteEvent(
                agent_id=node_id,
                result_summary=response_text[:200],
                full_response=response_text,
                correlation_id=trigger.correlation_id,
            )
        )

    async def _reset_agent_state(self, node_id: str, depth_key: str | None) -> None:
        try:
            current_node = await self._node_store.get_node(node_id)
            if current_node is not None and current_node.status == NodeStatus.RUNNING:
                await self._node_store.transition_status(node_id, NodeStatus.IDLE)
        except Exception:  # noqa: BLE001 - best effort cleanup
            logger.exception("Failed to reset node status for %s", node_id)
        if depth_key is not None:
            remaining = self._depths.get(depth_key, 1) - 1
            if remaining <= 0:
                self._depths.pop(depth_key, None)
            else:
                self._depths[depth_key] = remaining

    @staticmethod
    def _build_prompt(node: Node, trigger: Trigger) -> str:
        """Build the turn prompt from node identity and trigger details."""
        node_type = (
            node.node_type.value if hasattr(node.node_type, "value") else str(node.node_type)
        )
        parts = [
            f"# Node: {node.full_name}",
            f"Type: {node_type} | File: {node.file_path}",
        ]
        if node.node_type == NodeType.VIRTUAL:
            parts.extend(
                [
                    "",
                    "## Role",
                    f"You are a {node.role or 'virtual'} agent.",
                    "Use your tools and incoming events to coordinate work.",
                ]
            )
        elif node.source_code:
            parts.extend(
                [
                    "",
                    "## Source Code",
                    "```",
                    node.source_code,
                    "```",
                ]
            )
        else:
            parts.extend(
                [
                    "",
                    "## Structure",
                    "This is a directory node. Use your tools to inspect children and subtree.",
                ]
            )
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
        try:
            loaded = yaml.safe_load(text) or {}
        except yaml.YAMLError:
            logger.warning("Ignoring malformed _bundle/bundle.yaml")
            return {}
        if not isinstance(loaded, dict):
            return {}

        expanded = _expand_env_vars(loaded)
        if not isinstance(expanded, dict):
            return {}

        validated: dict[str, Any] = {}
        for key in ("system_prompt", "system_prompt_extension", "model"):
            value = expanded.get(key)
            if isinstance(value, str) and value.strip():
                validated[key] = value

        max_turns = expanded.get("max_turns")
        if max_turns is not None:
            try:
                validated["max_turns"] = max(1, int(max_turns))
            except (TypeError, ValueError):
                pass

        prompts = expanded.get("prompts")
        if isinstance(prompts, dict):
            prompt_values: dict[str, str] = {}
            for mode in ("chat", "reactive"):
                value = prompts.get(mode)
                if isinstance(value, str) and value.strip():
                    prompt_values[mode] = value
            if prompt_values:
                validated["prompts"] = prompt_values

        return validated

    @staticmethod
    def _turn_mode(event: Event | None) -> str:
        from_agent = getattr(event, "from_agent", None) if event is not None else None
        return "chat" if from_agent == "user" else "reactive"


def _event_content(event: Event) -> str:
    if hasattr(event, "content"):
        return str(event.content)
    return ""


__all__ = ["Outbox", "RecordingOutbox", "Trigger", "Actor"]
