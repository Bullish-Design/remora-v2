# Remora v2 — Core/Plugin Boundary Brainstorm

**Date:** 2026-03-16
**Goal:** Determine how to split remora into a stable "core" layer (freeze-worthy infrastructure) and a "plugin" layer (the LLM agent behaviors, tools, bundles, prompts, and use-case-specific logic that we want to rapidly iterate on).

---

## Table of Contents

1. [The Problem Statement](#1-the-problem-statement) — Why we want this split, what "freeze" means, and what rapid iteration looks like
2. [Current Architecture Inventory](#2-current-architecture-inventory) — What exists today, dependency graph, and natural fault lines
3. [Option A: Bundle-Only Plugin Layer](#3-option-a-bundle-only-plugin-layer) — Keep all Python in core, plugins are purely bundles/tools/config
4. [Option B: Python Package Split (remora-core + remora-agents)](#4-option-b-python-package-split-remora-core--remora-agents) — Two installable packages with a clear import boundary
5. [Option C: Plugin Registry with Entry Points](#5-option-c-plugin-registry-with-entry-points) — Core discovers plugins via setuptools entry_points
6. [Option D: Workspace-as-Plugin (External Bundle Repos)](#6-option-d-workspace-as-plugin-external-bundle-repos) — Bundles live outside the remora package entirely
7. [Option E: Hybrid — Thin Core + Thick Config](#7-option-e-hybrid--thin-core--thick-config) — Core ships minimal defaults, everything else is config-driven
8. [Where to Draw the Line: Module-by-Module Analysis](#8-where-to-draw-the-line-module-by-module-analysis) — For each source file, is it core or plugin?
9. [The Externals API as the Formal Contract](#9-the-externals-api-as-the-formal-contract) — How the externals surface defines the plugin boundary
10. [Language Plugins and Discovery Extensions](#10-language-plugins-and-discovery-extensions) — Tree-sitter plugins, query files, and the NodeType question
11. [Config Surface and Override Hierarchy](#11-config-surface-and-override-hierarchy) — How plugin config interacts with core config
12. [Comparison Matrix](#12-comparison-matrix) — Side-by-side evaluation of all options
13. [Recommended Approach](#13-recommended-approach) — The specific architecture we should pursue

---


## 1. The Problem Statement

### What "freeze the core" means

Remora's infrastructure — the event bus, node graph, reconciler, actor lifecycle, workspace management, Grail tool execution — is largely built. It works. The refactoring from the code review (project 41) will clean it up further. At some point soon, this infrastructure should be **stable** — rarely modified, well-tested, and treated as a platform.

The interesting work ahead is the **agent behavior** layer:
- What system prompts do agents get?
- What tools are available to them?
- How do agents respond to different event types?
- What bundles exist and how are they composed?
- What subscription patterns make sense for different node types?
- How should the companion/reflection system evolve?
- What new tool scripts enable useful emergent behaviors?

This is the "actually using the library for its intended purpose" part. We want to iterate on this daily without touching core infrastructure.

### What rapid iteration looks like

A developer working on agent behaviors should be able to:
1. Write/modify a `.pym` tool script
2. Write/modify a `bundle.yaml` system prompt or prompt template
3. Add a new bundle role with custom tools
4. Change subscription patterns (which events trigger which agents)
5. Adjust model parameters, max turns, reflection config
6. Add new virtual agent definitions
7. Potentially add new externals (capability functions available to tools)

...all **without modifying any Python source files in remora's core**.

### The core question

Where exactly is the boundary? The codebase has a spectrum:

```
Pure infrastructure ←——————————————→ Pure agent behavior
   (EventBus, SQLite)              (bundle.yaml, .pym tools)
         |              |                    |
      types.py     reconciler.py       bundles/code-agent/
      graph.py     turn_executor.py    bundles/system/tools/
      events/      prompt.py           remora.yaml config
      db.py        externals.py
```

The tricky modules are in the middle: `prompt.py` (builds prompts from config), `externals.py` (defines the API surface tools can call), `turn_executor.py` (orchestrates the turn pipeline), `config.py` (defines what's configurable). These are the seam.


---

## 2. Current Architecture Inventory

### Source file classification

The codebase has 46 Python source files across 4 packages:

**`remora.core` (21 files) — The runtime engine:**
```
core/types.py          — Enums: NodeStatus, NodeType, EventType, ChangeType
core/config.py         — Config, BundleConfig, SearchConfig, VirtualAgentConfig
core/db.py             — open_database() (WAL-mode SQLite)
core/node.py           — Node Pydantic model
core/events/types.py   — Event base + 23 concrete event classes
core/events/bus.py     — EventBus in-memory pub/sub
core/events/store.py   — EventStore (SQLite + bus + dispatcher fan-out)
core/events/dispatcher.py — TriggerDispatcher
core/events/subscriptions.py — SubscriptionRegistry + pattern matching
core/graph.py          — NodeStore (nodes + edges SQLite tables)
core/actor.py          — Actor (inbox loop, turn sequencing)
core/turn_executor.py  — AgentTurnExecutor (the turn pipeline)
core/outbox.py         — Outbox (write-through event emission)
core/prompt.py         — PromptBuilder (assembles system/user prompts)
core/trigger.py        — TriggerPolicy (cooldown, depth)
core/runner.py         — ActorPool (actor lifecycle, routing)
core/externals.py      — TurnContext (27 capability methods for tools)
core/grail.py          — GrailTool loading and execution
core/kernel.py         — structured-agents kernel wrapper
core/workspace.py      — AgentWorkspace + CairnWorkspaceService
core/metrics.py        — Simple in-memory metrics
core/rate_limit.py     — SlidingWindowRateLimiter
core/search.py         — SearchService (embeddy integration)
core/services.py       — RuntimeServices (DI container)
core/lifecycle.py      — RemoraLifecycle (startup/run/shutdown)
```

**`remora.code` (8 files) — Source discovery and reconciliation:**
```
code/discovery.py      — Tree-sitter node discovery
code/languages.py      — LanguagePlugin protocol + Python/Markdown/TOML plugins
code/paths.py          — Path resolution and file walking
code/reconciler.py     — FileReconciler orchestrator
code/watcher.py        — FileWatcher (watchfiles integration)
code/directories.py    — DirectoryManager (directory node projection)
code/virtual_agents.py — VirtualAgentManager (declarative virtual agents)
code/queries/*.scm     — Tree-sitter query files (3 files)
```

**`remora.web` (9 files) — HTTP surface:**
```
web/server.py          — App factory + create_app
web/deps.py            — WebDeps dataclass
web/middleware.py       — CSRFMiddleware
web/sse.py             — SSE streaming
web/paths.py           — Workspace path resolution
web/routes/nodes.py    — Node CRUD endpoints
web/routes/chat.py     — Chat + respond
web/routes/events.py   — Event listing + SSE endpoint
web/routes/cursor.py   — Cursor focus
web/routes/health.py   — Health check
web/routes/proposals.py — Rewrite proposals (if exists)
web/routes/search.py   — Semantic search (if exists)
```

**`remora.lsp` (2 files) — LSP surface:**
```
lsp/server.py          — pygls LSP adapter
lsp/__init__.py        — Lazy import wrapper
```

**`remora/__main__.py` — CLI entry point**

### Non-Python assets

```
bundles/
  system/bundle.yaml + tools/*.pym     — Base tools for all agents (15 tools)
  code-agent/bundle.yaml + tools/*.pym — Code element agent behavior
  directory-agent/bundle.yaml + tools/*.pym — Directory coordinator
  companion/bundle.yaml + tools/*.pym  — Project-level observer
  review-agent/bundle.yaml + tools/*.pym — Code review agent
  test-agent/bundle.yaml + tools/*.pym — Test scaffolding agent

src/remora/code/queries/
  python.scm, markdown.scm, toml.scm  — Tree-sitter queries

src/remora/web/static/
  index.html                           — Web UI

remora.yaml.example                    — Example config
```

### Dependency graph: who imports whom

The dependency flow is largely one-directional:

```
types.py ← config.py ← node.py
              ↑
events/types.py ← events/bus.py ← events/store.py ← events/dispatcher.py
                                         ↑
                              events/subscriptions.py
                                         ↑
graph.py ← externals.py ← grail.py ← workspace.py
   ↑              ↑           ↑
  actor.py ← turn_executor.py (imports EVERYTHING)
   ↑
  runner.py ← services.py ← lifecycle.py
                                ↑
                         web/server.py, lsp/server.py, __main__.py
```

**Key observations:**
- `turn_executor.py` is the convergence point — it imports from almost every core module
- `externals.py` defines the API surface available to tools — this is the natural plugin boundary
- `config.py` defines what's user-configurable — bundles, models, subscription patterns
- `grail.py` is the bridge between Python runtime and `.pym` tool scripts
- `prompt.py` builds prompts from `BundleConfig` — it's behavior, not infrastructure
- The `bundles/` directory is already a de facto plugin layer (just not formalized)

### Natural fault lines

1. **The externals contract.** Tools (`.pym` scripts) call into `TurnContext` capabilities. This dict of async functions is the ABI between core and plugins. If this is stable, plugins can evolve freely.

2. **The bundle system.** Bundles are already loaded from disk at runtime. They're not compiled into the Python package. They're already "plugins" in a sense — just not formalized with a discovery mechanism.

3. **The config hierarchy.** `remora.yaml` → `bundle.yaml` → runtime defaults. This three-tier config is already a plugin-like override system.

4. **The LanguagePlugin protocol.** Discovery is extensible via the `LanguagePlugin` protocol. New languages can be added by implementing this protocol and registering with `LanguageRegistry`.


---

## 3. Option A: Bundle-Only Plugin Layer

**Concept:** Keep all Python code in a single `remora` package. "Plugins" are purely bundles — directories of `bundle.yaml` + `tools/*.pym` files loaded from `bundle_root` at runtime.

**How it works today:** This is essentially what we already have. The `bundles/` directory contains role-specific configurations and tools. The `bundle_overlays` config maps node types to bundle names. Bundles are loaded from disk by `CairnWorkspaceService.provision_bundle()`.

**What changes:**
- Formalize the bundle discovery mechanism (currently just filesystem globbing)
- Add a `remora bundle list` CLI command to inspect available bundles
- Document the bundle authoring contract (required files, available externals)
- Move bundles out of the remora repo into a separate repo or installable package
- Add a bundle compatibility version field to `bundle.yaml`

**Bundle layout:**
```
remora-bundles/           # Separate repo
  system/
    bundle.yaml
    tools/*.pym
  code-agent/
    bundle.yaml
    tools/*.pym
  directory-agent/
    bundle.yaml
    tools/*.pym
  companion/
    bundle.yaml
    tools/*.pym
```

**Pros:**
- Zero Python code changes to core — just move files and add documentation
- Simplest possible approach — the infrastructure is already built
- Bundle authors only need to understand YAML + Grail (.pym) scripting
- Natural git submodule or separate-repo pattern
- No import boundaries to manage
- Testing: bundles can be tested via the existing integration test framework

**Cons:**
- Cannot add new externals (capability functions) without modifying core Python
- Cannot add new language plugins without modifying core Python
- Cannot add new event types without modifying core Python
- The "plugin" boundary is implicit (filesystem convention), not enforced
- No versioning contract between core and bundles (a core change could silently break tools)
- Prompt construction logic (`prompt.py`) is baked into core — can't customize how prompts are built

**Best for:** Teams where one person maintains core and multiple people author agent behaviors purely through bundles and tools.

---

## 4. Option B: Python Package Split (remora-core + remora-agents)

**Concept:** Split the Python codebase into two installable packages with an explicit import boundary.

**Package 1: `remora-core`** (the freezable platform)
```
remora/
  core/          — Everything in core/ today
  code/          — Discovery, reconciliation, languages
  web/           — Web server (or make this a third package)
  lsp/           — LSP server (or make this a third package)
  __main__.py    — CLI
```

**Package 2: `remora-agents`** (the rapidly-iterated agent behavior layer)
```
remora_agents/
  bundles/       — All bundle directories
  queries/       — Tree-sitter query files (if we want custom ones)
  prompts/       — Prompt templates (extracted from prompt.py defaults)
  defaults.py    — Default config overrides, bundle registry
```

**The import boundary:** `remora-agents` may import from `remora-core`, but never the reverse. Core defines the platform; agents defines the behavior.

**What moves from core to agents:**
- `bundles/` directory (all of it)
- Default bundle_overlays mapping (currently hardcoded in `Config`)
- Default system prompt text (currently hardcoded in `BundleConfig`)
- Language-specific tree-sitter query files (`code/queries/*.scm`)
- Possibly `code/languages.py` (the builtin Python/Markdown/TOML plugins)

**What stays in core:**
- Everything in `core/` (types, events, graph, actor, turn_executor, externals, grail, kernel, etc.)
- `code/discovery.py`, `code/reconciler.py`, `code/paths.py`, `code/watcher.py`, `code/directories.py`, `code/virtual_agents.py`
- `web/`, `lsp/`, `__main__.py`
- The `LanguagePlugin` protocol (but not the builtin implementations)

**Pros:**
- Explicit import boundary enforced by Python's package system
- Each package has its own `pyproject.toml`, version, and release cycle
- Core can be versioned and published independently
- Agents package can depend on a specific core version range
- Forces clean API design — anything agents needs from core must be a public API

**Cons:**
- Two packages to manage (versions, CI, releases)
- The `remora_agents` package would be very thin — mostly config and file assets
- Still can't add new externals or event types from agents without touching core
- Language plugins are awkward — the protocol is in core, implementations have heavy deps (tree-sitter-python, etc.)
- `prompt.py` lives in core but constructs agent-specific prompts — does it stay or move?
- `config.py` defaults (like `bundle_overlays`) encode agent behavior knowledge in core

**Best for:** When you want to publish `remora-core` as a stable library that others can build on top of.

---

## 5. Option C: Plugin Registry with Entry Points

**Concept:** Core defines extension points as protocols. Plugins register implementations via Python `entry_points` (setuptools/importlib.metadata). Core discovers and loads plugins at startup.

**Extension points:**
```python
# In remora.core — plugin protocols

class LanguagePlugin(Protocol):
    """Already exists — tree-sitter language support."""
    ...

class BundleProvider(Protocol):
    """Provides bundle definitions for agent roles."""
    def get_bundle_dirs(self) -> list[Path]: ...
    def get_bundle_names(self) -> list[str]: ...

class ExternalsExtension(Protocol):
    """Adds new capability functions to TurnContext."""
    def get_capabilities(self, context: TurnContext) -> dict[str, Any]: ...

class EventTypeExtension(Protocol):
    """Registers new event types."""
    def get_event_classes(self) -> list[type[Event]]: ...

class PromptCustomizer(Protocol):
    """Customizes prompt construction."""
    def customize_system_prompt(self, base: str, bundle_config: BundleConfig) -> str: ...
```

**Plugin registration (in the agents package's pyproject.toml):**
```toml
[project.entry-points."remora.plugins.languages"]
python = "remora_agents.languages:PythonPlugin"
markdown = "remora_agents.languages:MarkdownPlugin"

[project.entry-points."remora.plugins.bundles"]
default = "remora_agents.bundles:DefaultBundleProvider"

[project.entry-points."remora.plugins.externals"]
search = "remora_agents.externals:SearchExternals"
```

**Discovery at startup (in core):**
```python
from importlib.metadata import entry_points

def discover_language_plugins() -> list[LanguagePlugin]:
    eps = entry_points(group="remora.plugins.languages")
    return [ep.load()() for ep in eps]
```

**Pros:**
- Maximum extensibility — everything is pluggable
- Multiple plugin packages can coexist (e.g., `remora-code-agents`, `remora-doc-agents`)
- Clean separation of concerns with formal contracts
- Standard Python ecosystem pattern (pytest, tox, flask all use this)
- New externals can be added without touching core

**Cons:**
- Highest implementation complexity — many new protocols to define and maintain
- Entry point discovery adds startup overhead and debugging complexity
- Over-engineered for a single-team project where one person maintains everything
- The externals extension point is dangerous — plugins could inject arbitrary capabilities
- Testing becomes harder — integration tests need plugins installed
- `GrailTool` already provides runtime extensibility via `.pym` scripts — this layer might be redundant

**Best for:** When remora will be used by multiple independent teams who need to extend the core in incompatible ways.

---

## 6. Option D: Workspace-as-Plugin (External Bundle Repos)

**Concept:** Bundles are not shipped with remora at all. Each project workspace brings its own bundles. The `bundle_root` config points to a directory in the user's project.

**How it works:**
- User clones remora and installs it
- User creates their project with `remora.yaml` pointing to their own `bundles/` directory
- Remora ships with zero bundles — or a minimal "starter" bundle installable via `remora init`
- Advanced users can create bundle packages installable via pip that drop files into a known location

**Config:**
```yaml
# remora.yaml
bundle_root: "./bundles"          # local project bundles
bundle_packages:                  # pip-installed bundle collections
  - "remora-default-agents"
  - "my-custom-agents"
```

**Discovery:**
```python
def resolve_bundle_dirs(config: Config) -> list[Path]:
    dirs = [Path(config.bundle_root)]
    for package_name in config.bundle_packages:
        pkg_path = importlib.resources.files(package_name) / "bundles"
        dirs.append(Path(str(pkg_path)))
    return dirs
```

**Pros:**
- Users own their agent behaviors completely
- Bundles are version-controlled in the user's project repo
- No coupling between remora releases and agent behavior updates
- Natural "fork and customize" workflow
- Bundles can be shared as git repos or pip packages

**Cons:**
- First-run experience is poor — remora does nothing without bundles
- Need an `remora init` command to bootstrap a project with starter bundles
- Cannot extend externals, events, or languages — only bundle content
- Hard to share best practices if bundles are fully decoupled
- Testing bundles requires a running remora instance

**Best for:** When different projects need fundamentally different agent behaviors and don't want to be constrained by default bundles.

---

## 7. Option E: Hybrid — Thin Core + Thick Config

**Concept:** Core ships as a single Python package but is designed around configuration-driven extension. Instead of Python-level plugin protocols, everything is extensible through config + bundles + tool scripts.

**The key insight:** Remora's Grail tool system already provides runtime extensibility. A `.pym` script can call any externals function. The `bundle.yaml` controls prompts, models, max_turns, self-reflection. The `remora.yaml` controls subscription patterns, virtual agents, bundle mappings. **Almost everything agent-behavior-related is already configurable without touching Python.**

**What this option adds:**
1. Move builtin language plugins to a config-driven registry
2. Make the prompt builder fully template-driven (Jinja2 or simple string interpolation)
3. Add a bundle search path (multiple directories, first match wins)
4. Make externals extensible via `.pym` "capability scripts" (not Python, Grail scripts that compose existing externals into new higher-level tools)
5. Keep everything in one Python package

**Bundle search path:**
```yaml
# remora.yaml
bundle_search_paths:
  - "./bundles"                    # project-local bundles (highest priority)
  - "~/.remora/bundles"            # user-level shared bundles
  - "@default"                     # remora's built-in default bundles (lowest priority)
```

**Prompt templates in bundle.yaml:**
```yaml
prompts:
  system: |
    You are an autonomous agent for {node_type} "{node_name}" in {file_path}.
    {system_prompt_extension}
  chat: |
    User message received. Respond using send_message to "user".
  reactive: |
    Event {event_type} received for {node_id}. Update internal state.
```

**Pros:**
- Single package — simplest to develop, test, release
- Leverages existing Grail extensibility (tools are already plugins)
- Config-driven, not code-driven — agent behavior authors don't need Python
- Bundle search path gives natural override/layering
- Default bundles ship with the package but can be overridden per-project
- Prompt templates make prompt construction fully customizable without touching `prompt.py`

**Cons:**
- Still can't add new externals without Python changes (unless we add capability scripts)
- Language plugin extensibility requires a config-driven registration mechanism
- "Thick config" can become its own complexity (config schema bloat)
- Less formal than package-level separation — discipline required to not blur the line

**Best for:** A single team that wants to iterate on agent behaviors quickly while keeping a clean, simple architecture.

---

## 8. Where to Draw the Line: Module-by-Module Analysis

For each source module, we classify: **core** (stable infrastructure, freeze-worthy), **boundary** (defines the contract between core and plugins), or **plugin** (agent behavior, should be externalized/configurable).

### Definitive core — freeze these

| Module | Why it's core |
|--------|--------------|
| `core/types.py` | Foundation enums. Everything depends on these. Rarely changes. |
| `core/db.py` | SQLite connection management. Pure infrastructure. |
| `core/node.py` | The `Node` Pydantic model. Stable data structure. |
| `core/events/types.py` | Event base class + `EventType` enum. The event schema. |
| `core/events/bus.py` | In-memory pub/sub. Generic, reusable. |
| `core/events/store.py` | Event persistence + fan-out. Pure infrastructure. |
| `core/events/dispatcher.py` | Trigger dispatch logic. Stateless routing. |
| `core/events/subscriptions.py` | Subscription pattern matching. Generic. |
| `core/graph.py` | Node/edge storage. Pure persistence. |
| `core/actor.py` | Actor inbox/processing loop. Lifecycle infrastructure. |
| `core/outbox.py` | Write-through event emission. Thin wrapper. |
| `core/trigger.py` | Cooldown/depth policy. Stateless rules. |
| `core/runner.py` | ActorPool lifecycle management. Infrastructure. |
| `core/rate_limit.py` | Sliding window limiter. Generic primitive. |
| `core/metrics.py` | In-memory counters. Infrastructure. |
| `core/kernel.py` | Thin structured-agents wrapper. LLM abstraction. |
| `core/grail.py` | Grail tool loading/execution. The script runtime. |
| `core/workspace.py` | Cairn workspace management. Per-agent filesystem. |
| `core/services.py` | DI container. Wires everything together. |
| `core/lifecycle.py` | Startup/run/shutdown orchestrator. |
| `code/discovery.py` | Tree-sitter AST walking. Generic discovery engine. |
| `code/paths.py` | File walking, gitignore filtering. |
| `code/reconciler.py` | File change → node graph updates. Orchestrator. |
| `code/watcher.py` | Filesystem watch loop. Pure infrastructure. |
| `code/directories.py` | Directory node projection. Infrastructure. |
| `code/virtual_agents.py` | Virtual agent manager. Driven by config, not behavior. |
| `web/server.py` | App factory, lifespan. Infrastructure. |
| `web/deps.py` | Shared web dependencies. Infrastructure. |
| `web/middleware.py` | CSRF. Infrastructure. |
| `web/sse.py` | SSE streaming. Infrastructure. |
| `web/paths.py` | Workspace path resolution. Infrastructure. |
| `web/routes/*.py` | HTTP route handlers. Infrastructure (they expose core APIs). |
| `lsp/server.py` | LSP adapter. Infrastructure. |
| `__main__.py` | CLI entry point. Infrastructure. |

### Boundary modules — the contract surface

| Module | Why it's boundary |
|--------|------------------|
| `core/externals.py` | **THE** plugin API surface. `TurnContext` defines the 27 capability functions that `.pym` tools can call. This is the ABI between core and plugins. Adding/removing/changing a capability is a breaking change for tools. |
| `core/turn_executor.py` | Orchestrates the turn pipeline. It wires externals to the kernel. Changes here affect how all agents execute. Boundary because it determines *what* agents can do per turn. |
| `core/config.py` | Defines what's configurable. `BundleConfig`, `VirtualAgentConfig`, bundle_overlays — these shape agent behavior via config. The config schema IS the plugin contract for YAML-level customization. |

### Plugin-layer modules — should live outside core

| Module | Why it's plugin |
|--------|----------------|
| `core/prompt.py` | `PromptBuilder` constructs system/user prompts from `BundleConfig`. This is pure agent behavior logic — how prompts are assembled, what variables are injected, what structure they follow. Different agent designs will want radically different prompts. |
| `core/search.py` | `SearchService` wraps embeddy for semantic search. This is an optional capability, not core infrastructure. Not every deployment needs it. |
| `code/languages.py` | The `LanguagePlugin` **protocol** is core, but the builtin implementations (PythonPlugin, MarkdownPlugin, TomlPlugin) are plugins. These could ship separately. |
| `code/queries/*.scm` | Tree-sitter query files. These define what code elements are discovered for each language. Tightly coupled to language plugins. |
| `bundles/*` | Already externalized. Bundle YAML + tool scripts are the primary plugin surface. |
| `web/static/index.html` | The web UI. Presentation layer. Could be a separate package or even a separate repo. |
| `remora.yaml.example` | Example config. Documentation, not code. |

### The gray zone

| Module | Tension |
|--------|---------|
| `core/search.py` | It's an optional externals capability. The `search_nodes` function is in TurnContext. Should optional capabilities be pluggable? Or should core ship with all capabilities and let bundles decide which tools expose them? |
| `code/languages.py` | The protocol vs. implementations split is clean in theory, but the builtins are tightly integrated (query files are loaded relative to the package). Separating them requires a query file discovery mechanism. |
| `core/events/types.py` | The concrete event classes (NodeChanged, ChatReceived, etc.) are infrastructure. But new agent behaviors might want new event types. Currently you'd have to modify this file. |

---

## 9. The Externals API as the Formal Contract

The `TurnContext` class in `externals.py` is the single most important boundary in the entire codebase. It defines what tools can do. Every `.pym` script interacts with the runtime exclusively through the capabilities dict produced by `to_capabilities_dict()`.

### Current externals surface (27 capabilities)

```
# Communication
send_message(to_node_id, content)
query_agents(query, filters)

# Self-modification
rewrite_self(new_source, rationale)
propose_changes(file_path, changes, rationale)

# Persistence
kv_get(key) / kv_set(key, value) / kv_delete(key)
reflect(content)
get_event_history(event_types, limit)

# Subscriptions
subscribe(event_type, pattern) / unsubscribe(subscription_id)
get_subscriptions()

# Graph queries
get_node(node_id) / get_neighbors(node_id, edge_type)
search_nodes(query, limit)

# Workspace
read_file(path) / write_file(path, content) / list_files(pattern)

# Companion/reflection
companion_summarize(summary, tags)
companion_reflect(insight)
companion_link(target_node_id, relation)
aggregate_digest(analysis)

# Identity
get_self() — returns the node's own metadata
```

### Why this is the right boundary

1. **Stability.** These 27 functions are the full surface area that tools can rely on. If we freeze this API (with minor additions allowed), all existing tools continue to work forever.

2. **Completeness.** The externals cover all the primitive operations an agent needs: communicate, persist, observe, modify. Higher-level behaviors are composed in `.pym` scripts from these primitives.

3. **Testability.** We can write a conformance test suite: "given a mock TurnContext with these capabilities, does tool X produce the expected calls?" Tools become independently testable.

4. **Versioning.** We can version the externals API: `externals_version: 1`. Tools can declare which version they need. Core can maintain backwards compatibility or error clearly.

### What's missing from the externals

Some behaviors that tools might want in the future:

- **Spawn sub-agents.** A tool that creates a temporary agent for a subtask.
- **Schedule delayed events.** "Remind me to check this in 5 minutes."
- **Access raw LLM.** A tool that makes its own LLM call (not through the agent turn).
- **File system operations beyond workspace.** Read files outside the agent's workspace.
- **HTTP/external API access.** Make web requests (sandboxed).

These would be new externals capabilities — additions to the contract. The question is whether plugins should be able to define them. Options A and E say no (core defines all externals). Options B and C say yes (plugins can extend the externals dict).

### Recommendation for the externals boundary

**Freeze the existing 27 capabilities as v1.** Allow core to add new capabilities in future versions (non-breaking — tools that don't use them don't break). Do NOT allow plugins to inject arbitrary capabilities — this would make the security/sandboxing story impossible. If a new capability is needed, it goes through a core PR with review.

The externals dict should be the **only** way tools interact with the runtime. No side channels, no global state, no monkey-patching.

---

## 10. Language Plugins and Discovery Extensions

### The current system

`code/languages.py` defines:
```python
class LanguagePlugin(Protocol):
    suffixes: ClassVar[tuple[str, ...]]
    language_name: ClassVar[str]
    node_types: ClassVar[tuple[str, ...]]
    def get_query(self) -> str: ...
    def post_process(self, nodes: list[Node]) -> list[Node]: ...
```

Three builtins: `PythonPlugin`, `MarkdownPlugin`, `TomlPlugin`. Registered with `LanguageRegistry`.

Tree-sitter query files (`.scm`) are loaded from `code/queries/` relative to the package.

### The extension question

Adding a new language (e.g., JavaScript, Rust, Go) requires:
1. A new `LanguagePlugin` implementation (Python class)
2. A tree-sitter query file (`.scm`)
3. A tree-sitter grammar dependency (`tree-sitter-javascript`, etc.)
4. Registration with `LanguageRegistry`

Steps 1, 2, and 4 are code changes in the remora package. Step 3 is a dependency change in `pyproject.toml`. This is a core change no matter how you slice it.

### Options for making language plugins external

**A. Config-driven query files + generic plugin:**
```yaml
# remora.yaml
languages:
  javascript:
    suffixes: [".js", ".jsx", ".mjs"]
    query_file: "./queries/javascript.scm"
    grammar: "tree-sitter-javascript"
    node_types: ["function", "class", "method"]
```
Core provides a `GenericLanguagePlugin` that reads a query file and applies standard tree-sitter discovery. No Python needed for basic languages.

**B. Entry point plugins (Option C approach):**
```toml
[project.entry-points."remora.plugins.languages"]
javascript = "remora_js:JavaScriptPlugin"
```
Each language is a separate pip-installable package.

**C. Keep builtins in core, add external query file path:**
```yaml
language_query_paths:
  - "./queries"  # project-local overrides
  - "@builtin"   # package builtins
```
Query files can be overridden per-project, but the Python plugin classes stay in core.

### Recommendation

**Option A (config-driven) for the common case, with the protocol for advanced cases.** Most languages just need a query file and suffix mapping. The `post_process` hook is only needed for Python (to handle decorators, async, etc.). A generic config-driven plugin covers 90% of languages. Keep the protocol for the 10% that need custom Python logic.

---

## 11. Config Surface and Override Hierarchy

### Current config layers

```
Layer 1: Python defaults (Config class defaults in config.py)
Layer 2: remora.yaml (project-level config file)
Layer 3: Environment variables (REMORA_* prefix, pydantic-settings)
Layer 4: bundle.yaml (per-bundle behavior config)
```

### What's configured where

| Setting | Layer | Category |
|---------|-------|----------|
| `project_root` | 2 | Infrastructure |
| `db_path` | 2 | Infrastructure |
| `model` | 2, 4 | Behavior (which LLM to use) |
| `bundle_root` | 2 | Plugin discovery |
| `bundle_overlays` | 2 | Behavior (node→role mapping) |
| `bundle_rules` | 2 | Behavior (pattern→role mapping) |
| `virtual_agents` | 2 | Behavior (declarative agents) |
| `max_turns` | 2, 4 | Behavior |
| `self_reflect` | 4 | Behavior |
| `system_prompt_extension` | 4 | Behavior |
| `prompts` | 4 | Behavior (chat/reactive templates) |
| `tools` | 4 | Behavior (available tool scripts) |
| `search` | 2 | Infrastructure (embeddy config) |
| `log_level` | 2 | Infrastructure |
| `web_host/port` | 2 | Infrastructure |

### The pattern

Infrastructure settings live in `remora.yaml`. Behavior settings live in both `remora.yaml` (global defaults) and `bundle.yaml` (per-role overrides). This is a natural and correct split.

### What should change

1. **Bundle search path instead of single `bundle_root`.** Allow multiple directories with priority ordering. This enables per-project overrides of default bundles.

2. **Externals version in bundle.yaml.** Each bundle declares which externals API version it expects. Core validates compatibility at load time.

3. **Config schema for plugin-defined settings.** If we go with Option E, plugins (bundles) might want their own config sections. A `bundle_config` section in `remora.yaml` could hold bundle-specific settings:
   ```yaml
   bundle_config:
     code-agent:
       max_rewrite_size: 500
       auto_reflect: true
     companion:
       digest_interval: 60
   ```

4. **Move behavior defaults out of Python.** The default `bundle_overlays` mapping, default model, default max_turns — these should come from a `defaults.yaml` file shipped with the package, not hardcoded in `Config.__init__`. This makes them overridable without subclassing.

---

## 12. Comparison Matrix

| Criterion | A: Bundle-Only | B: Package Split | C: Entry Points | D: External Repos | E: Hybrid |
|-----------|---------------|------------------|-----------------|-------------------|-----------|
| **Implementation effort** | Minimal | Moderate | High | Moderate | Low-Moderate |
| **Agent behavior iteration speed** | Fast (YAML/pym only) | Fast (separate package) | Fast (plugins independent) | Fast (project-local) | Fast (config/YAML/pym) |
| **Can add new externals from plugin?** | No | No | Yes | No | No (by design) |
| **Can add new languages from plugin?** | No | Partial | Yes | No | Yes (config-driven) |
| **Can customize prompts from plugin?** | Via bundle.yaml only | Via separate package | Via protocol | Via bundle.yaml | Via templates |
| **Package management complexity** | 1 package | 2+ packages | 1+ plugins | 1 package + repos | 1 package |
| **First-run experience** | Good (defaults bundled) | Good (depends on core) | Complex (need plugins) | Poor (no bundles) | Good (defaults bundled) |
| **Formal contract/versioning** | Implicit | Import boundary | Protocols | Implicit | Config schema |
| **Testing complexity** | Low | Moderate | High | Moderate | Low |
| **Risk of boundary violations** | High (no enforcement) | Low (package boundary) | Low (protocols) | Medium | Medium |
| **Matches our team size (1 person)** | Yes | Overkill | Overkill | Partial | Yes |
| **Enables future multi-team** | Limited | Yes | Yes | Yes | Upgradeable |
| **Codebase elegance** | Simple but informal | Clean separation | Over-engineered | Clean but sparse | Clean and practical |

---

## 13. Recommended Approach

### The recommendation: Option E (Hybrid) with elements of Option A

**Why Option E wins:**

1. **We are a single developer.** Managing multiple packages (Option B) or plugin registries (Option C) adds overhead with zero immediate benefit. We can always split later if needed.

2. **The infrastructure already supports it.** Bundles, tools, and config already provide 90% of the extensibility we need. We're not building new mechanisms — we're formalizing and slightly extending what exists.

3. **No backwards compatibility concerns.** The user explicitly stated we don't care about backwards compatibility. We can restructure freely to get the cleanest architecture.

4. **The "freeze" is a development discipline, not a code boundary.** What we really want is the ability to say "I'm only editing files in `bundles/` and `remora.yaml` today." Option E makes this natural by moving all behavior-specific logic out of Python and into config/templates/tools.

5. **It's upgradeable.** If we later need package-level separation (Option B) or entry point plugins (Option C), Option E is a natural stepping stone — the config-driven architecture makes extraction easier, not harder.

### The specific architecture

**Single package `remora` with three internal layers:**

```
remora/
├── core/           ← Layer 1: FROZEN infrastructure
│   ├── types.py        Foundation types
│   ├── config.py       Config schema (not defaults)
│   ├── db.py           Database
│   ├── node.py         Node model
│   ├── events/         Event system
│   ├── graph.py        Node/edge storage
│   ├── actor.py        Actor lifecycle
│   ├── outbox.py       Event emission
│   ├── trigger.py      Trigger policy
│   ├── runner.py       Actor pool
│   ├── rate_limit.py   Rate limiter
│   ├── metrics.py      Metrics
│   ├── kernel.py       LLM abstraction
│   ├── grail.py        Tool execution engine
│   ├── workspace.py    Workspace management
│   ├── externals.py    THE CONTRACT (versioned capabilities dict)
│   ├── turn_executor.py  Turn pipeline
│   ├── services.py     DI container
│   └── lifecycle.py    Startup/shutdown
│
├── code/           ← Layer 1: FROZEN discovery engine
│   ├── discovery.py    Generic tree-sitter walker
│   ├── languages.py    LanguagePlugin protocol + GenericPlugin
│   ├── paths.py        File walking
│   ├── reconciler.py   Change reconciliation
│   ├── watcher.py      File watching
│   ├── directories.py  Directory projection
│   └── virtual_agents.py  Virtual agent manager
│
├── web/            ← Layer 1: FROZEN web surface
│   └── (all current web modules)
│
├── lsp/            ← Layer 1: FROZEN LSP surface
│   └── (all current LSP modules)
│
├── defaults/       ← Layer 2: SHIPPED defaults (overridable)
│   ├── defaults.yaml       Default config values
│   ├── bundles/            Default bundle definitions
│   │   ├── system/
│   │   ├── code-agent/
│   │   ├── directory-agent/
│   │   ├── companion/
│   │   ├── review-agent/
│   │   └── test-agent/
│   └── queries/            Default tree-sitter queries
│       ├── python.scm
│       ├── markdown.scm
│       └── toml.scm
│
└── __main__.py     ← CLI entry point
```

**The `defaults/` directory** is the key addition. It contains everything that defines agent behavior:
- `defaults.yaml` — the default bundle_overlays, model, max_turns, etc. (currently hardcoded in Config)
- `bundles/` — moved from the repo root into the package, under `defaults/`
- `queries/` — moved from `code/queries/` into `defaults/`

**Bundle search path resolution:**
```
1. Project-local: {project_root}/bundles/     (user overrides)
2. User-level:    ~/.remora/bundles/          (shared across projects)
3. Package:       remora/defaults/bundles/    (shipped defaults)
```

**Query file search path resolution:**
```
1. Project-local: {project_root}/queries/
2. Package:       remora/defaults/queries/
```

### What moves out of Python into config/templates

1. **Default bundle_overlays** → `defaults.yaml`
2. **Default model/max_turns/etc.** → `defaults.yaml`
3. **Prompt construction** → bundle.yaml templates with variable interpolation (remove `prompt.py` entirely)
4. **Language definitions** → `defaults.yaml` language registry section (config-driven GenericPlugin)
5. **Search capability** → optional external, enabled via config

### What stays as frozen Python

Everything in `core/`, `code/`, `web/`, `lsp/`. The externals API. The turn pipeline. The event system. The reconciler. The workspace manager. All of it.

### The externals contract

Freeze the current 27 capabilities as **externals v1**. Add `externals_version: 1` to bundle.yaml schema. Core validates that bundle's declared version is supported. New capabilities can be added in v1.x (non-breaking). Capability removals require v2 (breaking).

### What this enables

After implementing this architecture:

- **Day-to-day work** is editing `bundles/*/bundle.yaml`, `bundles/*/tools/*.pym`, and `remora.yaml`. No Python changes needed.
- **Adding a new language** is creating a `.scm` query file and adding a YAML entry. No Python changes needed (for simple languages).
- **Adding a new agent role** is creating a new bundle directory. No Python changes needed.
- **Customizing prompts** is editing templates in `bundle.yaml`. No Python changes needed.
- **Adding new tools** is writing a `.pym` script. No Python changes needed.
- **The core Python codebase is frozen** — only touched for bug fixes, performance improvements, or new externals capabilities.

