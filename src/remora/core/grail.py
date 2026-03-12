"""Grail tool loading and execution helpers."""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import Any

import grail
from fsdantic import FileNotFoundError as FsdFileNotFoundError
from structured_agents.types import ToolCall, ToolResult, ToolSchema

from remora.core.workspace import AgentWorkspace

logger = logging.getLogger(__name__)

_TYPE_MAP = {
    "str": "string",
    "int": "integer",
    "float": "number",
    "bool": "boolean",
}


def _build_parameters(script: grail.GrailScript) -> dict[str, Any]:
    """Build JSON Schema parameters from Grail input declarations."""
    properties: dict[str, Any] = {}
    required: list[str] = []

    for name, spec in script.inputs.items():
        schema_type = _TYPE_MAP.get(spec.type_annotation, "string")
        properties[name] = {"type": schema_type}
        if spec.required:
            required.append(name)

    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _load_script_from_source(source: str, name: str) -> grail.GrailScript:
    filename = f"{name}.pym" if not name.endswith(".pym") else name
    with tempfile.TemporaryDirectory(prefix="remora-grail-") as temp_dir:
        script_path = Path(temp_dir) / filename
        script_path.write_text(source, encoding="utf-8")
        return grail.load(script_path)


class GrailTool:
    """A structured-agents tool wrapper around a GrailScript."""

    def __init__(
        self,
        script: grail.GrailScript,
        *,
        externals: dict[str, Any],
        name_override: str | None = None,
    ):
        self._script = script
        self._externals = externals
        self._schema = ToolSchema(
            name=name_override or script.name,
            description=f"Tool: {script.name}",
            parameters=_build_parameters(script),
        )

    @property
    def schema(self) -> ToolSchema:
        return self._schema

    async def execute(self, arguments: dict[str, Any], context: ToolCall | None) -> ToolResult:
        call_id = context.id if context else ""
        try:
            used_externals = {
                name: fn
                for name, fn in self._externals.items()
                if name in self._script.externals
            }
            result = await self._script.run(inputs=arguments, externals=used_externals)
            output = result if isinstance(result, str) else json.dumps(result)
            return ToolResult(
                call_id=call_id,
                name=self._schema.name,
                output=output,
                is_error=False,
            )
        except Exception as exc:  # noqa: BLE001 - tool boundary must return errors
            return ToolResult(
                call_id=call_id,
                name=self._schema.name,
                output=str(exc),
                is_error=True,
            )


async def discover_tools(
    workspace: AgentWorkspace,
    externals: dict[str, Any],
) -> list[GrailTool]:
    """Discover .pym tools under _bundle/tools in an agent workspace."""
    try:
        tool_files = await workspace.list_dir("_bundle/tools")
    except (FileNotFoundError, FsdFileNotFoundError):
        return []

    tools: list[GrailTool] = []
    for filename in tool_files:
        if not filename.endswith(".pym"):
            continue
        try:
            source = await workspace.read(f"_bundle/tools/{filename}")
            script = _load_script_from_source(source, filename.removesuffix(".pym"))
            tools.append(GrailTool(script=script, externals=externals))
        except Exception as exc:  # noqa: BLE001 - skip invalid tool and continue
            logger.warning("Failed to load tool %s: %s", filename, exc)

    return tools


__all__ = ["GrailTool", "discover_tools"]
