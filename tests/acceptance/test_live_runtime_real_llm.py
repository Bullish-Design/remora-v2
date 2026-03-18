from __future__ import annotations

import asyncio
import contextlib
import json
import os
import socket
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from tests.factories import write_file

from remora.__main__ import _configure_file_logging
from remora.core.model.config import load_config
from remora.core.services.lifecycle import RemoraLifecycle

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
            "query_search_paths:\n"
            "  - \"@default\"\n"
            "workspace_root: .remora-acceptance\n"
            "bundle_search_paths:\n"
            f"  - {bundles_root}\n"
            "  - \"@default\"\n"
            f"model_base_url: {model_url}\n"
            f"model_default: {model_name}\n"
            f"model_api_key: {model_api_key}\n"
            "timeout_s: 60\n"
            "max_turns: 8\n"
        ),
        encoding="utf-8",
    )
    return RuntimeProject(config_path=config_path, source_path=source_path)


def _write_proposal_project(
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
            "  If the user asks for rewrite_to_magic, call rewrite_to_magic exactly once,\n"
            "  then respond in one sentence.\n"
            f"model: {model_name}\n"
            "max_turns: 8\n"
        ),
    )
    write_file(code / "bundle.yaml", f"name: code-agent\nmodel: {model_name}\nmax_turns: 8\n")
    write_file(
        code / "tools" / "rewrite_to_magic.pym",
        (
            "from grail import external\n\n"
            "@external\n"
            "async def write_file(path: str, content: str) -> bool: ...\n"
            "@external\n"
            "async def propose_changes(reason: str = '') -> str: ...\n"
            "@external\n"
            "async def my_node_id() -> str: ...\n\n"
            "node_id = await my_node_id()\n"
            "await write_file(f\"source/{node_id}\", \"def alpha():\\n    return 99\\n\")\n"
            "proposal_id = await propose_changes(\"acceptance rewrite\")\n"
            "proposal_id\n"
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
            "query_search_paths:\n"
            "  - \"@default\"\n"
            "workspace_root: .remora-acceptance\n"
            "bundle_search_paths:\n"
            f"  - {bundles_root}\n"
            "  - \"@default\"\n"
            f"model_base_url: {model_url}\n"
            f"model_default: {model_name}\n"
            f"model_api_key: {model_api_key}\n"
            "timeout_s: 60\n"
            "max_turns: 8\n"
        ),
        encoding="utf-8",
    )
    return RuntimeProject(config_path=config_path, source_path=source_path)


