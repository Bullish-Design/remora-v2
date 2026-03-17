from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import pytest_asyncio
from tests.doubles import RecordingOutbox
from tests.factories import make_node

from remora.core.actor import Outbox
from remora.core.config import Config
from remora.core.db import open_database
from remora.core.events import AgentMessageEvent, EventStore
from remora.core.events.types import CustomEvent
from remora.core.externals import TurnContext
from remora.core.graph import NodeStore
from remora.core.types import NodeStatus, NodeType
from remora.core.workspace import CairnWorkspaceService


@pytest_asyncio.fixture
async def context_env(tmp_path: Path):
    db = await open_database(tmp_path / "phase5.db")
    node_store = NodeStore(db)
    await node_store.create_tables()
    event_store = EventStore(db=db)
    await event_store.create_tables()

    config = Config(workspace_root=".remora-phase5")
    workspace_service = CairnWorkspaceService(config, tmp_path)
    await workspace_service.initialize()

    yield node_store, event_store, workspace_service

    await workspace_service.close()
    await db.close()


async def _context(
    node_id: str,
    workspace,
    node_store: NodeStore,
    event_store: EventStore,
    correlation_id: str = "corr-1",
    outbox=None,
    human_input_timeout_s: float = 300.0,
    search_content_max_matches: int = 1000,
    broadcast_max_targets: int = 50,
    send_message_rate_limit: int = 10,
    send_message_rate_window_s: float = 1.0,
    search_service=None,
) -> TurnContext:
    if outbox is None:
        outbox = Outbox(actor_id=node_id, event_store=event_store, correlation_id=correlation_id)
    return TurnContext(
        node_id=node_id,
        workspace=workspace,
        correlation_id=correlation_id,
        node_store=node_store,
        event_store=event_store,
        outbox=outbox,
        human_input_timeout_s=human_input_timeout_s,
        search_content_max_matches=search_content_max_matches,
        broadcast_max_targets=broadcast_max_targets,
        send_message_rate_limit=send_message_rate_limit,
        send_message_rate_window_s=send_message_rate_window_s,
        search_service=search_service,
    )


class _MockSearchService:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.search_calls: list[tuple[str, str | None, int, str]] = []
        self.similar_calls: list[tuple[str, str | None, int]] = []

    async def search(
        self,
        query: str,
        collection: str | None = None,
        top_k: int = 10,
        mode: str = "hybrid",
    ) -> list[dict]:
        self.search_calls.append((query, collection, top_k, mode))
        return [{"chunk_id": "c1", "score": 0.9}]

    async def find_similar(
        self,
        chunk_id: str,
        collection: str | None = None,
        top_k: int = 10,
    ) -> list[dict]:
        self.similar_calls.append((chunk_id, collection, top_k))
        return [{"chunk_id": chunk_id, "score": 0.8}]


@pytest.mark.asyncio
async def test_externals_workspace_ops(context_env) -> None:
    node_store, event_store, workspace_service = context_env
    node = make_node("src/app.py::alpha")
    await node_store.upsert_node(node)
    ws = await workspace_service.get_agent_workspace(node.node_id)
    context = await _context(node.node_id, ws, node_store, event_store)
    externals = context.to_capabilities_dict()

    assert await externals["write_file"]("notes/a.txt", "hello")
    assert await externals["read_file"]("notes/a.txt") == "hello"
    assert await externals["file_exists"]("notes/a.txt") is True
    assert "a.txt" in await externals["list_dir"]("notes")
    assert "notes/a.txt" in await externals["search_files"]("a.txt")
    matches = await externals["search_content"]("hello", "notes")
    assert matches and matches[0]["file"] == "notes/a.txt"


@pytest.mark.asyncio
async def test_externals_search_content_caps_results(context_env) -> None:
    node_store, event_store, workspace_service = context_env
    node = make_node("src/app.py::alpha")
    await node_store.upsert_node(node)
    ws = await workspace_service.get_agent_workspace(node.node_id)
    lines = "\n".join(f"needle-{idx}" for idx in range(1500))
    await ws.write("notes/huge.txt", lines)
    context = await _context(
        node.node_id,
        ws,
        node_store,
        event_store,
        search_content_max_matches=1000,
    )
    externals = context.to_capabilities_dict()

    matches = await externals["search_content"]("needle-", "notes")
    assert len(matches) == 1000


