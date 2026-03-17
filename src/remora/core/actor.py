"""Actor orchestration and public re-exports for actor primitives."""

from __future__ import annotations

import asyncio
import time
import uuid

from structured_agents import Message

from remora.core.config import Config
from remora.core.events.store import EventStore
from remora.core.events.types import Event
from remora.core.grail import discover_tools
from remora.core.graph import NodeStore
from remora.core.kernel import create_kernel, extract_response_text
from remora.core.metrics import Metrics
from remora.core.outbox import Outbox, OutboxObserver
from remora.core.prompt import PromptBuilder
from remora.core.search import SearchServiceProtocol
from remora.core.trigger import Trigger, TriggerPolicy
from remora.core.turn_executor import AgentTurnExecutor
from remora.core.workspace import CairnWorkspaceService


class Actor:
    """Per-agent actor with inbox, outbox, and sequential processing loop."""

    def __init__(
        self,
        node_id: str,
        event_store: EventStore,
        node_store: NodeStore,
        workspace_service: CairnWorkspaceService,
        config: Config,
        semaphore: asyncio.Semaphore,
        metrics: Metrics | None = None,
        search_service: SearchServiceProtocol | None = None,
    ) -> None:
        self.node_id = node_id
        self.inbox: asyncio.Queue[Event | None] = asyncio.Queue()
        self._event_store = event_store
        self._task: asyncio.Task | None = None
        self._last_active: float = time.time()
        self._history: list[Message] = []

        self._trigger_policy = TriggerPolicy(config)
        self._prompt_builder = PromptBuilder(config)
        self._turn_executor = AgentTurnExecutor(
            node_store=node_store,
            event_store=event_store,
            workspace_service=workspace_service,
            config=config,
            semaphore=semaphore,
            metrics=metrics,
            history=self._history,
            prompt_builder=self._prompt_builder,
            trigger_policy=self._trigger_policy,
            search_service=search_service,
            # Keep these injected from actor module so existing test monkeypatch
            # paths on remora.core.actor continue to work during decomposition.
            create_kernel_fn=lambda **kwargs: create_kernel(**kwargs),
            discover_tools_fn=lambda workspace, capabilities: discover_tools(
                workspace,
                capabilities,
            ),
            extract_response_text_fn=lambda result: extract_response_text(result),
        )

    @property
    def last_active(self) -> float:
        return self._last_active

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def history(self) -> list[Message]:
        """Read-only access to conversation history for observability."""
        return list(self._history)

    def start(self) -> None:
        """Launch the actor's processing loop as a managed asyncio.Task."""
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(), name=f"actor-{self.node_id}")

    async def stop(self) -> None:
        """Stop the processing loop and wait for it to finish."""
        if self._task is not None and not self._task.done():
            self.inbox.put_nowait(None)
            await self._task
        self._task = None

    async def _run(self) -> None:
        """Main processing loop: consume inbox events one at a time."""
        try:
            while True:
                event = await self.inbox.get()
                if event is None:
                    break
                self._last_active = time.time()
                correlation_id = event.correlation_id or str(uuid.uuid4())
                if not self._trigger_policy.should_trigger(correlation_id):
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

    async def _execute_turn(self, trigger: Trigger, outbox: Outbox) -> None:
        await self._turn_executor.execute_turn(trigger, outbox)


__all__ = [
    "Outbox",
    "OutboxObserver",
    "Trigger",
    "TriggerPolicy",
    "PromptBuilder",
    "AgentTurnExecutor",
    "Actor",
]
