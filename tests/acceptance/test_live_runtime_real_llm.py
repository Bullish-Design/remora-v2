from __future__ import annotations

import asyncio
import contextlib
import os
import socket
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from tests.factories import write_file

from remora.__main__ import _start

DEFAULT_TEST_MODEL_NAME = "Qwen/Qwen3-4B-Instruct-2507-FP8"
_REAL_LLM_ENV_MISSING = not os.getenv("REMORA_TEST_MODEL_URL")
_REAL_LLM_SKIP_REASON = "REMORA_TEST_MODEL_URL not set - skipping real LLM acceptance test"
_READINESS_TIMEOUT_S = float(os.getenv("REMORA_ACCEPTANCE_READY_TIMEOUT_S", "20"))
_EVENT_TIMEOUT_S = float(os.getenv("REMORA_ACCEPTANCE_EVENT_TIMEOUT_S", "90"))


@dataclass(frozen=True)
class RuntimeProject:
    config_path: Path
    source_path: Path


def _reserve_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _write_send_message_project(
    root: Path,
    *,
    model_url: str,
    model_name: str,
    model_api_key: str,
) -> RuntimeProject:
    source_path = root / "src" / "app.py"
    write_file(source_path, "def alpha():\n    return 1\n")

    bundles_root = root / "bundles"
    system = bundles_root / "system"
    code = bundles_root / "code-agent"
    (system / "tools").mkdir(parents=True, exist_ok=True)
    (code / "tools").mkdir(parents=True, exist_ok=True)

    write_file(
        system / "bundle.yaml",
        (
            "name: system\n"
            "system_prompt: >-\n"
            "  You are a deterministic acceptance-test agent.\n"
            "  For user requests, call send_message exactly once with the provided\n"
            "  to_node_id and content, then reply in one sentence.\n"
            f"model: {model_name}\n"
            "max_turns: 8\n"
        ),
    )
    write_file(code / "bundle.yaml", f"name: code-agent\nmodel: {model_name}\nmax_turns: 8\n")
    write_file(
        system / "tools" / "send_message.pym",
        (
            "from grail import Input, external\n\n"
            'to_node_id: str = Input("to_node_id")\n'
            'content: str = Input("content")\n\n'
            "@external\n"
            "async def send_message(to_node_id: str, content: str) -> bool: ...\n\n"
            "ok = await send_message(to_node_id, content)\n"
            "result = \"sent\" if ok else \"failed\"\n"
            "result\n"
        ),
    )

    config_path = root / "remora.yaml"
    config_path.write_text(
        (
            "discovery_paths:\n"
            "  - src\n"
            "discovery_languages:\n"
            "  - python\n"
            "language_map:\n"
            "  .py: python\n"
            "query_paths: []\n"
            "workspace_root: .remora-acceptance\n"
            "bundle_root: bundles\n"
            f"model_base_url: {model_url}\n"
            f"model_default: {model_name}\n"
            f"model_api_key: {model_api_key}\n"
            "timeout_s: 60\n"
            "max_turns: 8\n"
        ),
        encoding="utf-8",
    )
    return RuntimeProject(config_path=config_path, source_path=source_path)


async def _wait_for_health(base_url: str, timeout_s: float = _READINESS_TIMEOUT_S) -> None:
    deadline = time.monotonic() + timeout_s
    async with httpx.AsyncClient(base_url=base_url, timeout=2.0) as client:
        while time.monotonic() < deadline:
            try:
                response = await client.get("/api/health")
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.1)
    raise AssertionError(f"Runtime at {base_url} did not become healthy within {timeout_s}s")


async def _fetch_events(client: httpx.AsyncClient, limit: int = 500) -> list[dict[str, Any]]:
    response = await client.get(f"/api/events?limit={limit}")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    return payload


async def _wait_for_event(
    client: httpx.AsyncClient,
    predicate: Callable[[dict[str, Any]], bool],
    *,
    timeout_s: float = _EVENT_TIMEOUT_S,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        for event in await _fetch_events(client):
            if predicate(event):
                return event
        await asyncio.sleep(0.2)
    raise AssertionError(f"Timed out waiting for matching event after {timeout_s}s")


async def _wait_for_function_node_id(client: httpx.AsyncClient) -> str:
    deadline = time.monotonic() + _EVENT_TIMEOUT_S
    while time.monotonic() < deadline:
        response = await client.get("/api/nodes")
        assert response.status_code == 200
        nodes = response.json()
        assert isinstance(nodes, list)
        for node in nodes:
            if node.get("node_type") == "function":
                node_id = str(node.get("node_id", "")).strip()
                if node_id:
                    return node_id
        await asyncio.sleep(0.2)
    raise AssertionError("Timed out waiting for discovered function node")


@contextlib.asynccontextmanager
async def _running_runtime(*, project_root: Path, config_path: Path, port: int):
    task = asyncio.create_task(
        _start(
            project_root=project_root,
            config_path=config_path,
            port=port,
            no_web=False,
            bind="127.0.0.1",
            run_seconds=0.0,
            log_events=False,
            lsp=False,
        ),
        name="acceptance-runtime",
    )
    base_url = f"http://127.0.0.1:{port}"
    await _wait_for_health(base_url)
    try:
        yield base_url
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=15.0)


@pytest.mark.asyncio
@pytest.mark.acceptance
@pytest.mark.real_llm
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_acceptance_live_web_chat_routes_through_dispatcher_actorpool_and_real_llm(
    tmp_path: Path,
) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")

    runtime_project = _write_send_message_project(
        tmp_path,
        model_url=model_url,
        model_name=model_name,
        model_api_key=model_api_key,
    )
    port = _reserve_port()

    async with _running_runtime(
        project_root=tmp_path,
        config_path=runtime_project.config_path,
        port=port,
    ) as base_url:
        async with httpx.AsyncClient(base_url=base_url, timeout=5.0) as client:
            node_id = await _wait_for_function_node_id(client)
            token = f"acceptance-chat-{uuid.uuid4().hex[:10]}"

            response = await client.post(
                "/api/chat",
                json={
                    "node_id": node_id,
                    "message": (
                        "Call send_message exactly once with "
                        f"to_node_id='{node_id}' and content='{token}'. "
                        "Then reply in one short sentence."
                    ),
                },
            )
            assert response.status_code == 200

            message_event = await _wait_for_event(
                client,
                lambda event: (
                    event.get("event_type") == "AgentMessageEvent"
                    and event.get("payload", {}).get("from_agent") == node_id
                    and event.get("payload", {}).get("to_agent") == node_id
                    and event.get("payload", {}).get("content") == token
                ),
            )
            correlation_id = str(message_event.get("correlation_id") or "").strip()
            assert correlation_id

            await _wait_for_event(
                client,
                lambda event: (
                    event.get("event_type") == "AgentCompleteEvent"
                    and event.get("correlation_id") == correlation_id
                ),
            )
            events = await _fetch_events(client)
            errors = [
                event
                for event in events
                if event.get("event_type") == "AgentErrorEvent"
                and event.get("correlation_id") == correlation_id
            ]
            assert errors == []
