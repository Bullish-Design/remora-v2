# Remora v2 — Core/Plugin Boundary Refactor Guide

**Date:** 2026-03-16
**Implements:** Option E (Hybrid — Thin Core + Thick Config) from `BOUNDARY_BRAINSTORM.md`
**Compatibility:** None. We are redesigning for elegance, not backwards compatibility.

---

## Table of Contents

1. [Overview and Goals](#1-overview-and-goals) — What we're building and why
2. [Target Directory Layout](#2-target-directory-layout) — The final package structure
3. [Phase 1: Create the Defaults Package](#3-phase-1-create-the-defaults-package) — Move bundles, queries, and config defaults into `remora/defaults/`
4. [Phase 2: Config-Driven Language Registry](#4-phase-2-config-driven-language-registry) — Replace hardcoded language plugins with YAML-driven generic plugin
5. [Phase 3: Template-Driven Prompt Construction](#5-phase-3-template-driven-prompt-construction) — Replace `prompt.py` with bundle.yaml template interpolation
6. [Phase 4: Bundle Search Path Resolution](#6-phase-4-bundle-search-path-resolution) — Multi-directory bundle discovery with priority ordering
7. [Phase 5: Extract Config Defaults to defaults.yaml](#7-phase-5-extract-config-defaults-to-defaultsyaml) — Move behavior defaults out of Python into YAML
8. [Phase 6: Externals API Versioning](#8-phase-6-externals-api-versioning) — Add version contract between core and bundles
9. [Phase 7: Clean Up Search as Optional Capability](#9-phase-7-clean-up-search-as-optional-capability) — Make search fully opt-in with clean boundaries
10. [Phase 8: Verification and Freeze Criteria](#10-phase-8-verification-and-freeze-criteria) — How we know the refactor is complete

---

## 1. Overview and Goals

### What we're building

A single `remora` Python package with a clean internal separation between:

1. **Core** (`remora/core/`, `remora/code/`, `remora/web/`, `remora/lsp/`) — frozen infrastructure. The event bus, node graph, actor lifecycle, workspace management, Grail tool execution, web/LSP surfaces. Touched only for bug fixes or new externals capabilities.

2. **Defaults** (`remora/defaults/`) — shipped default behaviors. Bundle definitions, tree-sitter queries, config defaults. Overridable per-project without modifying the package.

### What changes

| Before | After |
|--------|-------|
| Bundles live at repo root `bundles/` | Bundles ship inside package at `remora/defaults/bundles/` |
| Tree-sitter queries at `code/queries/` | Queries ship at `remora/defaults/queries/`, discoverable from config |
| Language plugins hardcoded in `languages.py` | Config-driven `GenericLanguagePlugin` + YAML language definitions |
| Prompt construction in `prompt.py` with hardcoded logic | Template interpolation from `bundle.yaml` prompt strings |
| Config defaults hardcoded in `Config` class | Behavior defaults loaded from `defaults/defaults.yaml` |
| Single `bundle_root` config key | `bundle_search_paths` list with priority resolution |
| No externals versioning | `externals_version` field in bundle.yaml, validated at load time |

### What does NOT change

- The externals API (27 capabilities in `TurnContext`)
- The event system (EventBus, EventStore, SubscriptionRegistry)
- The node graph (NodeStore, Node model)
- The actor lifecycle (Actor, ActorPool, TriggerDispatcher)
- The workspace system (Cairn workspaces, AgentWorkspace)
- The Grail tool execution engine
- The web server and LSP surfaces
- The reconciler and file watcher

### Prerequisites

Complete project 41 (code review refactor guide) phases 4-5 first. Those phases simplify `turn_executor`, decompose `externals`, batch event commits, and fix transaction management — all changes that should land before we draw the freeze line. **DONE**

---

## 2. Target Directory Layout

```
src/remora/
├── __init__.py
├── __main__.py              ← CLI entry point (frozen)
├── py.typed                 ← PEP 561 marker
│
├── core/                    ← FROZEN infrastructure
│   ├── __init__.py
│   ├── types.py                 Foundation enums
│   ├── config.py                Config schema + loading
│   ├── db.py                    SQLite connection
│   ├── node.py                  Node model
│   ├── events/                  Event system
│   │   ├── __init__.py
│   │   ├── types.py
│   │   ├── bus.py
│   │   ├── store.py
│   │   ├── dispatcher.py
│   │   └── subscriptions.py
│   ├── graph.py                 Node/edge storage
│   ├── actor.py                 Actor inbox/lifecycle
│   ├── outbox.py                Event emission
│   ├── trigger.py               Trigger policy
│   ├── runner.py                Actor pool
│   ├── rate_limit.py            Rate limiter
│   ├── metrics.py               Metrics
│   ├── kernel.py                LLM abstraction
│   ├── grail.py                 Tool execution engine
│   ├── workspace.py             Workspace management
│   ├── externals.py             THE CONTRACT — versioned capabilities
│   ├── prompt.py                Template-driven prompt builder
│   ├── search.py                Optional search integration
│   ├── services.py              DI container
│   └── lifecycle.py             Startup/shutdown
│
├── code/                    ← FROZEN discovery engine
│   ├── __init__.py
│   ├── discovery.py             Generic tree-sitter walker
│   ├── languages.py             LanguagePlugin protocol + GenericPlugin + registry
│   ├── paths.py                 File walking
│   ├── reconciler.py            File reconciler
│   ├── watcher.py               File watcher
│   ├── directories.py           Directory projection
│   └── virtual_agents.py        Virtual agent manager
│
├── web/                     ← FROZEN web surface
│   ├── __init__.py
│   ├── server.py
│   ├── deps.py
│   ├── middleware.py
│   ├── sse.py
│   ├── paths.py
│   ├── static/
│   │   └── index.html
│   └── routes/
│       ├── __init__.py
│       ├── nodes.py
│       ├── chat.py
│       ├── events.py
│       ├── proposals.py
│       ├── search.py
│       ├── health.py
│       └── cursor.py
│
├── lsp/                     ← FROZEN LSP surface
│   ├── __init__.py
│   └── server.py
│
└── defaults/                ← OVERRIDABLE shipped defaults
    ├── __init__.py              Package resource helpers
    ├── defaults.yaml            Default config values (behavior layer)
    ├── bundles/                 Default bundle definitions
    │   ├── system/
    │   │   ├── bundle.yaml
    │   │   └── tools/*.pym
    │   ├── code-agent/
    │   │   ├── bundle.yaml
    │   │   └── tools/*.pym
    │   ├── directory-agent/
    │   │   ├── bundle.yaml
    │   │   └── tools/*.pym
    │   ├── companion/
    │   │   ├── bundle.yaml
    │   │   └── tools/*.pym
    │   ├── review-agent/
    │   │   ├── bundle.yaml
    │   │   └── tools/*.pym
    │   └── test-agent/
    │       ├── bundle.yaml
    │       └── tools/*.pym
    └── queries/                 Default tree-sitter queries
        ├── python.scm
        ├── markdown.scm
        └── toml.scm
```

**Key difference from today:** The `bundles/` directory at the repo root is a development convenience. In the installed package, bundles ship inside `remora/defaults/bundles/`. The `defaults/__init__.py` provides `importlib.resources`-based helpers to locate these assets.

---

## 3. Phase 1: Create the Defaults Package

### Goal

Move all behavior-defining assets (bundles, queries) into `src/remora/defaults/` and update all references to use the new locations.

### Step 1.1: Create `remora/defaults/__init__.py` with resource helpers

Create `src/remora/defaults/__init__.py`:

```python
"""Shipped default assets — bundles, queries, and config defaults.

This package is the canonical source for default bundle definitions,
tree-sitter query files, and config defaults. All assets are locatable
via importlib.resources so they work in installed (non-editable) packages.
"""

from __future__ import annotations

from importlib.resources import as_file, files
from pathlib import Path


def defaults_dir() -> Path:
    """Return the resolved filesystem path to the defaults package directory."""
    ref = files("remora.defaults")
    # In editable installs this is already a Path; in wheel installs we need as_file
    if isinstance(ref, Path):
        return ref
    with as_file(ref) as p:
        return Path(p)


def default_bundles_dir() -> Path:
    """Return the path to the shipped default bundles."""
    return defaults_dir() / "bundles"


def default_queries_dir() -> Path:
    """Return the path to the shipped default tree-sitter queries."""
    return defaults_dir() / "queries"


def default_config_path() -> Path:
    """Return the path to defaults.yaml."""
    return defaults_dir() / "defaults.yaml"


__all__ = [
    "defaults_dir",
    "default_bundles_dir",
    "default_queries_dir",
    "default_config_path",
]
```

### Step 1.2: Move bundles into the package

```
mkdir -p src/remora/defaults/bundles
mv bundles/system     src/remora/defaults/bundles/system
mv bundles/code-agent src/remora/defaults/bundles/code-agent
mv bundles/directory-agent src/remora/defaults/bundles/directory-agent
mv bundles/companion  src/remora/defaults/bundles/companion
mv bundles/review-agent src/remora/defaults/bundles/review-agent
mv bundles/test-agent src/remora/defaults/bundles/test-agent
rmdir bundles/  # or keep as symlink for development convenience
```

### Step 1.3: Move tree-sitter queries into defaults

```
mkdir -p src/remora/defaults/queries
mv src/remora/code/queries/python.scm    src/remora/defaults/queries/python.scm
mv src/remora/code/queries/markdown.scm  src/remora/defaults/queries/markdown.scm
mv src/remora/code/queries/toml.scm      src/remora/defaults/queries/toml.scm
rmdir src/remora/code/queries
```

### Step 1.4: Update `pyproject.toml` to include defaults assets

Add to `[tool.setuptools.package-data]`:
```toml
[tool.setuptools.package-data]
"remora.defaults" = ["defaults.yaml", "bundles/**/*", "queries/**/*"]
```

Or if using `[tool.setuptools.packages.find]`, ensure `remora.defaults` is included and non-Python files are picked up.

### Step 1.5: Update language plugin query paths

In `code/languages.py`, change `get_default_query_path()` to use the defaults package:

**Before** (each plugin):
```python
def get_default_query_path(self) -> Path:
    return Path(__file__).parent / "queries" / "python.scm"
```

**After** (each plugin):
```python
def get_default_query_path(self) -> Path:
    from remora.defaults import default_queries_dir
    return default_queries_dir() / "python.scm"
```

### Step 1.6: Update bundle provisioning to use defaults as fallback

In `code/reconciler.py`, the `_provision_bundle` method resolves `bundle_root` from config. Update the bundle resolution to check the defaults package as a fallback:

**In `reconciler.py` `_provision_bundle`:**
```python
async def _provision_bundle(self, node_id: str, role: str | None) -> None:
    template_dirs = self._resolve_bundle_template_dirs("system")
    if role:
        template_dirs.extend(self._resolve_bundle_template_dirs(role))
    await self._workspace_service.provision_bundle(node_id, template_dirs)
    # ... existing self_reflect metadata sync ...

def _resolve_bundle_template_dirs(self, bundle_name: str) -> list[Path]:
    """Resolve a bundle name to template directories using search path."""
    from remora.defaults import default_bundles_dir
    dirs = []
    # Project-local bundle (highest priority)
    local = Path(self._config.bundle_root) / bundle_name
    if local.exists():
        dirs.append(local)
    # Package default (fallback)
    default = default_bundles_dir() / bundle_name
    if default.exists():
        dirs.append(default)
    return dirs
```

This changes the provisioning semantics: project-local bundles override package defaults, and both layers merge (local tools + default tools).

### Step 1.7: Update `_do_reconcile_file` bundle resolution

The `_do_reconcile_file` method also directly constructs `Path(self._config.bundle_root) / "system"`. Update all such callsites to use `_resolve_bundle_template_dirs`.

### Step 1.8: Update tests

- Tests that reference `bundles/system/` need to point to `src/remora/defaults/bundles/system/` or use the defaults helpers.
- Any fixture that creates a temporary bundle directory is fine — those simulate project-local overrides.

### Verification

- `devenv shell -- pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q` — full suite passes.
- Confirm that `from remora.defaults import default_bundles_dir; default_bundles_dir().exists()` returns `True`.
- Confirm bundle provisioning works with both local and default bundles.

---

## 4. Phase 2: Config-Driven Language Registry

### Goal

Replace the hardcoded `PythonPlugin`, `MarkdownPlugin`, `TomlPlugin` classes with a single `GenericLanguagePlugin` that reads its configuration from YAML. Keep the `LanguagePlugin` protocol for advanced cases that need custom Python logic.

### Step 2.1: Add language definitions to `defaults.yaml`

In `src/remora/defaults/defaults.yaml`:
```yaml
languages:
  python:
    extensions: [".py"]
    query_file: "python.scm"
    node_type_rules:
      class_definition: class
      function_definition: function
      decorated_definition: function   # GenericPlugin doesn't handle nested class ancestor check
  markdown:
    extensions: [".md"]
    query_file: "markdown.scm"
    default_node_type: section
  toml:
    extensions: [".toml"]
    query_file: "toml.scm"
    default_node_type: table
```

### Step 2.2: Create `GenericLanguagePlugin`

In `code/languages.py`, add:

```python
class GenericLanguagePlugin:
    """Config-driven language plugin for simple languages."""

    def __init__(
        self,
        name: str,
        extensions: list[str],
        query_path: Path,
        node_type_rules: dict[str, str] | None = None,
        default_node_type: str = "function",
    ):
        self._name = name
        self._extensions = extensions
        self._query_path = query_path
        self._node_type_rules = node_type_rules or {}
        self._default_node_type = default_node_type

    @property
    def name(self) -> str:
        return self._name

    @property
    def extensions(self) -> list[str]:
        return self._extensions

    def get_language(self) -> Language:
        # Dynamic import: tree_sitter_{name}
        import importlib
        mod = importlib.import_module(f"tree_sitter_{self._name}")
        return Language(mod.language())

    def get_default_query_path(self) -> Path:
        return self._query_path

    def resolve_node_type(self, ts_node: Any) -> str:
        return self._node_type_rules.get(ts_node.type, self._default_node_type)
```

### Step 2.3: Keep `PythonPlugin` as a protocol implementation

Python's `resolve_node_type` has complex logic (`_has_class_ancestor`, `_decorated_target`). This cannot be expressed in config alone. **Keep `PythonPlugin` as a concrete class** but make it instantiable from config:

```python
# Special-case plugins that need custom Python logic
ADVANCED_PLUGINS: dict[str, type] = {
    "python": PythonPlugin,
}
```

### Step 2.4: Update `LanguageRegistry` to load from config

```python
class LanguageRegistry:
    def __init__(self, plugins: list[LanguagePlugin] | None = None):
        self._by_name: dict[str, LanguagePlugin] = {}
        self._by_ext: dict[str, LanguagePlugin] = {}
        if plugins is not None:
            for plugin in plugins:
                self.register(plugin)

    @classmethod
    def from_config(
        cls,
        language_defs: dict[str, dict[str, Any]],
        query_search_paths: list[Path],
    ) -> LanguageRegistry:
        """Build a registry from YAML language definitions."""
        registry = cls(plugins=[])
        for lang_name, lang_config in language_defs.items():
            if lang_name in ADVANCED_PLUGINS:
                plugin = ADVANCED_PLUGINS[lang_name]()
            else:
                query_file = lang_config.get("query_file", f"{lang_name}.scm")
                query_path = _resolve_query_file(query_file, query_search_paths)
                plugin = GenericLanguagePlugin(
                    name=lang_name,
                    extensions=lang_config.get("extensions", []),
                    query_path=query_path,
                    node_type_rules=lang_config.get("node_type_rules"),
                    default_node_type=lang_config.get("default_node_type", "function"),
                )
            registry.register(plugin)
        return registry


def _resolve_query_file(filename: str, search_paths: list[Path]) -> Path:
    """Find a query file in the search paths."""
    for search_dir in search_paths:
        candidate = search_dir / filename
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Query file {filename} not found in {search_paths}")
```

### Step 2.5: Wire `from_config` into `RuntimeServices`

In `services.py`, replace:
```python
self.language_registry = LanguageRegistry()
```
with:
```python
self.language_registry = LanguageRegistry.from_config(
    language_defs=defaults_config.get("languages", {}),
    query_search_paths=resolve_query_search_paths(config, project_root),
)
```

Where `resolve_query_search_paths` checks:
1. Project-local `{project_root}/queries/`
2. Config-specified `query_paths`
3. Package default `remora/defaults/queries/`

### Step 2.6: Remove `BUILTIN_PLUGINS` constant

The `BUILTIN_PLUGINS` list is no longer needed — all plugins come from config. Remove it and the default `LanguageRegistry()` constructor that uses it.

### Step 2.7: Add `language_map` to `defaults.yaml`

Move the default `language_map` (`.py` → `python`, `.md` → `markdown`, `.toml` → `toml`) from `Config` class defaults into `defaults.yaml`:

```yaml
language_map:
  ".py": python
  ".md": markdown
  ".toml": toml
```

### Verification

- `devenv shell -- pytest tests/unit/test_discovery.py -q` — discovery still finds Python/Markdown/TOML nodes.
- Add a test that creates a `GenericLanguagePlugin` from config and verifies it can parse a simple file.
- Full suite passes.

---

## 5. Phase 3: Template-Driven Prompt Construction

### Goal

Replace the hardcoded prompt assembly logic in `prompt.py` with template interpolation from `bundle.yaml`. Prompts become fully customizable per-bundle without touching Python.

### Step 3.1: Define the template variable contract

Available variables for prompt templates:

| Variable | Source | Description |
|----------|--------|-------------|
| `{node_name}` | `Node.name` | e.g., `"calculate_total"` |
| `{node_full_name}` | `Node.full_name` | e.g., `"src/math.py::calculate_total"` |
| `{node_type}` | `Node.node_type` | e.g., `"function"` |
| `{file_path}` | `Node.file_path` | e.g., `"src/math.py"` |
| `{source}` | `Node.text` | The full source code text |
| `{role}` | `Node.role` | e.g., `"code-agent"` |
| `{event_type}` | `Event.event_type` | e.g., `"node_changed"` |
| `{event_content}` | Extracted from event | Message content or change description |
| `{turn_mode}` | `"chat"` or `"reactive"` | Derived from trigger |
| `{companion_context}` | Workspace KV | Prior reflections, activity, links |

### Step 3.2: Add default prompt templates to `defaults.yaml`

```yaml
prompt_templates:
  system: |
    You are an autonomous AI agent embodying the {node_type} "{node_name}" in {file_path}.
    Speak in the first person. When asked what you do, answer as if you ARE this code element.
  user: |
    # Node: {node_full_name}
    Type: {node_type} | File: {file_path}

    ## Source Code
    ```
    {source}
    ```

    ## Trigger
    Event: {event_type}
    {event_content}
  reflection: |
    You just completed a conversation turn. Reflect on the exchange and record metadata.

    Use your companion tools:
    - companion_summarize: Write a one-sentence summary and 1-3 tags
    - companion_reflect: Record one key insight or observation
    - companion_link: If you referenced another code element, record the link

    Tag vocabulary: bug, question, refactor, explanation, test, performance, design, insight, todo, review

    Be specific. Skip trivial exchanges.
```

### Step 3.3: Rewrite `PromptBuilder` to use template interpolation

Replace the current `PromptBuilder` with a simpler template-based version:

```python
class PromptBuilder:
    """Build system/user prompts via string template interpolation."""

    def __init__(self, config: Config, default_templates: dict[str, str]) -> None:
        self._config = config
        self._default_templates = default_templates

    def build_system_prompt(
        self,
        bundle_config: BundleConfig,
        trigger_event: Event | None,
    ) -> tuple[str, str, int]:
        is_reflection = self._is_reflection_turn(bundle_config, trigger_event)
        if is_reflection:
            return self._build_reflection(bundle_config)

        # System prompt: bundle.yaml system_prompt + system_prompt_extension + mode prompt
        system_prompt = bundle_config.system_prompt
        if bundle_config.system_prompt_extension:
            system_prompt = f"{system_prompt}\n\n{bundle_config.system_prompt_extension}"
        mode = self.turn_mode(trigger_event)
        mode_prompt = bundle_config.prompts.get(mode, "")
        if mode_prompt:
            system_prompt = f"{system_prompt}\n\n{mode_prompt}"

        model = bundle_config.model or self._config.model_default
        max_turns = bundle_config.max_turns
        return system_prompt, model, max_turns

    def build_user_prompt(self, node: Node, trigger_event: Event | None) -> str:
        """Build the user prompt from template + node/event context."""
        variables = self._build_template_vars(node, trigger_event)
        # Bundle can override the user prompt template
        template = self._default_templates.get("user", "")
        return self._interpolate(template, variables)

    def _build_template_vars(self, node: Node, trigger_event: Event | None) -> dict[str, str]:
        return {
            "node_name": node.name,
            "node_full_name": node.full_name,
            "node_type": serialize_enum(node.node_type),
            "file_path": node.file_path,
            "source_code": node.text or "",
            "role": node.role or "",
            "event_type": trigger_event.event_type if trigger_event else "manual",
            "event_content": _event_content(trigger_event) if trigger_event else "",
            "turn_mode": self.turn_mode(trigger_event),
        }

    @staticmethod
    def _interpolate(template: str, variables: dict[str, str]) -> str:
        """Simple {var} interpolation. Unknown vars left as-is."""
        result = template
        for key, value in variables.items():
            result = result.replace(f"{{{key}}}", value)
        return result
```

### Step 3.4: Update `BundleConfig` to accept custom prompt templates

Add an optional `prompt_templates` field to `BundleConfig`:
```python
class BundleConfig(BaseModel):
    # ... existing fields ...
    prompt_templates: dict[str, str] = Field(default_factory=dict)
```

Bundles can now override the user prompt template entirely:
```yaml
# bundle.yaml
prompt_templates:
  user: |
    # Directory: {node_full_name}
    You are a directory coordinator. Use your tools to manage children.
```

### Step 3.5: Rename `build_prompt` → `build_user_prompt`

The static method `PromptBuilder.build_prompt` becomes `build_user_prompt` for clarity. Update all callsites in `turn_executor.py`.

### Step 3.6: Load default templates at startup

In `RuntimeServices.initialize()` or `PromptBuilder.__init__`, load the `prompt_templates` section from `defaults.yaml`.

### Step 3.7: Remove `_DEFAULT_REFLECTION_PROMPT`

The hardcoded reflection prompt string moves to `defaults.yaml` under `prompt_templates.reflection`. The `PromptBuilder._build_reflection` method reads it from the loaded defaults.

### Verification

- `devenv shell -- pytest tests/unit/test_prompt.py -q` — prompt tests pass with template-based builder.
- Verify that editing `bundle.yaml` prompt_templates changes the actual prompts without touching Python.
- Full suite passes.

---

## 6. Phase 4: Bundle Search Path Resolution

### Goal

Replace the single `bundle_root` config key with a `bundle_search_paths` list. Bundles are resolved by searching paths in priority order. Project-local bundles override package defaults.

### Step 4.1: Update `Config` with `bundle_search_paths`

Replace `bundle_root: str = "bundles"` with:
```python
bundle_search_paths: tuple[str, ...] = ("bundles/", "@default")
```

The sentinel `@default` means "the package's `remora/defaults/bundles/` directory."

### Step 4.2: Create `resolve_bundle_search_paths()` helper

In `config.py` or a new `core/bundle_resolution.py`:

```python
from remora.defaults import default_bundles_dir

def resolve_bundle_search_paths(config: Config, project_root: Path) -> list[Path]:
    """Resolve bundle search path entries to filesystem paths."""
    paths: list[Path] = []
    for entry in config.bundle_search_paths:
        if entry == "@default":
            paths.append(default_bundles_dir())
        else:
            resolved = (project_root / entry).resolve()
            if resolved.exists():
                paths.append(resolved)
    return paths
```

### Step 4.3: Create `resolve_bundle_dirs()` for a specific bundle name

```python
def resolve_bundle_dirs(bundle_name: str, search_paths: list[Path]) -> list[Path]:
    """Find all directories for a bundle name across search paths.

    Returns dirs in priority order (first = highest priority).
    All found directories are included so tool scripts merge across layers.
    """
    dirs: list[Path] = []
    for base in search_paths:
        candidate = base / bundle_name
        if candidate.is_dir():
            dirs.append(candidate)
    return dirs
```

### Step 4.4: Update reconciler bundle provisioning

Replace all `Path(self._config.bundle_root) / name` patterns with `resolve_bundle_dirs(name, self._bundle_search_paths)` where `self._bundle_search_paths` is computed once at reconciler init.

The provisioning call becomes:
```python
async def _provision_bundle(self, node_id: str, role: str | None) -> None:
    system_dirs = resolve_bundle_dirs("system", self._bundle_search_paths)
    role_dirs = resolve_bundle_dirs(role, self._bundle_search_paths) if role else []
    template_dirs = system_dirs + role_dirs
    await self._workspace_service.provision_bundle(node_id, template_dirs)
    # ... metadata sync ...
```

### Step 4.5: Update `_do_reconcile_file` bundle resolution

Same pattern: replace `bundle_root = Path(self._config.bundle_root)` with precomputed search paths.

### Step 4.6: Remove `bundle_root` from Config

After migrating all callsites, remove the old `bundle_root` field. Update `remora.yaml.example` to show `bundle_search_paths`.

### Step 4.7: Update query file resolution similarly

Add `query_search_paths` to Config (default: `("queries/", "@default")`). The `@default` sentinel resolves to `remora/defaults/queries/`.

Update `code/paths.py` `resolve_query_paths()` to use this search path instead of the current logic.

### Verification

- Create a project-local `bundles/code-agent/bundle.yaml` override. Confirm it takes priority over the package default.
- Confirm that removing the local override falls back to the package default.
- Full suite passes.

---

## 7. Phase 5: Extract Config Defaults to defaults.yaml

### Goal

Move all behavior-related default values from the `Config` class into `defaults/defaults.yaml`. The `Config` class retains infrastructure defaults (db path, log level, concurrency) but behavior defaults (model, max_turns, bundle_overlays, etc.) come from the YAML file.

### Step 5.1: Create `defaults.yaml`

```yaml
# src/remora/defaults/defaults.yaml
# Behavior-layer defaults. Override in remora.yaml.

# Bundle resolution: which node types get which bundles
bundle_overlays:
  function: code-agent
  class: code-agent
  method: code-agent
  directory: directory-agent

# LLM defaults
model_default: "Qwen/Qwen3-4B"
max_turns: 8

# Language definitions (used by LanguageRegistry.from_config)
languages:
  python:
    extensions: [".py"]
    query_file: "python.scm"
  markdown:
    extensions: [".md"]
    query_file: "markdown.scm"
    default_node_type: section
  toml:
    extensions: [".toml"]
    query_file: "toml.scm"
    default_node_type: table

# Default extension→language mapping
language_map:
  ".py": python
  ".md": markdown
  ".toml": toml

# Prompt templates
prompt_templates:
  reflection: |
    You just completed a conversation turn. Reflect on the exchange and record metadata.
    Use your companion tools:
    - companion_summarize: Write a one-sentence summary and 1-3 tags
    - companion_reflect: Record one key insight or observation
    - companion_link: If you referenced another code element, record the link
    Tag vocabulary: bug, question, refactor, explanation, test, performance, design, insight, todo, review
    Be specific. Skip trivial exchanges.

# Externals API version (incremented when capabilities change)
externals_version: 1
```

### Step 5.2: Create `load_defaults()` helper

In `defaults/__init__.py`:
```python
import yaml

def load_defaults() -> dict[str, Any]:
    """Load defaults.yaml and return the parsed dict."""
    path = default_config_path()
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
```

### Step 5.3: Integrate defaults into `Config` loading

In `config.py`, modify `load_config`:
```python
def load_config(path: Path | None = None) -> Config:
    from remora.defaults import load_defaults

    defaults = load_defaults()
    config_path = path if path is not None else _find_config_file()

    if config_path is not None:
        user_data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    else:
        user_data = {}

    # Defaults are lowest priority, user config overrides
    merged = {**defaults, **expand_env_vars(user_data)}
    return Config(**merged)
```

### Step 5.4: Simplify `Config` class defaults

Remove behavior defaults from `Config` fields. The `Config` field defaults become `None` or empty for behavior fields, indicating "use value from defaults.yaml":

```python
class Config(BaseSettings):
    bundle_overlays: dict[str, str] = Field(default_factory=dict)  # was: hardcoded map
    model_default: str = ""  # was: "Qwen/Qwen3-4B"
    max_turns: int = 0  # was: 8 (0 = use defaults.yaml value)
    language_map: dict[str, str] = Field(default_factory=dict)  # was: hardcoded map
```

Since `load_config` merges defaults first, these empty defaults are only hit if both `defaults.yaml` and `remora.yaml` are missing — which is a broken install.

### Step 5.5: Update tests

Tests that construct `Config()` directly (without `load_config`) need to either:
1. Use `load_config()` which picks up defaults.yaml
2. Pass explicit values for the fields they need

Update test fixtures accordingly.

### Verification

- Confirm `load_config()` returns sensible defaults even without a `remora.yaml`.
- Confirm `remora.yaml` values override `defaults.yaml` values.
- Full suite passes.

---

## 8. Phase 6: Externals API Versioning

### Goal

Add a version contract between core's externals API and bundles. Bundles declare which externals version they expect. Core validates compatibility at bundle load time.

### Step 6.1: Add `externals_version` to `BundleConfig`

```python
class BundleConfig(BaseModel):
    externals_version: int | None = None  # None = no version constraint
    # ... existing fields ...
```

### Step 6.2: Define `EXTERNALS_VERSION` constant in `externals.py`

```python
EXTERNALS_VERSION = 1  # Increment when capabilities change
```

### Step 6.3: Add validation in `CairnWorkspaceService.read_bundle_config`

After parsing the bundle config, validate externals compatibility:

```python
from remora.core.externals import EXTERNALS_VERSION

async def read_bundle_config(self, node_id: str) -> BundleConfig:
    # ... existing parsing ...
    config = BundleConfig.model_validate(expanded)
    if config.externals_version is not None and config.externals_version > EXTERNALS_VERSION:
        logger.warning(
            "Bundle for %s requires externals v%d but core provides v%d",
            node_id, config.externals_version, EXTERNALS_VERSION,
        )
    return config
```

### Step 6.4: Add `externals_version: 1` to all shipped bundle.yaml files

Update each bundle in `defaults/bundles/*/bundle.yaml`:
```yaml
externals_version: 1
```

### Step 6.5: Document the externals contract

Create `docs/externals-contract.md` listing all 27 capabilities, their signatures, and the version in which they were introduced.

### Verification

- Test that a bundle with `externals_version: 999` logs a warning.
- Test that a bundle without `externals_version` loads fine (no constraint).
- Full suite passes.

---

## 9. Phase 7: Clean Up Search as Optional Capability

### Goal

Make the search integration cleanly optional. Core should not import search dependencies at module level. Search should be a capability that plugins can use if available, ignore if not.

### Step 7.1: Make `SearchServiceProtocol` the only search type in core

`core/search.py` currently contains both the protocol and the implementation. Split:
- Keep `SearchServiceProtocol` in `core/search.py` (frozen)
- Move `SearchService` (the embeddy implementation) to a `search_impl.py` or keep in `search.py` behind a lazy import

### Step 7.2: Guard embeddy imports

```python
class SearchService:
    def __init__(self, config: SearchConfig, project_root: Path):
        try:
            import embeddy  # noqa: F401
            self._available = True
        except ImportError:
            self._available = False
            logger.info("embeddy not installed, search disabled")
```

### Step 7.3: Make search an optional dependency in `pyproject.toml`

```toml
[project.optional-dependencies]
search = ["embeddy>=0.1"]
```

This means a minimal `remora` install doesn't require embeddy. Search is opt-in.

### Verification

- Confirm `uv add remora` (without `[search]`) works and search is disabled.
- Confirm `uv add remora[search]` enables search.
- Full suite passes.

---

## 10. Phase 8: Verification and Freeze Criteria

### The freeze checklist

After all phases are complete, verify:

1. **No behavior logic in core Python.** grep for hardcoded prompt strings, default model names, bundle overlays — all should come from `defaults.yaml` or `bundle.yaml`.

2. **Bundle authoring test.** Create a new bundle from scratch (new directory, `bundle.yaml`, one `.pym` tool) and verify it works without any Python changes.

3. **Language addition test.** Add a new language (e.g., JSON with a trivial query) by adding a YAML entry and a `.scm` file. Verify nodes are discovered without any Python changes.

4. **Override test.** Create a project-local `bundles/code-agent/bundle.yaml` that overrides the default. Verify the override takes effect and default tools still merge.

5. **Clean install test.** `pip install .` from a clean venv. Verify `remora run` starts, discovers nodes, and agents respond to events.

6. **Full test suite.** `devenv shell -- pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q` — all pass.

### What "frozen" means going forward

After this refactor, the following directories are frozen:
- `src/remora/core/` — only bug fixes, performance, and new externals (v1.x additions)
- `src/remora/code/` — only bug fixes
- `src/remora/web/` — only bug fixes and new API endpoints
- `src/remora/lsp/` — only bug fixes

Day-to-day development happens in:
- `src/remora/defaults/bundles/` — bundle definitions and tool scripts
- `src/remora/defaults/queries/` — tree-sitter queries
- `src/remora/defaults/defaults.yaml` — behavior defaults
- `remora.yaml` (per-project) — project-specific overrides

### Phase summary and dependencies

```
Phase 1: Create defaults package         (no deps)
Phase 2: Config-driven language registry  (depends on Phase 1 for query paths)
Phase 3: Template-driven prompts          (no deps, can parallel with Phase 2)
Phase 4: Bundle search paths              (depends on Phase 1 for defaults dir)
Phase 5: Extract config defaults          (depends on Phases 1-4)
Phase 6: Externals versioning             (no deps, can parallel with anything)
Phase 7: Optional search                  (no deps, can parallel with anything)
Phase 8: Verification                     (depends on all above)
```

**Recommended execution order:** 1 → (2 + 3 + 6 + 7 in parallel) → 4 → 5 → 8