def _write_reactive_mode_project(
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
    directory = bundles_root / "directory-agent"
    (system / "tools").mkdir(parents=True, exist_ok=True)
    (code / "tools").mkdir(parents=True, exist_ok=True)
    (directory / "tools").mkdir(parents=True, exist_ok=True)

    write_file(
        system / "bundle.yaml",
        (
            "name: system\n"
            "system_prompt: >-\n"
            "  You are a deterministic acceptance-test agent.\n"
            "  If the user asks for rewrite_to_magic, call rewrite_to_magic exactly once,\n"
            "  then reply in one sentence.\n"
            "  For reactive (non-user) turns, you MUST call emit_mode_token exactly once,\n"
            "  then reply in one sentence.\n"
            f"model: {model_name}\n"
            "max_turns: 8\n"
            "prompts:\n"
            "  chat: |\n"
            "    MODE_TOKEN=chat-ok\n"
            "  reactive: |\n"
            "    MODE_TOKEN=reactive-ok\n"
        ),
    )
    write_file(code / "bundle.yaml", f"name: code-agent\nmodel: {model_name}\nmax_turns: 8\n")
    write_file(
        directory / "bundle.yaml",
        f"name: directory-agent\nmodel: {model_name}\nmax_turns: 8\n",
    )
    write_file(
        system / "tools" / "emit_mode_token.pym",
        (
            "from grail import external\n\n"
            "@external\n"
            "async def my_node_id() -> str: ...\n"
            "@external\n"
            "async def send_message(to_node_id: str, content: str) -> bool: ...\n\n"
            "node_id = await my_node_id()\n"
            "ok = await send_message(node_id, \"reactive-ok\")\n"
            "result = \"reactive-ok\" if ok else \"failed\"\n"
            "result\n"
        ),
    )
    write_file(
        code / "tools" / "rewrite_to_magic.pym",
        (
            "from grail import external\n\n"
            "@external\n"
            "async def write_file(path: str, content: str) -> bool: ...\n"
            "@external\n"
            "async def propose_changes(reason: str = '') -> str: ...\n\n"
            "await write_file(\"source/src/app.py\", \"def alpha():\\n    return 3\\n\")\n"
            "proposal_id = await propose_changes(\"reactive acceptance rewrite\")\n"
            "proposal_id\n"
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
            "query_search_paths:\n"
            "  - \"@default\"\n"
            "workspace_root: .remora-acceptance\n"
            "bundle_search_paths:\n"
            f"  - {bundles_root}\n"
            "  - \"@default\"\n"
            f"model_base_url: {model_url}\n"
            f"model_default: {model_name}\n"
            f"model_api_key: {model_api_key}\n"
            "timeout_s: 60\n"
            "max_turns: 8\n"
        ),
        encoding="utf-8",
    )
    return RuntimeProject(config_path=config_path, source_path=source_path)


def _write_lsp_smoke_project(root: Path) -> RuntimeProject:
    source_path = root / "src" / "app.py"
    write_file(source_path, "def alpha():\n    return 1\n")

    bundles_root = root / "bundles"
    system = bundles_root / "system"
    code = bundles_root / "code-agent"
    (system / "tools").mkdir(parents=True, exist_ok=True)
    (code / "tools").mkdir(parents=True, exist_ok=True)
    write_file(system / "bundle.yaml", "name: system\nmax_turns: 4\n")
    write_file(code / "bundle.yaml", "name: code-agent\nmax_turns: 4\n")

    config_path = root / "remora.yaml"
    config_path.write_text(
        (
            "discovery_paths:\n"
            "  - src\n"
            "discovery_languages:\n"
            "  - python\n"
            "language_map:\n"
            "  .py: python\n"
            "query_search_paths:\n"
            "  - \"@default\"\n"
            "workspace_root: .remora-acceptance\n"
            "bundle_search_paths:\n"
            f"  - {bundles_root}\n"
            "  - \"@default\"\n"
            "max_turns: 4\n"
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
    last_events: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        last_events = await _fetch_events(client)
        for event in last_events:
            if predicate(event):
                return event
        await asyncio.sleep(0.2)
    recent = [
        (
            event.get("event_type"),
            event.get("correlation_id"),
            event.get("payload", {}).get("agent_id"),
            event.get("payload", {}).get("from_agent"),
            event.get("payload", {}).get("to_agent"),
            event.get("payload", {}).get("content"),
        )
        for event in last_events[:20]
    ]
    raise AssertionError(
        f"Timed out waiting for matching event after {timeout_s}s; recent_events={recent}"
    )


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


async def _wait_for_directory_node_id(client: httpx.AsyncClient) -> str:
    deadline = time.monotonic() + _EVENT_TIMEOUT_S
    while time.monotonic() < deadline:
        response = await client.get("/api/nodes")
        assert response.status_code == 200
        nodes = response.json()
        assert isinstance(nodes, list)
        for node in nodes:
            if node.get("node_type") == "directory":
                node_id = str(node.get("node_id", "")).strip()
                if node_id == ".":
                    return node_id
        await asyncio.sleep(0.2)
    raise AssertionError("Timed out waiting for root directory node")


async def _wait_for_pending_proposal(
    client: httpx.AsyncClient,
    *,
    node_id: str,
    timeout_s: float = _EVENT_TIMEOUT_S,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        response = await client.get("/api/proposals")
        assert response.status_code == 200
        payload = response.json()
        assert isinstance(payload, list)
        for proposal in payload:
            if proposal.get("node_id") == node_id and proposal.get("proposal_id"):
                return proposal
        await asyncio.sleep(0.2)
    raise AssertionError(f"Timed out waiting for pending proposal on node {node_id}")


def _encode_lsp_message(payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


async def _read_lsp_message(
    stream: asyncio.StreamReader,
    *,
    timeout_s: float = 10.0,
) -> dict[str, Any]:
    headers: dict[str, str] = {}
    while True:
        line = await asyncio.wait_for(stream.readline(), timeout=timeout_s)
        if not line:
            raise AssertionError("LSP process closed stdout before header terminator")
        if line in {b"\r\n", b"\n"}:
            break
        decoded = line.decode("ascii", errors="replace").strip()
        if ":" in decoded:
            key, value = decoded.split(":", maxsplit=1)
            headers[key.strip().lower()] = value.strip()
    content_length = int(headers.get("content-length", "0"))
    if content_length <= 0:
        raise AssertionError(f"Invalid LSP Content-Length header: {headers!r}")
    body = await asyncio.wait_for(stream.readexactly(content_length), timeout=timeout_s)
    return json.loads(body.decode("utf-8"))


@contextlib.asynccontextmanager
async def _running_lsp_process(project_root: Path, *, config_path: Path):
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "remora",
        "lsp",
        "--project-root",
        str(project_root),
        "--config",
        str(config_path),
        "--log-level",
        "INFO",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        if process.stdin is None or process.stdout is None:
            raise AssertionError("LSP subprocess missing stdio pipes")
        yield process
    finally:
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=10.0)
            except TimeoutError:
                process.kill()
                await process.wait()


async def _initialize_lsp(process: asyncio.subprocess.Process) -> None:
    if process.stdin is None or process.stdout is None:
        raise AssertionError("LSP subprocess missing stdio pipes")

    init_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "processId": None,
            "rootUri": None,
            "capabilities": {},
        },
    }
    process.stdin.write(_encode_lsp_message(init_request))
    await process.stdin.drain()

    init_response = await _read_lsp_message(process.stdout, timeout_s=45.0)
    assert init_response.get("id") == 1
    assert "result" in init_response

    initialized = {"jsonrpc": "2.0", "method": "initialized", "params": {}}
    process.stdin.write(_encode_lsp_message(initialized))
    await process.stdin.drain()


async def _send_lsp_notification(
    process: asyncio.subprocess.Process,
    *,
    method: str,
    params: dict[str, Any],
) -> None:
    if process.stdin is None:
        raise AssertionError("LSP subprocess missing stdin pipe")
    payload = {"jsonrpc": "2.0", "method": method, "params": params}
    process.stdin.write(_encode_lsp_message(payload))
    await process.stdin.drain()


@contextlib.asynccontextmanager
async def _running_runtime(*, project_root: Path, config_path: Path, port: int):
    config = load_config(config_path)
    lifecycle = RemoraLifecycle(
        config=config,
        project_root=project_root,
        bind="127.0.0.1",
        port=port,
        no_web=False,
        log_events=False,
        lsp=False,
        configure_file_logging=_configure_file_logging,
    )
    base_url = f"http://127.0.0.1:{port}"
    started = False
    await lifecycle.start()
    started = True
    await _wait_for_health(base_url)
    try:
        yield base_url
    finally:
        if started:
            await asyncio.wait_for(lifecycle.shutdown(), timeout=20.0)


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
                    event.get("event_type") == "agent_message"
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
                    event.get("event_type") == "agent_complete"
                    and event.get("correlation_id") == correlation_id
                ),
            )
            events = await _fetch_events(client)
            errors = [
                event
                for event in events
                if event.get("event_type") == "agent_error"
                and event.get("correlation_id") == correlation_id
            ]
            assert errors == []


