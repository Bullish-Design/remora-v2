# Directory Node Agent — Implementation Recommendation

## Executive Summary

Directory nodes should be first-class `CodeNode` entries with a new `NodeType.DIRECTORY` value, materialized during reconciliation from the file paths already being scanned. They use the same actor/outbox/subscription infrastructure as every other node — no special runtime paths. A new `directory-agent` bundle gives them behavior via `.pym` tools, and the reconciler grows a small directory-materialization step that runs before file discovery.

The key insight: **directories are not discovered by tree-sitter — they are implied by the files that are**. The reconciler already walks every source file. It already knows every directory. It just doesn't persist them yet.

---

## 1. Node Identity & ID Scheme

### Directory node IDs

Use the directory's relative path from project root as the node ID:

```
src/remora/core/          → node_id: "src/remora/core"
src/remora/               → node_id: "src/remora"
src/                      → node_id: "src"
.                         → node_id: "."   (project root)
```

Rationale:
- File node IDs already use `file_path::QualifiedName`. Directories have no `::` component — they're cleanly distinguishable.
- Relative paths are stable across machines (unlike absolute paths).
- The root node is always `"."` — a single canonical entrypoint per project.

### `parent_id` linkage

Directory nodes chain upward via `parent_id`:
```
"src/remora/core"  →  parent_id: "src/remora"
"src/remora"       →  parent_id: "src"
"src"              →  parent_id: "."
"."                →  parent_id: None
```

File nodes already have `parent_id` for intra-file hierarchy (class → method). We extend this: **file-level code nodes** (functions, classes at module level — those with `parent_id = None`) get their `parent_id` set to their containing directory node.

This means `parent_id` serves double duty, which is intentional — it's the single "containment" relationship regardless of whether the container is a class or a directory. Agents can walk `parent_id` upward to reach the project root from any node in the graph.

---

## 2. Data Model Changes

### `NodeType` enum (types.py)

Add one value:

```python
class NodeType(str, Enum):
    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"
    SECTION = "section"
    TABLE = "table"
    DIRECTORY = "directory"   # ← new
```

### `CodeNode` model (node.py)

No structural changes needed. `CodeNode` already has every field a directory node needs:

| Field | Directory value |
|-------|----------------|
| `node_id` | `"src/remora/core"` |
| `node_type` | `"directory"` |
| `name` | `"core"` (basename) |
| `full_name` | `"src/remora/core"` (relative path) |
| `file_path` | `"src/remora/core"` (the directory path itself) |
| `start_line` | `0` |
| `end_line` | `0` |
| `source_code` | `""` (empty — directories have no source) |
| `source_hash` | hash of sorted child listing (for change detection) |
| `parent_id` | `"src/remora"` |
| `bundle_name` | `"directory-agent"` |

The `source_hash` for directories is a hash of their sorted immediate children (file names + subdirectory names). This gives us change detection for free — when files are added/removed from a directory, its hash changes and triggers a `NodeChangedEvent`.

### `NodeStore.list_nodes()` (graph.py)

Already supports `node_type` filtering — `list_nodes(node_type="directory")` works out of the box.

Add one convenience query:

```python
async def get_children(self, parent_id: str) -> list[CodeNode]:
    """Get all nodes whose parent_id matches."""
    rows = await self._db.fetch_all(
        "SELECT * FROM nodes WHERE parent_id = ? ORDER BY node_id ASC",
        (parent_id,),
    )
    return [CodeNode.from_row(row) for row in rows]
```

Add a `parent_id` index to the schema:

```sql
CREATE INDEX IF NOT EXISTS idx_nodes_parent ON nodes(parent_id);
```

---

## 3. Reconciler Changes

### New: `_materialize_directories()`

Add a method to `FileReconciler` that runs **before** file discovery in each reconcile cycle. It:

1. Collects all unique directory paths from the files being scanned.
2. Builds the full ancestor chain up to (and including) `"."`.
3. For each directory path, computes a `source_hash` from its sorted immediate children.
4. Upserts the directory `CodeNode` if it's new or its hash changed.
5. Emits `NodeDiscoveredEvent` / `NodeChangedEvent` / `NodeRemovedEvent` as appropriate.

