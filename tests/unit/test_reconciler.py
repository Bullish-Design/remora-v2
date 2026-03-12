from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest
import pytest_asyncio

import remora.code.reconciler as reconciler_module
from remora.code.reconciler import FileReconciler
from remora.core.config import Config
from remora.core.events import EventStore
from remora.core.graph import NodeStore
from remora.core.workspace import CairnWorkspaceService


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_bundle_templates(root: Path) -> None:
    system = root / "system"
    code_bundle = root / "code-agent"
    (system / "tools").mkdir(parents=True, exist_ok=True)
    (code_bundle / "tools").mkdir(parents=True, exist_ok=True)

    (system / "bundle.yaml").write_text("name: system\nmax_turns: 4\n", encoding="utf-8")
    (code_bundle / "bundle.yaml").write_text("name: code-agent\nmax_turns: 8\n", encoding="utf-8")
    (system / "tools" / "send_message.pym").write_text("return 'ok'\n", encoding="utf-8")
    (code_bundle / "tools" / "rewrite_self.pym").write_text("return 'ok'\n", encoding="utf-8")


@pytest_asyncio.fixture
async def reconcile_env(tmp_path: Path):
    conn = sqlite3.connect(str(tmp_path / "reconcile.db"), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    lock = asyncio.Lock()

    node_store = NodeStore(conn, lock)
    await node_store.create_tables()
    event_store = EventStore(connection=conn, lock=lock)
    await event_store.initialize()

    bundles_root = tmp_path / "bundles"
    _write_bundle_templates(bundles_root)

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
        event_store,
        workspace_service,
        project_root=tmp_path,
    )

    yield node_store, event_store, workspace_service, config, reconciler

    await workspace_service.close()
    conn.close()


@pytest.mark.asyncio
async def test_full_scan_discovers_registers_and_emits(reconcile_env, tmp_path: Path) -> None:
    node_store, event_store, _workspace_service, _config, reconciler = reconcile_env
    _write(tmp_path / "src" / "app.py", "def a():\n    return 1\n")

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
    _node_store, _event_store, _workspace_service, _config, reconciler = reconcile_env
    first = tmp_path / "src" / "first.py"
    second = tmp_path / "src" / "second.py"
    _write(first, "def first():\n    return 1\n")
    _write(second, "def second():\n    return 2\n")
    await reconciler.full_scan()

    seen_files: list[Path] = []
    real_discover = reconciler_module.discover

    def wrapped_discover(paths, **kwargs):  # noqa: ANN001, ANN202
        seen_files.extend(paths)
        return real_discover(paths, **kwargs)

    monkeypatch.setattr(reconciler_module, "discover", wrapped_discover)

    _write(second, "def second():\n    return 3\n")
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
    _write(file_a, "def a():\n    return 1\n")
    await reconciler.full_scan()

    _write(file_b, "def b():\n    return 2\n")
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
    _node_store, event_store, _workspace_service, _config, reconciler = reconcile_env
    _write(tmp_path / "src" / "app.py", "def a():\n    return 1\n")
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
