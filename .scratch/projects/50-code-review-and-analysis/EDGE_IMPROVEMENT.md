# Edge Improvement Analysis

> Investigation of cross-file relationship extraction beyond parent/child edges.
> Examines what the current edge system supports, what relationships could be extracted
> via tree-sitter, and how to populate the existing `edges` table with richer data.

---

## Table of Contents

1. **[Current Edge System](#1-current-edge-system)** — What exists today.
2. **[Gap Analysis](#2-gap-analysis)** — What's missing and why it matters.
3. **[Relationship Types to Extract](#3-relationship-types-to-extract)** — Concrete edge types.
4. **[Tree-Sitter Extraction Strategy](#4-tree-sitter-extraction-strategy)** — How to extract each type.
5. **[Schema and Storage](#5-schema-and-storage)** — Changes to the edges table and NodeStore.
6. **[Reconciler Integration](#6-reconciler-integration)** — Where extraction plugs in.
7. **[Capability Exposure](#7-capability-exposure)** — New graph queries for agents.
8. **[Implementation Plan](#8-implementation-plan)** — Step-by-step build order.
9. **[Trade-offs and Risks](#9-trade-offs-and-risks)** — What could go wrong.
10. **[Impact Assessment](#10-impact-assessment)** — Value delivered.

---

## 1. Current Edge System

### Schema

The `edges` table already exists and is general-purpose:

```sql
CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id TEXT NOT NULL,
    to_id TEXT NOT NULL,
    edge_type TEXT NOT NULL,
    UNIQUE(from_id, to_id, edge_type)
);
CREATE INDEX IF NOT EXISTS idx_edges_from ON edges(from_id);
CREATE INDEX IF NOT EXISTS idx_edges_to ON edges(to_id);
```

### Current Usage

- **Edge type**: Only `"contains"` (parent → child) edges are ever created.
- **Created in**: `FileReconciler._reconcile_events()` at `reconciler.py:296`:
  ```python
  await self._node_store.add_edge(node.parent_id, node.node_id, "contains")
  ```
- **Queried via**: `NodeStore.get_edges(node_id, direction)` and `GraphCapabilities.graph_get_edges(target_id)`.
- **Deleted**: Automatically when a node is deleted (`delete_node` cleans edges).

### API Surface

- `GET /api/nodes/{id}/edges` — returns edges for a node.
- `graph_get_edges(target_id)` — tool external available to agents.
- `graph_get_children(parent_id)` — uses `parent_id` column, not edges.

### Key Observation

The infrastructure for arbitrary edge types is **already built**. The `edges` table has a string `edge_type` column, `NodeStore` has full CRUD for edges, and `GraphCapabilities` exposes them to agents. The only missing piece is **populating edges beyond `contains`**.

---

## 2. Gap Analysis

### What's Missing

The code graph today is a **tree** (parent/child containment). Real codebases have a **graph** structure with cross-cutting relationships:

| Relationship | Example | Current State |
|---|---|---|
| Import/dependency | `from foo import Bar` → file `foo.py` | Not extracted |
| Function call | `bar()` inside `def baz()` | Not extracted |
| Class inheritance | `class Dog(Animal)` → `Animal` | Not extracted |
| Decorator usage | `@retry` on `def fetch()` | Not extracted |
| Type reference | `def f(x: Config)` → `Config` | Not extracted |

### Why It Matters

1. **Impact analysis**: When `class Config` changes, agents could automatically know which functions reference it and trigger targeted reviews.
2. **Context enrichment**: An agent reviewing `def fetch()` could automatically receive the source of `@retry` decorator and imported utilities.
3. **Dependency-aware prompting**: The prompt builder could include "this function calls X and Y" as context, making agent responses more accurate.
4. **Graph visualization**: The web UI could render a true dependency graph instead of a flat file tree.
5. **Subscription targeting**: Subscription patterns could filter by "changed node that is imported by my node" — currently impossible.

---

## 3. Relationship Types to Extract

### Priority 1: Import Edges (High Value, Moderate Complexity)

**Edge type**: `"imports"`

Python imports can be extracted from `import_statement` and `import_from_statement` AST nodes.

| Source | Target | Example |
|---|---|---|
| File node or function node | Target module/file node | `from remora.core.model.node import Node` |

**Resolution challenge**: Import paths must be resolved to file paths and then to node IDs. `from remora.core.model.node import Node` → `src/remora/core/model/node.py::Node`.

### Priority 2: Inheritance Edges (High Value, Low Complexity)

**Edge type**: `"inherits"`

Class inheritance is explicit in the AST: `class Dog(Animal)` has an `argument_list` containing `Animal`.

| Source | Target | Example |
|---|---|---|
| Class node | Base class node | `class NodeStore` → (implicit `object`) |

**Resolution**: The base class name must be matched to a known node ID. This requires a name → node_id index.

### Priority 3: Call Edges (Medium Value, High Complexity)

**Edge type**: `"calls"`

Function calls within a function body: `def baz(): bar()` → edge from `baz` to `bar`.

**Resolution challenge**: Call targets must be resolved through imports and scope chains. `self.method()` requires class context. This is the most complex relationship to extract accurately.

### Priority 4: Decorator Edges (Medium Value, Low Complexity)

**Edge type**: `"decorated_by"`

The `decorated_definition` AST node already wraps `decorator` children with the decorator name.

| Source | Target | Example |
|---|---|---|
| Function/class node | Decorator function node | `@retry` on `def fetch()` → `retry` |

### Priority 5: Type Reference Edges (Low Value, Medium Complexity)

**Edge type**: `"references_type"`

Type annotations in function signatures: `def f(x: Config)` → `Config`.

**Resolution**: Similar to imports — must resolve type names to node IDs.

---

## 4. Tree-Sitter Extraction Strategy

### Approach: Separate Query Files per Edge Type

Rather than cramming everything into `python.scm`, create additional query files:

```
src/remora/defaults/queries/
├── python.scm              # Existing: node discovery
├── python_imports.scm      # NEW: import extraction
├── python_inheritance.scm  # NEW: class base extraction
├── python_decorators.scm   # NEW: decorator extraction
```

### Import Query (`python_imports.scm`)

```scheme
; Standard imports: import foo
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
```

### Inheritance Query (`python_inheritance.scm`)

```scheme
; Class with base classes
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

### Decorator Query (`python_decorators.scm`)

```scheme
; Simple decorator: @foo
(decorator
  (identifier) @decorator.name) @decorator

; Dotted decorator: @foo.bar
(decorator
  (attribute
    attribute: (identifier) @decorator.name)) @decorator

; Called decorator: @foo(args)
(decorator
  (call
    function: (identifier) @decorator.name)) @decorator
```

### Resolution Pipeline

Raw tree-sitter captures give us **names**, not **node IDs**. A resolution step is needed:

```
Parse file → extract import names → resolve to file paths → resolve to node IDs
```

#### Import Resolution

```python
def resolve_import_to_file(
    import_path: str,
    project_root: Path,
    source_file: Path,
) -> Path | None:
    """Resolve 'remora.core.model.node' to 'src/remora/core/model/node.py'."""
    parts = import_path.split(".")
    # Try as package path
    candidate = project_root / "src" / Path(*parts)
    if candidate.with_suffix(".py").exists():
        return candidate.with_suffix(".py")
    if (candidate / "__init__.py").exists():
        return candidate / "__init__.py"
    # Relative imports
    if import_path.startswith("."):
        ...
    return None
```

#### Name-to-NodeID Index

For inheritance and call edges, build an in-memory index during reconciliation:

```python
# Built during reconcile_cycle from existing nodes
name_index: dict[str, list[str]] = {}  # name → [node_id, ...]
# "Node" → ["src/remora/core/model/node.py::Node"]
# "EventBus" → ["src/remora/core/events/bus.py::EventBus"]
```

This index allows `class Dog(Animal)` to resolve `"Animal"` → `"src/remora/animals.py::Animal"`.

---

## 5. Schema and Storage

### No Schema Changes Needed

The existing `edges` table already supports arbitrary edge types via the `edge_type TEXT` column. New edge types (`imports`, `inherits`, `decorated_by`, `calls`) are just new string values.

### New NodeStore Methods

Add convenience queries to `src/remora/core/storage/graph.py`:

```python
async def get_edges_by_type(
    self, node_id: str, edge_type: str, direction: str = "both"
) -> list[Edge]:
    """Get edges of a specific type for a node."""
    ...

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

async def delete_edges_by_type(
    self, node_id: str, edge_type: str
) -> int:
    """Delete all edges of a type involving a node. Used during re-extraction."""
    cursor = await self._db.execute(
        "DELETE FROM edges WHERE (from_id = ? OR to_id = ?) AND edge_type = ?",
        (node_id, node_id, edge_type),
    )
    await self._maybe_commit()
    return cursor.rowcount
```

### Index Addition

Add a composite index for type-filtered queries:

```sql
CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(edge_type);
```

---

## 6. Reconciler Integration

### Where to Extract

Edge extraction should happen in `FileReconciler._do_reconcile_file`, after node discovery and upsert but before event emission. This ensures edges are consistent with the current node set.

### Extraction Flow

```
1. discover() → nodes (existing)
2. upsert nodes (existing)
3. extract_relationships(source_bytes, plugin, projected_nodes) → raw edges  (NEW)
4. resolve_edges(raw_edges, name_index) → resolved edges  (NEW)
5. delete old cross-file edges for this file  (NEW)
6. insert new edges  (NEW)
7. emit events (existing)
```

### New Module: `src/remora/code/relationships.py`

```python
"""Cross-file relationship extraction from tree-sitter AST."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tree_sitter import Parser, Query, QueryCursor

from remora.code.languages import LanguagePlugin
from remora.core.model.node import Node


@dataclass
class RawRelationship:
    """An unresolved relationship between source elements."""
    source_node_id: str
    target_name: str
    edge_type: str  # "imports", "inherits", "decorated_by", "calls"
    target_module: str | None = None  # For imports: "remora.core.model.node"


@dataclass
class ResolvedEdge:
    """A resolved edge ready for storage."""
    from_id: str
    to_id: str
    edge_type: str


def extract_imports(
    source_bytes: bytes,
    plugin: LanguagePlugin,
    file_path: str,
    nodes: list[Node],
    query_paths: list[Path],
) -> list[RawRelationship]:
    """Extract import relationships from a source file."""
    ...


def extract_inheritance(
    source_bytes: bytes,
    plugin: LanguagePlugin,
    file_path: str,
    nodes: list[Node],
    query_paths: list[Path],
) -> list[RawRelationship]:
    """Extract class inheritance relationships."""
    ...


def resolve_relationships(
    raw: list[RawRelationship],
    name_index: dict[str, list[str]],
    project_root: Path,
) -> list[ResolvedEdge]:
    """Resolve raw relationship targets to node IDs."""
    ...
```

### Name Index Maintenance

The name index maps short names to node IDs across the entire graph. It must be rebuilt or incrementally updated during reconciliation:

```python
# In FileReconciler.__init__:
self._name_index: dict[str, list[str]] = {}

# In _do_reconcile_file, after upserting nodes:
for node in projected:
    self._name_index.setdefault(node.name, []).append(node.node_id)
    # Also index full_name for qualified lookups
    self._name_index.setdefault(node.full_name, []).append(node.node_id)
```

On node removal:
```python
# In _remove_node:
if node.name in self._name_index:
    self._name_index[node.name] = [
        nid for nid in self._name_index[node.name] if nid != node_id
    ]
```

---

## 7. Capability Exposure

### New Agent Externals

Add to `GraphCapabilities` in `src/remora/core/tools/capabilities.py`:

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

### Updated `to_dict`

```python
def to_dict(self) -> dict[str, Any]:
    return {
        "graph_get_node": self.graph_get_node,
        "graph_query_nodes": self.graph_query_nodes,
        "graph_get_edges": self.graph_get_edges,
        "graph_get_children": self.graph_get_children,
        "graph_set_status": self.graph_set_status,
        "graph_get_importers": self.graph_get_importers,         # NEW
        "graph_get_dependencies": self.graph_get_dependencies,   # NEW
        "graph_get_edges_by_type": self.graph_get_edges_by_type, # NEW
    }
```

### Bump `EXTERNALS_VERSION`

In `src/remora/core/tools/context.py`:
```python
EXTERNALS_VERSION = 3  # was 2
```

Update bundle `externals_version` in `bundle.yaml` files that need the new capabilities.

### New API Endpoint

Add to `src/remora/web/routes/nodes.py`:

```python
async def api_node_relationships(request: Request) -> JSONResponse:
    """Get cross-file relationships for a node."""
    deps = _deps_from_request(request)
    node_id = request.path_params["node_id"]
    edge_type = request.query_params.get("type")

    if edge_type:
        edges = await deps.node_store.get_edges_by_type(node_id, edge_type)
    else:
        edges = await deps.node_store.get_edges(node_id)

    return JSONResponse([
        {"from_id": e.from_id, "to_id": e.to_id, "edge_type": e.edge_type}
        for e in edges
    ])
```

---

## 8. Implementation Plan

### Phase 1: Import Edges (Recommended First)

Imports are the highest-value, most-reliable relationship to extract. They're explicit in the AST and have well-defined resolution rules.

**Steps**:
1. Write `python_imports.scm` query file
2. Create `src/remora/code/relationships.py` with `extract_imports()` and `resolve_relationships()`
3. Add import resolution logic (dotted path → file path → node ID)
4. Add name index to `FileReconciler`
5. Call extraction in `_do_reconcile_file` after node upsert
6. Add `delete_edges_by_type` to clear stale import edges before re-inserting
7. Add `get_importers`/`get_dependencies` to `NodeStore`
8. Expose via `GraphCapabilities`
9. Add tests for extraction, resolution, and reconciler integration
10. Bump `EXTERNALS_VERSION`

**Estimated scope**: ~300 lines of new code + ~150 lines of tests.

### Phase 2: Inheritance Edges

**Steps**:
1. Write `python_inheritance.scm` query file
2. Add `extract_inheritance()` to `relationships.py`
3. Resolve base class names via name index
4. Insert `"inherits"` edges in reconciler
5. Add tests

**Estimated scope**: ~100 lines of new code + ~50 lines of tests.

### Phase 3: Decorator Edges (IGNORE FOR NOW)

**Steps**:
1. Write `python_decorators.scm` query file
2. Add `extract_decorators()` to `relationships.py`
3. Resolve decorator names via name index
4. Insert `"decorated_by"` edges in reconciler
5. Add tests

**Estimated scope**: ~80 lines of new code + ~50 lines of tests.

### Phase 4: Call Edges (Optional, High Complexity)

Call edges require scope-aware resolution (what does `self.foo()` refer to? what about `bar.baz()`?). Recommend deferring until Phases 1-3 prove the pattern.

---

## 9. Trade-offs and Risks

### Performance

| Concern | Mitigation |
|---|---|
| Extra tree-sitter parse per file | Reuse the already-parsed tree from discovery |
| Name index memory | Bounded by node count; ~10KB for 1000 nodes |
| Edge insertion I/O | Batched within existing transaction context |
| Resolution cost | O(1) dict lookup per relationship |

### Accuracy

| Concern | Mitigation |
|---|---|
| Import resolution failures (third-party, dynamic imports) | Store unresolved edges with `to_id = "unresolved:name"` or skip |
| Name collisions (two classes named `Config`) | `name_index` maps to `list[str]`; create edges to all candidates or use file proximity |
| Dynamic imports (`importlib.import_module`) | Skip — not extractable from AST |
| Star imports (`from foo import *`) | Create edge to module, not individual names |

### Stale Edges

When a file is re-reconciled, its cross-file edges may be stale. The reconciler must:
1. Delete all non-`contains` edges where `from_id` belongs to nodes in this file
2. Re-extract and re-insert

This is the `delete_edges_by_type` → `add_edge` cycle described in Phase 1 Step 6.

### Backward Compatibility

- The `edges` table schema is unchanged — no migration needed.
- Existing `contains` edges are unaffected.
- New edge types are additive.
- `EXTERNALS_VERSION` bump means old bundles won't try to use new capabilities.

---

## 10. Impact Assessment

### Value by Phase

| Phase | Edge Type | Agent Value | Prompt Value | UI Value |
|---|---|---|---|---|
| 1: Imports | `imports` | **High** — "what depends on this?" queries | **High** — auto-include dependency context | **High** — dependency graph visualization |
| 2: Inheritance | `inherits` | **Medium** — class hierarchy queries | **Medium** — include base class in reviews | **Medium** — class tree view |
| 3: Decorators | `decorated_by` | **Low** — decorator awareness | **Low** — include decorator source | **Low** — decorator annotations |
| 4: Calls | `calls` | **Medium** — call graph queries | **High** — include callers/callees in context | **High** — call graph visualization |

### Subscription Enhancement

With import edges, subscription patterns could gain a new field:

```yaml
subscriptions:
  - event_types: [node_changed]
    imports_from: true  # trigger when a node I import changes
```

This enables **dependency-aware reactive triggers** — an agent reviewing `handler.py` would automatically re-trigger when `utils.py` (which `handler.py` imports) changes, without requiring a broad `path_glob: "src/**"` pattern.

### Prompt Builder Enhancement

The `PromptBuilder` could automatically include dependency context:

```python
# In build_user_prompt, after node source:
importers = await node_store.get_importers(node_id)
dependencies = await node_store.get_dependencies(node_id)
if dependencies:
    dep_context = "This code depends on: " + ", ".join(dependencies[:10])
    prompt += f"\n\n{dep_context}"
```

### Summary

The edge system infrastructure is already built. The gap is purely in **extraction and population**. Phase 1 (import edges) delivers the highest value with moderate complexity and proves the pattern for subsequent phases. The existing `edges` table, `NodeStore` methods, and `GraphCapabilities` external make this a natural extension rather than a new subsystem.

---

_End of edge improvement analysis._
