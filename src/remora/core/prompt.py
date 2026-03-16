"""Prompt construction primitives for agent turns."""

from __future__ import annotations

from remora.core.config import BundleConfig, Config
from remora.core.events.types import Event
from remora.core.node import Node
from remora.core.types import NodeType, serialize_enum

_DEFAULT_REFLECTION_PROMPT = """\
You just completed a conversation turn. Reflect on the exchange and record metadata.

Use your companion tools:
- companion_summarize: Write a one-sentence summary and 1-3 tags
- companion_reflect: Record one key insight or observation
- companion_link: If you referenced another code element, record the link

Tag vocabulary: bug, question, refactor, explanation, test, performance, design, insight, todo, review

Be specific. Skip trivial exchanges."""


class PromptBuilder:
    """Build system/user prompts from bundle config, node state, and trigger context."""

    def __init__(self, config: Config) -> None:
        self._config = config

    def build_system_prompt(
        self,
        bundle_config: BundleConfig,
        trigger_event: Event | None,
    ) -> tuple[str, str, int]:
        self_reflect = bundle_config.self_reflect
        is_reflection = (
            self_reflect is not None
            and self_reflect.enabled
            and trigger_event is not None
            and trigger_event.event_type == "AgentCompleteEvent"
            and "primary" in getattr(trigger_event, "tags", ())
        )
        if is_reflection:
            reflection_prompt = self_reflect.prompt or _DEFAULT_REFLECTION_PROMPT
            model_name = self_reflect.model or bundle_config.model or self._config.model_default
            max_turns = self_reflect.max_turns
            return reflection_prompt, model_name, max_turns

        system_prompt = bundle_config.system_prompt
        prompt_extension = bundle_config.system_prompt_extension
        if prompt_extension:
            system_prompt = f"{system_prompt}\n\n{prompt_extension}"
        mode = self.turn_mode(trigger_event)
        mode_prompt = bundle_config.prompts.get(mode, "")
        if mode_prompt:
            system_prompt = f"{system_prompt}\n\n{mode_prompt}"
        model_name = bundle_config.model or self._config.model_default
        max_turns = bundle_config.max_turns
        return system_prompt, model_name, max_turns

    @staticmethod
    def build_prompt(node: Node, trigger_event: Event | None) -> str:
        """Build the turn prompt from node identity and trigger details."""
        node_type = serialize_enum(node.node_type)
        parts = [
            f"# Node: {node.full_name}",
            f"Type: {node_type} | File: {node.file_path}",
        ]
        if node.node_type == NodeType.VIRTUAL:
            parts.extend(
                [
                    "",
                    "## Role",
                    f"You are a {node.role or 'virtual'} agent.",
                    "Use your tools and incoming events to coordinate work.",
                ]
            )
        elif node.source_code:
            parts.extend(
                [
                    "",
                    "## Source Code",
                    "```",
                    node.source_code,
                    "```",
                ]
            )
        else:
            parts.extend(
                [
                    "",
                    "## Structure",
                    "This is a directory node. Use your tools to inspect children and subtree.",
                ]
            )
        if trigger_event is not None:
            parts.extend(["", "## Trigger", f"Event: {trigger_event.event_type}"])
            content = _event_content(trigger_event)
            if content:
                parts.append(f"Content: {content}")
        return "\n".join(parts)

    @staticmethod
    def turn_mode(event: Event | None) -> str:
        from_agent = getattr(event, "from_agent", None) if event is not None else None
        return "chat" if from_agent == "user" else "reactive"


def _event_content(event: Event) -> str:
    if hasattr(event, "content"):
        return str(event.content)
    return ""


__all__ = ["PromptBuilder"]
