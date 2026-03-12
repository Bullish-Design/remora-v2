from __future__ import annotations

from types import SimpleNamespace

from remora.code.languages import LanguageRegistry, MarkdownPlugin, PythonPlugin, TomlPlugin


def _node(node_type: str, parent=None, children=None):  # noqa: ANN001, ANN202
    return SimpleNamespace(type=node_type, parent=parent, children=children or [])


def test_language_registry_resolves_by_name_and_extension() -> None:
    registry = LanguageRegistry()
    assert registry.get_by_name("python") is not None
    assert registry.get_by_extension(".py") is not None
    assert registry.get_by_extension(".md") is not None
    assert registry.get_by_extension(".toml") is not None


def test_python_plugin_resolve_node_type() -> None:
    plugin = PythonPlugin()
    class_node = _node("class_definition")
    method_node = _node("function_definition", parent=class_node)
    fn_node = _node("function_definition")

    assert plugin.resolve_node_type(class_node) == "class"
    assert plugin.resolve_node_type(method_node) == "method"
    assert plugin.resolve_node_type(fn_node) == "function"


def test_markdown_and_toml_plugins() -> None:
    assert MarkdownPlugin().resolve_node_type(_node("heading")) == "section"
    assert TomlPlugin().resolve_node_type(_node("table")) == "table"
