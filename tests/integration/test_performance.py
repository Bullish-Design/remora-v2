from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from remora.code.discovery import discover
from remora.core.db import AsyncDB
from remora.core.events import HumanChatEvent, SubscriptionPattern, SubscriptionRegistry
from remora.core.graph import NodeStore
from remora.core.node import CodeNode


def _node(idx: int) -> CodeNode:
    name = f"f{idx}"
    return CodeNode(
        node_id=f"src/perf.py::{name}",
        node_type="function",
        name=name,
        full_name=name,
        file_path="src/perf.py",
        start_line=idx + 1,
        end_line=idx + 1,
        source_code=f"def {name}():\n    return {idx}\n",
        source_hash=f"h-{idx}",
    )


@pytest.mark.asyncio
async def test_perf_discovery_100_nodes(tmp_path: Path) -> None:
    file_path = tmp_path / "src" / "perf.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    source = "\n".join(f"def f{i}():\n    return {i}\n" for i in range(120))
    file_path.write_text(source, encoding="utf-8")

    started = time.perf_counter()
    nodes = discover([tmp_path / "src"], languages=["python"])
    elapsed = time.perf_counter() - started

    functions = [node for node in nodes if node.node_type == "function"]
    assert len(functions) >= 100
    assert elapsed < 5.0


@pytest.mark.asyncio
async def test_perf_nodestore_100_upserts(tmp_path: Path) -> None:
    db = AsyncDB.from_path(tmp_path / "perf-nodes.db")
    node_store = NodeStore(db)
    await node_store.create_tables()

    started = time.perf_counter()
    for idx in range(100):
        await node_store.upsert_node(_node(idx))
    elapsed = time.perf_counter() - started

    assert elapsed < 1.0
    db.close()


@pytest.mark.asyncio
async def test_perf_subscription_matching(tmp_path: Path) -> None:
    db = AsyncDB.from_path(tmp_path / "perf-subs.db")
    registry = SubscriptionRegistry(db)
    await registry.create_tables()

    for idx in range(100):
        await registry.register(
            f"agent-{idx}",
            SubscriptionPattern(to_agent=f"agent-{idx}"),
        )

    event = HumanChatEvent(to_agent="agent-42", message="ping")
    started = time.perf_counter()
    for _ in range(1000):
        matched = await registry.get_matching_agents(event)
    elapsed = time.perf_counter() - started

    assert "agent-42" in matched
    assert elapsed < 1.0
    db.close()
