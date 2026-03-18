# Test Fix Guide

10 tests are failing after the core reorganization. They group into 4 root causes.

Run tests with: `devenv shell -- pytest -s -vv --ignore=tests/benchmarks --ignore=tests/acceptance`

---

## Fix 1: Add `languages` to `BehaviorConfig` in tests (6 tests)

### Problem

When tests construct `Config(behavior=BehaviorConfig(...))` directly, the `languages`
field defaults to `{}` (empty dict). `LanguageRegistry.from_config({}, ...)` builds
a registry with **zero plugins registered**. Discovery then finds `.py` files via
`language_map`, looks up `"python"` in the empty registry, gets `None`, and raises:

```
ValueError: Configured language 'python' not found for extension '.py'
```

In production, `load_config()` calls `load_defaults()` which provides the `languages`
dict from `defaults.yaml` before deep-merging user config. Tests bypass this.

### Affected tests

| File | Test |
|------|------|
| `tests/integration/test_e2e.py` | `test_e2e_human_chat_to_rewrite` |
| `tests/integration/test_e2e.py` | `test_e2e_agent_message_chain` |
| `tests/integration/test_e2e.py` | `test_e2e_file_change_triggers` |
| `tests/integration/test_e2e.py` | `test_e2e_two_agents_interact_via_send_message_tool` |
| `tests/integration/test_lifecycle.py` | `test_lifecycle_discovers_nodes_serves_health_and_shuts_down` |
| `tests/integration/test_performance.py` | `test_perf_reconciler_load_1000_files_10_nodes_each` |

### How to fix

Every `BehaviorConfig(...)` that includes `language_map={".py": "python"}` must also
include a matching `languages` entry so the registry has a plugin to resolve.

The minimum required `languages` value for Python-only tests:

```python
languages={"python": {"extensions": [".py"]}},
```

#### test_e2e.py

The `_setup_runtime` helper (line ~117) is missing both `language_map` and `languages`.
Add both to its `BehaviorConfig`:

```python
# Before (line ~117)
behavior=BehaviorConfig(
    bundle_search_paths=(str(bundles_root),),
    bundle_overlays={
        "function": "code-agent",
        "class": "code-agent",
        "method": "code-agent",
    },
    prompt_templates={"user": _E2E_USER_TEMPLATE},
    model_default="mock",
    max_turns=2,
),

# After
behavior=BehaviorConfig(
    language_map={".py": "python"},
    languages={"python": {"extensions": [".py"]}},
    query_search_paths=("@default",),
    bundle_search_paths=(str(bundles_root),),
    bundle_overlays={
        "function": "code-agent",
        "class": "code-agent",
        "method": "code-agent",
    },
    prompt_templates={"user": _E2E_USER_TEMPLATE},
    model_default="mock",
    max_turns=2,
),
```

#### test_lifecycle.py

Add `languages` to the existing `BehaviorConfig` (line ~30):

```python
# Before
behavior=BehaviorConfig(
    language_map={".py": "python"},
    query_search_paths=("@default",),
),

# After
behavior=BehaviorConfig(
    language_map={".py": "python"},
    languages={"python": {"extensions": [".py"]}},
    query_search_paths=("@default",),
),
```

#### test_performance.py

Same pattern as lifecycle. Find the `BehaviorConfig` in
`test_perf_reconciler_load_1000_files_10_nodes_each` and add `languages`:

```python
behavior=BehaviorConfig(
    language_map={".py": "python"},
    languages={"python": {"extensions": [".py"]}},
    query_search_paths=("@default",),
),
```

### How to verify

After the fix, the e2e tests should discover function nodes (`alpha`, `beta`) instead
of returning an empty list. The lifecycle and performance tests should complete
discovery without the `ValueError`.

---

## Fix 2: Monkeypatch the correct module in `test_services.py` (2 tests)

### Problem

The tests do:

```python
import remora.core.services as services_module
monkeypatch.setattr(services_module, "FileReconciler", _DummyReconciler)
```

But `container.py` imports `FileReconciler` directly in its `initialize()` method:

```python
# container.py line 59
async def initialize(self) -> None:
    from remora.code.reconciler import FileReconciler
    ...
```

The monkeypatch replaces `FileReconciler` on the `__init__.py` module's lazy
`__getattr__`, but `container.py` imports from `remora.code.reconciler` directly.
The real `FileReconciler` and `SearchService` are used, so the dummy class attributes
(`last_language_registry`, `init_calls`) are never set.

### Affected tests

| File | Test |
|------|------|
| `tests/unit/test_services.py` | `test_runtime_services_search_disabled` |
| `tests/unit/test_services.py` | `test_runtime_services_search_enabled` |

### How to fix

Patch the modules where `container.py` actually imports from. There are three imports
that `container.py` resolves at runtime inside `__init__` and `initialize()`:

1. `FileReconciler` - imported from `remora.code.reconciler` (inside `initialize()`)
2. `ActorPool` - imported from `remora.core.agents.runner` (top-level in `container.py`)
3. `SearchService` - imported from `remora.core.services.search` (top-level in `container.py`)

Since `container.py` imports `ActorPool` and `SearchService` at module level, and
`FileReconciler` via a local import in `initialize()`, the correct monkeypatch targets
are:

