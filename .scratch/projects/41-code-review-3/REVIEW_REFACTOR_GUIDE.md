# Remora v2 — Review Refactor Guide

**Date:** 2026-03-16
**Purpose:** Step-by-step implementation guide for all recommended refactors from the code review. Each section is self-contained with exact file paths, code changes, and test verification steps.

**Guiding principles:**
- No backwards compatibility — only the cleanest, most elegant architecture
- TDD: write a failing test first, implement the change, verify the test passes
- Run the full test suite after each section to catch regressions
- Commit after each completed section

---

## Table of Contents

### Phase 1: Model Cleanup & Quick Wins
1. [1.1 Unify the Node Model (CSTNode → Node)](#11-unify-the-node-model-cstnode--node) — Eliminate the dual-model layer and projections.py entirely
2. [1.2 Remove Test-Driven Production Indirection](#12-remove-test-driven-production-indirection) — Delete lambda wrappers, fix monkeypatch paths, remove clear_caches()
3. [1.3 Make `_expand_env_vars` Public](#13-make-_expand_env_vars-public) — Rename and add to `__all__`
4. [1.4 Fix Config Silent Drops](#14-fix-config-silent-drops) — Raise on unknown prompt keys instead of silently discarding
5. [1.5 Remove Dead Config](#15-remove-dead-config) — Delete the `"file"` key from bundle_overlays default
6. [1.6 Add `project_root` Property to Workspace Service](#16-add-project_root-property-to-workspace-service) — Eliminate private attribute access in web server

### Phase 2: Bug Fixes & Type Safety
7. [2.1 Fix Event Type Dispatch](#21-fix-event-type-dispatch) — Replace string-based event_type with EventType StrEnum
8. [2.2 Fix the Rate Limiter Bug](#22-fix-the-rate-limiter-bug) — Move rate limiting state from TurnContext to Actor

### Phase 3: Structural Decomposition
9. [3.1 Decompose the Reconciler](#31-decompose-the-reconciler) — Split 735 LOC into focused modules (watcher, directories, virtual_agents)
10. [3.2 Decompose the Web Server](#32-decompose-the-web-server) — Split 722 LOC into route modules, middleware, SSE, paths

### Phase 4: Turn Pipeline Simplification
11. [4.1 Simplify the Turn Executor](#41-simplify-the-turn-executor) — Extract TurnContextFactory, KernelRunner, move companion/bundle helpers
12. [4.2 Decompose the Externals God-Object](#42-decompose-the-externals-god-object) — Split TurnContext into focused capability protocols

### Phase 5: Performance & Polish
13. [5.1 Batch Event Commits](#51-batch-event-commits) — Add batching mode to EventStore
14. [5.2 Clean Up Grail Caching](#52-clean-up-grail-caching) — Replace two-tier cache with single bounded dict
15. [5.3 Fix NodeStore.batch() Transaction Management](#53-fix-nodestorenbatch-transaction-management) — Use proper BEGIN/COMMIT/ROLLBACK
16. [5.4 Use asyncio.iscoroutinefunction in EventBus](#54-use-asyncioiscoroutinefunction-in-eventbus) — Check the function, not the result
17. [5.5 Miscellaneous Polish](#55-miscellaneous-polish) — Idle timeout config, SearchMode enum, lazy HTML, SHA256 truncation, logger namespace

---


## Phase 1: Model Cleanup & Quick Wins

### 1.1 Unify the Node Model (CSTNode → Node)

**Goal:** Eliminate the dual-model layer (`CSTNode` + `Node`) and delete `projections.py` entirely. Discovery will produce `Node` objects directly.

**Why this is the right fix:** Remora's architecture is event-driven with nodes as the fundamental entity. Having two representations of the same thing (CSTNode for "discovered" state, Node for "persisted" state) creates a translation layer (`projections.py`) that does nothing except copy fields and compute a hash. The projection function is 82 LOC of pure mechanical copying. The names differ pointlessly (`text` vs `source_code`). By making discovery produce `Node` directly, we eliminate an entire conceptual layer.

**Files to modify:**
- `src/remora/code/discovery.py` — Replace `CSTNode` with `Node`
- `src/remora/code/projections.py` — **Delete entirely**
- `src/remora/code/reconciler.py` — Inline the 10 lines of projection logic
- `src/remora/code/__init__.py` — Update re-exports
- `src/remora/core/node.py` — Rename `source_code` to `text`
- `tests/factories.py` — Update `make_cst` → `make_node` or merge with `make_node`
- `tests/unit/test_projections.py` — **Delete entirely** (logic folded into reconciler tests)
- `tests/unit/test_discovery.py` — Update to expect `Node` instead of `CSTNode`

**Step-by-step:**

**Step 1: Decide on field naming.** The `Node` model uses `source_code` while `CSTNode` uses `text`. We'll use `text` moving forward.

**Step 2: Add `source_hash` computation to discovery.** Currently discovery doesn't compute `source_hash` — that happens in `projections.py`. Add it to `_parse_file` in `discovery.py`:

```python
# In discovery.py, inside the node construction loop:
import hashlib

source_text = _node_text(source_bytes, node)
source_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
```

**Step 3: Modify `discovery.py` to return `Node` objects instead of `CSTNode`.** 

Replace the `CSTNode` class definition and all `CSTNode(...)` constructor calls with `Node(...)`. The key field mapping:
- `CSTNode.text` → `Node.text`
- Add `source_hash=hashlib.sha256(text.encode("utf-8")).hexdigest()`
- Add `status="idle"` (default)
- Add `role=None` (default)

The `CSTNode` class should be completely removed. The `Node` import comes from `remora.core.node`.

```python
# discovery.py imports change:
# REMOVE: from pydantic import BaseModel, ConfigDict
# ADD:
import hashlib
from remora.core.node import Node

# In _parse_file, replace CSTNode construction:
source_text = _node_text(source_bytes, node)
nodes_out.append(
    Node(
        node_id=candidate_id,
        node_type=plugin.resolve_node_type(node),
        name=name,
        full_name=full_name,
        file_path=file_path,
        source_code=source_text,
        source_hash=hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        start_line=node.start_point.row + 1,
        end_line=node.end_point.row + 1,
        start_byte=node.start_byte,
        end_byte=node.end_byte,
        parent_id=parent_id,
    )
)
```

**Step 4: Delete `projections.py`.** This file is now dead code. Remove it entirely.

**Step 5: Inline projection logic into `reconciler.py`.** The `_do_reconcile_file` method currently calls `project_nodes(discovered, ...)`. Replace this with inline logic that does:
1. Batch-fetch existing nodes by ID: `await self._node_store.get_nodes_by_ids(node_ids)`
2. For each discovered node, compare `source_hash` with existing
3. If unchanged and no bundle sync needed, skip
4. If changed or new, resolve the bundle, update status/role from existing, upsert

The core logic is approximately:

```python
async def _do_reconcile_file(self, file_path, mtime_ns, *, sync_existing_bundles=False):
    discovered = discover([Path(file_path)], ...)
    
    node_ids = [n.node_id for n in discovered]
    existing_nodes = await self._node_store.get_nodes_by_ids(node_ids)
    existing_by_id = {n.node_id: n for n in existing_nodes}
    old_ids = self._file_state.get(file_path, (0, set()))[1]
    new_ids = {n.node_id for n in discovered}
    
    projected: list[Node] = []
    bundle_root = Path(self._config.bundle_root)
    
    for node in discovered:
        existing = existing_by_id.get(node.node_id)
        
        if existing is not None and existing.source_hash == node.source_hash:
            if sync_existing_bundles:
                template_dirs = [bundle_root / "system"]
                role = self._config.resolve_bundle(node.node_type, node.name) or existing.role
                if role:
                    template_dirs.append(bundle_root / role)
                await self._workspace_service.provision_bundle(node.node_id, template_dirs)
            projected.append(existing)
            continue
        
        mapped_bundle = self._config.resolve_bundle(node.node_type, node.name)
        # Enrich the discovered node with persisted state
        node.status = existing.status if existing else "idle"
        node.role = mapped_bundle if mapped_bundle is not None else (existing.role if existing else None)
        
        await self._node_store.upsert_node(node)
        
        if existing is None:
            template_dirs = [bundle_root / "system"]
            if mapped_bundle:
                template_dirs.append(bundle_root / mapped_bundle)
            await self._workspace_service.provision_bundle(node.node_id, template_dirs)
        
        projected.append(node)
    
    # ... rest of reconciliation (edges, events) remains the same but uses `projected`
```

**Step 6: Update `code/__init__.py`.** Remove re-exports of `CSTNode` and `project_nodes`. Add `Node` re-export from `discovery` if needed.

**Step 7: Update tests.**

- `tests/factories.py`: The `make_cst` helper should be deleted. If tests need a discovered node, use `make_node` (which already creates `Node` objects).
- `tests/unit/test_discovery.py`: Change all assertions from `CSTNode` to `Node`. Add assertions that `source_hash` is present and correct.
- `tests/unit/test_projections.py`: Delete this file entirely. The projection logic is now tested via reconciler tests.
- Any test importing `CSTNode` or `project_nodes` needs updating.

**Test verification:**

```bash
# Run all affected tests:
devenv shell -- pytest tests/unit/test_discovery.py tests/unit/test_reconciler.py -v

# Verify projections test file is gone:
test ! -f tests/unit/test_projections.py

# Run full suite to catch any missed imports:
devenv shell -- pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q
```


---

### 1.2 Remove Test-Driven Production Indirection

**Goal:** Delete the lambda wrappers in `Actor.__init__` that exist solely to preserve monkeypatch paths in tests. Fix tests to patch the real modules instead.

**Why this is the right fix:** Production code should never contort itself to accommodate test infrastructure. The lambda wrappers (`lambda **kwargs: create_kernel(**kwargs)`) are no-op indirection that exists because tests monkeypatch `remora.core.actor.create_kernel` instead of `remora.core.kernel.create_kernel`. The fix is to patch at the source.

**Files to modify:**
- `src/remora/core/actor.py` — Remove lambda wrappers
- `src/remora/core/turn_executor.py` — Remove the 3 injectable `_fn` params, import directly
- `src/remora/code/discovery.py` — Delete `clear_caches()` function
- `tests/unit/test_actor.py` — Fix all ~36 monkeypatch paths
- `tests/integration/test_e2e.py` — Fix monkeypatch paths (line ~193)
- `tests/unit/test_discovery.py` — Stop using `clear_caches()`, use fresh `LanguageRegistry` instances

**Step-by-step:**

**Step 1: Simplify `AgentTurnExecutor.__init__`.** Remove the three injectable function parameters:

```python
# turn_executor.py — REMOVE these params from __init__:
#   create_kernel_fn: Callable[..., Any] = create_kernel,
#   discover_tools_fn: Callable[..., Any] = discover_tools,
#   extract_response_text_fn: Callable[[Any], str] = extract_response_text,

# REMOVE these instance assignments:
#   self._create_kernel_fn = create_kernel_fn
#   self._discover_tools_fn = discover_tools_fn
#   self._extract_response_text_fn = extract_response_text_fn

# Replace all uses of self._create_kernel_fn with create_kernel
# Replace all uses of self._discover_tools_fn with discover_tools
# Replace all uses of self._extract_response_text_fn with extract_response_text
```

The imports are already at the top of `turn_executor.py` (lines 19-21), so the functions are directly available.

**Step 2: Simplify `Actor.__init__`.** Remove the lambda-wrapped kwargs from the `AgentTurnExecutor` construction:

```python
# actor.py — REMOVE these lines from the AgentTurnExecutor constructor call:
#   create_kernel_fn=lambda **kwargs: create_kernel(**kwargs),
#   discover_tools_fn=lambda workspace, capabilities: discover_tools(workspace, capabilities),
#   extract_response_text_fn=lambda result: extract_response_text(result),
```

Also remove the now-unused imports of `create_kernel`, `discover_tools`, and `extract_response_text` from `actor.py` if they're no longer used there.

**Step 3: Fix test monkeypatch paths.** In `tests/unit/test_actor.py`, find all instances of:

```python
monkeypatch.setattr("remora.core.actor.create_kernel", ...)
monkeypatch.setattr("remora.core.actor.discover_tools", ...)
monkeypatch.setattr("remora.core.actor.extract_response_text", ...)
```

Replace with:

```python
monkeypatch.setattr("remora.core.kernel.create_kernel", ...)
monkeypatch.setattr("remora.core.grail.discover_tools", ...)
monkeypatch.setattr("remora.core.kernel.extract_response_text", ...)
```

**Important:** Also check `remora.core.turn_executor` — since `turn_executor.py` imports these at the top level, you must patch the import reference in the module that *uses* them. The correct paths are:

```python
monkeypatch.setattr("remora.core.turn_executor.create_kernel", ...)
monkeypatch.setattr("remora.core.turn_executor.discover_tools", ...)
monkeypatch.setattr("remora.core.turn_executor.extract_response_text", ...)
```

This is because Python resolves names at the module level where they're imported. The `turn_executor` module imports `create_kernel` at line 21, so patching `remora.core.turn_executor.create_kernel` is what actually affects runtime behavior.

**Step 4: Fix `tests/integration/test_e2e.py`.** Same pattern — find the monkeypatch on `remora.core.actor.*` and change to `remora.core.turn_executor.*`.

**Step 5: Delete `clear_caches()` from `discovery.py`.** Remove the function and its entry in `__all__`. In tests that call `clear_caches()`, instead inject a fresh `LanguageRegistry` instance:

```python
# Before:
from remora.code.discovery import clear_caches
clear_caches()

# After:
from remora.code.languages import LanguageRegistry
# Pass language_registry=LanguageRegistry() to discover() calls
```

**Step 6: Fix the hardcoded logger namespace in `turn_executor.py`.** Replace:

```python
logger = logging.getLogger("remora.core.actor")
```

With:

```python
logger = logging.getLogger(__name__)
```

Update any tests that assert on the `"remora.core.actor"` logger name to use `"remora.core.turn_executor"` instead.

**Test verification:**

```bash
# Run the directly affected tests:
devenv shell -- pytest tests/unit/test_actor.py tests/unit/test_discovery.py -v

# Run integration tests:
devenv shell -- pytest tests/integration/test_e2e.py -v

# Full suite:
devenv shell -- pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q
```


---

### 1.3 Make `_expand_env_vars` Public

**Goal:** Rename `_expand_env_vars` to `expand_env_vars` since it's used across module boundaries.

**Files to modify:**
- `src/remora/core/config.py` — Rename function, add to `__all__`
- `src/remora/core/turn_executor.py` — Update import

**Step-by-step:**

**Step 1:** In `config.py`, rename `_expand_env_vars` to `expand_env_vars` and `_expand_string` to `expand_string`. Add both to `__all__`.

**Step 2:** In `turn_executor.py` line 15, update the import:
```python
# Before:
from remora.core.config import BundleConfig, Config, _expand_env_vars
# After:
from remora.core.config import BundleConfig, Config, expand_env_vars
```

Update the usage in `_read_bundle_config` (line 415):
```python
# Before:
expanded = _expand_env_vars(loaded)
# After:
expanded = expand_env_vars(loaded)
```

**Step 3:** In `tests/unit/test_config.py`, update any imports of `_expand_env_vars`.

**Test verification:**

```bash
devenv shell -- pytest tests/unit/test_config.py -v
devenv shell -- pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q
```

---

### 1.4 Fix Config Silent Drops

**Goal:** `BundleConfig.prompts` validator silently drops unknown keys. Make it raise instead.

**Why this is the right fix:** Silently discarding user data is always wrong. If a user puts `{"analysis": "Do X"}` in their bundle config's prompts section, they expect it to work. Silently dropping it means they'll debug for hours wondering why their prompt isn't being used.

**Files to modify:**
- `src/remora/core/config.py` — Change the prompts validator

**Step-by-step:**

**Step 1:** In `config.py`, change the `_validate_prompts` validator on `BundleConfig`:

```python
# Before (line 122-125):
@field_validator("prompts")
@classmethod
def _validate_prompts(cls, value: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in value.items() if k in ("chat", "reactive") and v.strip()}

# After:
_VALID_PROMPT_KEYS = frozenset({"chat", "reactive"})

@field_validator("prompts")
@classmethod
def _validate_prompts(cls, value: dict[str, str]) -> dict[str, str]:
    unknown = set(value.keys()) - _VALID_PROMPT_KEYS
    if unknown:
        raise ValueError(f"Unknown prompt keys: {', '.join(sorted(unknown))}. Valid keys: {', '.join(sorted(_VALID_PROMPT_KEYS))}")
    return {k: v for k, v in value.items() if v.strip()}
```

Move `_VALID_PROMPT_KEYS` to module level above the class.

**Step 2:** Check tests and example config to ensure no test data uses unknown prompt keys.

**Test verification:**

```bash
devenv shell -- pytest tests/unit/test_config.py -v

# Also verify the example config still loads:
devenv shell -- python -c "from remora.core.config import load_config; load_config()"
```

---

### 1.5 Remove Dead Config

**Goal:** The `bundle_overlays` default includes `"file": "code-agent"` but `NodeType` has no `FILE` variant. Remove it.

**Files to modify:**
- `src/remora/core/config.py` — Remove `"file"` from `bundle_overlays` default

**Step-by-step:**

In `config.py` line 148-155, change the `bundle_overlays` default:

```python
# Before:
bundle_overlays: dict[str, str] = Field(
    default_factory=lambda: {
        "function": "code-agent",
        "class": "code-agent",
        "method": "code-agent",
        "file": "code-agent",
        "directory": "directory-agent",
    }
)

# After:
bundle_overlays: dict[str, str] = Field(
    default_factory=lambda: {
        "function": "code-agent",
        "class": "code-agent",
        "method": "code-agent",
        "directory": "directory-agent",
    }
)
```

**Test verification:**

```bash
devenv shell -- pytest tests/unit/test_config.py -v
```

---

### 1.6 Add `project_root` Property to Workspace Service

**Goal:** The web server accesses `workspace_service._project_root` (a private attribute). Add a public property.

**Files to modify:**
- `src/remora/core/workspace.py` — Add `project_root` property
- `src/remora/web/server.py` — Replace `_project_root` access with property

**Step-by-step:**

**Step 1:** In `workspace.py`, add to `CairnWorkspaceService`:

```python
@property
def project_root(self) -> Path:
    """The resolved project root path."""
    return self._project_root
```

**Step 2:** In `web/server.py`, update the `_resolve_within_project_root` function (lines 119-124):

```python
# Before:
if workspace_service is not None and not candidate.is_absolute():
    candidate = workspace_service._project_root / candidate
...
project_root = workspace_service._project_root.resolve()

# After:
if workspace_service is not None and not candidate.is_absolute():
    candidate = workspace_service.project_root / candidate
...
project_root = workspace_service.project_root.resolve()
```

**Test verification:**

```bash
devenv shell -- pytest tests/unit/test_web.py -v
devenv shell -- pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q
```


---

## Phase 2: Bug Fixes & Type Safety

### 2.1 Fix Event Type Dispatch

**Goal:** Replace the fragile string-based `event_type` field with an `EventType` StrEnum. Currently, subscriptions match on strings like `"AgentCompleteEvent"`, which is just the Python class name auto-assigned in `model_post_init`. Renaming a class silently breaks all subscriptions.

**Why this is the right fix for remora:** Remora's event system is its backbone — events drive everything from reconciliation to actor triggers. Having the event identity be an accidental side-effect of the class name is dangerous. A StrEnum gives events stable, semantic identities that are decoupled from implementation names. Since we don't care about backwards compatibility, we can do this cleanly.

**Alternative considered:** Type-based subscriptions (storing Python type references in `SubscriptionRegistry` instead of strings). This is cleaner in pure-Python code, but remora persists subscriptions to SQLite. Serializing Python types to SQLite is fragile for the same reason — class renames break it. The StrEnum approach gives us stable string identities that serialize cleanly.

**Files to modify:**
- `src/remora/core/types.py` — Add `EventType` StrEnum
- `src/remora/core/events/types.py` — Set `event_type` from enum values instead of class names
- `src/remora/core/events/subscriptions.py` — Match on `EventType` values
- `src/remora/code/reconciler.py` — Update string literals to `EventType` enum references
- `src/remora/core/turn_executor.py` — Update string literal on line 101
- `src/remora/web/server.py` — Update string literals in SSE handler
- All test files that reference event_type strings

**Step-by-step:**

**Step 1: Define the `EventType` StrEnum.** In `types.py`, add:

```python
class EventType(StrEnum):
    """Stable event type identifiers decoupled from class names."""
    AGENT_START = "agent_start"
    AGENT_COMPLETE = "agent_complete"
    AGENT_ERROR = "agent_error"
    AGENT_MESSAGE = "agent_message"
    NODE_DISCOVERED = "node_discovered"
    NODE_REMOVED = "node_removed"
    NODE_CHANGED = "node_changed"
    CONTENT_CHANGED = "content_changed"
    HUMAN_INPUT_REQUEST = "human_input_request"
    HUMAN_INPUT_RESPONSE = "human_input_response"
    REWRITE_PROPOSAL = "rewrite_proposal"
    REWRITE_ACCEPTED = "rewrite_accepted"
    REWRITE_REJECTED = "rewrite_rejected"
    MODEL_REQUEST = "model_request"
    MODEL_RESPONSE = "model_response"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    REMORA_TOOL_CALL = "remora_tool_call"
    REMORA_TOOL_RESULT = "remora_tool_result"
    TURN_COMPLETE = "turn_complete"
    TURN_DIGESTED = "turn_digested"
    CUSTOM = "custom"
    CURSOR_FOCUS = "cursor_focus"
```

Add `EventType` to `__all__`.

**Step 2: Update `Event` base class.** In `events/types.py`:

```python
from remora.core.types import EventType

class Event(BaseModel):
    event_type: str = ""  # Keep as str for CustomEvent flexibility
    ...
```

Then on each concrete event class, set a class-level default:

```python
class AgentStartEvent(Event):
    event_type: str = EventType.AGENT_START
    agent_id: str
    node_name: str = ""

class AgentCompleteEvent(Event):
    event_type: str = EventType.AGENT_COMPLETE
    agent_id: str
    result_summary: str = ""
    ...
```

Remove the `model_post_init` that sets `event_type` from the class name. Each class now explicitly declares its event type.

**Step 3: Update all string comparisons.** Find every place that compares `event_type` to a string and replace with the enum:

```python
# reconciler.py — subscription registrations:
# Before:
SubscriptionPattern(event_types=["NodeChangedEvent"], ...)
# After:
SubscriptionPattern(event_types=[EventType.NODE_CHANGED], ...)

# Before:
SubscriptionPattern(event_types=["ContentChangedEvent"], ...)
# After:
SubscriptionPattern(event_types=[EventType.CONTENT_CHANGED], ...)

# Before:
SubscriptionPattern(event_types=["AgentCompleteEvent"], ...)
# After:
SubscriptionPattern(event_types=[EventType.AGENT_COMPLETE], ...)

# turn_executor.py line 101:
# Before:
trigger.event.event_type == "AgentCompleteEvent"
# After:
trigger.event.event_type == EventType.AGENT_COMPLETE
```

**Step 4: Update `SubscriptionPattern.event_types` type.** Consider changing from `list[str]` to `list[str]` but documenting that values should be `EventType` members. Since `EventType` is a `StrEnum`, it's already a `str`, so the type annotation doesn't need to change for compatibility. The values just change from class names to snake_case identifiers.

**Step 5: Handle `CustomEvent`.** `CustomEvent` lets agents emit arbitrary event types. The `event_type` field should remain `str` on the base `Event` class, but `CustomEvent` should keep its current behavior where the caller sets the event_type to whatever they want. The `model_post_init` should be removed, and `CustomEvent` should default to `EventType.CUSTOM`:

```python
class CustomEvent(Event):
    event_type: str = EventType.CUSTOM
    payload: dict[str, Any] = Field(default_factory=dict)
```

But agents can override it: `CustomEvent(event_type="my_custom_event", ...)`.

**Step 6: Database migration.** The `events` table stores `event_type` as text. Old events will have class names like `"AgentCompleteEvent"`. New events will have `"agent_complete"`. This is fine — old data is historical. If you need to query across old and new, add a migration:

```sql
UPDATE events SET event_type = 'agent_start' WHERE event_type = 'AgentStartEvent';
UPDATE events SET event_type = 'agent_complete' WHERE event_type = 'AgentCompleteEvent';
-- ... etc for each event type
```

But since we don't care about backwards compatibility, you can just wipe the database or accept that old events have old names.

Similarly, the `subscriptions` table stores `pattern_json` with event_type strings. These need updating too. Simplest approach: clear subscriptions on startup (the reconciler re-registers them anyway).

**Test verification:**

```bash
# Run event-related tests:
devenv shell -- pytest tests/unit/test_events.py tests/unit/test_subscriptions.py -v

# Run reconciler tests (heavy subscription use):
devenv shell -- pytest tests/unit/test_reconciler.py -v

# Run turn executor tests:
devenv shell -- pytest tests/unit/test_actor.py -v

# Full suite:
devenv shell -- pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q
```

**Grep for remaining string literals to ensure none were missed:**

```bash
rg '"AgentCompleteEvent"|"NodeChangedEvent"|"ContentChangedEvent"|"AgentStartEvent"' src/
```


---

### 2.2 Fix the Rate Limiter Bug

**Goal:** The `send_message` rate limiter in `TurnContext` is broken. `TurnContext` is recreated per-turn in `_prepare_turn_context` (turn_executor.py line 209), so `_send_message_timestamps` (a dict initialized empty in `__init__`) always starts fresh. An agent can send unlimited messages per turn because the rate window is effectively reset every turn.

**Why this is the right fix:** Rate limiting needs to persist across turns. The `Actor` object persists across turns (it has the inbox loop). The rate limiter state belongs on the `Actor`, not on the per-turn `TurnContext`.

**Files to modify:**
- `src/remora/core/actor.py` — Own the rate limiter state
- `src/remora/core/externals.py` — Accept rate limiter as a parameter instead of owning state
- `src/remora/core/turn_executor.py` — Pass rate limiter through to TurnContext

**Step-by-step:**

**Step 1: Extract a `RateLimiter` class.** The web server already has a `RateLimiter` class (web/server.py line 48). Since both the web server and the externals need the same sliding-window rate limiter, extract it to a shared location. Create the class in `externals.py` (or a new `rate_limit.py` module):

```python
class SlidingWindowRateLimiter:
    """Per-key sliding window rate limiter."""

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        self._max_requests = max(1, max_requests)
        self._window_seconds = max(0.001, window_seconds)
        self._timestamps: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        now = time.time()
        timestamps = self._timestamps.setdefault(key, deque())
        cutoff = now - self._window_seconds
        while timestamps and timestamps[0] <= cutoff:
            timestamps.popleft()
        if len(timestamps) >= self._max_requests:
            return False
        timestamps.append(now)
        return True
```

**Step 2: Create the rate limiter in `Actor.__init__`.** The `Actor` persists across turns, so it's the right place to own rate state:

```python
# actor.py
class Actor:
    def __init__(self, ...):
        ...
        self._send_message_limiter = SlidingWindowRateLimiter(
            max_requests=config.send_message_rate_limit,
            window_seconds=config.send_message_rate_window_s,
        )
```

**Step 3: Pass the limiter to `TurnContext`.** Modify `TurnContext.__init__` to accept a `send_message_limiter` parameter instead of creating its own timestamps dict:

```python
# externals.py
class TurnContext:
    def __init__(
        self,
        ...
        send_message_limiter: SlidingWindowRateLimiter | None = None,
    ) -> None:
        ...
        self._send_message_limiter = send_message_limiter

    def _allow_send_message(self) -> bool:
        if self._send_message_limiter is None:
            return True
        return self._send_message_limiter.allow(self.node_id)
```

Remove the old `_send_message_timestamps`, `_send_message_rate_limit`, and `_send_message_rate_window_s` fields.

**Step 4: Thread the limiter through `AgentTurnExecutor`.** The turn executor creates the `TurnContext` in `_prepare_turn_context`. Add a `send_message_limiter` parameter to the executor and pass it through:

```python
# turn_executor.py
class AgentTurnExecutor:
    def __init__(self, ..., send_message_limiter=None):
        ...
        self._send_message_limiter = send_message_limiter

    async def _prepare_turn_context(self, ...):
        context = TurnContext(
            ...,
            send_message_limiter=self._send_message_limiter,
        )
```

And in `actor.py`, pass it when constructing the executor:

```python
self._turn_executor = AgentTurnExecutor(
    ...,
    send_message_limiter=self._send_message_limiter,
)
```

**Step 5: Update the web server's `RateLimiter`.** Replace the web server's local `RateLimiter` class with the shared `SlidingWindowRateLimiter`:

```python
# web/server.py
from remora.core.externals import SlidingWindowRateLimiter

# Replace RateLimiter usage with SlidingWindowRateLimiter
```

Or, if you created a separate `rate_limit.py` module, import from there.

**Test verification:**

Write a test that verifies rate limiting persists across turns:

```python
async def test_send_message_rate_limit_persists_across_turns():
    """Rate limiter state must survive TurnContext recreation."""
    limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=10.0)
    
    # Turn 1: send 2 messages (should both succeed)
    ctx1 = TurnContext(..., send_message_limiter=limiter)
    assert ctx1._allow_send_message() is True
    assert ctx1._allow_send_message() is True
    
    # Turn 2: new TurnContext, same limiter — should be rate-limited
    ctx2 = TurnContext(..., send_message_limiter=limiter)
    assert ctx2._allow_send_message() is False
```

```bash
devenv shell -- pytest tests/unit/test_externals.py tests/unit/test_actor.py -v
devenv shell -- pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q
```


---

## Phase 3: Structural Decomposition

### 3.1 Decompose the Reconciler

**Goal:** Split the 735 LOC `reconciler.py` into focused modules. Currently it handles four distinct jobs: file watching, node reconciliation, directory hierarchy management, and virtual agent lifecycle.

**Why this is the right fix for remora:** The reconciler is the bridge between the filesystem and the reactive event graph. It's the most critical path in the system — bugs here mean stale nodes, missed events, or orphaned agents. Decomposing it makes each concern independently testable and the code easier to reason about when debugging reconciliation issues.

**Target structure:**

```
code/
  reconciler.py       -> Slim orchestrator (~150 LOC)
  watcher.py          -> File watching via watchfiles (~100 LOC)
  directories.py      -> Directory hierarchy projection (~200 LOC)
  virtual_agents.py   -> Virtual agent sync (~150 LOC)
```

**Files to modify:**
- `src/remora/code/reconciler.py` — Slim down to orchestrator
- `src/remora/code/watcher.py` — **New file**: extract file watching
- `src/remora/code/directories.py` — **New file**: extract directory management
- `src/remora/code/virtual_agents.py` — **New file**: extract virtual agent sync
- `src/remora/code/__init__.py` — Update re-exports
- `src/remora/core/services.py` — Update `FileReconciler` constructor if signature changes
- Test files may need to be split accordingly

**Step-by-step:**

**Step 1: Extract `watcher.py`.** Move the following from `reconciler.py`:
- `run_forever` method → becomes a standalone function or class
- `_run_watching` method
- `_stop_event` method
- `_collect_file_mtimes` method

Create a `FileWatcher` class:

```python
# code/watcher.py
"""File change detection via watchfiles."""

import asyncio
import logging
from pathlib import Path

from remora.code.paths import resolve_discovery_paths, walk_source_files
from remora.core.config import Config

logger = logging.getLogger(__name__)


class FileWatcher:
    """Detects file changes for incremental reconciliation."""

    def __init__(self, config: Config, project_root: Path) -> None:
        self._config = config
        self._project_root = project_root.resolve()
        self._running = False
        self._stop_task: asyncio.Task | None = None

    @property
    def stop_task(self) -> asyncio.Task | None:
        return self._stop_task

    def collect_file_mtimes(self) -> dict[str, int]:
        """Scan discovery paths and return {file_path: mtime_ns}."""
        mtimes: dict[str, int] = {}
        discovery_paths = resolve_discovery_paths(self._config, self._project_root)
        for file_path in walk_source_files(
            discovery_paths,
            self._config.workspace_ignore_patterns,
        ):
            try:
                mtimes[str(file_path)] = file_path.stat().st_mtime_ns
            except FileNotFoundError:
                continue
        return mtimes

    async def watch(self, on_changes) -> None:
        """Watch for changes and call on_changes(changed_paths) for each batch."""
        import watchfiles

        self._running = True
        paths_to_watch = resolve_discovery_paths(self._config, self._project_root)
        watch_paths = [str(p) for p in paths_to_watch if p.exists()]
        if not watch_paths:
            raise RuntimeError("No discovery paths exist to watch.")

        try:
            async for changes in watchfiles.awatch(
                *watch_paths, stop_event=self._stop_event()
            ):
                if not self._running:
                    break
                changed_files = {str(Path(path)) for _change_type, path in changes}
                await on_changes(changed_files)
        finally:
            self._running = False

    def stop(self) -> None:
        self._running = False
        if self._stop_task is not None and not self._stop_task.done():
            self._stop_task.cancel()

    def _stop_event(self):
        import threading
        if self._stop_task is not None and not self._stop_task.done():
            self._stop_task.cancel()
        event = threading.Event()

        async def _checker() -> None:
            try:
                while self._running:
                    await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                pass
            finally:
                event.set()

        self._stop_task = asyncio.create_task(_checker())
        return event
```

**Step 2: Extract `directories.py`.** Move the directory hierarchy logic:
- `_compute_directory_hierarchy`
- `_materialize_directories`
- `_upsert_directory_node`
- `_remove_stale_directories`
- `_normalize_dir_id`
- `_parent_dir_id`
- `_directory_id_for_file`
- `_relative_file_path`

Create a `DirectoryManager` class that takes `node_store`, `event_store`, `workspace_service`, `config`, and `project_root` as constructor args.

**Step 3: Extract `virtual_agents.py`.** Move:
- `_sync_virtual_agents`
- `_virtual_patterns`
- `_virtual_agent_hash`

Create a `VirtualAgentManager` class.

**Step 4: Slim down `reconciler.py` to an orchestrator.** The reconciler keeps:
- `__init__` (now takes watcher, dir_manager, virtual_agent_manager)
- `full_scan` / `reconcile_cycle`
- `_reconcile_file` / `_do_reconcile_file` (core node reconciliation)
- `_remove_node`
- `_register_subscriptions`
- `_provision_bundle`
- File lock management
- Content change event handler

```python
class FileReconciler:
    def __init__(
        self,
        config: Config,
        node_store: NodeStore,
        event_store: EventStore,
        workspace_service: CairnWorkspaceService,
        project_root: Path,
        *,
        search_service: SearchServiceProtocol | None = None,
    ):
        self._watcher = FileWatcher(config, project_root)
        self._dir_manager = DirectoryManager(config, node_store, event_store, workspace_service, project_root)
        self._virtual_agent_manager = VirtualAgentManager(config, node_store, event_store, workspace_service)
        # ... keep remaining init state

    async def reconcile_cycle(self) -> None:
        generation = self._next_reconcile_generation()
        await self._virtual_agent_manager.sync()
        current_mtimes = self._watcher.collect_file_mtimes()
        await self._dir_manager.materialize(set(current_mtimes.keys()), ...)
        # ... reconcile changed/deleted files
```

**Step 5: Update `services.py`.** The `FileReconciler` constructor signature hasn't changed externally (it still takes the same args), so `services.py` should need minimal changes. The reconciler just internally creates the sub-objects.

**Test verification:**

```bash
# Run reconciler tests:
devenv shell -- pytest tests/unit/test_reconciler.py -v

# If you split tests, run new test files too:
devenv shell -- pytest tests/unit/test_watcher.py tests/unit/test_directories.py tests/unit/test_virtual_agents.py -v

# Full suite:
devenv shell -- pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q
```


---

### 3.2 Decompose the Web Server

**Goal:** Split the 722 LOC `web/server.py` into focused route modules, middleware, SSE, and path resolution.

**Why this is the right fix for remora:** The web server is the primary human interface for inspecting the agent swarm. Having 17 route handlers, CSRF middleware, rate limiting, SSE streaming, and path resolution in one file makes it hard to find and modify specific endpoints. Splitting by domain concern (nodes, proposals, events, search, chat) makes each independently testable.

**Target structure:**

```
web/
  __init__.py          -> Re-export create_app
  server.py            -> App factory + lifespan (~60 LOC)
  deps.py              -> WebDeps dataclass + deps helper
  middleware.py         -> CSRFMiddleware
  sse.py               -> SSE streaming logic
  paths.py             -> Workspace path resolution
  routes/
    __init__.py
    nodes.py           -> Node CRUD + companion + conversation
    events.py          -> Event listing + SSE stream endpoint
    proposals.py       -> Rewrite proposal workflow
    chat.py            -> Chat + respond endpoints
    search.py          -> Semantic search endpoint
    health.py          -> Health check
    cursor.py          -> Cursor focus endpoint
```

**Step-by-step:**

**Step 1: Create `web/deps.py`.** Extract:
- `WebDeps` dataclass
- `_deps_from_request` helper
- `_get_chat_limiter` helper
- `RateLimiter` class (or import `SlidingWindowRateLimiter` if you already extracted it in phase 2)

**Step 2: Create `web/middleware.py`.** Extract:
- `_is_allowed_origin`
- `CSRFMiddleware`

**Step 3: Create `web/paths.py`.** Extract:
- `_resolve_within_project_root`
- `_workspace_path_to_disk_path`
- `_latest_rewrite_proposal`

**Step 4: Create `web/sse.py`.** Extract:
- `sse_stream`
- `_wait_for_shutdown`
- `_wait_for_disconnect`

**Improve the SSE streaming** while extracting. The current implementation creates/cancels a task per event iteration, which is unnecessarily complex. Simplify using `asyncio.wait_for` with the bus stream:

```python
async def sse_stream(request: Request) -> StreamingResponse:
    deps = _deps_from_request(request)
    ...
    async def event_generator():
        yield ": connected\n\n"
        # ... replay logic stays the same ...
        if once:
            return
        async with deps.event_bus.stream() as stream:
            async for event in stream:
                if await request.is_disconnected() or deps.shutdown_event.is_set():
                    break
                payload = json.dumps(event.to_envelope(), separators=(",", ":"))
                yield f"id: {event.timestamp}\nevent: {event.event_type}\ndata: {payload}\n\n"
        if deps.shutdown_event.is_set():
            yield ": server-shutdown\n\n"
    ...
```

Note: The above simplification only works if `request.is_disconnected()` is checked periodically. Since the `async for event in stream` blocks until an event arrives, you may still need the task-based approach for disconnect detection. An alternative is to use `asyncio.wait` with the stream and a disconnect check:

```python
async with deps.event_bus.stream() as stream:
    stream_iter = stream.__aiter__()
    while True:
        next_event = asyncio.ensure_future(stream_iter.__anext__())
        disconnect = asyncio.ensure_future(request.is_disconnected())
        done, pending = await asyncio.wait(
            {next_event, disconnect},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        if next_event in done:
            event = next_event.result()
            yield f"..."
        else:
            break
```

Keep the current approach if the simplification doesn't work cleanly — the decomposition is the main win, not the SSE rewrite.

**Step 5: Create route modules under `web/routes/`.** Each module exports its route handler functions and a `routes()` function returning a list of `Route` objects:

```python
# web/routes/nodes.py
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from remora.web.deps import _deps_from_request


async def api_nodes(request: Request) -> JSONResponse:
    deps = _deps_from_request(request)
    nodes = await deps.node_store.list_nodes()
    return JSONResponse([node.model_dump() for node in nodes])

# ... other node handlers ...

def routes() -> list[Route]:
    return [
        Route("/api/nodes", endpoint=api_nodes),
        Route("/api/nodes/{node_id:path}/edges", endpoint=api_edges),
        Route("/api/nodes/{node_id:path}/conversation", endpoint=api_conversation),
        Route("/api/nodes/{node_id:path}/companion", endpoint=api_node_companion),
        Route("/api/nodes/{node_id:path}", endpoint=api_node),
    ]
```

**Step 6: Slim down `server.py`.** It becomes just the app factory:

```python
# web/server.py
from starlette.applications import Starlette
from starlette.staticfiles import StaticFiles

from remora.web.deps import WebDeps
from remora.web.middleware import CSRFMiddleware
from remora.web.routes import nodes, events, proposals, chat, search, health, cursor


def create_app(...) -> Starlette:
    deps = WebDeps(...)
    all_routes = [
        Route("/", endpoint=index),
        *nodes.routes(),
        *events.routes(),
        *proposals.routes(),
        *chat.routes(),
        *search.routes(),
        *health.routes(),
        *cursor.routes(),
    ]
    app = Starlette(routes=all_routes, lifespan=_build_lifespan(deps.shutdown_event))
    app.state.deps = deps
    app.add_middleware(CSRFMiddleware)
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
    return app
```

**Step 7: Fix lazy HTML loading.** Replace the import-time file read:

```python
# Before:
_INDEX_HTML = (_STATIC_DIR / "index.html").read_text(encoding="utf-8")

# After:
_INDEX_HTML: str | None = None

def _get_index_html() -> str:
    global _INDEX_HTML
    if _INDEX_HTML is None:
        _INDEX_HTML = (_STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return _INDEX_HTML

async def index(_request: Request) -> HTMLResponse:
    return HTMLResponse(_get_index_html())
```

**Test verification:**

The existing `tests/unit/test_web.py` should continue to pass since the `create_app` interface hasn't changed. Individual route modules can get focused tests.

```bash
devenv shell -- pytest tests/unit/test_web.py -v
devenv shell -- pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q
```


---

## Phase 4: Turn Pipeline Simplification

### 4.1 Simplify the Turn Executor

**Goal:** `AgentTurnExecutor.__init__` takes 13 parameters. Extract focused collaborators so it becomes pure orchestration.

**Why this is the right fix for remora:** The turn executor is the hottest path — every agent turn flows through it. When debugging a turn failure, you need to quickly identify which phase failed (workspace setup, tool discovery, prompt building, kernel execution, response handling). The current monolith makes this hard. Decomposing into phases makes each testable and debuggable in isolation.

**Files to modify:**
- `src/remora/core/turn_executor.py` — Extract helpers, slim down
- `src/remora/core/workspace.py` — Move `_read_bundle_config` there
- `src/remora/core/actor.py` — Update constructor if signature changes
- Tests that construct `AgentTurnExecutor` directly

**Step-by-step:**

**Step 1: Move `_read_bundle_config` to `CairnWorkspaceService`.** This method reads `_bundle/bundle.yaml` from an agent workspace and parses it. It logically belongs on the workspace service, not the turn executor:

```python
# workspace.py — add to CairnWorkspaceService:
async def read_bundle_config(self, node_id: str) -> BundleConfig:
    """Read and parse the bundle config for an agent."""
    workspace = await self.get_agent_workspace(node_id)
    try:
        text = await workspace.read("_bundle/bundle.yaml")
    except (FileNotFoundError, FsdFileNotFoundError):
        return BundleConfig()
    try:
        loaded = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        logger.warning("Ignoring malformed _bundle/bundle.yaml for %s", node_id)
        return BundleConfig()
    if not isinstance(loaded, dict):
        return BundleConfig()

    expanded = expand_env_vars(loaded)
    if not isinstance(expanded, dict):
        return BundleConfig()

    self_reflect = expanded.get("self_reflect")
    if isinstance(self_reflect, dict) and not self_reflect.get("enabled"):
        expanded = dict(expanded)
        expanded.pop("self_reflect", None)

    try:
        return BundleConfig.model_validate(expanded)
    except ValidationError:
        logger.warning("Invalid bundle config for %s, using defaults", node_id)
        return BundleConfig()
```

Then in `turn_executor.py`, replace `await self._read_bundle_config(workspace)` with `await self._workspace_service.read_bundle_config(node_id)`.

Delete the `_read_bundle_config` static method from `AgentTurnExecutor`.

**Step 2: Move `_build_companion_context` to `AgentWorkspace`.** This method reads workspace KV data to build context. It logically belongs on the workspace:

```python
# workspace.py — add to AgentWorkspace:
async def build_companion_context(self) -> str:
    """Build a compact companion-memory context block from KV."""
    parts: list[str] = []

    reflections = await self.kv_get("companion/reflections")
    if isinstance(reflections, list) and reflections:
        reflection_lines: list[str] = []
        for entry in reflections[-5:]:
            if not isinstance(entry, dict):
                continue
            insight = entry.get("insight", "")
            if isinstance(insight, str) and insight.strip():
                reflection_lines.append(f"- {insight.strip()}")
        if reflection_lines:
            parts.append("## Prior Reflections")
            parts.extend(reflection_lines)

    # ... same for chat_index and links ...

    if not parts:
        return ""
    return "\n## Companion Memory\n" + "\n".join(parts)
```

Then in `turn_executor.py`, replace `await self._build_companion_context(workspace)` with `await workspace.build_companion_context()`.

Delete the `_build_companion_context` static method from `AgentTurnExecutor`.

**Step 3: Delete `_resolve_maybe_awaitable`.** This method exists because `discover_tools` might return either a coroutine or a list. Since we control `discover_tools`, make it always async (it already is — `async def discover_tools`). Remove the wrapper:

```python
# Before:
tools = await self._resolve_maybe_awaitable(self._discover_tools_fn(workspace, capabilities))

# After:
tools = await discover_tools(workspace, capabilities)
```

Delete the `_resolve_maybe_awaitable` static method.

**Step 4: Reduce constructor parameters.** After the above extractions, `AgentTurnExecutor.__init__` no longer needs to store `config` for bundle reading or companion context. It still needs: `node_store`, `event_store`, `workspace_service`, `config` (for model settings), `semaphore`, `metrics`, `history`, `prompt_builder`, `trigger_policy`, `search_service`. That's 10 params — still high but more focused.

Consider grouping `node_store + event_store + workspace_service + config` into a single `RuntimeServices` reference since the turn executor already has access to all of them through `services.py`. But this may create a dependency cycle. Evaluate whether passing `RuntimeServices` simplifies without creating issues.

**Test verification:**

```bash
devenv shell -- pytest tests/unit/test_actor.py tests/unit/test_workspace.py -v
devenv shell -- pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q
```

---

### 4.2 Decompose the Externals God-Object

**Goal:** `TurnContext` exposes 27 capabilities as a flat list of methods. Split into focused capability groups.

**Why this is the right fix for remora:** Remora agents execute Grail tool scripts that call into `TurnContext` capabilities via the `externals` mechanism. Each tool should only receive the capabilities it needs (principle of least privilege). A file-manipulation tool shouldn't have access to `send_message` or `graph_set_status`. Splitting into groups makes this possible and each group independently testable.

**Files to modify:**
- `src/remora/core/externals.py` — Split into capability classes
- `src/remora/core/turn_executor.py` — Construct capability groups
- `src/remora/core/grail.py` — Accept capability groups (already flexible via dict)

**Step-by-step:**

**Step 1: Create capability classes.** These aren't Protocol classes (those are for type hints) — they're concrete implementations:

```python
# externals.py

class FileCapabilities:
    """File system operations for agent tools."""

    def __init__(self, workspace: AgentWorkspace) -> None:
        self._workspace = workspace

    async def read_file(self, path: str) -> str:
        return await self._workspace.read(path)

    async def write_file(self, path: str, content: str) -> bool:
        await self._workspace.write(path, content)
        return True

    async def list_dir(self, path: str = ".") -> list[str]:
        return await self._workspace.list_dir(path)

    async def file_exists(self, path: str) -> bool:
        return await self._workspace.exists(path)

    async def search_files(self, pattern: str) -> list[str]:
        paths = await self._workspace.list_all_paths()
        return sorted(p for p in paths if fnmatch.fnmatch(p, f"*{pattern}*"))

    async def search_content(self, pattern: str, path: str = ".") -> list[dict[str, Any]]:
        # ... existing logic ...

    def to_dict(self) -> dict[str, Any]:
        return {
            "read_file": self.read_file,
            "write_file": self.write_file,
            "list_dir": self.list_dir,
            "file_exists": self.file_exists,
            "search_files": self.search_files,
            "search_content": self.search_content,
        }


class GraphCapabilities:
    """Graph operations for agent tools."""

    def __init__(self, node_id: str, node_store: NodeStore) -> None:
        self._node_id = node_id
        self._node_store = node_store

    # ... graph_get_node, graph_query_nodes, graph_get_edges, etc. ...

    def to_dict(self) -> dict[str, Any]:
        return { ... }


class EventCapabilities:
    """Event operations for agent tools."""
    # ... event_emit, event_subscribe, event_unsubscribe, event_get_history ...


class CommunicationCapabilities:
    """Inter-agent communication for agent tools."""
    # ... send_message, broadcast, request_human_input, propose_changes ...


class KVCapabilities:
    """Key-value store operations for agent tools."""
    # ... kv_get, kv_set, kv_delete, kv_list ...


class SearchCapabilities:
    """Semantic search operations for agent tools."""
    # ... semantic_search, find_similar_code ...


class IdentityCapabilities:
    """Agent identity queries for agent tools."""
    # ... my_node_id, my_correlation_id, get_node_source ...
```

**Step 2: Keep `TurnContext` as a facade.** `TurnContext` now composes the capability groups:

```python
class TurnContext:
    def __init__(self, ...):
        self.files = FileCapabilities(workspace)
        self.graph = GraphCapabilities(node_id, node_store)
        self.events = EventCapabilities(outbox, node_id, correlation_id, event_store)
        self.comms = CommunicationCapabilities(node_id, outbox, node_store, ...)
        self.kv = KVCapabilities(workspace)
        self.search = SearchCapabilities(search_service)
        self.identity = IdentityCapabilities(node_id, correlation_id, node_store)

    def to_capabilities_dict(self) -> dict[str, Any]:
        """Flatten all capabilities into a single dict for Grail tools."""
        result: dict[str, Any] = {}
        result.update(self.files.to_dict())
        result.update(self.graph.to_dict())
        result.update(self.events.to_dict())
        result.update(self.comms.to_dict())
        result.update(self.kv.to_dict())
        result.update(self.search.to_dict())
        result.update(self.identity.to_dict())
        return result
```

The `to_capabilities_dict()` method ensures backward compatibility with Grail tools — they still see a flat dict of capability functions. But now each group is testable in isolation.

**Step 3: Update tests.** Tests that construct `TurnContext` can now test individual capability groups:

```python
async def test_file_capabilities_read():
    workspace = MockWorkspace(files={"readme.md": "hello"})
    caps = FileCapabilities(workspace)
    assert await caps.read_file("readme.md") == "hello"
```

**Test verification:**

```bash
devenv shell -- pytest tests/unit/test_externals.py -v
devenv shell -- pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q
```


---

## Phase 5: Performance & Polish

### 5.1 Batch Event Commits

**Goal:** Every `EventStore.append()` does an individual `await self._db.commit()`. Under burst emission (reconciler `full_scan` with hundreds of events), this serializes on SQLite write throughput.

**Why this is the right fix for remora:** The reconciler emits `NodeDiscoveredEvent` and `NodeChangedEvent` for every node it processes. A project with 200 code nodes means 200+ individual commits during startup reconciliation. SQLite WAL mode handles concurrent reads well, but writes are serialized. Batching turns 200 commits into 1.

**Files to modify:**
- `src/remora/core/events/store.py` — Add `batch()` context manager
- `src/remora/code/reconciler.py` — Wrap burst-emission paths in `batch()`

**Step-by-step:**

**Step 1: Add batching to EventStore.** Follow the same pattern as `NodeStore.batch()`:

```python
# events/store.py
class EventStore:
    def __init__(self, ...):
        ...
        self._batch_depth = 0
        self._batch_buffer: list[Event] = []

    @asynccontextmanager
    async def batch(self):
        """Buffer events and commit in a single transaction."""
        self._batch_depth += 1
        try:
            yield
        except BaseException:
            if self._batch_depth == 1:
                self._batch_buffer.clear()
            raise
        finally:
            self._batch_depth -= 1
            if self._batch_depth == 0:
                await self._db.commit()
                for event in self._batch_buffer:
                    await self._event_bus.emit(event)
                    await self._dispatcher.dispatch(event)
                self._batch_buffer.clear()

    async def append(self, event: Event) -> int:
        envelope = event.to_envelope()
        # ... INSERT ...
        if self._batch_depth > 0:
            event_id = int(cursor.lastrowid)
            self._batch_buffer.append(event)
            return event_id
        else:
            await self._db.commit()
            event_id = int(cursor.lastrowid)
            await self._event_bus.emit(event)
            await self._dispatcher.dispatch(event)
            return event_id
```

**Step 2: Wrap reconciler burst paths.** In `reconciler.py`, the `_do_reconcile_file` method already uses `async with self._node_store.batch()`. Wrap the event emissions in an `event_store.batch()` as well:

```python
async with self._node_store.batch():
    async with self._event_store.batch():
        # ... all the event appends within this file reconciliation ...
```

Similarly, in `_materialize_directories` and `_sync_virtual_agents`, wrap the event-heavy loops.

**Test verification:**

Write a test that verifies batching reduces commits:

```python
async def test_event_store_batch_single_commit(db):
    """Events within a batch should commit once, not per-event."""
    store = EventStore(db)
    await store.create_tables()
    
    commit_count = 0
    original_commit = db.commit
    async def counting_commit():
        nonlocal commit_count
        commit_count += 1
        await original_commit()
    db.commit = counting_commit
    
    async with store.batch():
        for i in range(10):
            await store.append(NodeDiscoveredEvent(node_id=f"n{i}", ...))
    
    assert commit_count == 1  # One commit for the batch, not 10
```

```bash
devenv shell -- pytest tests/unit/test_events.py -v
devenv shell -- pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q
```

---

### 5.2 Clean Up Grail Caching

**Goal:** Replace the two-tier cache (dict + `lru_cache`) in `grail.py` with a single bounded dict keyed by content hash.

**Why this is the right fix:** The current caching has two layers that work against each other. `_SCRIPT_SOURCE_CACHE` stores raw source text keyed by `(content_hash, filename)`. Then `_cached_script` is an `@lru_cache` that takes `(content_hash, normalized_name)` and reads from the source cache. This means:
1. Two caches to manage, two eviction paths
2. The `lru_cache` stores the hash as its key but needs the source from the dict — if the dict evicts first, the `lru_cache` hit raises `ValueError`
3. Temp file I/O on every cache miss (unavoidable — grail needs a file path)

**Files to modify:**
- `src/remora/core/grail.py` — Replace caching

**Step-by-step:**

**Step 1: Replace both caches with a single dict:**

```python
# grail.py

_MAX_SCRIPT_CACHE = 256
_PARSED_SCRIPT_CACHE: dict[str, grail.GrailScript] = {}  # content_hash -> parsed script


def _load_script_from_source(source: str, name: str) -> grail.GrailScript:
    content_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
    cached = _PARSED_SCRIPT_CACHE.get(content_hash)
    if cached is not None:
        return cached

    filename = f"{name}.pym" if not name.endswith(".pym") else name
    with tempfile.TemporaryDirectory(prefix="remora-grail-") as temp_dir:
        script_path = Path(temp_dir) / filename
        script_path.write_text(source, encoding="utf-8")
        script = grail.load(script_path)

    if len(_PARSED_SCRIPT_CACHE) >= _MAX_SCRIPT_CACHE:
        _PARSED_SCRIPT_CACHE.pop(next(iter(_PARSED_SCRIPT_CACHE)))
    _PARSED_SCRIPT_CACHE[content_hash] = script
    return script
```

**Step 2: Delete the old caching code:**
- Delete `_SCRIPT_SOURCE_CACHE`
- Delete `_evict_source_cache()`
- Delete `_cached_script()` (the `@lru_cache` function)

**Test verification:**

```bash
devenv shell -- pytest tests/unit/test_grail.py -v
devenv shell -- pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q
```

---

### 5.3 Fix NodeStore.batch() Transaction Management

**Goal:** `NodeStore.batch()` uses raw `await self._db.execute("ROLLBACK")` which is fragile. Use proper transaction management.

**Files to modify:**
- `src/remora/core/graph.py` — Fix `batch()` method

**Step-by-step:**

Replace the current `batch()` implementation:

```python
# Before:
@asynccontextmanager
async def batch(self):
    self._batch_depth += 1
    failed = False
    try:
        yield
    except BaseException:
        failed = True
        if self._batch_depth == 1:
            await self._db.execute("ROLLBACK")
        raise
    finally:
        self._batch_depth -= 1
        if self._batch_depth == 0 and not failed:
            await self._db.commit()

# After:
@asynccontextmanager
async def batch(self):
    self._batch_depth += 1
    try:
        yield
    except BaseException:
        if self._batch_depth == 1:
            await self._db.rollback()
        raise
    finally:
        self._batch_depth -= 1
        if self._batch_depth == 0:
            await self._db.commit()
```

Key changes:
1. Use `self._db.rollback()` instead of `self._db.execute("ROLLBACK")` — aiosqlite provides a proper rollback method
2. Remove the `failed` flag — the `except` clause handles the failure case, and the `finally` clause only commits if no exception was raised (because the `except` re-raises)

Wait — actually there's a subtlety. If an exception is raised, `except BaseException` runs rollback and re-raises. Then `finally` runs and would try to commit (since `self._batch_depth` is back to 0). We need to track whether an exception occurred:

```python
@asynccontextmanager
async def batch(self):
    self._batch_depth += 1
    failed = False
    try:
        yield
    except BaseException:
        failed = True
        if self._batch_depth == 1:
            await self._db.rollback()
        raise
    finally:
        self._batch_depth -= 1
        if self._batch_depth == 0 and not failed:
            await self._db.commit()
```

The only change from the current code is `self._db.execute("ROLLBACK")` → `self._db.rollback()`. The `failed` flag is actually correct as-is. The fix is minimal.

**Test verification:**

```bash
devenv shell -- pytest tests/unit/test_graph.py -v
```

---

### 5.4 Use asyncio.iscoroutinefunction in EventBus

**Goal:** `EventBus._dispatch_handlers` calls every handler and then checks if the result is a coroutine. This means sync handlers are called even if their result isn't awaited properly.

**Files to modify:**
- `src/remora/core/events/bus.py` — Fix dispatch logic

**Step-by-step:**

```python
# Before (bus.py lines 36-39):
for handler in handlers:
    result = handler(event)
    if asyncio.iscoroutine(result):
        tasks.append(asyncio.create_task(result))

# After:
for handler in handlers:
    if asyncio.iscoroutinefunction(handler):
        tasks.append(asyncio.create_task(handler(event)))
    else:
        handler(event)
```

The key difference: `iscoroutine(result)` calls the handler first and then checks the return. If the handler is sync, it runs but its result is silently dropped. `iscoroutinefunction(handler)` checks the function itself before calling it, so sync handlers are called correctly without creating a task, and async handlers are properly awaited.

**Test verification:**

```bash
devenv shell -- pytest tests/unit/test_events.py -v
```

---

### 5.5 Miscellaneous Polish

**5.5.1 Idle Actor Eviction Config**

Move the hardcoded `max_idle_seconds=300.0` from `runner.py` to `Config`:

```python
# config.py — add to Config:
actor_idle_timeout_s: float = 300.0

# runner.py — use config value:
self._max_idle_seconds = config.actor_idle_timeout_s
```

**5.5.2 SearchConfig Mode Enum**

```python
# config.py — add:
class SearchMode(StrEnum):
    REMOTE = "remote"
    LOCAL = "local"

# Update SearchConfig:
class SearchConfig(BaseModel):
    mode: SearchMode = SearchMode.REMOTE
    ...
    # Remove the _validate_mode validator — the enum handles validation
```

**5.5.3 SHA256 Truncation Length**

In `workspace.py`, `CairnWorkspaceService._safe_id`, increase from 10 to 16 hex chars:

```python
# Before:
digest = hashlib.sha256(node_id.encode("utf-8")).hexdigest()[:10]

# After:
digest = hashlib.sha256(node_id.encode("utf-8")).hexdigest()[:16]
```

This increases from 40 bits to 64 bits of collision resistance, which is appropriate for a namespace with potentially thousands of nodes.

**5.5.4 Fix _ContextFilter naming**

The `_turn_logger` function in `turn_executor.py` creates a `LoggerAdapter` with per-turn context fields. The code review mentioned `_ContextFilter` but this doesn't appear in the current code — it may have been removed in a prior refactor. If a `_ContextFilter` class exists anywhere, rename it to `_StructuredFieldInjector` to honestly describe what it does.

**5.5.5 Logger namespace fix (if not done in 1.2)**

Ensure `turn_executor.py` uses `logger = logging.getLogger(__name__)` instead of `logging.getLogger("remora.core.actor")`.

**Test verification for all polish items:**

```bash
devenv shell -- pytest tests/unit/test_config.py tests/unit/test_workspace.py -v
devenv shell -- pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q
```


---

## Final Verification Checklist

After completing all phases, run the full verification:

```bash
# 1. Full test suite
devenv shell -- pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q

# 2. Type checking (if configured)
devenv shell -- ruff check src/

# 3. Verify no stale imports
rg "CSTNode|project_nodes|clear_caches|_expand_env_vars" src/remora/
# Should return nothing (all renamed/removed)

# 4. Verify no private attribute access across modules
rg "\._project_root" src/remora/web/
# Should return nothing (replaced with .project_root property)

# 5. Verify no old-style event type strings in subscriptions
rg '"AgentCompleteEvent"|"NodeChangedEvent"|"ContentChangedEvent"|"AgentStartEvent"|"NodeDiscoveredEvent"|"NodeRemovedEvent"' src/
# Should return nothing (all replaced with EventType enum)

# 6. Verify lambda wrappers are gone
rg "lambda \*\*kwargs: create_kernel" src/
# Should return nothing

# 7. Verify rate limiter state is on Actor, not TurnContext
rg "_send_message_timestamps" src/
# Should return nothing (replaced with SlidingWindowRateLimiter)
```

## File Deletion Checklist

Files that should be deleted during this refactor:
- `src/remora/code/projections.py` (Phase 1.1)
- `tests/unit/test_projections.py` (Phase 1.1)

## New File Checklist

Files that should be created during this refactor:
- `src/remora/code/watcher.py` (Phase 3.1)
- `src/remora/code/directories.py` (Phase 3.1)
- `src/remora/code/virtual_agents.py` (Phase 3.1)
- `src/remora/web/deps.py` (Phase 3.2)
- `src/remora/web/middleware.py` (Phase 3.2)
- `src/remora/web/sse.py` (Phase 3.2)
- `src/remora/web/paths.py` (Phase 3.2)
- `src/remora/web/routes/__init__.py` (Phase 3.2)
- `src/remora/web/routes/nodes.py` (Phase 3.2)
- `src/remora/web/routes/events.py` (Phase 3.2)
- `src/remora/web/routes/proposals.py` (Phase 3.2)
- `src/remora/web/routes/chat.py` (Phase 3.2)
- `src/remora/web/routes/search.py` (Phase 3.2)
- `src/remora/web/routes/health.py` (Phase 3.2)
- `src/remora/web/routes/cursor.py` (Phase 3.2)

## Summary

| Phase | Sections | Key Outcome |
|-------|----------|-------------|
| **Phase 1** | 1.1–1.6 | Eliminate dual model, clean up config, remove test indirection |
| **Phase 2** | 2.1–2.2 | Fix event dispatch bug, fix rate limiter bug |
| **Phase 3** | 3.1–3.2 | Decompose the two largest files (reconciler + web server) |
| **Phase 4** | 4.1–4.2 | Simplify turn pipeline, decompose externals god-object |
| **Phase 5** | 5.1–5.5 | Batch commits, clean caching, transaction fixes, misc polish |

Each phase is independent — complete one phase fully (with passing tests) before starting the next. Within a phase, sections should be done in order as later sections may depend on earlier ones.
