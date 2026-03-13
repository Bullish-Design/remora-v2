from __future__ import annotations

import json
import logging
from pathlib import Path

import grail
import pytest
from structured_agents.types import ToolCall

from remora.core.grail import GrailTool, _build_parameters, _load_script_from_source, discover_tools

SCRIPT_SOURCE = """
from grail import Input, external

name: str = Input("name")
count: int = Input("count", default=1)

@external
async def echo(text: str) -> str: ...

result = await echo(name)
return {"value": result, "count": count}
""".strip()


def _load_script(tmp_path: Path, filename: str = "demo.pym") -> grail.GrailScript:
    path = tmp_path / filename
    path.write_text(SCRIPT_SOURCE, encoding="utf-8")
    return grail.load(path)


class _WorkspaceStub:
    def __init__(self, files: dict[str, str], *, missing_tools_dir: bool = False):
        self._files = files
        self._missing_tools_dir = missing_tools_dir

    async def list_dir(self, path: str = ".") -> list[str]:
        if self._missing_tools_dir:
            raise FileNotFoundError(path)
        prefix = f"{path.rstrip('/')}/"
        names = []
        for full_path in self._files:
            if full_path.startswith(prefix):
                suffix = full_path[len(prefix) :]
                if "/" not in suffix:
                    names.append(suffix)
        return sorted(names)

    async def read(self, path: str) -> str:
        return self._files[path]


def test_build_parameters(tmp_path: Path) -> None:
    script = _load_script(tmp_path)
    schema = _build_parameters(script)
    assert schema["type"] == "object"
    assert schema["properties"]["name"]["type"] == "string"
    assert schema["properties"]["count"]["type"] == "integer"
    assert schema["required"] == ["name"]


def test_grail_tool_schema(tmp_path: Path) -> None:
    script = _load_script(tmp_path)
    tool = GrailTool(script=script, externals={"echo": lambda _: "ok"})
    assert tool.schema.name == "demo"
    assert tool.schema.parameters["properties"]["name"]["type"] == "string"


@pytest.mark.asyncio
async def test_grail_tool_execute(tmp_path: Path) -> None:
    _ = _load_script(tmp_path)

    class ScriptStub:
        name = "demo"
        inputs = {}
        externals = {"echo": object()}

        async def run(self, inputs, externals):  # noqa: ANN001, ANN201
            echoed = await externals["echo"](inputs["name"])
            return {"value": echoed, "count": inputs["count"]}

    async def echo(text: str) -> str:
        return f"echo:{text}"

    tool = GrailTool(script=ScriptStub(), externals={"echo": echo, "unused": echo})
    result = await tool.execute(
        {"name": "remora", "count": 2},
        ToolCall(id="call-1", name="demo", arguments={"name": "remora"}),
    )

    payload = json.loads(result.output)
    assert result.is_error is False
    assert result.call_id == "call-1"
    assert payload == {"value": "echo:remora", "count": 2}


@pytest.mark.asyncio
async def test_grail_tool_error_handling(tmp_path: Path) -> None:
    _ = _load_script(tmp_path)

    class ScriptStub:
        name = "demo"
        inputs = {}
        externals = {"echo": object()}

        async def run(self, inputs, externals):  # noqa: ANN001, ANN201
            return await externals["echo"](inputs["name"])

    async def fail(_: str) -> str:
        raise RuntimeError("boom")

    tool = GrailTool(script=ScriptStub(), externals={"echo": fail})
    result = await tool.execute({"name": "x"}, ToolCall(id="call-2", name="demo", arguments={}))
    assert result.is_error is True
    assert "boom" in result.output


@pytest.mark.asyncio
async def test_discover_tools_from_workspace() -> None:
    workspace = _WorkspaceStub(
        {
            "_bundle/tools/demo.pym": SCRIPT_SOURCE,
            "_bundle/tools/ignore.txt": "x",
        }
    )

    async def echo(text: str) -> str:
        return text

    tools = await discover_tools(workspace, externals={"echo": echo})
    assert len(tools) == 1
    assert tools[0].schema.name == "demo"


@pytest.mark.asyncio
async def test_discover_tools_empty() -> None:
    workspace = _WorkspaceStub({}, missing_tools_dir=True)
    tools = await discover_tools(workspace, externals={})
    assert tools == []


def test_load_script_from_source_uses_cache() -> None:
    first = _load_script_from_source(SCRIPT_SOURCE, "demo")
    second = _load_script_from_source(SCRIPT_SOURCE, "demo")
    assert first is second


@pytest.mark.asyncio
async def test_discover_tools_logs_load_failure(caplog) -> None:
    workspace = _WorkspaceStub({"_bundle/tools/bad.pym": "def broken(:\n"})

    with caplog.at_level(logging.INFO, logger="remora.core.grail"):
        tools = await discover_tools(workspace, externals={})

    assert tools == []
    messages = [record.getMessage() for record in caplog.records]
    assert any("Failed to load tool bad.pym" in message for message in messages)
    assert any("Loaded 0 Grail tool(s)" in message for message in messages)


@pytest.mark.asyncio
async def test_grail_tool_execute_logs_start_and_failure(tmp_path: Path, caplog) -> None:
    _ = _load_script(tmp_path)

    class ScriptStub:
        name = "demo"
        inputs = {}
        externals = {"echo": object()}

        async def run(self, inputs, externals):  # noqa: ANN001, ANN201
            return await externals["echo"](inputs["name"])

    async def fail(_: str) -> str:
        raise RuntimeError("boom")

    tool = GrailTool(script=ScriptStub(), externals={"echo": fail}, agent_id="node-x")
    with caplog.at_level(logging.INFO, logger="remora.core.grail"):
        result = await tool.execute({"name": "x"}, ToolCall(id="call-3", name="demo", arguments={}))

    assert result.is_error is True
    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "Tool start agent=node-x tool=demo call_id=call-3" in message for message in messages
    )
    assert any(
        "Tool failed agent=node-x tool=demo call_id=call-3" in message for message in messages
    )
