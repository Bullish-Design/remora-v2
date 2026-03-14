# Alignment Refactoring Guide

> Step-by-step instructions for removing all backward-compatibility shims, legacy aliases, stale naming, and repository clutter from the remora-v2 codebase. After completing this guide, the codebase will have a single canonical vocabulary, no migration code in hot paths, and a clean repository with no generated artifacts.

## Prerequisites

- Run the full test suite before starting: `uv run pytest tests/`
- Commit (or stash) any unrelated work so you have a clean baseline
- Work through the steps **in order** — later steps depend on earlier ones
- After each numbered step, run `uv run pytest tests/` to catch breakage early
- Each major section (Phase A–D) should be its own commit

---

## Phase A: Remove Public Compatibility Aliases

**Goal:** One canonical name per concept. No old type aliases in public exports.

### Step A1: Remove class aliases from `src/remora/core/node.py`

1. **Delete lines 138–139** (the alias assignments):
   ```python
   # DELETE these lines:
   CodeElement = DiscoveredElement
   CodeNode = Node
   ```

2. **Update `__all__` on line 142** to remove the old names:
   ```python
   # BEFORE:
   __all__ = ["DiscoveredElement", "Agent", "Node", "CodeElement", "CodeNode"]
   # AFTER:
   __all__ = ["DiscoveredElement", "Agent", "Node"]
   ```

3. **Update the `Node` class docstring on line 66** — it currently says "Combined view for migration and backwards compatibility". Replace with something accurate:
   ```python
   # BEFORE:
   """Combined view for migration and backwards compatibility."""
   # AFTER:
   """Unified node model joining discovered element data with agent state."""
   ```

4. **Verify:** `grep -rn "CodeElement\|CodeNode" src/ tests/` should return zero hits in remora source (ignore `.context/`).

### Step A2: Remove class alias from `src/remora/core/actor.py`

1. **Delete line 454** (the alias):
   ```python
   # DELETE:
   AgentActor = Actor
   ```

2. **Update `__all__` on line 451** to remove the old name:
   ```python
   # BEFORE:
   __all__ = ["Outbox", "RecordingOutbox", "Trigger", "Actor", "AgentActor"]
   # AFTER:
   __all__ = ["Outbox", "RecordingOutbox", "Trigger", "Actor"]
   ```

3. **Verify:** `grep -rn "AgentActor" src/ tests/` should return zero hits.

### Step A3: Remove class alias from `src/remora/core/runner.py`

1. **Delete line 115** (the alias):
   ```python
   # DELETE:
   AgentRunner = ActorPool
   ```

2. **Update `__all__` on line 118**:
   ```python
   # BEFORE:
   __all__ = ["ActorPool", "AgentRunner"]
   # AFTER:
   __all__ = ["ActorPool"]
   ```

3. **Verify:** `grep -rn "AgentRunner" src/ tests/` should return zero hits in remora source.

### Step A4: Remove class alias and method alias from `src/remora/core/externals.py`

1. **Delete lines 274–276** (the `to_externals_dict` method):
   ```python
   # DELETE:
   def to_externals_dict(self) -> dict[str, Any]:
       """Backward-compatible alias for to_capabilities_dict."""
       return self.to_capabilities_dict()
   ```

2. **Delete line 308** (the class alias):
   ```python
   # DELETE:
   AgentContext = TurnContext
   ```

3. **Update `__all__` on line 311**:
   ```python
   # BEFORE:
   __all__ = ["TurnContext", "AgentContext"]
   # AFTER:
   __all__ = ["TurnContext"]
   ```

4. **Verify:** `grep -rn "AgentContext\|to_externals_dict" src/ tests/` should return zero hits in remora source (ignore `.context/` which is vendored deps).

### Step A5: Remove `initialize()` alias from `src/remora/core/events/store.py`

1. **Delete lines 67–69** (the alias method):
   ```python
   # DELETE:
   async def initialize(self) -> None:
       """Backward-compatible alias for create_tables."""
       await self.create_tables()
   ```

2. **Verify:** `grep -rn "\.initialize()" src/ tests/` — ensure no remora code calls `event_store.initialize()`. If any callers exist, change them to call `create_tables()` instead.

