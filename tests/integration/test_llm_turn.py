from __future__ import annotations

import asyncio
import os
from pathlib import Path

import aiosqlite
import pytest
from tests.factories import write_file

from remora.code.reconciler import FileReconciler
from remora.core.actor import Actor, Outbox, Trigger
from remora.core.config import Config
from remora.core.db import open_database
from remora.core.events import AgentMessageEvent, ContentChangedEvent, EventStore, NodeChangedEvent
from remora.core.graph import NodeStore
from remora.core.workspace import CairnWorkspaceService

DEFAULT_TEST_MODEL_NAME = "Qwen/Qwen3-4B-Instruct-2507-FP8"
_REAL_LLM_ENV_MISSING = not os.getenv("REMORA_TEST_MODEL_URL")
_REAL_LLM_SKIP_REASON = "REMORA_TEST_MODEL_URL not set - skipping real LLM integration test"
pytestmark = pytest.mark.real_llm


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


def _write_kv_roundtrip_bundles(root: Path, model_name: str) -> None:
    system = root / "system"
    code = root / "code-agent"
    (system / "tools").mkdir(parents=True, exist_ok=True)
    (code / "tools").mkdir(parents=True, exist_ok=True)

    write_file(
        system / "bundle.yaml",
        (
            "name: system\n"
            "system_prompt: >-\n"
            "  You are a deterministic integration-test agent.\n"
            "  For user requests, call the requested tools in order.\n"
            "  Use send_message exactly once after kv_set and kv_get.\n"
            f"model: {model_name}\n"
            "max_turns: 8\n"
        ),
    )
    write_file(code / "bundle.yaml", f"name: code-agent\nmax_turns: 8\n")
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
    write_file(
        system / "tools" / "kv_set.pym",
        (
            "from grail import Input, external\n\n"
            'key: str = Input("key")\n'
            'value: str = Input("value")\n\n'
            "@external\n"
            "async def kv_set(key: str, value: str) -> bool: ...\n\n"
            "ok = await kv_set(key, value)\n"
            "message = f\"Stored value for {key}\" if ok else f\"Failed to store value for {key}\"\n"
            "message\n"
        ),
    )
    write_file(
        system / "tools" / "kv_get.pym",
        (
            "from grail import Input, external\n\n"
            'key: str = Input("key")\n\n'
            "@external\n"
            "async def kv_get(key: str) -> str | None: ...\n\n"
            "value = await kv_get(key)\n"
            "result = \"\" if value is None else str(value)\n"
            "result\n"
        ),
    )


def _write_reactive_mode_bundles(root: Path, model_name: str) -> None:
    system = root / "system"
    code = root / "code-agent"
    (system / "tools").mkdir(parents=True, exist_ok=True)
    (code / "tools").mkdir(parents=True, exist_ok=True)

    write_file(
        system / "bundle.yaml",
        (
            "name: system\n"
            "system_prompt: >-\n"
            "  You are a deterministic integration-test agent.\n"
            "  Mandatory protocol for every turn:\n"
            "  1) Read MODE_TOKEN from the active mode prompt.\n"
            "  2) Call send_message exactly once with to_node_id='src/app.py::alpha'\n"
            "     and content equal to MODE_TOKEN.\n"
            "  3) Then reply with one short sentence.\n"
            f"model: {model_name}\n"
            "max_turns: 8\n"
            "prompts:\n"
            "  chat: |\n"
            "    MODE_TOKEN=chat-ok\n"
            "  reactive: |\n"
            "    MODE_TOKEN=reactive-ok\n"
        ),
    )
    write_file(code / "bundle.yaml", "name: code-agent\nmax_turns: 8\n")
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


