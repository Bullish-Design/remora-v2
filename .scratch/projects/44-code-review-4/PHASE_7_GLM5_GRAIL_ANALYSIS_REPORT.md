# Grail Phase 7 Analysis Report

**Date:** 2026-03-18
**Project:** remora-v2
**Subject:** Critical issues with REVIEW_REFACTOR_GUIDE.md Phase 7 recommendations

---

## Executive Summary

Phase 7 of the REVIEW_REFACTOR_GUIDE.md recommends namespacing capability functions (e.g., `read_file` → `files.read_file`). **This recommendation is fundamentally incompatible with Grail's external function architecture and would break all existing .pym tool scripts.**

The guide correctly notes this concern with a TODO marker: "TODO: Does this work with Grail??" — the answer is **NO, it does not work.**

---

## Section 1: How Grail's External System Works

### 1.1 The `@external` Decorator

Grail v3.0.0 uses the `@external` decorator to declare functions that the host application provides at runtime:

```python
# In a .pym file
from grail import external, Input

@external
async def read_file(path: str) -> str:
    ...

content = await read_file("config.yaml")
```

Key points:
1. The `@external` decorator is a **no-op at runtime** — it exists purely for AST parsing
2. External function bodies must be `...` (Ellipsis) — no implementation
3. The parser extracts the function signature to generate type stubs
4. At runtime, the host passes implementations via `externals={"read_file": callable}`

### 1.2 Name Resolution in Grail

When `grail.load()` parses a .pym file (via `parser.py:extract_externals()`):

```python
externals[node.name] = ExternalSpec(
    name=node.name,  # <-- The function NAME is the key
    is_async=isinstance(node, ast.AsyncFunctionDef),
    parameters=params,
    ...
)
```

The external function's **name** becomes the dictionary key. The script code calls this function by its bare name:

```python
# Generated Monty code (after stripping @external declarations)
result = await read_file("path/to/file")  # Bare name, no namespace
```

### 1.3 Runtime Binding

When `GrailScript.run()` executes:

```python
# In script.py:418-530
result = await pydantic_monty.run_monty_async(
    monty,
    inputs=monty_inputs,
    external_functions=externals,  # <-- Dict of {name: callable}
    ...
)
```

The `externals` dict is keyed by the **bare function name**. The Monty sandbox resolves `await read_file(...)` by looking up `"read_file"` in this dict.

---

## Section 2: Why Phase 7's Namespacing Breaks Grail

### 2.1 The Guide's Recommendation

Phase 7 recommends:

```python
class FileCapabilities:
    def to_dict(self) -> dict[str, Any]:
        return {
            "files.read_file": self.read_file,  # Namespaced key
            "files.write_file": self.write_file,
            ...
        }
```

And suggests two options:
- **Option A:** Pass the flat namespaced dict as-is — tool scripts use `await capabilities["files.read_file"](...)`. (Called "Ugly")
- **Option B:** Pass capability group objects directly — tool scripts use `await files.read_file(...)`. (Called "Clean")

### 2.2 Why Option A Fails

If we namespace the capability dict keys:

```python
externals = {
    "files.read_file": <callable>,
    "files.write_file": <callable>,
    ...
}
```

The existing .pym scripts would still declare:

```python
@external
async def read_file(path: str) -> str: ...  # Bare name

content = await read_file("config.yaml")  # Bare name call
```

When Monty tries to resolve `read_file`, it looks for `"read_file"` in the externals dict. But the dict only has `"files.read_file"`. **The call fails with `ExternalError: Missing external function: 'read_file'`.**

### 2.3 Why Option B Fails

Option B suggests injecting capability group objects:

```python
exec_globals = {
    "files": context.files,  # FileCapabilities instance
    "kv": context.kv,
    ...
}
```

This requires `.pym` scripts to use attribute access:

```python
content = await files.read_file("path")  # Attribute access
```

**However, Grail's external declaration system doesn't support this pattern:**

1. **`@external` only works on functions, not objects.** The parser (`parser.py:147-192`) specifically looks for `ast.FunctionDef` or `ast.AsyncFunctionDef` nodes with `@external` decorators. There's no mechanism to declare `files.read_file` as an external.

2. **Grail's code generator strips `@external` functions.** The `GrailDeclarationStripper` (`codegen.py:12-77`) removes `@external` decorated functions from the generated Monty code. For object-based access, there's nothing to strip — the `files` variable would need to be injected into the execution context, but Grail's `run()` method only accepts `external_functions: dict[str, Callable]`.

3. **Type stubs can't express object attributes.** The stub generator (`stubs.py`) creates function stubs like `async def read_file(path: str) -> str: ...`. It cannot generate a stub expressing "`files` is an object with a `read_file` async method."

