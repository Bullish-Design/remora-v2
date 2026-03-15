# Remora Externals API Reference

## Table of Contents

1. Overview
2. Function Inventory
3. File Operations
4. Key-Value Store
5. Graph Operations
6. Event Operations
7. Messaging
8. Code Modification
9. Self Introspection

## 1. Overview

This document describes the external functions available to Grail `.pym` tool scripts through `TurnContext.to_capabilities_dict()`.

Current exported function count: **25**.

Each function below includes:

- Signature
- Description
- Example
- Notes

## 2. Function Inventory

| Category | Functions |
|---|---|
| File Operations | `read_file`, `write_file`, `list_dir`, `file_exists`, `search_files`, `search_content` |
| KV Store | `kv_get`, `kv_set`, `kv_delete`, `kv_list` |
| Graph | `graph_get_node`, `graph_query_nodes`, `graph_get_edges`, `graph_get_children`, `graph_set_status` |
| Events | `event_emit`, `event_subscribe`, `event_unsubscribe`, `event_get_history` |
| Messaging | `send_message`, `broadcast` |
| Code Modification | `apply_rewrite`, `get_node_source` |
| Self Introspection | `my_node_id`, `my_correlation_id` |

## 3. File Operations

### `read_file(path: str) -> str`

Reads a file from the current agent workspace.

```python
from grail import Input, external

path: str = Input("path")

@external
async def read_file(path: str) -> str: ...

result = await read_file(path)
result
```

Notes: Raises an error if the file does not exist.

### `write_file(path: str, content: str) -> bool`

Writes text content to a workspace file.

```python
@external
async def write_file(path: str, content: str) -> bool: ...

ok = await write_file("notes/todo.md", "# TODO\n")
result = "written" if ok else "failed"
result
```

Notes: Returns `True` on success.

### `list_dir(path: str = ".") -> list[str]`

Lists entries in a workspace directory.

```python
@external
async def list_dir(path: str = ".") -> list[str]: ...

entries = await list_dir("_bundle/tools")
result = "\n".join(entries)
result
```

Notes: Entries are returned sorted.

### `file_exists(path: str) -> bool`

Checks whether a workspace path exists.

```python
@external
async def file_exists(path: str) -> bool: ...

exists = await file_exists("_bundle/bundle.yaml")
result = "yes" if exists else "no"
result
```

### `search_files(pattern: str) -> list[str]`

Finds file paths that contain the provided pattern.

```python
@external
async def search_files(pattern: str) -> list[str]: ...

paths = await search_files("test")
result = paths
result
```

Notes: Pattern matching is substring-based against all workspace paths.

### `search_content(pattern: str, path: str = ".") -> list[dict[str, Any]]`

Searches file contents for matching lines.

```python
@external
async def search_content(pattern: str, path: str = ".") -> list[dict]: ...

hits = await search_content("TODO", path="src")
result = hits
result
```

Notes: Returns records shaped as `{"file": ..., "line": ..., "text": ...}`.

## 4. Key-Value Store

### `kv_get(key: str) -> Any | None`

Reads a KV value from the agent workspace.

```python
@external
async def kv_get(key: str): ...

value = await kv_get("memory:last_review")
result = value or "missing"
result
```

### `kv_set(key: str, value: Any) -> bool`

Writes a KV value.

```python
@external
async def kv_set(key: str, value): ...

ok = await kv_set("memory:last_review", "clean")
result = "ok" if ok else "failed"
result
```

### `kv_delete(key: str) -> bool`

Deletes a KV key.

```python
@external
async def kv_delete(key: str) -> bool: ...

result = await kv_delete("memory:last_review")
result
```

### `kv_list(prefix: str = "") -> list[str]`

Lists KV keys for a prefix.

```python
@external
async def kv_list(prefix: str = "") -> list[str]: ...

keys = await kv_list("memory:")
result = keys
result
```

## 5. Graph Operations

### `graph_get_node(target_id: str) -> dict[str, Any]`

Returns a node object by ID.

```python
@external
async def graph_get_node(target_id: str) -> dict: ...

node = await graph_get_node("src/app.py::run")
result = node
result
```

Notes: Returns `{}` when not found.

### `graph_query_nodes(node_type: str | None = None, status: str | None = None, file_path: str | None = None) -> list[dict[str, Any]]`

