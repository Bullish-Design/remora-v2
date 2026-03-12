from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
import pytest_asyncio

import remora.code.reconciler as reconciler_module
from remora.code.reconciler import FileReconciler
from remora.core.config import Config
from remora.core.events import ContentChangedEvent
from remora.core.db import AsyncDB
from remora.core.events import EventStore
from remora.core.graph import AgentStore, NodeStore
from remora.core.workspace import CairnWorkspaceService
from tests.factories import write_bundle_templates, write_file


@pytest_asyncio.fixture
async def reconcile_env(tmp_path: Path):
    db = AsyncDB.from_path(tmp_path / "reconcile.db")
    node_store = NodeStore(db)
    agent_store = AgentStore(db)
    await node_store.create_tables()
    await agent_store.create_tables()
    event_store = EventStore(db=db)
    await event_store.create_tables()

    bundles_root = tmp_path / "bundles"
    write_bundle_templates(bundles_root)

    config = Config(
        discovery_paths=("src",),
        discovery_languages=("python",),
        language_map={".py": "python"},
        query_paths=(),
        swarm_root=".remora-reconcile",
        bundle_root=str(bundles_root),
    )
    workspace_service = CairnWorkspaceService(config, tmp_path)
    await workspace_service.initialize()
    reconciler = FileReconciler(
        config,
        node_store,
        agent_store,
        event_store,
        workspace_service,
        project_root=tmp_path,
    )

    yield node_store, agent_store, event_store, workspace_service, config, reconciler

    await workspace_service.close()
    db.close()


@pytest.mark.asyncio
async def test_full_scan_discovers_registers_and_emits(reconcile_env, tmp_path: Path) -> None:
    node_store, _agent_store, event_store, _workspace_service, _config, reconciler = reconcile_env
    write_file(tmp_path / "src" / "app.py", "def a():\n    return 1\n")

    nodes = await reconciler.full_scan()
    stored = await node_store.list_nodes()
    events = await event_store.get_events(limit=20)
    discovered = [event for event in events if event["event_type"] == "NodeDiscoveredEvent"]
    subs = event_store.connection.execute("SELECT * FROM subscriptions").fetchall()  # type: ignore[union-attr]

    assert nodes
    assert stored
    assert len(discovered) == len(nodes)
    assert len(subs) == len(nodes) * 2


@pytest.mark.asyncio
async def test_reconcile_cycle_modified_file_only(
    reconcile_env,
    tmp_path: Path,
    monkeypatch,
) -> None:
    _node_store, _agent_store, _event_store, _workspace_service, _config, reconciler = reconcile_env
    first = tmp_path / "src" / "first.py"
    second = tmp_path / "src" / "second.py"
    write_file(first, "def first():\n    return 1\n")
    write_file(second, "def second():\n    return 2\n")
    await reconciler.full_scan()

    seen_files: list[Path] = []
    real_discover = reconciler_module.discover

    def wrapped_discover(paths, **kwargs):  # noqa: ANN001, ANN202
        seen_files.extend(paths)
        return real_discover(paths, **kwargs)

    monkeypatch.setattr(reconciler_module, "discover", wrapped_discover)

    write_file(second, "def second():\n    return 3\n")
    await asyncio.sleep(0.001)
    await reconciler.reconcile_cycle()

    changed_calls = [path for path in seen_files if path.name == "second.py"]
    first_calls = [path for path in seen_files if path.name == "first.py"]
    assert changed_calls
    assert not first_calls


@pytest.mark.asyncio
async def test_reconcile_cycle_handles_new_and_deleted_files(reconcile_env, tmp_path: Path) -> None:
    node_store, _agent_store, event_store, _workspace_service, _config, reconciler = reconcile_env
    file_a = tmp_path / "src" / "a.py"
    file_b = tmp_path / "src" / "b.py"
    write_file(file_a, "def a():\n    return 1\n")
    await reconciler.full_scan()

    write_file(file_b, "def b():\n    return 2\n")
    await reconciler.reconcile_cycle()
    assert await node_store.get_node(f"{file_b}::b") is not None

    file_a.unlink()
    await reconciler.reconcile_cycle()
    assert await node_store.get_node(f"{file_a}::a") is None

    events = await event_store.get_events(limit=50)
    removed = [event for event in events if event["event_type"] == "NodeRemovedEvent"]
    assert removed


