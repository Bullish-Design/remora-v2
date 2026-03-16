# Remora v2 — Step-by-Step Refactoring Guide

**Date**: 2026-03-16
**Purpose**: Complete refactoring guide for transforming the remora library into the cleanest, most elegant codebase possible. No backwards compatibility constraints.
**Source**: Validated findings from `CODE_REVIEW.md` and `RECOMMENDATIONS.md`, verified against every source file.

**IMPORTANT: NO SUBAGENTS** — NEVER use the Task tool. Do ALL work directly. No delegation. No exceptions. This is the highest-priority rule.

---

## Table of Contents

1. **Phase 0: Preparation** — Sync deps, run full test suite, establish baseline
2. **Phase 1: Correctness Fixes** — Class-level mutable state, batch() error handling, set_status removal
3. **Phase 2: Delete Dead Weight** — Actor delegation wrappers, compatibility shims, normalize_dir_id
4. **Phase 3: Type the Untyped** — SearchService Protocol, outbox typing, workspace typing, lifecycle typing
5. **Phase 4: Extract BundleConfig Pydantic Model** — Replace 62 lines of manual validation
6. **Phase 5: Decompose actor.py** — Split into outbox, trigger, prompt, turn_executor, actor modules
7. **Phase 6: Refactor web/server.py** — Extract closure soup into class-based handler groups
8. **Phase 7: Fix Event System Issues** — TurnDigestedEvent.tags shadow, CustomEvent payload nesting, bus.unsubscribe, store commits
9. **Phase 8: Decompose _materialize_directories** — Break 125-line method into focused helpers
10. **Phase 9: Performance Fixes** — N+1 queries, SSE polling, _latest_rewrite_proposal, broadcast
11. **Phase 10: Fix Encapsulation Violations** — Health endpoint _db access, OutboxObserver dispatch
12. **Phase 11: Clean Up Global State** — Grail caches, discovery LRU caches, file lock lifecycle
13. **Phase 12: Logging & Error Boundary Cleanup** — Demote hot-path logs, document error boundaries
14. **Phase 13: Minor Fixes & Polish** — SHA-1 replacement, rate limiter per-client, LSP port, naming consistency
15. **Phase 14: Test Suite Improvements** — Lifecycle tests, concurrency tests, fix whitebox tests
16. **Appendix A: Review Findings Validation** — Which review items were confirmed, adjusted, or dismissed

**IMPORTANT: NO SUBAGENTS** — NEVER use the Task tool. Do ALL work directly. No delegation. No exceptions.

---

## Phase 0: Preparation

Before touching any code, establish a green baseline.

### Step 0.1: Sync Dependencies

```bash
devenv shell -- uv sync --extra dev
```

### Step 0.2: Run Full Test Suite

```bash
devenv shell -- python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q
```

Record the output. Every test must pass. If any test fails, fix it before proceeding. This is your "before" snapshot.

### Step 0.3: Run Linter

```bash
devenv shell -- ruff check src/
```

Record any existing violations. You will not introduce new ones.

### Step 0.4: Initial Commit

Commit after each phase completes. Use descriptive commit messages like `refactor(core): fix TurnContext class-level mutable state`.

---

## Phase 1: Correctness Fixes

These are bugs or correctness hazards. Fix them first because later phases may depend on correct behavior.

### Step 1.1: Fix TurnContext Class-Level Mutable State

**File**: `src/remora/core/externals.py`
**Problem**: Line 30 declares `_send_message_timestamps` as a class variable. All TurnContext instances share the same dict, causing rate limit state to leak between agents and between tests.

**Action**:
1. Delete line 30 (`_send_message_timestamps: dict[str, deque[float]] = {}`)
2. Add to `__init__` (after `self._search_service = search_service`):
   ```python
   self._send_message_timestamps: dict[str, deque[float]] = {}
   ```
3. Update `_allow_send_message` — it already references `self._send_message_timestamps`, so no change needed there.

**Verify**: Run `devenv shell -- python -m pytest tests/unit/test_externals.py -v`

### Step 1.2: Fix batch() Context Manager Error Handling

**File**: `src/remora/core/graph.py`
**Problem**: Lines 39-48 — the `batch()` context manager commits even when an inner operation raises, persisting partial mutations.

**Action**: Replace the `batch` method (lines 39-48) with:

```python
@asynccontextmanager
async def batch(self):  # noqa: ANN201
    """Group multiple node mutations into a single commit."""
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
```

**Verify**: Run `devenv shell -- python -m pytest tests/unit/test_graph.py -v`. Add a test that verifies rollback on exception:

```python
async def test_batch_rolls_back_on_exception(node_store, sample_node):
    """Batch should not commit when an inner operation raises."""
    try:
        async with node_store.batch():
            await node_store.upsert_node(sample_node)
            raise ValueError("deliberate failure")
    except ValueError:
        pass
    result = await node_store.get_node(sample_node.node_id)
    assert result is None
```

### Step 1.3: Remove set_status from NodeStore

**File**: `src/remora/core/graph.py`
**Problem**: `set_status()` (lines 158-165) bypasses the state machine enforced by `transition_status()`. Any caller can silently corrupt node state.

**Action**:
1. Delete the entire `set_status` method (lines 158-165).
2. Search for all callers: `grep -rn "set_status" src/ tests/`
3. Replace each call with `transition_status()` or delete if it's a test that was testing `set_status` directly.

**Verify**: `devenv shell -- python -m pytest tests/unit/test_graph.py -v`

### Step 1.4: Commit

```bash
git add -A && git commit -m "fix(core): correctness fixes — TurnContext state, batch rollback, remove set_status"
```

---

## Phase 2: Delete Dead Weight

Remove code that exists only for backwards compatibility. We don't care about backwards compatibility.

### Step 2.1: Delete Actor Delegation Wrappers

**File**: `src/remora/core/actor.py`
**Problem**: Lines 854-936 contain ~80 lines of trivial delegation wrappers that forward calls to `AgentTurnExecutor` private methods. They violate encapsulation and add zero value.

