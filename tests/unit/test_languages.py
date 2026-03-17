from __future__ import annotations

from types import SimpleNamespace

from remora.code.languages import GenericLanguagePlugin, LanguageRegistry, PythonPlugin
from remora.defaults import default_queries_dir


def make_ts_node(node_type: str, parent=None, children=None):  # noqa: ANN001, ANN202
    return SimpleNamespace(type=node_type, parent=parent, children=children or [])


def test_language_registry_resolves_by_name_and_extension() -> None:
    registry = LanguageRegistry.from_defaults()
    assert registry.get_by_name("python") is not None
    assert registry.get_by_extension(".py") is not None
    assert registry.get_by_extension(".md") is not None
    assert registry.get_by_extension(".toml") is not None


def test_python_plugin_resolve_node_type() -> None:
    plugin = PythonPlugin(default_queries_dir() / "python.scm")
    class_node = make_ts_node("class_definition")
    method_node = make_ts_node("function_definition", parent=class_node)
    fn_node = make_ts_node("function_definition")

    assert plugin.resolve_node_type(class_node) == "class"
    assert plugin.resolve_node_type(method_node) == "method"
    assert plugin.resolve_node_type(fn_node) == "function"


def test_generic_language_plugin_node_type_resolution() -> None:
    markdown = GenericLanguagePlugin(
        name="markdown",
        extensions=[".md"],
        query_path=default_queries_dir() / "markdown.scm",
        default_node_type="section",
    )
    toml = GenericLanguagePlugin(
        name="toml",
        extensions=[".toml"],
        query_path=default_queries_dir() / "toml.scm",
        default_node_type="table",
    )
    assert markdown.resolve_node_type(make_ts_node("heading")) == "section"
    assert toml.resolve_node_type(make_ts_node("table")) == "table"