```python
async def _materialize_directories(self, file_paths: set[str]) -> None:
    """Derive directory nodes from the set of discovered file paths."""
    # Collect all directory paths (including ancestors up to root)
    dir_paths: set[str] = {"."}
    for fp in file_paths:
        rel = Path(fp).relative_to(self._project_root)
        for ancestor in [rel.parent, *rel.parent.parents]:
            dir_path = str(ancestor) if str(ancestor) != "." else "."
            dir_paths.add(dir_path if dir_path != "." else ".")

    # Compute children hash for each directory
    for dir_path in sorted(dir_paths):
        children = sorted(
            name for name in dir_paths | file_rel_paths
            if _parent_of(name) == dir_path
        )
        source_hash = hashlib.sha256(
            "\n".join(children).encode()
        ).hexdigest()

        # Upsert directory node with change detection
        ...
```

### Modify: `_reconcile_file()` — set file-level `parent_id`

After projecting code nodes from a file, set `parent_id` on top-level nodes (those with `parent_id = None`) to the file's containing directory node ID:

```python
dir_node_id = str(Path(file_path).relative_to(self._project_root).parent)
if dir_node_id == ".":
    dir_node_id = "."
for node in projected:
    if node.parent_id is None:
        node.parent_id = dir_node_id
        await self._node_store.upsert_node(node)
```

### Modify: `reconcile_cycle()` — call directory materialization

```python
async def reconcile_cycle(self) -> None:
    current_mtimes = self._collect_file_mtimes()
    await self._materialize_directories(set(current_mtimes.keys()))
    # ... existing file reconciliation continues unchanged ...
```

### Handle directory removal

When a reconcile cycle detects that a directory no longer has any children, remove its node and emit `NodeRemovedEvent`. This happens naturally: if all files in a directory are deleted, the next `_materialize_directories()` call won't include that directory path, and we diff against the previous set.

---

## 4. Bundle: `directory-agent`

Create `bundles/directory-agent/` with a bundle config and `.pym` tools tailored to directory-level awareness.

### `bundle.yaml`

```yaml
name: directory-agent
system_prompt: |
  You are an autonomous AI agent embodying a directory in a codebase.
  You have awareness of your child files and subdirectories, and your
  parent directory (if any).

  Your responsibilities:
  1. Maintain awareness of structural changes in your directory.
  2. Coordinate with child nodes when cross-cutting changes occur.
  3. Respond to queries about your directory's contents and organization.

  You do NOT have source code — you are a structural organizer.
model: "${REMORA_MODEL:-Qwen/Qwen3-4B}"
max_turns: 6
```

### Tools (`.pym` scripts)

**`list_children.pym`** — List immediate children (files and subdirectories):

```python
from grail import external

@external
async def graph_query_nodes(node_type=None, status=None, file_path=None) -> list: ...

@external
async def my_node_id() -> str: ...

node_id = my_node_id
children = await graph_query_nodes()
my_children = [n for n in children if n.get("parent_id") == node_id]
lines = [f"- [{c['node_type']}] {c['name']} ({c['node_id']})" for c in my_children]
return "Children:\n" + "\n".join(lines) if lines else "No children found."
```

**`get_parent.pym`** — Navigate to parent directory:

```python
from grail import external

@external
async def graph_get_node(target_id: str) -> dict: ...

@external
async def my_node_id() -> str: ...

# Get self to find parent_id
self_node = await graph_get_node(my_node_id)
parent_id = self_node.get("parent_id")
if not parent_id:
    return "This is the root directory — no parent."
parent = await graph_get_node(parent_id)
return f"Parent: {parent.get('name', '?')} ({parent_id})" if parent else "Parent not found."
```

**`summarize_tree.pym`** — Recursively summarize the subtree:

```python
from grail import Input, external

max_depth: int = Input("max_depth", default=3)

@external
async def graph_query_nodes(node_type=None, status=None, file_path=None) -> list: ...

@external
async def my_node_id() -> str: ...

all_nodes = await graph_query_nodes()
by_parent = {}
for n in all_nodes:
    pid = n.get("parent_id")
    if pid:
        by_parent.setdefault(pid, []).append(n)

def render(node_id, depth=0):
    if depth > max_depth:
        return ["  " * depth + "..."]
    children = by_parent.get(node_id, [])
    lines = []
    for c in sorted(children, key=lambda x: x["name"]):
        prefix = "  " * depth
        lines.append(f"{prefix}- [{c['node_type']}] {c['name']}")
        if c["node_type"] == "directory":
            lines.extend(render(c["node_id"], depth + 1))
    return lines

tree_lines = render(my_node_id)
return "Directory tree:\n" + "\n".join(tree_lines) if tree_lines else "Empty directory."
```

