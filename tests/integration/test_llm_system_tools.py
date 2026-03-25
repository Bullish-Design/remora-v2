from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

import aiosqlite
import pytest
import yaml
from tests.factories import write_file

from remora.code.languages import LanguageRegistry
from remora.code.reconciler import FileReconciler
from remora.code.subscriptions import SubscriptionManager
from remora.core.agents.actor import Actor, Outbox, Trigger
from remora.core.events import (
    AgentMessageEvent,
    EventBus,
    EventStore,
    SubscriptionRegistry,
    TriggerDispatcher,
)
from remora.core.model.config import (
    BehaviorConfig,
    Config,
    InfraConfig,
    ProjectConfig,
)
from remora.core.storage.db import open_database
from remora.core.storage.graph import NodeStore
from remora.core.storage.transaction import TransactionContext
from remora.core.storage.workspace import CairnWorkspaceService

DEFAULT_TEST_MODEL_NAME = "Qwen/Qwen3-4B-Instruct-2507-FP8"
DEFAULTS_BUNDLES = Path("src/remora/defaults/bundles")
_REAL_LLM_ENV_MISSING = not os.getenv("REMORA_TEST_MODEL_URL")
_REAL_LLM_SKIP_REASON = "REMORA_TEST_MODEL_URL not set - skipping real LLM integration test"
pytestmark = pytest.mark.real_llm

_LLM_USER_TEMPLATE = (
    "# Node: {node_full_name}\n"
    "Type: {node_type} | File: {file_path}\n\n"
    "## Source Code\n"
    "```\n"
    "{source}\n"
    "```\n\n"
    "## Trigger\n"
    "Event: {event_type}\n"
    "Content: {event_content}\n"
)


def _write_system_project(tmp_path: Path) -> None:
    write_file(
        tmp_path / "src" / "app.py",
        "def alpha() -> int:\n    return 1\n\n\ndef beta() -> int:\n    return 2\n",
    )
    write_file(tmp_path / "src" / "worker.py", "def gamma() -> int:\n    return 3\n")


def _write_system_bundles(
    root: Path,
    model_name: str,
    system_prompt: str,
    chat_prompt: str,
) -> None:
    shutil.copytree(DEFAULTS_BUNDLES / "system", root / "system")
    bundle_path = root / "system" / "bundle.yaml"
    data = yaml.safe_load(bundle_path.read_text(encoding="utf-8"))
    data["model"] = model_name
    data["system_prompt"] = system_prompt
    data["max_turns"] = 6
    prompts = data.get("prompts") or {}
    prompts["chat"] = chat_prompt
    data["prompts"] = prompts
    bundle_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


