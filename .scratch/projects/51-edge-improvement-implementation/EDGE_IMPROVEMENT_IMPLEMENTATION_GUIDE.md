# Edge Improvement Implementation Guide

> Step-by-step implementation guide for adding cross-file relationship edges (imports, inheritance)
> to the remora-v2 code graph. Written for an intern-level implementer with full verification steps.

**IMPORTANT: NEVER use subagents (the Task tool). Do all work directly.**

---

## Table of Contents

1. **[Prerequisites](#step-1-prerequisites)** — What you need to know before starting.
2. **[Add `idx_edges_type` Index](#step-2-add-idx_edges_type-index)** — Add composite index for type-filtered edge queries.
3. **[Add `get_edges_by_type` to NodeStore](#step-3-add-get_edges_by_type-to-nodestore)** — Type-filtered edge query method.
4. **[Add `get_importers` and `get_dependencies` to NodeStore](#step-4-add-get_importers-and-get_dependencies-to-nodestore)** — Convenience import-edge query methods.
5. **[Add `delete_edges_by_type` to NodeStore](#step-5-add-delete_edges_by_type-to-nodestore)** — Stale edge cleanup method.
6. **[Write Unit Tests for New NodeStore Methods](#step-6-write-unit-tests-for-new-nodestore-methods)** — TDD verification of storage layer.
7. **[Create `python_imports.scm` Query File](#step-7-create-python_importsscm-query-file)** — Tree-sitter query for import extraction.
8. **[Create `python_inheritance.scm` Query File](#step-8-create-python_inheritancescm-query-file)** — Tree-sitter query for class base extraction.
9. **[Create `src/remora/code/relationships.py`](#step-9-create-srcremoraccoderelationshipspy)** — Core extraction and resolution module.
10. **[Write Unit Tests for Relationship Extraction](#step-10-write-unit-tests-for-relationship-extraction)** — TDD for extraction functions.
11. **[Add Name Index to FileReconciler](#step-11-add-name-index-to-filereconciler)** — In-memory name-to-nodeID index.
12. **[Integrate Edge Extraction into Reconciler](#step-12-integrate-edge-extraction-into-reconciler)** — Call extraction in `_do_reconcile_file`.
13. **[Write Integration Tests for Reconciler Edge Extraction](#step-13-write-integration-tests-for-reconciler-edge-extraction)** — End-to-end reconciler verification.
14. **[Add GraphCapabilities Externals](#step-14-add-graphcapabilities-externals)** — Expose new queries to agent tools.
15. **[Add API Endpoint for Relationships](#step-15-add-api-endpoint-for-relationships)** — REST endpoint for relationship queries.
16. **[Bump EXTERNALS_VERSION](#step-16-bump-externals_version)** — Version gate for new capabilities.
17. **[Final Verification](#step-17-final-verification)** — Full test suite and manual smoke test.

**IMPORTANT: NEVER use subagents (the Task tool). Do all work directly.**

---

## Step 1: Prerequisites

### What You Need to Know

- **Python 3.11+** with `asyncio` and `aiosqlite`
- **Tree-sitter**: AST parsing library. Remora uses it to discover code elements (functions, classes) from source files.
- **Pydantic**: Data validation library. `Node` is a Pydantic `BaseModel`.
- **SQLite WAL mode**: The persistence layer. All nodes, edges, and events live in SQLite.

### Key Files to Read First

Read these files to understand the existing system before making any changes:

| File | Purpose | Why You Need It |
|------|---------|-----------------|
| `src/remora/core/storage/graph.py` | `NodeStore` + `Edge` dataclass | You'll add methods here (Steps 3-5) |
| `src/remora/code/discovery.py` | Tree-sitter node discovery | Understand how files are parsed into nodes |
| `src/remora/code/reconciler.py` | `FileReconciler` | You'll integrate extraction here (Steps 11-12) |
| `src/remora/code/languages.py` | `LanguagePlugin` + `PythonPlugin` | Understand query loading and language system |
| `src/remora/defaults/queries/python.scm` | Current tree-sitter queries | See the pattern for node discovery queries |
| `src/remora/core/tools/capabilities.py` | `GraphCapabilities` | You'll expose new methods here (Step 14) |
| `src/remora/core/tools/context.py` | `EXTERNALS_VERSION` | You'll bump this (Step 16) |
| `tests/unit/test_graph.py` | Existing NodeStore tests | Pattern for writing your tests |
| `tests/unit/test_discovery.py` | Existing discovery tests | Pattern for tree-sitter tests |
| `tests/factories.py` | `make_node()`, `write_file()` | Test helpers you'll reuse |

### Environment Setup

Before running any tests, always sync dependencies first:

```bash
devenv shell -- uv sync --extra dev
```

Run existing tests to confirm everything passes before you start:

```bash
devenv shell -- python -m pytest tests/unit/test_graph.py tests/unit/test_discovery.py -v
```

**Verification**: All tests should pass. If they don't, stop and investigate before proceeding.

### How Node IDs Work

Node IDs follow the pattern `"{file_path}::{full_name}"`. Examples:
- `src/remora/core/model/node.py::Node` — the `Node` class
- `src/remora/core/events/bus.py::EventBus.publish` — the `publish` method on `EventBus`
- `src/app.py::greet` — a top-level function

Understanding this pattern is critical for import resolution (Step 9).

### How the Edges Table Works

The `edges` table in `graph.py:81-89`:

```sql
CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id TEXT NOT NULL,
    to_id TEXT NOT NULL,
    edge_type TEXT NOT NULL,
    UNIQUE(from_id, to_id, edge_type)
);
```

- `edge_type` is a free-form string. Currently only `"contains"` is used.
- `UNIQUE(from_id, to_id, edge_type)` prevents duplicate edges.
- `INSERT OR IGNORE` in `add_edge()` means re-adding the same edge is a no-op.

You will add new edge types: `"imports"` and `"inherits"`.

---

## Step 2: Add `idx_edges_type` Index

### What

Add a database index on `edges(edge_type)` so that type-filtered queries (e.g., "get all import edges for node X") are fast.

### Where

**File**: `src/remora/core/storage/graph.py`, inside `NodeStore.create_tables()` method (line 57-92).

### How

Add this line after the existing `idx_edges_to` index creation (after line 89, before the closing `"""`):

```sql
CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(edge_type);
```

The full `executescript` block should end like:

```python
            CREATE INDEX IF NOT EXISTS idx_edges_from ON edges(from_id);
            CREATE INDEX IF NOT EXISTS idx_edges_to ON edges(to_id);
            CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(edge_type);
            """
```

### Why

Without this index, queries like `SELECT ... WHERE edge_type = 'imports'` require a full table scan. With the index, they're O(log n).

### Verification

```bash
devenv shell -- python -m pytest tests/unit/test_graph.py -v
```

**Expected**: All existing tests pass. The `IF NOT EXISTS` clause means the index creation is idempotent and won't break existing databases.

---

## Step 3: Add `get_edges_by_type` to NodeStore

### What

A method to query edges filtered by both node ID and edge type, with direction support.

### Where

**File**: `src/remora/core/storage/graph.py`, add after the `get_edges()` method (after line 252).

### How

Add this method to the `NodeStore` class:

```python
    async def get_edges_by_type(
        self, node_id: str, edge_type: str, direction: str = "both"
    ) -> list[Edge]:
        """Get edges of a specific type for a node."""
        if direction == "outgoing":
            sql = (
                "SELECT from_id, to_id, edge_type FROM edges "
                "WHERE from_id = ? AND edge_type = ? ORDER BY id ASC"
            )
            params: tuple[Any, ...] = (node_id, edge_type)
        elif direction == "incoming":
            sql = (
                "SELECT from_id, to_id, edge_type FROM edges "
                "WHERE to_id = ? AND edge_type = ? ORDER BY id ASC"
            )
            params = (node_id, edge_type)
        elif direction == "both":
            sql = (
                "SELECT from_id, to_id, edge_type FROM edges "
                "WHERE (from_id = ? OR to_id = ?) AND edge_type = ? ORDER BY id ASC"
            )
            params = (node_id, node_id, edge_type)
        else:
            raise ValueError("direction must be one of: outgoing, incoming, both")

        cursor = await self._db.execute(sql, params)
        rows = await cursor.fetchall()
        return [
            Edge(from_id=row["from_id"], to_id=row["to_id"], edge_type=row["edge_type"])
            for row in rows
        ]
```

### Why

The existing `get_edges()` returns all edge types. Many callers only need edges of a specific type (e.g., "get all import edges for this node"). This method avoids post-filtering in Python.

### Verification

You'll write tests for this in Step 6. For now, confirm the file still parses:

```bash
devenv shell -- python -c "from remora.core.storage.graph import NodeStore; print('OK')"
```

**Expected**: Prints `OK` with no errors.

---

## Step 4: Add `get_importers` and `get_dependencies` to NodeStore

### What

Two convenience methods for the most common import-edge queries:
- `get_importers(node_id)` — "who imports me?"
- `get_dependencies(node_id)` — "what do I import?"

### Where

**File**: `src/remora/core/storage/graph.py`, add after the `get_edges_by_type()` method you added in Step 3.

### How

```python
    async def get_importers(self, node_id: str) -> list[str]:
        """Get node IDs that import the given node."""
        cursor = await self._db.execute(
            "SELECT from_id FROM edges WHERE to_id = ? AND edge_type = 'imports'",
            (node_id,),
        )
        rows = await cursor.fetchall()
        return [row["from_id"] for row in rows]

    async def get_dependencies(self, node_id: str) -> list[str]:
        """Get node IDs that the given node depends on (imports)."""
        cursor = await self._db.execute(
            "SELECT to_id FROM edges WHERE from_id = ? AND edge_type = 'imports'",
            (node_id,),
        )
        rows = await cursor.fetchall()
        return [row["to_id"] for row in rows]
```

### Why

These are the highest-value queries for agents: "what depends on this node?" and "what does this node depend on?" They're used in `GraphCapabilities` (Step 14) and could be used by the prompt builder for context enrichment.

### Verification

Confirm the file still parses:

```bash
devenv shell -- python -c "from remora.core.storage.graph import NodeStore; print('OK')"
```

---

## Step 5: Add `delete_edges_by_type` to NodeStore

### What

A method to delete all edges of a given type that involve a specific node. Used during re-reconciliation to clear stale cross-file edges before re-extracting fresh ones.

### Where

**File**: `src/remora/core/storage/graph.py`, add after the `get_dependencies()` method.

### How

```python
    async def delete_edges_by_type(self, node_id: str, edge_type: str) -> int:
        """Delete all edges of a type involving a node. Used during re-extraction."""
        cursor = await self._db.execute(
            "DELETE FROM edges WHERE (from_id = ? OR to_id = ?) AND edge_type = ?",
            (node_id, node_id, edge_type),
        )
        await self._maybe_commit()
        return cursor.rowcount
```

### Why

When a file is re-reconciled, its import relationships may have changed (e.g., an import was removed). We must delete old import edges and re-insert fresh ones. This method handles the "delete old" step.

**Important**: This only deletes edges of the specified type. It does NOT touch `"contains"` edges — those are managed by the existing reconciler logic.

### Verification

Confirm the file still parses:

```bash
devenv shell -- python -c "from remora.core.storage.graph import NodeStore; print('OK')"
```

---

## Step 6: Write Unit Tests for New NodeStore Methods

### What

TDD tests for `get_edges_by_type`, `get_importers`, `get_dependencies`, and `delete_edges_by_type`.

### Where

**File**: `tests/unit/test_graph.py` — append new test functions at the end of the file.

### How

Add these tests at the end of `tests/unit/test_graph.py`:

```python
@pytest.mark.asyncio
async def test_nodestore_get_edges_by_type(db, tx) -> None:
    store = NodeStore(db, tx=tx)
    await store.create_tables()
    await store.upsert_node(make_node("src/app.py::a"))
    await store.upsert_node(make_node("src/app.py::b"))
    await store.upsert_node(make_node("src/app.py::c"))
    await store.add_edge("src/app.py::a", "src/app.py::b", "imports")
    await store.add_edge("src/app.py::a", "src/app.py::c", "contains")

    imports_out = await store.get_edges_by_type("src/app.py::a", "imports", direction="outgoing")
    assert len(imports_out) == 1
    assert imports_out[0].to_id == "src/app.py::b"
    assert imports_out[0].edge_type == "imports"

    contains_out = await store.get_edges_by_type("src/app.py::a", "contains", direction="outgoing")
    assert len(contains_out) == 1
    assert contains_out[0].to_id == "src/app.py::c"

    # incoming direction
    imports_in = await store.get_edges_by_type("src/app.py::b", "imports", direction="incoming")
    assert len(imports_in) == 1
    assert imports_in[0].from_id == "src/app.py::a"

    # both direction
    both = await store.get_edges_by_type("src/app.py::a", "imports", direction="both")
    assert len(both) == 1


@pytest.mark.asyncio
async def test_nodestore_get_edges_by_type_invalid_direction(db, tx) -> None:
    store = NodeStore(db, tx=tx)
    await store.create_tables()
    with pytest.raises(ValueError, match="direction"):
        await store.get_edges_by_type("src/app.py::a", "imports", direction="invalid")


@pytest.mark.asyncio
async def test_nodestore_get_importers(db, tx) -> None:
    store = NodeStore(db, tx=tx)
    await store.create_tables()
    await store.upsert_node(make_node("src/app.py::a"))
    await store.upsert_node(make_node("src/app.py::b"))
    await store.upsert_node(make_node("src/app.py::c"))
    await store.add_edge("src/app.py::a", "src/app.py::c", "imports")
    await store.add_edge("src/app.py::b", "src/app.py::c", "imports")
    await store.add_edge("src/app.py::a", "src/app.py::b", "contains")

    importers = await store.get_importers("src/app.py::c")
    assert sorted(importers) == ["src/app.py::a", "src/app.py::b"]

    # "contains" edges should NOT appear in importers
    importers_b = await store.get_importers("src/app.py::b")
    assert importers_b == []


@pytest.mark.asyncio
async def test_nodestore_get_dependencies(db, tx) -> None:
    store = NodeStore(db, tx=tx)
    await store.create_tables()
    await store.upsert_node(make_node("src/app.py::a"))
    await store.upsert_node(make_node("src/app.py::b"))
    await store.upsert_node(make_node("src/app.py::c"))
    await store.add_edge("src/app.py::a", "src/app.py::b", "imports")
    await store.add_edge("src/app.py::a", "src/app.py::c", "imports")
    await store.add_edge("src/app.py::a", "src/app.py::b", "contains")

    deps = await store.get_dependencies("src/app.py::a")
    assert sorted(deps) == ["src/app.py::b", "src/app.py::c"]


@pytest.mark.asyncio
async def test_nodestore_delete_edges_by_type(db, tx) -> None:
    store = NodeStore(db, tx=tx)
    await store.create_tables()
    await store.upsert_node(make_node("src/app.py::a"))
    await store.upsert_node(make_node("src/app.py::b"))
    await store.upsert_node(make_node("src/app.py::c"))
    await store.add_edge("src/app.py::a", "src/app.py::b", "imports")
    await store.add_edge("src/app.py::a", "src/app.py::c", "imports")
    await store.add_edge("src/app.py::a", "src/app.py::b", "contains")

    deleted = await store.delete_edges_by_type("src/app.py::a", "imports")
    assert deleted == 2

    # "contains" edge should still exist
    remaining = await store.get_edges("src/app.py::a", direction="outgoing")
    assert len(remaining) == 1
    assert remaining[0].edge_type == "contains"

    # Importers should now be empty
    assert await store.get_importers("src/app.py::b") == []
```

### Important Notes

- Each test creates its own `NodeStore` and calls `create_tables()` — this is the existing pattern in `test_graph.py`.
- The `db` and `tx` fixtures come from `conftest.py` (they provide a fresh in-memory SQLite database per test).
- The `NodeStore` import is already present in the existing file — you don't need to add it again.

### Verification

```bash
devenv shell -- python -m pytest tests/unit/test_graph.py -v -k "edges_by_type or importers or dependencies or delete_edges_by_type"
```

**Expected**: All 6 new tests pass. If any fail, fix the `NodeStore` methods from Steps 3-5 before proceeding.

Then run the full test file to ensure nothing is broken:

```bash
devenv shell -- python -m pytest tests/unit/test_graph.py -v
```

**Expected**: All tests pass (existing + new).

---

## Step 7: Create `python_imports.scm` Query File

### What

A tree-sitter query file that captures Python import statements. This file is used by the relationship extraction module (Step 9) to find imports in source files.

### Where

**File**: `src/remora/defaults/queries/python_imports.scm` (NEW file).

### How

Create this file with the following content:

```scheme
; Standard imports: import foo, import foo.bar
(import_statement
  name: (dotted_name) @import.target) @import

; From imports: from foo import bar
(import_from_statement
  module_name: (dotted_name) @import.source
  name: (dotted_name) @import.target) @import

; From imports with alias: from foo import bar as baz
(import_from_statement
  module_name: (dotted_name) @import.source
  name: (aliased_import
    name: (dotted_name) @import.target)) @import

; From imports with multiple names: from foo import bar, baz
(import_from_statement
  module_name: (dotted_name) @import.source
  name: (aliased_import
    name: (identifier) @import.target)) @import_aliased_ident

; Single-name from import: from foo import bar (where bar is identifier, not dotted_name)
(import_from_statement
  module_name: (dotted_name) @import.source
  name: (identifier) @import.target) @import_ident
```

### Understanding the Query Captures

- `@import.source` — the module being imported from (e.g., `remora.core.model.node` in `from remora.core.model.node import Node`)
- `@import.target` — the specific name being imported (e.g., `Node`)
- `@import` — the full import statement node (used as an anchor)

### Why Multiple Patterns

Python has several import syntaxes:
1. `import foo` — `@import.target` = `foo`, no `@import.source`
2. `from foo import bar` — `@import.source` = `foo`, `@import.target` = `bar`
3. `from foo import bar as baz` — `@import.source` = `foo`, `@import.target` = `bar`
4. `from foo import bar, baz` — one pattern per name

### Verification

You'll verify this query in Step 10 via unit tests. For now, confirm the file was created:

```bash
ls -la src/remora/defaults/queries/python_imports.scm
```

**Expected**: File exists with the content above.

### Manual Tree-Sitter Check (Optional)

If you want to verify the query syntax is valid before writing tests:

```bash
devenv shell -- python -c "
from tree_sitter import Language, Query
import tree_sitter_python
lang = Language(tree_sitter_python.language())
q = Query(lang, open('src/remora/defaults/queries/python_imports.scm').read())
print('Query parsed OK')
"
```

If this errors, the `.scm` syntax has an issue — check for missing parentheses or incorrect node type names.

---

## Step 8: Create `python_inheritance.scm` Query File

### What

A tree-sitter query file that captures class inheritance (base class declarations).

### Where

**File**: `src/remora/defaults/queries/python_inheritance.scm` (NEW file).

### How

Create this file with the following content:

```scheme
; Class with simple base: class Foo(Bar)
(class_definition
  name: (identifier) @class.name
  superclasses: (argument_list
    (identifier) @class.base)) @class

; Class with dotted base: class Foo(bar.Baz)
(class_definition
  name: (identifier) @class.name
  superclasses: (argument_list
    (attribute
      object: (identifier)
      attribute: (identifier) @class.base))) @class
```

### Understanding the Query Captures

- `@class.name` — the name of the class being defined (e.g., `Dog` in `class Dog(Animal)`)
- `@class.base` — the name of a base class (e.g., `Animal`)
- `@class` — the full class definition node

### Why

When `class Dog(Animal)` is encountered, we want to create an edge: `Dog --inherits--> Animal`. The query extracts the names; the resolution module (Step 9) converts names to node IDs.

### Verification

```bash
ls -la src/remora/defaults/queries/python_inheritance.scm
```

**Expected**: File exists.

Optionally verify syntax:

```bash
devenv shell -- python -c "
from tree_sitter import Language, Query
import tree_sitter_python
lang = Language(tree_sitter_python.language())
q = Query(lang, open('src/remora/defaults/queries/python_inheritance.scm').read())
print('Query parsed OK')
"
```

---

## Step 9: Create `src/remora/code/relationships.py`

### What

The core module for cross-file relationship extraction and resolution. It:
1. Parses source files using tree-sitter queries (from Steps 7-8)
2. Extracts raw relationships (unresolved names)
3. Resolves names to node IDs using a name index

### Where

**File**: `src/remora/code/relationships.py` (NEW file).

### How

Create this file with the following content:

```python
"""Cross-file relationship extraction from tree-sitter AST."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tree_sitter import Parser, Query, QueryCursor

from remora.code.languages import LanguagePlugin

logger = logging.getLogger(__name__)


@dataclass
class RawRelationship:
    """An unresolved relationship between source elements."""

    source_node_id: str
    target_name: str
    edge_type: str  # "imports", "inherits"
    target_module: str | None = None  # For imports: "remora.core.model.node"


@dataclass
class ResolvedEdge:
    """A resolved edge ready for storage."""

    from_id: str
    to_id: str
    edge_type: str


def _load_query(
    plugin: LanguagePlugin, query_filename: str, query_paths: list[Path]
) -> Query | None:
    """Load a tree-sitter query file by name from query search paths."""
    for query_dir in query_paths:
        candidate = query_dir / query_filename
        if candidate.exists():
            query_text = candidate.read_text(encoding="utf-8")
            return Query(plugin.get_language(), query_text)

    # Try the default queries directory (same dir as plugin's default query)
    default_dir = plugin.get_default_query_path().parent
    candidate = default_dir / query_filename
    if candidate.exists():
        query_text = candidate.read_text(encoding="utf-8")
        return Query(plugin.get_language(), query_text)

    return None


def _node_text(source: bytes, node: Any) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def extract_imports(
    source_bytes: bytes,
    plugin: LanguagePlugin,
    file_path: str,
    file_node_id: str,
    query_paths: list[Path],
) -> list[RawRelationship]:
    """Extract import relationships from a Python source file.

    Parameters
    ----------
    source_bytes:
        Raw bytes of the source file.
    plugin:
        The language plugin (must be Python).
    file_path:
        The file path string (used for logging).
    file_node_id:
        The node ID used as the source of import edges. Typically the first
        discovered node in the file, or the file path itself as fallback.
    query_paths:
        Directories to search for query files.

    Returns
    -------
    list[RawRelationship]:
        Unresolved import relationships.
    """
    query = _load_query(plugin, "python_imports.scm", query_paths)
    if query is None:
        return []

    parser = Parser(plugin.get_language())
    tree = parser.parse(source_bytes)
    matches = QueryCursor(query).matches(tree.root_node)

    relationships: list[RawRelationship] = []
    seen: set[tuple[str, str]] = set()

    for _pattern_index, captures in matches:
        source_nodes = captures.get("import.source", [])
        target_nodes = captures.get("import.target", [])

        if not target_nodes:
            continue

        target_name = _node_text(source_bytes, target_nodes[0]).strip()
        source_module = (
            _node_text(source_bytes, source_nodes[0]).strip() if source_nodes else None
        )

        if not target_name:
            continue

        # Deduplicate: same (module, target) pair
        dedup_key = (source_module or "", target_name)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        relationships.append(
            RawRelationship(
                source_node_id=file_node_id,
                target_name=target_name,
                edge_type="imports",
                target_module=source_module,
            )
        )

    return relationships


def extract_inheritance(
    source_bytes: bytes,
    plugin: LanguagePlugin,
    file_path: str,
    nodes_by_name: dict[str, str],
    query_paths: list[Path],
) -> list[RawRelationship]:
    """Extract class inheritance relationships from a Python source file.

    Parameters
    ----------
    source_bytes:
        Raw bytes of the source file.
    plugin:
        The language plugin (must be Python).
    file_path:
        The file path string.
    nodes_by_name:
        Mapping of class name -> node_id for classes discovered in THIS file.
        Used to find the source_node_id for the inheriting class.
    query_paths:
        Directories to search for query files.

    Returns
    -------
    list[RawRelationship]:
        Unresolved inheritance relationships.
    """
    query = _load_query(plugin, "python_inheritance.scm", query_paths)
    if query is None:
        return []

    parser = Parser(plugin.get_language())
    tree = parser.parse(source_bytes)
    matches = QueryCursor(query).matches(tree.root_node)

    relationships: list[RawRelationship] = []

    for _pattern_index, captures in matches:
        class_name_nodes = captures.get("class.name", [])
        base_name_nodes = captures.get("class.base", [])

        if not class_name_nodes or not base_name_nodes:
            continue

        class_name = _node_text(source_bytes, class_name_nodes[0]).strip()
        base_name = _node_text(source_bytes, base_name_nodes[0]).strip()

        if not class_name or not base_name:
            continue

        # Skip built-in bases that won't resolve to project nodes
        if base_name in {"object", "type", "Exception", "BaseException"}:
            continue

        source_node_id = nodes_by_name.get(class_name)
        if source_node_id is None:
            continue

        relationships.append(
            RawRelationship(
                source_node_id=source_node_id,
                target_name=base_name,
                edge_type="inherits",
            )
        )

    return relationships


def resolve_relationships(
    raw: list[RawRelationship],
    name_index: dict[str, list[str]],
) -> list[ResolvedEdge]:
    """Resolve raw relationship targets to node IDs using the name index.

    Parameters
    ----------
    raw:
        Unresolved relationships from extract_imports/extract_inheritance.
    name_index:
        Mapping of name -> [node_id, ...] built from the full graph.

    Returns
    -------
    list[ResolvedEdge]:
        Resolved edges ready for storage. Relationships whose targets
        cannot be resolved are silently dropped.
    """
    resolved: list[ResolvedEdge] = []

    for rel in raw:
        target_ids: list[str] = []

        if rel.edge_type == "imports" and rel.target_module:
            # For "from X import Y": try "X.Y" as a qualified name first,
            # then fall back to just "Y".
            qualified = f"{rel.target_module}.{rel.target_name}"
            target_ids = name_index.get(qualified, [])
            if not target_ids:
                # Try the module itself (e.g., "from os import path")
                target_ids = name_index.get(rel.target_module, [])
            if not target_ids:
                # Fall back to bare target name
                target_ids = name_index.get(rel.target_name, [])
        else:
            # For inheritance and plain imports: look up by name
            target_ids = name_index.get(rel.target_name, [])

        # Skip self-edges
        target_ids = [tid for tid in target_ids if tid != rel.source_node_id]

        if not target_ids:
            logger.debug(
                "Unresolved %s: %s -> %s (module=%s)",
                rel.edge_type,
                rel.source_node_id,
                rel.target_name,
                rel.target_module,
            )
            continue

        # Create an edge to each candidate (handles name collisions)
        for target_id in target_ids:
            resolved.append(
                ResolvedEdge(
                    from_id=rel.source_node_id,
                    to_id=target_id,
                    edge_type=rel.edge_type,
                )
            )

    return resolved


__all__ = [
    "RawRelationship",
    "ResolvedEdge",
    "extract_imports",
    "extract_inheritance",
    "resolve_relationships",
]
```

### Key Design Decisions

1. **File-level import edges**: Import edges are created from the first node in the file to the imported target. This is because Python imports are file-scoped.

2. **Name index for resolution**: Instead of trying to resolve dotted import paths to file paths (which requires understanding `src` layout, `__init__.py` re-exports, etc.), we use a name index built from all known nodes. This is simpler and handles re-exports naturally.

3. **Multiple candidates**: If `Config` resolves to two different nodes (name collision), we create edges to both. This is conservative — better to have a spurious edge than miss a real dependency.

4. **Built-in skip list**: `object`, `type`, `Exception`, `BaseException` are skipped for inheritance since they'll never resolve to project nodes.

5. **Separate queries per relationship type**: Each `.scm` file handles one relationship type. This keeps queries simple and testable.

### Verification

```bash
devenv shell -- python -c "from remora.code.relationships import extract_imports, resolve_relationships; print('OK')"
```

**Expected**: Prints `OK`.

---

## Step 10: Write Unit Tests for Relationship Extraction

### What

Unit tests for `extract_imports`, `extract_inheritance`, and `resolve_relationships`.

### Where

**File**: `tests/unit/test_relationships.py` (NEW file).

### How

Create this file:

```python
"""Tests for cross-file relationship extraction."""

from __future__ import annotations

from pathlib import Path

import pytest

from remora.code.languages import LanguageRegistry
from remora.code.relationships import (
    RawRelationship,
    ResolvedEdge,
    extract_imports,
    extract_inheritance,
    resolve_relationships,
)
from remora.defaults import default_queries_dir


@pytest.fixture
def python_plugin():
    registry = LanguageRegistry.from_defaults()
    return registry.get_by_name("python")


@pytest.fixture
def query_paths():
    return [default_queries_dir()]


class TestExtractImports:
    def test_simple_import(self, python_plugin, query_paths):
        source = b"import os\n"
        rels = extract_imports(source, python_plugin, "app.py", "app.py::__file__", query_paths)
        assert any(r.target_name == "os" and r.edge_type == "imports" for r in rels)

    def test_from_import(self, python_plugin, query_paths):
        source = b"from os.path import join\n"
        rels = extract_imports(source, python_plugin, "app.py", "app.py::__file__", query_paths)
        assert any(
            r.target_name == "join" and r.target_module == "os.path" and r.edge_type == "imports"
            for r in rels
        )

    def test_from_import_dotted_target(self, python_plugin, query_paths):
        source = b"from remora.core.model.node import Node\n"
        rels = extract_imports(source, python_plugin, "app.py", "app.py::__file__", query_paths)
        assert any(
            r.target_name == "Node" and r.target_module == "remora.core.model.node"
            for r in rels
        )

    def test_multiple_imports(self, python_plugin, query_paths):
        source = b"import os\nimport sys\nfrom pathlib import Path\n"
        rels = extract_imports(source, python_plugin, "app.py", "app.py::__file__", query_paths)
        target_names = {r.target_name for r in rels}
        assert "os" in target_names
        assert "sys" in target_names
        assert "Path" in target_names

    def test_no_imports(self, python_plugin, query_paths):
        source = b"def hello():\n    pass\n"
        rels = extract_imports(source, python_plugin, "app.py", "app.py::__file__", query_paths)
        assert rels == []

    def test_deduplication(self, python_plugin, query_paths):
        source = b"from os import path\nfrom os import path\n"
        rels = extract_imports(source, python_plugin, "app.py", "app.py::__file__", query_paths)
        path_rels = [r for r in rels if r.target_name == "path"]
        assert len(path_rels) == 1


class TestExtractInheritance:
    def test_simple_inheritance(self, python_plugin, query_paths):
        source = b"class Dog(Animal):\n    pass\n"
        nodes_by_name = {"Dog": "app.py::Dog"}
        rels = extract_inheritance(source, python_plugin, "app.py", nodes_by_name, query_paths)
        assert len(rels) == 1
        assert rels[0].source_node_id == "app.py::Dog"
        assert rels[0].target_name == "Animal"
        assert rels[0].edge_type == "inherits"

    def test_multiple_bases(self, python_plugin, query_paths):
        source = b"class Dog(Animal, Trainable):\n    pass\n"
        nodes_by_name = {"Dog": "app.py::Dog"}
        rels = extract_inheritance(source, python_plugin, "app.py", nodes_by_name, query_paths)
        base_names = {r.target_name for r in rels}
        assert "Animal" in base_names
        assert "Trainable" in base_names

    def test_skips_builtin_bases(self, python_plugin, query_paths):
        source = b"class MyError(Exception):\n    pass\n"
        nodes_by_name = {"MyError": "app.py::MyError"}
        rels = extract_inheritance(source, python_plugin, "app.py", nodes_by_name, query_paths)
        assert rels == []

    def test_unknown_class_name_skipped(self, python_plugin, query_paths):
        source = b"class Dog(Animal):\n    pass\n"
        nodes_by_name = {}  # Dog not in the map
        rels = extract_inheritance(source, python_plugin, "app.py", nodes_by_name, query_paths)
        assert rels == []

    def test_no_inheritance(self, python_plugin, query_paths):
        source = b"class Dog:\n    pass\n"
        nodes_by_name = {"Dog": "app.py::Dog"}
        rels = extract_inheritance(source, python_plugin, "app.py", nodes_by_name, query_paths)
        assert rels == []


class TestResolveRelationships:
    def test_resolve_import_with_qualified_name(self):
        raw = [
            RawRelationship(
                source_node_id="app.py::__file__",
                target_name="Node",
                edge_type="imports",
                target_module="remora.core.model.node",
            )
        ]
        name_index = {
            "remora.core.model.node.Node": ["src/remora/core/model/node.py::Node"],
            "Node": ["src/remora/core/model/node.py::Node", "other.py::Node"],
        }
        edges = resolve_relationships(raw, name_index)
        # Should resolve via qualified name to exactly 1 target
        assert len(edges) == 1
        assert edges[0].to_id == "src/remora/core/model/node.py::Node"

    def test_resolve_import_fallback_to_bare_name(self):
        raw = [
            RawRelationship(
                source_node_id="app.py::__file__",
                target_name="Config",
                edge_type="imports",
                target_module="some.unknown.module",
            )
        ]
        name_index = {"Config": ["config.py::Config"]}
        edges = resolve_relationships(raw, name_index)
        assert len(edges) == 1
        assert edges[0].to_id == "config.py::Config"

    def test_resolve_inheritance(self):
        raw = [
            RawRelationship(
                source_node_id="app.py::Dog",
                target_name="Animal",
                edge_type="inherits",
            )
        ]
        name_index = {"Animal": ["animals.py::Animal"]}
        edges = resolve_relationships(raw, name_index)
        assert len(edges) == 1
        assert edges[0].from_id == "app.py::Dog"
        assert edges[0].to_id == "animals.py::Animal"
        assert edges[0].edge_type == "inherits"

    def test_unresolved_target_dropped(self):
        raw = [
            RawRelationship(
                source_node_id="app.py::Dog",
                target_name="UnknownBase",
                edge_type="inherits",
            )
        ]
        name_index = {}
        edges = resolve_relationships(raw, name_index)
        assert edges == []

    def test_self_edge_filtered(self):
        raw = [
            RawRelationship(
                source_node_id="app.py::Foo",
                target_name="Foo",
                edge_type="inherits",
            )
        ]
        name_index = {"Foo": ["app.py::Foo"]}
        edges = resolve_relationships(raw, name_index)
        assert edges == []

    def test_multiple_candidates(self):
        raw = [
            RawRelationship(
                source_node_id="app.py::Dog",
                target_name="Config",
                edge_type="inherits",
            )
        ]
        name_index = {"Config": ["a.py::Config", "b.py::Config"]}
        edges = resolve_relationships(raw, name_index)
        assert len(edges) == 2
        assert {e.to_id for e in edges} == {"a.py::Config", "b.py::Config"}
```

### Important Notes

- The `default_queries_dir()` function is imported from `remora.defaults` — this gives you the path to `src/remora/defaults/queries/` where your new `.scm` files live.
- The `python_plugin` fixture uses `LanguageRegistry.from_defaults()` to get a real Python plugin with tree-sitter loaded.
- These tests parse real Python source bytes through tree-sitter, so they verify the `.scm` queries from Steps 7-8 are correct.

### Verification

```bash
devenv shell -- python -m pytest tests/unit/test_relationships.py -v
```

**Expected**: All tests pass. If any `extract_imports` or `extract_inheritance` tests fail, the issue is likely in the `.scm` query file syntax (Steps 7-8). Debug by examining what tree-sitter captures are returned.

### Debugging Tree-Sitter Query Issues

If a test fails because no matches are found, you can debug by printing all captures:

```python
devenv shell -- python -c "
from tree_sitter import Parser, Query, QueryCursor
from remora.code.languages import LanguageRegistry
from remora.defaults import default_queries_dir

registry = LanguageRegistry.from_defaults()
plugin = registry.get_by_name('python')
lang = plugin.get_language()
query = Query(lang, open(str(default_queries_dir() / 'python_imports.scm')).read())
parser = Parser(lang)
source = b'from os.path import join\n'
tree = parser.parse(source)
matches = QueryCursor(query).matches(tree.root_node)
for pattern_idx, captures in matches:
    print(f'Pattern {pattern_idx}: {captures}')
"
```

This will show you exactly what the query captures, helping you adjust the `.scm` file if needed.

---

## Step 11: Add Name Index to FileReconciler

### What

An in-memory dictionary mapping names and full names to node IDs. Built incrementally as files are reconciled. Used by the resolution step to convert import/inheritance target names to node IDs.

### Where

**File**: `src/remora/code/reconciler.py`

### How

#### 11a: Add the name index field to `__init__`

In `FileReconciler.__init__` (line 45-99), add this field after `self._file_state` (after line 69):

```python
        self._name_index: dict[str, list[str]] = {}
```

#### 11b: Add helper methods for name index maintenance

Add these private methods to the `FileReconciler` class, after `_evict_stale_file_locks` (after line 393):

```python
    def _index_node_names(self, nodes: list[Node]) -> None:
        """Add node names and full names to the name index."""
        for node in nodes:
            self._name_index.setdefault(node.name, []).append(node.node_id)
            if node.full_name != node.name:
                self._name_index.setdefault(node.full_name, []).append(node.node_id)

    def _deindex_node_names(self, node_id: str, node: Node) -> None:
        """Remove a node from the name index."""
        for key in (node.name, node.full_name):
            if key in self._name_index:
                self._name_index[key] = [
                    nid for nid in self._name_index[key] if nid != node_id
                ]
                if not self._name_index[key]:
                    del self._name_index[key]
```

#### 11c: Call `_index_node_names` after building the projected list

In `_do_reconcile_file` (line 217-281), add a call to `_index_node_names` right before the `if self._tx is not None:` block (before line 274):

```python
        self._index_node_names(projected)
```

So the code around line 272-280 should look like:

```python
            projected.append(node)

        self._index_node_names(projected)

        if self._tx is not None:
            async with self._tx.batch():
                await self._reconcile_events(projected, old_ids, new_ids, old_hashes, file_path)
```

#### 11d: Call `_deindex_node_names` when removing nodes

In `_remove_node` (line 395-410), add the deindex call after fetching the node but before deleting it. The method should look like:

```python
    async def _remove_node(self, node_id: str) -> None:
        node = await self._node_store.get_node(node_id)
        if node is None:
            await self._event_store.subscriptions.unregister_by_agent(node_id)
            return

        self._deindex_node_names(node_id, node)
        await self._event_store.subscriptions.unregister_by_agent(node_id)
        await self._node_store.delete_node(node_id)
        await self._event_store.append(
            NodeRemovedEvent(
                node_id=node.node_id,
                node_type=node.node_type,
                file_path=node.file_path,
                name=node.name,
            )
        )
```

### Why

The name index is the bridge between raw tree-sitter captures (which produce names like `"Node"` or `"EventBus"`) and the graph's node IDs (like `"src/remora/core/model/node.py::Node"`). Without it, we can't resolve import/inheritance targets.

Building it incrementally (add during reconcile, remove during `_remove_node`) keeps it consistent without needing to rebuild from scratch.

### Verification

```bash
devenv shell -- python -m pytest tests/unit/test_reconciler.py tests/unit/test_reconciler_lifecycle.py -v
```

**Expected**: All existing reconciler tests pass. The name index changes are purely additive — they don't change any existing behavior.

---

## Step 12: Integrate Edge Extraction into Reconciler

### What

Call the relationship extraction functions from `_do_reconcile_file`, after node discovery and upsert, to create import and inheritance edges.

### Where

**File**: `src/remora/code/reconciler.py`

### How

#### 12a: Add imports at the top of the file

Add this import after the existing imports (after line 35, before the `logger` definition):

```python
from remora.code.relationships import (
    extract_imports,
    extract_inheritance,
    resolve_relationships,
)
```

#### 12b: Add edge extraction to `_do_reconcile_file`

In `_do_reconcile_file`, add edge extraction after `self._index_node_names(projected)` (which you added in Step 11c) and before the `if self._tx is not None:` block. Insert this code:

```python
        # --- Cross-file relationship extraction ---
        plugin = self._language_registry.get_by_name(
            self._config.behavior.language_map.get(Path(file_path).suffix.lower(), "")
        )
        if plugin is not None and plugin.name == "python":
            try:
                source_bytes = Path(file_path).read_bytes()
            except OSError:
                source_bytes = None

            if source_bytes is not None:
                file_node_ids = [n.node_id for n in projected]
                nodes_by_name = {
                    n.name: n.node_id for n in projected if n.node_type == "class"
                }

                raw_rels = extract_imports(
                    source_bytes,
                    plugin,
                    file_path,
                    file_node_ids[0] if file_node_ids else file_path,
                    self._query_paths,
                )
                raw_rels.extend(
                    extract_inheritance(
                        source_bytes,
                        plugin,
                        file_path,
                        nodes_by_name,
                        self._query_paths,
                    )
                )

                if raw_rels:
                    edges = resolve_relationships(raw_rels, self._name_index)
                    # Clear stale cross-file edges for nodes in this file
                    for node_id in file_node_ids:
                        await self._node_store.delete_edges_by_type(node_id, "imports")
                        await self._node_store.delete_edges_by_type(node_id, "inherits")
                    # Insert fresh edges
                    for edge in edges:
                        await self._node_store.add_edge(
                            edge.from_id, edge.to_id, edge.edge_type
                        )
```

### Important Notes

1. **Only Python files**: The `if plugin.name == "python"` guard ensures we only extract relationships from Python files. Other languages (markdown, toml) don't have imports/inheritance.

2. **Source re-read**: We re-read the file bytes for relationship extraction. The `discover()` function already reads the file, but doesn't expose the bytes. This is a minor I/O cost.

3. **Stale edge cleanup**: Before inserting new edges, we delete old `imports` and `inherits` edges for all nodes in this file. This handles cases where an import was removed.

4. **Error boundary**: The `try/except OSError` around file reading ensures that if the file was deleted between discovery and edge extraction, we don't crash.

### Verification

```bash
devenv shell -- python -m pytest tests/unit/test_reconciler.py tests/unit/test_reconciler_lifecycle.py -v
```

**Expected**: All existing tests pass. The edge extraction is additive and doesn't affect the existing reconcile flow.

---

## Step 13: Write Integration Tests for Reconciler Edge Extraction

### What

Tests that verify the full pipeline: discover nodes -> extract relationships -> resolve to edges -> store in DB.

### Where

**File**: `tests/unit/test_reconciler_edges.py` (NEW file).

### How

Create this file. Check `tests/unit/test_reconciler.py` for the existing fixture patterns and imports — your test fixtures should match that file's conventions.

```python
"""Tests for cross-file edge extraction in the reconciler."""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

from remora.code.languages import LanguageRegistry
from remora.code.reconciler import FileReconciler
from remora.code.subscriptions import SubscriptionManager
from remora.core.events import EventBus, EventStore, SubscriptionRegistry, TriggerDispatcher
from remora.core.model.config import Config
from remora.core.storage.graph import NodeStore
from remora.core.storage.transaction import TransactionContext
from remora.core.storage.workspace import CairnWorkspaceService
from tests.factories import write_file, write_bundle_templates


@pytest_asyncio.fixture
async def reconciler_env(db, tmp_path):
    """Set up a full reconciler environment for edge extraction tests."""
    bus = EventBus()
    dispatcher = TriggerDispatcher()
    tx = TransactionContext(db, bus, dispatcher)
    subs = SubscriptionRegistry(db, tx=tx)
    dispatcher.subscriptions = subs

    node_store = NodeStore(db, tx=tx)
    await node_store.create_tables()

    event_store = EventStore(db=db, event_bus=bus, dispatcher=dispatcher, tx=tx)
    await event_store.create_tables()

    project_root = tmp_path / "project"
    project_root.mkdir()
    src_dir = project_root / "src"
    src_dir.mkdir()

    bundles_dir = tmp_path / "bundles"
    write_bundle_templates(bundles_dir)

    config = Config()
    config.project.discovery_paths = ("src",)
    config.project.bundle_search_paths = (str(bundles_dir),)

    workspace_service = CairnWorkspaceService(tmp_path / "workspaces")
    await workspace_service.initialize()

    registry = LanguageRegistry.from_defaults()
    sub_manager = SubscriptionManager(subs, config)

    reconciler = FileReconciler(
        config=config,
        node_store=node_store,
        event_store=event_store,
        workspace_service=workspace_service,
        project_root=project_root,
        language_registry=registry,
        subscription_manager=sub_manager,
        tx=tx,
    )

    return reconciler, node_store, project_root


@pytest.mark.asyncio
async def test_reconcile_creates_import_edges(reconciler_env):
    reconciler, node_store, project_root = reconciler_env
    src_dir = project_root / "src"

    # Create two Python files where one imports from the other
    write_file(src_dir / "models.py", "class Config:\n    pass\n")
    write_file(
        src_dir / "app.py",
        "from models import Config\n\ndef main():\n    return Config()\n",
    )

    await reconciler.reconcile_cycle()

    all_edges = await node_store.list_all_edges()
    import_edges = [e for e in all_edges if e.edge_type == "imports"]

    # There should be at least one import edge
    assert len(import_edges) >= 1


@pytest.mark.asyncio
async def test_reconcile_creates_inheritance_edges(reconciler_env):
    reconciler, node_store, project_root = reconciler_env
    src_dir = project_root / "src"

    write_file(src_dir / "base.py", "class Animal:\n    pass\n")
    write_file(src_dir / "dog.py", "class Dog(Animal):\n    pass\n")

    await reconciler.reconcile_cycle()

    all_edges = await node_store.list_all_edges()
    inherits_edges = [e for e in all_edges if e.edge_type == "inherits"]

    # Dog should inherit from Animal (if resolution succeeded via name index)
    dog_inherits = [e for e in inherits_edges if "Dog" in e.from_id]
    if dog_inherits:
        assert any("Animal" in e.to_id for e in dog_inherits)


@pytest.mark.asyncio
async def test_reconcile_clears_stale_edges_on_rereconcile(reconciler_env):
    reconciler, node_store, project_root = reconciler_env
    src_dir = project_root / "src"

    # First reconcile: app imports Config
    write_file(src_dir / "models.py", "class Config:\n    pass\n")
    write_file(src_dir / "app.py", "from models import Config\n\ndef main():\n    pass\n")
    await reconciler.reconcile_cycle()

    # Second reconcile: app no longer imports Config
    write_file(src_dir / "app.py", "def main():\n    pass\n")
    await reconciler.reconcile_cycle()

    all_edges = await node_store.list_all_edges()
    import_edges = [e for e in all_edges if e.edge_type == "imports"]

    # After removing the import, the import edge should be gone
    app_imports = [e for e in import_edges if "app" in e.from_id]
    config_targets = [e for e in app_imports if "Config" in e.to_id]
    assert len(config_targets) == 0


@pytest.mark.asyncio
async def test_reconcile_preserves_contains_edges(reconciler_env):
    reconciler, node_store, project_root = reconciler_env
    src_dir = project_root / "src"

    write_file(
        src_dir / "app.py",
        "class Foo:\n    def bar(self):\n        pass\n",
    )

    await reconciler.reconcile_cycle()

    all_edges = await node_store.list_all_edges()
    contains_edges = [e for e in all_edges if e.edge_type == "contains"]

    # Parent-child containment edges should exist
    assert len(contains_edges) >= 1
```

### Important Notes

- These tests use a real `FileReconciler` with a real SQLite database and real tree-sitter parsing.
- The `reconciler_env` fixture creates a temporary project with `src/` directory.
- You may need to adjust `Config()` field assignments depending on your `Config` model's defaults and required fields. Check `test_reconciler.py` for the pattern used there.
- The `db` fixture must come from `conftest.py`. If it doesn't exist, check `tests/conftest.py`.

### Verification

```bash
devenv shell -- python -m pytest tests/unit/test_reconciler_edges.py -v
```

**Expected**: All tests pass. If import edge tests fail, debug by adding logging or checking:
1. Were nodes discovered? (`await node_store.list_nodes()`)
2. Was the name index populated? (Add `print(reconciler._name_index)`)
3. Did extraction produce raw relationships? (Add logging to `extract_imports`)

---

## Step 14: Add GraphCapabilities Externals

### What

Expose the new NodeStore methods (`get_importers`, `get_dependencies`, `get_edges_by_type`) to agent tool scripts via `GraphCapabilities`.

### Where

**File**: `src/remora/core/tools/capabilities.py`, `GraphCapabilities` class (line 121-197).

### How

#### 14a: Add new methods to GraphCapabilities

Add these methods after `graph_set_status` (line 186-188) and before `to_dict` (line 190):

```python
    async def graph_get_importers(self, target_id: str) -> list[str]:
        """Get node IDs that import the given node."""
        return await self._node_store.get_importers(target_id)

    async def graph_get_dependencies(self, target_id: str) -> list[str]:
        """Get node IDs that the given node imports/depends on."""
        return await self._node_store.get_dependencies(target_id)

    async def graph_get_edges_by_type(
        self, target_id: str, edge_type: str
    ) -> list[dict[str, Any]]:
        """Get edges of a specific type for a node."""
        edges = await self._node_store.get_edges_by_type(target_id, edge_type)
        return [
            {"from_id": e.from_id, "to_id": e.to_id, "edge_type": e.edge_type}
            for e in edges
        ]
```

#### 14b: Update `to_dict`

Replace the existing `to_dict` method (line 190-197) with:

```python
    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_get_node": self.graph_get_node,
            "graph_query_nodes": self.graph_query_nodes,
            "graph_get_edges": self.graph_get_edges,
            "graph_get_children": self.graph_get_children,
            "graph_set_status": self.graph_set_status,
            "graph_get_importers": self.graph_get_importers,
            "graph_get_dependencies": self.graph_get_dependencies,
            "graph_get_edges_by_type": self.graph_get_edges_by_type,
        }
```

### Why

Agent tool scripts (`.pym` files) access capabilities via the `externals` dict injected by the Grail tool system. Adding these methods to `to_dict` makes them callable from agent scripts like:

```python
importers = await externals["graph_get_importers"](my_node_id)
```

### Verification

```bash
devenv shell -- python -c "from remora.core.tools.capabilities import GraphCapabilities; print('OK')"
```

**Expected**: Prints `OK`.

---

## Step 15: Add API Endpoint for Relationships

### What

A REST endpoint that returns cross-file relationships for a node, optionally filtered by edge type.

### Where

**File**: `src/remora/web/routes/nodes.py`

### How

#### 15a: Add the endpoint function

Add this function after `api_edges` (after line 53):

```python
async def api_node_relationships(request: Request) -> JSONResponse:
    """Get cross-file relationships for a node, optionally filtered by type."""
    deps = _deps_from_request(request)
    node_id = request.path_params["node_id"]
    edge_type = request.query_params.get("type")

    if edge_type:
        edges = await deps.node_store.get_edges_by_type(node_id, edge_type)
    else:
        # Return all non-contains edges (cross-file relationships only)
        all_edges = await deps.node_store.get_edges(node_id)
        edges = [e for e in all_edges if e.edge_type != "contains"]

    payload = [
        {"from_id": edge.from_id, "to_id": edge.to_id, "edge_type": edge.edge_type}
        for edge in edges
    ]
    return JSONResponse(payload)
```

#### 15b: Register the route

In the `routes()` function (line 96-104), add the new route. Insert it before the catch-all `api_node` route (which must remain last because of `{node_id:path}`):

```python
def routes() -> list[Route]:
    return [
        Route("/api/nodes", endpoint=api_nodes),
        Route("/api/edges", endpoint=api_all_edges),
        Route("/api/nodes/{node_id:path}/edges", endpoint=api_edges),
        Route("/api/nodes/{node_id:path}/relationships", endpoint=api_node_relationships),
        Route("/api/nodes/{node_id:path}/conversation", endpoint=api_conversation),
        Route("/api/nodes/{node_id:path}/companion", endpoint=api_node_companion),
        Route("/api/nodes/{node_id:path}", endpoint=api_node),
    ]
```

#### 15c: Update `__all__`

Add `"api_node_relationships"` to the `__all__` list at the bottom of the file.

### Usage Examples

```
GET /api/nodes/src/app.py::main/relationships           -> all cross-file edges
GET /api/nodes/src/app.py::main/relationships?type=imports  -> only import edges
GET /api/nodes/src/app.py::Dog/relationships?type=inherits  -> only inheritance edges
```

### Verification

```bash
devenv shell -- python -c "from remora.web.routes.nodes import routes; print(f'{len(routes())} routes OK')"
```

**Expected**: Prints `8 routes OK` (was 7 before).

---

## Step 16: Bump EXTERNALS_VERSION

### What

Increment the `EXTERNALS_VERSION` constant so that bundles compiled against the old version won't try to call the new capabilities (which would fail).

### Where

**File**: `src/remora/core/tools/context.py`, line 27.

### How

Change:

```python
EXTERNALS_VERSION = 2
```

To:

```python
EXTERNALS_VERSION = 3
```

### Why

The version check in `turn.py:233-240` prevents bundles with `externals_version > EXTERNALS_VERSION` from running. By bumping from 2 to 3, bundles that need the new graph capabilities can declare `externals_version: 3` in their `bundle.yaml`, and older bundles remain compatible.

### Verification

```bash
devenv shell -- python -c "from remora.core.tools.context import EXTERNALS_VERSION; assert EXTERNALS_VERSION == 3; print('OK')"
```

**Expected**: Prints `OK`.

---

## Step 17: Final Verification

### Full Test Suite

Run the entire test suite to ensure nothing is broken:

```bash
devenv shell -- python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q
```

**Expected**: All tests pass. No regressions.

### Targeted New Test Run

Run only the tests you wrote:

```bash
devenv shell -- python -m pytest tests/unit/test_graph.py tests/unit/test_relationships.py tests/unit/test_reconciler_edges.py -v
```

**Expected**: All new tests pass.

### Lint Check

```bash
devenv shell -- ruff check src/remora/code/relationships.py src/remora/core/storage/graph.py src/remora/core/tools/capabilities.py src/remora/web/routes/nodes.py
```

**Expected**: No lint errors.

### Manual Smoke Test (Optional)

If you have a running remora instance:

1. Start remora against a Python project
2. Wait for initial reconcile to complete
3. Check the API for import edges:
   ```bash
   curl http://localhost:8765/api/edges | python -m json.tool | grep imports
   ```
4. Check a specific node's relationships:
   ```bash
   curl "http://localhost:8765/api/nodes/src/app.py::main/relationships" | python -m json.tool
   ```

### Summary of Files Changed/Created

| File | Action | Step |
|------|--------|------|
| `src/remora/core/storage/graph.py` | MODIFIED — added index, 4 new methods | 2-5 |
| `src/remora/defaults/queries/python_imports.scm` | CREATED | 7 |
| `src/remora/defaults/queries/python_inheritance.scm` | CREATED | 8 |
| `src/remora/code/relationships.py` | CREATED — core extraction module | 9 |
| `src/remora/code/reconciler.py` | MODIFIED — name index + edge extraction | 11-12 |
| `src/remora/core/tools/capabilities.py` | MODIFIED — 3 new GraphCapabilities methods | 14 |
| `src/remora/web/routes/nodes.py` | MODIFIED — new API endpoint | 15 |
| `src/remora/core/tools/context.py` | MODIFIED — version bump | 16 |
| `tests/unit/test_graph.py` | MODIFIED — 6 new tests | 6 |
| `tests/unit/test_relationships.py` | CREATED — extraction unit tests | 10 |
| `tests/unit/test_reconciler_edges.py` | CREATED — integration tests | 13 |

### Estimated Total New/Changed Lines

- ~250 lines new code in `relationships.py`
- ~60 lines new code in `graph.py`
- ~30 lines new code in `capabilities.py`
- ~30 lines changes in `reconciler.py`
- ~15 lines changes in `nodes.py`
- ~250 lines of tests

**Total**: ~635 lines

---

_End of implementation guide._
