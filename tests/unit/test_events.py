from __future__ import annotations

import time

from remora.core.events import (
    AgentCompleteEvent,
    AgentErrorEvent,
    AgentMessageEvent,
    AgentStartEvent,
    ContentChangedEvent,
    CursorFocusEvent,
    HumanInputRequestEvent,
    HumanInputResponseEvent,
    NodeChangedEvent,
    NodeDiscoveredEvent,
    NodeRemovedEvent,
    ToolResultEvent,
)
from remora.core.events.subscriptions import SubscriptionPattern


def test_agent_text_response_event_removed() -> None:
    import remora.core.events.types as event_types

    assert not hasattr(event_types, "AgentTextResponse")


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


def test_event_to_envelope_shape() -> None:
    event = AgentMessageEvent(
        from_agent="a",
        to_agent="b",
        content="hello",
        correlation_id="corr-1",
        tags=("chat",),
    )
    envelope = event.to_envelope()
    assert envelope["event_type"] == "AgentMessageEvent"
    assert envelope["correlation_id"] == "corr-1"
    assert envelope["tags"] == ["chat"]
    assert envelope["payload"] == {
        "from_agent": "a",
        "to_agent": "b",
        "content": "hello",
    }


def test_subscription_pattern_matches_tags() -> None:
    event = AgentMessageEvent(
        from_agent="a",
        to_agent="b",
        content="hello",
        tags=("scaffold", "review"),
    )
    assert SubscriptionPattern(tags=["scaffold"]).matches(event)
    assert SubscriptionPattern(tags=["review"]).matches(event)
    assert not SubscriptionPattern(tags=["missing"]).matches(event)


def test_all_event_types_instantiate() -> None:
    events = [
        AgentStartEvent(agent_id="a", node_name="node"),
        AgentCompleteEvent(agent_id="a", result_summary="ok"),
        AgentErrorEvent(agent_id="a", error="err"),
        AgentMessageEvent(from_agent="a", to_agent="b", content="msg"),
        AgentMessageEvent(from_agent="user", to_agent="a", content="hello"),
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
        ContentChangedEvent(
            path="src/app.py",
            change_type="modified",
            agent_id="a",
            old_hash="old",
            new_hash="new",
        ),
        HumanInputRequestEvent(
            agent_id="a",
            request_id="req-1",
            question="Proceed?",
            options=("yes", "no"),
        ),
        HumanInputResponseEvent(
            agent_id="a",
            request_id="req-1",
            response="yes",
        ),
        ToolResultEvent(agent_id="a", tool_name="rewrite_self", result_summary="done"),
        CursorFocusEvent(file_path="src/app.py", line=3, character=0, node_id="src/app.py::a"),
    ]
    assert all(event.event_type for event in events)


def test_agent_complete_event_preserves_full_response() -> None:
    long_text = "x" * 500
    event = AgentCompleteEvent(
        agent_id="test",
        result_summary=long_text[:200],
        full_response=long_text,
    )
    assert len(event.result_summary) == 200
    assert len(event.full_response) == 500
