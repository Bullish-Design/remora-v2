"""Grail tool loading and execution helpers."""

from __future__ import annotations

import hashlib
import json
import logging
import tempfile
import time
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

_SCRIPT_CACHE: dict[str, grail.GrailScript] = {}


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
    content_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
    cached = _SCRIPT_CACHE.get(content_hash)
    if cached is not None:
        return cached

    filename = f"{name}.pym" if not name.endswith(".pym") else name
    with tempfile.TemporaryDirectory(prefix="remora-grail-") as temp_dir:
        script_path = Path(temp_dir) / filename
        script_path.write_text(source, encoding="utf-8")
        script = grail.load(script_path)
    _SCRIPT_CACHE[content_hash] = script
    return script


class GrailTool:
    """A structured-agents tool wrapper around a GrailScript."""

    def __init__(
        self,
        script: grail.GrailScript,
        *,
        capabilities: dict[str, Any] | None = None,
        externals: dict[str, Any] | None = None,
        name_override: str | None = None,
        agent_id: str = "?",
        source_file: str | None = None,
    ):
        self._script = script
        self._capabilities = capabilities if capabilities is not None else (externals or {})
        self._agent_id = agent_id
        self._source_file = source_file or f"{script.name}.pym"
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
        started = time.perf_counter()
        logger.info(
            "Tool start agent=%s tool=%s call_id=%s source=%s args=%s",
            self._agent_id,
            self._schema.name,
            call_id or "-",
            self._source_file,
            arguments,
        )
        try:
            used_capabilities = {
                name: fn
                for name, fn in self._capabilities.items()
                if name in self._script.externals
            }
            result = await self._script.run(inputs=arguments, externals=used_capabilities)
            output = result if isinstance(result, str) else json.dumps(result)
            logger.info(
                "Tool complete agent=%s tool=%s call_id=%s duration_ms=%.1f output=%s",
                self._agent_id,
                self._schema.name,
                call_id or "-",
                (time.perf_counter() - started) * 1000.0,
                output,
            )
            return ToolResult(
                call_id=call_id,
                name=self._schema.name,
                output=output,
                is_error=False,
            )
        except Exception as exc:  # noqa: BLE001 - tool boundary must return errors
            logger.exception(
                "Tool failed agent=%s tool=%s call_id=%s duration_ms=%.1f source=%s args=%s",
                self._agent_id,
                self._schema.name,
                call_id or "-",
                (time.perf_counter() - started) * 1000.0,
                self._source_file,
                arguments,
            )
            return ToolResult(
                call_id=call_id,
                name=self._schema.name,
                output=str(exc),
                is_error=True,
            )


async def discover_tools(
    workspace: AgentWorkspace,
    capabilities: dict[str, Any] | None = None,
    externals: dict[str, Any] | None = None,
) -> list[GrailTool]:
    """Discover .pym tools under _bundle/tools in an agent workspace."""
    resolved_capabilities = capabilities if capabilities is not None else (externals or {})
    agent_id = str(getattr(workspace, "_agent_id", "?"))
    try:
        tool_files = await workspace.list_dir("_bundle/tools")
    except (FileNotFoundError, FsdFileNotFoundError):
        logger.info("No tools directory for agent=%s", agent_id)
        return []

    tools: list[GrailTool] = []
    for filename in tool_files:
        if not filename.endswith(".pym"):
            continue
        try:
            source = await workspace.read(f"_bundle/tools/{filename}")
            script = _load_script_from_source(source, filename.removesuffix(".pym"))
            tools.append(
                GrailTool(
                    script=script,
                    capabilities=resolved_capabilities,
                    agent_id=agent_id,
                    source_file=filename,
                )
            )
        except Exception:  # noqa: BLE001 - skip invalid tool and continue
            logger.exception("Failed to load tool %s for agent=%s", filename, agent_id)

    logger.info("Loaded %d Grail tool(s) for agent=%s", len(tools), agent_id)
    return tools


__all__ = ["GrailTool", "discover_tools"]