Queries nodes with optional filters.

```python
@external
async def graph_query_nodes(node_type: str | None = None, status: str | None = None, file_path: str | None = None) -> list[dict]: ...

nodes = await graph_query_nodes(node_type="function", status="idle")
result = nodes
result
```

Notes: Invalid `node_type` or `status` raises `ValueError`.

### `graph_get_edges(target_id: str) -> list[dict[str, Any]]`

Lists edges touching a node.

```python
@external
async def graph_get_edges(target_id: str) -> list[dict]: ...

edges = await graph_get_edges("src/app.py::run")
result = edges
result
```

### `graph_get_children(parent_id: str | None = None) -> list[dict[str, Any]]`

Returns child nodes of `parent_id`; defaults to current node.

```python
@external
async def graph_get_children(parent_id: str | None = None) -> list[dict]: ...

children = await graph_get_children()
result = children
result
```

### `graph_set_status(target_id: str, new_status: str) -> bool`

Sets node runtime status.

```python
@external
async def graph_set_status(target_id: str, new_status: str) -> bool: ...

ok = await graph_set_status("src/app.py::run", "idle")
result = ok
result
```

Notes: Intended for controlled coordination workflows.

## 6. Event Operations

### `event_emit(event_type: str, payload: dict[str, Any]) -> bool`

Emits a custom event tagged with the current correlation ID.

```python
@external
async def event_emit(event_type: str, payload: dict) -> bool: ...

ok = await event_emit("ScaffoldRequestEvent", {"intent": "add tests"})
result = ok
result
```

### `event_subscribe(event_types: list[str] | None = None, from_agents: list[str] | None = None, path_glob: str | None = None) -> int`

Creates a subscription pattern for the current agent.

```python
@external
async def event_subscribe(event_types: list[str] | None = None, from_agents: list[str] | None = None, path_glob: str | None = None) -> int: ...

sub_id = await event_subscribe(event_types=["NodeChangedEvent"], path_glob="src/**")
result = sub_id
result
```

### `event_unsubscribe(subscription_id: int) -> bool`

Removes a subscription by ID.

```python
@external
async def event_unsubscribe(subscription_id: int) -> bool: ...

result = await event_unsubscribe(123)
result
```

### `event_get_history(target_id: str, limit: int = 20) -> list[dict[str, Any]]`

Reads recent events involving an agent.

```python
@external
async def event_get_history(target_id: str, limit: int = 20) -> list[dict]: ...

history = await event_get_history("src/app.py::run", limit=10)
result = history
result
```

## 7. Messaging

### `send_message(to_node_id: str, content: str) -> bool`

Sends an `AgentMessageEvent` from the current node to another node (or `"user"`).

```python
@external
async def send_message(to_node_id: str, content: str) -> bool: ...

ok = await send_message("user", "Done.")
result = ok
result
```

### `broadcast(pattern: str, content: str) -> str`

Sends a message to multiple agents resolved by pattern.

```python
@external
async def broadcast(pattern: str, content: str) -> str: ...

summary = await broadcast("siblings", "Please re-check tests")
result = summary
result
```

Pattern behavior:

- `*` or `all`: all nodes except sender
- `siblings`: nodes with same `file_path`
- `file:<path>`: nodes in specific file
- fallback: substring match on `node_id`

## 8. Code Modification

### `apply_rewrite(new_source: str) -> bool`

Rewrites the current node's source in-place and emits `ContentChangedEvent`.

```python
@external
async def apply_rewrite(new_source: str) -> bool: ...

ok = await apply_rewrite("def fn():\n    return 42\n")
result = ok
result
```

Notes:

- Uses byte-range replacement when available.
- Falls back to first source-text replacement otherwise.
- Returns `False` if target node/file is unavailable.

### `get_node_source(target_id: str) -> str`

Returns source code for a node ID.

```python
@external
async def get_node_source(target_id: str) -> str: ...

source = await get_node_source("src/app.py::run")
result = source[:400]
result
```

## 9. Self Introspection

### `my_node_id() -> str`

Returns the current agent node ID.

```python
@external
async def my_node_id() -> str: ...

result = await my_node_id()
result
```

### `my_correlation_id() -> str | None`

Returns the current turn correlation ID.

```python
@external
async def my_correlation_id() -> str | None: ...

result = await my_correlation_id()
result
```