@pytest.mark.asyncio
async def test_externals_kv_ops(context_env) -> None:
    node_store, event_store, workspace_service = context_env
    node = make_node("src/app.py::alpha")
    await node_store.upsert_node(node)
    ws = await workspace_service.get_agent_workspace(node.node_id)
    context = await _context(node.node_id, ws, node_store, event_store)
    externals = context.to_capabilities_dict()

    assert await externals["kv_set"]("state/name", "alpha")
    assert await externals["kv_get"]("state/name") == "alpha"
    assert await externals["kv_get"]("state/missing") is None
    assert await externals["kv_list"]("state/") == ["state/name"]
    assert await externals["kv_delete"]("state/name")
    assert await externals["kv_get"]("state/name") is None


@pytest.mark.asyncio
async def test_externals_graph_ops(context_env) -> None:
    node_store, event_store, workspace_service = context_env
    a = make_node("src/app.py::a")
    b = make_node("src/app.py::b")
    await node_store.upsert_node(a)
    await node_store.upsert_node(b)
    await node_store.add_edge(a.node_id, b.node_id, "calls")

    ws = await workspace_service.get_agent_workspace(a.node_id)
    context = await _context(a.node_id, ws, node_store, event_store)
    externals = context.to_capabilities_dict()

    got = await externals["graph_get_node"](a.node_id)
    listed = await externals["graph_query_nodes"]("function", None)
    edges = await externals["graph_get_edges"](a.node_id)
    assert got["node_id"] == a.node_id
    assert len(listed) == 2
    assert edges[0]["to_id"] == b.node_id
    assert await externals["graph_set_status"](a.node_id, "running")


@pytest.mark.asyncio
async def test_externals_graph_query_nodes_rejects_invalid_enums(context_env) -> None:
    node_store, event_store, workspace_service = context_env
    node = make_node("src/app.py::a")
    await node_store.upsert_node(node)
    ws = await workspace_service.get_agent_workspace(node.node_id)
    context = await _context(node.node_id, ws, node_store, event_store)
    externals = context.to_capabilities_dict()

    with pytest.raises(ValueError, match="Invalid node_type"):
        await externals["graph_query_nodes"]("NodeType.DIRECTORY", None)

    with pytest.raises(ValueError, match="Invalid status"):
        await externals["graph_query_nodes"](None, "NodeStatus.IDLE")


@pytest.mark.asyncio
async def test_externals_graph_set_status_rejects_invalid_status(context_env) -> None:
    node_store, event_store, workspace_service = context_env
    node = make_node("src/app.py::a")
    await node_store.upsert_node(node)
    ws = await workspace_service.get_agent_workspace(node.node_id)
    context = await _context(node.node_id, ws, node_store, event_store)
    externals = context.to_capabilities_dict()

    with pytest.raises(ValueError):
        await externals["graph_set_status"](node.node_id, "not-a-status")


@pytest.mark.asyncio
async def test_externals_graph_set_status_enforces_transition_rules(context_env) -> None:
    node_store, event_store, workspace_service = context_env
    node = make_node("src/app.py::a", status="idle")
    await node_store.upsert_node(node)
    ws = await workspace_service.get_agent_workspace(node.node_id)
    context = await _context(node.node_id, ws, node_store, event_store)
    externals = context.to_capabilities_dict()

    assert not await externals["graph_set_status"](node.node_id, "error")
    updated = await node_store.get_node(node.node_id)
    assert updated is not None
    assert updated.status == NodeStatus.IDLE


