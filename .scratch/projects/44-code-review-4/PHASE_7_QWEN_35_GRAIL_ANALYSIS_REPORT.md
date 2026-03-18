# Phase 7 Analysis Report: Namespace Capability Functions

**Date:** 2026-03-18  
**Project:** remora-v2  
**Analysis Target:** REVIEW_REFACTOR_GUIDE.md Phase 7 — "Namespace Capability Functions"  
**Grail Version Studied:** v3.0.0

---

# Phase 7 Analysis - Quick Summary

## Finding: CRITICAL FLAW IN GUIDE

**Phase 7 should NOT be implemented as written.**

## Why

The guide's recommendation to namespace capability functions (e.g., `files.read_file`, `graph.get_node`) fundamentally breaks Grail's architecture:

1. **Syntax Error**: Grail's `@external` decorator requires valid Python function names. Dotted names like `files.read_file` are invalid syntax.

2. **Wrong Problem**: The guide claims namespace collisions are a problem, but the current flat structure works correctly because:
   - Each tool script only declares the externals it needs
   - Function names are unique across capability groups
   - Grail's external resolution matches by exact name

3. **Incompatible with Grail**: The guide suggests injecting namespace objects (`files`, `graph`) into the exec context, but Grail's `run()` method only accepts `inputs` and `externals` dicts keyed by function name.

## Current Implementation is Correct

```python
# Tool script (tool.pym):
@external
async def read_file(path: str) -> str: ...

content = await read_file(path)

# Host code:
capabilities = {"read_file": file_caps.read_file}
```

This is the correct Grail pattern. No changes needed.

## If Naming Conflicts Arise

Use underscore prefixes, not dotted notation:
- `graph_get_node` instead of `graph.get_node`
- `kv_get` instead of `kv.get`

## Recommendation

**Mark Phase 7 as "NOT REQUIRED"** and proceed to the next phase.

---


## Executive Summary

**CRITICAL ISSUE IDENTIFIED:** The Phase 7 recommendation fundamentally misunderstands how Grail tool scripts work and would break the entire tool system. **Do not implement Phase 7 as written.**

The guide's proposal to namespace capability functions (e.g., `files.read_file`, `graph.get_node`) conflicts with how Grail `.pym` scripts declare and use external functions. The current implementation is actually correct and follows Grail's design principles.

---

## 1. How Grail Tool Scripts Work

### 1.1 Declaration Model

Grail `.pym` scripts use a **declaration-based** model:

```python
# In tool.pym:
from grail import Input, external

# Declare inputs
node_id: str = Input("node_id")

# Declare external functions (with `...` body)
@external
async def read_file(path: str) -> str: ...

# Use them in executable code
content = await read_file(node_id)
```

Key points:
- `@external` functions are **declarations only** — the body must be `...` (ellipsis)
- The Grail parser extracts these declarations as `ExternalSpec` objects
- At runtime, host code provides implementations via a dict lookup
- The script sees these as regular function calls

### 1.2 How Remora Implements This

From `src/remora/core/tools/grail.py`:

```python
class GrailTool:
    async def execute(self, arguments: dict[str, Any], context: ToolCall) -> ToolResult:
        # Build externals dict from capabilities
        used_capabilities = {
            name: fn
            for name, fn in self._capabilities.items()
            if name in self._script.externals
        }
        # Pass to GrailScript.run()
        result = await self._script.run(inputs=arguments, externals=used_capabilities)
```

The `_capabilities` dict is built in `core/tools/capabilities.py` where each capability group (FileCapabilities, GraphCapabilities, etc.) provides methods. These are merged into a **flat dict** keyed by function name.

---

## 2. Problems with Phase 7 as Written

### 2.1 Problem 1: Dotted Names Break External Resolution

**Guide suggests:**
```python
# In .pym script:
await files.read_file(path)
```

**Problem:** Grail's `@external` decorator expects a function name, not a dotted path. The declaration:

