"""Prompt construction primitives for agent turns."""

from __future__ import annotations

from remora.core.config import BundleConfig, Config
from remora.core.events.types import Event
from remora.core.node import Node
from remora.core.types import EventType, serialize_enum


class PromptBuilder:
    """Build system and user prompts from bundle config and templates."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._default_templates = dict(config.behavior.prompt_templates)

    def build_system_prompt(
        self,
        bundle_config: BundleConfig,
        trigger_event: Event | None,
    ) -> tuple[str, str, int]:
        if self._is_reflection_turn(bundle_config, trigger_event):
            return self._build_reflection(bundle_config)

        system_prompt = bundle_config.system_prompt
        prompt_extension = bundle_config.system_prompt_extension
        if prompt_extension:
            system_prompt = f"{system_prompt}\n\n{prompt_extension}"

        mode = self.turn_mode(trigger_event)
        mode_prompt = bundle_config.prompts.get(mode, "")
        if mode_prompt:
            system_prompt = f"{system_prompt}\n\n{mode_prompt}"

        model_name = bundle_config.model or self._config.behavior.model_default
        max_turns = bundle_config.max_turns
        return system_prompt, model_name, max_turns

    def build_user_prompt(
        self,
        node: Node,
        trigger_event: Event | None,
        *,
        bundle_config: BundleConfig | None = None,
        companion_context: str = "",
    ) -> str:
        """Build the user prompt from template interpolation."""
        variables = self._build_template_vars(node, trigger_event, companion_context)

        bundle_template = ""
        if bundle_config is not None:
            bundle_template = bundle_config.prompt_templates.get("user", "")

        template = bundle_template or self._default_templates.get("user", "")
        return self._interpolate(template, variables)

    @staticmethod
    def turn_mode(event: Event | None) -> str:
        from_agent = getattr(event, "from_agent", None) if event is not None else None
        return "chat" if from_agent == "user" else "reactive"

    def _build_reflection(self, bundle_config: BundleConfig) -> tuple[str, str, int]:
        self_reflect = bundle_config.self_reflect
        if self_reflect is None:
            return "", self._config.behavior.model_default, 1

        reflection_prompt = (
            self_reflect.prompt
            or bundle_config.prompt_templates.get("reflection", "")
            or self._default_templates.get("reflection", "")
        )
        model_name = (
            self_reflect.model or bundle_config.model or self._config.behavior.model_default
        )
        max_turns = self_reflect.max_turns
        return reflection_prompt, model_name, max_turns

    @staticmethod
    def _interpolate(template: str, variables: dict[str, str]) -> str:
        """Interpolate template vars using simple `{name}` replacement."""
        result = template
        for key, value in variables.items():
            result = result.replace(f"{{{key}}}", value)
        return result

    def _build_template_vars(
        self,
        node: Node,
        trigger_event: Event | None,
        companion_context: str,
    ) -> dict[str, str]:
        return {
            "node_name": node.name,
            "node_full_name": node.full_name,
            "node_type": serialize_enum(node.node_type),
            "file_path": node.file_path,
            "source": node.text or "",
            "role": node.role or "",
            "event_type": trigger_event.event_type if trigger_event is not None else "manual",
            "event_content": _event_content(trigger_event) if trigger_event is not None else "",
            "turn_mode": self.turn_mode(trigger_event),
            "companion_context": companion_context,
        }

    @staticmethod
    def _is_reflection_turn(
        bundle_config: BundleConfig,
        trigger_event: Event | None,
    ) -> bool:
        self_reflect = bundle_config.self_reflect
        return (
            self_reflect is not None
            and self_reflect.enabled
            and trigger_event is not None
            and trigger_event.event_type == EventType.AGENT_COMPLETE
            and "primary" in getattr(trigger_event, "tags", ())
        )


def _event_content(event: Event) -> str:
    if hasattr(event, "content"):
        return str(event.content)
    return ""


__all__ = ["PromptBuilder"]