### Step A6: Remove `initialize()` alias from `src/remora/core/events/subscriptions.py`

1. **Delete lines 73–75** (the alias method):
   ```python
   # DELETE:
   async def initialize(self) -> None:
       """Backward-compatible alias for create_tables."""
       await self.create_tables()
   ```

2. **Verify:** Same check as Step A5 for subscription registry callers.

### Step A7: Replace star imports in `src/remora/core/events/__init__.py`

1. **Replace the entire file content** with explicit imports. The current file is:
   ```python
   from remora.core.events.types import *  # noqa: F401, F403
   from remora.core.events.bus import *  # noqa: F401, F403
   from remora.core.events.subscriptions import *  # noqa: F401, F403
   from remora.core.events.store import *  # noqa: F401, F403
   from remora.core.events.dispatcher import *  # noqa: F401, F403
   ```

2. **Replace with explicit imports** — import only the symbols from each submodule's `__all__`:
   ```python
   """Event system: types, bus, subscriptions, persistence, and dispatch."""

   from remora.core.events.bus import EventBus
   from remora.core.events.dispatcher import TriggerDispatcher
   from remora.core.events.store import EventStore
   from remora.core.events.subscriptions import SubscriptionPattern, SubscriptionRegistry
   from remora.core.events.types import (
       AgentCompleteEvent,
       AgentErrorEvent,
       AgentMessageEvent,
       AgentStartEvent,
       ContentChangedEvent,
       CustomEvent,
       Event,
       EventHandler,
       NodeChangedEvent,
       NodeDiscoveredEvent,
       NodeRemovedEvent,
       ToolResultEvent,
   )

   __all__ = [
       "Event",
       "AgentStartEvent",
       "AgentCompleteEvent",
       "AgentErrorEvent",
       "AgentMessageEvent",
       "NodeDiscoveredEvent",
       "NodeRemovedEvent",
       "NodeChangedEvent",
       "ContentChangedEvent",
       "CustomEvent",
       "ToolResultEvent",
       "EventHandler",
       "EventBus",
       "SubscriptionPattern",
       "SubscriptionRegistry",
       "EventStore",
       "TriggerDispatcher",
   ]
   ```

3. **Verify:** Run the full test suite. All existing imports like `from remora.core.events import EventStore, AgentMessageEvent` should still work because the explicit imports provide the same symbols.

---

## Phase B: Remove Legacy Field and Config Migration Paths

**Goal:** Runtime models and config reject old field names. No silent migration.

### Step B1: Remove `bundle_name` migration from `Agent` in `src/remora/core/node.py`

1. **Delete lines 42–49** (the `_migrate_bundle_name` model validator on `Agent`):
   ```python
   # DELETE the entire validator:
   @model_validator(mode="before")
   @classmethod
   def _migrate_bundle_name(cls, data: Any) -> Any:
       if isinstance(data, dict) and "bundle_name" in data and "role" not in data:
           copied = dict(data)
           copied["role"] = copied.pop("bundle_name")
           return copied
       return data
   ```

2. **Delete lines 60–62** (the `bundle_name` property on `Agent`):
   ```python
   # DELETE:
   @property
   def bundle_name(self) -> str | None:
       return self.role
   ```

### Step B2: Remove `bundle_name` migration from `Node` in `src/remora/core/node.py`

1. **Delete lines 85–92** (the `_migrate_bundle_name` model validator on `Node`):
   ```python
   # DELETE the entire validator
   ```

2. **Delete lines 133–135** (the `bundle_name` property on `Node`):
   ```python
   # DELETE:
   @property
   def bundle_name(self) -> str | None:
       return self.role
   ```

### Step B3: Remove legacy config migration from `src/remora/core/config.py`

