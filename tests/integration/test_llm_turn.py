from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from tests.factories import write_file

from remora.code.reconciler import FileReconciler
from remora.core.actor import AgentActor, Outbox, Trigger
from remora.core.config import Config
from remora.core.db import AsyncDB
from remora.core.events import AgentMessageEvent, EventStore
from remora.core.graph import AgentStore, NodeStore
from remora.core.workspace import CairnWorkspaceService

DEFAULT_TEST_MODEL_NAME = "Qwen/Qwen3-4B-Instruct-2507-FP8"


def _write_llm_test_bundles(root: Path, model_name: str) -> None:
    system = root / "system"
    code = root / "code-agent"
    (system / "tools").mkdir(parents=True, exist_ok=True)
    (code / "tools").mkdir(parents=True, exist_ok=True)

    write_file(
        system / "bundle.yaml",
        (
            "name: system\n"
            "system_prompt: >-\n"
            "  You are a tool-using test agent. You must call send_message exactly once,\n"
            "  then answer with one short sentence.\n"
            f"model: {model_name}\n"
            "max_turns: 6\n"
        ),
    )
    write_file(
        code / "bundle.yaml",
        f"name: code-agent\nmodel: {model_name}\nmax_turns: 6\n",
    )
    write_file(
        system / "tools" / "send_message.pym",
        (
            "from grail import Input, external\n\n"
            'to_node_id: str = Input("to_node_id")\n'
            'content: str = Input("content")\n\n'
            "@external\n"
            "async def send_message(to_node_id: str, content: str) -> bool: ...\n\n"
            "result = await send_message(to_node_id, content)\n"
            "if result:\n"
            '    message = f"Message sent to {to_node_id}"\n'
            "else:\n"
            '    message = f"Failed to send message to {to_node_id}"\n'
            "message\n"
        ),
    )


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.getenv("REMORA_TEST_MODEL_URL"),
    reason="REMORA_TEST_MODEL_URL not set - skipping real LLM integration test",
)
async def test_real_llm_turn_invokes_tool_and_completes(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))

    source_path = tmp_path / "src" / "app.py"
    write_file(source_path, "def alpha():\n    return 1\n")
    bundles_root = tmp_path / "bundles"
    _write_llm_test_bundles(bundles_root, model_name)

    db = AsyncDB.from_path(tmp_path / "llm-turn.db")
    node_store = NodeStore(db)
    agent_store = AgentStore(db)
    await node_store.create_tables()
    await agent_store.create_tables()
    event_store = EventStore(db=db)
    await event_store.create_tables()
    config = Config(
        discovery_paths=("src",),
        discovery_languages=("python",),
        bundle_root=str(bundles_root),
        swarm_root=".remora-llm-int",
        model_base_url=model_url,
        model_default=model_name,
        model_api_key=model_api_key,
        timeout_s=timeout_s,
        max_turns=6,
    )
    workspace_service = CairnWorkspaceService(config, tmp_path)
    await workspace_service.initialize()

    try:
        reconciler = FileReconciler(
            config,
            node_store,
            agent_store,
            event_store,
            workspace_service,
            project_root=tmp_path,
        )
        nodes = await reconciler.full_scan()
        node = next(candidate for candidate in nodes if candidate.node_type != "directory")

        actor = AgentActor(
            node_id=node.node_id,
            event_store=event_store,
            node_store=node_store,
            agent_store=agent_store,
            workspace_service=workspace_service,
            config=config,
            semaphore=asyncio.Semaphore(1),
        )
        correlation_id = "corr-llm-turn"
        event = AgentMessageEvent(
            from_agent="user",
            to_agent=node.node_id,
            content=(
                f"Use the send_message tool exactly once with to_node_id='{node.node_id}' and "
                "content='integration-ok'. Then give a one-line confirmation."
            ),
            correlation_id=correlation_id,
        )
        outbox = Outbox(actor_id=node.node_id, event_store=event_store, correlation_id=correlation_id)
        trigger = Trigger(node_id=node.node_id, correlation_id=correlation_id, event=event)
        await actor._execute_turn(trigger, outbox)

        events = await event_store.get_events(limit=30)
        event_types = [entry["event_type"] for entry in events]
        assert "AgentStartEvent" in event_types
        assert "AgentCompleteEvent" in event_types
        assert "AgentErrorEvent" not in event_types

        message_events = [entry for entry in events if entry["event_type"] == "AgentMessageEvent"]
        assert message_events, "expected at least one send_message tool emission"
        assert any(
            item["payload"].get("to_agent") == node.node_id
            and item["payload"].get("content") == "integration-ok"
            for item in message_events
        )
    finally:
        await workspace_service.close()
        db.close()
