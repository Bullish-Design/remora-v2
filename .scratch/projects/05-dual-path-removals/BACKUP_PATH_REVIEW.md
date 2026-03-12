# Backup Path Review

## Executive Summary

This document identifies all "backup paths" in the remora-v2 library — architectural patterns where multiple code paths exist to accomplish the same task, with one path serving as a fallback or alternative when the primary path fails or is unavailable.

**Key Finding:** The primary backup path is the **FileReconciler's watchfiles → polling fallback**. This is the most significant dual-path architecture and should be removed to align with the fail-fast development philosophy.

Beyond this, several other patterns were identified that, while not traditional "backup paths," represent silent fallbacks or graceful degradation that may mask configuration or integration problems during development.

---

## 1. FileReconciler: watchfiles → Polling Fallback

**Location:** `src/remora/code/reconciler.py:76-133`

### The Dual Path

```python
async def run_forever(self, *, poll_interval_s: float = 1.0) -> None:
    self._running = True
    try:
        if self._watch_mode:
            try:
                await self._run_watching()
            except ImportError:
                logger.info("watchfiles unavailable, falling back to polling mode")
                await self._run_polling(poll_interval_s)
        else:
            await self._run_polling(poll_interval_s)
    finally:
        self._running = False
```

### How It Works

| Path | Trigger | Implementation |
|------|---------|----------------|
| **Primary** | Filesystem events via `watchfiles` library | `_run_watching()` — receives real-time OS-level file change events |
| **Fallback** | 1-second polling loop | `_run_polling()` — calls `reconcile_cycle()` on a fixed interval |

### Activation Conditions

1. `watchfiles` not installed (ImportError)
2. `_watch_mode = False` (configurable flag, currently always True)
3. No valid paths to watch (empty `watch_paths` list)

### Additional Dual Path Within `_run_watching()`

Even within the watch mode, there's another fallback:

```python
async def _run_watching(self) -> None:
    # ...
    watch_paths = [str(path) for path in paths_to_watch if path.exists()]
    if not watch_paths:
        await self._run_polling(1.0)  # <-- Falls back to polling if no paths
        return
```

### Recommendation: REMOVE

**Rationale:**
- During development, if `watchfiles` is not installed, this should be a hard error — not a silent fallback to a different behavior.
- Polling has different latency characteristics (1-second delay vs. instant), making timing-dependent bugs harder to reproduce.
- The dual path doubles the testing surface — bugs may appear in one mode but not the other.

**Proposed Change:**
```python
async def run_forever(self) -> None:
    """Run filesystem watching. Raises ImportError if watchfiles unavailable."""
    import watchfiles  # Fail fast if not installed
    self._running = True
    try:
        await self._run_watching()
    finally:
        self._running = False
```

If no paths exist to watch, this should likely be a configuration error or no-op (empty project), not a silent fallback.

---

## 2. ContentChangedEvent Handler + File Watching

**Location:** `src/remora/code/reconciler.py:94-96, 264-273`

### The Dual Path

The reconciler has **two independent mechanisms** for detecting file changes:

1. **Filesystem watching** (`watchfiles` or polling)
2. **Event-driven reconciliation** via `ContentChangedEvent`

```python
async def start(self, event_bus: EventBus) -> None:
    """Subscribe to content change events for immediate reconciliation."""
    event_bus.subscribe(ContentChangedEvent, self._on_content_changed)

async def _on_content_changed(self, event: ContentChangedEvent) -> None:
    """Immediately reconcile a file reported changed by upstream systems."""
    file_path = event.path
    p = Path(file_path)
    if p.exists() and p.is_file():
        try:
            mtime = p.stat().st_mtime_ns
            await self._reconcile_file(str(p), mtime)
        except Exception:
            logger.exception("Event-triggered reconcile failed for %s", file_path)
```

### How They Interact

- `watchfiles` detects file changes at the OS level
- `ContentChangedEvent` is emitted by external systems (e.g., LSP server, manual triggers)
- Both ultimately call `_reconcile_file()`

### Potential Issue

If `watchfiles` and `ContentChangedEvent` both fire for the same file change, `_reconcile_file()` could be called twice for the same change. The current code doesn't deduplicate by checking mtimes or using a debounce mechanism.

### Recommendation: EVALUATE

This is less clearly a "backup path" and more of a "dual input" architecture. However:

- During development, having two paths to trigger reconciliation makes it harder to trace which mechanism actually fired.
- If the goal is event-driven architecture (R20), the filesystem watching becomes redundant once `ContentChangedEvent` is reliable.
- Consider: Should there be ONE canonical source of change events? If so, which one?

**Questions to resolve:**
1. Is `ContentChangedEvent` meant to supplement or replace filesystem watching?
2. Should the reconciler deduplicate calls to `_reconcile_file()` within a time window?