1. **Delete lines 99–109** (the `_migrate_legacy_bundle_mapping` model validator):
   ```python
   # DELETE the entire validator:
   @model_validator(mode="before")
   @classmethod
   def _migrate_legacy_bundle_mapping(cls, data: Any) -> Any:
       if isinstance(data, dict):
           copied = dict(data)
           if "bundle_mapping" in copied and "bundle_overlays" not in copied:
               copied["bundle_overlays"] = copied.pop("bundle_mapping")
           if "swarm_root" in copied and "workspace_root" not in copied:
               copied["workspace_root"] = copied.pop("swarm_root")
           return copied
       return data
   ```

2. **Delete lines 111–119** (the `bundle_mapping` and `swarm_root` compatibility properties):
   ```python
   # DELETE both properties:
   @property
   def bundle_mapping(self) -> dict[str, str]:
       """Backward-compatible alias for bundle_overlays."""
       return self.bundle_overlays

   @property
   def swarm_root(self) -> str:
       """Backward-compatible alias for workspace_root."""
       return self.workspace_root
   ```

### Step B4: Update `remora.yaml.example` to use modern keys

1. **Open `remora.yaml.example`** and replace the two deprecated keys:
   - Line 12: change `bundle_mapping:` to `bundle_overlays:`
   - Line 22: change `swarm_root: ".remora"` to `workspace_root: ".remora"`

   The complete corrected file should be:
   ```yaml
   # Copy to remora.yaml and adjust for your project.
   project_path: "."
   discovery_paths:
     - "src/"
   language_map:
     ".py": "python"
     ".md": "markdown"
     ".toml": "toml"
   query_paths:
     - "queries/"
   bundle_root: "bundles"
   bundle_overlays:
     function: "code-agent"
     class: "code-agent"
     method: "code-agent"
     file: "code-agent"
   model_base_url: "http://localhost:8000/v1"
   model_default: "Qwen/Qwen3-4B"
   model_api_key: "${OPENAI_API_KEY:-}"
   timeout_s: 300.0
   max_turns: 8
   workspace_root: ".remora"
   max_concurrency: 4
   max_trigger_depth: 5
   trigger_cooldown_ms: 1000
   workspace_ignore_patterns:
     - ".git"
     - ".venv"
     - "__pycache__"
     - "node_modules"
     - ".remora"
   ```

### Step B5: Update tests that assert legacy compatibility behavior

These tests were specifically written to verify backward-compatibility. They must be **replaced** with tests that verify old keys are **rejected**.

#### 1. `tests/unit/test_config.py`

**Line 18** — Remove usage of `config.bundle_mapping` accessor:
```python
# BEFORE (in test_default_config):
assert config.bundle_mapping["function"] == "code-agent"
# AFTER: delete this line entirely (it tests the removed property)
```

**Lines 23–25** — Replace `test_legacy_bundle_mapping_alias_still_loads` with a rejection test:
```python
# BEFORE:
def test_legacy_bundle_mapping_alias_still_loads() -> None:
    config = Config(bundle_mapping={"function": "special-agent"})
    assert config.bundle_overlays["function"] == "special-agent"

# AFTER:
def test_legacy_bundle_mapping_key_rejected() -> None:
    """Old 'bundle_mapping' key is no longer silently migrated."""
    with pytest.raises(ValidationError):
        Config(bundle_mapping={"function": "special-agent"})
```

#### 2. `tests/unit/test_refactor_naming.py`

**Lines 29–34** — Replace `test_config_workspace_root_aliases_legacy_swarm_root` with a rejection test:
```python
# BEFORE:
def test_config_workspace_root_aliases_legacy_swarm_root() -> None:
    config = Config(workspace_root=".remora-workspace")
    assert config.workspace_root == ".remora-workspace"

    legacy = Config(swarm_root=".remora-legacy")
    assert legacy.workspace_root == ".remora-legacy"

# AFTER:
def test_config_workspace_root_works() -> None:
    config = Config(workspace_root=".remora-workspace")
    assert config.workspace_root == ".remora-workspace"


def test_legacy_swarm_root_key_rejected() -> None:
    """Old 'swarm_root' key is no longer silently migrated."""
    with pytest.raises(ValidationError):
        Config(swarm_root=".remora-legacy")
```

(Add `from pydantic import ValidationError` to the imports of this file.)

---

## Phase C: Remove Runtime Migration Code and Internal Boundary Leaks

