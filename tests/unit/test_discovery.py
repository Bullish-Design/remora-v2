from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from remora.code.discovery import CSTNode, discover


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_discover_python_function(tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    _write(source, "def greet(name):\n    return f'hi {name}'\n")

    nodes = discover(
        [tmp_path],
        language_map={".py": "python"},
    )
    func = next(node for node in nodes if node.name == "greet")

    assert func.node_type == "function"
    assert func.start_line == 1
    assert func.end_line == 2


def test_discover_python_class_and_method(tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    _write(source, "class Greeter:\n    def hello(self):\n        return 'ok'\n")

    nodes = discover([tmp_path], language_map={".py": "python"})
    klass = next(node for node in nodes if node.name == "Greeter")
    method = next(node for node in nodes if node.name == "hello")

    assert klass.node_type == "class"
    assert method.node_type == "method"
    assert method.parent_id == klass.node_id
    assert method.full_name == "Greeter.hello"


def test_discover_python_decorated_and_async(tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    _write(
        source,
        "@decorator\n"
        "def decorated():\n"
        "    return 1\n\n"
        "async def async_fn():\n"
        "    return 2\n",
    )

    nodes = discover([tmp_path], language_map={".py": "python"})
    names = {node.name for node in nodes}

    assert "decorated" in names
    assert "async_fn" in names


def test_discover_markdown_sections_hierarchy(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    _write(readme, "# Top\n\n## Install\n\n### From Source\n")

    nodes = discover([tmp_path], language_map={".md": "markdown"})
    names = {node.full_name for node in nodes}

    assert "Top" in names
    assert "Top.Install" in names
    assert "Top.Install.From Source" in names


def test_discover_toml_tables(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    _write(pyproject, "[tool.ruff.lint]\nselect = ['E']\n\n[project]\nname = 'x'\n")

    nodes = discover([tmp_path], language_map={".toml": "toml"})
    names = {node.full_name for node in nodes}
    assert "tool.ruff.lint" in names
    assert "project" in names


def test_discover_ignores_patterns(tmp_path: Path) -> None:
    ignored = tmp_path / "node_modules" / "ignore_me.py"
    kept = tmp_path / "src" / "keep_me.py"
    _write(ignored, "def ignored():\n    return 1\n")
    _write(kept, "def kept():\n    return 2\n")

    nodes = discover(
        [tmp_path],
        language_map={".py": "python"},
        ignore_patterns=("node_modules",),
    )
    names = {node.name for node in nodes}

    assert "ignored" not in names
    assert "kept" in names


def test_discover_query_override(tmp_path: Path) -> None:
    source = tmp_path / "example.py"
    _write(source, "def only_function():\n    return 1\n\nclass C:\n    pass\n")

    override_dir = tmp_path / "queries"
    override_dir.mkdir(parents=True, exist_ok=True)
    _write(
        override_dir / "python.scm",
        "(class_definition name: (identifier) @node.name) @node\n",
    )

    nodes = discover(
        [tmp_path],
        language_map={".py": "python"},
        query_paths=[override_dir],
    )
    names = {node.name for node in nodes}
    assert names == {"C"}


def test_discover_multiple_files(tmp_path: Path) -> None:
    _write(tmp_path / "a.py", "def a():\n    return 1\n")
    _write(tmp_path / "b.py", "def b():\n    return 2\n")

    nodes = discover([tmp_path], language_map={".py": "python"})
    names = {node.name for node in nodes}

    assert {"a", "b"}.issubset(names)


def test_discover_empty_dir(tmp_path: Path) -> None:
    nodes = discover([tmp_path], language_map={".py": "python"})
    assert nodes == []


def test_language_not_in_registry_is_skipped(tmp_path: Path) -> None:
    _write(tmp_path / "x.foo", "hello")
    nodes = discover([tmp_path], language_map={".foo": "unknown"})
    assert nodes == []


def test_cstnode_frozen() -> None:
    node = CSTNode(
        node_id="a::b",
        node_type="function",
        name="b",
        full_name="b",
        file_path="a.py",
        text="def b():\n    pass\n",
        start_line=1,
        end_line=2,
        start_byte=0,
        end_byte=17,
    )

    with pytest.raises(ValidationError):
        node.name = "changed"
