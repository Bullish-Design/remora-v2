from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from tests.factories import write_bundle_templates, write_file

import remora.code.reconciler as reconciler_module
from remora.code.reconciler import FileReconciler
from remora.core.config import Config
from remora.core.db import open_database
from remora.core.events import AgentMessageEvent, ContentChangedEvent, EventStore, NodeChangedEvent
from remora.core.graph import NodeStore
from remora.core.workspace import CairnWorkspaceService


@pytest_asyncio.fixture
async def reconcile_env(tmp_path: Path):
    db = await open_database(tmp_path / "reconcile.db")
    node_store = NodeStore(db)
    await node_store.create_tables()
    event_store = EventStore(db=db)
    await event_store.create_tables()

    bundles_root = tmp_path / "bundles"
    write_bundle_templates(bundles_root)

    config = Config(
        discovery_paths=("src",),
        discovery_languages=("python",),
        language_map={".py": "python"},
        query_paths=(),
        workspace_root=".remora-reconcile",
        bundle_root=str(bundles_root),
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

    yield node_store, event_store, workspace_service, config, reconciler

    await workspace_service.close()
    await db.close()


@pytest.mark.asyncio
async def test_full_scan_discovers_registers_and_emits(reconcile_env, tmp_path: Path) -> None:
    node_store, event_store, _workspace_service, _config, reconciler = reconcile_env
    write_file(tmp_path / "src" / "app.py", "def a():\n    return 1\n")

    nodes = await reconciler.full_scan()
    stored = await node_store.list_nodes()
    events = await event_store.get_events(limit=20)
    discovered = [event for event in events if event["event_type"] == "NodeDiscoveredEvent"]

    assert nodes
    assert stored
    assert len(discovered) == len(stored)
    assert any(node.node_type == "directory" and node.node_id == "." for node in stored)

    app_node = next(node for node in stored if node.node_id.endswith("::a"))
    assert app_node.parent_id == "src"

    for node in stored:
        message_event = AgentMessageEvent(
            from_agent="user",
            to_agent=node.node_id,
            content="hello",
        )
        matched_message = await event_store.subscriptions.get_matching_agents(message_event)
        assert node.node_id in matched_message

        if node.node_type == "directory":
            child_path = "src/app.py" if node.file_path == "." else f"mock/{node.file_path}/child.py"
            node_event = NodeChangedEvent(
                node_id=node.node_id,
                old_hash="old",
                new_hash="new",
                file_path=child_path,
            )
            matched_node_changed = await event_store.subscriptions.get_matching_agents(node_event)
            assert node.node_id in matched_node_changed

            content_event = ContentChangedEvent(path=child_path)
            matched_content = await event_store.subscriptions.get_matching_agents(content_event)
            assert node.node_id in matched_content


@pytest.mark.asyncio
async def test_reconcile_cycle_modified_file_only(
    reconcile_env,
    tmp_path: Path,
    monkeypatch,
) -> None:
    _node_store, _event_store, _workspace_service, _config, reconciler = reconcile_env
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
    node_store, event_store, _workspace_service, _config, reconciler = reconcile_env
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
    node_store, event_store, _workspace_service, _config, reconciler = reconcile_env
    write_file(tmp_path / "src" / "app.py", "def a():\n    return 1\n")
    await reconciler.full_scan()
    await reconciler.reconcile_cycle()
    await reconciler.reconcile_cycle()

    nodes = await node_store.list_nodes()
    for node in nodes:
        message_event = AgentMessageEvent(
            from_agent="test",
            to_agent=node.node_id,
            content="ping",
        )
        matched = await event_store.subscriptions.get_matching_agents(message_event)
        assert node.node_id in matched


@pytest.mark.asyncio
async def test_reconciler_survives_cycle_error(reconcile_env, tmp_path: Path, monkeypatch) -> None:
    _node_store, _event_store, _workspace_service, _config, reconciler = reconcile_env
    source = tmp_path / "src" / "app.py"
    write_file(source, "def a():\n    return 1\n")

    call_count = 0

    async def fake_awatch(*_args, **_kwargs):  # noqa: ANN001, ANN202
        yield {(1, str(source))}
        yield {(1, str(source))}

    async def flaky_reconcile(_file_path: str, _mtime_ns: int) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("simulated failure")
        reconciler.stop()

    monkeypatch.setitem(sys.modules, "watchfiles", SimpleNamespace(awatch=fake_awatch))
    monkeypatch.setattr(reconciler, "_reconcile_file", flaky_reconcile)

    await asyncio.wait_for(reconciler.run_forever(), timeout=1.0)
    assert call_count >= 2


@pytest.mark.asyncio
async def test_reconciler_watch_import_error_is_not_suppressed(reconcile_env, monkeypatch) -> None:
    _node_store, _event_store, _workspace_service, _config, reconciler = reconcile_env

    async def fake_watch() -> None:
        raise ImportError("watchfiles unavailable")

    monkeypatch.setattr(reconciler, "_run_watching", fake_watch)
    with pytest.raises(ImportError, match="watchfiles unavailable"):
        await asyncio.wait_for(reconciler.run_forever(), timeout=0.05)


@pytest.mark.asyncio
async def test_reconciler_content_changed_event_triggers_reconcile(
    reconcile_env,
    tmp_path: Path,
) -> None:
    node_store, _event_store, _workspace_service, _config, reconciler = reconcile_env
    source_file = tmp_path / "src" / "event.py"
    write_file(source_file, "def event_fn():\n    return 1\n")
    await reconciler.full_scan()

    write_file(source_file, "def event_fn():\n    return 2\n")
    await reconciler._on_content_changed(
        ContentChangedEvent(path=str(source_file), change_type="modified")
    )

    node = await node_store.get_node(f"{source_file}::event_fn")
    assert node is not None
    assert "return 2" in node.source_code


@pytest.mark.asyncio
async def test_reconciler_handles_malformed_source(reconcile_env, tmp_path: Path) -> None:
    node_store, _event_store, _workspace_service, _config, reconciler = reconcile_env
    bad_source = tmp_path / "src" / "broken.py"
    write_file(bad_source, "def broken(:\n    pass\n")

    await reconciler.reconcile_cycle()
    nodes = await node_store.list_nodes(file_path=str(bad_source))
    assert isinstance(nodes, list)


@pytest.mark.asyncio
async def test_directory_nodes_materialize_parent_chain(reconcile_env, tmp_path: Path) -> None:
    node_store, _event_store, _workspace_service, _config, reconciler = reconcile_env
    write_file(tmp_path / "src" / "pkg" / "mod.py", "def fn():\n    return 1\n")

    await reconciler.full_scan()
    root = await node_store.get_node(".")
    src_dir = await node_store.get_node("src")
    pkg_dir = await node_store.get_node("src/pkg")
    fn_node = await node_store.get_node(f"{tmp_path / 'src' / 'pkg' / 'mod.py'}::fn")

    assert root is not None
    assert root.node_type == "directory"
    assert root.parent_id is None
    assert src_dir is not None
    assert src_dir.parent_id == "."
    assert pkg_dir is not None
    assert pkg_dir.parent_id == "src"
    assert fn_node is not None
    assert fn_node.parent_id == "src/pkg"


@pytest.mark.asyncio
async def test_directory_nodes_removed_when_tree_disappears(reconcile_env, tmp_path: Path) -> None:
    node_store, event_store, _workspace_service, _config, reconciler = reconcile_env
    source = tmp_path / "src" / "gone" / "leaf.py"
    write_file(source, "def leaf():\n    return 1\n")
    await reconciler.full_scan()

    source.unlink()
    await reconciler.reconcile_cycle()

    assert await node_store.get_node("src/gone") is None
    events = await event_store.get_events(limit=50)
    removed_ids = [
        event["payload"]["node_id"]
        for event in events
        if event["event_type"] == "NodeRemovedEvent"
    ]
    assert "src/gone" in removed_ids


@pytest.mark.asyncio
async def test_directory_subscriptions_refreshed_on_startup(reconcile_env, tmp_path: Path) -> None:
    node_store, event_store, workspace_service, config, reconciler = reconcile_env
    write_file(tmp_path / "src" / "app.py", "def a():\n    return 1\n")
    await reconciler.full_scan()

    await event_store.subscriptions.unregister_by_agent(".")

    restart_reconciler = FileReconciler(
        config,
        node_store,
        event_store,
        workspace_service,
        project_root=tmp_path,
    )
    await restart_reconciler.reconcile_cycle()

    test_event = NodeChangedEvent(node_id=".", old_hash="x", new_hash="y", file_path="src/app.py")
    matched = await event_store.subscriptions.get_matching_agents(test_event)
    assert "." in matched


@pytest.mark.asyncio
async def test_directory_bundles_refreshed_on_startup(reconcile_env, tmp_path: Path) -> None:
    node_store, event_store, workspace_service, config, reconciler = reconcile_env
    write_file(tmp_path / "src" / "app.py", "def a():\n    return 1\n")
    await reconciler.full_scan()

    root_workspace = await workspace_service.get_agent_workspace(".")
    await root_workspace.write("_bundle/tools/send_message.pym", "result = 'stale'\nresult\n")

    system_tool = tmp_path / "bundles" / "system" / "tools" / "send_message.pym"
    system_tool.write_text("result = 'fresh'\nresult\n", encoding="utf-8")

    restart_reconciler = FileReconciler(
        config,
        node_store,
        event_store,
        workspace_service,
        project_root=tmp_path,
    )
    await restart_reconciler.reconcile_cycle()

    refreshed = await root_workspace.read("_bundle/tools/send_message.pym")
    assert "fresh" in refreshed