**Goal:** No schema-upgrade logic in steady-state runtime paths. No DB internals exposed for test convenience.

### Step C1: Remove DB schema migration helpers from `src/remora/core/graph.py`

These methods rename the old `bundle_name` column to `role` at runtime. Since Phase B ensures only `role` is used, these are no longer needed.

1. **In `NodeStore`, delete lines 205–216** (the `_migrate_role_columns` and `_table_columns` methods):
   ```python
   # DELETE:
   async def _migrate_role_columns(self) -> None:
       ...

   async def _table_columns(self, table_name: str) -> set[str]:
       ...
   ```

2. **In `NodeStore.create_tables()`, delete line 78** (the call to the migration):
   ```python
   # DELETE:
   await self._migrate_role_columns()
   ```

3. **In `AgentStore`, delete lines 289–293** (the `_migrate_role_column` method):
   ```python
   # DELETE:
   async def _migrate_role_column(self) -> None:
       ...
   ```

4. **In `AgentStore.create_tables()`, delete line 238** (the call to the migration):
   ```python
   # DELETE:
   await self._migrate_role_column()
   ```

### Step C2: Remove `EventStore.connection` and `EventStore.lock` escape hatches from `src/remora/core/events/store.py`

1. **Delete lines 37–43** (the `connection` and `lock` properties):
   ```python
   # DELETE:
   @property
   def connection(self):  # noqa: ANN201
       return self._db.connection

   @property
   def lock(self) -> asyncio.Lock:
       return self._db.lock
   ```

2. **Also remove the `asyncio` import** if no longer needed (check first — it may still be used elsewhere in the file). Currently it is only used for the `lock` return type, so it can be removed.

### Step C3: Remove `SubscriptionRegistry.db` property from `src/remora/core/events/subscriptions.py`

1. **Delete lines 55–57** (the `db` property):
   ```python
   # DELETE:
   @property
   def db(self) -> AsyncDB:
       return self._db
   ```

### Step C4: Remove `NodeStore.db` property from `src/remora/core/graph.py`

1. **Delete lines 31–33** (the `db` property):
   ```python
   # DELETE:
   @property
   def db(self) -> AsyncDB:
       return self._db
   ```

### Step C5: Add `NodeStore.list_all_edges()` method and fix web server

The web server at `src/remora/web/server.py:55` bypasses the store abstraction with `node_store.db.fetch_all(...)`. Now that `db` is removed, this needs a proper store method.

1. **Add a new method to `NodeStore` in `src/remora/core/graph.py`**, after the existing `get_edges` method:
   ```python
   async def list_all_edges(self) -> list[Edge]:
       """Return all edges in the graph."""
       rows = await self._db.fetch_all(
           "SELECT from_id, to_id, edge_type FROM edges ORDER BY id ASC"
       )
       return [
           Edge(from_id=row["from_id"], to_id=row["to_id"], edge_type=row["edge_type"])
           for row in rows
       ]
   ```

2. **Update `src/remora/web/server.py` lines 54–58** to use the new method:
   ```python
   # BEFORE:
   async def api_all_edges(_request: Request) -> JSONResponse:
       rows = await node_store.db.fetch_all(
           "SELECT from_id, to_id, edge_type FROM edges ORDER BY id ASC"
       )
       return JSONResponse([dict(row) for row in rows])

   # AFTER:
   async def api_all_edges(_request: Request) -> JSONResponse:
       edges = await node_store.list_all_edges()
       return JSONResponse([
           {"from_id": edge.from_id, "to_id": edge.to_id, "edge_type": edge.edge_type}
           for edge in edges
       ])
   ```

### Step C6: Fix tests that use removed internal properties

#### 1. `tests/unit/test_graph.py` — `test_shared_connection` (lines 122–135)

This test verifies that NodeStore and EventStore share the same DB connection. Since the `connection` and `lock` properties are removed, **rewrite the test** to verify shared DB behavior through public APIs instead:

```python
# BEFORE:
async def test_shared_connection(db) -> None:
    node_store = NodeStore(db)
    event_store = EventStore(db=db)
    await node_store.create_tables()
    await event_store.create_tables()
    await node_store.upsert_node(make_node("src/app.py::a"))
    event_id = await event_store.append(AgentStartEvent(agent_id="src/app.py::a"))
    got = await node_store.get_node("src/app.py::a")

    assert got is not None
    assert event_id == 1
    assert node_store.db.connection is event_store.connection
    assert node_store.db.lock is event_store.lock

# AFTER:
async def test_shared_db_coexistence(db) -> None:
    """Node and event stores sharing a DB can read/write without conflict."""
    node_store = NodeStore(db)
    event_store = EventStore(db=db)
    await node_store.create_tables()
    await event_store.create_tables()
    await node_store.upsert_node(make_node("src/app.py::a"))
    event_id = await event_store.append(AgentStartEvent(agent_id="src/app.py::a"))
    got = await node_store.get_node("src/app.py::a")

    assert got is not None
    assert event_id == 1
```

#### 2. `tests/unit/test_reconciler.py` — Direct SQL via `event_store.connection`

Three tests use `event_store.connection.execute(...)` for raw SQL. These must be rewritten to use public store APIs.

**`test_full_scan_discovers_registers_and_emits` (line 69):**

Replace the direct SQL subscription query with a public API approach. The subscriptions can be verified by checking that agents receive dispatched events, or by using the `SubscriptionRegistry` API. The simplest approach:

```python
# BEFORE (line 69):
subs = event_store.connection.execute("SELECT * FROM subscriptions").fetchall()

# AFTER — use the subscription registry's public matching API to verify:
# Remove direct SQL query and instead verify subscription behavior.
# Replace lines 69 and 79-95 with:
    for node in stored:
        from remora.core.events.types import NodeChangedEvent as NCE
        test_event = NCE(node_id=node.node_id, old_hash="x", new_hash="y", file_path=node.file_path)
        matched = await event_store.subscriptions.get_matching_agents(test_event)
        if node.node_type == "directory":
            # Directories subscribe to NodeChangedEvent + ContentChangedEvent + direct messages
            assert node.node_id in matched
```

Alternatively, the simplest minimal fix is to use the `SubscriptionRegistry` db through the subscription's own `_rebuild_cache` or test the matching behavior indirectly.

**`test_reconcile_subscription_idempotency` (lines 159–161):**

```python
# BEFORE:
conn = event_store.connection
assert conn is not None
rows = conn.execute("SELECT agent_id, pattern_json FROM subscriptions").fetchall()

# AFTER — use the subscription registry to verify matching behavior:
# Verify that for each node, subscription matching works correctly
# by testing that events directed at each node match.
nodes = await node_store.list_nodes()
for node in nodes:
    from remora.core.events.types import AgentMessageEvent as AME
    direct_event = AME(from_agent="test", to_agent=node.node_id, content="test")
    matched = await event_store.subscriptions.get_matching_agents(direct_event)
    assert node.node_id in matched
```

**`test_directory_subscriptions_upgraded_on_startup` (lines 284–327):**

This test inserts old-format subscriptions directly via SQL and verifies they get replaced. Since the reconciler already re-registers subscriptions on startup (via `_subscriptions_bootstrapped = False`), rewrite this test to verify the current startup behavior without needing raw SQL:

```python
# AFTER: Test that a fresh reconciler re-registers subscriptions on startup
@pytest.mark.asyncio
async def test_directory_subscriptions_refreshed_on_startup(reconcile_env, tmp_path: Path) -> None:
    node_store, agent_store, event_store, workspace_service, config, reconciler = reconcile_env
    write_file(tmp_path / "src" / "app.py", "def a():\n    return 1\n")
    await reconciler.full_scan()

    # Unregister all subscriptions for root directory
    await event_store.subscriptions.unregister_by_agent(".")

    # A new reconciler should re-register subscriptions on its first cycle
    restart_reconciler = FileReconciler(
        config,
        node_store,
        agent_store,
        event_store,
        workspace_service,
        project_root=tmp_path,
    )
    await restart_reconciler.reconcile_cycle()

    # Verify root directory now has subscriptions for NodeChangedEvent
    from remora.core.events.types import NodeChangedEvent as NCE
    test_event = NCE(node_id=".", old_hash="x", new_hash="y", file_path=".")
    matched = await event_store.subscriptions.get_matching_agents(test_event)
    assert "." in matched
```