def _write_virtual_agent_bundles(root: Path, model_name: str) -> None:
    system = root / "system"
    test_agent = root / "test-agent"
    code = root / "code-agent"
    (system / "tools").mkdir(parents=True, exist_ok=True)
    (test_agent / "tools").mkdir(parents=True, exist_ok=True)
    (code / "tools").mkdir(parents=True, exist_ok=True)

    write_file(
        system / "bundle.yaml",
        (
            "name: system\n"
            "system_prompt: Base system\n"
            f"model: {model_name}\n"
            "max_turns: 8\n"
        ),
    )
    write_file(code / "bundle.yaml", "name: code-agent\nmax_turns: 8\n")
    write_file(
        test_agent / "bundle.yaml",
        (
            "name: test-agent\n"
            "system_prompt: >-\n"
            "  You are a virtual test agent.\n"
            "  For every turn, call send_message exactly once with\n"
            "  to_node_id='test-agent' and content='virtual-reactive-ok',\n"
            "  then answer with one short sentence.\n"
            f"model: {model_name}\n"
            "max_turns: 8\n"
        ),
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


async def _setup_llm_runtime(
    tmp_path: Path,
    *,
    model_url: str,
    model_name: str,
    model_api_key: str,
    timeout_s: float,
    bundle_writer,
) -> tuple[Actor, object, EventStore, CairnWorkspaceService, aiosqlite.Connection, Path]:
    source_path = tmp_path / "src" / "app.py"
    write_file(source_path, "def alpha():\n    return 1\n")
    bundles_root = tmp_path / "bundles"
    bundle_writer(bundles_root, model_name)

    db = await open_database(tmp_path / "llm-turn.db")
    node_store = NodeStore(db)
    await node_store.create_tables()
    event_store = EventStore(db=db)
    await event_store.create_tables()
    config = Config(
        discovery_paths=("src",),
        discovery_languages=("python",),
        bundle_root=str(bundles_root),
        workspace_root=".remora-llm-int",
        model_base_url=model_url,
        model_default=model_name,
        model_api_key=model_api_key,
        timeout_s=timeout_s,
        max_turns=8,
    )
    workspace_service = CairnWorkspaceService(config, tmp_path)
    await workspace_service.initialize()

    reconciler = FileReconciler(
        config,
        node_store,
        event_store,
        workspace_service,
        project_root=tmp_path,
    )
    nodes = await reconciler.full_scan()
    node = next(candidate for candidate in nodes if candidate.node_type != "directory")

    actor = Actor(
        node_id=node.node_id,
        event_store=event_store,
        node_store=node_store,
        workspace_service=workspace_service,
        config=config,
        semaphore=asyncio.Semaphore(1),
    )
    return actor, node, event_store, workspace_service, db, source_path


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_turn_invokes_tool_and_completes(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))

    source_path = tmp_path / "src" / "app.py"
    write_file(source_path, "def alpha():\n    return 1\n")
    bundles_root = tmp_path / "bundles"
    _write_llm_test_bundles(bundles_root, model_name)

    db = await open_database(tmp_path / "llm-turn.db")
    node_store = NodeStore(db)
    await node_store.create_tables()
    event_store = EventStore(db=db)
    await event_store.create_tables()
    config = Config(
        discovery_paths=("src",),
        discovery_languages=("python",),
        bundle_root=str(bundles_root),
        workspace_root=".remora-llm-int",
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
            event_store,
            workspace_service,
            project_root=tmp_path,
        )
        nodes = await reconciler.full_scan()
        node = next(candidate for candidate in nodes if candidate.node_type != "directory")

        actor = Actor(
            node_id=node.node_id,
            event_store=event_store,
            node_store=node_store,
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
        assert "agent_start" in event_types
        assert "agent_complete" in event_types
        assert "agent_error" not in event_types

        message_events = [entry for entry in events if entry["event_type"] == "agent_message"]
        assert message_events, "expected at least one send_message tool emission"
        assert any(
            item["payload"].get("to_agent") == node.node_id
            and item["payload"].get("content") == "integration-ok"
            for item in message_events
        )
    finally:
        await workspace_service.close()
        await db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_turn_kv_roundtrip_and_message(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))

    actor = node = event_store = workspace_service = db = None
    try:
        actor, node, event_store, workspace_service, db, _source_path = await _setup_llm_runtime(
            tmp_path,
            model_url=model_url,
            model_name=model_name,
            model_api_key=model_api_key,
            timeout_s=timeout_s,
            bundle_writer=_write_kv_roundtrip_bundles,
        )
        correlation_id = "corr-llm-kv"
        outbox = Outbox(actor_id=node.node_id, event_store=event_store, correlation_id=correlation_id)
        trigger = Trigger(
            node_id=node.node_id,
            correlation_id=correlation_id,
            event=AgentMessageEvent(
                from_agent="user",
                to_agent=node.node_id,
                content=(
                    "Call kv_set with key='state/integration' and value='v-integration', "
                    "then call kv_get for key='state/integration', then call send_message with "
                    f"to_node_id='{node.node_id}' and content='kv-ok:v-integration'."
                ),
                correlation_id=correlation_id,
            ),
        )
        await actor._execute_turn(trigger, outbox)

        workspace = await workspace_service.get_agent_workspace(node.node_id)
        assert await workspace.kv_get("state/integration") == "v-integration"

        events = await event_store.get_events(limit=40)
        by_corr = [entry for entry in events if entry.get("correlation_id") == correlation_id]
        assert any(entry["event_type"] == "agent_complete" for entry in by_corr)
        assert not any(entry["event_type"] == "agent_error" for entry in by_corr)
        assert any(
            entry["event_type"] == "agent_message"
            and entry["payload"].get("to_agent") == node.node_id
            and "v-integration" in str(entry["payload"].get("content", ""))
            for entry in by_corr
        )
    finally:
        if workspace_service is not None:
            await workspace_service.close()
        if db is not None:
            await db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_turn_reload_uses_runtime_bundle_mutation(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))

    actor = node = event_store = workspace_service = db = None
    try:
        actor, node, event_store, workspace_service, db, _source_path = await _setup_llm_runtime(
            tmp_path,
            model_url=model_url,
            model_name=model_name,
            model_api_key=model_api_key,
            timeout_s=timeout_s,
            bundle_writer=_write_llm_test_bundles,
        )
        corr_a = "corr-reload-a"
        outbox_a = Outbox(actor_id=node.node_id, event_store=event_store, correlation_id=corr_a)
        trigger_a = Trigger(
            node_id=node.node_id,
            correlation_id=corr_a,
            event=AgentMessageEvent(
                from_agent="user",
                to_agent=node.node_id,
                content="Briefly acknowledge this turn.",
                correlation_id=corr_a,
            ),
        )
        await actor._execute_turn(trigger_a, outbox_a)

        workspace = await workspace_service.get_agent_workspace(node.node_id)
        await workspace.write(
            "_bundle/bundle.yaml",
            (
                "name: system\n"
                "system_prompt: Runtime mutated config\n"
                "model: does/not-exist-in-vllm\n"
                "max_turns: 4\n"
            ),
        )

        corr_b = "corr-reload-b"
        outbox_b = Outbox(actor_id=node.node_id, event_store=event_store, correlation_id=corr_b)
        trigger_b = Trigger(
            node_id=node.node_id,
            correlation_id=corr_b,
            event=AgentMessageEvent(
                from_agent="user",
                to_agent=node.node_id,
                content="This turn should use the mutated model config.",
                correlation_id=corr_b,
            ),
        )
        await actor._execute_turn(trigger_b, outbox_b)

        events = await event_store.get_events(limit=60)
        first_turn = [entry for entry in events if entry.get("correlation_id") == corr_a]
        second_turn = [entry for entry in events if entry.get("correlation_id") == corr_b]
        assert any(entry["event_type"] == "agent_complete" for entry in first_turn)
        assert not any(entry["event_type"] == "agent_error" for entry in first_turn)
        assert any(entry["event_type"] == "agent_error" for entry in second_turn)
        assert not any(entry["event_type"] == "agent_complete" for entry in second_turn)
    finally:
        if workspace_service is not None:
            await workspace_service.close()
        if db is not None:
            await db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_virtual_agent_reacts_to_node_changed(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))

    source_path = tmp_path / "src" / "app.py"
    write_file(source_path, "def alpha():\n    return 1\n")
    bundles_root = tmp_path / "bundles"
    _write_virtual_agent_bundles(bundles_root, model_name)

    db = await open_database(tmp_path / "llm-turn-virtual.db")
    node_store = NodeStore(db)
    await node_store.create_tables()
    event_store = EventStore(db=db)
    await event_store.create_tables()
    config = Config(
        discovery_paths=("src",),
        discovery_languages=("python",),
        bundle_root=str(bundles_root),
        workspace_root=".remora-llm-int",
        model_base_url=model_url,
        model_default=model_name,
        model_api_key=model_api_key,
        timeout_s=timeout_s,
        max_turns=8,
        virtual_agents=(
            {
                "id": "test-agent",
                "role": "test-agent",
                "subscriptions": (
                    {
                        "event_types": ["node_changed"],
                        "path_glob": "src/**",
                    },
                ),
            },
        ),
    )
    workspace_service = CairnWorkspaceService(config, tmp_path)
    await workspace_service.initialize()

    try:
        reconciler = FileReconciler(
            config,
            node_store,
            event_store,
            workspace_service,
            project_root=tmp_path,
        )
        await reconciler.full_scan()

        virtual = await node_store.get_node("test-agent")
        assert virtual is not None
        actor = Actor(
            node_id=virtual.node_id,
            event_store=event_store,
            node_store=node_store,
            workspace_service=workspace_service,
            config=config,
            semaphore=asyncio.Semaphore(1),
        )
        correlation_id = "corr-virtual-reactive"
        trigger_event = NodeChangedEvent(
            node_id=str(source_path) + "::alpha",
            old_hash="old",
            new_hash="new",
            file_path="src/app.py",
            correlation_id=correlation_id,
        )
        outbox = Outbox(
            actor_id=virtual.node_id,
            event_store=event_store,
            correlation_id=correlation_id,
        )
        trigger = Trigger(
            node_id=virtual.node_id,
            correlation_id=correlation_id,
            event=trigger_event,
        )
        await actor._execute_turn(trigger, outbox)

        events = await event_store.get_events(limit=60)
        by_corr = [entry for entry in events if entry.get("correlation_id") == correlation_id]
        assert any(entry["event_type"] == "agent_start" for entry in by_corr)
        assert any(entry["event_type"] == "agent_complete" for entry in by_corr)
        assert not any(entry["event_type"] == "agent_error" for entry in by_corr)
        assert any(
            entry["event_type"] == "agent_message"
            and entry["payload"].get("to_agent") == "test-agent"
            and entry["payload"].get("content") == "virtual-reactive-ok"
            for entry in by_corr
        )
    finally:
        await workspace_service.close()
        await db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_reactive_trigger_uses_reactive_mode_prompt(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))

    actor = node = event_store = workspace_service = db = None
    try:
        actor, node, event_store, workspace_service, db, source_path = await _setup_llm_runtime(
            tmp_path,
            model_url=model_url,
            model_name=model_name,
            model_api_key=model_api_key,
            timeout_s=timeout_s,
            bundle_writer=_write_reactive_mode_bundles,
        )
        correlation_id = "corr-reactive-mode"
        outbox = Outbox(actor_id=node.node_id, event_store=event_store, correlation_id=correlation_id)
        trigger = Trigger(
            node_id=node.node_id,
            correlation_id=correlation_id,
            event=ContentChangedEvent(
                path=str(source_path),
                change_type="modified",
                correlation_id=correlation_id,
            ),
        )
        await actor._execute_turn(trigger, outbox)

        events = await event_store.get_events(limit=50)
        by_corr = [entry for entry in events if entry.get("correlation_id") == correlation_id]
        assert any(entry["event_type"] == "agent_start" for entry in by_corr)
        assert any(entry["event_type"] == "agent_complete" for entry in by_corr)
        assert not any(entry["event_type"] == "agent_error" for entry in by_corr)
    finally:
        if workspace_service is not None:
            await workspace_service.close()
        if db is not None:
            await db.close()
