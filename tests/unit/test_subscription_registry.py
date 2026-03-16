from __future__ import annotations

import pytest

from remora.core.events import (
    AgentMessageEvent,
    ContentChangedEvent,
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
    pattern = SubscriptionPattern(event_types=["AgentMessageEvent"])
    assert pattern.matches(AgentMessageEvent(from_agent="user", to_agent="a", content="hi"))
    assert not pattern.matches(ContentChangedEvent(path="src/app.py"))


def test_subscription_pattern_matches_path_glob() -> None:
    pattern = SubscriptionPattern(path_glob="src/**/*.py")
    assert pattern.matches(ContentChangedEvent(path="src/auth/service.py"))
    assert not pattern.matches(ContentChangedEvent(path="docs/readme.md"))


def test_subscription_pattern_none_matches_all() -> None:
    pattern = SubscriptionPattern()
    assert pattern.matches(AgentMessageEvent(from_agent="user", to_agent="a", content="hi"))
    assert pattern.matches(ContentChangedEvent(path="any/path.txt"))


@pytest.mark.asyncio
async def test_registry_register_and_match(db) -> None:
    registry = SubscriptionRegistry(db)
    await registry.create_tables()
    await registry.register("agent-b", SubscriptionPattern(to_agent="b"))
    matches = await registry.get_matching_agents(
        AgentMessageEvent(from_agent="a", to_agent="b", content="hello")
    )
    assert matches == ["agent-b"]


@pytest.mark.asyncio
async def test_registry_unregister(db) -> None:
    registry = SubscriptionRegistry(db)
    await registry.create_tables()
    sub_id = await registry.register("agent-b", SubscriptionPattern(to_agent="b"))
    assert await registry.unregister(sub_id)
    matches = await registry.get_matching_agents(
        AgentMessageEvent(from_agent="a", to_agent="b", content="hello")
    )
    assert matches == []


@pytest.mark.asyncio
async def test_registry_cache_invalidation(db) -> None:
    registry = SubscriptionRegistry(db)
    await registry.create_tables()
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


@pytest.mark.asyncio
async def test_registry_register_updates_cache_incrementally(db, monkeypatch) -> None:
    registry = SubscriptionRegistry(db)
    await registry.create_tables()
    await registry.register("agent-b", SubscriptionPattern(to_agent="b"))
    first = await registry.get_matching_agents(
        AgentMessageEvent(from_agent="a", to_agent="b", content="hello")
    )
    assert first == ["agent-b"]

    async def fail_rebuild() -> None:
        raise AssertionError("cache rebuild should not be required")

    monkeypatch.setattr(registry, "_rebuild_cache", fail_rebuild)
    await registry.register("agent-c", SubscriptionPattern(to_agent="b"))
    second = await registry.get_matching_agents(
        AgentMessageEvent(from_agent="a", to_agent="b", content="hello")
    )
    assert second == ["agent-b", "agent-c"]


@pytest.mark.asyncio
async def test_registry_unregister_updates_cache_incrementally(db, monkeypatch) -> None:
    registry = SubscriptionRegistry(db)
    await registry.create_tables()
    sub_b = await registry.register("agent-b", SubscriptionPattern(to_agent="b"))
    sub_c = await registry.register("agent-c", SubscriptionPattern(to_agent="b"))

    baseline = await registry.get_matching_agents(
        AgentMessageEvent(from_agent="a", to_agent="b", content="hello")
    )
    assert baseline == ["agent-b", "agent-c"]

    async def fail_rebuild() -> None:
        raise AssertionError("cache rebuild should not be required")

    monkeypatch.setattr(registry, "_rebuild_cache", fail_rebuild)

    assert await registry.unregister(sub_c)
    after_unsub = await registry.get_matching_agents(
        AgentMessageEvent(from_agent="a", to_agent="b", content="hello")
    )
    assert after_unsub == ["agent-b"]

    assert await registry.unregister_by_agent("agent-b") == 1
    after_agent_remove = await registry.get_matching_agents(
        AgentMessageEvent(from_agent="a", to_agent="b", content="hello")
    )
    assert after_agent_remove == []
