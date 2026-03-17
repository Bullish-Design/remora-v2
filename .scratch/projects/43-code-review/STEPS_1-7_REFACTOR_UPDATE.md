# Steps 1-7 Refactor — Fix-Up Guide

**Date:** 2026-03-17
**Companion to:** `REVIEW_REFACTORING_GUIDE.md`, `refactor_review_steps_1-7.md`

This guide addresses issues found during review of the Steps 1-7 implementation. Each fix-up is self-contained. Complete them in order — some later fixes reference earlier ones.

---

## Table of Contents

1. [Fix-Up A: Status Leak on Timeout in `request_human_input` (Step 2 Bug)](#fix-up-a-status-leak-on-timeout-in-request_human_input-step-2-bug)
2. [Fix-Up B: Export Sub-Models from `config.py __all__` (Step 5 Omission)](#fix-up-b-export-sub-models-from-configpy-__all__-step-5-omission)
3. [Fix-Up C: Guard Against `_nest_flat_config` Key Drift (Step 5 Fragility)](#fix-up-c-guard-against-_nest_flat_config-key-drift-step-5-fragility)
4. [Fix-Up D: `BundleConfig.max_turns` Validator Breaks Inherit Semantic (Step 5 Latent Bug)](#fix-up-d-bundleconfigmax_turns-validator-breaks-inherit-semantic-step-5-latent-bug)
5. [Fix-Up E: Remove Legacy Batch Logic from EventStore and NodeStore (Step 6 Incomplete)](#fix-up-e-remove-legacy-batch-logic-from-eventstore-and-nodestore-step-6-incomplete)
6. [Fix-Up F: Wire `tx` into SubscriptionRegistry (Step 6 Gap)](#fix-up-f-wire-tx-into-subscriptionregistry-step-6-gap)
7. [Fix-Up G: Move Externals Version Check to Turn Executor (Step 8 Not Implemented)](#fix-up-g-move-externals-version-check-to-turn-executor-step-8-not-implemented)
8. [Fix-Up H: Redundant Double-Clear in TransactionContext (Step 6 Minor)](#fix-up-h-redundant-double-clear-in-transactioncontext-step-6-minor)

---

## Fix-Up A: Status Leak on Timeout in `request_human_input` (Step 2 Bug)

### Problem

Step 2 removed the `finally` block and moved the `RUNNING` transition to the success path only — that part is correct. However, the timeout path at `externals.py:325-327` discards the future and re-raises `TimeoutError`, but **never transitions the node out of `AWAITING_INPUT`**.

The turn executor's error boundary (`turn_executor.py:164-175`) catches the exception and transitions the node to `ERROR`. But `STATUS_TRANSITIONS` must allow `AWAITING_INPUT -> ERROR` for that to work. If it doesn't, the node is stuck in `AWAITING_INPUT` permanently — a silent state leak.

### What to Verify

**File:** `src/remora/core/types.py`

Check that `STATUS_TRANSITIONS` includes a path from `AWAITING_INPUT` to `ERROR`:

```python
STATUS_TRANSITIONS = {
    NodeStatus.IDLE: {NodeStatus.RUNNING},
    NodeStatus.RUNNING: {NodeStatus.IDLE, NodeStatus.ERROR, NodeStatus.AWAITING_INPUT, NodeStatus.AWAITING_REVIEW},
    NodeStatus.AWAITING_INPUT: {NodeStatus.RUNNING, NodeStatus.ERROR},  # <-- ERROR must be here
    NodeStatus.AWAITING_REVIEW: {NodeStatus.RUNNING, NodeStatus.ERROR},
    NodeStatus.ERROR: {NodeStatus.IDLE},
}
```

If `NodeStatus.ERROR` is **not** in `STATUS_TRANSITIONS[NodeStatus.AWAITING_INPUT]`, add it.

### What to Change

**File:** `src/remora/core/types.py`

If the transition is missing, add `NodeStatus.ERROR` to the set of valid targets from `AWAITING_INPUT`:

```python
# Ensure this line includes ERROR:
NodeStatus.AWAITING_INPUT: {NodeStatus.RUNNING, NodeStatus.ERROR},
```

### Testing & Validation

Write a focused test that confirms the full timeout → error flow:

```python
# tests/unit/test_externals.py

@pytest.mark.asyncio
async def test_request_human_input_timeout_allows_error_transition(
    comms, node_store
):
    """After timeout, the turn executor should be able to transition to ERROR."""
    comms._human_input_timeout_s = 0.01
    with pytest.raises(TimeoutError):
        await comms.request_human_input("question?")

    # Node is in AWAITING_INPUT after timeout
    node = await node_store.get_node(comms._node_id)
    assert node.status == NodeStatus.AWAITING_INPUT

    # The turn executor's error handler does this transition — verify it's allowed
    success = await node_store.transition_status(
        comms._node_id, NodeStatus.ERROR
    )
    assert success, "AWAITING_INPUT -> ERROR transition must be allowed"
```

Run:
```bash
devenv shell -- pytest tests/unit/test_externals.py -v
```

---

## Fix-Up B: Export Sub-Models from `config.py __all__` (Step 5 Omission)

### Problem

The four new sub-models (`ProjectConfig`, `RuntimeConfig`, `InfraConfig`, `BehaviorConfig`) are public API — tests and other modules need to import them to construct `Config` objects. But they are missing from `__all__` at `config.py:441-456`.

### What to Change

**File:** `src/remora/core/config.py`

Add the four sub-models to `__all__`:

```python
__all__ = [
    "BundleConfig",
    "BundleOverlayRule",
    "ProjectConfig",
    "RuntimeConfig",
    "InfraConfig",
    "BehaviorConfig",
    "SearchConfig",
    "SearchMode",
    "SelfReflectConfig",
    "VirtualSubscriptionConfig",
    "VirtualAgentConfig",
    "Config",
    "expand_env_vars",
    "expand_string",
    "load_config",
    "resolve_bundle_search_paths",
    "resolve_bundle_dirs",
    "resolve_query_search_paths",
]
```

### Testing & Validation

```bash
devenv shell -- python -c "
from remora.core.config import ProjectConfig, RuntimeConfig, InfraConfig, BehaviorConfig
print('All sub-models importable from __all__: OK')
"
```

Then run:
```bash
devenv shell -- pytest tests/unit/test_config.py -v
```

---

## Fix-Up C: Guard Against `_nest_flat_config` Key Drift (Step 5 Fragility)

### Problem

`_nest_flat_config()` at `config.py:305-370` contains four hardcoded key sets (`project_keys`, `runtime_keys`, `infra_keys`, `behavior_keys`) that must stay manually in sync with the sub-model field names. If someone adds a field to `RuntimeConfig` but forgets to add it to `runtime_keys`, flat YAML configs silently break for that field.

### What to Change

**File:** `src/remora/core/config.py`

Replace the hardcoded key sets with sets derived from the model fields:

```python
def _nest_flat_config(flat: dict[str, Any]) -> dict[str, Any]:
    """Map flat config keys into nested sub-model structure."""
    project_keys = set(ProjectConfig.model_fields)
    runtime_keys = set(RuntimeConfig.model_fields)
    infra_keys = set(InfraConfig.model_fields)
    behavior_keys = set(BehaviorConfig.model_fields)

    nested: dict[str, Any] = {}
    project: dict[str, Any] = {}
    runtime: dict[str, Any] = {}
    infra: dict[str, Any] = {}
    behavior: dict[str, Any] = {}

    for key, value in flat.items():
        if key in project_keys:
            project[key] = value
        elif key in runtime_keys:
            runtime[key] = value
        elif key in infra_keys:
            infra[key] = value
        elif key in behavior_keys:
            behavior[key] = value
        elif key in ("search", "virtual_agents", "project", "runtime", "infra", "behavior"):
            nested[key] = value
        else:
            nested[key] = value

    if project:
        nested.setdefault("project", {}).update(project)
    if runtime:
        nested.setdefault("runtime", {}).update(runtime)
    if infra:
        nested.setdefault("infra", {}).update(infra)
    if behavior:
        nested.setdefault("behavior", {}).update(behavior)

    return nested
```

Using `model_fields` means adding a field to any sub-model automatically updates the routing — no manual sync required.

### Testing & Validation

Write a test that proves the key sets stay in sync:

```python
# tests/unit/test_config.py

def test_nest_flat_config_covers_all_submodel_fields():
    """Every sub-model field must be routed by _nest_flat_config."""
    from remora.core.config import (
        ProjectConfig, RuntimeConfig, InfraConfig, BehaviorConfig,
        _nest_flat_config,
    )
    # Build a flat dict with every sub-model field set to a sentinel
    flat = {}
    for model_cls, prefix in [
        (ProjectConfig, "project"),
        (RuntimeConfig, "runtime"),
        (InfraConfig, "infra"),
        (BehaviorConfig, "behavior"),
    ]:
        for field_name in model_cls.model_fields:
            flat[field_name] = f"sentinel_{prefix}_{field_name}"

    nested = _nest_flat_config(flat)

    # Every field should be routed to its sub-model, not left at top level
    for field_name in ProjectConfig.model_fields:
        assert field_name in nested.get("project", {}), f"{field_name} not routed to project"
    for field_name in RuntimeConfig.model_fields:
        assert field_name in nested.get("runtime", {}), f"{field_name} not routed to runtime"
    for field_name in InfraConfig.model_fields:
        assert field_name in nested.get("infra", {}), f"{field_name} not routed to infra"
    for field_name in BehaviorConfig.model_fields:
        assert field_name in nested.get("behavior", {}), f"{field_name} not routed to behavior"
```

Run:
```bash
devenv shell -- pytest tests/unit/test_config.py -v -k nest
```

---

## Fix-Up D: `BundleConfig.max_turns` Validator Breaks Inherit Semantic (Step 5 Latent Bug)

### Problem

`BundleConfig.max_turns` defaults to `0` (meaning "inherit from global config"), but the validator at `config.py:213-216` does `return max(1, value)` — which silently converts `0` to `1`. This means a bundle that omits `max_turns` (or explicitly sets it to `0` to inherit) gets `max_turns=1` instead of inheriting the global value.

### What to Change

**File:** `src/remora/core/config.py`

The validator should allow `0` as a sentinel for "inherit" and only clamp positive values:

```python
class BundleConfig(BaseModel):
    """Agent bundle configuration loaded from bundle.yaml."""

    system_prompt: str = ""
    system_prompt_extension: str = ""
    model: str | None = None
    max_turns: int = 0  # 0 = inherit from global config
    # ...

    @field_validator("max_turns")
    @classmethod
    def _validate_max_turns(cls, value: int) -> int:
        if value == 0:
            return 0  # sentinel: inherit from global
        return max(1, value)  # explicit values must be >= 1
```

Then verify the caller that resolves the inheritance honors this. In `prompt.py`, the `build_system_prompt` method (or wherever `max_turns` is consumed from `BundleConfig`) should fall back to the global default when `bundle_config.max_turns == 0`:

```python
max_turns = bundle_config.max_turns or self._config.behavior.max_turns
```

Verify this is already the case. If `prompt.py` already does this fallback, only the validator fix is needed. If not, add the fallback.

### Testing & Validation

```python
# tests/unit/test_config.py

def test_bundle_config_max_turns_zero_means_inherit():
    """max_turns=0 should be preserved as the 'inherit' sentinel."""
    config = BundleConfig()
    assert config.max_turns == 0

def test_bundle_config_max_turns_explicit_clamped():
    """Explicit max_turns values below 1 (but not 0) are clamped to 1."""
    config = BundleConfig(max_turns=-5)
    assert config.max_turns == 1

def test_bundle_config_max_turns_positive_preserved():
    """Positive max_turns values pass through unchanged."""
    config = BundleConfig(max_turns=12)
    assert config.max_turns == 12
```

Run:
```bash
devenv shell -- pytest tests/unit/test_config.py -v -k max_turns
```

---

## Fix-Up E: Remove Legacy Batch Logic from EventStore and NodeStore (Step 6 Incomplete)

### Problem

Step 6 introduced `TransactionContext` and wired it into both stores via the `tx` parameter. However, both stores **retain their old independent batch logic** as a fallback:

- `EventStore` (`events/store.py:36-37`): still has `_batch_depth` and `_batch_buffer`
- `EventStore.batch()` (`events/store.py:117-138`): still has the full independent batch implementation
- `NodeStore` (`graph.py:38`): still has `_batch_depth`
- `NodeStore.batch()` (`graph.py:41-60`): still has the full independent batch implementation

The guide specified removing the old batch logic when `tx` is present. The current hybrid approach means there are **two independent transaction-tracking mechanisms** that can get out of sync. Any caller using `store.batch()` directly (instead of `tx.batch()`) bypasses the unified transaction.

### What to Change

#### E1. Simplify `EventStore`

**File:** `src/remora/core/events/store.py`

Remove `_batch_depth` and `_batch_buffer`. The `batch()` method should delegate to `tx` when available, or provide a minimal standalone fallback for tests:

```python
class EventStore:
    def __init__(
        self,
        db: aiosqlite.Connection,
        event_bus: EventBus | None = None,
        dispatcher: TriggerDispatcher | None = None,
        metrics: Metrics | None = None,
        tx: Any | None = None,
    ) -> None:
        self._db = db
        self._event_bus = event_bus or EventBus()
        self._dispatcher = dispatcher or TriggerDispatcher(SubscriptionRegistry(db))
        self._metrics = metrics
        self._tx = tx
        self._pending_responses: dict[str, asyncio.Future[str]] = {}

    async def append(self, event: Event) -> int:
        """Append an event and fan-out to bus and matching subscription triggers."""
        envelope = event.to_envelope()
        payload = envelope["payload"]
        summary = event.summary()
        agent_id = payload.get("agent_id")
        from_agent = payload.get("from_agent")
        to_agent = payload.get("to_agent")

        cursor = await self._db.execute(
            """
            INSERT INTO events (
                event_type, agent_id, from_agent, to_agent,
                correlation_id, timestamp, tags, payload, summary
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                envelope["event_type"],
                agent_id,
                from_agent,
                to_agent,
                envelope["correlation_id"],
                envelope["timestamp"],
                json.dumps(envelope.get("tags", [])),
                json.dumps(payload),
                summary,
            ),
        )
        event_id = int(cursor.lastrowid)
        if self._metrics is not None:
            self._metrics.events_emitted_total += 1

        if self._tx is not None and self._tx.in_batch:
            self._tx.defer_event(event)
            return event_id

        await self._db.commit()
        await self._event_bus.emit(event)
        await self._dispatcher.dispatch(event)
        return event_id

    @asynccontextmanager
    async def batch(self):
        """Batch context — delegates to TransactionContext when available."""
        if self._tx is not None:
            async with self._tx.batch():
                yield
        else:
            # Standalone fallback for tests without tx
            try:
                yield
            except BaseException:
                await self._db.rollback()
                raise
            else:
                await self._db.commit()
```

Key changes:
- Remove `self._batch_depth = 0` and `self._batch_buffer: list[Event] = []` from `__init__`
- Remove all `_batch_depth` / `_batch_buffer` logic from `append()` and `batch()`
- The standalone fallback in `batch()` is intentionally simple — it just does commit/rollback without event buffering, because without `tx` there's no deferred fan-out

#### E2. Simplify `NodeStore`

**File:** `src/remora/core/graph.py`

Same pattern — remove `_batch_depth`:

```python
class NodeStore:
    def __init__(self, db: aiosqlite.Connection, tx: Any | None = None):
        self._db = db
        self._tx = tx

    @asynccontextmanager
    async def batch(self):
        """Batch context — delegates to TransactionContext when available."""
        if self._tx is not None:
            async with self._tx.batch():
                yield
        else:
            # Standalone fallback for tests without tx
            try:
                yield
            except BaseException:
                await self._db.rollback()
                raise
            else:
                await self._db.commit()

    async def _maybe_commit(self) -> None:
        if self._tx is not None and self._tx.in_batch:
            return
        await self._db.commit()
```

Key changes:
- Remove `self._batch_depth = 0` from `__init__`
- Remove all `_batch_depth` tracking from `batch()` and replace with clean delegation

### Testing & Validation

1. Verify existing transaction tests still pass:
```bash
devenv shell -- pytest tests/unit/test_transaction.py -v
```

2. Verify store-level batch tests still pass:
```bash
devenv shell -- pytest tests/unit/ -k "batch" -v
```

3. Write a test proving the stores delegate to `tx`:
```python
@pytest.mark.asyncio
async def test_event_store_batch_delegates_to_tx(db, event_bus, dispatcher):
    """EventStore.batch() should use tx.batch() when tx is provided."""
    tx = TransactionContext(db, event_bus, dispatcher)
    store = EventStore(db=db, event_bus=event_bus, dispatcher=dispatcher, tx=tx)

    async with store.batch():
        assert tx.in_batch is True
    assert tx.in_batch is False

@pytest.mark.asyncio
async def test_node_store_batch_delegates_to_tx(db):
    """NodeStore.batch() should use tx.batch() when tx is provided."""
    tx = TransactionContext(db, EventBus(), TriggerDispatcher(SubscriptionRegistry(db)))
    store = NodeStore(db, tx=tx)

    async with store.batch():
        assert tx.in_batch is True
    assert tx.in_batch is False
```

4. Run the full suite:
```bash
devenv shell -- pytest -x
```

---

## Fix-Up F: Wire `tx` into SubscriptionRegistry (Step 6 Gap)

### Problem

In `services.py:32`, `SubscriptionRegistry` receives `db` directly without `tx`. If subscriptions are written inside a `tx.batch()` context (e.g., during reconciliation), the registry can call `db.commit()` independently, breaking the atomicity guarantee that `TransactionContext` is supposed to provide.

### What to Change

#### F1. Add `tx` support to `SubscriptionRegistry`

**File:** `src/remora/core/events/subscriptions.py`

Add the same `tx` / `_maybe_commit` pattern used by `NodeStore` and `EventStore`:

```python
class SubscriptionRegistry:
    def __init__(self, db: aiosqlite.Connection, tx: Any | None = None):
        self._db = db
        self._tx = tx

    async def _maybe_commit(self) -> None:
        if self._tx is not None and self._tx.in_batch:
            return
        await self._db.commit()
```

Then replace every `await self._db.commit()` call in the registry with `await self._maybe_commit()`.

#### F2. Wire it in `RuntimeServices`

**File:** `src/remora/core/services.py`

Pass `tx` when constructing the registry:

```python
# Old:
self.subscriptions = SubscriptionRegistry(db)

# New:
self.subscriptions = SubscriptionRegistry(db, tx=self.tx)
```

Note: `self.tx` must be constructed before `self.subscriptions`. Check the construction order in `RuntimeServices.__init__` — currently `SubscriptionRegistry` is constructed at line 32, before `TransactionContext` at line 34. You need to reorder:

```python
self.event_bus = EventBus()
self.tx = TransactionContext(db, self.event_bus, ...)  # move up
self.subscriptions = SubscriptionRegistry(db, tx=self.tx)
self.dispatcher = TriggerDispatcher(self.subscriptions)
```

Wait — `TransactionContext` takes `dispatcher` as a parameter, and `dispatcher` needs `subscriptions`. This is a circular dependency. There are two clean options:

**Option A (recommended):** Initialize `TransactionContext` without `dispatcher`, then set it after:

```python
self.event_bus = EventBus()
self.subscriptions = SubscriptionRegistry(db)  # no tx yet — set later
self.dispatcher = TriggerDispatcher(self.subscriptions)
self.tx = TransactionContext(db, self.event_bus, self.dispatcher)
self.subscriptions._tx = self.tx  # wire tx after construction
```

This works but requires `SubscriptionRegistry` to accept late-binding of `_tx`. Just set it as a mutable attribute.

**Option B:** Pass `tx` to `SubscriptionRegistry` as a property that reads from a shared holder, or accept that subscriptions don't need transactional semantics if they're always idempotent (INSERT OR IGNORE / DELETE + re-INSERT). In that case, document the decision and skip this fix-up.

Pick one approach and apply it consistently.

### Testing & Validation

```bash
devenv shell -- pytest tests/unit/ -k "subscription" -v
devenv shell -- pytest -x
```

---

## Fix-Up G: Move Externals Version Check to Turn Executor (Step 8 Not Implemented)

### Problem

Step 8 in the refactoring guide was **not implemented at all**. The current state:

- `workspace.py:19` still imports `EXTERNALS_VERSION` from `externals.py` (boundary violation)
- `workspace.py:184-190` still only logs a warning on version mismatch
- No `IncompatibleBundleError` was created
- The version check was not moved to `turn_executor.py`

### What to Change

#### G1. Define the exception

**File:** `src/remora/core/workspace.py` (or create `src/remora/core/errors.py` if you prefer a shared exceptions module)

```python
class IncompatibleBundleError(Exception):
    """Raised when a bundle requires a newer externals version than core provides."""
```

#### G2. Remove the version check from `read_bundle_config`

**File:** `src/remora/core/workspace.py`

Remove lines 184-190 (the `if config.externals_version ...` warning block) and the `EXTERNALS_VERSION` import from line 19:

```python
# Delete this import:
from remora.core.externals import EXTERNALS_VERSION

# In read_bundle_config(), delete these lines:
if config.externals_version is not None and config.externals_version > EXTERNALS_VERSION:
    logger.warning(
        "Bundle for %s requires externals v%d but core provides v%d",
        node_id,
        config.externals_version,
        EXTERNALS_VERSION,
    )
```

The method should simply return the parsed `BundleConfig` without version validation.

#### G3. Add the version check to `_start_agent_turn`

**File:** `src/remora/core/turn_executor.py`

Add the import and check:

```python
from remora.core.externals import EXTERNALS_VERSION
from remora.core.workspace import IncompatibleBundleError  # or from errors module

# In _start_agent_turn(), after reading bundle config:
async def _start_agent_turn(self, node_id, trigger, outbox, turn_log):
    node = await self._node_store.get_node(node_id)
    if node is None:
        turn_log.warning("Trigger for unknown node")
        return None

    if not await self._node_store.transition_status(node_id, NodeStatus.RUNNING):
        turn_log.warning("Failed to transition node into running state")
        return None

    await outbox.emit(
        AgentStartEvent(
            agent_id=node_id,
            node_name=node.name,
            correlation_id=trigger.correlation_id,
        )
    )

    workspace = await self._workspace_service.get_agent_workspace(node_id)
    bundle_config = await self._workspace_service.read_bundle_config(node_id)

    # Version gate — fail fast if bundle requires capabilities we don't have
    if (
        bundle_config.externals_version is not None
        and bundle_config.externals_version > EXTERNALS_VERSION
    ):
        raise IncompatibleBundleError(
            f"Bundle for {node_id} requires externals v{bundle_config.externals_version} "
            f"but core provides v{EXTERNALS_VERSION}"
        )

    return node, workspace, bundle_config
```

The existing error boundary in `execute_turn()` at lines 164-175 will catch `IncompatibleBundleError` (since it catches `Exception`), transition the node to `ERROR`, and emit an `AgentErrorEvent` with the clear version mismatch message. No additional handling is needed.

### Testing & Validation

```python
# tests/unit/test_turn_executor.py (or test_workspace.py)

@pytest.mark.asyncio
async def test_incompatible_bundle_raises_in_turn(workspace_service):
    """Bundles requiring a newer externals version should fail at turn start."""
    ws = await workspace_service.get_agent_workspace("test::node")
    await ws.write("_bundle/bundle.yaml", "externals_version: 999\n")

    # read_bundle_config should return the config without raising
    config = await workspace_service.read_bundle_config("test::node")
    assert config.externals_version == 999

    # The check is now in turn_executor, not workspace
    from remora.core.externals import EXTERNALS_VERSION
    assert config.externals_version > EXTERNALS_VERSION

def test_workspace_does_not_import_externals_version():
    """workspace.py should not import EXTERNALS_VERSION (boundary fix)."""
    import ast
    from pathlib import Path
    source = Path("src/remora/core/workspace.py").read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "remora.core.externals":
            imported_names = [alias.name for alias in node.names]
            assert "EXTERNALS_VERSION" not in imported_names, (
                "workspace.py should not import EXTERNALS_VERSION"
            )
```

Run:
```bash
devenv shell -- pytest tests/unit/test_workspace.py tests/unit/test_turn_executor.py -v
devenv shell -- pytest -x
```

---

## Fix-Up H: Redundant Double-Clear in TransactionContext (Step 6 Minor)

### Problem

In `transaction.py:30-51`, when an exception occurs at `_depth == 1`, the `except` block clears `_deferred_events` (line 41), and then the `finally` block clears it again (line 51). This is harmless but redundant.

### What to Change

**File:** `src/remora/core/transaction.py`

Remove the `clear()` from the `except` block — the `finally` block handles it:

```python
@asynccontextmanager
async def batch(self):
    """Nest-safe batch context. Only the outermost batch commits and fans out."""
    self._depth += 1
    failed = False
    try:
        yield
    except BaseException:
        failed = True
        if self._depth == 1:
            await self._db.rollback()
        raise
    finally:
        self._depth -= 1
        if self._depth == 0:
            if not failed:
                await self._db.commit()
                for event in self._deferred_events:
                    await self._event_bus.emit(event)
                    await self._dispatcher.dispatch(event)
            self._deferred_events.clear()
```

### Testing & Validation

```bash
devenv shell -- pytest tests/unit/test_transaction.py -v
devenv shell -- pytest -x
```

---

## Summary

| Fix-Up | Severity | Step | Issue |
|--------|----------|------|-------|
| A | **High** | 2 | Timeout leaves node stuck in AWAITING_INPUT if status transition not allowed |
| B | Medium | 5 | Sub-models not exported from `__all__` |
| C | Medium | 5 | `_nest_flat_config` key sets drift risk — use `model_fields` instead |
| D | Medium | 5 | `BundleConfig.max_turns` validator destroys the `0 = inherit` sentinel |
| E | **High** | 6 | Legacy batch logic retained alongside `TransactionContext` — two competing mechanisms |
| F | Low | 6 | `SubscriptionRegistry` bypasses `TransactionContext` |
| G | **High** | 8 | Entire step not implemented — version mismatch still warn-only, boundary violation remains |
| H | Low | 6 | Redundant double-clear in `TransactionContext` |

Apply fixes A, E, and G first — they are the highest severity. The rest can follow in any order.
