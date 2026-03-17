# Remora v2 — Code Review

**Date:** 2026-03-17
**Scope:** Full codebase review of `src/remora/` (~7,600 LOC) and the core/plugin boundary refactor (project 42).
**Verdict:** Solid intern work with clear architectural vision, but several structural issues, boundary violations, and missed opportunities that need addressing before the codebase can be considered production-grade.

---

## Table of Contents

1. [Overall Assessment](#1-overall-assessment) — High-level verdict on codebase quality
2. [Architecture & Boundary Review](#2-architecture--boundary-review) — How well the core/defaults split was executed
3. [Concurrency & Correctness](#3-concurrency--correctness) — Thread safety, async discipline, race conditions
4. [Error Handling](#4-error-handling) — Exception boundaries, recovery, and failure modes
5. [Data Model & Persistence](#5-data-model--persistence) — SQLite usage, schema design, transaction management
6. [API Design & Contracts](#6-api-design--contracts) — Externals API, event types, type safety
7. [Configuration System](#7-configuration-system) — Config loading, defaults merging, validation
8. [Discovery & Reconciliation](#8-discovery--reconciliation) — Tree-sitter parsing, file watching, node lifecycle
9. [Prompt & Template System](#9-prompt--template-system) — Template interpolation, prompt construction
10. [Search Integration](#10-search-integration) — Optional embeddy boundary
11. [Web & LSP Surfaces](#11-web--lsp-surfaces) — HTTP routes, SSE, LSP adapter
12. [Testing](#12-testing) — Coverage, fixture design, missing areas
13. [Code Style & Hygiene](#13-code-style--hygiene) — Naming, imports, dead code, conventions
14. [Dependency Management](#14-dependency-management) — pyproject.toml, pinning, optional deps

---

## 1. Overall Assessment

**The good:** The codebase demonstrates a clear architectural vision — reactive code agents driven by events, with SQLite persistence, tree-sitter discovery, and clean surface separation (CLI/web/LSP). The core/plugin boundary refactor (project 42) was executed methodically and achieved its primary goals: bundles and queries now ship inside the package, config is defaults-driven, languages are config-registered, prompts are template-based, search is lazily optional, and externals are versioned.

**The concerning:** The refactor was implemented too literally from the guide — following instructions without enough independent judgment about what should have been done differently during execution. Several design decisions from the guide were questionable and should have been challenged. The intern also introduced subtle bugs, left architectural seams half-finished, and missed opportunities to simplify.

### Scorecard

| Area | Grade | Notes |
|------|-------|-------|
| Architecture | B | Good separation of concerns, but boundary is leaky in places |
| Correctness | C+ | Several race conditions, lock misuse, incomplete error recovery |
| Code quality | B- | Generally clean, but inconsistent patterns and some dead weight |
| Testing | B | Good breadth (50 test files), unclear depth and integration coverage |
| Refactor execution | B- | Followed the guide well, but didn't think independently enough |

---

## 2. Architecture & Boundary Review

### 2.1 What the refactor got right

- **Bundles inside the package.** Moving bundles from repo-root `bundles/` to `src/remora/defaults/bundles/` was the correct call. The `importlib.resources` helpers in `defaults/__init__.py` are clean.
- **`@default` sentinel.** The `bundle_search_paths` and `query_search_paths` with `@default` → package directory resolution is a good pattern.
- **Config-driven languages.** `LanguageRegistry.from_config()` with `ADVANCED_PLUGINS` for Python's special needs is well-designed.
- **Externals versioning.** The `EXTERNALS_VERSION` constant + `BundleConfig.externals_version` with warning-on-mismatch is simple and effective.

### 2.2 Boundary violations and leaks

**ISSUE: `workspace.py` imports `EXTERNALS_VERSION` from `externals.py`.**
`CairnWorkspaceService.read_bundle_config()` (line 243) imports and checks `EXTERNALS_VERSION`. This is a boundary violation — the workspace service is infrastructure; externals version checking is a business rule that belongs in the turn executor or a bundle validation layer. The workspace should just parse and return the config; the caller decides whether to accept it.

**ISSUE: `reconciler.py` reads `bundle.yaml` directly.**
`_provision_bundle` in `reconciler.py:412-422` reads `bundle.yaml`, parses self_reflect config, and writes to KV. This duplicates logic with `CairnWorkspaceService.read_bundle_config()`. The reconciler should call `read_bundle_config()` instead of reimplementing YAML parsing.

**ISSUE: `discovery.py` has a stale `_DEFAULT_LANGUAGE_MAP`.**
Line 16-20 defines `_DEFAULT_LANGUAGE_MAP = {".py": "python", ".md": "markdown", ".toml": "toml"}`. This is dead code from before the refactor — the language map now comes from `defaults.yaml`. But the fallback in `discover()` still uses it when `language_map` is None. This means `discover()` works without config, which violates the principle that all behavior should come from `defaults.yaml`.

**ISSUE: `discovery.py` has module-level caches that bypass config.**
`_get_language_registry()` is an `@lru_cache(maxsize=1)` that calls `LanguageRegistry.from_defaults()`. This creates a registry from `defaults.yaml` independent of the user's config. If a user adds a custom language in `remora.yaml`, the `discover()` function called without an explicit `language_registry` parameter will ignore it. The reconciler does pass `language_map` but not a `language_registry`, so it uses config's language map but the default registry. This is a subtle inconsistency.

### 2.3 Boundary decisions that should have been challenged

**The `code/` package should not be "frozen."**
The refactor guide declares `code/` as frozen infrastructure. But `code/` contains `reconciler.py` (441 lines) which is the single most complex module in the codebase and the primary place where new behavior will need to evolve. Freezing it is premature. A better boundary would freeze `core/events/`, `core/graph.py`, `core/db.py`, and `core/types.py`, but leave `code/reconciler.py` and `code/directories.py` as mutable orchestration.

**`Config` is doing too much.**
`Config` at 361 lines contains: project config, bundle config, search config, virtual agent config, language definitions, prompt templates, externals version, and config resolution helpers. It's a god object. The refactor should have split it into at least:
- `ProjectConfig` (paths, ignore patterns)
- `RuntimeConfig` (concurrency, timeouts, rate limits)
- `BehaviorConfig` (bundles, languages, prompts — the defaults.yaml layer)
- `SearchConfig` (already exists but is nested)

**`services.py` is anemic.**
`RuntimeServices` at 100 lines is just a constructor + `initialize()` + `close()`. For a "DI container" it does almost nothing — all the actual wiring happens in `lifecycle.py`. Either make it a proper service locator or just inline the construction into lifecycle.

---

## 3. Concurrency & Correctness

### 3.1 AgentWorkspace lock granularity is wrong

`AgentWorkspace` uses a single `asyncio.Lock()` per workspace for ALL operations (read, write, exists, list_dir, kv_get, kv_set, etc.). This means a slow file read blocks all KV operations for that agent. Since the underlying Cairn workspace is likely already thread-safe (it's a library), this global lock adds unnecessary serialization. If a lock is truly needed, it should be per-subsystem (files vs KV) or removed entirely.

### 3.2 CairnWorkspaceService has a race between check and cache

In `get_agent_workspace()` (workspace.py:191-209), the lock is released BEFORE the workspace is added to the cache:

```python
async with self._lock:
    cached = self._agent_workspaces.get(node_id)
    if cached is not None:
        return cached
    raw_workspace = await cairn_wm.open_workspace(str(workspace_path))
    self._manager.track_workspace(raw_workspace)
    # lock released here
agent_workspace = AgentWorkspace(raw_workspace, node_id)
self._raw_agent_workspaces[node_id] = raw_workspace  # NOT under lock
self._agent_workspaces[node_id] = agent_workspace     # NOT under lock
```

Two concurrent calls for the same `node_id` can both pass the cache check, both open workspaces, and race to write to the cache. The second write wins, orphaning the first workspace (it's tracked by `_manager` but the `AgentWorkspace` wrapper is lost). Move the cache writes inside the lock.

### 3.3 TriggerPolicy is per-Actor but has shared-looking semantics

`TriggerPolicy` is instantiated per-Actor (actor.py:50), but its cooldown (`last_trigger_ms`) applies globally to that actor. The `trigger_cooldown_ms` prevents the same actor from being triggered more than once per cooldown window. This seems intentional but the naming is confusing — it's really a "per-actor debounce" not a system-wide cooldown.

### 3.4 EventBus handler dispatch creates unbounded tasks

`EventBus._dispatch_handlers()` creates an `asyncio.Task` for every async handler and gathers them. If a burst of events arrives and handlers are slow, this creates unbounded concurrent tasks. There's no backpressure mechanism. For a system with potentially thousands of events (e.g., during full_scan), this could overwhelm the event loop.

### 3.5 ActorPool.run_forever is a polling loop

`run_forever()` uses `await asyncio.sleep(1.0)` in a loop to periodically evict idle actors. This is fine for idle eviction but means the pool does nothing useful between sleeps. The sleep interval should at least be configurable, and the idle eviction could be event-driven instead.

---

## 4. Error Handling

### 4.1 Overly broad exception catching with `BLE001` suppression

The codebase has 12+ instances of `except Exception` with `# noqa: BLE001` comments. While the intent (error boundaries that prevent cascading failures) is correct, the execution is sloppy:

- **`reconciler.py:158`** catches all exceptions during watch-triggered reconcile but only logs them. If the error is a `RuntimeError` from a corrupt database, silently continuing is wrong.
- **`workspace.py:421`** catches all exceptions during bundle metadata sync. A `PermissionError` writing to KV would be silently swallowed.
- **`grail.py:203`** catches all exceptions loading a tool script. A `SyntaxError` in a `.pym` file gets logged and skipped — fine for resilience, but the user has no feedback mechanism beyond checking logs.

**Recommendation:** Replace broad catches with specific exception types where the failure mode is known. Keep broad catches only at true process boundaries (actor loop, watch loop, HTTP handlers).

### 4.2 `request_human_input` can leave node in wrong state

In `CommunicationCapabilities.request_human_input()` (externals.py:320-327):

```python
try:
    return await asyncio.wait_for(future, timeout=...)
except TimeoutError:
    self._event_store.discard_response_future(request_id)
    raise
finally:
    await self._node_store.transition_status(self._node_id, NodeStatus.RUNNING)
```

If the timeout fires, the node transitions from `AWAITING_INPUT` → `RUNNING`. But the `TimeoutError` is re-raised, which will propagate up to the turn executor's `except Exception` handler, which transitions to `ERROR`. So the node rapidly goes `AWAITING_INPUT` → `RUNNING` → `ERROR`. The `finally` block's transition to `RUNNING` is pointless when the error will override it. Also, if the turn executor's reset then transitions from `ERROR` → `IDLE` via `_reset_agent_state`, the node goes through 4 state transitions for one timeout.

### 4.3 No structured error reporting to users

Tool failures, bundle validation errors, and externals version mismatches all go to Python logging. There's no mechanism for surfacing these errors through the web UI or LSP surface. A user seeing a silent agent would have to grep logs to find out why.

---

## 5. Data Model & Persistence

### 5.1 No database migrations

Tables are created with `CREATE TABLE IF NOT EXISTS`. There's no migration system. If the schema needs to change (and it will — e.g., adding columns to `events` or `nodes`), there's no path forward other than deleting the database. This is acceptable for a pre-1.0 project but needs addressing before any real usage.

### 5.2 Batch contexts are fragile

Both `NodeStore.batch()` and `EventStore.batch()` track `_batch_depth` as an integer counter for nested batches. But they share the same `aiosqlite.Connection` (passed via `RuntimeServices`). If `NodeStore.batch()` and `EventStore.batch()` are nested (as in `reconciler.py:235-236`), both are managing commits on the same connection with independent depth counters. The `EventStore.batch()` will commit when its depth reaches 0, even if `NodeStore.batch()` hasn't finished yet — because they commit independently.

In practice this works because the nesting in reconciler always puts `NodeStore.batch()` as the outer context and `EventStore.batch()` as the inner, and the event store commits first. But this relies on call ordering, not structural guarantees. A single unified transaction context would be safer.

### 5.3 `fetchall()` everywhere with no pagination

`NodeStore.list_nodes()`, `EventStore.get_events()`, `SubscriptionRegistry.get_matching_agents()` — all use `fetchall()` which loads entire result sets into memory. For a project with thousands of nodes or tens of thousands of events, this will become a problem. The `list_nodes()` method in particular is called during broadcast resolution (`_resolve_broadcast_targets`), which loads ALL nodes just to filter by ID.

### 5.4 Node model mixes discovery data with runtime state

`Node` has both discovery-time fields (`start_line`, `end_line`, `text`, `source_hash`) and runtime fields (`status`, `role`). The `upsert_node` does `INSERT OR REPLACE` which means a re-discovery overwrites runtime state. The reconciler carefully preserves `status` and `role` before upserting, but this is fragile — any caller of `upsert_node` that forgets to carry forward runtime fields will reset them.

---

## 6. API Design & Contracts

### 6.1 `to_dict()` / `to_capabilities_dict()` is a poor tool registration pattern

Each capability group (`FileCapabilities`, `KVCapabilities`, etc.) has a `to_dict()` that returns `{name: callable}`. `TurnContext.to_capabilities_dict()` merges all of these into a flat dict. This flat namespace means tool scripts reference capabilities by string name (`read_file`, `kv_get`), and name collisions are possible. More importantly, the `GrailTool.execute()` method (grail.py:133-138) filters capabilities by checking `if name in self._script.externals`, which means tool scripts must know the exact string names of every capability they use. There's no type safety or discovery mechanism.

### 6.2 Event type hierarchy is flat and stringly-typed

All events inherit from `Event(BaseModel)` with `event_type: str`. The event type strings are defined in `EventType(StrEnum)`. This means the type system can't distinguish events at the Python level — you need runtime `isinstance()` checks. The `SubscriptionPattern.matches()` method checks event attributes via `getattr()` (e.g., `getattr(event, "from_agent", None)`), which is fragile and untyped.

A better design would use the Python type hierarchy directly for dispatch and pattern matching, rather than string-based event_type checking.

### 6.3 `propose_changes` has unclear semantics

`CommunicationCapabilities.propose_changes()` collects "changed files" by listing ALL workspace files excluding `_bundle/`. But it doesn't track what actually changed — it just lists everything. The resulting `RewriteProposalEvent` includes this full file list as "changed files", which is misleading. There's also no mechanism for the human to see diffs, just file names.

### 6.4 Externals version is checked but never enforced

`EXTERNALS_VERSION` mismatch only logs a warning (workspace.py:243-249). A bundle requiring `externals_version: 999` will still load and execute, potentially failing at runtime when it tries to use a capability that doesn't exist. The version check should either be enforced (refuse to load incompatible bundles) or the warning should be more prominent.

---

## 7. Configuration System

### 7.1 Defaults merging is shallow

`load_config()` in config.py:298 does `merged = {**defaults, **expand_env_vars(user_data)}`. This is a shallow merge — if `defaults.yaml` has `languages: {python: {...}, markdown: {...}}` and the user's `remora.yaml` has `languages: {python: {extensions: [".py", ".pyi"]}}`, the user config completely replaces all language definitions. The user loses markdown and toml. This should be a deep merge (like `_merge_dicts` in workspace.py), at least for dict-typed fields.

### 7.2 Config field defaults create a "broken install" trap

The refactor guide says Config field defaults should be empty (e.g., `model_default: str = ""`, `max_turns: int = 0`), since `load_config()` fills them from `defaults.yaml`. But if someone constructs `Config()` directly (as tests do), they get an unusable config with `model_default=""` and `max_turns=0`. The `BundleConfig.max_turns` validator at line 121 clamps to `max(1, value)`, so `max_turns=0` becomes `max_turns=1`, which silently changes behavior.

The original `BundleConfig` validator at line 119-122 converts `max_turns=0` to `max_turns=1` via `max(1, value)`. But the `Config.max_turns` has no such validator — so `Config.max_turns=0` passes through, and it's only the bundle config that clamps. If `Config.max_turns` is used directly somewhere (it's used as a fallback in prompt builder), 0 would mean "no turns," which is probably not intended.

### 7.3 `BundleConfig` validators have side effects

`BundleConfig._validate_max_turns` silently clamps `max_turns` to `max(1, value)`. This means `max_turns: 0` in a bundle.yaml becomes 1 without warning. Silent coercion in validators is a foot-gun — it should either reject invalid values or log the coercion.

### 7.4 `expand_env_vars` doesn't handle nested tuple/list correctly

`expand_env_vars` handles `dict`, `list`, `tuple`, and `str`. But pydantic models use `tuple` for frozen sequences like `discovery_paths`. The user's YAML will produce `list` (since YAML lists become Python lists), which pydantic then coerces to `tuple`. But `expand_env_vars` runs BEFORE pydantic validation, so it correctly handles lists. This is fine but fragile — if the coercion order changes, env vars in tuple fields would break.

---

## 8. Discovery & Reconciliation

### 8.1 `discover()` has a global LRU cache that ignores config

As noted in section 2.2, `_get_language_registry()` is `@lru_cache(maxsize=1)` and creates a registry from defaults only. Similarly, `_get_parser()` and `_load_query()` are cached by language name/query file respectively. These caches are never invalidated. If the user changes a `.scm` query file while remora is running, the cached query will be stale until process restart.

For the reconciler use case (which passes `query_paths` and `language_map`), the cache is partially bypassed because `_resolve_query_file()` checks custom paths first. But the parser and query caches are still keyed by name, not by config.

### 8.2 Reconciler does double-duty as subscription manager

`_register_subscriptions()` (reconciler.py:345-399) is 55 lines of subscription orchestration logic that belongs in a dedicated subscription manager, not in the file reconciler. The reconciler should discover nodes and emit events; subscription wiring should be handled by a separate component that listens to those events.

### 8.3 Bundle provisioning in reconciler is synchronous bottleneck

During `reconcile_cycle()`, every changed file triggers `_provision_bundle()` which reads and writes workspace files. For a large project with hundreds of files changing (e.g., git checkout), this serializes all bundle provisioning. The provisioning could be batched or deferred.

### 8.4 `_file_lock` returns a Lock but is used as a context manager

`_file_lock()` (reconciler.py:304-309) returns an `asyncio.Lock` but is used as `async with self._file_lock(file_path, generation)`. This works because `asyncio.Lock` supports `async with`, but the method signature (`-> asyncio.Lock`) suggests it returns a lock rather than a context manager. The naming/signature is misleading.

### 8.5 Directory hierarchy computation is O(n * depth)

`DirectoryManager.compute_hierarchy()` iterates all file paths and walks up the directory tree for each. For deeply nested projects, this is O(n * d) where d is max depth. This is unlikely to be a bottleneck in practice, but the algorithm could be simplified with a trie-based approach.

---

## 9. Prompt & Template System

### 9.1 Template interpolation is fragile

`PromptBuilder._interpolate()` does simple `str.replace()` with `{var}` patterns. This means if a template contains literal `{text}` that isn't a variable, it won't be replaced (which is good). But if a variable VALUE contains `{other_var}`, those won't be expanded (no recursive interpolation). More dangerously, if `{source}` contains `{node_name}`, the replacement order matters — if `{source}` is replaced first, the literal `{node_name}` in the source code could be replaced by the actual node name in a second pass if node_name happens to be in the dict. Since `dict` iteration order is insertion order in Python 3.7+, and `_build_template_vars` puts `source` after `node_name`, the source is replaced first, so any `{node_name}` in source code would NOT be double-replaced. But this ordering dependency is fragile.

**Fix:** Use a regex-based single-pass replacement, or escape braces in variable values.

### 9.2 `build_system_prompt` and `build_user_prompt` have asymmetric designs

`build_system_prompt()` returns a tuple `(str, str, int)` — prompt, model, max_turns. This is a poor API — it conflates prompt construction with model selection. The caller (`turn_executor.py`) must destructure this tuple. Model selection should be a separate method or a dataclass return type.

`build_user_prompt()` returns just a string but takes `bundle_config` and `companion_context` as keyword args that the caller must remember to pass. The companion context is also injected into the system prompt in `turn_executor.py:98-100`, creating two places where companion context is handled.

### 9.3 Companion context is assembled in the wrong place

`AgentWorkspace.build_companion_context()` (workspace.py:106-163) is 57 lines of prompt construction logic living in the workspace layer. The workspace should provide raw data (reflections, chat_index, links); the prompt builder should format it. Currently, the workspace returns formatted markdown that the turn executor appends to the system prompt AND passes to the user prompt template.

### 9.4 The `system` template in defaults.yaml is never used

`defaults.yaml` defines `prompt_templates.system`, but `PromptBuilder.build_system_prompt()` uses `bundle_config.system_prompt` (from the bundle's `bundle.yaml`), not the default template. The default system template is dead config.

---

## 10. Search Integration

### 10.1 Search is properly optional — good

The refactor correctly made search lazily optional. `SearchServiceProtocol` is a clean protocol in `core/search.py`, `SearchService` is the implementation, and all callers check `if self._search_service is None or not self._search_service.available`. The `pyproject.toml` has `search` as an optional dependency group.

### 10.2 SearchService has duplicated result mapping

`search()` and `find_similar()` in `search.py` both have identical 10-field result mapping blocks (lines 160-174 and 195-209). This should be a `_map_result()` helper.

### 10.3 `SearchService.initialize()` swallows connection failures silently

If the remote embeddy server is unreachable, `initialize()` catches all exceptions (line 78) and sets `self._available = False`. This means search silently degrades. While graceful degradation is good, there should be a way for the user to know search failed at startup — a health check endpoint or startup banner.

### 10.4 `collection_for_file` duplicates `SearchConfig.collection_map`

`SearchService.collection_for_file()` (line 271-273) could be a method on `SearchConfig` itself, since it only uses config fields. Moving it there would reduce `SearchService`'s responsibilities.

---

## 11. Web & LSP Surfaces

### 11.1 CSRF protection is origin-based only

`CSRFMiddleware` checks if the `Origin` header is localhost. This is better than nothing but doesn't protect against CSRF from other local services. A token-based approach would be more robust. Low priority for a development tool, but worth noting.

### 11.2 Global mutable state in `web/server.py`

`_INDEX_HTML: str | None = None` is a module-level global that's lazily populated. This is fine for a single-process server but would be a problem if the module were ever imported in tests that need isolation. Use a class attribute or request-scoped caching instead.

### 11.3 LSP server has good test abstraction

The `RemoraLSPHandlers` dataclass exposing handler callables for unit testing (lsp/server.py:71-83) is a smart pattern. This allows testing LSP handlers without spinning up a transport. Good work.

### 11.4 LSP `get_stores()` has a lazy-init race

`create_lsp_server()` defines an inner `get_stores()` async function that lazily opens a DB connection. If two LSP requests arrive simultaneously, they could both try to open the database concurrently. The `stores` dict is checked without a lock. This probably doesn't matter in practice (LSP servers are single-threaded), but it's technically unsafe.

### 11.5 WebDeps uses mutable per-IP rate limiters without bounds

`_get_chat_limiter()` (deps.py:42-48) creates a new `SlidingWindowRateLimiter` per IP address and stores it in `deps.chat_limiters`. This dict is never cleaned up. A slow DoS from many IPs would grow this dict unboundedly. Add a max-size or LRU eviction.

---

## 12. Testing

### 12.1 Good test breadth

50 test files covering unit and integration scenarios is solid. The test factories (`make_node`, `write_bundle_templates`) and shared conftest fixtures are clean.

### 12.2 Missing areas

- **No tests for config merging behavior.** The shallow merge issue (section 7.1) would be caught by a test that provides partial `languages` override and checks the result.
- **No concurrency stress tests.** The race conditions in `CairnWorkspaceService.get_agent_workspace()` and the unbounded EventBus tasks are not exercised.
- **No test for the full prompt construction pipeline.** Individual pieces are tested, but there's no end-to-end test that feeds a Node + Event + BundleConfig through the full prompt builder and validates the complete output.
- **`test_refactor_naming.py` is a meta-test.** It verifies naming conventions rather than behavior. This is fine as a regression guard but shouldn't replace behavioral tests.

### 12.3 Test fixture creates real databases

The `db` fixture opens a real SQLite database in `tmp_path`. This is correct for integration tests but slow for unit tests that only need to test in-memory logic. Consider adding an in-memory `:memory:` fixture for pure unit tests.

---

## 13. Code Style & Hygiene

### 13.1 `__all__` exports are inconsistent

Some modules export internal helpers in `__all__` (e.g., `turn_executor.py:334` exports `_turn_logger` which is a private function). Others omit important public types. The `__all__` lists should only export public API.

### 13.2 `actor.py` re-exports unrelated types

`actor.py:122-130` re-exports `Outbox`, `OutboxObserver`, `Trigger`, `TriggerPolicy`, `PromptBuilder`, and `AgentTurnExecutor` from its `__all__`. The `Actor` module shouldn't be the canonical export point for all these types — each module should export its own types.

### 13.3 Inconsistent use of `from __future__ import annotations`

All source files use it (good), but the pattern of mixing string annotations with runtime types is inconsistent. Some TYPE_CHECKING blocks are used (`externals.py:26-28`, `web/server.py:26-28`), others import types directly at runtime.

### 13.4 Module-level functions after `__all__`

`workspace.py` defines `_merge_dicts` and `_bundle_template_fingerprint` AFTER the `__all__` declaration (lines 313-345). These are private helpers that should be above `__all__` or the `__all__` should be at the end of the file. The inconsistency makes it look like these functions were added as an afterthought.

### 13.5 `factories.py` has a missing blank line

`make_node` at line 34 flows directly into `write_file` at line 35 with no blank line between function definitions. PEP 8 requires two blank lines between top-level definitions.

---

## 14. Dependency Management

### 14.1 All core dependencies are unpinned upper bounds

`pyproject.toml` uses `>=` for all dependencies: `aiosqlite>=0.20`, `pydantic>=2.0`, etc. This is correct for a library but risky for an application. A breaking change in `pydantic>=3.0` (if it ever ships) would break the build. Consider adding upper bounds for critical dependencies.

### 14.2 Internal dependencies use git tags

`structured-agents`, `cairn`, `grail`, `fsdantic`, and `embeddy` are all sourced from git repositories. This means builds are not reproducible unless `uv.lock` is committed. If these repos are rebased or tags are moved, builds break silently. Either vendor these or publish them to a private index.

### 14.3 `tree-sitter-python` is a hard dependency but other tree-sitter grammars are too

`pyproject.toml` lists `tree-sitter-python>=0.25.0`, `tree-sitter-markdown>=0.5.1`, and `tree-sitter-toml>=0.7.0` as required dependencies. But the refactor was supposed to make languages config-driven. If languages are truly config-driven, the grammar packages should be optional dependencies grouped by language, not hard requirements. A user who only wants Python support shouldn't need `tree-sitter-toml`.

### 14.4 `fsdantic` is an unlisted dependency

`workspace.py` imports `from fsdantic import FileNotFoundError as FsdFileNotFoundError` and `from fsdantic import ViewQuery, Workspace`. But `fsdantic` doesn't appear in `pyproject.toml` dependencies — it's presumably a transitive dependency of `cairn`. This should be an explicit dependency.

---