**`broadcast_children.pym`** — Send a message to all immediate child agents:

```python
from grail import Input, external

message: str = Input("message")

@external
async def graph_query_nodes(node_type=None, status=None, file_path=None) -> list: ...

@external
async def send_message(to_node_id: str, content: str) -> bool: ...

@external
async def my_node_id() -> str: ...

all_nodes = await graph_query_nodes()
children = [n for n in all_nodes if n.get("parent_id") == my_node_id]
count = 0
for child in children:
    await send_message(child["node_id"], message)
    count += 1
return f"Broadcast sent to {count} children."
```

### Config mapping

Add to `bundle_mapping` in config:

```yaml
bundle_mapping:
  function: "code-agent"
  class: "code-agent"
  method: "code-agent"
  directory: "directory-agent"   # ← new
```

---

## 5. Subscriptions for Directory Nodes

Directory nodes should subscribe to structural events in their subtree. During `_register_subscriptions()` for a directory node:

```python
# Direct messages to this directory
SubscriptionPattern(to_agent=node.node_id)

# Node discovery/removal anywhere under this directory's path
SubscriptionPattern(
    event_types=["NodeDiscoveredEvent", "NodeRemovedEvent", "NodeChangedEvent"],
    path_glob=f"{node.file_path}/*" if node.file_path != "." else "*",
)

# Content changes in files under this directory
SubscriptionPattern(
    event_types=["ContentChangedEvent"],
    path_glob=f"{node.file_path}/*" if node.file_path != "." else "*",
)
```

This means directory agents get triggered when:
- Files are added/removed/changed in their subtree
- Another agent sends them a direct message
- Content changes happen in their subtree

The root node (`"."`) sees everything — it's the project-level orchestrator.

---

## 6. AgentContext Additions

Add one new external to `AgentContext` for hierarchy traversal:

```python
async def graph_get_children(self, parent_id: str | None = None) -> list[dict[str, Any]]:
    """Get child nodes. Defaults to current node's children."""
    target = parent_id or self.node_id
    children = await self._node_store.get_children(target)
    return [node.model_dump() for node in children]
```

And expose it in `to_externals_dict()`:

```python
"graph_get_children": self.graph_get_children,
```

This is the minimal addition. The `.pym` tools can already do hierarchy traversal via `graph_query_nodes()` + filtering on `parent_id`, but `graph_get_children` makes it a first-class indexed query.

---

## 7. Actor Prompt Adaptation

In `AgentActor._build_prompt()`, the prompt currently shows source code. For directory nodes (`source_code == ""`), adapt the prompt to show structural context instead:

```python
@staticmethod
def _build_prompt(node: CodeNode, trigger: Trigger) -> str:
    parts = [
        f"# Node: {node.full_name}",
        f"Type: {node.node_type} | File: {node.file_path}",
    ]

    if node.source_code:
        parts.extend(["", "## Source Code", "```", node.source_code, "```"])
    else:
        parts.extend([
            "",
            "## Structure",
            "This is a directory node. Use your tools to inspect children and subtree.",
        ])

    if trigger.event is not None:
        parts.extend(["", "## Trigger", f"Event: {trigger.event.event_type}"])
        content = _event_content(trigger.event)
        if content:
            parts.append(f"Content: {content}")

    return "\n".join(parts)
```

---

## 8. What We Do NOT Change

These parts of the architecture remain untouched:

- **`AgentActor`**: Directory nodes are regular actors. No subclass, no special-case.
- **`AgentRunner`**: Lazily creates actors for directory nodes the same as any other.
- **`EventStore` / `EventBus` / `TriggerDispatcher`**: All work unchanged.
- **`Outbox`**: Directory actors emit events through the same write-through outbox.
- **`CairnWorkspaceService`**: Directory agents get workspaces like any other node.
- **Tree-sitter discovery**: Unchanged. Directories aren't discovered by tree-sitter — they're materialized from the file set.

---

## 9. Implementation Order