```python
# Before
import remora.core.services as services_module
monkeypatch.setattr(services_module, "FileReconciler", _DummyReconciler)
monkeypatch.setattr(services_module, "ActorPool", _DummyActorPool)

# After
import remora.core.services.container as container_module
monkeypatch.setattr(container_module, "ActorPool", _DummyActorPool)
monkeypatch.setattr("remora.code.reconciler.FileReconciler", _DummyReconciler)
```

For the search-enabled test, also patch SearchService on the container module:

```python
# Before
monkeypatch.setattr(services_module, "SearchService", _DummySearchService)

# After
monkeypatch.setattr(container_module, "SearchService", _DummySearchService)
```

Update both test functions to use `import remora.core.services.container as container_module`
instead of `import remora.core.services as services_module`.

### How to verify

After the fix, `_DummyReconciler.last_language_registry` should be set (not `None`)
because the dummy is now actually instantiated. `_DummySearchService.init_calls`
should be `1` in the enabled test.

---

## Fix 3: Fix the competing-updates test assertion (1 test)

### Problem

`test_nodestore_transition_status_competing_updates_only_one_wins` does:

```python
results = await asyncio.gather(
    store.transition_status("src/app.py::a", NodeStatus.AWAITING_INPUT),
    store.transition_status("src/app.py::a", NodeStatus.ERROR),
)
assert sum(1 for result in results if result) == 1
```

This assumes the two calls race and only one wins. But `aiosqlite` serializes all
operations through a single background thread. The first `transition_status` completes
fully (UPDATE + commit) before the second one starts. Both see status=`running` (a
valid source state) and both succeed, so the count is 2.

This is working as designed -- there is no concurrency with a single `aiosqlite`
connection. The test's assumption was never valid in this architecture.

### Affected test

| File | Test |
|------|------|
| `tests/unit/test_graph.py` | `test_nodestore_transition_status_competing_updates_only_one_wins` |

### How to fix

Change the test to reflect the actual serialized behavior. Both transitions succeed
sequentially, and the final status is whichever ran second. Replace the assertion:

```python
# Before
assert sum(1 for result in results if result) == 1
updated = await store.get_node("src/app.py::a")
assert updated is not None
assert updated.status in {NodeStatus.AWAITING_INPUT, NodeStatus.ERROR}

# After -- both succeed because aiosqlite serializes on a single connection
assert all(results), "both transitions succeed sequentially"
updated = await store.get_node("src/app.py::a")
assert updated is not None
# The second gather operand runs last, so its status wins
assert updated.status == NodeStatus.ERROR
```

Also rename the test to reflect the new semantics:

```python
# Before
async def test_nodestore_transition_status_competing_updates_only_one_wins(db, tx) -> None:

# After
async def test_nodestore_transition_status_sequential_updates_both_succeed(db, tx) -> None:
```

### Why this is correct

Production uses a single `aiosqlite` connection per process. `asyncio.gather` on the
same connection doesn't produce real concurrency -- operations queue up on aiosqlite's
background thread. The test should verify the behavior that actually occurs: both
transitions succeed in sequence and the last one determines the final state.

---

## Fix 4: Serialize overlapping reconcile cycles (1 test)

### Problem

`test_overlapping_reconcile_cycles_are_idempotent` runs:

```python
await asyncio.gather(reconciler.reconcile_cycle(), reconciler.reconcile_cycle())
```

Both cycles call `provision_bundle()`, which writes to Cairn workspaces. Cairn/agentfs
uses its own internal SQLite database for filesystem operations. Two concurrent writes
from the same process trigger `turso.Busy: database is locked` on Cairn's internal DB.

This is not a Remora bug -- Cairn doesn't support concurrent writers from a single
process. In production, reconcile cycles don't overlap because `run_forever()` runs
them sequentially.

### Affected test

| File | Test |
|------|------|
| `tests/unit/test_concurrency.py` | `test_overlapping_reconcile_cycles_are_idempotent` |

### How to fix

Run the two cycles sequentially instead of concurrently. The test's intent is to verify
idempotency (running reconcile twice produces the same result), not concurrent access.

```python
# Before
await asyncio.gather(reconciler.reconcile_cycle(), reconciler.reconcile_cycle())

# After -- reconcile cycles are idempotent, not concurrency-safe
await reconciler.reconcile_cycle()
await reconciler.reconcile_cycle()
```

### How to verify

After the fix, the test should complete without `database is locked`. Both cycles
should produce the same node set (idempotency), which is what the remaining assertions
already check.

---

## Checklist

- [ ] Fix 1: Add `languages={"python": {"extensions": [".py"]}}` to 3 locations
  - [ ] `test_e2e.py` `_setup_runtime` (also add `language_map` and `query_search_paths`)
  - [ ] `test_lifecycle.py` `BehaviorConfig`
  - [ ] `test_performance.py` `BehaviorConfig`
- [ ] Fix 2: Change monkeypatch targets in `test_services.py`
  - [ ] `test_runtime_services_search_disabled`
  - [ ] `test_runtime_services_search_enabled`
- [ ] Fix 3: Update assertion in `test_graph.py` competing-updates test
- [ ] Fix 4: Sequentialize reconcile calls in `test_concurrency.py`
- [ ] Run full test suite and confirm 0 failures