---

## Phase D: Repository Hygiene and Messaging Alignment

**Goal:** Docstrings/UI reflect current concepts. No generated artifacts tracked in git. Broken tool contracts fixed.

### Step D1: Update stale naming in `src/remora/code/projections.py`

1. **Line 1** — Update module docstring:
   ```python
   # BEFORE:
   """Projection from discovered CST nodes into persisted CodeNodes."""
   # AFTER:
   """Projection from discovered CST nodes into persisted Nodes."""
   ```

2. **Line 23** — Update function docstring:
   ```python
   # BEFORE:
   """Project CSTNodes into CodeNodes and provision bundles for new nodes."""
   # AFTER:
   """Project CSTNodes into Nodes and provision bundles for new nodes."""
   ```

### Step D2: Update stale naming in `src/remora/core/actor.py`

1. **Line 220** — Update comment:
   ```python
   # BEFORE:
   """Execute one agent turn. Reuses logic from the old ActorPool._execute_turn."""
   # AFTER:
   """Execute one agent turn."""
   ```

### Step D3: Fix UI copy in `src/remora/web/static/index.html`

1. **Line 90** — Update the sidebar meta text:
   ```html
   <!-- BEFORE: -->
   <div class="meta">Live swarm graph and companion panel</div>
   <!-- AFTER: -->
   <div class="meta">Live agent graph</div>
   ```

### Step D4: Guard LSP optional import in `src/remora/lsp/__init__.py`

The current code unconditionally imports from `remora.lsp.server`, which requires `pygls` as a dependency. If `pygls` is not installed, this import will fail at module load time.

1. **Replace the entire file with a lazy import**:
   ```python
   """LSP adapter package."""


   def create_lsp_server(*args, **kwargs):
       """Create the LSP server, raising a clear error if pygls is missing."""
       try:
           from remora.lsp.server import create_lsp_server as _create
       except ImportError as exc:
           raise ImportError(
               "LSP support requires pygls. Install with: pip install remora[lsp]"
           ) from exc
       return _create(*args, **kwargs)


   __all__ = ["create_lsp_server"]
   ```

### Step D5: Fix broken `rewrite_self.pym` tool contract

The tool at `bundles/code-agent/tools/rewrite_self.pym` calls `propose_rewrite` which does not exist in the `TurnContext` capabilities API. The correct function is `apply_rewrite`.

1. **Replace the contents of `bundles/code-agent/tools/rewrite_self.pym`**:
   ```python
   from grail import Input, external

   new_source: str = Input("new_source")


   @external
   async def apply_rewrite(new_source: str) -> bool: ...


   success = await apply_rewrite(new_source)
   message = f"Rewrite applied: {success}"
   message
   ```

   Key changes:
   - `propose_rewrite` → `apply_rewrite` (matches `TurnContext.apply_rewrite`)
   - Return type `str` → `bool` (matches the actual method signature)
   - Updated message format

### Step D6: Remove tracked `.grail` artifacts from git

The `.grail/` directory contains 115 compiled/cached tool outputs that should not be tracked in source control. This includes random temp files like `.grail/tmp98yh9rr7/`.

1. **Add `.grail/` to `.gitignore`**:
   ```
   # Grail compiled tool cache
   .grail/
   ```

2. **Remove the tracked files from git** (keeps them on disk):
   ```bash
   git rm -r --cached .grail/
   ```

3. **Commit this change** with a message like "remove tracked .grail artifacts and add ignore rule".

### Step D7: Update stale test function names

Several test functions use the old `codenode` naming:

In `tests/unit/test_node.py`:
- **Line 29**: Rename `test_codenode_creation` → `test_node_creation`
- **Line 36**: Rename `test_codenode_roundtrip` → `test_node_roundtrip`
- **Line 43**: Rename `test_codenode_element_and_agent_projection` → `test_node_element_and_agent_projection`
- **Line 53**: Rename `test_codenode_rejects_invalid_status` → `test_node_rejects_invalid_status`

