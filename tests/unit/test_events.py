from __future__ import annotations

import time

from remora.core.events import (
    AgentCompleteEvent,
    AgentErrorEvent,
    AgentMessageEvent,
    AgentStartEvent,
    AgentTextResponse,
    ContentChangedEvent,
    HumanChatEvent,
    NodeChangedEvent,
    NodeDiscoveredEvent,
    NodeRemovedEvent,
    RewriteProposalEvent,
    ToolResultEvent,
)


def test_event_base_auto_type() -> None:
    event = AgentStartEvent(agent_id="a1")
    assert event.event_type == "AgentStartEvent"


def test_event_timestamp() -> None:
    before = time.time()
    event = AgentErrorEvent(agent_id="a1", error="boom")
    after = time.time()
    assert before <= event.timestamp <= after


def test_event_serialization() -> None:
    event = AgentMessageEvent(from_agent="a", to_agent="b", content="hello")
    dumped = event.model_dump()
    assert dumped["event_type"] == "AgentMessageEvent"
    assert dumped["from_agent"] == "a"
    assert dumped["to_agent"] == "b"
    assert dumped["content"] == "hello"


def test_all_event_types_instantiate() -> None:
    events = [
        AgentStartEvent(agent_id="a", node_name="node"),
        AgentCompleteEvent(agent_id="a", result_summary="ok"),
        AgentErrorEvent(agent_id="a", error="err"),
        AgentMessageEvent(from_agent="a", to_agent="b", content="msg"),
        HumanChatEvent(to_agent="a", message="hello"),
        AgentTextResponse(agent_id="a", content="text"),
        NodeDiscoveredEvent(
            node_id="src/app.py::f",
            node_type="function",
            file_path="src/app.py",
            name="f",
        ),
        NodeRemovedEvent(
            node_id="src/app.py::f",
            node_type="function",
            file_path="src/app.py",
            name="f",
        ),
        NodeChangedEvent(node_id="src/app.py::f", old_hash="old", new_hash="new"),
        ContentChangedEvent(path="src/app.py", change_type="modified"),
        RewriteProposalEvent(
            agent_id="a",
            proposal_id="p1",
            file_path="src/app.py",
            old_source="old",
            new_source="new",
            diff="@@",
        ),
        ToolResultEvent(agent_id="a", tool_name="rewrite_self", result_summary="done"),
    ]
    assert all(event.event_type for event in events)