async def _setup_system_runtime(
    tmp_path: Path,
    *,
    model_url: str,
    model_name: str,
    model_api_key: str,
    timeout_s: float,
    system_prompt: str,
    chat_prompt: str,
) -> tuple[Actor, EventStore, CairnWorkspaceService, aiosqlite.Connection, str]:
    _write_system_project(tmp_path)
    bundles_root = tmp_path / "bundles"
    _write_system_bundles(
        bundles_root,
        model_name,
        system_prompt,
        chat_prompt,
    )

    db = await open_database(tmp_path / "llm-system-tools.db")
    event_bus = EventBus()
    dispatcher = TriggerDispatcher()
    tx = TransactionContext(db, event_bus, dispatcher)
    subscriptions = SubscriptionRegistry(db, tx=tx)
    dispatcher.subscriptions = subscriptions
    node_store = NodeStore(db, tx=tx)
    await node_store.create_tables()
    event_store = EventStore(db=db, event_bus=event_bus, dispatcher=dispatcher, tx=tx)
    await event_store.create_tables()

    config = Config(
        project=ProjectConfig(
            discovery_paths=("src",),
            discovery_languages=("python",),
        ),
        behavior=BehaviorConfig(
            language_map={".py": "python"},
            bundle_search_paths=(str(bundles_root),),
            bundle_overlays={
                "function": "system",
                "class": "system",
                "method": "system",
            },
            prompt_templates={"user": _LLM_USER_TEMPLATE},
            model_default=model_name,
            max_turns=8,
        ),
        infra=InfraConfig(
            workspace_root=".remora-llm-int",
            model_base_url=model_url,
            model_api_key=model_api_key,
            timeout_s=timeout_s,
        ),
    )
    workspace_service = CairnWorkspaceService(config, tmp_path)
    await workspace_service.initialize()

    language_registry = LanguageRegistry.from_defaults()
    subscription_manager = SubscriptionManager(event_store, workspace_service)
    reconciler = FileReconciler(
        config,
        node_store,
        event_store,
        workspace_service,
        project_root=tmp_path,
        language_registry=language_registry,
        subscription_manager=subscription_manager,
        tx=tx,
    )
    nodes = await reconciler.full_scan()
    node = next((candidate for candidate in nodes if candidate.name == "alpha"), None)
    assert node is not None

    actor = Actor(
        node_id=node.node_id,
        event_store=event_store,
        node_store=node_store,
        workspace_service=workspace_service,
        config=config,
        semaphore=asyncio.Semaphore(1),
    )
    return actor, event_store, workspace_service, db, node.node_id


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_system_broadcast(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))

    system_prompt = (
        "For each chat turn, call broadcast exactly once with pattern='*' and content='ping-all'. "
        "Then respond with one sentence."
    )
    chat_prompt = "Use broadcast with pattern * and content ping-all."

    actor = event_store = workspace_service = db = node_id = None
    try:
        actor, event_store, workspace_service, db, node_id = await _setup_system_runtime(
            tmp_path,
            model_url=model_url,
            model_name=model_name,
            model_api_key=model_api_key,
            timeout_s=timeout_s,
            system_prompt=system_prompt,
            chat_prompt=chat_prompt,
        )

        correlation_id = "corr-system-broadcast"
        outbox = Outbox(actor_id=node_id, event_store=event_store, correlation_id=correlation_id)
        trigger = Trigger(
            node_id=node_id,
            correlation_id=correlation_id,
            event=AgentMessageEvent(
                from_agent="user",
                to_agent=node_id,
                content="Broadcast ping-all to everyone.",
                correlation_id=correlation_id,
            ),
        )
        await actor._execute_turn(trigger, outbox)

        events = await event_store.get_events(limit=140)
        by_corr = [entry for entry in events if entry.get("correlation_id") == correlation_id]
        assert any(entry["event_type"] == "agent_complete" for entry in by_corr)
        assert not any(entry["event_type"] == "agent_error" for entry in by_corr)
        assert any(
            entry["event_type"] == "remora_tool_result"
            and entry["payload"].get("tool_name") == "broadcast"
            and "Broadcast sent to" in str(entry["payload"].get("output_preview", ""))
            for entry in by_corr
        )
        sent_messages = [entry for entry in by_corr if entry["event_type"] == "agent_message"]
        assert len(sent_messages) >= 2
    finally:
        if workspace_service is not None:
            await workspace_service.close()
        if db is not None:
            await db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_system_query_agents(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))

    system_prompt = (
        "For each chat turn, call query_agents exactly once with no arguments. "
        "Then respond with one sentence."
    )
    chat_prompt = "Use query_agents with no arguments."

    actor = event_store = workspace_service = db = node_id = None
    try:
        actor, event_store, workspace_service, db, node_id = await _setup_system_runtime(
            tmp_path,
            model_url=model_url,
            model_name=model_name,
            model_api_key=model_api_key,
            timeout_s=timeout_s,
            system_prompt=system_prompt,
            chat_prompt=chat_prompt,
        )

        correlation_id = "corr-system-query-agents"
        outbox = Outbox(actor_id=node_id, event_store=event_store, correlation_id=correlation_id)
        trigger = Trigger(
            node_id=node_id,
            correlation_id=correlation_id,
            event=AgentMessageEvent(
                from_agent="user",
                to_agent=node_id,
                content="Query all agents.",
                correlation_id=correlation_id,
            ),
        )
        await actor._execute_turn(trigger, outbox)

        events = await event_store.get_events(limit=120)
        by_corr = [entry for entry in events if entry.get("correlation_id") == correlation_id]
        assert any(entry["event_type"] == "agent_complete" for entry in by_corr)
        assert not any(entry["event_type"] == "agent_error" for entry in by_corr)
        assert any(
            entry["event_type"] == "remora_tool_result"
            and entry["payload"].get("tool_name") == "query_agents"
            and "node_id" in str(entry["payload"].get("output_preview", ""))
            for entry in by_corr
        )
    finally:
        if workspace_service is not None:
            await workspace_service.close()
        if db is not None:
            await db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_system_reflect(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))

    system_prompt = (
        "For each chat turn, call reflect exactly once with history_limit=5, "
        "then respond with one sentence."
    )
    chat_prompt = "Use reflect now."

    actor = event_store = workspace_service = db = node_id = None
    try:
        actor, event_store, workspace_service, db, node_id = await _setup_system_runtime(
            tmp_path,
            model_url=model_url,
            model_name=model_name,
            model_api_key=model_api_key,
            timeout_s=timeout_s,
            system_prompt=system_prompt,
            chat_prompt=chat_prompt,
        )

        correlation_id = "corr-system-reflect"
        outbox = Outbox(actor_id=node_id, event_store=event_store, correlation_id=correlation_id)
        trigger = Trigger(
            node_id=node_id,
            correlation_id=correlation_id,
            event=AgentMessageEvent(
                from_agent="user",
                to_agent=node_id,
                content="Record a reflection note.",
                correlation_id=correlation_id,
            ),
        )
        await actor._execute_turn(trigger, outbox)

        events = await event_store.get_events(limit=120)
        by_corr = [entry for entry in events if entry.get("correlation_id") == correlation_id]
        assert any(entry["event_type"] == "agent_complete" for entry in by_corr)
        assert not any(entry["event_type"] == "agent_error" for entry in by_corr)
        assert any(
            entry["event_type"] == "remora_tool_result"
            and entry["payload"].get("tool_name") == "reflect"
            and "Reflection recorded" in str(entry["payload"].get("output_preview", ""))
            for entry in by_corr
        )

        workspace = await workspace_service.get_agent_workspace(node_id)
        reflection = await workspace.read("notes/reflection.md")
        assert "Reviewed recent activity." in reflection
    finally:
        if workspace_service is not None:
            await workspace_service.close()
        if db is not None:
            await db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_system_subscribe_unsubscribe(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))

    system_prompt = (
        "Follow the user request exactly and call either subscribe or unsubscribe as requested. "
        "Do not call unrelated tools."
    )
    chat_prompt = "Follow user subscription commands exactly."

    actor = event_store = workspace_service = db = node_id = None
    try:
        actor, event_store, workspace_service, db, node_id = await _setup_system_runtime(
            tmp_path,
            model_url=model_url,
            model_name=model_name,
            model_api_key=model_api_key,
            timeout_s=timeout_s,
            system_prompt=system_prompt,
            chat_prompt=chat_prompt,
        )

        first_corr = "corr-system-subscribe"
        first_outbox = Outbox(actor_id=node_id, event_store=event_store, correlation_id=first_corr)
        first_trigger = Trigger(
            node_id=node_id,
            correlation_id=first_corr,
            event=AgentMessageEvent(
                from_agent="user",
                to_agent=node_id,
                content="Call subscribe with event_types='node_changed'.",
                correlation_id=first_corr,
            ),
        )
        await actor._execute_turn(first_trigger, first_outbox)

        events = await event_store.get_events(limit=160)
        first_events = [entry for entry in events if entry.get("correlation_id") == first_corr]
        assert any(entry["event_type"] == "agent_complete" for entry in first_events)
        assert not any(entry["event_type"] == "agent_error" for entry in first_events)

        subscribe_result = next(
            (
                entry
                for entry in first_events
                if entry["event_type"] == "remora_tool_result"
                and entry["payload"].get("tool_name") == "subscribe"
            ),
            None,
        )
        assert subscribe_result is not None
        assert not subscribe_result["payload"].get("is_error")
        cursor = await db.execute(
            "SELECT id FROM subscriptions WHERE agent_id = ? ORDER BY id DESC LIMIT 1",
            (node_id,),
        )
        row = await cursor.fetchone()
        assert row is not None
        subscription_id = int(row[0])

        second_corr = "corr-system-unsubscribe"
        second_outbox = Outbox(
            actor_id=node_id,
            event_store=event_store,
            correlation_id=second_corr,
        )
        second_trigger = Trigger(
            node_id=node_id,
            correlation_id=second_corr,
            event=AgentMessageEvent(
                from_agent="user",
                to_agent=node_id,
                content=f"Call unsubscribe with subscription_id={subscription_id}.",
                correlation_id=second_corr,
            ),
        )
        await actor._execute_turn(second_trigger, second_outbox)

        events = await event_store.get_events(limit=200)
        second_events = [entry for entry in events if entry.get("correlation_id") == second_corr]
        assert any(entry["event_type"] == "agent_complete" for entry in second_events)
        assert not any(entry["event_type"] == "agent_error" for entry in second_events)
        assert any(
            entry["event_type"] == "remora_tool_result"
            and entry["payload"].get("tool_name") == "unsubscribe"
            and "Unsubscribed" in str(entry["payload"].get("output_preview", ""))
            for entry in second_events
        )
    finally:
        if workspace_service is not None:
            await workspace_service.close()
        if db is not None:
            await db.close()


# TODO: add end-to-end ask_human coverage once a programmable HumanInputBroker test
# harness is wired for real-LLM integration tests.
# TODO: add semantic_search/categorize real-LLM coverage behind an embeddy
# availability gate once search service test infra is present.