---

## 3. AgentWorkspace: Agent → Stable Workspace Fallback

**Location:** `src/remora/core/workspace.py:27-38`

### The Dual Path

```python
async def read(self, path: str) -> str:
    """Read a file from the agent workspace, falling back to stable if needed."""
    async with self._lock:
        try:
            content = await self._workspace.files.read(path)
        except (FileNotFoundError, FsdFileNotFoundError):
            if self._stable is None:
                raise
            content = await self._stable.files.read(path)
```

### How It Works

| Path | Location | Purpose |
|------|----------|---------|
| **Primary** | Agent workspace (`_workspace`) | Per-agent sandboxed files |
| **Fallback** | Stable workspace (`_stable`) | Shared read-only baseline files |

Every read operation checks agent workspace first, then stable workspace.

### Similar Pattern in Other Methods

- `exists()` — checks both workspaces
- `list_dir()` — merges entries from both
- `list_all_paths()` — merges paths from both

### Is This a Backup Path?

**This is intentional architecture**, not a fallback for missing dependencies. The stable workspace provides:
- Read-only baseline files (bundle templates, system tools)
- Shared configuration
- Source code for reference

However, it does create implicit behavior where a file "exists" from two possible sources, which can be confusing during debugging.

### Recommendation: KEEP BUT DOCUMENT

This is a **valid architectural pattern** for workspace composition, not a fault-tolerance backup. However:

1. Add explicit documentation to each method explaining the fallback semantics
2. Consider adding a `read_strict()` method that doesn't fall back (for debugging)
3. Log at DEBUG level when falling back to stable workspace

---

## 4. Discovery: Language Resolution Fallback Chain

**Location:** `src/remora/code/discovery.py:61-68`

### The Dual Path

```python
language_name = effective_language_map.get(ext)
plugin = None
if language_name is not None:
    plugin = language_registry.get_by_name(language_name)
if plugin is None:
    plugin = language_registry.get_by_extension(ext)
if plugin is None:
    continue  # Skip file silently
```

### How It Works

| Path | Condition | Action |
|------|-----------|--------|
| **Primary** | Extension in `language_map` config | Use configured language |
| **Fallback 1** | Extension matches registry default | Use registry-provided language |
| **Fallback 2** | No match found | Skip file silently |

### Issue

If a file extension is typoed in `language_map` (e.g., `.py` → `.python`), the fallback to `get_by_extension()` may silently "fix" it by finding Python anyway. This masks configuration errors.

### Recommendation: SIMPLIFY

Remove the dual resolution path:

```python
language_name = effective_language_map.get(ext)
if language_name is None:
    continue  # Not configured for this extension
plugin = language_registry.get_by_name(language_name)
if plugin is None:
    raise ValueError(f"Configured language '{language_name}' not found for extension '{ext}'")
```

This makes misconfiguration immediately visible.

---

## 5. Exception Handlers That Suppress Errors

Several exception handlers catch broad exceptions and log them, allowing the system to continue. While appropriate for production, during development these can mask root causes.

### 5.1 Reconciler Watch Batch Failures

**Location:** `src/remora/code/reconciler.py:123-124`

```python
except Exception:  # noqa: BLE001 - isolate one watch batch failure
    logger.exception("Watch-triggered reconcile failed")
```

**Impact:** If a file parse fails during watch-triggered reconciliation, the error is logged but the reconciler continues. The failing file's nodes won't be updated, but there's no indication to the user.

### 5.2 Reconciler Polling Failures

**Location:** `src/remora/code/reconciler.py:131-132`

```python
except Exception:  # noqa: BLE001 - keep loop alive
    logger.exception("Reconcile cycle failed, will retry next cycle")
```

**Impact:** Same as above but for polling mode.

### 5.3 Runner Turn Failures

**Location:** `src/remora/core/runner.py:186-196`

```python
except Exception as exc:  # noqa: BLE001 - boundary should never crash loop
    logger.exception("Agent turn failed for %s", node_id)
    await self._agent_store.transition_status(node_id, NodeStatus.ERROR)
    # ... error event emission
```

**Impact:** Agent failures are captured as ERROR status and error events. This is appropriate, but during development, you might want the entire process to crash to surface issues.

### 5.4 Grail Tool Loading Failures

**Location:** `src/remora/core/grail.py:127-128`

```python
except Exception as exc:  # noqa: BLE001 - skip invalid tool and continue
    logger.warning("Failed to load tool %s: %s", filename, exc)
```

**Impact:** Invalid tool scripts are skipped with a warning. The agent runs without that tool.

### Recommendation: ENVIRONMENT-AWARE ERROR HANDLING

Add a `--fail-fast` mode or `REMORA_DEV=1` environment variable that:

1. Raises exceptions instead of catching them broadly
2. Exits on first error instead of continuing
3. Logs at ERROR level instead of WARNING

```python
# In config.py
fail_fast: bool = Field(default=False, description="Exit on first error during development")

# In runner.py
except Exception as exc:
    if self._config.fail_fast:
        raise
    logger.exception(...)
```

---

## 6. Config: Env Var Expansion with Default

**Location:** `src/remora/core/config.py:99-108`

### The Pattern

```python
def _expand_string(value: str) -> str:
    """Expand ${VAR:-default} shell-style values."""
    def replace(match: re.Match[str]) -> str:
        var_name = match.group(1)
        default = match.group(2) or ""
        env_value = os.getenv(var_name)
        return env_value if env_value is not None else default
    return _ENV_VAR_PATTERN.sub(replace, value)
```

### How It Works

Config values like `${MODEL_API_KEY:-sk-test}` will:
1. Use `MODEL_API_KEY` env var if set
2. Fall back to `sk-test` if not set

### Is This a Backup Path?

This is a **valid configuration pattern** for deployment flexibility. The default is explicit and intentional.

### Recommendation: KEEP

This is not a silent fallback — the default is explicitly declared in config. No changes needed.

---

## 7. LRU Caches with Stale Data Potential

**Location:** `src/remora/code/discovery.py:76-94`

### The Pattern

```python
@lru_cache(maxsize=16)
def _get_registry_plugin(name: str) -> LanguagePlugin: ...

@lru_cache(maxsize=16)
def _get_parser(language: str) -> Parser: ...

@lru_cache(maxsize=64)
def _load_query(language: str, query_file: str) -> Query: ...
```

### Issue

If a `.scm` query file is modified on disk, the cached query won't be invalidated until:
1. The process restarts
2. The cache fills and evicts the entry
3. Someone clears the cache manually

During development, query file changes won't take effect immediately.

### Recommendation: ADD CACHE INVALIDATION

```python
def clear_query_cache() -> None:
    _load_query.cache_clear()

# Or use file modification time as part of cache key
@lru_cache(maxsize=64)
def _load_query(language: str, query_file: str, mtime: float) -> Query: ...
```

---

## 8. Subscription Cache Rebuild on Demand

**Location:** `src/remora/core/events/subscriptions.py:109-112`

### The Pattern

```python
async def get_matching_agents(self, event: Event) -> list[str]:
    """Resolve agent IDs whose patterns match the supplied event."""
    if self._cache is None:
        await self._rebuild_cache()
```

### How It Works

The subscription cache is lazily rebuilt when:
1. First accessed after initialization
2. Any subscription is registered/unregistered (cache is set to `None`)

### Is This a Backup Path?

This is **lazy initialization**, not a fallback. The cache is invalidated and rebuilt on demand.

### Recommendation: NO CHANGE

This is a valid optimization pattern.

---

## Summary Table

| # | Location | Pattern Type | Severity | Recommendation |
|---|----------|--------------|----------|----------------|
| 1 | `reconciler.py:76-133` | watchfiles → polling fallback | **HIGH** | **REMOVE** — fail fast if watchfiles unavailable |
| 2 | `reconciler.py:94-96, 264-273` | Dual change detection (watch + event) | MEDIUM | Evaluate if both are needed |
| 3 | `workspace.py:27-38` | Agent → stable workspace fallback | LOW | Keep, but document better |
| 4 | `discovery.py:61-68` | Language resolution fallback chain | MEDIUM | Simplify to single path, fail on config error |
| 5 | Multiple | Broad exception handlers | MEDIUM | Add `--fail-fast` mode |
| 6 | `config.py:99-108` | Env var default expansion | N/A | Keep — intentional pattern |
| 7 | `discovery.py:76-94` | LRU cache without invalidation | LOW | Add cache clearing mechanism |
| 8 | `subscriptions.py:109-112` | Lazy cache rebuild | N/A | Keep — valid pattern |

---

## Recommended Actions

### Immediate (Do Now)

1. **Remove watchfiles → polling fallback** in `FileReconciler.run_forever()`
   - Make `watchfiles` import failure a hard error
   - Remove `_run_polling()` method (or keep for explicit opt-in only)
   - Remove `_watch_mode` flag

### Near-Term (Plan)

2. **Evaluate ContentChangedEvent + watchfiles dual path**
   - Decide: one source of truth or keep both?
   - If both, add deduplication logic

3. **Simplify language resolution in discovery**
   - Single resolution path via config
   - Fail fast on unknown languages

4. **Add `--fail-fast` development mode**
   - Config flag or env var
   - Disables broad exception catching

### Future Consideration

5. **Add debug visibility to workspace fallback**
   - Log when falling back to stable workspace
   - Add `read_strict()` method

6. **Add query cache invalidation**
   - Clear on file change or include mtime in key
