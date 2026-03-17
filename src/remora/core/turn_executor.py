"""Turn execution pipeline for actor-triggered agent turns."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import yaml
from fsdantic import FileNotFoundError as FsdFileNotFoundError
from pydantic import ValidationError
from structured_agents import Message

from remora.core.config import BundleConfig, Config, expand_env_vars
from remora.core.events import AgentCompleteEvent, AgentErrorEvent, AgentStartEvent
from remora.core.events.store import EventStore
from remora.core.externals import TurnContext
from remora.core.grail import GrailTool, discover_tools
from remora.core.graph import NodeStore
from remora.core.kernel import create_kernel, extract_response_text
from remora.core.metrics import Metrics
from remora.core.node import Node
from remora.core.outbox import Outbox, OutboxObserver
from remora.core.prompt import PromptBuilder
from remora.core.rate_limit import SlidingWindowRateLimiter
from remora.core.search import SearchServiceProtocol
from remora.core.trigger import Trigger, TriggerPolicy
from remora.core.types import EventType, NodeStatus
from remora.core.workspace import AgentWorkspace, CairnWorkspaceService

logger = logging.getLogger(__name__)


def _turn_logger(node_id: str, correlation_id: str, turn_number: int) -> logging.LoggerAdapter:
    """Create a logger adapter with per-turn context fields."""
    return logging.LoggerAdapter(
        logger,
        {
            "node_id": node_id,
            "correlation_id": correlation_id,
            "turn": turn_number,
        },
    )


class AgentTurnExecutor:
    """Execute a single agent turn including workspace, tools, and kernel calls."""

    def __init__(
        self,
        *,
        node_store: NodeStore,
        event_store: EventStore,
        workspace_service: CairnWorkspaceService,
        config: Config,
        semaphore: asyncio.Semaphore,
        metrics: Metrics | None,
        history: list[Message],
        prompt_builder: PromptBuilder,
        trigger_policy: TriggerPolicy,
        search_service: SearchServiceProtocol | None,
        send_message_limiter: SlidingWindowRateLimiter | None = None,
    ) -> None:
        self._node_store = node_store
        self._event_store = event_store
        self._workspace_service = workspace_service
        self._config = config
        self._semaphore = semaphore
        self._metrics = metrics
        self._history = history
        self._prompt_builder = prompt_builder
        self._trigger_policy = trigger_policy
        self._search_service = search_service
        self._send_message_limiter = send_message_limiter

    async def execute_turn(self, trigger: Trigger, outbox: Outbox) -> None:
        """Execute one agent turn."""
        node_id = trigger.node_id
        depth_key = trigger.correlation_id
        turn_number = max(1, self._trigger_policy.depths.get(depth_key, 1))
        turn_log = _turn_logger(node_id, trigger.correlation_id, turn_number)

        async with self._semaphore:
            try:
                start_result = await self._start_agent_turn(node_id, trigger, outbox, turn_log)
                if start_result is None:
                    return
                node, workspace, bundle_config = start_result

                system_prompt, model_name, max_turns = self._prompt_builder.build_system_prompt(
                    bundle_config,
                    trigger.event,
                )
                is_reflection_turn = (
                    trigger.event is not None
                    and trigger.event.event_type == EventType.AGENT_COMPLETE
                    and "primary" in getattr(trigger.event, "tags", ())
                )
                if not is_reflection_turn:
                    companion_context = await self._build_companion_context(workspace)
                    if companion_context:
                        system_prompt = f"{system_prompt}\n{companion_context}"

                _, tools = await self._prepare_turn_context(
                    node_id,
                    workspace,
                    trigger,
                    outbox,
                )

                turn_log.debug(
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
                    Message(
                        role="user",
                        content=self._prompt_builder.build_prompt(node, trigger.event),
                    ),
                ]
                user_message = messages[1].content if len(messages) > 1 else ""
                self._history.extend(messages)

                result = await self._run_kernel(
                    node_id,
                    trigger,
                    system_prompt,
                    messages,
                    model_name,
                    tools,
                    max_turns,
                    outbox,
                    turn_log,
                )

                response_text = extract_response_text(result)
                self._history.append(Message(role="assistant", content=response_text))
                turn_tags = ("reflection",) if is_reflection_turn else ("primary",)
                await self._complete_agent_turn(
                    node_id,
                    response_text,
                    outbox,
                    trigger,
                    turn_log,
                    turn_tags=turn_tags,
                    user_message=user_message,
                )
                if self._metrics is not None:
                    self._metrics.agent_turns_total += 1
            # Error boundary: a single turn failure must not crash the actor loop.
            except Exception as exc:  # noqa: BLE001 - boundary should never crash loop
                turn_log.exception("Agent turn failed")
                if self._metrics is not None:
                    self._metrics.agent_turns_failed += 1
                await self._node_store.transition_status(node_id, NodeStatus.ERROR)
                await outbox.emit(
                    AgentErrorEvent(
                        agent_id=node_id,
                        error=str(exc),
                        correlation_id=trigger.correlation_id,
                    )
                )
            finally:
                await self._reset_agent_state(node_id, depth_key, turn_log)

    async def _start_agent_turn(
        self,
        node_id: str,
        trigger: Trigger,
        outbox: Outbox,
        turn_log: logging.LoggerAdapter,
    ) -> tuple[Node, AgentWorkspace, BundleConfig] | None:
        node = await self._node_store.get_node(node_id)
        if node is None:
            turn_log.warning("Trigger for unknown node")
            return None

        if not await self._node_store.transition_status(node_id, NodeStatus.RUNNING):
            turn_log.warning("Failed to transition node into running state")
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
            human_input_timeout_s=self._config.human_input_timeout_s,
            search_content_max_matches=self._config.search_content_max_matches,
            broadcast_max_targets=self._config.broadcast_max_targets,
            send_message_limiter=self._send_message_limiter,
            search_service=self._search_service,
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
        outbox: Outbox,
        turn_log: logging.LoggerAdapter,
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
                observer=OutboxObserver(outbox=outbox, agent_id=node_id),
            )
            try:
                if attempt == 0:
                    turn_log.debug(
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
                    turn_log.warning(
                        "Retrying model request node=%s attempt=%d/%d",
                        node_id,
                        attempt + 1,
                        max_retries + 1,
                    )
                return await kernel.run(messages, tool_schemas, max_turns=max_turns)
            # Error boundary: kernel/model failures are retried and surfaced as turn errors.
            except Exception as exc:
                last_exc = exc
                if attempt < max_retries:
                    backoff = 2.0**attempt
                    turn_log.warning(
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
        self,
        node_id: str,
        response_text: str,
        outbox: Outbox,
        trigger: Trigger,
        turn_log: logging.LoggerAdapter,
        *,
        turn_tags: tuple[str, ...] = ("primary",),
        user_message: str = "",
    ) -> None:
        turn_log.debug(
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
                user_message=user_message,
                correlation_id=trigger.correlation_id,
                tags=turn_tags,
            )
        )

    async def _reset_agent_state(
        self, node_id: str, depth_key: str | None, turn_log: logging.LoggerAdapter
    ) -> None:
        try:
            current_node = await self._node_store.get_node(node_id)
            if current_node is not None and current_node.status == NodeStatus.RUNNING:
                await self._node_store.transition_status(node_id, NodeStatus.IDLE)
        # Error boundary: status reset is best-effort cleanup during finally path.
        except Exception:  # noqa: BLE001 - best effort cleanup
            turn_log.exception("Failed to reset node status")
        self._trigger_policy.release_depth(depth_key)

    @staticmethod
    async def _resolve_maybe_awaitable(value: Any) -> Any:
        if asyncio.iscoroutine(value):
            return await value
        return value

    @staticmethod
    async def _build_companion_context(workspace: AgentWorkspace) -> str:
        """Build a compact companion-memory context block from workspace KV."""
        parts: list[str] = []

        reflections = await workspace.kv_get("companion/reflections")
        if isinstance(reflections, list) and reflections:
            reflection_lines: list[str] = []
            for entry in reflections[-5:]:
                if not isinstance(entry, dict):
                    continue
                insight = entry.get("insight", "")
                if isinstance(insight, str) and insight.strip():
                    reflection_lines.append(f"- {insight.strip()}")
            if reflection_lines:
                parts.append("## Prior Reflections")
                parts.extend(reflection_lines)

        chat_index = await workspace.kv_get("companion/chat_index")
        if isinstance(chat_index, list) and chat_index:
            chat_lines: list[str] = []
            for entry in chat_index[-5:]:
                if not isinstance(entry, dict):
                    continue
                summary = entry.get("summary", "")
                if not isinstance(summary, str) or not summary.strip():
                    continue
                raw_tags = entry.get("tags", [])
                tags_source = raw_tags if isinstance(raw_tags, (list, tuple)) else []
                tags = [str(tag).strip() for tag in tags_source if str(tag).strip()]
                tag_suffix = f" [{', '.join(tags)}]" if tags else ""
                chat_lines.append(f"- {summary.strip()}{tag_suffix}")
            if chat_lines:
                parts.append("## Recent Activity")
                parts.extend(chat_lines)

        links = await workspace.kv_get("companion/links")
        if isinstance(links, list) and links:
            link_lines: list[str] = []
            for entry in links[-10:]:
                if not isinstance(entry, dict):
                    continue
                target = entry.get("target", "")
                if not isinstance(target, str) or not target.strip():
                    continue
                relationship = entry.get("relationship", "related")
                relation_text = (
                    relationship.strip()
                    if isinstance(relationship, str) and relationship.strip()
                    else "related"
                )
                link_lines.append(f"- {relation_text}: {target.strip()}")
            if link_lines:
                parts.append("## Known Relationships")
                parts.extend(link_lines)

        if not parts:
            return ""
        return "\n## Companion Memory\n" + "\n".join(parts)

    @staticmethod
    async def _read_bundle_config(workspace: AgentWorkspace) -> BundleConfig:
        try:
            text = await workspace.read("_bundle/bundle.yaml")
        except (FileNotFoundError, FsdFileNotFoundError):
            return BundleConfig()
        try:
            loaded = yaml.safe_load(text) or {}
        except yaml.YAMLError:
            logger.warning("Ignoring malformed _bundle/bundle.yaml")
            return BundleConfig()
        if not isinstance(loaded, dict):
            return BundleConfig()

        expanded = expand_env_vars(loaded)
        if not isinstance(expanded, dict):
            return BundleConfig()

        # Preserve previous behavior: disabled self-reflect should be treated as absent.
        self_reflect = expanded.get("self_reflect")
        if isinstance(self_reflect, dict) and not self_reflect.get("enabled"):
            expanded = dict(expanded)
            expanded.pop("self_reflect", None)

        try:
            return BundleConfig.model_validate(expanded)
        except ValidationError:
            logger.warning("Invalid bundle config, using defaults")
            return BundleConfig()


__all__ = ["AgentTurnExecutor", "_turn_logger"]