**Action**:
1. Delete all these methods from the `Actor` class (lines 852-936):
   - `_start_agent_turn`
   - `_build_system_prompt`
   - `_prepare_turn_context`
   - `_run_kernel`
   - `_complete_agent_turn`
   - `_reset_agent_state`
   - `_build_prompt`
   - `_resolve_maybe_awaitable`
   - `_read_bundle_config`
   - `_turn_mode`
2. Keep `_execute_turn` (line 852) since it's called from `_run`.

### Step 2.2: Delete Actor Compatibility Property Shims

**File**: `src/remora/core/actor.py`
**Problem**: Lines 760-791 expose internal TriggerPolicy state via property shims (`_last_trigger_ms`, `_depths`, `_depth_timestamps`, `_trigger_checks`). These exist only because tests poke at Actor internals.

**Action**:
1. Delete all four property pairs (lines 760-791).
2. Also delete `_should_trigger` and `_cleanup_depth_state` wrapper methods (lines 844-850) — they're trivial forwards.

### Step 2.3: Update Tests That Used Deleted APIs

**Files**: `tests/unit/test_actor.py`, `tests/unit/test_runner.py`

**Action**: Search for all references to the deleted APIs:
```bash
grep -n "actor\._depths\|actor\._last_trigger_ms\|actor\._depth_timestamps\|actor\._trigger_checks\|actor\._start_agent_turn\|actor\._prepare_turn_context\|actor\._run_kernel\|actor\._complete_agent_turn\|actor\._reset_agent_state\|actor\._build_system_prompt\|actor\._build_prompt\|actor\._turn_mode\|actor\._read_bundle_config\|actor\._resolve_maybe_awaitable" tests/
```

For each hit:
- If the test tests TriggerPolicy logic (depths, cooldowns), rewrite it to test `TriggerPolicy` directly.
- If the test tests turn execution, rewrite it to test `AgentTurnExecutor` directly.
- If the test tests prompt building, rewrite it to test `PromptBuilder` directly.
- `tests/unit/test_runner.py` lines 120,154 call `actor._build_prompt` — change to `PromptBuilder.build_prompt(node, trigger.event)`.

### Step 2.4: Fix _normalize_dir_id No-Op

**File**: `src/remora/code/reconciler.py`
**Problem**: Lines 350-353 — the `isinstance` check is meaningless (both branches do the same thing).

**Action**: Replace with:
```python
@staticmethod
def _normalize_dir_id(path: Path | str) -> str:
    value = Path(path).as_posix()
    return "." if value in {"", "."} else value
```

### Step 2.5: Commit

```bash
git add -A && git commit -m "refactor(core): delete Actor delegation wrappers, property shims, and dead code"
```

---

## Phase 3: Type the Untyped

The review correctly identified `search_service: object | None` and `Any` as the most widespread typing failures. Fix them all.

### Step 3.1: Create SearchService Protocol

**File**: `src/remora/core/search.py`

**Action**: Add a Protocol class before the concrete `SearchService` class:

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class SearchServiceProtocol(Protocol):
    @property
    def available(self) -> bool: ...
    async def search(self, query: str, collection: str | None, top_k: int, mode: str) -> list[dict[str, Any]]: ...
    async def find_similar(self, chunk_id: str, collection: str | None, top_k: int) -> list[dict[str, Any]]: ...
    async def index_file(self, path: str, collection: str | None = None) -> None: ...
    async def delete_source(self, path: str, collection: str | None = None) -> None: ...
```

### Step 3.2: Replace All `object | None` and `Any` search_service Types

**Files to update** (7 files):
1. `src/remora/core/actor.py` — `AgentTurnExecutor.__init__` and `Actor.__init__`: change `search_service: object | None` to `search_service: SearchServiceProtocol | None`
2. `src/remora/core/externals.py` — `TurnContext.__init__`: change `search_service: Any` to `search_service: SearchServiceProtocol | None`
3. `src/remora/core/runner.py` — `ActorPool.__init__`: change `search_service: object | None` to `search_service: SearchServiceProtocol | None`
4. `src/remora/core/services.py` — `RuntimeServices`: change `self.search_service: SearchService | None` to `self.search_service: SearchServiceProtocol | None` (already somewhat typed but should use the Protocol)
5. `src/remora/code/reconciler.py` — `FileReconciler.__init__`: change `search_service: object | None` to `search_service: SearchServiceProtocol | None`
6. `src/remora/web/server.py` — `create_app()`: change `search_service: object | None` to `search_service: SearchServiceProtocol | None`

Add the import `from remora.core.search import SearchServiceProtocol` to each file.

### Step 3.3: Replace getattr Duck-Typing with Protocol

After typing, all `getattr(search_service, "available", False)` calls in `reconciler.py` (lines 473, 483) and `web/server.py` (line 396) can be replaced with `search_service.available` since the Protocol guarantees the attribute exists.

### Step 3.4: Type Other `Any` Parameters

**File**: `src/remora/core/externals.py`
- `outbox: Any` → `outbox: Outbox` (import from `remora.core.actor`). **NOTE**: This creates a circular import. Solve with `from __future__ import annotations` (already present) and `TYPE_CHECKING`:
  ```python
  from typing import TYPE_CHECKING
  if TYPE_CHECKING:
      from remora.core.actor import Outbox
  ```

**File**: `src/remora/core/workspace.py`
- `workspace: Any` in `AgentWorkspace.__init__` — this wraps a Cairn workspace. Study that library codebase, which has been copied in for reference in the .context/ directory at repo root. If Cairn exports a Protocol or base class, use it. Otherwise leave as `Any` with a `# cairn runtime type` comment.

**File**: `src/remora/core/lifecycle.py`
- `configure_file_logging: Any` → `configure_file_logging: Callable[[Path], None]`:
  ```python
  from collections.abc import Callable
  ```