---

## Final Verification Checklist

After completing all phases, run these checks:

### 1. Full test suite passes
```bash
uv run pytest tests/ -v
```

### 2. No compatibility aliases remain in source
```bash
# Should return zero hits in src/ and tests/ (ignore .context/):
grep -rn "CodeElement\|CodeNode\|AgentActor\|AgentRunner\|AgentContext\|to_externals_dict" src/ tests/
grep -rn "bundle_mapping\|swarm_root\|bundle_name" src/ tests/
```

### 3. No migration validators in models
```bash
grep -rn "_migrate_bundle_name\|_migrate_legacy_bundle_mapping\|_migrate_role_column" src/
# Should return zero hits
```

### 4. No `initialize()` alias methods
```bash
grep -rn "async def initialize" src/remora/core/events/
# Should return zero hits
```

### 5. No `.grail` files tracked
```bash
git ls-files .grail | wc -l
# Should return 0
```

### 6. No internal DB access in tests
```bash
grep -rn "event_store\.connection\|event_store\.lock\|node_store\.db\." tests/
# Should return zero hits
```

### 7. Example config uses modern keys
```bash
grep -n "bundle_mapping\|swarm_root" remora.yaml.example
# Should return zero hits
```

### 8. `rewrite_self.pym` uses correct API
```bash
grep "propose_rewrite" bundles/
# Should return zero hits
grep "apply_rewrite" bundles/code-agent/tools/rewrite_self.pym
# Should return a hit
```

---

## Summary of Files Modified

| File | Changes |
|------|---------|
| `src/remora/core/node.py` | Remove `CodeElement`, `CodeNode` aliases; remove `_migrate_bundle_name` validators; remove `bundle_name` properties; update `Node` docstring; update `__all__` |
| `src/remora/core/actor.py` | Remove `AgentActor` alias; update `__all__`; update stale comment |
| `src/remora/core/runner.py` | Remove `AgentRunner` alias; update `__all__` |
| `src/remora/core/externals.py` | Remove `to_externals_dict` method; remove `AgentContext` alias; update `__all__` |
| `src/remora/core/config.py` | Remove `_migrate_legacy_bundle_mapping` validator; remove `bundle_mapping` and `swarm_root` properties |
| `src/remora/core/graph.py` | Remove `_migrate_role_columns`, `_migrate_role_column`, `_table_columns` methods; remove migration calls from `create_tables`; remove `NodeStore.db` property; add `list_all_edges()` method |
| `src/remora/core/events/__init__.py` | Replace star imports with explicit imports and `__all__` |
| `src/remora/core/events/store.py` | Remove `initialize()` alias; remove `connection` and `lock` properties |
| `src/remora/core/events/subscriptions.py` | Remove `initialize()` alias; remove `db` property |
| `src/remora/code/projections.py` | Update docstrings from "CodeNodes" to "Nodes" |
| `src/remora/lsp/__init__.py` | Add lazy import with clear error message |
| `src/remora/web/server.py` | Use `node_store.list_all_edges()` instead of raw DB access |
| `src/remora/web/static/index.html` | Update "swarm graph and companion panel" → "agent graph" |
| `remora.yaml.example` | `bundle_mapping` → `bundle_overlays`; `swarm_root` → `workspace_root` |
| `bundles/code-agent/tools/rewrite_self.pym` | `propose_rewrite` → `apply_rewrite` with correct signature |
| `.gitignore` | Add `.grail/` |
| `tests/unit/test_config.py` | Replace legacy-alias test with rejection test; remove `bundle_mapping` accessor usage |
| `tests/unit/test_refactor_naming.py` | Replace `swarm_root` alias test with rejection test |
| `tests/unit/test_graph.py` | Rewrite `test_shared_connection` to not use internal properties |
| `tests/unit/test_reconciler.py` | Rewrite 3 tests to not use `event_store.connection` for raw SQL |
| `tests/unit/test_node.py` | Rename `test_codenode_*` → `test_node_*` |