@pytest.mark.asyncio
async def test_externals_event_ops(context_env) -> None:
    node_store, event_store, workspace_service = context_env
    node = make_node("src/app.py::alpha")
    await node_store.upsert_node(node)
    ws = await workspace_service.get_agent_workspace(node.node_id)
    context = await _context(node.node_id, ws, node_store, event_store)
    externals = context.to_capabilities_dict()

    sub_id = await externals["event_subscribe"](["AgentMessageEvent"], None, None)
    assert isinstance(sub_id, int)
    assert await externals["event_emit"]("CustomEvent", {"value": "x"}, tags=["scaffold"])
    stored = await event_store.get_events(limit=10)
    custom = next(event for event in stored if event["event_type"] == "CustomEvent")
    assert custom["payload"]["value"] == "x"
    assert custom["tags"] == ["scaffold"]
    history = await externals["event_get_history"](node.node_id, limit=10)
    assert isinstance(history, list)
    assert await externals["event_unsubscribe"](sub_id)

    await event_store.append(AgentMessageEvent(from_agent="a", to_agent=node.node_id, content="x"))
    got = await event_store.get_events_for_agent(node.node_id, limit=5)
    assert got


@pytest.mark.asyncio
async def test_externals_event_subscribe_supports_tag_filters(context_env) -> None:
    node_store, event_store, workspace_service = context_env
    node = make_node("src/app.py::alpha")
    await node_store.upsert_node(node)
    ws = await workspace_service.get_agent_workspace(node.node_id)
    context = await _context(node.node_id, ws, node_store, event_store)
    externals = context.to_capabilities_dict()

    sub_id = await externals["event_subscribe"](["CustomEvent"], None, None, ["review"])
    assert isinstance(sub_id, int)

    await externals["event_emit"]("CustomEvent", {"value": "no-match"}, tags=["other"])
    await externals["event_emit"]("CustomEvent", {"value": "match"}, tags=["review"])

    no_match_event = CustomEvent(
        event_type="CustomEvent",
        payload={"value": "n"},
        tags=("other",),
    )
    yes_match_event = CustomEvent(
        event_type="CustomEvent",
        payload={"value": "y"},
        tags=("review",),
    )
    assert node.node_id not in await event_store.subscriptions.get_matching_agents(no_match_event)
    assert node.node_id in await event_store.subscriptions.get_matching_agents(yes_match_event)


@pytest.mark.asyncio
async def test_request_human_input_blocks_until_response(context_env) -> None:
    node_store, event_store, workspace_service = context_env
    node = make_node("src/app.py::human")
    await node_store.upsert_node(node)
    assert await node_store.transition_status(node.node_id, NodeStatus.RUNNING)

    ws = await workspace_service.get_agent_workspace(node.node_id)
    context = await _context(node.node_id, ws, node_store, event_store, "corr-human")
    externals = context.to_capabilities_dict()

    task = asyncio.create_task(externals["request_human_input"]("Proceed?", ["yes", "no"]))
    await asyncio.sleep(0.01)

    events = await event_store.get_events(limit=10)
    request = next(event for event in events if event["event_type"] == "HumanInputRequestEvent")
    request_id = request["payload"]["request_id"]
    assert request["payload"]["question"] == "Proceed?"
    assert request["payload"]["options"] == ["yes", "no"]

    awaiting = await node_store.get_node(node.node_id)
    assert awaiting is not None
    assert awaiting.status == NodeStatus.AWAITING_INPUT

    assert event_store.resolve_response(request_id, "yes")
    assert await task == "yes"

    resumed = await node_store.get_node(node.node_id)
    assert resumed is not None
    assert resumed.status == NodeStatus.RUNNING


@pytest.mark.asyncio
async def test_request_human_input_times_out_and_resets_status(context_env) -> None:
    node_store, event_store, workspace_service = context_env
    node = make_node("src/app.py::human-timeout")
    await node_store.upsert_node(node)
    assert await node_store.transition_status(node.node_id, NodeStatus.RUNNING)

    ws = await workspace_service.get_agent_workspace(node.node_id)
    context = await _context(
        node.node_id,
        ws,
        node_store,
        event_store,
        "corr-human-timeout",
        human_input_timeout_s=0.01,
    )
    externals = context.to_capabilities_dict()

    with pytest.raises(TimeoutError):
        await externals["request_human_input"]("Need approval?", None)

    events = await event_store.get_events(limit=10)
    request = next(event for event in events if event["event_type"] == "HumanInputRequestEvent")
    request_id = request["payload"]["request_id"]
    assert not event_store.resolve_response(request_id, "late")

    resumed = await node_store.get_node(node.node_id)
    assert resumed is not None
    assert resumed.status == NodeStatus.RUNNING


