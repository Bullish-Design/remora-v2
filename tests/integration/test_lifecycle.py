from __future__ import annotations

import asyncio
import socket
from pathlib import Path

import httpx
import pytest
from tests.factories import write_file

from remora.core.config import Config
from remora.core.lifecycle import RemoraLifecycle


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.mark.asyncio
async def test_lifecycle_discovers_nodes_serves_health_and_shuts_down(tmp_path: Path) -> None:
    write_file(tmp_path / "src" / "app.py", "def a():\n    return 1\n")
    port = _free_port()
    config = Config(
        discovery_paths=("src",),
        discovery_languages=("python",),
        language_map={".py": "python"},
        query_search_paths=("@default",),
        workspace_root=".remora-lifecycle-test",
    )
    lifecycle = RemoraLifecycle(
        config=config,
        project_root=tmp_path,
        bind="127.0.0.1",
        port=port,
        no_web=False,
        log_events=False,
        lsp=False,
        configure_file_logging=lambda _path: None,
    )

    try:
        await lifecycle.start()
        services = lifecycle._services  # noqa: SLF001
        assert services is not None

        nodes = await services.node_store.list_nodes()
        assert nodes
        assert any(node.node_id.endswith("::a") for node in nodes)

        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=0.5) as client:
            deadline = asyncio.get_running_loop().time() + 5.0
            response: httpx.Response | None = None
            while asyncio.get_running_loop().time() < deadline:
                try:
                    response = await client.get("/api/health")
                    if response.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.05)
            assert response is not None
            assert response.status_code == 200
            assert response.json().get("status") == "ok"

        await lifecycle.run(run_seconds=2.0)
    finally:
        await lifecycle.shutdown()

    leaked_remora_tasks = [
        task
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task()
        and not task.done()
        and task.get_name().startswith("remora-")
    ]
    assert leaked_remora_tasks == []