@pytest.mark.asyncio
@pytest.mark.acceptance
async def test_acceptance_process_lsp_open_save_emits_content_changed_event(
    tmp_path: Path,
) -> None:
    runtime_project = _write_lsp_smoke_project(tmp_path)
    port = _reserve_port()

    async with _running_runtime(
        project_root=tmp_path,
        config_path=runtime_project.config_path,
        port=port,
    ) as base_url:
        async with _running_lsp_process(
            tmp_path,
            config_path=runtime_project.config_path,
        ) as lsp_process:
            await _initialize_lsp(lsp_process)
            file_uri = runtime_project.source_path.resolve().as_uri()

            await _send_lsp_notification(
                lsp_process,
                method="textDocument/didOpen",
                params={
                    "textDocument": {
                        "uri": file_uri,
                        "languageId": "python",
                        "version": 1,
                        "text": runtime_project.source_path.read_text(encoding="utf-8"),
                    }
                },
            )
            await _send_lsp_notification(
                lsp_process,
                method="textDocument/didSave",
                params={"textDocument": {"uri": file_uri}},
            )

            async with httpx.AsyncClient(base_url=base_url, timeout=5.0) as client:
                await _wait_for_event(
                    client,
                    lambda event: (
                        event.get("event_type") == "content_changed"
                        and event.get("payload", {}).get("path")
                        == str(runtime_project.source_path.resolve())
                        and event.get("payload", {}).get("change_type") == "modified"
                    ),
                    timeout_s=30.0,
                )