@pytest.mark.asyncio
async def test_externals_communication(context_env) -> None:
    node_store, event_store, workspace_service = context_env
    sender = make_node("src/app.py::sender")
    target_a = make_node("src/app.py::target_a")
    target_b = make_node("src/app.py::target_b")
    await node_store.upsert_node(sender)
    await node_store.upsert_node(target_a)
    await node_store.upsert_node(target_b)
    ws = await workspace_service.get_agent_workspace(sender.node_id)
    context = await _context(sender.node_id, ws, node_store, event_store)
    externals = context.to_capabilities_dict()

    assert await externals["send_message"](target_a.node_id, "direct")
    summary = await externals["broadcast"]("*", "all")
    assert "Broadcast sent to" in summary
    events = await event_store.get_events(limit=10)
    message_events = [event for event in events if event["event_type"] == "AgentMessageEvent"]
    assert len(message_events) >= 3


@pytest.mark.asyncio
async def test_externals_broadcast_siblings_and_file_patterns(context_env) -> None:
    node_store, event_store, workspace_service = context_env
    sender = make_node("src/app.py::sender", file_path="src/app.py")
    sibling = make_node("src/app.py::sib", file_path="src/app.py")
    other = make_node("src/other.py::oth", file_path="src/other.py")
    await node_store.upsert_node(sender)
    await node_store.upsert_node(sibling)
    await node_store.upsert_node(other)
    ws = await workspace_service.get_agent_workspace(sender.node_id)
    context = await _context(sender.node_id, ws, node_store, event_store)
    externals = context.to_capabilities_dict()

    summary1 = await externals["broadcast"]("siblings", "same-file")
    summary2 = await externals["broadcast"]("file:src/other.py", "other-file")

    assert "1 agents" in summary1
    assert "1 agents" in summary2
    events = await event_store.get_events(limit=10)
    payloads = [e["payload"] for e in events if e["event_type"] == "AgentMessageEvent"]
    assert any(p["to_agent"] == sibling.node_id for p in payloads)
    assert any(p["to_agent"] == other.node_id for p in payloads)


@pytest.mark.asyncio
async def test_externals_broadcast_caps_target_count(context_env) -> None:
    node_store, event_store, workspace_service = context_env
    sender = make_node("src/app.py::sender")
    await node_store.upsert_node(sender)
    for idx in range(60):
        await node_store.upsert_node(make_node(f"src/app.py::target_{idx:02d}"))
    ws = await workspace_service.get_agent_workspace(sender.node_id)
    context = await _context(
        sender.node_id,
        ws,
        node_store,
        event_store,
        broadcast_max_targets=50,
    )
    externals = context.to_capabilities_dict()

    summary = await externals["broadcast"]("*", "all")
    assert "50 agents" in summary
    events = await event_store.get_events(limit=200)
    sent = [event for event in events if event["event_type"] == "AgentMessageEvent"]
    assert len(sent) == 50


@pytest.mark.asyncio
async def test_externals_code_ops(context_env) -> None:
    node_store, event_store, workspace_service = context_env
    source_path = workspace_service._project_root / "src" / "app.py"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    full_source = (
        "def alpha():\n"
        "    return 1\n\n"
        "def beta():\n"
        "    return 2\n"
    )
    source_path.write_text(full_source, encoding="utf-8")

    node = make_node("src/app.py::alpha", file_path=str(source_path))
    node = node.model_copy(update={"source_code": "def alpha():\n    return 1\n"})
    await node_store.upsert_node(node)
    ws = await workspace_service.get_agent_workspace(node.node_id)
    context = await _context(node.node_id, ws, node_store, event_store)
    externals = context.to_capabilities_dict()

    await externals["write_file"](f"source/{node.node_id}", "def alpha():\n    return 2\n")
    await externals["graph_set_status"](node.node_id, "running")
    proposal_id = await externals["propose_changes"]("Update alpha behavior")
    assert isinstance(proposal_id, str)
    assert proposal_id

    source = await externals["get_node_source"](node.node_id)
    assert "def alpha" in source
    file_source = source_path.read_text(encoding="utf-8")
    assert "def alpha():\n    return 1\n" in file_source

    events = await event_store.get_events(limit=5)
    proposal_events = [event for event in events if event["event_type"] == "RewriteProposalEvent"]
    assert proposal_events
    assert proposal_events[0]["payload"]["proposal_id"] == proposal_id
    assert proposal_events[0]["payload"]["reason"] == "Update alpha behavior"
    assert proposal_events[0]["payload"]["files"] == [f"source/{node.node_id}"]
    updated_node = await node_store.get_node(node.node_id)
    assert updated_node is not None
    assert updated_node.status == NodeStatus.AWAITING_REVIEW


