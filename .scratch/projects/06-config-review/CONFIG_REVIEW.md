# Configuration System Review

## Executive Summary

Remora-v2's configuration is spread across **four distinct mechanisms**:

1. **`remora.yaml`** — Project-level YAML config file
2. **`bundle.yaml`** — Per-bundle agent behavior config
3. **Environment variables** — Via `REMORA_*` prefix or `${VAR:-default}` expansion
4. **CLI arguments** — Typer-based command-line flags

This fragmentation creates complexity, duplication, and ambiguity. The current system works but has significant opportunities for consolidation and improvement.

---

## Part 1: Configuration Inventory

### 1.1 `remora.yaml` / `Config` Class

**Location:** `src/remora/core/config.py:17-66`

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `project_path` | `str` | `"."` | **UNUSED** — Project root path |
| `discovery_paths` | `tuple[str, ...]` | `("src/",)` | Directories to scan for code |
| `discovery_languages` | `tuple[str, ...] \| None` | `None` | Filter languages (optional) |
| `language_map` | `dict[str, str]` | `{".py": "python", ".md": "markdown", ".toml": "toml"}` | Extension → language mapping |
| `query_paths` | `tuple[str, ...]` | `("queries/",)` | Custom query file directories |
| `bundle_root` | `str` | `"bundles"` | Bundle directory root |
| `bundle_mapping` | `dict[str, str]` | `{"function": "code-agent", "class": "code-agent", "method": "code-agent", "file": "code-agent"}` | Node type → bundle mapping |
| `model_base_url` | `str` | `"http://localhost:8000/v1"` | LLM API endpoint |
| `model_default` | `str` | `"Qwen/Qwen3-4B"` | Default model name |
| `model_api_key` | `str` | `""` | API key for LLM |
| `timeout_s` | `float` | `300.0` | LLM request timeout |
| `max_turns` | `int` | `8` | Max agent turns per execution |
| `swarm_root` | `str` | `".remora"` | Runtime data directory |
| `max_concurrency` | `int` | `4` | Concurrent agent limit |
| `max_trigger_depth` | `int` | `5` | Cascade depth limit |
| `trigger_cooldown_ms` | `int` | `1000` | Min time between agent triggers |
| `workspace_ignore_patterns` | `tuple[str, ...]` | `(".git", ".venv", "__pycache__", "node_modules", ".remora")` | Paths to ignore during discovery |

### 1.2 `bundle.yaml` (Per-Bundle)

**Location:** `bundles/*/bundle.yaml`

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `name` | `str` | (required) | Bundle identifier |
| `system_prompt` | `str` | (required) | Agent system prompt |
| `model` | `str` | `"${REMORA_MODEL:-Qwen/Qwen3-4B}"` | Model for this bundle |
| `max_turns` | `int` | Varies by bundle | Max turns for this bundle |

**Current Bundles:**
- `system/` — 4 turns, basic tools
- `code-agent/` — 8 turns, rewrite tools
- `companion/` — (exists but not analyzed)

### 1.3 Environment Variables

| Variable | Source | Used For |
|----------|--------|----------|
| `REMORA_*` | pydantic-settings prefix | Any `Config` field |
| `${REMORA_MODEL:-default}` | YAML expansion | Bundle model selection |
| `${VAR:-default}` | Generic expansion | Any YAML value |

### 1.4 CLI Arguments

**Location:** `src/remora/__main__.py:28-40`

| Argument | Type | Default | Purpose |
|----------|------|---------|---------|
| `--project-root` | `Path` | `.` | Project directory |
| `--config` | `Path` | `None` (auto-discover) | Config file path |
| `--port` | `int` | `8080` | Web server port |
| `--no-web` | `bool` | `False` | Disable web server |
| `--run-seconds` | `float` | `0.0` | Run duration (smoke test) |

### 1.5 Hardcoded Values (Not Configurable)

