from __future__ import annotations

import pytest

from remora.core.graph import AgentStore
from remora.core.node import Agent
from remora.core.types import NodeStatus


@pytest.mark.asyncio
async def test_agentstore_upsert_and_get(db) -> None:
    store = AgentStore(db)
    await store.create_tables()
    agent = Agent(agent_id="a1", element_id="src/a.py::a", status=NodeStatus.IDLE)
    await store.upsert_agent(agent)

    got = await store.get_agent("a1")
    assert got is not None
    assert got.agent_id == "a1"
    assert got.element_id == "src/a.py::a"


@pytest.mark.asyncio
async def test_agentstore_transition_status(db) -> None:
    store = AgentStore(db)
    await store.create_tables()
    await store.upsert_agent(Agent(agent_id="a1", status=NodeStatus.IDLE))

    assert await store.transition_status("a1", NodeStatus.RUNNING)
    running = await store.get_agent("a1")
    assert running is not None
    assert running.status == NodeStatus.RUNNING

    assert not await store.transition_status("a1", NodeStatus.RUNNING)


@pytest.mark.asyncio
async def test_agentstore_list_and_delete(db) -> None:
    store = AgentStore(db)
    await store.create_tables()
    await store.upsert_agent(Agent(agent_id="a1", status=NodeStatus.IDLE))
    await store.upsert_agent(Agent(agent_id="a2", status=NodeStatus.RUNNING))

    running = await store.list_agents(NodeStatus.RUNNING)
    assert [a.agent_id for a in running] == ["a2"]

    assert await store.delete_agent("a1")
    assert await store.get_agent("a1") is None
