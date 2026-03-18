# Remora v2 — Refactor Fixes Guide

**Date:** 2026-03-17
**Starting point:** commit `a95f0f5` (step 15 complete)
**Target:** 0 test failures, full alignment with refactored architecture
**Principle:** No backwards compatibility. Tests must wire services the same way production does.

---

## Table of Contents

1. [Step 1: Make TransactionContext Required](#step-1-make-transactioncontext-required)
2. [Step 2: Remove Dead Fallback Code from NodeStore and EventStore](#step-2-remove-dead-fallback-code-from-nodestore-and-eventstore)
3. [Step 3: Update test_graph to Wire TransactionContext](#step-3-update-test_graph-to-wire-transactioncontext)
4. [Step 4: Update test_event_store to Wire TransactionContext](#step-4-update-test_event_store-to-wire-transactioncontext)
5. [Step 5: Replace Externals Version Warning Test with Error Test](#step-5-replace-externals-version-warning-test-with-error-test)
6. [Step 6: Update test_services Dummy to Match FileReconciler Signature](#step-6-update-test_services-dummy-to-match-filereconciler-signature)
7. [Step 7: Update All Remaining Flat Config Construction](#step-7-update-all-remaining-flat-config-construction)
8. [Step 8: Update All Remaining FileReconciler Construction](#step-8-update-all-remaining-filereconciler-construction)

---

## Step 1: Make TransactionContext Required

### Problem

`NodeStore`, `EventStore`, and `SubscriptionRegistry` all accept `tx: Any | None = None`. In production, `RuntimeServices` always provides a `TransactionContext`. The optional `None` path is dead code in production but silently breaks batch semantics — `_maybe_commit()` always calls `db.commit()` when `_tx is None`, so `batch()` has no effect.

Making `tx` required eliminates the hidden failure mode and ensures tests wire services the same way production does.

### What to Change

#### 1a. `src/remora/core/graph.py` — `NodeStore`

Change the constructor signature. `tx` becomes a required positional parameter:

```python
from remora.core.transaction import TransactionContext

class NodeStore:
    """SQLite-backed storage for the Node graph."""

    def __init__(self, db: aiosqlite.Connection, tx: TransactionContext):
        self._db = db
        self._tx = tx
```

Remove the `batch()` method entirely — callers should use `tx.batch()` directly. The `batch()` on `NodeStore` was always just a delegation wrapper and its else-branch was dead code in production. If you prefer to keep `batch()` as a convenience alias, it simplifies to:

```python
    @asynccontextmanager
    async def batch(self):  # noqa: ANN201
        """Convenience alias for self._tx.batch()."""
        async with self._tx.batch():
            yield
```

Simplify `_maybe_commit`:

```python
    async def _maybe_commit(self) -> None:
        if self._tx.in_batch:
            return
        await self._db.commit()
```

#### 1b. `src/remora/core/events/store.py` — `EventStore`

Same treatment. Make `tx`, `event_bus`, and `dispatcher` required — they're always provided in production via `RuntimeServices`. Remove the fallback defaults that silently construct new instances:

```python
from remora.core.transaction import TransactionContext

class EventStore:
    """Append-only SQLite event log with bus emission and trigger dispatch."""

    def __init__(
        self,
        db: aiosqlite.Connection,
        event_bus: EventBus,
        dispatcher: TriggerDispatcher,
        tx: TransactionContext,
        metrics: Metrics | None = None,
    ) -> None:
        self._db = db
        self._event_bus = event_bus
        self._dispatcher = dispatcher
        self._tx = tx
        self._metrics = metrics
        self._pending_responses: dict[str, asyncio.Future[str]] = {}
```

Simplify `append()` — remove the `if self._tx is not None` guard:

```python
    async def append(self, event: Event) -> int:
        # ... insert into DB (unchanged) ...
        event_id = int(cursor.lastrowid)
        if self._metrics is not None:
            self._metrics.events_emitted_total += 1

        if self._tx.in_batch:
            self._tx.defer_event(event)
            return event_id

        await self._db.commit()
        await self._event_bus.emit(event)
        await self._dispatcher.dispatch(event)
        return event_id
```

Simplify `batch()`:

```python
    @asynccontextmanager
    async def batch(self):  # noqa: ANN201
        """Convenience alias for self._tx.batch()."""
        async with self._tx.batch():
            yield
```

#### 1c. `src/remora/core/events/subscriptions.py` — `SubscriptionRegistry`

Same. Make `tx` required:

```python
class SubscriptionRegistry:
    def __init__(self, db: aiosqlite.Connection, tx: TransactionContext):
        self._db = db
        self._tx = tx
        self._cache: dict[str, list[tuple[int, str, SubscriptionPattern]]] | None = None

    async def _maybe_commit(self) -> None:
        if self._tx.in_batch:
            return
        await self._db.commit()
```

#### 1d. `src/remora/core/services.py` — Update wiring order

`SubscriptionRegistry` now requires `tx`, so create `TransactionContext` before `SubscriptionRegistry`:

```python
    self.metrics = Metrics()
    self.event_bus = EventBus()
    self.dispatcher_subscriptions = SubscriptionRegistry(db, tx=self.tx)  # need tx first

    # But tx needs dispatcher... which needs subscriptions. Circular.
```

There's a dependency cycle: `TransactionContext` needs `EventBus` and `TriggerDispatcher`. `TriggerDispatcher` needs `SubscriptionRegistry`. `SubscriptionRegistry` now needs `TransactionContext`.

**Resolution:** Pass `tx` to `SubscriptionRegistry` after construction, or break the cycle by having `TransactionContext` not depend on `TriggerDispatcher` at construction time. The simplest approach: keep `SubscriptionRegistry.__init__` accepting `tx` as a settable attribute (set it after `TransactionContext` is created), just like the current `self.subscriptions._tx = self.tx` line in `services.py`.

Revised approach for `SubscriptionRegistry`:

```python
class SubscriptionRegistry:
    def __init__(self, db: aiosqlite.Connection):
        self._db = db
        self._tx: TransactionContext | None = None
        self._cache: ...

    def set_tx(self, tx: TransactionContext) -> None:
        """Wire the TransactionContext after construction (breaks init cycle)."""
        self._tx = tx

    async def _maybe_commit(self) -> None:
        if self._tx is not None and self._tx.in_batch:
            return
        await self._db.commit()
```

And in `services.py`:

```python
    self.subscriptions = SubscriptionRegistry(db)
    self.dispatcher = TriggerDispatcher(self.subscriptions)
    self.tx = TransactionContext(db, self.event_bus, self.dispatcher)
    self.subscriptions.set_tx(self.tx)
    self.node_store = NodeStore(db, tx=self.tx)
    self.event_store = EventStore(
        db=db, event_bus=self.event_bus, dispatcher=self.dispatcher,
        tx=self.tx, metrics=self.metrics,
    )
```

This replaces the current `self.subscriptions._tx = self.tx` private attribute poke with a proper public method.

### Testing & Validation

This step will cause many test compilation failures. That's intentional — every test that constructs `NodeStore(db)` or `EventStore(db=db)` without a `TransactionContext` will fail loudly. Fix them in Steps 3-4 and 7-8.

```bash
devenv shell -- python -c "from remora.core.services import RuntimeServices; print('OK')"
```

---

## Step 2: Remove Dead Fallback Code from NodeStore and EventStore

### Problem

After Step 1 makes `tx` required, the `else` branches in `NodeStore.batch()` and `EventStore.batch()` are unreachable. Dead code should be deleted.

### What to Change

**File:** `src/remora/core/graph.py`

The `batch()` method's else-branch (lines 45-52) is dead:

```python
    # DELETE this entire else block:
        else:
            try:
                yield
            except BaseException:
                await self._db.rollback()
                raise
            else:
                await self._db.commit()
```

Either remove `batch()` entirely (callers use `tx.batch()`) or keep it as a one-line delegation:

```python
    @asynccontextmanager
    async def batch(self):  # noqa: ANN201
        async with self._tx.batch():
            yield
```

**File:** `src/remora/core/events/store.py`

Same — remove the else-branch from `batch()`.

### Testing & Validation

```bash
devenv shell -- ruff check src/remora/core/graph.py src/remora/core/events/store.py
```

---

## Step 3: Update test_graph to Wire TransactionContext

### Problem

Every test in `tests/unit/test_graph.py` constructs `NodeStore(db)` without a `TransactionContext`. After Step 1, this is a `TypeError`.

### What to Change

**File:** `tests/unit/test_graph.py`

Add a `tx` fixture and update `NodeStore` construction throughout. The simplest approach: add a shared fixture at the top of the file.

```python
from remora.core.events.bus import EventBus
from remora.core.events.dispatcher import TriggerDispatcher
from remora.core.events.subscriptions import SubscriptionRegistry
from remora.core.transaction import TransactionContext


@pytest_asyncio.fixture
async def tx(db):
    """Minimal TransactionContext for testing."""
    bus = EventBus()
    subs = SubscriptionRegistry(db)
    dispatcher = TriggerDispatcher(subs)
    context = TransactionContext(db, bus, dispatcher)
    subs.set_tx(context)
    return context
```

Then update every test. For example, `test_nodestore_upsert_and_get`:

```python
@pytest.mark.asyncio
async def test_nodestore_upsert_and_get(db, tx) -> None:
    store = NodeStore(db, tx=tx)
    await store.create_tables()
    node = make_node("src/app.py::a")
    await store.upsert_node(node)
    got = await store.get_node(node.node_id)
    assert got is not None
    assert got.model_dump() == node.model_dump()
```

Apply the same pattern to all ~20 tests in this file. Each `NodeStore(db)` becomes `NodeStore(db, tx=tx)`.

For `test_shared_db_coexistence`, both stores need the same `tx`:

```python
@pytest.mark.asyncio
async def test_shared_db_coexistence(db, tx) -> None:
    node_store = NodeStore(db, tx=tx)
    event_store = EventStore(db=db, event_bus=EventBus(), dispatcher=TriggerDispatcher(SubscriptionRegistry(db)), tx=tx)
    ...
```

That's verbose. Consider a helper or a second fixture for EventStore. But since this is the only test that needs both, inline is fine.

The three batch/commit tests now work correctly because `tx` provides real depth tracking:

- **`test_nodestore_batch_commits_once_for_grouped_writes`** — `store.batch()` delegates to `tx.batch()`, which increments depth. Inner `_maybe_commit()` sees `tx.in_batch == True` and skips. The outer `tx.batch()` commits once on exit.
- **`test_batch_rolls_back_on_exception`** — `tx.batch()` catches the exception at depth 1, calls `db.rollback()`. Inner upserts never committed. Node is gone.
- **`test_nodestore_transition_status_competing_updates_only_one_wins`** — This test doesn't use `batch()`. Each `transition_status` calls `_maybe_commit()` which calls `db.commit()` (since `tx.in_batch` is `False`). The commit serialization depends on aiosqlite's internal threading. If this test is still flaky, wrap the UPDATE + commit in a `BEGIN IMMEDIATE` transaction for true atomicity (see note below).

**Note on competing transitions:** If `test_nodestore_transition_status_competing_updates_only_one_wins` remains flaky, the issue is that aiosqlite interleaves the `execute` and `commit` calls between coroutines. The fix is to make `transition_status` use an explicit `BEGIN IMMEDIATE` to hold a write lock across the UPDATE + commit. This is a pre-existing aiosqlite interleaving issue unrelated to `TransactionContext`.

### Testing & Validation

```bash
devenv shell -- pytest tests/unit/test_graph.py -v
```

---

## Step 4: Update test_event_store to Wire TransactionContext

### Problem

Every test in `tests/unit/test_event_store.py` constructs `EventStore(db=db)` without the now-required `event_bus`, `dispatcher`, and `tx` parameters.

### What to Change

**File:** `tests/unit/test_event_store.py`

Add fixtures and a helper function:

```python
import pytest_asyncio

from remora.core.events.bus import EventBus
from remora.core.events.dispatcher import TriggerDispatcher
from remora.core.events.subscriptions import SubscriptionRegistry
from remora.core.transaction import TransactionContext


@pytest_asyncio.fixture
async def event_env(tmp_path):
    """Standard EventStore wiring for tests."""
    db = await open_database(tmp_path / "events.db")
    bus = EventBus()
    subs = SubscriptionRegistry(db)
    dispatcher = TriggerDispatcher(subs)
    tx = TransactionContext(db, bus, dispatcher)
    subs.set_tx(tx)
    store = EventStore(db=db, event_bus=bus, dispatcher=dispatcher, tx=tx)
    await store.create_tables()
    yield store, bus, db
    await db.close()
```

Then update each test. For example:

```python
@pytest.mark.asyncio
async def test_eventstore_append_returns_id(event_env) -> None:
    store, _bus, _db = event_env
    first = await store.append(AgentStartEvent(agent_id="a"))
    second = await store.append(AgentStartEvent(agent_id="b"))
    assert first == 1
    assert second == 2
```

For `test_eventstore_batch_uses_single_commit`, the commit-counting approach changes slightly. `tx.batch()` handles depth; the monkeypatched commit counter on `db.commit` should see exactly 1 call:

```python
@pytest.mark.asyncio
async def test_eventstore_batch_uses_single_commit(event_env, monkeypatch) -> None:
    store, _bus, db = event_env

    commit_count = 0
    original_commit = db.commit

    async def counting_commit() -> None:
        nonlocal commit_count
        commit_count += 1
        await original_commit()

    monkeypatch.setattr(db, "commit", counting_commit)
    commit_count = 0

    async with store.batch():
        for index in range(10):
            await store.append(AgentStartEvent(agent_id=f"a{index}"))

    assert commit_count == 1
```

For `test_eventstore_forwards_to_bus`, the test already creates a custom `EventBus` — just also create the other required deps:

```python
@pytest.mark.asyncio
async def test_eventstore_forwards_to_bus(tmp_path) -> None:
    bus = EventBus()
    seen: list[str] = []
    bus.subscribe_all(lambda event: seen.append(event.event_type))

    db = await open_database(tmp_path / "events.db")
    subs = SubscriptionRegistry(db)
    dispatcher = TriggerDispatcher(subs)
    tx = TransactionContext(db, bus, dispatcher)
    subs.set_tx(tx)
    store = EventStore(db=db, event_bus=bus, dispatcher=dispatcher, tx=tx)
    await store.create_tables()
    await store.append(AgentStartEvent(agent_id="a"))
    assert seen == ["agent_start"]
    await db.close()
```

### Testing & Validation

```bash
devenv shell -- pytest tests/unit/test_event_store.py -v
```

---

## Step 5: Replace Externals Version Warning Test with Error Test

### Problem

Step 8 of the refactor moved the externals version check from `workspace.py` (warning) to `turn_executor.py` (hard `IncompatibleBundleError`). The test `test_read_bundle_config_warns_on_newer_externals_version` still expects a warning log from `read_bundle_config()`, which no longer performs any version check.

### What to Change

**File:** `tests/unit/test_actor.py`

Replace the test at lines 770-782:

```python
# DELETE:
@pytest.mark.asyncio
async def test_read_bundle_config_warns_on_newer_externals_version(actor_env, caplog) -> None:
    ...

# REPLACE WITH:
@pytest.mark.asyncio
async def test_read_bundle_config_passes_through_externals_version(actor_env) -> None:
    """read_bundle_config returns the version as-is; enforcement is in the turn executor."""
    node_id = "src/app.py::externals-version-pass"
    workspace = await actor_env["workspace_service"].get_agent_workspace(node_id)
    await workspace.write("_bundle/bundle.yaml", "externals_version: 999\n")

    bundle_config = await actor_env["workspace_service"].read_bundle_config(node_id)
    assert bundle_config.externals_version == 999
```

The companion test `test_read_bundle_config_without_externals_version_has_no_warning` (lines 785-798) should also be simplified — it tests for absence of a warning that can no longer happen. Rename and simplify:

```python
@pytest.mark.asyncio
async def test_read_bundle_config_defaults_externals_version_to_none(actor_env) -> None:
    """Without explicit externals_version, bundle config defaults to None."""
    node_id = "src/app.py::externals-version-none"
    workspace = await actor_env["workspace_service"].get_agent_workspace(node_id)
    await workspace.write("_bundle/bundle.yaml", "model: mock\n")

    bundle_config = await actor_env["workspace_service"].read_bundle_config(node_id)
    assert bundle_config.externals_version is None
```

### Testing & Validation

```bash
devenv shell -- pytest tests/unit/test_actor.py -k externals -v
```

---

## Step 6: Update test_services Dummy to Match FileReconciler Signature

### Problem

`RuntimeServices.initialize()` passes `language_registry`, `subscription_manager`, and `tx` to `FileReconciler`. The `_DummyReconciler` in `test_services.py` doesn't accept these, causing `TypeError`.

### What to Change

**File:** `tests/unit/test_services.py`

Update `_DummyReconciler` to match the real `FileReconciler` constructor signature. Also verify that the critical new dependencies are actually provided:

```python
class _DummyReconciler:
    last_search_service = None
    last_language_registry = None
    last_subscription_manager = None
    last_tx = None

    def __init__(
        self,
        config,
        node_store,
        event_store,
        workspace_service,
        project_root,
        language_registry,
        subscription_manager,
        *,
        search_service=None,
        tx=None,
    ) -> None:
        del config, node_store, event_store, workspace_service, project_root
        self._running = False
        self.stop_task = None
        type(self).last_search_service = search_service
        type(self).last_language_registry = language_registry
        type(self).last_subscription_manager = subscription_manager
        type(self).last_tx = tx

    async def start(self, event_bus) -> None:
        del event_bus
        self._running = True

    def stop(self) -> None:
        self._running = False
```

Update the test assertions to verify the new dependencies are provided:

```python
@pytest.mark.asyncio
async def test_runtime_services_search_disabled(tmp_path, monkeypatch) -> None:
    import remora.core.services as services_module

    monkeypatch.setattr(services_module, "FileReconciler", _DummyReconciler)
    monkeypatch.setattr(services_module, "ActorPool", _DummyActorPool)

    db = await open_database(tmp_path / "services-disabled.db")
    services = RuntimeServices(Config(), tmp_path, db)
    await services.initialize()

    assert services.search_service is None
    assert _DummyReconciler.last_search_service is None
    assert _DummyActorPool.last_search_service is None
    # Verify new refactored dependencies are wired
    assert _DummyReconciler.last_language_registry is not None
    assert _DummyReconciler.last_subscription_manager is not None
    assert _DummyReconciler.last_tx is services.tx

    await services.close()
```

### Testing & Validation

```bash
devenv shell -- pytest tests/unit/test_services.py -v
```

---

## Step 7: Update All Remaining Flat Config Construction

### Problem

Multiple test files still construct `Config()` with flat keys (`discovery_paths`, `workspace_root`, etc.) that now live in sub-models. Pydantic raises `Extra inputs are not permitted`.

### Affected Files

| File | Config calls |
|---|---|
| `tests/unit/test_watcher.py` | 1 (`_config()` helper) |
| `tests/unit/test_directories.py` | 1 (`_config()` helper) |
| `tests/unit/test_concurrency.py` | 2 (one per test) |
| `tests/integration/test_e2e.py` | 1 (`_setup_runtime()`) |
| `tests/integration/test_lifecycle.py` | 1 |
| `tests/integration/test_performance.py` | 1 |
| `tests/integration/test_llm_turn.py` | 3 (currently skipped, fix preventively) |

### Key Mapping

| Old flat key | New nested path |
|---|---|
| `discovery_paths` | `project=ProjectConfig(discovery_paths=...)` |
| `discovery_languages` | `project=ProjectConfig(discovery_languages=...)` |
| `workspace_ignore_patterns` | `project=ProjectConfig(workspace_ignore_patterns=...)` |
| `workspace_root` | `infra=InfraConfig(workspace_root=...)` |
| `model_base_url` | `infra=InfraConfig(model_base_url=...)` |
| `model_api_key` | `infra=InfraConfig(model_api_key=...)` |
| `timeout_s` | `infra=InfraConfig(timeout_s=...)` |
| `max_concurrency` | `runtime=RuntimeConfig(max_concurrency=...)` |
| `trigger_cooldown_ms` | `runtime=RuntimeConfig(trigger_cooldown_ms=...)` |
| `max_trigger_depth` | `runtime=RuntimeConfig(max_trigger_depth=...)` |
| `language_map` | `behavior=BehaviorConfig(language_map=...)` |
| `query_search_paths` | `behavior=BehaviorConfig(query_search_paths=...)` |
| `bundle_search_paths` | `behavior=BehaviorConfig(bundle_search_paths=...)` |
| `bundle_overlays` | `behavior=BehaviorConfig(bundle_overlays=...)` |
| `prompt_templates` | `behavior=BehaviorConfig(prompt_templates=...)` |
| `model_default` | `behavior=BehaviorConfig(model_default=...)` |
| `max_turns` | `behavior=BehaviorConfig(max_turns=...)` |

### What to Change

Apply the mapping mechanically to each file. Example transformations:

**`tests/unit/test_watcher.py`:**

```python
from remora.core.config import BehaviorConfig, Config, InfraConfig, ProjectConfig


def _config() -> Config:
    return Config(
        project=ProjectConfig(
            discovery_paths=("src",),
            discovery_languages=("python",),
        ),
        behavior=BehaviorConfig(
            language_map={".py": "python"},
            query_search_paths=("@default",),
            bundle_search_paths=("bundles",),
        ),
        infra=InfraConfig(workspace_root=".remora-reconcile"),
    )
```

**`tests/unit/test_concurrency.py` — `test_concurrent_dispatch_serializes_for_single_actor`:**

```python
from remora.core.config import Config, InfraConfig, RuntimeConfig

    config = Config(
        infra=InfraConfig(workspace_root=".remora-concurrency"),
        runtime=RuntimeConfig(trigger_cooldown_ms=0, max_trigger_depth=10),
    )
```

**`tests/integration/test_e2e.py` — `_setup_runtime()`:**

```python
from remora.core.config import BehaviorConfig, Config, InfraConfig, ProjectConfig

    config = Config(
        project=ProjectConfig(
            discovery_paths=("src",),
            discovery_languages=("python",),
        ),
        behavior=BehaviorConfig(
            bundle_search_paths=(str(bundles_root),),
            bundle_overlays={"function": "code-agent", "class": "code-agent", "method": "code-agent"},
            prompt_templates={"user": _E2E_USER_TEMPLATE},
            model_default="mock",
            max_turns=2,
        ),
        infra=InfraConfig(workspace_root=".remora-e2e"),
    )
```

**`tests/integration/test_llm_turn.py` — all three `Config()` calls:**

```python
    config = Config(
        project=ProjectConfig(
            discovery_paths=("src",),
            discovery_languages=("python",),
        ),
        behavior=BehaviorConfig(
            bundle_search_paths=(str(bundles_root),),
            bundle_overlays={"function": "code-agent", "class": "code-agent", "method": "code-agent"},
            prompt_templates={"user": _LLM_USER_TEMPLATE},
            model_default=model_name,
            max_turns=8,
        ),
        infra=InfraConfig(
            workspace_root=".remora-llm-int",
            model_base_url=model_url,
            model_api_key=model_api_key,
            timeout_s=timeout_s,
        ),
    )
```

Apply the same pattern to `test_directories.py`, `test_lifecycle.py`, and `test_performance.py`.

### Testing & Validation

```bash
devenv shell -- pytest tests/unit/test_watcher.py tests/unit/test_directories.py tests/unit/test_concurrency.py tests/integration/test_lifecycle.py tests/integration/test_performance.py -v
```

---

## Step 8: Update All Remaining FileReconciler Construction

### Problem

`FileReconciler.__init__` now requires `language_registry` and `subscription_manager` as positional arguments (Step 9 and Step 10 of the refactoring). Several test files construct `FileReconciler` without these, plus they construct `NodeStore` and `EventStore` without `TransactionContext`.

### Affected Files

| File | Issue |
|---|---|
| `tests/unit/test_concurrency.py` | Missing `language_registry`, `subscription_manager`, no `tx` on stores |
| `tests/integration/test_e2e.py` | Missing `language_registry`, `subscription_manager`, no `tx` on stores |
| `tests/integration/test_performance.py` | Missing `language_registry`, `subscription_manager`, no `tx` on stores |
| `tests/integration/test_llm_turn.py` | Same (skipped but fix preventively) |

### What to Change

Each test that constructs `NodeStore`, `EventStore`, and `FileReconciler` must now wire the full dependency graph. Extract a helper or do it inline. Here is the full wiring pattern:

```python
from remora.code.languages import LanguageRegistry
from remora.code.subscriptions import SubscriptionManager
from remora.core.config import resolve_query_search_paths
from remora.core.events import EventBus, EventStore, SubscriptionRegistry, TriggerDispatcher
from remora.core.graph import NodeStore
from remora.core.transaction import TransactionContext

    db = await open_database(tmp_path / "test.db")
    event_bus = EventBus()
    subs = SubscriptionRegistry(db)
    dispatcher = TriggerDispatcher(subs)
    tx = TransactionContext(db, event_bus, dispatcher)
    subs.set_tx(tx)
    node_store = NodeStore(db, tx=tx)
    event_store = EventStore(db=db, event_bus=event_bus, dispatcher=dispatcher, tx=tx)
    await node_store.create_tables()
    await event_store.create_tables()

    language_registry = LanguageRegistry.from_config(
        language_defs=config.behavior.languages,
        query_search_paths=resolve_query_search_paths(config, tmp_path),
    )
    subscription_manager = SubscriptionManager(event_store, workspace_service)

    reconciler = FileReconciler(
        config,
        node_store,
        event_store,
        workspace_service,
        project_root=tmp_path,
        language_registry=language_registry,
        subscription_manager=subscription_manager,
        tx=tx,
    )
```

This mirrors the `RuntimeServices` wiring exactly. Apply to each affected file.

For tests that also construct `ActorPool` (e.g., `test_e2e.py`, `test_concurrency.py`), pass the `dispatcher`:

```python
    runner = ActorPool(
        event_store, node_store, workspace_service, config,
        dispatcher=dispatcher,
    )
```

### Testing & Validation

```bash
devenv shell -- pytest tests/ -x -v
```

---

## Execution Order

Steps must be done in this order — later steps depend on earlier ones:

1. **Step 1** — Make `tx` required in source. This intentionally breaks tests.
2. **Step 2** — Remove dead fallback code from source.
3. **Steps 3-4** — Fix unit tests for `NodeStore` and `EventStore`.
4. **Step 5** — Fix externals version test.
5. **Step 6** — Fix services dummy.
6. **Steps 7-8** — Fix remaining Config and FileReconciler construction across all test files.

### Final Validation

```bash
devenv shell -- pytest tests/ -x -v
```

Target: **0 failures**, all tests using production-aligned wiring.

### Commit Strategy

Single commit:
```
fix: make TransactionContext required and align all tests with production wiring
```