- `_lsp_server: Any` → keep as `Any` (pygls type isn't easily accessible)

### Step 3.5: Commit

```bash
git add -A && git commit -m "refactor(core): type SearchService interface with Protocol, fix Any parameters"
```

---

## Phase 4: Extract BundleConfig Pydantic Model

### Step 4.1: Create BundleConfig Model

**File**: `src/remora/core/config.py` (add near the other config models)

```python
class SelfReflectConfig(BaseModel):
    """Self-reflection configuration within a bundle."""
    enabled: bool = False
    model: str | None = None
    max_turns: int = 2
    prompt: str | None = None

    @field_validator("max_turns")
    @classmethod
    def _validate_max_turns(cls, value: int) -> int:
        return max(1, value)


class BundleConfig(BaseModel):
    """Agent bundle configuration loaded from bundle.yaml."""
    system_prompt: str = "You are an autonomous code agent."
    system_prompt_extension: str = ""
    model: str | None = None
    max_turns: int = 8
    prompts: dict[str, str] = Field(default_factory=dict)
    self_reflect: SelfReflectConfig | None = None

    @field_validator("max_turns")
    @classmethod
    def _validate_max_turns(cls, value: int) -> int:
        return max(1, value)

    @field_validator("prompts")
    @classmethod
    def _validate_prompts(cls, value: dict[str, str]) -> dict[str, str]:
        return {k: v for k, v in value.items() if k in ("chat", "reactive") and v.strip()}
```

### Step 4.2: Replace _read_bundle_config

**File**: `src/remora/core/actor.py`

Replace the 62-line `_read_bundle_config` static method (lines 660-721) with:

```python
@staticmethod
async def _read_bundle_config(workspace: AgentWorkspace) -> BundleConfig:
    try:
        text = await workspace.read("_bundle/bundle.yaml")
    except (FileNotFoundError, FsdFileNotFoundError):
        return BundleConfig()
    try:
        loaded = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        logger.warning("Ignoring malformed _bundle/bundle.yaml")
        return BundleConfig()
    if not isinstance(loaded, dict):
        return BundleConfig()
    expanded = _expand_env_vars(loaded)
    if not isinstance(expanded, dict):
        return BundleConfig()
    try:
        return BundleConfig.model_validate(expanded)
    except Exception:
        logger.warning("Invalid bundle config, using defaults")
        return BundleConfig()
```

### Step 4.3: Update All Callers

The return type changes from `dict[str, Any]` to `BundleConfig`. Update:
- `AgentTurnExecutor._start_agent_turn` return type: `tuple[Node, AgentWorkspace, BundleConfig] | None`
- `AgentTurnExecutor.execute_turn`: `bundle_config` is now a `BundleConfig`
- `PromptBuilder.build_system_prompt`: change `bundle_config: dict[str, Any]` to `bundle_config: BundleConfig`, then replace all `.get()` calls with direct attribute access
- All `bundle_config.get("system_prompt", ...)` → `bundle_config.system_prompt`
- All `bundle_config.get("model", ...)` → `bundle_config.model or self._config.model_default`
- All `bundle_config.get("self_reflect", {})` → `bundle_config.self_reflect`

### Step 4.4: Verify and Commit

```bash
devenv shell -- python -m pytest tests/unit/test_actor.py tests/unit/test_bundle_configs.py -v
git add -A && git commit -m "refactor(core): replace manual bundle config validation with Pydantic model"
```

---

## Phase 5: Decompose actor.py

The review correctly identified that actor.py conflates three responsibilities. After Phase 2 deletes the wrappers and Phase 4 extracts BundleConfig, actor.py should be ~700 LOC. Now split it.

### Step 5.1: Create `src/remora/core/outbox.py`

Move these classes:
- `Outbox` (lines 65-104)
- `OutboxObserver` (lines 107-159)

The module needs imports for `Event`, `EventStore`, `ModelRequestEvent`, `ModelResponseEvent`, `RemoraToolCallEvent`, `RemoraToolResultEvent`, `TurnCompleteEvent`.

### Step 5.2: Create `src/remora/core/trigger.py`

Move these:
- `Trigger` dataclass (lines 162-168)
- `TriggerPolicy` class (lines 171-220)
- The module constants `_DEPTH_TTL_MS` and `_DEPTH_CLEANUP_INTERVAL`

### Step 5.3: Create `src/remora/core/prompt.py`

Move:
- `PromptBuilder` class (lines 223-313)
- `_event_content` helper function (lines 938-941)
- The constant `_DEFAULT_REFLECTION_PROMPT`

### Step 5.4: Create `src/remora/core/turn_executor.py`

Move:
- `AgentTurnExecutor` class (lines 315-721, minus the `_read_bundle_config` which will be simplified per Phase 4)
- `_turn_logger` helper function (lines 53-62)

### Step 5.5: Slim Down `src/remora/core/actor.py`

After extraction, actor.py should contain ONLY:
- `Actor` class (~100 LOC)
- Re-exports in `__all__` pointing to the new modules

Update `__all__` to re-export everything for backwards-compatible imports:
```python
from remora.core.outbox import Outbox, OutboxObserver
from remora.core.trigger import Trigger, TriggerPolicy
from remora.core.prompt import PromptBuilder
from remora.core.turn_executor import AgentTurnExecutor
```

### Step 5.6: Update All Imports

Search for every import from `remora.core.actor` across the codebase and tests. Most should still work via re-exports, but verify:
```bash
grep -rn "from remora.core.actor import" src/ tests/
```

### Step 5.7: Verify and Commit

```bash
devenv shell -- python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q
git add -A && git commit -m "refactor(core): decompose actor.py into outbox, trigger, prompt, turn_executor modules"
```

---

## Phase 6: Refactor web/server.py

The review correctly identified this as a 560-line closure soup. Extract into focused handler classes.

### Step 6.1: Create Handler Dependencies Dataclass

At the top of `web/server.py`, create a shared dependencies container:

```python
@dataclass
class WebDeps:
    """Shared dependencies for all web handlers."""
    event_store: EventStore
    node_store: NodeStore
    event_bus: EventBus
    metrics: Metrics | None
    actor_pool: ActorPool | None
    workspace_service: CairnWorkspaceService | None
    search_service: SearchServiceProtocol | None
    shutdown_event: asyncio.Event
    chat_limiter: RateLimiter
```

### Step 6.2: Extract Handler Groups as Module-Level Functions

Group the 20+ endpoints into logical clusters. Each takes `deps: WebDeps` and `request: Request`:

**Group 1 — Node API** (`api_nodes`, `api_node`, `api_edges`, `api_all_edges`, `api_node_companion`, `api_conversation`):
```python
async def api_nodes(request: Request) -> JSONResponse:
    deps: WebDeps = request.app.state.deps
    nodes = await deps.node_store.list_nodes()
    return JSONResponse([node.model_dump() for node in nodes])
```

**Group 2 — Chat & Interaction** (`api_chat`, `api_respond`, `api_cursor`)

**Group 3 — Proposals** (`api_proposals`, `api_proposal_diff`, `api_proposal_accept`, `api_proposal_reject`)

**Group 4 — System** (`api_events`, `api_health`, `api_search`)

**Group 5 — SSE** (`sse_stream`)

### Step 6.3: Move Helper Functions to Module Level

Move these out of the closure:
- `_resolve_within_project_root` → module-level, takes `workspace_service` param
- `_workspace_path_to_disk_path` → module-level, takes `workspace_service` param
- `_latest_rewrite_proposal` → module-level, takes `event_store` param

### Step 6.4: Simplify create_app

`create_app` becomes a thin wiring function:

```python
def create_app(
    event_store: EventStore,
    node_store: NodeStore,
    event_bus: EventBus,
    metrics: Metrics | None = None,
    actor_pool: ActorPool | None = None,
    workspace_service: CairnWorkspaceService | None = None,
    search_service: SearchServiceProtocol | None = None,
) -> Starlette:
    shutdown_event = asyncio.Event()
    deps = WebDeps(
        event_store=event_store,
        node_store=node_store,
        event_bus=event_bus,
        metrics=metrics,
        actor_pool=actor_pool,
        workspace_service=workspace_service,
        search_service=search_service,
        shutdown_event=shutdown_event,
        chat_limiter=RateLimiter(max_requests=10, window_seconds=60.0),
    )

    # ... routes list using module-level handler functions ...

    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.deps = deps
    # ... middleware ...
    return app
```

### Step 6.5: Verify and Commit

```bash
devenv shell -- python -m pytest tests/unit/test_web_server.py -v
git add -A && git commit -m "refactor(web): extract closure soup into module-level handlers with WebDeps"
```

---

## Phase 7: Fix Event System Issues

The event system is the cleanest part, but has a few specific issues.

### Step 7.1: Fix TurnDigestedEvent.tags Shadow

**File**: `src/remora/core/events/types.py`
**Problem**: Line 198 — `TurnDigestedEvent` redeclares `tags: tuple[str, ...] = ()` which shadows the base `Event.tags` field identically.

**Action**: Delete line 198 (`tags: tuple[str, ...] = ()`). The base class already provides this field with the same type and default.

### Step 7.2: Fix CustomEvent Payload Nesting

**File**: `src/remora/core/events/types.py`
**Problem**: `CustomEvent` has a `payload` field, but `Event.to_envelope()` puts all non-base fields into `payload`. So `CustomEvent`'s payload ends up as `{"payload": {"payload": {...}}}`.

**Action**: Override `to_envelope` in `CustomEvent` to flatten:

```python
class CustomEvent(Event):
    payload: dict[str, Any] = Field(default_factory=dict)

    def to_envelope(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "correlation_id": self.correlation_id,
            "tags": list(self.tags),
            "payload": self.payload,
        }
```

### Step 7.3: Fix EventBus.unsubscribe Ghost Registrations

**File**: `src/remora/core/events/bus.py`
**Problem**: `list.remove()` only removes the first occurrence. If a handler is registered twice, unsubscribing leaves a ghost.

**Action**: Replace lines 59-65:
```python
def unsubscribe(self, handler: EventHandler) -> None:
    """Remove a handler from all subscriptions."""
    for event_type in list(self._handlers):
        self._handlers[event_type] = [h for h in self._handlers[event_type] if h is not handler]
        if not self._handlers[event_type]:
            del self._handlers[event_type]
    self._all_handlers = [h for h in self._all_handlers if h is not handler]
```

### Step 7.4: Commit

```bash
devenv shell -- python -m pytest tests/unit/test_events.py tests/unit/test_event_bus.py tests/unit/test_event_store.py -v
git add -A && git commit -m "fix(events): fix TurnDigestedEvent shadow, CustomEvent nesting, bus unsubscribe"
```

---

## Phase 8: Decompose _materialize_directories

### Step 8.1: Extract Helper Methods

**File**: `src/remora/code/reconciler.py`
**Problem**: `_materialize_directories` (lines 195-320) is 125 lines doing 7 things.

**Action**: Extract into focused methods:

```python
def _compute_directory_hierarchy(self, file_paths: set[str]) -> tuple[set[str], dict[str, list[str]]]:
    """Compute directory set and children-by-directory mapping from file paths."""
    file_rel_paths = {self._relative_file_path(path) for path in file_paths}
    dir_paths: set[str] = {"."}
    for rel_file_path in file_rel_paths:
        current = Path(rel_file_path).parent
        while True:
            dir_id = self._normalize_dir_id(current)
            dir_paths.add(dir_id)
            if dir_id == "." or current == current.parent:
                break
            current = current.parent

    children_by_dir: dict[str, list[str]] = {dir_id: [] for dir_id in dir_paths}
    for dir_id in dir_paths:
        if dir_id == ".":
            continue
        parent_id = self._parent_dir_id(dir_id)
        children_by_dir.setdefault(parent_id, []).append(dir_id)
    for rel_file_path in file_rel_paths:
        parent_id = self._parent_dir_id(rel_file_path)
        children_by_dir.setdefault(parent_id, []).append(rel_file_path)
    return dir_paths, children_by_dir

async def _remove_stale_directories(self, existing_by_id: dict[str, Node], desired_ids: set[str]) -> None:
    """Delete directory nodes that are no longer present in the file tree."""
    stale_ids = sorted(
        set(existing_by_id) - desired_ids,
        key=lambda node_id: node_id.count("/"),
        reverse=True,
    )
    for node_id in stale_ids:
        await self._remove_node(node_id)

async def _upsert_directory_node(
    self,
    dir_id: str,
    children: list[str],
    existing: Node | None,
    *,
    sync_existing_bundles: bool,
    refresh_subscriptions: bool,
) -> None:
    """Create or update a single directory node."""
    # ... the per-directory logic from _materialize_directories ...
```

### Step 8.2: Simplify _materialize_directories

After extraction, `_materialize_directories` becomes an orchestrator:

```python
async def _materialize_directories(self, file_paths: set[str], *, sync_existing_bundles: bool) -> None:
    dir_paths, children_by_dir = self._compute_directory_hierarchy(file_paths)
    existing_dirs = await self._node_store.list_nodes(node_type=NodeType.DIRECTORY)
    existing_by_id = {node.node_id: node for node in existing_dirs}

    async with self._node_store.batch():
        await self._remove_stale_directories(existing_by_id, dir_paths)
        for dir_id in sorted(dir_paths):
            children = sorted(children_by_dir.get(dir_id, []))
            existing = existing_by_id.get(dir_id)
            await self._upsert_directory_node(
                dir_id, children, existing,
                sync_existing_bundles=sync_existing_bundles,
                refresh_subscriptions=not self._subscriptions_bootstrapped,
            )
    self._subscriptions_bootstrapped = True
```

### Step 8.3: Verify and Commit

```bash
devenv shell -- python -m pytest tests/unit/test_reconciler.py -v
git add -A && git commit -m "refactor(reconciler): decompose _materialize_directories into focused helpers"
```

---

## Phase 9: Performance Fixes

### Step 9.1: Add get_latest_event_by_type to EventStore

**File**: `src/remora/core/events/store.py`

**Action**: Add this method:

```python
async def get_latest_event_by_type(
    self, agent_id: str, event_type: str
) -> dict[str, Any] | None:
    """Get the most recent event of a specific type for an agent."""
    cursor = await self._db.execute(
        """
        SELECT * FROM events
        WHERE (agent_id = ? OR from_agent = ? OR to_agent = ?)
          AND event_type = ?
        ORDER BY id DESC LIMIT 1
        """,
        (agent_id, agent_id, agent_id, event_type),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    result = dict(row)
    result["tags"] = json.loads(result.get("tags") or "[]")
    result["payload"] = json.loads(result["payload"])
    return result
```

### Step 9.2: Replace _latest_rewrite_proposal

**File**: `src/remora/web/server.py`

Replace the O(200) linear scan with:
```python
async def _latest_rewrite_proposal(node_id: str) -> dict | None:
    return await event_store.get_latest_event_by_type(node_id, "RewriteProposalEvent")
```

(Or if this is now a module-level function per Phase 6, use `deps.event_store`.)

### Step 9.3: Add get_nodes_by_ids to NodeStore

**File**: `src/remora/core/graph.py`

```python
async def get_nodes_by_ids(self, node_ids: list[str]) -> list[Node]:
    """Fetch multiple nodes by ID in a single query."""
    if not node_ids:
        return []
    placeholders = ", ".join("?" for _ in node_ids)
    cursor = await self._db.execute(
        f"SELECT * FROM nodes WHERE node_id IN ({placeholders})",
        tuple(node_ids),
    )
    rows = await cursor.fetchall()
    return [Node.from_row(row) for row in rows]
```

### Step 9.4: Fix N+1 in projections.py

**File**: `src/remora/code/projections.py`

Replace the per-node existence check (lines 29-30) with a batch query:

```python
async def project_nodes(...) -> list[Node]:
    results: list[Node] = []
    bundle_root = Path(config.bundle_root)

    # Batch-fetch existing nodes
    node_ids = [cst.node_id for cst in cst_nodes]
    existing_nodes = await node_store.get_nodes_by_ids(node_ids)
    existing_by_id = {n.node_id: n for n in existing_nodes}

    for cst in cst_nodes:
        source_hash = hashlib.sha256(cst.text.encode("utf-8")).hexdigest()
        existing = existing_by_id.get(cst.node_id)
        # ... rest of logic unchanged, just use existing from the dict ...
```

### Step 9.5: Fix SSE Polling

**File**: `src/remora/web/server.py`

Replace the `wait_for` timeout loop (lines 540-548) with task-based approach:

```python
async with event_bus.stream() as stream:
    stream_iterator = stream.__aiter__()
    while True:
        stream_task = asyncio.ensure_future(stream_iterator.__anext__())
        disconnect_task = asyncio.ensure_future(request.is_disconnected())
        shutdown_check = asyncio.ensure_future(_wait_for_shutdown(shutdown_event))

        done, pending = await asyncio.wait(
            {stream_task, disconnect_task, shutdown_check},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, StopAsyncIteration):
                pass

        if disconnect_task in done or shutdown_check in done:
            break
        if stream_task in done:
            try:
                event = stream_task.result()
            except StopAsyncIteration:
                break
            payload = json.dumps(event.to_envelope(), separators=(",", ":"))
            yield f"id: {event.timestamp}\nevent: {event.event_type}\ndata: {payload}\n\n"
```

Add the helper:
```python
async def _wait_for_shutdown(event: asyncio.Event) -> None:
    await event.wait()
```

### Step 9.6: Fix N+1 in reconciler _do_reconcile_file

**File**: `src/remora/code/reconciler.py`

Lines 410-413 do a per-node `get_node` to fetch old hashes. Use `get_nodes_by_ids`:

```python
existing_nodes = await self._node_store.get_nodes_by_ids(list(new_ids))
old_hashes = {n.node_id: n.source_hash for n in existing_nodes}
```

### Step 9.7: Verify and Commit

```bash
devenv shell -- python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q
git add -A && git commit -m "perf: batch queries, fix SSE polling, add get_latest_event_by_type"
```

---

## Phase 10: Fix Encapsulation Violations

### Step 10.1: Add count_nodes() to NodeStore

**File**: `src/remora/core/graph.py`

```python
async def count_nodes(self) -> int:
    """Return the total number of nodes."""
    cursor = await self._db.execute("SELECT COUNT(*) FROM nodes")
    row = await cursor.fetchone()
    return int(row[0]) if row else 0
```

### Step 10.2: Update Health Endpoint

**File**: `src/remora/web/server.py`

Replace line 433 (`cursor = await node_store._db.execute(...)`) with:
```python
node_count = await node_store.count_nodes()
```

Delete the subsequent `row = await cursor.fetchone()` and `node_count = ...` lines.

### Step 10.3: Fix OutboxObserver to Use isinstance Dispatch

**File**: `src/remora/core/outbox.py` (or `actor.py` if Phase 5 hasn't happened yet)

The review flagged string-based dispatch (`type(event).__name__`). However, the REPO_RULES.md says "No isinstance in business logic" with projection dispatch as the exception.

**Decision**: The OutboxObserver is a translation/bridge layer, not business logic. It translates structured_agents events into Remora events. `isinstance` is the right approach here.

**Action**: Import the structured_agents event types and use isinstance:

```python
from structured_agents.events import (
    ModelRequestEvent as SAModelRequestEvent,
    ModelResponseEvent as SAModelResponseEvent,
    ToolCallEvent as SAToolCallEvent,
    ToolResultEvent as SAToolResultEvent,
    TurnCompleteEvent as SATurnCompleteEvent,
)

def _translate(self, event: Any) -> Event | None:
    if isinstance(event, SAModelRequestEvent):
        return ModelRequestEvent(...)
    if isinstance(event, SAModelResponseEvent):
        return ModelResponseEvent(...)
    # ... etc
```

**Caveat**: First verify the structured_agents package actually exports these types. If not, keep the string dispatch and add a comment explaining why.

```bash
devenv shell -- python -c "from structured_agents.events import ModelRequestEvent; print('OK')" 2>&1
```

If that fails, keep string dispatch with a `# structured_agents doesn't export event types for isinstance` comment.

### Step 10.4: Verify and Commit

```bash
devenv shell -- python -m pytest tests/unit/test_web_server.py tests/unit/test_actor.py -v
git add -A && git commit -m "refactor: fix encapsulation violations — count_nodes(), isinstance dispatch"
```

---

## Phase 11: Clean Up Global State

### Step 11.1: Clean Up Grail Caches

**File**: `src/remora/core/grail.py`

**Problem**: `_SCRIPT_SOURCE_CACHE` (line 28) grows unbounded with no eviction, and `_cached_script` uses `@lru_cache(maxsize=256)` creating an uncoordinated two-level cache.

**Action**: Unify into a single bounded cache:

```python
from functools import lru_cache

_MAX_SCRIPT_CACHE = 256
_SCRIPT_SOURCE_CACHE: dict[tuple[str, str], str] = {}

def _evict_source_cache() -> None:
    """Evict oldest entries when source cache exceeds limit."""
    while len(_SCRIPT_SOURCE_CACHE) > _MAX_SCRIPT_CACHE:
        oldest_key = next(iter(_SCRIPT_SOURCE_CACHE))
        del _SCRIPT_SOURCE_CACHE[oldest_key]
```

Call `_evict_source_cache()` from `_load_script_from_source` after inserting.

### Step 11.2: Discovery Cache Cleanup

**File**: `src/remora/code/discovery.py`

The review suggested replacing `@lru_cache` with a class. However, the pragmatic fix is simpler — these caches hold tree-sitter Language/Parser objects that ARE intended to be singletons and don't change at runtime. The review overstated this issue.

**Action**: Leave the LRU caches as-is but add a `clear_caches()` function for test cleanup:

```python
def clear_caches() -> None:
    """Clear all module-level caches. For testing only."""
    _get_language_registry.cache_clear()
    _get_registry_plugin.cache_clear()
    _get_parser.cache_clear()
    _load_query.cache_clear()
```

### Step 11.3: Commit

```bash
git add -A && git commit -m "refactor: bound Grail script cache, add discovery cache clear for tests"
```

---

## Phase 12: Logging & Error Boundary Cleanup

### Step 12.1: Demote Hot-Path Logs to DEBUG

**File**: `src/remora/core/grail.py`
- Lines 124-131: Change `logger.info("Tool start ...")` → `logger.debug("Tool start ...")`
- Lines 140-147: Change `logger.info("Tool complete ...")` → `logger.debug("Tool complete ...")`
- Line 204: Change `logger.info("Loaded %d Grail tool(s) ...")` → `logger.debug("Loaded %d Grail tool(s) ...")`

**File**: `src/remora/core/actor.py` (or `turn_executor.py` after Phase 5)
- Lines 378-386: Change `turn_log.info("Agent turn start ...")` → `turn_log.debug("Agent turn start ...")`
- Lines 514-527: Change `turn_log.info("Model request ...")` → `turn_log.debug("Model request ...")`
- Lines 566-571: Change `turn_log.info("Agent turn complete ...")` → `turn_log.debug("Agent turn complete ...")`

Keep INFO for lifecycle events (actor created/evicted, reconcile complete, startup, shutdown).

### Step 12.2: Document Error Boundaries

Add a docstring to each catch-all `except Exception` block explaining WHY it's a boundary. The existing `# noqa: BLE001` comments are insufficient.

For each occurrence, add a one-line comment above the except:
```python
# Error boundary: tool execution failures must not crash the agent turn
except Exception as exc:  # noqa: BLE001
```

### Step 12.3: Commit

```bash
git add -A && git commit -m "refactor: demote hot-path logs to DEBUG, document error boundaries"
```

---

## Phase 13: Minor Fixes & Polish

### Step 13.1: Replace SHA-1 with SHA-256 in workspace.py

**File**: `src/remora/core/workspace.py` line 185

Change:
```python
digest = hashlib.sha1(node_id.encode("utf-8")).hexdigest()[:10]
```
To:
```python
digest = hashlib.sha256(node_id.encode("utf-8")).hexdigest()[:10]
```

**Note**: This changes workspace directory names. Since we don't care about backwards compatibility, this is fine. Existing workspaces will be recreated under new names.

### Step 13.2: Make Rate Limiter Per-Client

**File**: `src/remora/web/server.py`

Replace the single `RateLimiter` with per-IP limiting:

```python
_chat_limiters: dict[str, RateLimiter] = {}

def _get_chat_limiter(request: Request) -> RateLimiter:
    ip = request.client.host if request.client else "unknown"
    if ip not in _chat_limiters:
        _chat_limiters[ip] = RateLimiter(max_requests=10, window_seconds=60.0)
    return _chat_limiters[ip]
```

Update `api_chat` to use `_get_chat_limiter(request).allow()`.

### Step 13.3: Fix LSP Chat Command Hardcoded Port

**File**: `src/remora/lsp/server.py` line 183

The port is hardcoded to 8080. Pass it through from config.

**Action**: Add a `port` parameter to `create_lsp_server`:

```python
def create_lsp_server(
    node_store: NodeStore | None = None,
    event_store: EventStore | None = None,
    db_path: Path | None = None,
    web_port: int = 8080,
) -> LanguageServer:
```

Then use it:
```python
uri=f"http://localhost:{web_port}/?node={node_id}",
```

Update `lifecycle.py` to pass `web_port=self._port` when creating the LSP server.

### Step 13.4: Remove _discover Unnecessary Async

**File**: `src/remora/__main__.py`

The review noted `_discover` is async but calls only sync functions. However, `asyncio.run(_discover(...))` works fine and is harmless. The overhead is negligible.

**Decision**: Skip this fix. It's not worth the churn. The function is async in case future discovery needs async I/O.

### Step 13.5: Fix discovery.py _build_name_from_tree Dead Parameter

**File**: `src/remora/code/discovery.py` line 206-207

```python
def _build_name_from_tree(
    node: Any,
    name_node: Any,  # <-- unused, immediately deleted
    ...
```

**Action**: Remove the `name_node` parameter and the `del name_node` line. Update the two call sites (lines 170, 175-178) to not pass `name_node`.

### Step 13.6: Fix Language Plugin Properties → Class Attributes

**File**: `src/remora/code/languages.py`

The review noted that `@property` for constant values should be class attributes. However, changing properties to class attributes would break the `LanguagePlugin` Protocol which declares them as properties.

**Decision**: Skip this fix. The Protocol constraint makes properties the correct choice here.

### Step 13.7: Fix services.py Redundant create_tables

**File**: `src/remora/core/services.py` lines 51-53

`event_store.create_tables()` internally calls `self._dispatcher.subscriptions.create_tables()`. Then `services.py` also calls `subscriptions.create_tables()` separately (line 52). The subscription tables are created twice.

**Action**: Remove line 52 (`await self.subscriptions.create_tables()`). `event_store.create_tables()` handles it.

### Step 13.8: Verify and Commit

```bash
devenv shell -- python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q
git add -A && git commit -m "fix: SHA-256 workspace IDs, per-client rate limiter, LSP port config, minor cleanups"
```

---

## Phase 14: Test Suite Improvements

### Step 14.1: Add Lifecycle Integration Tests

**File**: `tests/integration/test_lifecycle.py` (new file)

Write tests that:
1. Start `RemoraLifecycle` with a small fixture project and `run_seconds=2.0`
2. Verify nodes are discovered (check `node_store.list_nodes()`)
3. Verify the web server responds to health checks (use `httpx.AsyncClient`)
4. Verify shutdown completes cleanly with no leaked asyncio tasks

### Step 14.2: Add Concurrency Tests

**File**: `tests/unit/test_concurrency.py` (new file)

Write tests for:
1. **Simultaneous dispatch**: Two events dispatched to the same agent via `asyncio.gather` — verify they serialize through the inbox queue.
2. **Subscription modification during dispatch**: Register a subscription, start a dispatch, modify subscriptions concurrently — verify no crash.
3. **Overlapping reconcile cycles**: Call `reconcile_cycle()` twice concurrently — verify idempotent result.

Use `asyncio.Event` to create controlled race conditions:
```python
async def test_concurrent_dispatch_serializes():
    """Two events dispatched simultaneously should be processed sequentially."""
    processed_order = []
    # ... set up actor with a tool that records execution order ...
    await asyncio.gather(
        actor.inbox.put(event_1),
        actor.inbox.put(event_2),
    )
    # ... verify processed_order is sequential ...
```

### Step 14.3: Fix Whitebox Tests

**File**: `tests/unit/test_actor.py`

After Phase 2 deleted the compatibility shims, any remaining tests that directly access TriggerPolicy internals should be rewritten:

- Tests about trigger depths → test `TriggerPolicy.should_trigger()` and `TriggerPolicy.release_depth()` directly
- Tests about cooldowns → test `TriggerPolicy.should_trigger()` with time mocking
- Tests about prompt building → test `PromptBuilder.build_system_prompt()` directly

### Step 14.4: Add Missing batch() Rollback Test

This was mentioned in Phase 1 but should be verified as existing. If not, add:

```python
async def test_batch_rollback_on_exception(node_store, sample_node):
    try:
        async with node_store.batch():
            await node_store.upsert_node(sample_node)
            raise ValueError("test")
    except ValueError:
        pass
    assert await node_store.get_node(sample_node.node_id) is None
```

### Step 14.5: Verify and Commit

```bash
devenv shell -- python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q
git add -A && git commit -m "test: add lifecycle integration tests, concurrency tests, fix whitebox tests"
```

---

## Appendix A: Review Findings Validation

After reading every source file in the library, here is the validation status of each finding from `CODE_REVIEW.md`.

### Confirmed As-Is (implement exactly as described)

| # | Finding | Verdict |
|---|---------|---------|
| 1 | Actor delegation anti-pattern (lines 854-936) | **Confirmed**. 80+ lines of pure boilerplate delegation. Delete all of it. |
| 2 | Compatibility property shims (lines 760-791) | **Confirmed**. Test-driven API shape. Delete. |
| 3 | TurnContext class-level mutable state (line 30) | **Confirmed**. Classic Python class variable bug. Fix immediately. |
| 4 | batch() commits on failure (graph.py:39-48) | **Confirmed**. Must rollback on exception. |
| 5 | set_status bypasses state machine (graph.py:158) | **Confirmed**. Delete the method entirely. |
| 6 | search_service typed as object/None everywhere | **Confirmed**. 7 files. Fix with Protocol. |
| 7 | _latest_rewrite_proposal O(200) scan | **Confirmed**. Add SQL query with WHERE event_type. |
| 8 | _normalize_dir_id isinstance no-op | **Confirmed**. Both branches identical. |
| 9 | Health endpoint accesses _db directly | **Confirmed**. Add count_nodes() method. |
| 10 | TurnDigestedEvent.tags shadows base class | **Confirmed**. Redundant field redeclaration. |
| 11 | bus.unsubscribe only removes first occurrence | **Confirmed**. Use list comprehension filter. |
| 12 | _build_name_from_tree has unused name_node param | **Confirmed**. Remove parameter and del statement. |
| 13 | services.py double create_tables call | **Confirmed**. Remove redundant call. |
| 14 | _read_bundle_config manual validation | **Confirmed**. 62 lines that should be a Pydantic model. |
| 15 | SSE polling with wait_for timeout | **Confirmed**. Use asyncio.wait with tasks instead. |
| 16 | _materialize_directories 125 lines | **Confirmed**. Decompose into 3-4 methods. |
| 17 | N+1 in projections.py | **Confirmed**. Batch with get_nodes_by_ids. |
| 18 | Grail _SCRIPT_SOURCE_CACHE unbounded | **Confirmed**. Add eviction. |
| 19 | Hot-path logging at INFO level | **Confirmed**. Demote to DEBUG. |
| 20 | SHA-1 for workspace IDs | **Confirmed**. Trivial fix to SHA-256. |
| 21 | web/server.py is one giant closure | **Confirmed**. Decompose into module-level handlers. |
| 22 | actor.py conflates three responsibilities | **Confirmed**. Split into separate modules. |
| 23 | CustomEvent payload nests redundantly | **Confirmed**. Override to_envelope. |

### Confirmed But With Adjusted Fix

| # | Finding | Adjustment |
|---|---------|------------|
| 1 | OutboxObserver string-based dispatch | **Adjusted**. The review recommends isinstance. This is correct ONLY if structured_agents exports the event types. Verify with an import test first. If imports fail, keep string dispatch with a comment. |
| 2 | Lifecycle configure_file_logging typed as Any | **Adjusted**. Fix type to `Callable[[Path], None]` but don't extract a Protocol — overkill for a single callback. |
| 3 | Rate limiter is per-process not per-client | **Adjusted**. Make per-IP, but also add an LRU eviction to prevent memory growth from many unique IPs. Cap at 10,000 entries. |
| 4 | EventStore.append does a full commit every time | **Deferred**. The review recommends a write-behind buffer. This is architecturally significant and risks losing events on crash. For a dev tool where correctness matters more than throughput, the current per-event commit is acceptable. Defer to a future performance pass if profiling shows it's a bottleneck. |
| 5 | SubscriptionRegistry cache invalidation fragile | **Deferred**. The incremental cache updates are correct and well-tested. Adding a periodic refresh would add complexity with no proven benefit. |
| 6 | workspace.py AgentWorkspace serializes all I/O | **Deferred**. A read-write lock would help concurrent reads, but the Cairn workspace internals may not be thread-safe. Leave the simple lock and revisit if profiling shows contention. |
| 7 | Duplicate result serialization in search.py | **Adjusted**. Extract a `_serialize_result(item)` helper, but don't over-abstract — it's just 10 lines of dict comprehension. |

### Dismissed (Not Worth Fixing)

| # | Finding | Reason |
|---|---------|--------|
| 1 | `_discover` is unnecessarily async | **Dismissed**. Async is harmless and allows future async I/O without signature changes. |
| 2 | Language plugin properties should be class attributes | **Dismissed**. The Protocol declares them as properties. Changing to class attributes would violate the Protocol. |
| 3 | Config _expand_env_vars no recursion depth limit | **Dismissed**. The review acknowledges "not a realistic concern." YAML files in practice are 2-3 levels deep. |
| 4 | _find_config_file walks to filesystem root | **Dismissed**. Standard behavior for tool configs (git, npm, etc.). Not surprising. |
| 5 | paths.py walk_source_files quadratic ignore matching | **Dismissed**. The number of ignore patterns is tiny (5 by default). Pre-compiling patterns or tries would be over-engineering. |
| 6 | kernel.py extract_response_text falls back to str(result) | **Dismissed**. This is a sensible fallback for an unknown result type. The str() output may not be pretty but it's better than crashing. |
| 7 | __all__ placement inconsistency | **Dismissed**. Pure style nit. Not worth the churn. |
| 8 | Discovery _parse_file quadratic parent walk | **Dismissed**. "For typical source files this is fine" — the review's own words. Files with thousands of deeply nested nodes are theoretical. |
| 9 | RuntimeServices is a bag not a container | **Dismissed**. The review says "works at this scale." At 12 services, a flat namespace is fine. Interface segregation would add boilerplate for no benefit. |
| 10 | reconciler.py _stop_event polling pattern | **Dismissed**. The polling bridges asyncio and threading for watchfiles. The 0.5s polling wastes negligible CPU. The review's suggested fix (asyncio.Event that sets threading.Event) would still need a bridge mechanism. |
| 11 | LSP DocumentStore.apply_changes edge cases | **Dismissed**. The review says "these cases are rare." Fixing them requires deep LSP protocol knowledge for scenarios that don't happen in practice. |
| 12 | File lock memory leak potential | **Partially dismissed**. The `_evict_stale_file_locks` method already handles cleanup by generation. Growth is bounded by the number of unique files touched in a generation. For any reasonable project, this is fine. |
| 13 | metrics.py cache_hit_rate counts provisions as misses | **Dismissed**. The denominator is `provisions + cache_hits`, which represents total workspace requests. Provisions include first-time creates AND cache misses. This is actually correct — the "hit rate" shows what percentage of workspace requests were served from cache. |
| 14 | Inconsistent naming (_store vs _service) | **Dismissed**. The distinction is intentional: stores are data access layers, services coordinate business logic. The naming is actually consistent within its own convention. |

---

**IMPORTANT: NO SUBAGENTS** — NEVER use the Task tool. Do ALL work directly. No delegation. No exceptions.