```python
@external
async def files.read_file(path: str) -> str: ...  # SYNTAX ERROR!
```

This is invalid Python syntax. You cannot have dots in function names.

### 2.2 Problem 2: Guide Contradicts Itself

The guide oscillates between two incompatible approaches:

**Option A (flat dict with dotted keys):**
```python
# Guide section 7.1 shows:
def to_dict(self) -> dict[str, Any]:
    return {
        "files.read_file": self.read_file,
        "files.write_file": self.write_file,
    }
```

**Option B (grouped objects):**
```python
# Guide section 7.2 suggests:
exec_globals = {
    "files": context.files,
    "graph": context.graph,
}
```

These are mutually exclusive. Option A gives you `files.read_file()` as a callable. Option B requires `files` to be an object with a `read_file` method. The guide doesn't resolve this.

### 2.3 Problem 3: Current Code Already Works

The current implementation is correct:

```python
# In .pym script (current, working):
@external
async def read_file(path: str) -> str: ...

content = await read_file(path)

# In host code:
capabilities = {
    "read_file": file_caps.read_file,
    "write_file": file_caps.write_file,
}
```

This follows Grail's design:
- Simple function names
- No namespace collisions (function names are unique)
- Clear mapping between declaration and implementation

### 2.4 Problem 4: Namespace Collision is Not a Real Problem

The guide's stated rationale:
> "If two groups define a function with the same name, the last one wins silently."

**This doesn't happen in practice** because:
1. Each tool script declares only the externals it needs
2. The `GrailTool.execute()` method filters capabilities to only those declared in the script
3. Function names like `read_file`, `write_file` are semantically distinct and shouldn't collide

The real collision risk would come from poor naming (e.g., two capability groups both defining `get()`), not from lack of namespacing.

---

## 3. What Phase 7 Should Actually Do

### 3.1 If Anything: Improve Capability Naming

If there are actual naming conflicts (which should be verified empirically), the fix is:

**Option A: Rename conflicting functions**
```python
# Instead of:
"get" -> ambiguous

# Use specific names:
"graph_get_node"
"kv_get"
"file_get_content"
```

**Option B: Use underscore-prefixed namespaces (if absolutely needed)**
```python
# Capability methods:
async def graph_get_node(self, node_id: str) -> dict: ...
async def kv_get(self, key: str) -> str: ...

# In .pym script:
@external
async def graph_get_node(node_id: str) -> dict: ...
```

This maintains flat function names while providing visual grouping.

### 3.2 Do NOT: Break Grail's Model

The following should **not** be done:
- Dotted function names in `@external` declarations (syntax error)
- Injecting namespace objects into Grail exec context (breaks external resolution)
- Changing the external function matching logic to use dotted names

---

## 4. Technical Deep Dive

### 4.1 Grail's External Function Resolution

From `grail/script.py` (Grail v3.0.0):

```python
async def run(self, inputs, externals, ...):
    # Validate externals match declarations
    self._validate_externals(externals, strict=strict_validation)
    
    # Create Monty instance with external function names
    monty = pydantic_monty.Monty(
        self.monty_code,
        external_functions=list(self.externals.keys()),  # Just names
        ...
    )
    
    # Execute with externals dict
    result = await pydantic_monty.run_monty_async(
        monty,
        external_functions=externals,  # Dict of name -> callable
        ...
    )
```

The `externals` dict keys must match the `@external` declaration names exactly.

### 4.2 Remora's Capability Injection

From `core/tools/capabilities.py` (simplified):

```python
class FileCapabilities:
    async def read_file(self, path: str) -> str: ...
    async def write_file(self, path: str, content: str) -> bool: ...
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "read_file": self.read_file,
            "write_file": self.write_file,
        }

# In TurnContext or similar:
all_capabilities = {
    **file_caps.to_dict(),
    **graph_caps.to_dict(),
    **kv_caps.to_dict(),
    ...
}
```