### 2.4 The Fundamental Mismatch

The core issue is that **Grail's external system was designed for flat function namespaces**:

```
.pym script                    Runtime
---------------                --------
@external                      externals = {
async def foo(): ...    -->      "foo": <callable>
}                              }

await foo()         -------->   lookup("foo")
```

Phase 7's namespacing attempts to introduce a hierarchical namespace:

```
files.read_file()   --?-->   lookup("files.read_file")?
files.read_file()   --?-->   lookup("files").read_file()?
```

Neither mapping is supported by Grail's current architecture.

---

## Section 3: Existing .pym Scripts Would Break

### 3.1 Current Script Pattern

All 29 .pym tool scripts in remora-v2 use bare function names:

```python
# src/remora/defaults/bundles/system/tools/send_message.pym
@external
async def send_message(to_node_id: str, content: str) -> bool: ...
result = await send_message(to_node_id, content)

# src/remora/defaults/bundles/system/tools/kv_get.pym
@external
async def kv_get(key: str) -> str | None: ...
value = await kv_get(key)

# src/remora/defaults/bundles/system/tools/query_agents.pym
@external
async def graph_query_nodes(node_type: str | None, status: str | None) -> list[dict]: ...
agents = await graph_query_nodes(node_type_value, None)
```

### 3.2 Required Changes Under Phase 7

If Phase 7 were implemented, every .pym script would need to change from:

```python
@external
async def read_file(path: str) -> str: ...
content = await read_file(path)
```

To (Option A — not supported by Grail):

```python
# This doesn't work — @external can't declare namespaced functions
@external
async def files.read_file(path: str) -> str: ...  # SYNTAX ERROR
```

Or (Option B — requires Grail modifications):

```python
# This requires a completely different external declaration mechanism
# and changes to how Grail resolves externals at runtime
content = await files.read_file(path)
```

---

## Section 4: The Hidden Collision Issue

### 4.1 The Original Problem

Phase 7's motivation is valid: if two capability groups define functions with the same name, the merge in `TurnContext.to_capabilities_dict()` silently overwrites:

```python
# In context.py:83-92
def to_capabilities_dict(self) -> dict[str, Any]:
    capabilities: dict[str, Any] = {}
    capabilities.update(self.files.to_dict())      # Has read_file
    capabilities.update(self.kv.to_dict())
    capabilities.update(self.graph.to_dict())
    capabilities.update(self.events.to_dict())
    capabilities.update(self.comms.to_dict())      # <-- What if this has read_file?
    capabilities.update(self.search.to_dict())
    capabilities.update(self.identity.to_dict())
    return capabilities
```

### 4.2 Current Reality

Examining all capability classes in `capabilities.py`:

| Class | Methods |
|-------|---------|
| `FileCapabilities` | `read_file`, `write_file`, `list_dir`, `file_exists`, `search_files`, `search_content` |
| `KVCapabilities` | `kv_get`, `kv_set`, `kv_delete`, `kv_list` |
| `GraphCapabilities` | `graph_get_node`, `graph_query_nodes`, `graph_get_edges`, `graph_get_children`, `graph_set_status` |
| `EventCapabilities` | `event_emit`, `event_subscribe`, `event_unsubscribe`, `event_get_history` |
| `CommunicationCapabilities` | `send_message`, `broadcast`, `request_human_input`, `propose_changes` |
| `SearchCapabilities` | `semantic_search`, `find_similar_code` |
| `IdentityCapabilities` | `get_node_source`, `my_node_id`, `my_correlation_id` |

**There are NO naming collisions.** Each capability class already uses a distinctive prefix:
- `FileCapabilities` → bare names (`read_file`)
- `KVCapabilities` → `kv_` prefix
- `GraphCapabilities` → `graph_` prefix
- `EventCapabilities` → `event_` prefix
- `CommunicationCapabilities` → bare names (unique: `send_message`, `broadcast`, etc.)
- `SearchCapabilities` → bare names (unique: `semantic_search`, `find_similar_code`)
- `IdentityCapabilities` → bare names (unique: `get_node_source`, `my_node_id`, etc.)

### 4.3 The Real Risk

The collision risk exists only for:
1. **Future additions** — if someone adds `read_file` to `CommunicationCapabilities`, it would silently overwrite `FileCapabilities.read_file`
2. **Third-party bundles** — custom bundles might declare `@external async def read_file(...)` expecting different semantics

However, this is already mitigated by:
1. The `.pym` scripts explicitly declare which externals they need via `@external`
2. `GrailTool.execute()` (in `grail.py:139-144`) filters capabilities to only those declared in the script:

```python
used_capabilities = {
    name: fn
    for name, fn in self._capabilities.items()
    if name in self._script.externals  # <-- Only declared externals
}
result = await self._script.run(inputs=arguments, externals=used_capabilities)
```

