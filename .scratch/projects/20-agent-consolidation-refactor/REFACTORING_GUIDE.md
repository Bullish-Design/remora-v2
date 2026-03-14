# Agent Consolidation Refactoring Guide

Merge Node and Agent into a single source of truth, eliminate the `agents` table and `AgentStore`, and clean up all dual-status coordination. No backwards compatibility. No shims.

## Table of Contents

1. **[Goal & Rationale](#1-goal--rationale)** — What we're doing and why
2. **[Before You Start](#2-before-you-start)** — Prerequisites and baseline
3. **[Step 1: Delete Agent Model and DiscoveredElement](#step-1-delete-agent-model-and-discoveredelement)** — Clean `core/node.py`
4. **[Step 2: Delete AgentStore](#step-2-delete-agentstore)** — Remove from `core/graph.py`
5. **[Step 3: Update Actor — Remove Dual Status Tracking](#step-3-update-actor--remove-dual-status-tracking)** — Simplify `core/actor.py`
6. **[Step 4: Update TurnContext — Remove agent_store](#step-4-update-turncontext--remove-agent_store)** — Simplify `core/externals.py`
7. **[Step 5: Update ActorPool — Remove agent_store](#step-5-update-actorpool--remove-agent_store)** — Simplify `core/runner.py`
8. **[Step 6: Update FileReconciler — Remove _ensure_agent](#step-6-update-filereconciler--remove-_ensure_agent)** — Simplify `code/reconciler.py`
9. **[Step 7: Update RuntimeServices](#step-7-update-runtimeservices)** — Remove agent_store wiring from `core/services.py`
10. **[Step 8: Update Test Factories](#step-8-update-test-factories)** — Clean `tests/factories.py`
11. **[Step 9: Delete test_agent_store.py](#step-9-delete-test_agent_storepy)** — Remove dead test file
12. **[Step 10: Update test_node.py](#step-10-update-test_nodepy)** — Remove Agent/DiscoveredElement tests
13. **[Step 11: Update test_graph.py](#step-11-update-test_graphpy)** — No AgentStore references
14. **[Step 12: Update test_actor.py](#step-12-update-test_actorpy)** — Remove all agent_store usage
15. **[Step 13: Update test_externals.py](#step-13-update-test_externalspy)** — Remove agent_store from fixtures
16. **[Step 14: Update test_runner.py](#step-14-update-test_runnerpy)** — Remove agent_store from fixtures
17. **[Step 15: Update test_reconciler.py](#step-15-update-test_reconcilerpy)** — Remove agent_store from fixtures
18. **[Step 16: Update Integration Tests](#step-16-update-integration-tests)** — e2e, llm_turn, performance
19. **[Step 17: Update Remaining Test Files](#step-17-update-remaining-test-files)** — Grep and clean stragglers
20. **[Step 18: Clean Up Imports and __all__](#step-18-clean-up-imports-and-__all__)** — Remove all dead references
21. **[Step 19: Run Full Test Suite and Fix](#step-19-run-full-test-suite-and-fix)** — Verify everything passes
22. **[Step 20: Final Audit](#step-20-final-audit)** — Grep for any remaining references

---

## 1. Goal & Rationale

### The Problem

Today, agent status is tracked in **two places**:

1. **`nodes` table** via `NodeStore` — has a `status` column
2. **`agents` table** via `AgentStore` — has a separate `status` column

Every status change must update both stores, creating 6+ coordination points:

- `Actor._start_agent_turn()` — transitions both to RUNNING
- `Actor._execute_turn()` error handler — transitions both to ERROR
- `Actor._reset_agent_state()` — resets both to IDLE
- `TurnContext.graph_set_status()` — updates both
- `FileReconciler._ensure_agent()` — creates agent rows mirroring nodes
- `FileReconciler._remove_node()` — deletes from both

If either update fails or is skipped, the stores diverge silently. The `agents` table adds no information that isn't already on `nodes` — `agent_id == node_id`, `element_id == node_id`, and `status`/`role` are identical.

### The Solution

Delete the `agents` table and `AgentStore` entirely. The `nodes` table is the single source of truth. All status operations go through `NodeStore` only.

### What Gets Deleted

- `Agent` class in `core/node.py`
- `DiscoveredElement` class in `core/node.py` (dead code — only used by `Node.to_element()`)
- `Node.to_agent()` method
- `Node.to_element()` method
- `AgentStore` class in `core/graph.py`
- `agents` table schema
- `test_agent_store.py` test file
- All `_ensure_agent` calls in reconciler
- All dual-update coordination code in actor, externals, runner

### Files Changed

| File | Change Type |
|------|-------------|
| `src/remora/core/node.py` | Delete `Agent`, `DiscoveredElement`, `to_agent()`, `to_element()` |
| `src/remora/core/graph.py` | Delete `AgentStore` class (~80 lines) |
| `src/remora/core/actor.py` | Remove `agent_store` param, simplify status tracking |
| `src/remora/core/externals.py` | Remove `agent_store` param, simplify `graph_set_status` |
| `src/remora/core/runner.py` | Remove `agent_store` param from `ActorPool` |
| `src/remora/core/services.py` | Remove `agent_store` creation and wiring |
| `src/remora/code/reconciler.py` | Remove `agent_store` param, delete `_ensure_agent` |
| `tests/factories.py` | Remove `to_agent` usage if any |
| `tests/unit/test_agent_store.py` | **DELETE entirely** |
| `tests/unit/test_node.py` | Remove `Agent`/`DiscoveredElement` tests |
| `tests/unit/test_graph.py` | No changes needed (doesn't use AgentStore) |
| `tests/unit/test_actor.py` | Remove all `agent_store` fixture setup and assertions |
| `tests/unit/test_externals.py` | Remove `agent_store` from fixtures and context creation |
| `tests/unit/test_runner.py` | Remove `agent_store` from fixtures |
| `tests/unit/test_reconciler.py` | Remove `agent_store` from fixtures |
| `tests/unit/test_refactor_naming.py` | Remove `to_agent()` assertion |
| `tests/integration/test_e2e.py` | Remove `AgentStore` creation |
| `tests/integration/test_llm_turn.py` | Remove `AgentStore` creation |

---

## 2. Before You Start

1. **Run the full test suite** to confirm your baseline is green:
   ```bash
   devenv shell -- uv sync --extra dev
   devenv shell -- python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q
   ```
   Expected: **208 passed, 4 skipped**

2. **Create a git branch**:
   ```bash
   git checkout -b refactor/agent-consolidation
   ```

3. **Read this entire guide** before making any changes. The steps are ordered to minimize broken intermediate states, but understanding the full picture helps.

---

## Step 1: Delete Agent Model and DiscoveredElement

**File**: `src/remora/core/node.py`

### 1a. Delete `DiscoveredElement` class

Delete the entire class (lines 13-30 in current code):

```python
# DELETE THIS ENTIRE CLASS:
class DiscoveredElement(BaseModel):
    """An immutable code structure discovered from source."""
    ...
```

### 1b. Delete `Agent` class

Delete the entire class (lines 32-49 in current code):

```python
# DELETE THIS ENTIRE CLASS:
class Agent(BaseModel):
    """An autonomous agent that may be attached to a code element."""
    ...
```

### 1c. Delete `Node.to_element()` method

Delete lines 72-86:

```python
# DELETE THIS METHOD:
def to_element(self) -> DiscoveredElement:
    ...
```

### 1d. Delete `Node.to_agent()` method

Delete lines 88-94:

```python
# DELETE THIS METHOD:
def to_agent(self) -> Agent:
    ...
```

### 1e. Clean up imports

Remove the unused `model_validator` import (it was never used):

```python
# BEFORE:
from pydantic import BaseModel, ConfigDict, model_validator

# AFTER:
from pydantic import BaseModel, ConfigDict
```

### 1f. Update `__all__`

```python
# BEFORE:
__all__ = ["DiscoveredElement", "Agent", "Node"]

# AFTER:
__all__ = ["Node"]
```

### 1g. Remove `sqlite3` import

The `sqlite3` import was only used for `Agent.from_row`'s type hint. `Node.from_row` also references `sqlite3.Row` — update it to use `aiosqlite.Row` or just `Any`:

```python
# BEFORE:
import sqlite3
...
@classmethod
def from_row(cls, row: sqlite3.Row | dict[str, Any]) -> "Node":

# AFTER:
# (remove the sqlite3 import entirely)
@classmethod
def from_row(cls, row: dict[str, Any]) -> "Node":
```

### Final state of `core/node.py`

The file should contain only the `Node` class with `to_row()` and `from_row()` methods. ~50 lines total.

---

## Step 2: Delete AgentStore

**File**: `src/remora/core/graph.py`

### 2a. Delete the entire `AgentStore` class

Delete lines 221-302 (the entire `AgentStore` class).

### 2b. Remove `Agent` import

```python
# BEFORE:
from remora.core.node import Agent, Node

# AFTER:
from remora.core.node import Node
```

### 2c. Update `__all__`

```python
# BEFORE:
__all__ = ["Edge", "NodeStore", "AgentStore"]

# AFTER:
__all__ = ["Edge", "NodeStore"]
```

### 2d. Remove `validate_status_transition` import if unused

Check: `NodeStore.transition_status` uses `validate_status_transition`. Keep it.

The `AgentStore` import of `validate_status_transition` was used by `AgentStore.transition_status` — since `AgentStore` is deleted, verify the import is still needed for `NodeStore`. It is, so keep it.

---

## Step 3: Update Actor — Remove Dual Status Tracking

**File**: `src/remora/core/actor.py`

This is the largest change. The actor currently maintains status in both `AgentStore` and `NodeStore`. After this step, only `NodeStore` is used.

### 3a. Remove `AgentStore` import

```python
# BEFORE:
from remora.core.graph import AgentStore, NodeStore

# AFTER:
from remora.core.graph import NodeStore
```

### 3b. Remove `agent_store` from `Actor.__init__`

```python
# BEFORE:
def __init__(
    self,
    node_id: str,
    event_store: EventStore,
    node_store: NodeStore,
    agent_store: AgentStore,
    workspace_service: CairnWorkspaceService,
    config: Config,
    semaphore: asyncio.Semaphore,
) -> None:
    ...
    self._agent_store = agent_store
    ...

# AFTER:
def __init__(
    self,
    node_id: str,
    event_store: EventStore,
    node_store: NodeStore,
    workspace_service: CairnWorkspaceService,
    config: Config,
    semaphore: asyncio.Semaphore,
) -> None:
    ...
    # (remove self._agent_store entirely)
    ...
```

### 3c. Simplify `_start_agent_turn`

Remove the agent store check and dual transition. Only use NodeStore:

```python
# BEFORE:
async def _start_agent_turn(
    self, node_id: str, trigger: Trigger, outbox: Outbox
) -> tuple[Node, AgentWorkspace, dict[str, Any]] | None:
    node = await self._node_store.get_node(node_id)
    if node is None:
        logger.warning("Trigger for unknown node: %s", node_id)
        return None

    if await self._agent_store.get_agent(node_id) is None:
        await self._agent_store.upsert_agent(node.to_agent())
    if not await self._agent_store.transition_status(node_id, NodeStatus.RUNNING):
        logger.warning("Failed to transition node %s into running state", node_id)
        return None

    await self._node_store.transition_status(node_id, NodeStatus.RUNNING)
    ...

# AFTER:
async def _start_agent_turn(
    self, node_id: str, trigger: Trigger, outbox: Outbox
) -> tuple[Node, AgentWorkspace, dict[str, Any]] | None:
    node = await self._node_store.get_node(node_id)
    if node is None:
        logger.warning("Trigger for unknown node: %s", node_id)
        return None

    if not await self._node_store.transition_status(node_id, NodeStatus.RUNNING):
        logger.warning("Failed to transition node %s into running state", node_id)
        return None
    ...
```

### 3d. Simplify `_execute_turn` error handler

```python
# BEFORE (in the except block):
await self._agent_store.transition_status(node_id, NodeStatus.ERROR)
await self._node_store.transition_status(node_id, NodeStatus.ERROR)

# AFTER:
await self._node_store.transition_status(node_id, NodeStatus.ERROR)
```

### 3e. Simplify `_reset_agent_state`

```python
# BEFORE:
async def _reset_agent_state(self, node_id: str, depth_key: str | None) -> None:
    try:
        current_agent = await self._agent_store.get_agent(node_id)
        if current_agent is not None and current_agent.status == NodeStatus.RUNNING:
            await self._agent_store.transition_status(node_id, NodeStatus.IDLE)
        current_node = await self._node_store.get_node(node_id)
        if current_node is not None and current_node.status == NodeStatus.RUNNING:
            await self._node_store.transition_status(node_id, NodeStatus.IDLE)
    except Exception:
        logger.exception("Failed to reset node status for %s", node_id)
    ...

# AFTER:
async def _reset_agent_state(self, node_id: str, depth_key: str | None) -> None:
    try:
        current_node = await self._node_store.get_node(node_id)
        if current_node is not None and current_node.status == NodeStatus.RUNNING:
            await self._node_store.transition_status(node_id, NodeStatus.IDLE)
    except Exception:  # noqa: BLE001 - best effort cleanup
        logger.exception("Failed to reset node status for %s", node_id)
    ...
```

### 3f. Update `_prepare_turn_context`

Remove `agent_store` from `TurnContext` construction:

```python
# BEFORE:
context = TurnContext(
    node_id=node_id,
    workspace=workspace,
    correlation_id=trigger.correlation_id,
    node_store=self._node_store,
    agent_store=self._agent_store,
    event_store=self._event_store,
    outbox=outbox,
)

# AFTER:
context = TurnContext(
    node_id=node_id,
    workspace=workspace,
    correlation_id=trigger.correlation_id,
    node_store=self._node_store,
    event_store=self._event_store,
    outbox=outbox,
)
```

---

## Step 4: Update TurnContext — Remove agent_store

**File**: `src/remora/core/externals.py`

### 4a. Remove `AgentStore` import

```python
# BEFORE:
from remora.core.graph import AgentStore, NodeStore

# AFTER:
from remora.core.graph import NodeStore
```

### 4b. Remove `agent_store` from `__init__`

```python
# BEFORE:
def __init__(
    self,
    node_id: str,
    workspace: AgentWorkspace,
    correlation_id: str | None,
    node_store: NodeStore,
    agent_store: AgentStore,
    event_store: EventStore,
    outbox: Any,
) -> None:
    ...
    self._agent_store = agent_store
    ...

# AFTER:
def __init__(
    self,
    node_id: str,
    workspace: AgentWorkspace,
    correlation_id: str | None,
    node_store: NodeStore,
    event_store: EventStore,
    outbox: Any,
) -> None:
    ...
    # (remove self._agent_store entirely)
    ...
```

### 4c. Simplify `graph_set_status`

```python
# BEFORE:
async def graph_set_status(self, target_id: str, new_status: str) -> bool:
    await self._agent_store.set_status(target_id, new_status)
    await self._node_store.set_status(target_id, new_status)
    return True

# AFTER:
async def graph_set_status(self, target_id: str, new_status: str) -> bool:
    await self._node_store.set_status(target_id, new_status)
    return True
```

---

## Step 5: Update ActorPool — Remove agent_store

**File**: `src/remora/core/runner.py`

### 5a. Remove `AgentStore` import

```python
# BEFORE:
from remora.core.graph import AgentStore, NodeStore

# AFTER:
from remora.core.graph import NodeStore
```

### 5b. Remove `agent_store` from `ActorPool.__init__`

```python
# BEFORE:
def __init__(
    self,
    event_store: EventStore,
    node_store: NodeStore,
    agent_store: AgentStore,
    workspace_service: CairnWorkspaceService,
    config: Config,
    dispatcher: TriggerDispatcher | None = None,
):
    ...
    self._agent_store = agent_store
    ...

# AFTER:
def __init__(
    self,
    event_store: EventStore,
    node_store: NodeStore,
    workspace_service: CairnWorkspaceService,
    config: Config,
    dispatcher: TriggerDispatcher | None = None,
):
    ...
    # (remove self._agent_store entirely)
    ...
```

### 5c. Update `get_or_create_actor`

Remove `agent_store` from `Actor` construction:

```python
# BEFORE:
actor = Actor(
    node_id=node_id,
    event_store=self._event_store,
    node_store=self._node_store,
    agent_store=self._agent_store,
    workspace_service=self._workspace_service,
    config=self._config,
    semaphore=self._semaphore,
)

# AFTER:
actor = Actor(
    node_id=node_id,
    event_store=self._event_store,
    node_store=self._node_store,
    workspace_service=self._workspace_service,
    config=self._config,
    semaphore=self._semaphore,
)
```

---

## Step 6: Update FileReconciler — Remove _ensure_agent

**File**: `src/remora/code/reconciler.py`

### 6a. Remove `AgentStore` import

```python
# BEFORE:
from remora.core.graph import AgentStore, NodeStore

# AFTER:
from remora.core.graph import NodeStore
```

### 6b. Remove `agent_store` from `__init__`

```python
# BEFORE:
def __init__(
    self,
    config: Config,
    node_store: NodeStore,
    agent_store: AgentStore,
    event_store: EventStore,
    workspace_service: CairnWorkspaceService,
    project_root: Path,
):
    ...
    self._agent_store = agent_store
    ...

# AFTER:
def __init__(
    self,
    config: Config,
    node_store: NodeStore,
    event_store: EventStore,
    workspace_service: CairnWorkspaceService,
    project_root: Path,
):
    ...
    # (remove self._agent_store entirely)
    ...
```

### 6c. Delete `_ensure_agent` method entirely

```python
# DELETE THIS ENTIRE METHOD:
async def _ensure_agent(self, node: Node) -> None:
    if await self._agent_store.get_agent(node.node_id) is None:
        await self._agent_store.upsert_agent(node.to_agent())
```

### 6d. Remove all `_ensure_agent` calls

Search the file for `await self._ensure_agent(` and delete every line. There are calls in:

- `_materialize_directories` — new directory nodes (line ~255): delete `await self._ensure_agent(directory_node)`
- `_materialize_directories` — refresh subscriptions path (line ~280): delete `await self._ensure_agent(directory_node)`
- `_materialize_directories` — hash changed path (line ~286): delete `await self._ensure_agent(directory_node)`
- `_do_reconcile_file` — additions (line ~389): delete `await self._ensure_agent(node)`
- `_do_reconcile_file` — updates (line ~405): delete `await self._ensure_agent(node)`

### 6e. Simplify `_remove_node`

Remove `agent_store.delete_agent` call:

```python
# BEFORE:
async def _remove_node(self, node_id: str) -> None:
    node = await self._node_store.get_node(node_id)
    if node is None:
        await self._event_store.subscriptions.unregister_by_agent(node_id)
        return

    await self._event_store.subscriptions.unregister_by_agent(node_id)
    await self._agent_store.delete_agent(node_id)
    await self._node_store.delete_node(node_id)
    ...

# AFTER:
async def _remove_node(self, node_id: str) -> None:
    node = await self._node_store.get_node(node_id)
    if node is None:
        await self._event_store.subscriptions.unregister_by_agent(node_id)
        return

    await self._event_store.subscriptions.unregister_by_agent(node_id)
    await self._node_store.delete_node(node_id)
    ...
```

---

## Step 7: Update RuntimeServices

**File**: `src/remora/core/services.py`

### 7a. Remove `AgentStore` import

```python
# BEFORE:
from remora.core.graph import AgentStore, NodeStore

# AFTER:
from remora.core.graph import NodeStore
```

### 7b. Remove `agent_store` from `__init__`

```python
# DELETE this line:
self.agent_store = AgentStore(db)
```

### 7c. Remove `agent_store.create_tables()` from `initialize`

```python
# DELETE this line:
await self.agent_store.create_tables()
```

### 7d. Update `FileReconciler` construction

```python
# BEFORE:
self.reconciler = FileReconciler(
    self.config,
    self.node_store,
    self.agent_store,
    self.event_store,
    self.workspace_service,
    self.project_root,
)

# AFTER:
self.reconciler = FileReconciler(
    self.config,
    self.node_store,
    self.event_store,
    self.workspace_service,
    self.project_root,
)
```

### 7e. Update `ActorPool` construction

```python
# BEFORE:
self.runner = ActorPool(
    self.event_store,
    self.node_store,
    self.agent_store,
    self.workspace_service,
    self.config,
    dispatcher=self.dispatcher,
)

# AFTER:
self.runner = ActorPool(
    self.event_store,
    self.node_store,
    self.workspace_service,
    self.config,
    dispatcher=self.dispatcher,
)
```

---

## Step 8: Update Test Factories

**File**: `tests/factories.py`

No changes needed. `make_node` returns `Node` objects and doesn't reference `Agent` or `to_agent()`. The `make_cst` function is also unaffected.

Verify by reading the file — there are no `Agent`, `to_agent`, or `AgentStore` references.

---

## Step 9: Delete test_agent_store.py

**File**: `tests/unit/test_agent_store.py`

**Delete this entire file.** It tests `AgentStore` which no longer exists.

```bash
rm tests/unit/test_agent_store.py
```

---

## Step 10: Update test_node.py

**File**: `tests/unit/test_node.py`

### 10a. Remove imports

```python
# BEFORE:
from remora.core.node import Agent, DiscoveredElement, Node

# AFTER:
from remora.core.node import Node
```

### 10b. Delete `test_node_element_and_agent_projection`

Delete the entire test function:

```python
# DELETE THIS ENTIRE TEST:
def test_node_element_and_agent_projection() -> None:
    node = make_auth_node()
    element = node.to_element()
    agent = node.to_agent()
    assert isinstance(element, DiscoveredElement)
    assert isinstance(agent, Agent)
    assert element.element_id == node.node_id
    assert agent.agent_id == node.node_id
```

---

## Step 11: Update test_graph.py

**File**: `tests/unit/test_graph.py`

No changes needed. This file only tests `NodeStore` and `EventStore`. Verify there are no `AgentStore` references.

---

## Step 12: Update test_actor.py

**File**: `tests/unit/test_actor.py`

This is the largest test file (689 lines). The changes are mechanical but spread across many fixtures and tests.

### 12a. Remove `AgentStore` import

```python
# BEFORE:
from remora.core.graph import AgentStore, NodeStore

# AFTER:
from remora.core.graph import NodeStore
```

### 12b. Update the main fixture

Find the fixture that creates the test environment (around line 110-130). It creates an `AgentStore`, calls `create_tables()`, and puts it in a dict:

```python
# BEFORE:
agent_store = AgentStore(db)
...
await agent_store.create_tables()
...
"agent_store": agent_store,

# AFTER:
# (delete the agent_store lines entirely)
# Remove "agent_store" from the env dict
```

### 12c. Update all Actor construction calls

Every place that creates an `Actor` passes `agent_store=env["agent_store"]`. Remove that parameter:

```python
# BEFORE:
Actor(
    node_id=...,
    event_store=...,
    node_store=...,
    agent_store=env["agent_store"],
    workspace_service=...,
    config=...,
    semaphore=...,
)

# AFTER:
Actor(
    node_id=...,
    event_store=...,
    node_store=...,
    workspace_service=...,
    config=...,
    semaphore=...,
)
```

### 12d. Remove agent_store assertions

Find any test that asserts against `agent_store.get_agent(...)` (e.g., line ~500):

```python
# BEFORE:
updated_agent = await env["agent_store"].get_agent(node.node_id)

# AFTER:
# Delete this line and the assertion below it, OR replace with node_store check:
updated_node = await env["node_store"].get_node(node.node_id)
```

### 12e. Update ActorPool construction in tests

Any test that creates an `ActorPool` directly (if any in this file) — remove `agent_store` param.

---

## Step 13: Update test_externals.py

**File**: `tests/unit/test_externals.py`

### 13a. Remove imports

```python
# BEFORE:
from remora.core.graph import AgentStore, NodeStore

# AFTER:
from remora.core.graph import NodeStore
```

### 13b. Update the `context_env` fixture

```python
# BEFORE:
agent_store = AgentStore(db)
...
await agent_store.create_tables()
...
yield node_store, agent_store, event_store, workspace_service

# AFTER:
# (remove agent_store lines)
yield node_store, event_store, workspace_service
```

### 13c. Update the `_context` helper function

```python
# BEFORE:
async def _context(
    node_id: str,
    workspace: AgentWorkspace,
    node_store: NodeStore,
    agent_store: AgentStore,
    event_store: EventStore,
    ...
) -> TurnContext:
    return TurnContext(
        node_id=node_id,
        workspace=workspace,
        ...
        node_store=node_store,
        agent_store=agent_store,
        event_store=event_store,
        ...
    )

# AFTER:
async def _context(
    node_id: str,
    workspace: AgentWorkspace,
    node_store: NodeStore,
    event_store: EventStore,
    ...
) -> TurnContext:
    return TurnContext(
        node_id=node_id,
        workspace=workspace,
        ...
        node_store=node_store,
        event_store=event_store,
        ...
    )
```

### 13d. Update every test function

Every test unpacks the fixture and calls `_context`. Update the unpacking:

```python
# BEFORE:
node_store, agent_store, event_store, workspace_service = context_env
...
await agent_store.upsert_agent(node.to_agent())
...
context = await _context(node.node_id, ws, node_store, agent_store, event_store)

# AFTER:
node_store, event_store, workspace_service = context_env
...
# (delete the agent_store.upsert_agent line entirely)
...
context = await _context(node.node_id, ws, node_store, event_store)
```

**This pattern repeats in every test function in the file (~15+ tests).** Go through each one mechanically:

1. Change the fixture unpacking from 4-tuple to 3-tuple
2. Delete any `agent_store.upsert_agent(...)` lines
3. Remove `agent_store` from `_context(...)` calls

---

## Step 14: Update test_runner.py

**File**: `tests/unit/test_runner.py`

### 14a. Remove imports

```python
# BEFORE:
from remora.core.graph import AgentStore, NodeStore

# AFTER:
from remora.core.graph import NodeStore
```

### 14b. Update the runner fixture

```python
# BEFORE:
agent_store = AgentStore(db)
...
await agent_store.create_tables()
...
runner = ActorPool(event_store, node_store, agent_store, workspace_service, config)
...
yield runner, node_store, agent_store, event_store, workspace_service

# AFTER:
# (remove agent_store lines)
runner = ActorPool(event_store, node_store, workspace_service, config)
...
yield runner, node_store, event_store, workspace_service
```

### 14c. Update test functions

Update fixture unpacking in each test to remove `agent_store`.

---

## Step 15: Update test_reconciler.py

**File**: `tests/unit/test_reconciler.py`

### 15a. Remove imports

```python
# BEFORE:
from remora.core.graph import AgentStore, NodeStore

# AFTER:
from remora.core.graph import NodeStore
```

### 15b. Update the reconcile fixture

```python
# BEFORE:
agent_store = AgentStore(db)
...
await agent_store.create_tables()
...
reconciler = FileReconciler(
    config,
    node_store,
    agent_store,
    event_store,
    workspace_service,
    project_root,
)
...
yield node_store, agent_store, event_store, workspace_service, config, reconciler

# AFTER:
# (remove agent_store lines)
reconciler = FileReconciler(
    config,
    node_store,
    event_store,
    workspace_service,
    project_root,
)
...
yield node_store, event_store, workspace_service, config, reconciler
```

### 15c. Update all test function unpacking

Change every tuple unpacking. Most tests use:

```python
# BEFORE:
node_store, _agent_store, event_store, _workspace_service, _config, reconciler = reconcile_env

# AFTER:
node_store, event_store, _workspace_service, _config, reconciler = reconcile_env
```

And for tests that use more fields:

```python
# BEFORE:
node_store, agent_store, event_store, workspace_service, config, reconciler = reconcile_env

# AFTER:
node_store, event_store, workspace_service, config, reconciler = reconcile_env
```

Update the `FileReconciler` construction in any tests that create a second reconciler:

```python
# BEFORE:
FileReconciler(config, node_store, agent_store, event_store, workspace_service, ...)

# AFTER:
FileReconciler(config, node_store, event_store, workspace_service, ...)
```

---

## Step 16: Update Integration Tests

### 16a. `tests/integration/test_e2e.py`

Remove `AgentStore` import, creation, `create_tables()` call, and all references:

```python
# Remove:
from remora.core.graph import AgentStore, NodeStore
# Replace with:
from remora.core.graph import NodeStore

# Delete:
agent_store = AgentStore(db)
await agent_store.create_tables()

# Update FileReconciler construction - remove agent_store param
# Update ActorPool construction - remove agent_store param
# Remove "agent_store" from any env dicts
```

### 16b. `tests/integration/test_llm_turn.py`

Same pattern as test_e2e.py:

```python
# Remove AgentStore import
# Delete agent_store creation and create_tables
# Remove agent_store from FileReconciler construction
# Remove agent_store from Actor construction
```

### 16c. `tests/integration/test_performance.py`

Check if it references `AgentStore`. Based on the grep, it only references `to_agent` in event field names (like `to_agent="agent-42"`), which are **event fields, not the AgentStore**. No changes needed unless it creates an `AgentStore` directly.

---

## Step 17: Update Remaining Test Files

### 17a. `tests/unit/test_refactor_naming.py`

Line 30 has: `assert node.to_agent().role == "code-agent"`

Replace with a direct assertion on the node:

```python
# BEFORE:
assert node.to_agent().role == "code-agent"

# AFTER:
assert node.role == "code-agent"
```

### 17b. Files that only reference `to_agent` as event fields

These files reference `to_agent` as a field on `AgentMessageEvent`, NOT as `Node.to_agent()`. **No changes needed** for:

- `test_event_bus.py` — uses `AgentMessageEvent(to_agent=...)`
- `test_event_store.py` — same
- `test_events.py` — same
- `test_subscription_registry.py` — same
- `test_web_server.py` — same
- `test_performance.py` — same

The `to_agent` field on `AgentMessageEvent` is an event routing field, completely unrelated to `Node.to_agent()`.

---

## Step 18: Clean Up Imports and __all__

Run a final grep to catch any remaining references:

```bash
# From the project root:
devenv shell -- ruff check src/ tests/ --select F401,F811
```

This catches unused imports. Fix any that appear.

Also grep for stale references:

```bash
grep -rn "AgentStore\|from_row.*Agent\|to_agent()\|_ensure_agent\|agent_store\|DiscoveredElement" src/ tests/ --include='*.py'
```

**Important**: `to_agent` as a string (event field name) will still appear in many places. That's correct — it's the `AgentMessageEvent.to_agent` field. Only `to_agent()` (with parentheses, as a method call) and `AgentStore` should be gone.

Filter accordingly:

```bash
grep -rn "AgentStore\|\.to_agent()\|_ensure_agent\|DiscoveredElement" src/ tests/ --include='*.py'
```

This should return zero results.

---

## Step 19: Run Full Test Suite and Fix

```bash
devenv shell -- python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q
```

Expected: All tests pass (count will be slightly lower due to deleted `test_agent_store.py` — roughly 205 passed).

If tests fail, the errors will be one of:

1. **`TypeError: __init__() got an unexpected keyword argument 'agent_store'`** — You missed removing `agent_store` from a constructor call somewhere. Grep for `agent_store` in the traceback file and remove it.

2. **`ImportError: cannot import name 'AgentStore'`** — A file still imports `AgentStore`. Remove the import.

3. **`ImportError: cannot import name 'Agent'`** — A file still imports `Agent`. Remove the import.

4. **`AttributeError: 'Node' object has no attribute 'to_agent'`** — A call to `node.to_agent()` still exists. Delete it.

5. **`ValueError: not enough values to unpack`** — A test fixture yields a different number of values than the test expects. Align the unpacking.

Fix each error, re-run, repeat until green.

---

## Step 20: Final Audit

### 20a. Verify no `agents` table is created

```bash
grep -rn "CREATE TABLE.*agents" src/ --include='*.py'
```

Should return zero results.

### 20b. Verify no AgentStore references in source

```bash
grep -rn "AgentStore\|agent_store" src/ --include='*.py'
```

Should return zero results.

### 20c. Verify no Agent model references

```bash
grep -rn "from remora.core.node import.*Agent\|class Agent" src/ --include='*.py'
```

Should return zero results.

### 20d. Verify no DiscoveredElement references

```bash
grep -rn "DiscoveredElement\|to_element" src/ --include='*.py'
```

Should return zero results.

### 20e. Verify no dual-status patterns in Actor

Read `src/remora/core/actor.py` and confirm that every status transition only calls `self._node_store.transition_status()` or `self._node_store.set_status()` — never two stores.

### 20f. Run ruff

```bash
devenv shell -- ruff check src/ tests/
```

Fix any lint issues (likely just unused imports).

### 20g. Commit

```bash
git add -A
git commit -m "refactor: consolidate Node/Agent into single source of truth

Delete AgentStore, Agent model, and DiscoveredElement. All status
tracking now goes through NodeStore exclusively, eliminating 6+
dual-status coordination points.

Removed:
- Agent class and agents table
- DiscoveredElement class (unused)
- Node.to_agent() and Node.to_element() methods
- All _ensure_agent calls in reconciler
- All dual agent_store/node_store status updates in actor
- test_agent_store.py (entire file)"
```

---

## Summary of Net Changes

| Metric | Before | After |
|--------|--------|-------|
| Source files | 31 | 31 (no new files) |
| `core/node.py` lines | ~112 | ~50 |
| `core/graph.py` lines | ~305 | ~220 |
| `core/actor.py` lines | ~510 | ~480 |
| `core/externals.py` lines | ~303 | ~295 |
| `core/runner.py` lines | ~115 | ~110 |
| `core/services.py` lines | ~87 | ~80 |
| `code/reconciler.py` lines | ~494 | ~470 |
| Test files | 35 | 34 (deleted test_agent_store.py) |
| Status coordination points | 6+ | 1 (NodeStore only) |
| Tables | nodes, agents, edges, events, subscriptions | nodes, edges, events, subscriptions |

**Net deletion**: ~150-180 lines of source code, ~50 lines of test code, one entire test file, one entire class, one entire table.