@pytest.mark.asyncio
@pytest.mark.acceptance
@pytest.mark.real_llm
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_acceptance_proposal_flow_generates_diff_and_accept_materializes_file(
    tmp_path: Path,
) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")

    runtime_project = _write_proposal_project(
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

            response = await client.post(
                "/api/chat",
                json={
                    "node_id": node_id,
                    "message": "Call rewrite_to_magic exactly once, then confirm completion.",
                },
            )
            assert response.status_code == 200

            proposal = await _wait_for_pending_proposal(client, node_id=node_id)
            proposal_id = str(proposal["proposal_id"])

            diff_response = await client.get(f"/api/proposals/{node_id}/diff")
            assert diff_response.status_code == 200
            diff_payload = diff_response.json()
            assert diff_payload["proposal_id"] == proposal_id
            assert diff_payload["diffs"]
            assert diff_payload["diffs"][0]["new"] == "def alpha():\n    return 99\n"

            accept_response = await client.post(f"/api/proposals/{node_id}/accept", json={})
            assert accept_response.status_code == 200
            accept_payload = accept_response.json()
            assert accept_payload["status"] == "accepted"
            assert accept_payload["proposal_id"] == proposal_id
            materialized_files = accept_payload.get("files", [])
            assert isinstance(materialized_files, list)
            assert materialized_files
            materialized_path = Path(str(materialized_files[0]))
            assert materialized_path.read_text(encoding="utf-8") == "def alpha():\n    return 99\n"

            await _wait_for_event(
                client,
                lambda event: (
                    event.get("event_type") == "rewrite_accepted"
                    and event.get("payload", {}).get("proposal_id") == proposal_id
                ),
            )
            await _wait_for_event(
                client,
                lambda event: (
                    event.get("event_type") == "content_changed"
                    and event.get("payload", {}).get("path") == str(materialized_path)
                ),
            )


@pytest.mark.asyncio
@pytest.mark.acceptance
@pytest.mark.real_llm
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_acceptance_reactive_file_change_triggers_live_real_llm_turn(
    tmp_path: Path,
) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")

    runtime_project = _write_reactive_mode_project(
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
            function_node_id = await _wait_for_function_node_id(client)
            directory_node_id = await _wait_for_directory_node_id(client)
            chat_response = await client.post(
                "/api/chat",
                json={
                    "node_id": function_node_id,
                    "message": "Call rewrite_to_magic exactly once, then confirm completion.",
                },
            )
            assert chat_response.status_code == 200
            await _wait_for_pending_proposal(client, node_id=function_node_id)
            accept_response = await client.post(f"/api/proposals/{function_node_id}/accept", json={})
            assert accept_response.status_code == 200

            message_event = await _wait_for_event(
                client,
                lambda event: (
                    event.get("event_type") == "agent_message"
                    and event.get("payload", {}).get("from_agent") == directory_node_id
                    and event.get("payload", {}).get("to_agent") == directory_node_id
                    and event.get("payload", {}).get("content") == "reactive-ok"
                ),
            )
            correlation_id = str(message_event.get("correlation_id") or "").strip()
            assert correlation_id

            await _wait_for_event(
                client,
                lambda event: (
                    event.get("event_type") == "agent_complete"
                    and event.get("correlation_id") == correlation_id
                ),
            )
            events = await _fetch_events(client)
            errors = [
                event
                for event in events
                if event.get("event_type") == "agent_error"
                and event.get("correlation_id") == correlation_id
            ]
            assert errors == []