| Value | Location | Purpose |
|-------|----------|---------|
| `"You are an autonomous code agent."` | `runner.py:144` | Fallback system prompt |
| `127.0.0.1` | `__main__.py:117` | Web server bind address |
| `warning` | `__main__.py:119` | Uvicorn log level |
| `False` | `__main__.py:120` | Access log disabled |
| `60_000.0` (ms) | `runner.py:89` | Cooldown cleanup window |
| Cache sizes (16, 64) | `discovery.py:76,84,90` | LRU cache limits |
| SHA-1 hash | `workspace.py:182` | Workspace ID hashing |

---

## Part 2: Configuration Flow Analysis

### 2.1 How Configuration Resolves

```
remora.yaml → Config (pydantic-settings)
           → merges with REMORA_* env vars
           → ${VAR:-default} expanded in YAML values

CLI args → Override select Config fields (port, no-web, run-seconds)
         → Provide project_root resolution

Bundle config → Per-agent overrides for model, max_turns, system_prompt
              → Read from workspace at runtime
              → Falls back to Config defaults
```

### 2.2 Configuration Access Points

| Component | Config Access | Bundle Config Access |
|-----------|---------------|---------------------|
| `AgentRunner` | Direct `self._config` | Via `_read_bundle_config()` |
| `FileReconciler` | Direct `self._config` | None |
| `CairnWorkspaceService` | `config.swarm_root` | None |
| `projections.py` | `config.bundle_root`, `config.bundle_mapping` | None |
| `__main__.py` | `load_config()` + CLI overrides | None |

### 2.3 Duplication Analysis

| Setting | Config Location | Bundle Location | Notes |
|---------|-----------------|-----------------|-------|
| `model` | `model_default: "Qwen/Qwen3-4B"` | `model: "${REMORA_MODEL:-Qwen/Qwen3-4B}"` | **Duplicate default** |
| `max_turns` | `max_turns: 8` | `max_turns: 8` (code-agent) | **Duplicate default** |
| System prompt | `"You are an autonomous code agent."` (fallback) | `system_prompt: \|...` | Fallback unused if bundle exists |

---

## Part 3: Issues & Anti-Patterns

### 3.1 Unused Configuration Field

**`project_path: str = "."`** — Defined in Config but never used. The project root is determined by:
1. CLI `--project-root` argument
2. Config file discovery via `_find_config_file()`
3. Passed explicitly to services

**Recommendation:** Remove this field.

### 3.2 Duplicate Defaults

The model default `"Qwen/Qwen3-4B"` appears in three places:
1. `Config.model_default`
2. `bundle.yaml` files as `"${REMORA_MODEL:-Qwen/Qwen3-4B}"`
3. `kernel.py:32` as `api_key or "EMPTY"` (different but related)

**Recommendation:** Single source of truth for model default.

### 3.3 Bundle Config Overrides Global Config

When a bundle specifies `model` or `max_turns`, it overrides the global Config:

```python
# runner.py:146-147
model_name = bundle_config.get("model", self._config.model_default)
max_turns = int(bundle_config.get("max_turns", self._config.max_turns))
```

This is intentional but creates a confusing hierarchy where:
- Global config is the baseline
- Bundle config can override
- But there's no validation that bundle values are sensible

**Recommendation:** Either fully commit to bundle-level config (move all agent behavior there) or keep global-only.

### 3.4 No Per-Node-Type Configuration

Currently `bundle_mapping` maps node types to bundles:

```python
bundle_mapping: dict[str, str] = {
    "function": "code-agent",
    "class": "code-agent",
    "method": "code-agent",
    "file": "code-agent",
}
```

But there's no way to configure:
- Different models for different node types
- Different max_turns for different node types
- Different cooldowns for different node types

**Recommendation:** Hierarchical config with per-node-type overrides (see R29 in CODE_REVIEW_2.md).

### 3.5 CLI Arguments Not In Config

Web server settings are CLI-only:
- `port: int = 8080`
- `no_web: bool = False`
- `host: str = "127.0.0.1"` (hardcoded)

These cannot be configured via `remora.yaml`.

**Recommendation:** Move web server config into `Config` class.

### 3.6 Hardcoded System Prompt Fallback

```python
# runner.py:142-145
system_prompt = bundle_config.get(
    "system_prompt",
    "You are an autonomous code agent.",
)
```

This fallback prompt is never used in practice because bundles always have a `system_prompt`. It's dead code.

