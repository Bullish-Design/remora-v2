from __future__ import annotations

import pytest

from remora.core.events import (
    AgentMessageEvent,
    ContentChangedEvent,
    HumanChatEvent,
    SubscriptionPattern,
    SubscriptionRegistry,
)


def test_subscription_pattern_matches_exact() -> None:
    pattern = SubscriptionPattern(to_agent="b")
    assert pattern.matches(AgentMessageEvent(from_agent="a", to_agent="b", content="hello"))
    assert not pattern.matches(
        AgentMessageEvent(from_agent="a", to_agent="c", content="hello")
    )


def test_subscription_pattern_matches_event_type() -> None:
    pattern = SubscriptionPattern(event_types=["HumanChatEvent"])
    assert pattern.matches(HumanChatEvent(to_agent="a", message="hi"))
    assert not pattern.matches(AgentMessageEvent(from_agent="a", to_agent="b", content="hello"))


def test_subscription_pattern_matches_path_glob() -> None:
    pattern = SubscriptionPattern(path_glob="src/**/*.py")
    assert pattern.matches(ContentChangedEvent(path="src/auth/service.py"))
    assert not pattern.matches(ContentChangedEvent(path="docs/readme.md"))


def test_subscription_pattern_none_matches_all() -> None:
    pattern = SubscriptionPattern()
    assert pattern.matches(HumanChatEvent(to_agent="a", message="hi"))
    assert pattern.matches(ContentChangedEvent(path="any/path.txt"))


@pytest.mark.asyncio
async def test_registry_register_and_match(db_connection, db_lock) -> None:
    registry = SubscriptionRegistry(db_connection, db_lock)
    await registry.register("agent-b", SubscriptionPattern(to_agent="b"))
    matches = await registry.get_matching_agents(
        AgentMessageEvent(from_agent="a", to_agent="b", content="hello")
    )
    assert matches == ["agent-b"]


@pytest.mark.asyncio
async def test_registry_unregister(db_connection, db_lock) -> None:
    registry = SubscriptionRegistry(db_connection, db_lock)
    sub_id = await registry.register("agent-b", SubscriptionPattern(to_agent="b"))
    assert await registry.unregister(sub_id)
    matches = await registry.get_matching_agents(
        AgentMessageEvent(from_agent="a", to_agent="b", content="hello")
    )
    assert matches == []


@pytest.mark.asyncio
async def test_registry_cache_invalidation(db_connection, db_lock) -> None:
    registry = SubscriptionRegistry(db_connection, db_lock)
    await registry.register("agent-b", SubscriptionPattern(to_agent="b"))
    first = await registry.get_matching_agents(
        AgentMessageEvent(from_agent="a", to_agent="b", content="hello")
    )
    assert first == ["agent-b"]

    await registry.register("agent-c", SubscriptionPattern(to_agent="b"))
    second = await registry.get_matching_agents(
        AgentMessageEvent(from_agent="a", to_agent="b", content="hello")
    )
    assert second == ["agent-b", "agent-c"]