@pytest.mark.asyncio
async def test_reconcile_subscription_idempotency(reconcile_env, tmp_path: Path) -> None:
    _node_store, _agent_store, event_store, _workspace_service, _config, reconciler = reconcile_env
    write_file(tmp_path / "src" / "app.py", "def a():\n    return 1\n")
    await reconciler.full_scan()
    await reconciler.reconcile_cycle()
    await reconciler.reconcile_cycle()

    conn = event_store.connection
    assert conn is not None
    rows = conn.execute("SELECT agent_id, pattern_json FROM subscriptions").fetchall()
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["agent_id"], []).append(json.loads(row["pattern_json"]))

    for patterns in grouped.values():
        assert len(patterns) == 2


@pytest.mark.asyncio
async def test_reconciler_survives_cycle_error(reconcile_env, tmp_path: Path, monkeypatch) -> None:
    _node_store, _agent_store, _event_store, _workspace_service, _config, reconciler = reconcile_env
    write_file(tmp_path / "src" / "app.py", "def a():\n    return 1\n")
    await reconciler.full_scan()

    call_count = 0
    original_cycle = reconciler.reconcile_cycle

    async def flaky_cycle() -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("simulated failure")
        await original_cycle()

    monkeypatch.setattr(reconciler, "reconcile_cycle", flaky_cycle)
    reconciler._watch_mode = False

    task = asyncio.create_task(reconciler.run_forever(poll_interval_s=0.01))
    await asyncio.sleep(0.05)
    reconciler.stop()
    await asyncio.wait_for(task, timeout=1.0)

    assert call_count >= 2


@pytest.mark.asyncio
async def test_reconciler_watch_fallback_to_polling(reconcile_env, monkeypatch) -> None:
    _node_store, _agent_store, _event_store, _workspace_service, _config, reconciler = reconcile_env
    called = False

    async def fake_watch() -> None:
        raise ImportError("watchfiles unavailable")

    async def fake_poll(_interval: float) -> None:
        nonlocal called
        called = True
        reconciler.stop()

    monkeypatch.setattr(reconciler, "_run_watching", fake_watch)
    monkeypatch.setattr(reconciler, "_run_polling", fake_poll)
    await reconciler.run_forever(poll_interval_s=0.01)
    assert called


@pytest.mark.asyncio
async def test_reconciler_content_changed_event_triggers_reconcile(
    reconcile_env,
    tmp_path: Path,
) -> None:
    node_store, _agent_store, _event_store, _workspace_service, _config, reconciler = reconcile_env
    source_file = tmp_path / "src" / "event.py"
    write_file(source_file, "def event_fn():\n    return 1\n")
    await reconciler.full_scan()

    write_file(source_file, "def event_fn():\n    return 2\n")
    await reconciler._on_content_changed(ContentChangedEvent(path=str(source_file), change_type="modified"))

    node = await node_store.get_node(f"{source_file}::event_fn")
    assert node is not None
    assert "return 2" in node.source_code


@pytest.mark.asyncio
async def test_reconciler_handles_malformed_source(reconcile_env, tmp_path: Path) -> None:
    node_store, _agent_store, _event_store, _workspace_service, _config, reconciler = reconcile_env
    bad_source = tmp_path / "src" / "broken.py"
    write_file(bad_source, "def broken(:\n    pass\n")

    await reconciler.reconcile_cycle()
    nodes = await node_store.list_nodes(file_path=str(bad_source))
    assert isinstance(nodes, list)