**Recommendation:** Remove fallback or require bundles to have system_prompt.

### 3.7 Mixed Path Types

Config uses both:
- Relative paths: `"src/"`, `"bundles"`, `".remora"`
- These are resolved relative to `project_root` at runtime

But the resolution logic is scattered:
- `resolve_discovery_paths()` in `paths.py`
- `resolve_query_paths()` in `paths.py`
- Direct concatenation in services

**Recommendation:** Centralize all path resolution in one place.

### 3.8 Environment Variable Prefix Inconsistency

- pydantic-settings uses `REMORA_*` prefix
- Bundle YAML uses `${REMORA_MODEL:-...}` expansion
- These are separate mechanisms that happen to share the prefix

**Recommendation:** Document the distinction clearly or unify.

---

## Part 4: Configuration Categories

### 4.1 Project Structure Config

Controls what files to analyze:
- `discovery_paths`
- `language_map`
- `discovery_languages`
- `query_paths`
- `workspace_ignore_patterns`

### 4.2 Runtime Behavior Config

Controls agent execution:
- `max_concurrency`
- `max_trigger_depth`
- `trigger_cooldown_ms`
- `timeout_s`
- `max_turns`

### 4.3 LLM Config

Controls model access:
- `model_base_url`
- `model_default`
- `model_api_key`
- `timeout_s`

### 4.4 Storage Config

Controls where data lives:
- `swarm_root`
- `bundle_root`

### 4.5 Bundle Config (Per-Agent)

Controls agent behavior:
- `system_prompt`
- `model`
- `max_turns`
- Tool selection (via directory structure)

---

## Part 5: Recommendations

### R1. Remove `project_path` Field

Dead code. Project root is determined by CLI or config file location.

### R2. Consolidate Model Configuration

**Current:** Model specified in Config + bundles + env var expansion
**Proposed:** Single `model` config with per-node-type overrides

```yaml
model:
  default: "Qwen/Qwen3-4B"
  base_url: "http://localhost:8000/v1"
  api_key: "${REMORA_API_KEY:-}"
  timeout_s: 300.0

node_types:
  function:
    model: "Qwen/Qwen3-4B"
    max_turns: 8
  section:
    model: "gpt-3.5-turbo"
    max_turns: 4
```

### R3. Move Web Server Config to YAML

```yaml
web:
  host: "127.0.0.1"
  port: 8080
  enabled: true
  log_level: "warning"
```

CLI `--port` and `--no-web` would override these values.

### R4. Remove Bundle YAML Files

Bundle configuration should be part of `remora.yaml`:

```yaml
bundles:
  code-agent:
    system_prompt: |
      You are an autonomous AI agent...
    tools:
      - rewrite_self
      - scaffold
    max_turns: 8

  system:
    system_prompt: |
      You are a helpful assistant...
    tools:
      - broadcast
      - query_agents
      - send_message
      - subscribe
      - unsubscribe
    max_turns: 4
```

This eliminates the filesystem-based bundle discovery and the need for `bundle_root` config.

### R5. Add Configuration Validation

Pydantic validators exist for `language_map` and `discovery_paths`, but:
- No validation that `model_base_url` is a valid URL
- No validation that `bundle_mapping` keys match valid node types
- No validation that `swarm_root` is writable

### R6. Single Source of Truth for Defaults

Create a `defaults.py` or embed in Config:

```python
# remora/core/defaults.py
DEFAULT_MODEL = "Qwen/Qwen3-4B"
DEFAULT_MAX_TURNS = 8
DEFAULT_TIMEOUT_S = 300.0
DEFAULT_PORT = 8080
DEFAULT_HOST = "127.0.0.1"
```

### R7. Remove Hardcoded Fallbacks

All defaults should flow through Config. Remove hardcoded strings like:
- `"You are an autonomous code agent."`
- `"http://localhost:8000/v1"`
- `8080` (port)

### R8. Per-Node-Type Configuration

Allow behavior overrides by node type:

```yaml
defaults:
  model: "Qwen/Qwen3-4B"
  max_turns: 8
  timeout_s: 300.0

node_types:
  function:
    max_turns: 12
    bundle: code-agent
  class:
    max_turns: 4
    bundle: code-agent
  section:
    model: "gpt-4"
    max_turns: 2
    bundle: docs-agent
```

### R9. Unify Path Resolution

Create a `PathResolver` class that handles all path resolution:

```python
class PathResolver:
    def __init__(self, config: Config, project_root: Path):
        self._config = config
        self._project_root = project_root

    def discovery_paths(self) -> list[Path]: ...
    def query_paths(self) -> list[Path]: ...
    def swarm_root(self) -> Path: ...
    def bundle_path(self, name: str) -> Path: ...
```

### R10. Document Configuration Hierarchy

Create a clear precedence document:

```
1. CLI arguments (highest priority)
2. Environment variables (REMORA_*)
3. remora.yaml
4. Hardcoded defaults (lowest priority)
```

---

## Part 6: Proposed Configuration Schema

### Before (Current)

```yaml
# remora.yaml
discovery_paths:
  - src/
language_map:
  .py: python
  .md: markdown
bundle_mapping:
  function: code-agent
  class: code-agent
model_base_url: http://localhost:8000/v1
model_default: Qwen/Qwen3-4B
max_turns: 8
timeout_s: 300.0
```

```yaml
# bundles/code-agent/bundle.yaml
name: code-agent
system_prompt: |
  You are an autonomous AI agent...
model: "${REMORA_MODEL:-Qwen/Qwen3-4B}"
max_turns: 8
```

### After (Proposed)

```yaml
# remora.yaml
discovery:
  paths:
    - src/
  languages:
    .py: python
    .md: markdown
  ignore:
    - .git
    - .venv
    - __pycache__

model:
  default: Qwen/Qwen3-4B
  base_url: http://localhost:8000/v1
  api_key: "${REMORA_API_KEY:-}"
  timeout_s: 300.0

execution:
  max_concurrency: 4
  max_trigger_depth: 5
  trigger_cooldown_ms: 1000
  defaults:
    max_turns: 8
    system_prompt: |
      You are an autonomous AI agent...

web:
  host: 127.0.0.1
  port: 8080
  enabled: true

storage:
  swarm_root: .remora

# Node type overrides
node_types:
  function:
    max_turns: 12
    tools:
      - rewrite_self
      - scaffold
      - broadcast
      - send_message

  class:
    max_turns: 4
    tools:
      - broadcast
      - send_message

  section:
    model: gpt-4
    max_turns: 2
    tools:
      - broadcast
      - send_message
```

---

## Part 7: Migration Path

### Phase 1: Cleanup (Low Risk)

1. Remove unused `project_path` field
2. Add web server config to Config class
3. Create `defaults.py` for hardcoded values
4. Add validators for URLs and paths

### Phase 2: Consolidation (Medium Risk)

1. Move bundle.yaml contents into remora.yaml
2. Implement per-node-type configuration
3. Remove bundle_root and bundle_mapping
4. Update projections.py to use new config

### Phase 3: Refinement (Higher Risk)

1. Implement PathResolver
2. Add configuration hot-reload
3. Add config change events
4. Document configuration hierarchy

---

## Summary Table

| Issue | Severity | Effort | Impact |
|-------|----------|--------|--------|
| Unused `project_path` field | Low | Trivial | Code cleanliness |
| Duplicate model defaults | Medium | Small | Single source of truth |
| Bundle config in separate files | Medium | Medium | Configuration centralization |
| Hardcoded web server config | Low | Small | Config completeness |
| No per-node-type overrides | High | Medium | Flexibility |
| Hardcoded fallback prompt | Low | Trivial | Dead code removal |
| Scattered path resolution | Medium | Medium | Maintainability |
| Missing validators | Medium | Small | Error prevention |

---

## Conclusion

The current configuration system is **functional but fragmented**. The primary opportunity is consolidating bundle configuration into the main `remora.yaml` and adding per-node-type overrides. This would eliminate the dual-source configuration (YAML + bundle files) and provide a single place to understand all agent behavior.

The secondary opportunity is adding proper validation and removing hardcoded defaults that should flow through the configuration system.