@pytest.mark.asyncio
async def test_propose_changes_excludes_bundle_paths(context_env) -> None:
    node_store, event_store, workspace_service = context_env
    node = make_node("src/app.py::helper")
    await node_store.upsert_node(node)
    assert await node_store.transition_status(node.node_id, NodeStatus.RUNNING)
    ws = await workspace_service.get_agent_workspace(node.node_id)
    await ws.write("_bundle/tools/internal.pym", "ignored\n")
    await ws.write(f"source/{node.node_id}", "def helper():\n    return 2\n")
    await ws.write("notes/analysis.txt", "candidate notes\n")
    context = await _context(node.node_id, ws, node_store, event_store)
    externals = context.to_capabilities_dict()

    proposal_id = await externals["propose_changes"]()
    assert proposal_id

    events = await event_store.get_events(limit=10)
    proposal_event = next(
        event for event in events if event["event_type"] == "RewriteProposalEvent"
    )
    files = proposal_event["payload"]["files"]
    assert f"source/{node.node_id}" in files
    assert "notes/analysis.txt" in files
    assert "_bundle/tools/internal.pym" not in files


@pytest.mark.asyncio
async def test_externals_identity(context_env) -> None:
    node_store, event_store, workspace_service = context_env
    node = make_node("src/app.py::alpha")
    await node_store.upsert_node(node)
    ws = await workspace_service.get_agent_workspace(node.node_id)
    context = await _context(node.node_id, ws, node_store, event_store, "corr-x")
    externals = context.to_capabilities_dict()
    assert await externals["my_node_id"]() == node.node_id
    assert await externals["my_correlation_id"]() == "corr-x"


@pytest.mark.asyncio
async def test_externals_graph_get_children(context_env) -> None:
    node_store, event_store, workspace_service = context_env
    parent = make_node("src", node_type=NodeType.DIRECTORY)
    child_a = make_node("src/app.py::a", parent_id="src")
    child_b = make_node("src/lib", node_type=NodeType.DIRECTORY, parent_id="src")
    await node_store.upsert_node(parent)
    await node_store.upsert_node(child_a)
    await node_store.upsert_node(child_b)
    ws = await workspace_service.get_agent_workspace(parent.node_id)
    context = await _context(parent.node_id, ws, node_store, event_store)
    externals = context.to_capabilities_dict()

    children = await externals["graph_get_children"]()
    child_ids = [node["node_id"] for node in children]
    assert child_ids == ["src/app.py::a", "src/lib"]


@pytest.mark.asyncio
async def test_externals_emit_uses_outbox_when_provided(context_env) -> None:
    node_store, event_store, workspace_service = context_env
    node = make_node("src/app.py::alpha")
    await node_store.upsert_node(node)
    ws = await workspace_service.get_agent_workspace(node.node_id)

    outbox = RecordingOutbox(actor_id=node.node_id)
    outbox.correlation_id = "corr-outbox"
    context = TurnContext(
        node_id=node.node_id,
        workspace=ws,
        correlation_id="corr-outbox",
        node_store=node_store,
        event_store=event_store,
        outbox=outbox,
    )
    externals = context.to_capabilities_dict()

    await externals["event_emit"]("CustomEvent", {"key": "val"})
    await externals["send_message"]("target-node", "hello")

    assert len(outbox.events) == 2
    assert outbox.events[0].event_type == "CustomEvent"
    assert outbox.events[1].event_type == "AgentMessageEvent"

    stored = await event_store.get_events(limit=10)
    assert not any(event["event_type"] == "CustomEvent" for event in stored)