This flat dict is passed to `GrailTool.__init__()` as `capabilities`.

### 4.3 Why the Guide's Proposal Doesn't Work

**Guide suggests (section 7.2, Option B):**
```python
exec_globals = {
    "files": context.files,
    "graph": context.graph,
}
```

But `GrailScript.run()` doesn't accept arbitrary `exec_globals`. It accepts:
- `inputs`: values for `Input()` declarations
- `externals`: dict of `name -> callable` for `@external` functions

There's no mechanism to inject namespace objects like `files` or `graph` into the script's execution context.

---

## 5. Empirical Verification Steps

Before considering any changes to Phase 7, verify:

### 5.1 Check for Actual Naming Conflicts

```bash
# Search for duplicate function names across capability groups
rg "async def (read_file|write_file|get|set|list)" src/remora/core/tools/capabilities.py
```

If no conflicts exist, the Phase 7 premise is invalid.

### 5.2 Review Tool Scripts for Confusion

Check if any `.pym` scripts have issues:
```bash
# Count distinct external function names used
rg "@external" src/remora/defaults/bundles/ -A 1
```

If scripts work correctly (they do), there's no functional problem to solve.

---

## 6. Recommendations

### 6.1 Immediate: Skip Phase 7

**Status:** NOT REQUIRED — current implementation is correct.

The Phase 7 guide contains fundamental misunderstandings of Grail's architecture. Implementing it would:
- Break all existing `.pym` tool scripts
- Require rewriting Grail's external function resolution
- Add complexity without solving a real problem

### 6.2 Optional: Improve Naming Conventions

If the team perceives naming confusion, consider:

1. **Adopt prefix naming for new capabilities:**
   ```python
   # Instead of:
   "get_node", "set_status"
   
   # Use:
   "graph_get_node", "graph_set_status"
   ```

2. **Document the naming convention** in `core/tools/capabilities.py`

3. **Add linting** to detect potential collisions

### 6.3 If Namespacing is Absolutely Required

If there's a compelling use case that requires namespacing (none identified yet), the correct approach would be:

1. Keep flat function names in Grail scripts (required by Grail)
2. Use prefix naming convention (`graph_get_node`)
3. Document that Grail tool scripts use a flat namespace

Do **not** attempt to inject namespace objects or use dotted names.

---

## 7. Conclusion

**Phase 7 as written in REVIEW_REFACTOR_GUIDE.md is fundamentally broken and should not be implemented.**

The current implementation correctly follows Grail's design:
- Flat function names in `@external` declarations
- Host-side dict mapping names to implementations
- No namespacing needed or supported

The guide's author appears to have misunderstood how Grail tool scripts work. The proposed solution (namespaced functions like `files.read_file`) is incompatible with Grail's `@external` decorator syntax and execution model.

**Recommendation:** Mark Phase 7 as "NOT REQUIRED — implementation is correct" and proceed to the next phase in the refactor guide.

---

## Appendix: Files Studied

### Grail Library (v3.0.0)
- `.context/grail_v3.0.0/ARCHITECTURE.md`
- `.context/grail_v3.0.0/SPEC.md`
- `.context/grail_v3.0.0/HOW_TO_USE_GRAIL.md`
- `.context/grail_v3.0.0/src/grail/__init__.py`
- `.context/grail_v3.0.0/src/grail/script.py`

### Remora-v2 Grail Integration
- `src/remora/core/tools/grail.py`
- `src/remora/defaults/bundles/**/*.pym` (all 28 tool scripts)

### Phase 7 Guide
- `.scratch/projects/44-code-review-4/REVIEW_REFACTOR_GUIDE.md` (lines 820-962)

---

**Analysis completed:** 2026-03-18  
**Analyst:** opencode  
**Status:** CRITICAL ISSUE — Phase 7 should not be implemented as written
