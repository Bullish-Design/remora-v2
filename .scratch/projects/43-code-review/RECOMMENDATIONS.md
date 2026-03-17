# Remora v2 — Recommendations & Improvement Plan

**Date:** 2026-03-17
**Companion to:** `CODE_REVIEW.md`
**Principle:** No backwards compatibility. Optimize for the cleanest, most elegant architecture possible.

---

## Table of Contents

1. [P0: Fix Correctness Bugs](#1-p0-fix-correctness-bugs) — Race conditions, lock bugs, state machine issues
2. [P0: Fix the Config Merge](#2-p0-fix-the-config-merge) — Deep merge for defaults + user config
3. [P1: Split the God Config](#3-p1-split-the-god-config) — Decompose Config into focused types
4. [P1: Unify Transaction Management](#4-p1-unify-transaction-management) — Single batch context for NodeStore + EventStore
5. [P1: Move Companion Context to Prompt Builder](#5-p1-move-companion-context-to-prompt-builder) — Separate data retrieval from formatting
6. [P1: Enforce Externals Version](#6-p1-enforce-externals-version) — Fail loudly on incompatible bundles
7. [P2: Eliminate Discovery Cache Staleness](#7-p2-eliminate-discovery-cache-staleness) — Config-aware caching or no caching
8. [P2: Extract Subscription Manager](#8-p2-extract-subscription-manager) — Separate subscription wiring from reconciliation
9. [P2: Rethink the Prompt Builder Return Types](#9-p2-rethink-the-prompt-builder-return-types) — Structured return types, not tuples
10. [P2: Make Tree-Sitter Grammars Optional](#10-p2-make-tree-sitter-grammars-optional) — Config-driven deps
11. [P3: Template Interpolation Safety](#11-p3-template-interpolation-safety) — Single-pass regex replacement
12. [P3: Bounded Collections Everywhere](#12-p3-bounded-collections-everywhere) — Rate limiter eviction, event bus backpressure
13. [P3: Clean Up Dead Code and Stale Patterns](#13-p3-clean-up-dead-code-and-stale-patterns) — Remove leftovers from pre-refactor
14. [Future: Database Migrations](#14-future-database-migrations) — Schema evolution strategy
15. [Future: Structured Error Reporting](#15-future-structured-error-reporting) — Surface errors to web/LSP

---

## 1. P0: Fix Correctness Bugs

### 1a. CairnWorkspaceService cache race

Move cache writes inside the lock in `get_agent_workspace()`:

```python
async def get_agent_workspace(self, node_id: str) -> AgentWorkspace:
    async with self._lock:
        cached = self._agent_workspaces.get(node_id)
        if cached is not None:
            if self._metrics is not None:
                self._metrics.workspace_cache_hits += 1
            return cached
        workspace_path = self._workspace_path(node_id)
        raw_workspace = await cairn_wm.open_workspace(str(workspace_path))
        self._manager.track_workspace(raw_workspace)
        if self._metrics is not None:
            self._metrics.workspace_provisions_total += 1
        agent_workspace = AgentWorkspace(raw_workspace, node_id)
        self._raw_agent_workspaces[node_id] = raw_workspace
        self._agent_workspaces[node_id] = agent_workspace
        return agent_workspace
```

### 1b. Fix `request_human_input` state machine

Remove the `finally` block that transitions to RUNNING. Let the turn executor's error handler manage the final state:

```python
async def request_human_input(self, question: str, options: list[str] | None = None) -> str:
    request_id = str(uuid.uuid4())
    future = self._event_store.create_response_future(request_id)
    await self._node_store.transition_status(self._node_id, NodeStatus.AWAITING_INPUT)
    await self._emit(HumanInputRequestEvent(...))
    try:
        result = await asyncio.wait_for(future, timeout=self._human_input_timeout_s)
        await self._node_store.transition_status(self._node_id, NodeStatus.RUNNING)
        return result
    except TimeoutError:
        self._event_store.discard_response_future(request_id)
        await self._node_store.transition_status(self._node_id, NodeStatus.RUNNING)
        raise
```

### 1c. Remove AgentWorkspace global lock

Either remove the lock entirely (if Cairn is already thread-safe) or replace with separate locks for files and KV subsystems.

---

## 2. P0: Fix the Config Merge

Replace the shallow merge in `load_config()` with a deep merge:

```python
def load_config(path: Path | None = None) -> Config:
    from remora.defaults import load_defaults
    defaults = load_defaults()
    config_path = path if path is not None else _find_config_file()
    if config_path is not None:
        user_data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    else:
        user_data = {}
    merged = _deep_merge(defaults, expand_env_vars(user_data))
    return Config(**merged)

def _deep_merge(base: dict, overlay: dict) -> dict:
    result = dict(base)
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
```

Note: `_merge_dicts` already exists in workspace.py. Hoist it to a shared utility.

---

## 3. P1: Split the God Config

Decompose `Config` into focused types:

```python
class ProjectConfig(BaseModel):
    """Paths and discovery settings."""
    project_path: str = "."
    discovery_paths: tuple[str, ...] = ("src/",)
    discovery_languages: tuple[str, ...] | None = None
    workspace_ignore_patterns: tuple[str, ...] = (...)

class RuntimeConfig(BaseModel):
    """Execution engine settings."""
    max_concurrency: int = 4
    max_trigger_depth: int = 5
    trigger_cooldown_ms: int = 1000
    human_input_timeout_s: float = 300.0
    actor_idle_timeout_s: float = 300.0
    send_message_rate_limit: int = 10
    send_message_rate_window_s: float = 1.0
    search_content_max_matches: int = 1000
    broadcast_max_targets: int = 50

class InfraConfig(BaseModel):
    """Infrastructure settings."""
    model_base_url: str = "http://localhost:8000/v1"
    model_api_key: str = ""
    timeout_s: float = 300.0
    workspace_root: str = ".remora"

class BehaviorConfig(BaseModel):
    """Defaults-layer config (from defaults.yaml, overridable in remora.yaml)."""
    model_default: str = "Qwen/Qwen3-4B"
    max_turns: int = 8
    bundle_search_paths: tuple[str, ...] = ("bundles/", "@default")
    query_search_paths: tuple[str, ...] = ("queries/", "@default")
    bundle_overlays: dict[str, str] = Field(default_factory=dict)
    bundle_rules: tuple[BundleOverlayRule, ...] = ()
    languages: dict[str, dict[str, Any]] = Field(default_factory=dict)
    language_map: dict[str, str] = Field(default_factory=dict)
    prompt_templates: dict[str, str] = Field(default_factory=dict)
    externals_version: int = 1

class Config(BaseSettings):
    """Top-level composition."""
    project: ProjectConfig = Field(default_factory=ProjectConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    infra: InfraConfig = Field(default_factory=InfraConfig)
    behavior: BehaviorConfig = Field(default_factory=BehaviorConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    virtual_agents: tuple[VirtualAgentConfig, ...] = ()
```

This changes every config access site, but since we don't care about backwards compatibility, it's worth it for clarity.

---

## 4. P1: Unify Transaction Management

Replace separate `NodeStore.batch()` / `EventStore.batch()` with a shared `TransactionContext`:

```python
class TransactionContext:
    def __init__(self, db: aiosqlite.Connection):
        self._db = db
        self._depth = 0
        self._deferred_events: list[Event] = []

    @asynccontextmanager
    async def batch(self):
        self._depth += 1
        try:
            yield
        except BaseException:
            if self._depth == 1:
                await self._db.rollback()
                self._deferred_events.clear()
            raise
        finally:
            self._depth -= 1
            if self._depth == 0:
                await self._db.commit()
                # fan out deferred events
                for event in self._deferred_events:
                    await self._event_bus.emit(event)
                    await self._dispatcher.dispatch(event)
                self._deferred_events.clear()
```

Both `NodeStore` and `EventStore` share this context. The reconciler uses a single `async with tx.batch():` instead of nested `node_store.batch()` + `event_store.batch()`.

---

## 5. P1: Move Companion Context to Prompt Builder

1. Add a `CompanionData` dataclass:

```python
@dataclass
class CompanionData:
    reflections: list[dict] = field(default_factory=list)
    chat_index: list[dict] = field(default_factory=list)
    links: list[dict] = field(default_factory=list)
```

2. Add `AgentWorkspace.get_companion_data() -> CompanionData` that returns raw data.
3. Move the markdown formatting from `build_companion_context()` into `PromptBuilder`.
4. Delete `AgentWorkspace.build_companion_context()`.

---

## 6. P1: Enforce Externals Version

Change the warning to an error:

```python
if config.externals_version is not None and config.externals_version > EXTERNALS_VERSION:
    raise IncompatibleBundleError(
        f"Bundle for {node_id} requires externals v{config.externals_version} "
        f"but core provides v{EXTERNALS_VERSION}"
    )
```

Agents with incompatible bundles should be skipped with an error event, not silently loaded with wrong capabilities.

---

## 7. P2: Eliminate Discovery Cache Staleness

Remove the `@lru_cache` decorators from `discovery.py`. Instead, pass a `LanguageRegistry` instance through from the caller:

1. `FileReconciler.__init__` already has access to the language registry (via services).
2. Thread it through `_do_reconcile_file` → `discover()` → `_parse_file()`.
3. Remove `_get_language_registry()`, `_get_parser()`, `_get_registry_plugin()` cached functions.
4. The `LanguageRegistry` can cache parsers internally if needed.

Also remove the stale `_DEFAULT_LANGUAGE_MAP` from `discovery.py`.

---

## 8. P2: Extract Subscription Manager

Create `code/subscriptions.py`:

```python
class SubscriptionManager:
    """Wires event subscriptions for nodes based on their type and config."""

    def __init__(self, event_store: EventStore, workspace_service: CairnWorkspaceService):
        self._event_store = event_store
        self._workspace_service = workspace_service

    async def register_for_node(self, node: Node, *, virtual_subscriptions=()) -> None:
        # Move all subscription logic from reconciler._register_subscriptions here
        ...
```

The reconciler calls `self._subscription_manager.register_for_node(node)` instead of managing subscriptions directly. This makes the reconciler focused on discovery and node lifecycle.

---

## 9. P2: Rethink the Prompt Builder Return Types

Replace the `tuple[str, str, int]` return with a structured type:

```python
@dataclass(frozen=True)
class TurnConfig:
    system_prompt: str
    model: str
    max_turns: int

class PromptBuilder:
    def build_turn_config(self, bundle_config: BundleConfig, trigger_event: Event | None) -> TurnConfig:
        ...
```

Also unify where companion context is injected — it should happen in one place (the prompt builder), not split between turn_executor and workspace.

---

## 10. P2: Make Tree-Sitter Grammars Optional

Move grammar packages to optional dependency groups:

```toml
[project.optional-dependencies]
python = ["tree-sitter-python>=0.25.0"]
markdown = ["tree-sitter-markdown>=0.5.1"]
toml = ["tree-sitter-toml>=0.7.0"]
all-languages = ["tree-sitter-python>=0.25.0", "tree-sitter-markdown>=0.5.1", "tree-sitter-toml>=0.7.0"]
```

`GenericLanguagePlugin.get_language()` already uses `importlib.import_module()` with a dynamic name, so it handles missing grammars gracefully. Add an `ImportError` catch that produces a clear message: "Language 'toml' requires tree-sitter-toml. Install with: pip install remora[toml]".

---

## 11. P3: Template Interpolation Safety

Replace the loop-based replacement with a single-pass regex:

```python
import re

@staticmethod
def _interpolate(template: str, variables: dict[str, str]) -> str:
    def replacer(match: re.Match) -> str:
        key = match.group(1)
        return variables.get(key, match.group(0))
    return re.sub(r"\{(\w+)\}", replacer, template)
```

This prevents any interaction between variable values and template patterns.

---

## 12. P3: Bounded Collections Everywhere

1. **Chat rate limiters:** Add LRU eviction to `WebDeps.chat_limiters`. Keep max 1000 entries, evict oldest on overflow.
2. **EventBus handlers:** Add a configurable concurrency limit to `_dispatch_handlers()`. Use `asyncio.Semaphore` to cap concurrent handler tasks.
3. **SlidingWindowRateLimiter timestamps:** Already bounded per-key by window, but the key dict itself can grow. Add max-keys eviction.

---

## 13. P3: Clean Up Dead Code and Stale Patterns

1. **Remove `_DEFAULT_LANGUAGE_MAP`** from `discovery.py:16-20`. It's dead code.
2. **Remove `system` template** from `defaults.yaml` or actually use it in `PromptBuilder`.
3. **Remove `_turn_logger`** from `turn_executor.py __all__`. It's a private function.
4. **Remove re-exports** from `actor.py __all__`. Each module exports its own types.
5. **Move `_merge_dicts`** from `workspace.py` to a shared utility module.
6. **Move `_bundle_template_fingerprint`** above `__all__` in workspace.py.
7. **Fix missing blank line** in `factories.py:34-35` between `make_node` and `write_file`.
8. **Add `fsdantic`** as an explicit dependency in `pyproject.toml`.

---

## 14. Future: Database Migrations

Add a simple migration system:

```python
MIGRATIONS = [
    (1, "CREATE TABLE IF NOT EXISTS nodes (...)"),
    (2, "ALTER TABLE nodes ADD COLUMN metadata TEXT DEFAULT '{}'"),
    # ...
]

async def apply_migrations(db: aiosqlite.Connection) -> None:
    await db.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER)")
    cursor = await db.execute("SELECT MAX(version) FROM schema_version")
    current = (await cursor.fetchone())[0] or 0
    for version, sql in MIGRATIONS:
        if version > current:
            await db.executescript(sql)
            await db.execute("INSERT INTO schema_version VALUES (?)", (version,))
    await db.commit()
```

This is minimal but sufficient for a pre-1.0 project. Replace `create_tables()` calls with `apply_migrations()`.

---

## 15. Future: Structured Error Reporting

Add an error/diagnostic event type and surface it through existing channels:

```python
class DiagnosticEvent(Event):
    event_type: str = EventType.DIAGNOSTIC
    severity: str  # "error", "warning", "info"
    source: str    # "bundle_validation", "tool_load", "search_init"
    node_id: str | None = None
    message: str
```

The web UI can subscribe to diagnostic events and show them in a status bar. The LSP can surface them as `window/showMessage` notifications.

---