---

## Section 5: Recommendations

### 5.1 DO NOT Implement Phase 7 As Written

The namespacing approach is architecturally incompatible with Grail. The `@external` decorator system expects bare function names, and changing this would require:
1. Modifying Grail's parser to support namespaced external declarations
2. Modifying Grail's code generator to handle namespaced calls
3. Modifying Grail's type stub generator for namespaced stubs
4. Updating all 29+ .pym scripts in remora-v2
5. Coordinating with any downstream users of Grail

### 5.2 Alternative: Add Validation Instead of Namespacing

If collision prevention is a concern, add validation in `TurnContext.to_capabilities_dict()`:

```python
def to_capabilities_dict(self) -> dict[str, Any]:
    capabilities: dict[str, Any] = {}
    
    for cap_group in [self.files, self.kv, self.graph, self.events, 
                      self.comms, self.search, self.identity]:
        group_dict = cap_group.to_dict()
        for name in group_dict:
            if name in capabilities:
                raise RuntimeError(
                    f"Capability collision: {cap_group.__class__.__name__}.{name} "
                    f"would shadow existing capability '{name}'"
                )
        capabilities.update(group_dict)
    
    return capabilities
```

This provides compile-time safety without breaking Grail integration.

### 5.3 Alternative: Use Existing Prefixes Consistently

The current naming conventions already prevent collisions:
- `kv_*` for key-value operations
- `graph_*` for graph operations  
- `event_*` for event operations

Enforce these prefixes via documentation and code review. The `FileCapabilities` methods (`read_file`, `write_file`, etc.) are the "default" namespace for file operations — consider adding a `file_` prefix if collision risk is deemed significant.

### 5.4 If Namespacing Is Absolutely Required

If namespacing is mandatory for other reasons, Grail itself would need modification:

1. **Add support for namespaced external declarations:**
   ```python
   # New syntax in .pym files
   from grail import external, ExternalGroup
   
   files = ExternalGroup("files")  # Hypothetical
   
   @external(group="files")
   async def read_file(path: str) -> str: ...
   ```

2. **Modify the parser to extract group information**

3. **Modify the code generator to transform calls:**
   ```python
   # Before (in .pym)
   content = await read_file(path)
   
   # After (in generated Monty code)
   content = await __externals__["files"]["read_file"](path)
   ```

4. **Modify the runtime binding to accept nested dicts**

This is a substantial change to Grail's architecture and should be a separate project.

---

## Section 6: Conclusion

**Phase 7 of the REVIEW_REFACTOR_GUIDE.md should be removed or substantially revised.** The proposed namespacing:

1. Is fundamentally incompatible with Grail's `@external` decorator system
2. Would require modifying Grail's parser, code generator, and type stub system
3. Would require updating all 29+ existing .pym scripts
4. Solves a problem (collision) that doesn't currently exist in the codebase
5. The existing capability filtering in `GrailTool.execute()` already prevents runtime collisions

The guide's TODO marker ("Does this work with Grail??") correctly identifies the uncertainty. The definitive answer is: **No, it does not work with Grail without substantial modifications to both Grail and remora-v2.**

---

## Appendix A: Key Files Analyzed

| File | Purpose |
|------|---------|
| `.context/grail_v3.0.0/src/grail/_external.py` | The `@external` decorator (no-op) |
| `.context/grail_v3.0.0/src/grail/parser.py` | AST parsing, extracts external function names |
| `.context/grail_v3.0.0/src/grail/codegen.py` | Strips `@external` functions, generates Monty code |
| `.context/grail_v3.0.0/src/grail/script.py` | `GrailScript.run()` binding logic |
| `src/remora/core/tools/grail.py` | `GrailTool.execute()` capability filtering |
| `src/remora/core/tools/capabilities.py` | All capability classes and their method names |
| `src/remora/core/tools/context.py` | `TurnContext.to_capabilities_dict()` merge logic |
| `.pym files in src/remora/defaults/bundles/` | 29 tool scripts using bare external names |

## Appendix B: Current External Names in Use

All external function names declared in remora-v2's .pym scripts:

**File operations:** `read_file`, `write_file`
**KV operations:** `kv_get`, `kv_set`
**Graph operations:** `graph_get_node`, `graph_query_nodes`, `graph_get_edges`, `graph_get_children`, `graph_set_status`
**Event operations:** `event_emit`, `event_subscribe`, `event_unsubscribe`, `event_get_history`
**Communication:** `send_message`, `broadcast`, `request_human_input`
**Search:** `semantic_search`
**Identity:** `my_node_id`, `my_correlation_id`

No collisions exist in this set.