1. **`NodeType.DIRECTORY`** — Add the enum value to `types.py`.

2. **`NodeStore.get_children()`** — Add the indexed query to `graph.py` (+ schema index).

3. **`AgentContext.graph_get_children()`** — Add the external to `externals.py`.

4. **`FileReconciler._materialize_directories()`** — The core logic. Derive directory nodes from file paths, upsert with change detection, emit events.

5. **`FileReconciler._reconcile_file()` update** — Set `parent_id` on top-level code nodes to their containing directory.

6. **`FileReconciler._register_subscriptions()` update** — Add directory-specific subscription patterns.

7. **`bundles/directory-agent/`** — Create the bundle with `bundle.yaml` and `.pym` tools.

8. **`Config.bundle_mapping`** — Add `"directory": "directory-agent"`.

9. **`AgentActor._build_prompt()`** — Adapt for nodes without source code.

10. **Tests** — Unit tests for directory materialization, parent linkage, subscription patterns, and the children query. Integration test for the full reconcile → directory node → actor lifecycle.

---

## 10. Architectural Alignment Assessment

### What the intern got right:
- Root directory as project entrypoint ✓
- Directories as first-class CodeNode entries (not a new model) ✓
- Parent-child chaining via `parent_id` ✓
- Incremental discovery from existing reconciliation ✓
- Actor model for execution ✓

### What this recommendation does differently:
- **ID scheme**: Uses relative paths (not file_path::name) — cleaner, no collision with code node IDs.
- **Source hash**: Hashes directory contents listing instead of leaving it empty — enables change detection.
- **No `contains` edges**: Uses `parent_id` exclusively for hierarchy, not edges. Edges are for cross-cutting relationships (calls, imports, references). Containment is structural and `parent_id` handles it with a simple indexed column query. Mixing containment into the edge table would conflate two different relationship semantics.
- **Subscriptions via path_glob**: Directory agents subscribe to subtree events using `path_glob`, which already exists in `SubscriptionPattern`. No new subscription mechanism needed.
- **`.pym` tools for awareness**: The intern's plan says "directory awareness contract" but doesn't specify how. This recommendation pushes all awareness to `.pym` tools — `list_children`, `get_parent`, `summarize_tree` — which is fully aligned with remora's "push functionality to agent tools" philosophy.
- **Minimal core changes**: Only three small additions to core (enum value, `get_children` query, `graph_get_children` external). Everything else is reconciler logic and bundle config. The core stays lean.

### Risks and mitigations:
- **Root node trigger storm**: The `"."` node subscribes to everything. Mitigation: existing cooldown (`trigger_cooldown_ms`) and depth limits (`max_trigger_depth`) on the actor already prevent runaway execution.
- **Large directories**: A directory with 500 files gets a `source_hash` from 500 entries. This is fine — it's a single SHA256 call, not an LLM call. The directory agent only triggers when the hash changes, not on every reconcile.
- **Nested project structures**: Monorepos with multiple `discovery_paths` — each path gets its own directory tree, all rooting at `"."`. The root node sees the union. This is correct behavior.

---

## 11. Summary of File Changes

| File | Change |
|------|--------|
| `src/remora/core/types.py` | Add `DIRECTORY = "directory"` to `NodeType` |
| `src/remora/core/graph.py` | Add `get_children()` method + `idx_nodes_parent` index |
| `src/remora/core/externals.py` | Add `graph_get_children()` external |
| `src/remora/core/actor.py` | Adapt `_build_prompt()` for empty source_code |
| `src/remora/core/config.py` | Add `"directory": "directory-agent"` to default `bundle_mapping` |
| `src/remora/code/reconciler.py` | Add `_materialize_directories()`, update `reconcile_cycle()` and `_reconcile_file()` and `_register_subscriptions()` |
| `bundles/directory-agent/bundle.yaml` | New file |
| `bundles/directory-agent/tools/*.pym` | New files (4 tools) |
| `tests/unit/test_reconciler.py` | New tests for directory materialization |
| `tests/unit/test_graph.py` | New tests for `get_children()` |
| `tests/unit/test_externals.py` | New test for `graph_get_children()` |

No new modules. No new base classes. No new runtime paths. The directory node is just another node that happens to have `node_type = "directory"` and `source_code = ""`.