@pytest.mark.asyncio
async def test_externals_send_message_rate_limit(context_env) -> None:
    node_store, event_store, workspace_service = context_env
    sender = make_node("src/app.py::sender")
    target = make_node("src/app.py::target")
    await node_store.upsert_node(sender)
    await node_store.upsert_node(target)
    ws = await workspace_service.get_agent_workspace(sender.node_id)
    context = await _context(
        sender.node_id,
        ws,
        node_store,
        event_store,
        send_message_rate_limit=2,
        send_message_rate_window_s=60.0,
    )
    externals = context.to_capabilities_dict()

    assert await externals["send_message"](target.node_id, "one")
    assert await externals["send_message"](target.node_id, "two")
    assert not await externals["send_message"](target.node_id, "three")


@pytest.mark.asyncio
async def test_externals_send_message_rate_limit_isolated_per_context_instance(
    context_env,
) -> None:
    node_store, event_store, workspace_service = context_env
    sender = make_node("src/app.py::sender-isolated")
    target = make_node("src/app.py::target-isolated")
    await node_store.upsert_node(sender)
    await node_store.upsert_node(target)
    ws = await workspace_service.get_agent_workspace(sender.node_id)

    first = await _context(
        sender.node_id,
        ws,
        node_store,
        event_store,
        send_message_rate_limit=1,
        send_message_rate_window_s=60.0,
    )
    second = await _context(
        sender.node_id,
        ws,
        node_store,
        event_store,
        send_message_rate_limit=1,
        send_message_rate_window_s=60.0,
    )

    first_externals = first.to_capabilities_dict()
    second_externals = second.to_capabilities_dict()

    assert await first_externals["send_message"](target.node_id, "one")
    assert await second_externals["send_message"](target.node_id, "fresh-context")


@pytest.mark.asyncio
async def test_semantic_search_returns_empty_without_service(context_env) -> None:
    node_store, event_store, workspace_service = context_env
    node = make_node("src/app.py::search-none")
    await node_store.upsert_node(node)
    ws = await workspace_service.get_agent_workspace(node.node_id)
    context = await _context(node.node_id, ws, node_store, event_store)

    assert await context.semantic_search("auth") == []
    assert await context.find_similar_code("chunk-1") == []


@pytest.mark.asyncio
async def test_semantic_search_returns_empty_when_service_unavailable(context_env) -> None:
    node_store, event_store, workspace_service = context_env
    node = make_node("src/app.py::search-offline")
    await node_store.upsert_node(node)
    ws = await workspace_service.get_agent_workspace(node.node_id)
    search_service = _MockSearchService(available=False)
    context = await _context(
        node.node_id,
        ws,
        node_store,
        event_store,
        search_service=search_service,
    )

    assert await context.semantic_search("auth") == []
    assert await context.find_similar_code("chunk-1") == []
    assert search_service.search_calls == []
    assert search_service.similar_calls == []


@pytest.mark.asyncio
async def test_semantic_search_and_find_similar_delegate(context_env) -> None:
    node_store, event_store, workspace_service = context_env
    node = make_node("src/app.py::search-live")
    await node_store.upsert_node(node)
    ws = await workspace_service.get_agent_workspace(node.node_id)
    search_service = _MockSearchService(available=True)
    context = await _context(
        node.node_id,
        ws,
        node_store,
        event_store,
        search_service=search_service,
    )

    results = await context.semantic_search("auth", "code", 5, "hybrid")
    similar = await context.find_similar_code("c1", "code", 3)

    assert results == [{"chunk_id": "c1", "score": 0.9}]
    assert similar == [{"chunk_id": "c1", "score": 0.8}]
    assert search_service.search_calls == [("auth", "code", 5, "hybrid")]
    assert search_service.similar_calls == [("c1", "code", 3)]


@pytest.mark.asyncio
async def test_capabilities_include_search_methods(context_env) -> None:
    node_store, event_store, workspace_service = context_env
    node = make_node("src/app.py::search-capabilities")
    await node_store.upsert_node(node)
    ws = await workspace_service.get_agent_workspace(node.node_id)
    search_service = _MockSearchService(available=True)
    context = await _context(
        node.node_id,
        ws,
        node_store,
        event_store,
        search_service=search_service,
    )
    externals = context.to_capabilities_dict()

    assert "semantic_search" in externals
    assert "find_similar_code" in externals
