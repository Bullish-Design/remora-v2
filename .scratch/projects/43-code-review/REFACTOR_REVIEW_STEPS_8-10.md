# Refactor Review: Steps 8-10

**Date:** 2026-03-17
**Scope:** Steps 8 (Enforce Externals Version), 9 (Eliminate Discovery Cache Staleness), 10 (Extract Subscription Manager)
**Reference:** `REVIEW_REFACTORING_GUIDE.md`

---

## Table of Contents

1. [Step 8: Enforce Externals Version — Review](#step-8-enforce-externals-version--review)
   - Summary of what was specified vs implemented
   - Boundary violation fix verification
   - `IncompatibleBundleError` placement analysis
   - Issues found (0 critical, 1 minor)

2. [Step 9: Eliminate Discovery Cache Staleness — Review](#step-9-eliminate-discovery-cache-staleness--review)
   - Removal of `_DEFAULT_LANGUAGE_MAP` and `@lru_cache` verification
   - `discover()` signature change verification
   - `LanguageRegistry` threading analysis
   - Issues found (1 medium — parser/query recreation on every file)

3. [Step 10: Extract Subscription Manager — Review](#step-10-extract-subscription-manager--review)
   - `SubscriptionManager` class structure and completeness
   - Callback wiring in `DirectoryManager` and `VirtualAgentManager`
   - `_register_subscriptions` removal from reconciler
   - Issues found (2 medium — callback type annotation, reconciler tx gate)

4. [Cross-Cutting Issues](#cross-cutting-issues)
   - `VirtualAgentManager` and `DirectoryManager` still use nested store batches
   - `SubscriptionRegistry._tx` late-binding fragility

5. [Summary Table](#summary-table)

---

## Step 8: Enforce Externals Version — Review

### What the Guide Specified

1. Define `IncompatibleBundleError` exception
2. Remove the version check from `CairnWorkspaceService.read_bundle_config()` (workspace.py)
3. Move the version check to `AgentTurnExecutor._start_agent_turn()` (turn_executor.py)
4. Remove `EXTERNALS_VERSION` import from workspace.py (boundary violation fix)

### What Was Implemented

**`workspace.py`:**
- `IncompatibleBundleError` defined at line 24-25
- The old version check (lines 184-190 in the pre-refactor code) has been **removed** from `read_bundle_config()`
- `EXTERNALS_VERSION` import from `remora.core.externals` has been **removed** — the boundary violation is fixed
- `IncompatibleBundleError` is exported in `__all__` (line 247)

**`turn_executor.py`:**
- `EXTERNALS_VERSION` imported from `remora.core.externals` at line 27
- `IncompatibleBundleError` imported from `remora.core.workspace` at line 26
- Version check added to `_start_agent_turn()` at lines 207-214, after `read_bundle_config()` returns
- The check raises `IncompatibleBundleError` when `bundle_config.externals_version > EXTERNALS_VERSION`
- The existing error boundary in `execute_turn()` (lines 164-176) catches it, transitions node to ERROR, and emits `AgentErrorEvent`

### Verdict: CORRECT

The implementation matches the guide exactly. The boundary violation is fixed — workspace.py no longer knows about externals versioning, and the turn executor owns the version gate.

### Issues

**Minor — `IncompatibleBundleError` lives in workspace.py:**
The exception is defined in `workspace.py` even though workspace.py no longer uses it. The guide mentioned putting it in "a shared exceptions module" as an alternative. Currently `turn_executor.py` imports it from `workspace.py`, which creates a mild conceptual mismatch (workspace defines the error, turn_executor raises it). This is not wrong, but if a `core/errors.py` module is ever created, consider moving it there.

---

## Step 9: Eliminate Discovery Cache Staleness — Review

### What the Guide Specified

1. Remove `_DEFAULT_LANGUAGE_MAP` from `discovery.py`
2. Remove all `@lru_cache` decorated functions (`_get_language_registry`, `_get_parser`, `_get_registry_plugin`, `_load_query`)
3. Make `language_map` and `language_registry` required parameters on `discover()`
4. Thread `LanguageRegistry` through to `_parse_file` instead of using cached module-level functions
5. Update the reconciler to pass the registry
6. Optionally add parser/query caching to `LanguagePlugin` classes

### What Was Implemented

**`discovery.py`:**
- `_DEFAULT_LANGUAGE_MAP` is completely gone — confirmed by grep (no matches in the entire codebase)
- All `@lru_cache` decorated functions are completely gone — confirmed by grep (no matches)
- `discover()` signature (lines 16-24) now requires `language_map: dict[str, str]` and `language_registry: LanguageRegistry` as keyword-only parameters — both non-optional
- The function uses the passed `language_registry` directly (line 29, 37) — no module-level state
- `_parse_file()` (lines 61-151) creates `Parser` and `Query` inline from the plugin

**`languages.py`:**
- `LanguageRegistry` class (lines 123-186) with `from_config()` classmethod and `from_defaults()` classmethod
- `PythonPlugin` (lines 27-79) with `get_language()` returning `Language(tree_sitter_python.language())`
- `GenericLanguagePlugin` (lines 82-115) with `get_language()` using `importlib.import_module()`
- `ADVANCED_PLUGINS` dict (lines 118-120) for Python-specific plugin dispatch
- `LanguageRegistry.from_config()` resolves query paths and builds plugins from YAML language definitions

**`reconciler.py`:**
- Constructor now accepts `language_registry: LanguageRegistry` (line 49)
- `_do_reconcile_file()` passes `language_registry=self._language_registry` to `discover()` (line 200)

**`services.py`:**
- `LanguageRegistry.from_config()` constructed at lines 47-50 using `config.behavior.languages` and resolved query paths
- Passed to `FileReconciler` constructor at line 74

### Verdict: CORRECT (with one performance concern)

The cache staleness issue is fully resolved. Discovery no longer uses any module-level cached state — everything flows through explicit parameters. The `LanguageRegistry` is built once in `RuntimeServices` and threaded through to all consumers.

### Issues

**Medium — No parser/query caching in `_parse_file`:**

`_parse_file()` at `discovery.py:61-68` creates a new `Parser` and `Query` on every invocation:

```python
def _parse_file(path: Path, plugin: LanguagePlugin, query_paths: list[Path]) -> list[Node]:
    source_bytes = path.read_bytes()
    parser = Parser(plugin.get_language())        # new Parser per file
    tree = parser.parse(source_bytes)

    query_file = _resolve_query_file(plugin, query_paths)
    query_text = query_file.read_text(encoding="utf-8")  # re-reads query file
    query = Query(plugin.get_language(), query_text)      # new Query per file
```

For each file discovered, this:
1. Calls `plugin.get_language()` (which calls `tree_sitter_python.language()` or `importlib.import_module()`)
2. Creates a new `Parser` wrapping that language
3. Reads the query `.scm` file from disk
4. Compiles a new `Query` from the text

The guide explicitly suggested adding caching to `LanguagePlugin`:

> *"If parser/query construction is expensive, add a cache to `LanguageRegistry` or `LanguagePlugin` instead"*

For a codebase with hundreds of Python files, this means hundreds of redundant `Parser` constructions and query file reads during a single reconciliation cycle. The fix is straightforward — cache per-plugin:

```python
class PythonPlugin:
    def get_language(self) -> Language:
        if not hasattr(self, "_language"):
            self._language = Language(tree_sitter_python.language())
        return self._language
```

And cache the resolved query file path + compiled query in `_parse_file` or on the plugin. Alternatively, have `discover()` maintain a local cache dict keyed by `plugin.name` for the duration of one call.

This is not a correctness bug, but it is a performance regression compared to the pre-refactor `@lru_cache` approach. Worth addressing before processing large codebases.

---

## Step 10: Extract Subscription Manager — Review

### What the Guide Specified

1. Create `SubscriptionManager` class in `src/remora/code/subscriptions.py`
2. Move all subscription logic from `FileReconciler._register_subscriptions` into it
3. Handle code nodes (content changed + self-reflection), directory nodes (node_changed + content_changed globs), and virtual nodes (custom patterns)
4. Update `DirectoryManager` and `VirtualAgentManager` to use it (via callback or direct reference)
5. Wire it in `RuntimeServices`
6. Delete `_register_subscriptions` from `FileReconciler`

### What Was Implemented

**`src/remora/code/subscriptions.py` (new file):**
- `SubscriptionManager` class (lines 11-78)
- Constructor takes `event_store` and `workspace_service` (lines 14-20)
- `register_for_node()` method (lines 22-78) handles all three node types:
  - All nodes: clears old subscriptions, registers direct-message subscription (lines 29-34)
  - Virtual nodes: registers custom patterns from `virtual_subscriptions` kwarg (lines 36-39)
  - Directory nodes: registers `NODE_CHANGED` and `CONTENT_CHANGED` with subtree globs (lines 41-57)
  - Code nodes: checks workspace KV for self-reflect config, registers `AGENT_COMPLETE` self-subscription if enabled (lines 59-70), registers `CONTENT_CHANGED` for own file path (lines 72-78)
- Exported in `__all__` (line 81)

**`reconciler.py`:**
- Imports `SubscriptionManager` from `remora.code.subscriptions` (line 16)
- Constructor accepts `subscription_manager: SubscriptionManager` (line 50)
- Stores as `self._subscription_manager` (line 61)
- Passes `self._subscription_manager.register_for_node` as callback to `DirectoryManager` (line 81) and `VirtualAgentManager` (line 89)
- `_do_reconcile_file()` calls `self._subscription_manager.register_for_node(node)` directly for additions (line 265) and updates (line 280)
- Old `_register_subscriptions` method is completely deleted — confirmed by grep

**`directories.py`:**
- Receives `register_subscriptions` callback (line 29) typed as `Callable[[Node], Awaitable[None]]`
- Calls it for new directories (line 148), subscription refreshes (line 178), and on hash changes (line 183)

**`virtual_agents.py`:**
- Receives `register_subscriptions` callback (lines 31-33) typed as `Callable[[Node], Awaitable[None]]`
- Calls it with `virtual_subscriptions=patterns` kwarg (lines 79-82, 104-107)

**`services.py`:**
- Creates `SubscriptionManager` at line 66
- Passes to `FileReconciler` at line 75

### Verdict: CORRECT (with two issues)

The extraction is clean and complete. The subscription logic is properly centralized in `SubscriptionManager`, and the old code was fully removed from the reconciler.

### Issues

**Medium — Type annotation mismatch for `register_subscriptions` callback in `VirtualAgentManager`:**

`virtual_agents.py:31-33` types the callback as:

```python
register_subscriptions: Callable[
    [Node], Awaitable[None]
],  # virtual patterns passed as kwarg
```

But then calls it with a keyword argument:

```python
await self._register_subscriptions(
    virtual_node,
    virtual_subscriptions=patterns,
)
```

The type `Callable[[Node], Awaitable[None]]` does not account for the `virtual_subscriptions` keyword argument. This works at runtime because the actual function is `SubscriptionManager.register_for_node`, but the type annotation is inaccurate. A type checker like pyright would flag this.

Fix — use a `Protocol`:

```python
class RegisterSubscriptionsFn(Protocol):
    async def __call__(
        self,
        node: Node,
        *,
        virtual_subscriptions: tuple[SubscriptionPattern, ...] = (),
    ) -> None: ...
```

Or use `Callable[..., Awaitable[None]]` as a pragmatic alternative.

**Medium — Reconciler `_do_reconcile_file` gates all event/edge/subscription work behind `if self._tx is not None:`:**

At `reconciler.py:247-292`, the entire post-discovery logic is wrapped in:

```python
if self._tx is not None:
    async with self._tx.batch():
        # edges, subscriptions, events for additions/updates/removals
```

If `self._tx` is `None`, **all of the following is silently skipped**:
- Parent edge creation (lines 249-255)
- Subscription registration for new/changed nodes (lines 265, 280)
- `NodeDiscoveredEvent` emission for additions (lines 266-273)
- `NodeChangedEvent` emission for updates (lines 281-288)
- `_remove_node` calls for removals (line 291)

This means a `FileReconciler` constructed without `tx` will discover and upsert nodes but **never emit events, register subscriptions, or create edges**. In production this is always wired with `tx` (services.py:77), but tests constructing `FileReconciler` directly without `tx` would get silently broken reconciliation.

Fix — either:
- **Make `tx` required** (remove `| None`, remove the `if` guard, add a fallback batch path)
- **Add an `else` branch** that does the same work with individual commits:

```python
if self._tx is not None:
    async with self._tx.batch():
        await self._reconcile_events(projected, old_ids, new_ids, old_hashes, file_path)
else:
    await self._reconcile_events(projected, old_ids, new_ids, old_hashes, file_path)
```

The cleanest approach is to make `tx` required and update test factories to always provide one.

---

## Cross-Cutting Issues

### `VirtualAgentManager` and `DirectoryManager` Still Use Nested Store Batches

`virtual_agents.py:50-51`:
```python
async with self._node_store.batch():
    async with self._event_store.batch():
```

`directories.py:78-79`:
```python
async with self._node_store.batch():
    async with self._event_store.batch():
```

Both still use the old nested-batch-through-stores pattern from before Step 6. Since both stores delegate their `batch()` to `TransactionContext.batch()` when `tx` is present, this works correctly — it creates nested `tx.batch()` calls, which the depth-tracking handles fine.

However, it's the old style. The guide's Step 6 vision was to use `tx.batch()` directly:

```python
async with self._tx.batch():
    ...
```

Neither `VirtualAgentManager` nor `DirectoryManager` currently receives `tx` directly — they access transactions indirectly through the stores' `batch()` methods. This is acceptable but could be made more explicit by passing `tx` to these managers.

**Severity:** Low. The behavior is correct. This is a style/clarity issue.

### `SubscriptionRegistry._tx` Set via Late-Binding in `services.py`

At `services.py:36`:
```python
self.subscriptions._tx = self.tx
```

This sets a private attribute (`_tx`) from outside the class after construction, because of a circular dependency: `TransactionContext` needs `dispatcher`, `dispatcher` needs `subscriptions`, and `subscriptions` needs `tx`.

This works but is fragile — a future refactor could easily miss that `_tx` is set externally. The `SubscriptionRegistry` constructor already accepts `tx` as a parameter (subscriptions.py:66), so this late-binding is an artifact of the construction order.

**Severity:** Low. Works correctly. Could be addressed by restructuring the construction order or using a two-phase init pattern.

---

## Summary Table

| Step | Verdict | Issues | Severity |
|------|---------|--------|----------|
| **8 — Enforce Externals Version** | **Correct** | `IncompatibleBundleError` defined in workspace.py rather than shared errors module | Minor |
| **9 — Eliminate Discovery Cache Staleness** | **Correct** | No parser/query caching — performance regression for large codebases | Medium |
| **10 — Extract Subscription Manager** | **Correct** | (a) `register_subscriptions` callback type doesn't include `virtual_subscriptions` kwarg; (b) Reconciler tx-None gate silently skips all event/edge/subscription work | Medium |
| **Cross-cutting** | N/A | (a) VirtualAgentManager/DirectoryManager use old nested-batch pattern; (b) SubscriptionRegistry._tx late-binding | Low |

### Priority Order for Fixes

1. **Reconciler tx-None gate** (Step 10, Medium) — Silent data loss in test scenarios
2. **Parser/query caching** (Step 9, Medium) — Performance regression
3. **Callback type annotation** (Step 10, Medium) — Type checker will flag
4. **Nested batch style** (Cross-cutting, Low) — Cleanup
5. **Late-binding _tx** (Cross-cutting, Low) — Fragility
6. **IncompatibleBundleError location** (Step 8, Minor) — Organizational
