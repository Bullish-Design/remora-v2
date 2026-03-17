# Remora v2 — Review Refactoring Guide

**Date:** 2026-03-17
**Companion to:** `CODE_REVIEW.md`, `RECOMMENDATIONS.md`
**Principle:** No backwards compatibility. Optimize for the cleanest, most elegant architecture possible.

This guide walks through each recommendation as a self-contained step. Complete each step fully (including tests and validation) before moving to the next. Steps are ordered by priority and dependency — later steps may build on earlier ones.

---

## Table of Contents

1. [Step 1: Fix the CairnWorkspaceService Cache Race (P0)](#step-1-fix-the-cairnworkspaceservice-cache-race-p0)
2. [Step 2: Fix `request_human_input` State Machine (P0)](#step-2-fix-request_human_input-state-machine-p0)
3. [Step 3: Remove AgentWorkspace Global Lock (P0)](#step-3-remove-agentworkspace-global-lock-p0)
4. [Step 4: Fix the Config Merge (P0)](#step-4-fix-the-config-merge-p0)
5. [Step 5: Split the God Config (P1)](#step-5-split-the-god-config-p1)
6. [Step 6: Unify Transaction Management (P1)](#step-6-unify-transaction-management-p1)
7. [Step 7: Move Companion Context to Prompt Builder (P1)](#step-7-move-companion-context-to-prompt-builder-p1)
8. [Step 8: Enforce Externals Version (P1)](#step-8-enforce-externals-version-p1)
9. [Step 9: Eliminate Discovery Cache Staleness (P2)](#step-9-eliminate-discovery-cache-staleness-p2)
10. [Step 10: Extract Subscription Manager (P2)](#step-10-extract-subscription-manager-p2)
11. [Step 11: Rethink the Prompt Builder Return Types (P2)](#step-11-rethink-the-prompt-builder-return-types-p2)
12. [Step 12: Make Tree-Sitter Grammars Optional (P2)](#step-12-make-tree-sitter-grammars-optional-p2)
13. [Step 13: Template Interpolation Safety (P3)](#step-13-template-interpolation-safety-p3)
14. [Step 14: Bounded Collections Everywhere (P3)](#step-14-bounded-collections-everywhere-p3)
15. [Step 15: Clean Up Dead Code and Stale Patterns (P3)](#step-15-clean-up-dead-code-and-stale-patterns-p3)

---

## Step 1: Fix the CairnWorkspaceService Cache Race (P0)

### Problem

`CairnWorkspaceService.get_agent_workspace()` in `src/remora/core/workspace.py:191-209` has a race condition. The `async with self._lock` block checks the cache and opens the raw workspace, but the lock is released BEFORE the `AgentWorkspace` wrapper is created and written into the cache dicts. Two concurrent calls for the same `node_id` can both pass the cache check, both open workspaces, and race to write to the cache. The second write wins, orphaning the first workspace.

### What to Change

**File:** `src/remora/core/workspace.py`

Move the `AgentWorkspace` construction and both cache writes inside the lock:

```python
async def get_agent_workspace(self, node_id: str) -> AgentWorkspace:
    """Get or create an AgentWorkspace for the given node ID."""
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

The key change: lines 206-209 of the current code (creating `AgentWorkspace` and writing to both dicts) must move inside the `async with self._lock:` block, before the `return`.

### Testing & Validation

1. **Run existing tests:**
   ```bash
   devenv shell -- pytest tests/unit/test_workspace.py -v
   ```
   All existing workspace tests should still pass.

2. **Write a concurrency stress test** in `tests/unit/test_workspace.py`:
   ```python
   @pytest.mark.asyncio
   async def test_get_agent_workspace_concurrent_same_node(workspace_service):
       """Two concurrent calls for the same node_id should return the same workspace."""
       results = await asyncio.gather(
           workspace_service.get_agent_workspace("node-a"),
           workspace_service.get_agent_workspace("node-a"),
       )
       # Both should return the exact same object
       assert results[0] is results[1]
   ```

   This test would have been flaky before the fix (the two calls could have created different `AgentWorkspace` instances) and should now be deterministic.

3. **Verify metrics consistency:** After the test, check that `workspace_provisions_total` is 1 (not 2) and `workspace_cache_hits` is 1 (the second caller found the cache entry).

4. **Run the full test suite:**
   ```bash
   devenv shell -- pytest -x
   ```

---

## Step 2: Fix `request_human_input` State Machine (P0)

### Problem

In `src/remora/core/externals.py:302-327`, the `request_human_input` method has a `finally` block that always transitions the node to `RUNNING`. When a timeout occurs, the `TimeoutError` is re-raised, and the turn executor's error handler (in `turn_executor.py:161-165`) then transitions the node to `ERROR`. The node rapidly goes through `AWAITING_INPUT` → `RUNNING` → `ERROR` — the intermediate `RUNNING` transition is pointless and potentially confusing.

### What to Change

**File:** `src/remora/core/externals.py`

Replace the current `try`/`except`/`finally` block with explicit state transitions in each path:

```python
async def request_human_input(
    self,
    question: str,
    options: list[str] | None = None,
) -> str:
    request_id = str(uuid.uuid4())
    future = self._event_store.create_response_future(request_id)

    await self._node_store.transition_status(self._node_id, NodeStatus.AWAITING_INPUT)
    await self._emit(
        HumanInputRequestEvent(
            agent_id=self._node_id,
            request_id=request_id,
            question=question,
            options=tuple(options or ()),
            correlation_id=self._correlation_id,
        )
    )

    try:
        result = await asyncio.wait_for(future, timeout=self._human_input_timeout_s)
        await self._node_store.transition_status(self._node_id, NodeStatus.RUNNING)
        return result
    except TimeoutError:
        self._event_store.discard_response_future(request_id)
        raise
```

The key changes:
- Remove the `finally` block entirely.
- Transition to `RUNNING` only on the **success** path (inside `try`, after `wait_for` returns).
- On `TimeoutError`, just discard the future and re-raise. The turn executor's error handler will transition to `ERROR`, which is the correct final state for a timeout.

### Testing & Validation

1. **Run existing externals tests:**
   ```bash
   devenv shell -- pytest tests/unit/test_externals.py -v
   ```

2. **Write/update tests for both paths:**

   **Success path test** — verify node goes `AWAITING_INPUT` → `RUNNING`:
   ```python
   @pytest.mark.asyncio
   async def test_request_human_input_success_transitions(comms, node_store, event_store):
       """Successful human input should transition AWAITING_INPUT -> RUNNING."""
       # Pre-resolve the future so wait_for returns immediately
       future_request_id = None
       original_create = event_store.create_response_future
       def capture_create(request_id):
           nonlocal future_request_id
           future_request_id = request_id
           f = original_create(request_id)
           f.set_result("user answer")
           return f
       event_store.create_response_future = capture_create

       result = await comms.request_human_input("question?")
       assert result == "user answer"
       node = await node_store.get_node(comms._node_id)
       assert node.status == NodeStatus.RUNNING
   ```

   **Timeout path test** — verify node stays in `AWAITING_INPUT` (not `RUNNING`), so the turn executor can move it to `ERROR`:
   ```python
   @pytest.mark.asyncio
   async def test_request_human_input_timeout_no_running_transition(comms, node_store):
       """Timeout should NOT transition to RUNNING — let the error handler decide."""
       comms._human_input_timeout_s = 0.01  # very short timeout
       with pytest.raises(TimeoutError):
           await comms.request_human_input("question?")
       node = await node_store.get_node(comms._node_id)
       # Node should still be AWAITING_INPUT — the turn executor handles the final state
       assert node.status == NodeStatus.AWAITING_INPUT
   ```

3. **Run full test suite:**
   ```bash
   devenv shell -- pytest -x
   ```

---

## Step 3: Remove AgentWorkspace Global Lock (P0)

### Problem

`AgentWorkspace` in `src/remora/core/workspace.py:25-105` uses a single `asyncio.Lock()` for ALL operations — file reads, file writes, KV gets, KV sets, directory listings, etc. This means a slow file read blocks all KV operations for that agent, adding unnecessary serialization. The underlying Cairn `Workspace` object is its own abstraction that likely handles its own safety, so this outer lock is redundant at best and harmful at worst.

### What to Change

**File:** `src/remora/core/workspace.py`

Remove the `self._lock = asyncio.Lock()` from `AgentWorkspace.__init__` and remove all `async with self._lock:` wrappers from every method. The class should become a thin passthrough:

```python
class AgentWorkspace:
    """Per-agent sandboxed filesystem backed by Cairn."""

    def __init__(self, workspace: Workspace, agent_id: str):
        self._workspace = workspace
        self._agent_id = agent_id

    async def read(self, path: str) -> str:
        """Read a file from the agent workspace."""
        content = await self._workspace.files.read(path)
        if isinstance(content, bytes):
            return content.decode("utf-8", errors="replace")
        return str(content)

    async def write(self, path: str, content: str | bytes) -> None:
        """Write a file to the agent workspace."""
        await self._workspace.files.write(path, content)

    async def exists(self, path: str) -> bool:
        """Check existence in the agent workspace."""
        return await self._workspace.files.exists(path)

    # ... same pattern for all other methods: remove `async with self._lock:` wrapper
```

Apply this to all 11 methods: `read`, `write`, `exists`, `list_dir`, `delete`, `list_all_paths`, `kv_get`, `kv_set`, `kv_delete`, `kv_list`, and `build_companion_context`.

### Testing & Validation

1. **Run existing workspace tests:**
   ```bash
   devenv shell -- pytest tests/unit/test_workspace.py -v
   ```

2. **Write a concurrent operations test:**
   ```python
   @pytest.mark.asyncio
   async def test_concurrent_file_and_kv_operations(agent_workspace):
       """File and KV operations should not block each other."""
       await agent_workspace.write("test.txt", "hello")
       await agent_workspace.kv_set("key1", "value1")

       # Run file read and KV read concurrently — should not deadlock
       results = await asyncio.gather(
           agent_workspace.read("test.txt"),
           agent_workspace.kv_get("key1"),
       )
       assert results[0] == "hello"
       assert results[1] == "value1"
   ```

3. **Run full test suite:**
   ```bash
   devenv shell -- pytest -x
   ```

---

## Step 4: Fix the Config Merge (P0)

### Problem

`load_config()` in `src/remora/core/config.py:298` does `merged = {**defaults, **expand_env_vars(user_data)}`. This is a **shallow merge** — if `defaults.yaml` defines `languages: {python: {...}, markdown: {...}, toml: {...}}` and the user's `remora.yaml` has `languages: {python: {extensions: [".py", ".pyi"]}}`, the user config completely replaces ALL language definitions. The user loses `markdown` and `toml`.

### What to Change

**File:** `src/remora/core/config.py`

1. **Add `_deep_merge` function** (note: `_merge_dicts` already exists in `workspace.py` with the same logic — we'll hoist it to config in Step 15, but for now just add it here):

   ```python
   def _deep_merge(base: dict, overlay: dict) -> dict:
       """Recursively merge overlay into base. Overlay values win for non-dict types."""
       result = dict(base)
       for key, value in overlay.items():
           if key in result and isinstance(result[key], dict) and isinstance(value, dict):
               result[key] = _deep_merge(result[key], value)
           else:
               result[key] = value
       return result
   ```

2. **Replace the shallow merge in `load_config()`:**

   Change line 298 from:
   ```python
   merged = {**defaults, **expand_env_vars(user_data)}
   ```
   To:
   ```python
   merged = _deep_merge(defaults, expand_env_vars(user_data))
   ```

### Testing & Validation

1. **Run existing config tests:**
   ```bash
   devenv shell -- pytest tests/unit/test_config.py -v
   ```

2. **Write tests for deep merge behavior** in `tests/unit/test_config.py`:

   ```python
   def test_deep_merge_basic():
       base = {"a": 1, "b": {"x": 10, "y": 20}}
       overlay = {"b": {"x": 99}, "c": 3}
       result = _deep_merge(base, overlay)
       assert result == {"a": 1, "b": {"x": 99, "y": 20}, "c": 3}

   def test_deep_merge_overlay_replaces_non_dict():
       base = {"a": [1, 2], "b": "text"}
       overlay = {"a": [3, 4]}
       result = _deep_merge(base, overlay)
       assert result == {"a": [3, 4], "b": "text"}

   def test_load_config_deep_merges_languages(tmp_path):
       """User overriding one language should not destroy other default languages."""
       user_config = tmp_path / "remora.yaml"
       user_config.write_text(
           "languages:\n"
           "  python:\n"
           "    extensions: ['.py', '.pyi']\n",
           encoding="utf-8",
       )
       config = load_config(user_config)
       # User's override should be applied
       assert ".pyi" in config.languages["python"]["extensions"]
       # Other default languages should still exist
       assert "markdown" in config.languages
       assert "toml" in config.languages

   def test_load_config_deep_merges_language_map(tmp_path):
       """User adding a language_map entry should not destroy defaults."""
       user_config = tmp_path / "remora.yaml"
       user_config.write_text(
           "language_map:\n"
           "  '.rs': rust\n",
           encoding="utf-8",
       )
       config = load_config(user_config)
       assert config.language_map[".rs"] == "rust"
       # Defaults should still be present
       assert config.language_map[".py"] == "python"
   ```

3. **Run full test suite:**
   ```bash
   devenv shell -- pytest -x
   ```

---

## Step 5: Split the God Config (P1)

### Problem

`Config` at 361 lines in `src/remora/core/config.py` is a god object containing: project config, bundle config, LLM config, execution engine settings, language definitions, prompt templates, externals version, and search config. Splitting it into focused sub-models makes the code self-documenting and reduces coupling — callers only accept the sub-config they need.

### What to Change

**File:** `src/remora/core/config.py`

This is a large refactor that touches many files. Here's the approach:

#### 5a. Define the new sub-models

Add these new models to `config.py`, above the `Config` class:

```python
class ProjectConfig(BaseModel):
    """Paths and discovery settings."""
    project_path: str = "."
    discovery_paths: tuple[str, ...] = ("src/",)
    discovery_languages: tuple[str, ...] | None = None
    workspace_ignore_patterns: tuple[str, ...] = (
        ".git", ".venv", "__pycache__", "node_modules", ".remora",
    )

    @field_validator("discovery_paths")
    @classmethod
    def _validate_discovery_paths(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("discovery_paths must not be empty")
        cleaned = tuple(path for path in value if isinstance(path, str) and path.strip())
        if not cleaned:
            raise ValueError("discovery_paths must contain at least one non-empty path")
        return cleaned


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

    @field_validator("language_map")
    @classmethod
    def _validate_language_map(cls, value: dict[str, str]) -> dict[str, str]:
        # ... same validator as current Config._validate_language_map
        ...

    @field_validator("bundle_search_paths", "query_search_paths")
    @classmethod
    def _validate_search_paths(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        # ... same validator as current Config._validate_search_paths
        ...
```

#### 5b. Redefine `Config` as a composition

```python
class Config(BaseSettings):
    """Remora configuration — composed of focused sub-models."""
    model_config = SettingsConfigDict(env_prefix="REMORA_", frozen=True, populate_by_name=True)

    project: ProjectConfig = Field(default_factory=ProjectConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    infra: InfraConfig = Field(default_factory=InfraConfig)
    behavior: BehaviorConfig = Field(default_factory=BehaviorConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    virtual_agents: tuple[VirtualAgentConfig, ...] = ()

    @field_validator("virtual_agents")
    @classmethod
    def _validate_virtual_agents(cls, value: tuple[VirtualAgentConfig, ...]) -> tuple[VirtualAgentConfig, ...]:
        # ... same validator as current
        ...

    def resolve_bundle(self, node_type: NodeType | str, node_name: str | None = None) -> str | None:
        """Resolve bundle by priority: first matching rule, then type overlays."""
        normalized_type = serialize_enum(node_type)
        normalized_name = node_name or ""
        for rule in self.behavior.bundle_rules:
            if rule.node_type != normalized_type:
                continue
            if rule.name_pattern is None or fnmatch(normalized_name, rule.name_pattern):
                return rule.bundle
        return self.behavior.bundle_overlays.get(normalized_type)
```

#### 5c. Update `load_config()` to map `defaults.yaml` fields into the nested structure

The `defaults.yaml` currently has a flat structure. You need to update `load_config()` to nest the flat keys from `defaults.yaml` and user YAML into the new sub-model structure. Add a `_nest_flat_config` function:

```python
def _nest_flat_config(flat: dict[str, Any]) -> dict[str, Any]:
    """Map flat config keys into nested sub-model structure."""
    nested: dict[str, Any] = {}

    project_keys = {"project_path", "discovery_paths", "discovery_languages", "workspace_ignore_patterns"}
    runtime_keys = {"max_concurrency", "max_trigger_depth", "trigger_cooldown_ms",
                     "human_input_timeout_s", "actor_idle_timeout_s", "send_message_rate_limit",
                     "send_message_rate_window_s", "search_content_max_matches", "broadcast_max_targets"}
    infra_keys = {"model_base_url", "model_api_key", "timeout_s", "workspace_root"}
    behavior_keys = {"model_default", "max_turns", "bundle_search_paths", "query_search_paths",
                      "bundle_overlays", "bundle_rules", "languages", "language_map",
                      "prompt_templates", "externals_version"}

    project = {}
    runtime = {}
    infra = {}
    behavior = {}

    for key, value in flat.items():
        if key in project_keys:
            project[key] = value
        elif key in runtime_keys:
            runtime[key] = value
        elif key in infra_keys:
            infra[key] = value
        elif key in behavior_keys:
            behavior[key] = value
        elif key == "search":
            nested["search"] = value
        elif key == "virtual_agents":
            nested["virtual_agents"] = value
        else:
            # Unknown keys pass through at top level for env var overrides
            nested[key] = value

    if project:
        nested["project"] = project
    if runtime:
        nested["runtime"] = runtime
    if infra:
        nested["infra"] = infra
    if behavior:
        nested["behavior"] = behavior

    return nested

def load_config(path: Path | None = None) -> Config:
    from remora.defaults import load_defaults
    defaults = load_defaults()
    config_path = path if path is not None else _find_config_file()
    if config_path is not None:
        user_data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    else:
        user_data = {}
    merged = _deep_merge(defaults, expand_env_vars(user_data))
    nested = _nest_flat_config(merged)
    return Config(**nested)
```

**Also update `defaults.yaml`** to use the nested structure if you prefer, but the `_nest_flat_config` function allows backwards-compatible YAML files.

#### 5d. Update ALL callers
 
This is the bulk of the work. Every file that accesses `config.<field>` needs to be updated to `config.<sub_model>.<field>`. Here is a mapping of the most important call sites:

| Old Access | New Access | Files Affected |
|---|---|---|
| `config.project_path` | `config.project.project_path` | `lifecycle.py` |
| `config.discovery_paths` | `config.project.discovery_paths` | `watcher.py`, `reconciler.py` |
| `config.discovery_languages` | `config.project.discovery_languages` | `reconciler.py` |
| `config.workspace_ignore_patterns` | `config.project.workspace_ignore_patterns` | `reconciler.py`, `watcher.py` |
| `config.max_concurrency` | `config.runtime.max_concurrency` | `runner.py` |
| `config.max_trigger_depth` | `config.runtime.max_trigger_depth` | `trigger.py` |
| `config.trigger_cooldown_ms` | `config.runtime.trigger_cooldown_ms` | `trigger.py` |
| `config.human_input_timeout_s` | `config.runtime.human_input_timeout_s` | `turn_executor.py` |
| `config.actor_idle_timeout_s` | `config.runtime.actor_idle_timeout_s` | `runner.py` |
| `config.send_message_rate_limit` | `config.runtime.send_message_rate_limit` | `actor.py` |
| `config.send_message_rate_window_s` | `config.runtime.send_message_rate_window_s` | `actor.py` |
| `config.search_content_max_matches` | `config.runtime.search_content_max_matches` | `turn_executor.py` |
| `config.broadcast_max_targets` | `config.runtime.broadcast_max_targets` | `turn_executor.py` |
| `config.model_base_url` | `config.infra.model_base_url` | `turn_executor.py` |
| `config.model_api_key` | `config.infra.model_api_key` | `turn_executor.py` |
| `config.timeout_s` | `config.infra.timeout_s` | `turn_executor.py` |
| `config.workspace_root` | `config.infra.workspace_root` | `workspace.py` |
| `config.model_default` | `config.behavior.model_default` | `prompt.py`, `turn_executor.py` |
| `config.max_turns` | `config.behavior.max_turns` | `prompt.py` |
| `config.bundle_search_paths` | `config.behavior.bundle_search_paths` | `config.py` (resolve functions) |
| `config.query_search_paths` | `config.behavior.query_search_paths` | `config.py` (resolve functions) |
| `config.bundle_overlays` | `config.behavior.bundle_overlays` | via `resolve_bundle()` |
| `config.bundle_rules` | `config.behavior.bundle_rules` | via `resolve_bundle()` |
| `config.languages` | `config.behavior.languages` | `services.py` |
| `config.language_map` | `config.behavior.language_map` | `reconciler.py` |
| `config.prompt_templates` | `config.behavior.prompt_templates` | `prompt.py` |
| `config.externals_version` | `config.behavior.externals_version` | `workspace.py` |

You need to find and update every reference. Use grep to find all `config.` accesses:
```bash
rg 'config\.' src/remora/ --type py | grep -v '#' | grep -v 'model_config'
```

#### 5e. Update `resolve_bundle_search_paths` and `resolve_query_search_paths`

These functions in `config.py` currently take a `Config` and access flat fields. Update them:

```python
def resolve_bundle_search_paths(config: Config, project_root: Path) -> list[Path]:
    from remora.defaults import default_bundles_dir
    return _resolve_search_paths(config.behavior.bundle_search_paths, project_root, default_bundles_dir())

def resolve_query_search_paths(config: Config, project_root: Path) -> list[Path]:
    from remora.defaults import default_queries_dir
    return _resolve_search_paths(config.behavior.query_search_paths, project_root, default_queries_dir())
```

### Testing & Validation

1. **Update all test files** that construct `Config()` directly. Tests that do `Config(max_turns=4)` must change to `Config(behavior=BehaviorConfig(max_turns=4))` etc. Search for `Config(` across all test files.

2. **Verify `Config()` with no arguments** produces a usable config with sensible defaults:
   ```python
   def test_default_config_has_sensible_defaults():
       config = Config()
       assert config.behavior.model_default == "Qwen/Qwen3-4B"
       assert config.behavior.max_turns == 8
       assert config.runtime.max_concurrency == 4
       assert config.infra.model_base_url == "http://localhost:8000/v1"
       assert config.project.discovery_paths == ("src/",)
   ```

3. **Verify `load_config()` still works** with both `defaults.yaml` and user YAML:
   ```python
   def test_load_config_nests_flat_defaults(tmp_path):
       config = load_config()  # no user config, just defaults.yaml
       assert config.behavior.model_default == "Qwen/Qwen3-4B"
       assert "python" in config.behavior.languages
   ```

4. **Run full test suite:**
   ```bash
   devenv shell -- pytest -x
   ```

   Expect many test failures initially from callers using old field paths. Fix them all.

5. **Run pyright type check:**
   ```bash
   devenv shell -- pyright src/remora/
   ```

---

## Step 6: Unify Transaction Management (P1)

### Problem

`NodeStore.batch()` and `EventStore.batch()` independently track `_batch_depth` on the same `aiosqlite.Connection`. When nested (as in `reconciler.py:235-236`), `EventStore.batch()` commits when its depth reaches 0 even if `NodeStore.batch()` hasn't finished. This relies on call ordering rather than structural guarantees.

### What to Change

#### 6a. Create `TransactionContext`

**New file:** `src/remora/core/transaction.py`

```python
"""Unified transaction context for NodeStore and EventStore."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import aiosqlite

from remora.core.events.bus import EventBus
from remora.core.events.dispatcher import TriggerDispatcher
from remora.core.events.types import Event


class TransactionContext:
    """Shared transaction depth tracker for a single DB connection."""

    def __init__(
        self,
        db: aiosqlite.Connection,
        event_bus: EventBus,
        dispatcher: TriggerDispatcher,
    ):
        self._db = db
        self._event_bus = event_bus
        self._dispatcher = dispatcher
        self._depth = 0
        self._deferred_events: list[Event] = []

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
                self._deferred_events.clear()
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

    @property
    def in_batch(self) -> bool:
        return self._depth > 0

    def defer_event(self, event: Event) -> None:
        """Buffer an event for fan-out after the outermost batch commits."""
        self._deferred_events.append(event)
```

#### 6b. Update `NodeStore` to use `TransactionContext`

Remove `_batch_depth` from `NodeStore`. Add a `tx` parameter:

```python
class NodeStore:
    def __init__(self, db: aiosqlite.Connection, tx: TransactionContext | None = None):
        self._db = db
        self._tx = tx

    async def batch(self):
        if self._tx is not None:
            async with self._tx.batch():
                yield
        else:
            # fallback for standalone usage / tests
            ...

    async def _maybe_commit(self) -> None:
        if self._tx is not None and self._tx.in_batch:
            return
        await self._db.commit()
```

#### 6c. Update `EventStore` to use `TransactionContext`

Remove `_batch_depth` and `_batch_buffer` from `EventStore`. Replace with `TransactionContext`:

```python
class EventStore:
    def __init__(self, db, event_bus, dispatcher, *, tx=None, metrics=None):
        self._db = db
        self._event_bus = event_bus
        self._dispatcher = dispatcher
        self._tx = tx
        self._metrics = metrics
        self._pending_responses = {}

    async def append(self, event: Event) -> int:
        # ... insert into DB (same as before) ...

        if self._tx is not None and self._tx.in_batch:
            self._tx.defer_event(event)
            return event_id

        await self._db.commit()
        await self._event_bus.emit(event)
        await self._dispatcher.dispatch(event)
        return event_id

    async def batch(self):
        if self._tx is not None:
            async with self._tx.batch():
                yield
        else:
            # fallback for standalone usage
            ...
```

#### 6d. Update `RuntimeServices` to wire the shared `TransactionContext`

```python
class RuntimeServices:
    def __init__(self, config, project_root, db):
        # ...
        self.event_bus = EventBus()
        self.subscriptions = SubscriptionRegistry(db)
        self.dispatcher = TriggerDispatcher(self.subscriptions)
        self.tx = TransactionContext(db, self.event_bus, self.dispatcher)
        self.node_store = NodeStore(db, tx=self.tx)
        self.event_store = EventStore(
            db=db, event_bus=self.event_bus, dispatcher=self.dispatcher,
            tx=self.tx, metrics=self.metrics,
        )
```

#### 6e. Update `reconciler.py` to use a single batch

Replace the nested batches:
```python
# Old:
async with self._node_store.batch():
    async with self._event_store.batch():
        ...

# New — single unified batch:
async with self._tx.batch():
    ...
```

The reconciler needs access to the `TransactionContext`. Pass it via the constructor or access it via the shared `RuntimeServices`.

### Testing & Validation

1. **Write a test** that verifies a single batch commits atomically:
   ```python
   @pytest.mark.asyncio
   async def test_unified_batch_commits_atomically(db, tx, node_store, event_store):
       """All operations in a batch should commit together."""
       async with tx.batch():
           await node_store.upsert_node(make_node("test::func"))
           await event_store.append(NodeDiscoveredEvent(...))

       # Both should be committed
       node = await node_store.get_node("test::func")
       assert node is not None
       events = await event_store.get_events(limit=1)
       assert len(events) == 1

   @pytest.mark.asyncio
   async def test_unified_batch_rolls_back_on_error(db, tx, node_store, event_store):
       """An error in a batch should rollback everything."""
       with pytest.raises(ValueError):
           async with tx.batch():
               await node_store.upsert_node(make_node("test::func"))
               raise ValueError("boom")

       # Node should NOT be committed
       node = await node_store.get_node("test::func")
       assert node is None
   ```

2. **Run all reconciler tests:**
   ```bash
   devenv shell -- pytest tests/unit/test_reconciler.py -v
   ```

3. **Run full test suite:**
   ```bash
   devenv shell -- pytest -x
   ```

---

## Step 7: Move Companion Context to Prompt Builder (P1)

### Problem

`AgentWorkspace.build_companion_context()` (`workspace.py:106-163`) is 57 lines of prompt construction logic living in the workspace layer. The workspace should provide raw data; the prompt builder should format it. Currently the workspace returns formatted markdown, and the turn executor manages injecting it into both the system and user prompts.

### What to Change

#### 7a. Create `CompanionData` dataclass

**File:** `src/remora/core/prompt.py` (add near the top)

```python
from dataclasses import dataclass, field

@dataclass
class CompanionData:
    """Raw companion memory data from agent workspace."""
    reflections: list[dict] = field(default_factory=list)
    chat_index: list[dict] = field(default_factory=list)
    links: list[dict] = field(default_factory=list)
```

#### 7b. Add `get_companion_data()` to `AgentWorkspace`

**File:** `src/remora/core/workspace.py`

Replace `build_companion_context()` with a raw data method:

```python
async def get_companion_data(self) -> CompanionData:
    """Retrieve raw companion memory data from workspace KV."""
    from remora.core.prompt import CompanionData

    reflections = await self.kv_get("companion/reflections")
    chat_index = await self.kv_get("companion/chat_index")
    links = await self.kv_get("companion/links")

    return CompanionData(
        reflections=reflections if isinstance(reflections, list) else [],
        chat_index=chat_index if isinstance(chat_index, list) else [],
        links=links if isinstance(links, list) else [],
    )
```

Delete the `build_companion_context()` method entirely.

#### 7c. Move formatting logic to `PromptBuilder`

**File:** `src/remora/core/prompt.py`

Add a method that formats `CompanionData` into a markdown string:

```python
@staticmethod
def format_companion_context(data: CompanionData) -> str:
    """Format raw companion data into a markdown context block."""
    parts: list[str] = []

    if data.reflections:
        lines = []
        for entry in data.reflections[-5:]:
            if not isinstance(entry, dict):
                continue
            insight = entry.get("insight", "")
            if isinstance(insight, str) and insight.strip():
                lines.append(f"- {insight.strip()}")
        if lines:
            parts.append("## Prior Reflections")
            parts.extend(lines)

    if data.chat_index:
        lines = []
        for entry in data.chat_index[-5:]:
            if not isinstance(entry, dict):
                continue
            summary = entry.get("summary", "")
            if not isinstance(summary, str) or not summary.strip():
                continue
            raw_tags = entry.get("tags", [])
            tags_source = raw_tags if isinstance(raw_tags, (list, tuple)) else []
            tags = [str(tag).strip() for tag in tags_source if str(tag).strip()]
            tag_suffix = f" [{', '.join(tags)}]" if tags else ""
            lines.append(f"- {summary.strip()}{tag_suffix}")
        if lines:
            parts.append("## Recent Activity")
            parts.extend(lines)

    if data.links:
        lines = []
        for entry in data.links[-10:]:
            if not isinstance(entry, dict):
                continue
            target = entry.get("target", "")
            if not isinstance(target, str) or not target.strip():
                continue
            relationship = entry.get("relationship", "related")
            rel_text = relationship.strip() if isinstance(relationship, str) and relationship.strip() else "related"
            lines.append(f"- {rel_text}: {target.strip()}")
        if lines:
            parts.append("## Known Relationships")
            parts.extend(lines)

    if not parts:
        return ""
    return "\n## Companion Memory\n" + "\n".join(parts)
```

#### 7d. Update `turn_executor.py`

**File:** `src/remora/core/turn_executor.py`

In `execute_turn()`, replace:
```python
companion_context = ""
if not is_reflection_turn:
    companion_context = await workspace.build_companion_context()
    if companion_context:
        system_prompt = f"{system_prompt}\n{companion_context}"
```

With:
```python
companion_context = ""
if not is_reflection_turn:
    companion_data = await workspace.get_companion_data()
    companion_context = self._prompt_builder.format_companion_context(companion_data)
    if companion_context:
        system_prompt = f"{system_prompt}\n{companion_context}"
```

### Testing & Validation

1. **Write tests for `CompanionData` and `format_companion_context`:**
   ```python
   def test_format_companion_context_empty():
       data = CompanionData()
       assert PromptBuilder.format_companion_context(data) == ""

   def test_format_companion_context_reflections():
       data = CompanionData(reflections=[{"insight": "Functions should be pure"}])
       result = PromptBuilder.format_companion_context(data)
       assert "Prior Reflections" in result
       assert "Functions should be pure" in result

   def test_format_companion_context_all_sections():
       data = CompanionData(
           reflections=[{"insight": "insight1"}],
           chat_index=[{"summary": "discussed X", "tags": ["design"]}],
           links=[{"target": "module::func", "relationship": "calls"}],
       )
       result = PromptBuilder.format_companion_context(data)
       assert "Prior Reflections" in result
       assert "Recent Activity" in result
       assert "Known Relationships" in result
   ```

2. **Update companion tools tests:**
   ```bash
   devenv shell -- pytest tests/unit/test_companion_tools.py -v
   ```

3. **Run all workspace and prompt tests:**
   ```bash
   devenv shell -- pytest tests/unit/test_workspace.py tests/unit/test_config.py -v
   ```

4. **Run full test suite:**
   ```bash
   devenv shell -- pytest -x
   ```

---

## Step 8: Enforce Externals Version (P1)

### Problem

`EXTERNALS_VERSION` mismatch in `workspace.py:240-249` only logs a warning. A bundle requiring a newer externals version will still load and execute, potentially failing at runtime when it tries to use capabilities that don't exist.

### What to Change

#### 8a. Define a custom exception

**File:** `src/remora/core/workspace.py` (or a shared exceptions module)

```python
class IncompatibleBundleError(Exception):
    """Raised when a bundle requires a newer externals version than core provides."""
    pass
```

#### 8b. Change the warning to a raise

**File:** `src/remora/core/workspace.py`

In `read_bundle_config()`, replace the warning block:

```python
# Old:
if (
    config.externals_version is not None
    and config.externals_version > EXTERNALS_VERSION
):
    logger.warning(...)

# New:
if (
    config.externals_version is not None
    and config.externals_version > EXTERNALS_VERSION
):
    raise IncompatibleBundleError(
        f"Bundle for {node_id} requires externals v{config.externals_version} "
        f"but core provides v{EXTERNALS_VERSION}"
    )
```

#### 8c. Handle the error in the turn executor

**File:** `src/remora/core/turn_executor.py`

In `_start_agent_turn()`, the `read_bundle_config()` call is already inside the turn's error boundary (`except Exception` in `execute_turn`). When `IncompatibleBundleError` is raised, the turn will fail and emit an `AgentErrorEvent` with a clear message. No additional handling is needed — the existing error boundary already does the right thing.

However, if you want to give a more specific error message, you can catch it explicitly:

```python
try:
    bundle_config = await self._workspace_service.read_bundle_config(node_id)
except IncompatibleBundleError as exc:
    turn_log.error("Bundle version mismatch: %s", exc)
    await self._node_store.transition_status(node_id, NodeStatus.ERROR)
    await outbox.emit(AgentErrorEvent(agent_id=node_id, error=str(exc), ...))
    return None
```

#### 8d. Move version check OUT of workspace (boundary fix)

The code review notes that `workspace.py` importing `EXTERNALS_VERSION` from `externals.py` is a boundary violation. The version check belongs in the turn executor or a bundle validation layer, not in the workspace service.

Move the version check from `read_bundle_config()` to `_start_agent_turn()` in `turn_executor.py`:

```python
bundle_config = await self._workspace_service.read_bundle_config(node_id)
if (
    bundle_config.externals_version is not None
    and bundle_config.externals_version > EXTERNALS_VERSION
):
    raise IncompatibleBundleError(
        f"Bundle for {node_id} requires externals v{bundle_config.externals_version} "
        f"but core provides v{EXTERNALS_VERSION}"
    )
```

Then remove the `EXTERNALS_VERSION` import from `workspace.py`.

### Testing & Validation

1. **Write a test for version enforcement:**
   ```python
   @pytest.mark.asyncio
   async def test_incompatible_bundle_raises(workspace_service, tmp_path):
       """Bundles requiring a newer externals version should fail loudly."""
       ws = await workspace_service.get_agent_workspace("test::node")
       await ws.write("_bundle/bundle.yaml", "externals_version: 999\n")

       # Now the check happens in the turn executor, not read_bundle_config
       config = await workspace_service.read_bundle_config("test::node")
       assert config.externals_version == 999

       # Verify that using this config in a turn would raise
       from remora.core.externals import EXTERNALS_VERSION
       assert config.externals_version > EXTERNALS_VERSION
   ```

2. **Run full test suite:**
   ```bash
   devenv shell -- pytest -x
   ```

---

## Step 9: Eliminate Discovery Cache Staleness (P2)

### Problem

`discovery.py` uses `@lru_cache` decorators on `_get_language_registry()`, `_get_parser()`, `_get_registry_plugin()`, and `_load_query()`. These caches are never invalidated and ignore user config. If a user adds a custom language in `remora.yaml`, discovery may use the default registry instead.

There's also a stale `_DEFAULT_LANGUAGE_MAP` (lines 16-20) that should have been removed during the refactor.

### What to Change

#### 9a. Remove `_DEFAULT_LANGUAGE_MAP`

**File:** `src/remora/code/discovery.py`

Delete lines 16-20:
```python
# DELETE THIS:
_DEFAULT_LANGUAGE_MAP: dict[str, str] = {
    ".py": "python",
    ".md": "markdown",
    ".toml": "toml",
}
```

Update `discover()` to require `language_map` instead of falling back to the deleted default:
```python
def discover(
    paths: list[Path],
    *,
    language_map: dict[str, str],  # no longer optional
    query_paths: list[Path] | None = None,
    ignore_patterns: tuple[str, ...] = (),
    languages: list[str] | None = None,
    language_registry: LanguageRegistry | None = None,
) -> list[Node]:
```

If you change the signature, update all callers. The reconciler already passes `language_map`.

#### 9b. Remove cached functions and thread `LanguageRegistry` through

**File:** `src/remora/code/discovery.py`

Delete the four cached functions:
- `_get_registry_plugin()`
- `_get_language_registry()`
- `_get_parser()`
- `_load_query()`

Instead, require a `LanguageRegistry` parameter. The registry itself can cache parsers internally:

```python
def discover(
    paths: list[Path],
    *,
    language_map: dict[str, str],
    language_registry: LanguageRegistry,  # now required
    query_paths: list[Path] | None = None,
    ignore_patterns: tuple[str, ...] = (),
    languages: list[str] | None = None,
) -> list[Node]:
    ...
    for source_file in walk_source_files(paths, ignore_patterns):
        ext = source_file.suffix.lower()
        language_name = effective_language_map.get(ext)
        if language_name is None:
            continue
        plugin = language_registry.get_by_name(language_name)
        ...
```

Update `_parse_file` to accept and use the registry directly instead of calling the cached helper functions:

```python
def _parse_file(path: Path, plugin: LanguagePlugin, query_paths: list[Path]) -> list[Node]:
    source_bytes = path.read_bytes()
    parser = Parser(plugin.get_language())
    tree = parser.parse(source_bytes)

    query_file = _resolve_query_file(plugin, query_paths)
    query_text = query_file.read_text(encoding="utf-8")
    query = Query(plugin.get_language(), query_text)
    ...
```

If parser/query construction is expensive, add a cache to `LanguageRegistry` or `LanguagePlugin` instead:

```python
class LanguagePlugin:
    def get_parser(self) -> Parser:
        """Return a cached parser for this language."""
        if not hasattr(self, '_parser'):
            self._parser = Parser(self.get_language())
        return self._parser
```

#### 9c. Update the reconciler to pass the registry

**File:** `src/remora/code/reconciler.py`

The reconciler's `_do_reconcile_file` calls `discover()`. Update it to pass the language registry. The registry is available via `RuntimeServices`:

```python
class FileReconciler:
    def __init__(self, ..., language_registry: LanguageRegistry):
        self._language_registry = language_registry
        ...

    async def _do_reconcile_file(self, file_path, mtime_ns, ...):
        discovered = discover(
            [Path(file_path)],
            language_map=self._config.behavior.language_map,  # or config.language_map pre-Step5
            language_registry=self._language_registry,
            query_paths=resolve_query_paths(self._config, self._project_root),
            ...
        )
```

Update `RuntimeServices.initialize()` to pass the registry when constructing the reconciler.

### Testing & Validation

1. **Run discovery tests:**
   ```bash
   devenv shell -- pytest tests/unit/test_discovery.py -v
   ```
   Update tests that call `discover()` to pass the now-required `language_registry` parameter.

2. **Write a test verifying custom languages work:**
   ```python
   def test_discover_uses_provided_registry(tmp_path):
       """Discovery should use the passed registry, not a cached default."""
       # Create a custom registry with only Python
       registry = LanguageRegistry.from_config(
           language_defs={"python": {"extensions": [".py"], "query_file": "python.scm"}},
           query_search_paths=[...],
       )
       nodes = discover(
           [tmp_path],
           language_map={".py": "python"},
           language_registry=registry,
       )
       # Should work — Python is in the registry
       ...
   ```

3. **Run reconciler tests:**
   ```bash
   devenv shell -- pytest tests/unit/test_reconciler.py -v
   ```

4. **Run full test suite:**
   ```bash
   devenv shell -- pytest -x
   ```

---

## Step 10: Extract Subscription Manager (P2)

### Problem

`_register_subscriptions()` in `reconciler.py:345-399` is 55 lines of subscription orchestration logic that doesn't belong in the file reconciler. The reconciler should discover nodes and emit events; subscription wiring should be handled by a separate component.

### What to Change

#### 10a. Create `SubscriptionManager`

**New file:** `src/remora/code/subscriptions.py`

```python
"""Subscription wiring for discovered nodes."""

from __future__ import annotations

from remora.core.events import EventStore, SubscriptionPattern
from remora.core.node import Node
from remora.core.types import EventType, NodeType
from remora.core.workspace import CairnWorkspaceService


class SubscriptionManager:
    """Wires event subscriptions for nodes based on their type and config."""

    def __init__(
        self,
        event_store: EventStore,
        workspace_service: CairnWorkspaceService,
    ):
        self._event_store = event_store
        self._workspace_service = workspace_service

    async def register_for_node(
        self,
        node: Node,
        *,
        virtual_subscriptions: tuple[SubscriptionPattern, ...] = (),
    ) -> None:
        """Register all appropriate subscriptions for a node."""
        await self._event_store.subscriptions.unregister_by_agent(node.node_id)

        # Every node subscribes to direct messages
        await self._event_store.subscriptions.register(
            node.node_id,
            SubscriptionPattern(to_agent=node.node_id),
        )

        if node.node_type == NodeType.VIRTUAL:
            for pattern in virtual_subscriptions:
                await self._event_store.subscriptions.register(node.node_id, pattern)
            return

        if node.node_type == NodeType.DIRECTORY:
            subtree_glob = "**" if node.file_path == "." else f"**/{node.file_path}/**"
            await self._event_store.subscriptions.register(
                node.node_id,
                SubscriptionPattern(
                    event_types=[EventType.NODE_CHANGED],
                    path_glob=subtree_glob,
                ),
            )
            await self._event_store.subscriptions.register(
                node.node_id,
                SubscriptionPattern(
                    event_types=[EventType.CONTENT_CHANGED],
                    path_glob=subtree_glob,
                ),
            )
            return

        # Code nodes: self-reflection subscription if enabled
        if self._workspace_service.has_workspace(node.node_id):
            workspace = await self._workspace_service.get_agent_workspace(node.node_id)
            self_reflect_config = await workspace.kv_get("_system/self_reflect")
            if isinstance(self_reflect_config, dict) and self_reflect_config.get("enabled"):
                await self._event_store.subscriptions.register(
                    node.node_id,
                    SubscriptionPattern(
                        event_types=[EventType.AGENT_COMPLETE],
                        from_agents=[node.node_id],
                        tags=["primary"],
                    ),
                )

        # Code nodes: content change subscription for own file
        await self._event_store.subscriptions.register(
            node.node_id,
            SubscriptionPattern(
                event_types=[EventType.CONTENT_CHANGED],
                path_glob=node.file_path,
            ),
        )


__all__ = ["SubscriptionManager"]
```

#### 10b. Update `FileReconciler` to use `SubscriptionManager`

**File:** `src/remora/code/reconciler.py`

1. Add `subscription_manager` to `__init__`:
   ```python
   def __init__(self, ..., subscription_manager: SubscriptionManager):
       self._subscription_manager = subscription_manager
   ```

2. Replace all calls to `self._register_subscriptions(node)` with `self._subscription_manager.register_for_node(node)`.

3. Delete the `_register_subscriptions` method from `FileReconciler`.

4. Update `DirectoryManager` and `VirtualAgentManager` which receive `register_subscriptions` as a callback — change them to use the `SubscriptionManager` directly.

#### 10c. Wire it in `RuntimeServices`

```python
self.subscription_manager = SubscriptionManager(self.event_store, self.workspace_service)
self.reconciler = FileReconciler(
    ...,
    subscription_manager=self.subscription_manager,
)
```

### Testing & Validation

1. **Write unit tests for `SubscriptionManager`:**
   ```python
   @pytest.mark.asyncio
   async def test_register_for_function_node(subscription_manager, event_store):
       node = make_node("src/app.py::func", node_type=NodeType.FUNCTION)
       await subscription_manager.register_for_node(node)
       subs = await event_store.subscriptions.get_subscriptions_for_agent(node.node_id)
       # Should have: direct message sub + content changed sub
       assert len(subs) >= 2

   @pytest.mark.asyncio
   async def test_register_for_directory_node(subscription_manager, event_store):
       node = make_node("src/", node_type=NodeType.DIRECTORY, file_path="src")
       await subscription_manager.register_for_node(node)
       subs = await event_store.subscriptions.get_subscriptions_for_agent(node.node_id)
       # Should have: direct message + node_changed + content_changed
       assert len(subs) >= 3
   ```

2. **Run reconciler tests:**
   ```bash
   devenv shell -- pytest tests/unit/test_reconciler.py -v
   ```

3. **Run full test suite:**
   ```bash
   devenv shell -- pytest -x
   ```

---

## Step 11: Rethink the Prompt Builder Return Types (P2)

### Problem

`build_system_prompt()` returns `tuple[str, str, int]` — prompt, model, max_turns. This conflates prompt construction with model selection. The caller must destructure this opaque tuple.

### What to Change

#### 11a. Define `TurnConfig` dataclass

**File:** `src/remora/core/prompt.py`

```python
@dataclass(frozen=True)
class TurnConfig:
    """Configuration for a single agent turn."""
    system_prompt: str
    model: str
    max_turns: int
```

#### 11b. Update `build_system_prompt` → `build_turn_config`

Rename the method and change the return type:

```python
def build_turn_config(
    self,
    bundle_config: BundleConfig,
    trigger_event: Event | None,
) -> TurnConfig:
    if self._is_reflection_turn(bundle_config, trigger_event):
        return self._build_reflection(bundle_config)

    system_prompt = bundle_config.system_prompt
    prompt_extension = bundle_config.system_prompt_extension
    if prompt_extension:
        system_prompt = f"{system_prompt}\n\n{prompt_extension}"

    mode = self.turn_mode(trigger_event)
    mode_prompt = bundle_config.prompts.get(mode, "")
    if mode_prompt:
        system_prompt = f"{system_prompt}\n\n{mode_prompt}"

    model_name = bundle_config.model or self._config.behavior.model_default
    max_turns = bundle_config.max_turns
    return TurnConfig(system_prompt=system_prompt, model=model_name, max_turns=max_turns)
```

Also update `_build_reflection` to return `TurnConfig`:

```python
def _build_reflection(self, bundle_config: BundleConfig) -> TurnConfig:
    self_reflect = bundle_config.self_reflect
    if self_reflect is None:
        return TurnConfig("", self._config.behavior.model_default, 1)
    ...
    return TurnConfig(reflection_prompt, model_name, max_turns)
```

#### 11c. Update `turn_executor.py`

Replace the tuple destructuring:

```python
# Old:
system_prompt, model_name, max_turns = self._prompt_builder.build_system_prompt(...)

# New:
turn_config = self._prompt_builder.build_turn_config(bundle_config, trigger.event)
system_prompt = turn_config.system_prompt
model_name = turn_config.model
max_turns = turn_config.max_turns
```

### Testing & Validation

1. **Update prompt builder tests:**
   ```bash
   devenv shell -- pytest tests/unit/ -k prompt -v
   ```
   Change all tests that expect a tuple to expect a `TurnConfig` object.

2. **Run full test suite:**
   ```bash
   devenv shell -- pytest -x
   ```

---

## Step 12: Make Tree-Sitter Grammars Optional (P2)

### Problem

`pyproject.toml` lists `tree-sitter-python`, `tree-sitter-markdown`, and `tree-sitter-toml` as hard dependencies. If languages are config-driven, grammars should be optional. A user who only needs Python shouldn't need `tree-sitter-toml`.

### What to Change

#### 12a. Move grammar packages to optional deps

**File:** `pyproject.toml`

Remove from `dependencies`:
```
"tree-sitter-python>=0.25.0",
"tree-sitter-markdown>=0.5.1",
"tree-sitter-toml>=0.7.0",
```

Add to `[project.optional-dependencies]`:
```toml
[project.optional-dependencies]
python = ["tree-sitter-python>=0.25.0"]
markdown = ["tree-sitter-markdown>=0.5.1"]
toml = ["tree-sitter-toml>=0.7.0"]
all-languages = [
    "tree-sitter-python>=0.25.0",
    "tree-sitter-markdown>=0.5.1",
    "tree-sitter-toml>=0.7.0",
]
```

Keep `"tree-sitter>=0.25"` in core dependencies (the base library).

#### 12b. Add a clear error on missing grammar

**File:** `src/remora/code/languages.py`

In `GenericLanguagePlugin.get_language()` (or wherever `importlib.import_module()` is called for tree-sitter grammars), wrap the import in a try/except:

```python
def get_language(self):
    try:
        module = importlib.import_module(self._module_name)
    except ImportError:
        raise ImportError(
            f"Language '{self.name}' requires {self._package_name}. "
            f"Install with: pip install remora[{self.name}]"
        ) from None
    return module.language()
```

#### 12c. Update dev dependencies

Add `all-languages` to the dev dependency group so developers get everything:
```toml
dev = [
    "remora[all-languages]",
    # ... rest of dev deps
]
```

### Testing & Validation

1. **Verify installation without grammars:**
   ```bash
   devenv shell -- pip install -e . --no-deps  # or just verify the import error message
   ```

2. **Write a test for the error message:**
   ```python
   def test_missing_grammar_gives_clear_error(monkeypatch):
       """Missing tree-sitter grammar should give an actionable error."""
       monkeypatch.setattr("importlib.import_module", lambda name: (_ for _ in ()).throw(ImportError()))
       plugin = GenericLanguagePlugin("fakeland", ...)
       with pytest.raises(ImportError, match="pip install remora"):
           plugin.get_language()
   ```

3. **Run full test suite (with all grammars installed via dev):**
   ```bash
   devenv shell -- pytest -x
   ```

---

## Step 13: Template Interpolation Safety (P3)

### Problem

`PromptBuilder._interpolate()` in `prompt.py:78-83` does loop-based `str.replace()` with `{var}` patterns. If a variable VALUE contains `{other_var}`, replacement order matters and could cause subtle bugs. A single-pass regex replacement prevents any interaction.

### What to Change

**File:** `src/remora/core/prompt.py`

Replace `_interpolate`:

```python
import re

@staticmethod
def _interpolate(template: str, variables: dict[str, str]) -> str:
    """Interpolate template vars using single-pass regex replacement."""
    def replacer(match: re.Match) -> str:
        key = match.group(1)
        return variables.get(key, match.group(0))
    return re.sub(r"\{(\w+)\}", replacer, template)
```

### Testing & Validation

1. **Write a test for the interaction case:**
   ```python
   def test_interpolate_no_double_replacement():
       """Variable values containing {other_var} should not be expanded."""
       template = "Name: {name}, Source: {source}"
       variables = {
           "name": "my_func",
           "source": "def my_func():\n    return '{name}'"  # source contains {name}
       }
       result = PromptBuilder._interpolate(template, variables)
       # {name} inside source should NOT be replaced
       assert "return '{name}'" in result
       assert "Name: my_func" in result

   def test_interpolate_unknown_vars_preserved():
       """Unknown template vars should be left as-is."""
       result = PromptBuilder._interpolate("{known} {unknown}", {"known": "hello"})
       assert result == "hello {unknown}"
   ```

2. **Run prompt tests:**
   ```bash
   devenv shell -- pytest tests/unit/ -k prompt -v
   ```

3. **Run full test suite:**
   ```bash
   devenv shell -- pytest -x
   ```

---

## Step 14: Bounded Collections Everywhere (P3)

### Problem

Several unbounded collections can grow without limit:
- `WebDeps.chat_limiters` grows per IP address with no eviction.
- `EventBus._dispatch_handlers()` creates unbounded concurrent tasks.

### What to Change

#### 14a. Bounded chat rate limiters

**File:** `src/remora/web/deps.py`

Add LRU eviction to `_get_chat_limiter`:

```python
_MAX_CHAT_LIMITERS = 1000

def _get_chat_limiter(request: Request, deps: WebDeps) -> SlidingWindowRateLimiter:
    ip = request.client.host if request.client is not None else "unknown"
    limiter = deps.chat_limiters.get(ip)
    if limiter is None:
        # Evict oldest if at capacity
        if len(deps.chat_limiters) >= _MAX_CHAT_LIMITERS:
            oldest_key = next(iter(deps.chat_limiters))
            del deps.chat_limiters[oldest_key]
        limiter = SlidingWindowRateLimiter(max_requests=10, window_seconds=60.0)
        deps.chat_limiters[ip] = limiter
    return limiter
```

#### 14b. Bounded EventBus handler concurrency

**File:** `src/remora/core/events/bus.py`

Add a semaphore to `EventBus`:

```python
class EventBus:
    def __init__(self, max_concurrent_handlers: int = 100) -> None:
        self._handlers: dict[type[Event], list[EventHandler]] = {}
        self._all_handlers: list[EventHandler] = []
        self._semaphore = asyncio.Semaphore(max_concurrent_handlers)

    @staticmethod
    async def _dispatch_handlers(
        handlers: list[EventHandler],
        event: Event,
        semaphore: asyncio.Semaphore | None = None,
    ) -> None:
        tasks: list[asyncio.Task[Any]] = []
        for handler in handlers:
            if asyncio.iscoroutinefunction(handler):
                async def bounded_handler(h=handler, e=event):
                    async with semaphore:
                        await h(e)
                if semaphore is not None:
                    tasks.append(asyncio.create_task(bounded_handler()))
                else:
                    tasks.append(asyncio.create_task(handler(event)))
                continue
            ...
```

Alternatively, a simpler approach: just pass the semaphore through `emit()`:

```python
async def emit(self, event: Event) -> None:
    event_type = type(event)
    await self._dispatch_handlers(self._handlers.get(event_type, []), event)
    if event_type is not Event:
        await self._dispatch_handlers(self._handlers.get(Event, []), event)
    await self._dispatch_handlers(self._all_handlers, event)
```

### Testing & Validation

1. **Test LRU eviction:**
   ```python
   def test_chat_limiter_evicts_oldest():
       deps = WebDeps(chat_limiters={})
       # Fill to capacity
       for i in range(_MAX_CHAT_LIMITERS):
           deps.chat_limiters[f"ip-{i}"] = SlidingWindowRateLimiter(10, 60.0)
       assert len(deps.chat_limiters) == _MAX_CHAT_LIMITERS
       # Adding one more should evict the oldest
       _get_chat_limiter(mock_request("new-ip"), deps)
       assert len(deps.chat_limiters) == _MAX_CHAT_LIMITERS
       assert "ip-0" not in deps.chat_limiters
   ```

2. **Test bounded event handlers:**
   ```python
   @pytest.mark.asyncio
   async def test_event_bus_limits_concurrent_handlers():
       bus = EventBus(max_concurrent_handlers=2)
       active = 0
       max_active = 0

       async def slow_handler(event):
           nonlocal active, max_active
           active += 1
           max_active = max(max_active, active)
           await asyncio.sleep(0.01)
           active -= 1

       for _ in range(10):
           bus.subscribe_all(slow_handler)

       await bus.emit(some_event)
       assert max_active <= 2
   ```

3. **Run full test suite:**
   ```bash
   devenv shell -- pytest -x
   ```

---

## Step 15: Clean Up Dead Code and Stale Patterns (P3)

### Problem

Various leftover code from before the refactor: dead code, incorrect `__all__` exports, stale patterns, and a missing dependency in `pyproject.toml`.

### What to Change

Each sub-item below is a small, independent fix:

#### 15a. Remove `_DEFAULT_LANGUAGE_MAP` from `discovery.py`

Already done in Step 9. If Step 9 hasn't been completed yet, delete lines 16-20 of `discovery.py`.

#### 15b. Remove `system` template from `defaults.yaml` OR use it

The `system` key in `prompt_templates` in `defaults.yaml` is never used by `PromptBuilder.build_system_prompt()` — it uses `bundle_config.system_prompt` instead.

**Option A (recommended):** Delete the `system:` key from `defaults.yaml:37-39`.

**Option B:** Have `PromptBuilder.build_turn_config()` fall back to the default `system` template when `bundle_config.system_prompt` is empty:
```python
system_prompt = bundle_config.system_prompt or self._default_templates.get("system", "")
```

#### 15c. Remove `_turn_logger` from `turn_executor.py __all__`

**File:** `src/remora/core/turn_executor.py`

Change line 334:
```python
# Old:
__all__ = ["AgentTurnExecutor", "_turn_logger"]

# New:
__all__ = ["AgentTurnExecutor"]
```

#### 15d. Remove re-exports from `actor.py __all__`

**File:** `src/remora/core/actor.py`

Change lines 122-130:
```python
# Old:
__all__ = [
    "Outbox", "OutboxObserver", "Trigger", "TriggerPolicy",
    "PromptBuilder", "AgentTurnExecutor", "Actor",
]

# New:
__all__ = ["Actor"]
```

Each of the removed types should be exported from their own module (`outbox.py`, `trigger.py`, `prompt.py`, `turn_executor.py`).

#### 15e. Hoist `_merge_dicts` to a shared utility

**File:** Create `src/remora/core/utils.py` (or add to an existing utility module)

```python
"""Shared utilities."""

from __future__ import annotations

from typing import Any


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge overlay into base. Overlay values win for non-dict types."""
    result = dict(base)
    for key, value in overlay.items():
        existing = result.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            result[key] = deep_merge(existing, value)
        else:
            result[key] = value
    return result
```

Then update `workspace.py` and `config.py` to import from the shared location instead of having their own copies.

#### 15f. Move `_bundle_template_fingerprint` above `__all__` in `workspace.py`

**File:** `src/remora/core/workspace.py`

Move the `_merge_dicts` and `_bundle_template_fingerprint` function definitions to above the `__all__` declaration, or move `__all__` to the end of the file. Either approach fixes the inconsistency.

#### 15g. Fix missing blank line in `factories.py`

**File:** `tests/factories.py`

Add a blank line between `make_node` (ending at line 34) and `write_file` (line 35):

```python
    data.update(overrides)
    return Node(**data)


def write_file(path: Path, text: str) -> None:
```

PEP 8 requires two blank lines between top-level function definitions.

#### 15h. Add `fsdantic` as an explicit dependency

**File:** `pyproject.toml`

Add `fsdantic` to `dependencies`:
```toml
dependencies = [
    "aiosqlite>=0.20",
    "fsdantic>=0.3",
    # ... rest
]
```

It's currently only a transitive dependency of `cairn`, but `workspace.py` imports directly from it.

### Testing & Validation

1. **Run ruff linter:**
   ```bash
   devenv shell -- ruff check src/remora/ tests/
   ```

2. **Run pyright:**
   ```bash
   devenv shell -- pyright src/remora/
   ```

3. **Run full test suite:**
   ```bash
   devenv shell -- pytest -x
   ```

4. **Verify imports work cleanly:**
   ```bash
   devenv shell -- python -c "from remora.core.actor import Actor; from remora.core.turn_executor import AgentTurnExecutor; print('OK')"
   ```

---

## General Workflow Notes

### Commit Strategy

Each step should be **one commit** with a descriptive message. For example:
- `fix: move workspace cache writes inside lock (P0 race condition)`
- `fix: remove finally block from request_human_input (P0 state machine)`
- `refactor: split Config into focused sub-models (P1)`

### Running Tests

Always run tests with `devenv shell`:
```bash
devenv shell -- pytest -x              # full suite, stop on first failure
devenv shell -- pytest tests/unit/ -v  # unit tests only, verbose
devenv shell -- pytest -k "keyword"    # filter by keyword
```

### Type Checking

After any change to type signatures:
```bash
devenv shell -- pyright src/remora/
```

### Linting

After any code change:
```bash
devenv shell -- ruff check src/remora/ tests/ --fix
```
