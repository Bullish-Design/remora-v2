# Remora v2 — Post-Alignment Code Review

**Version:** 0.5.0 (post-alignment refactor)
**Date:** 2026-03-14
**Codebase:** ~4,173 lines source / ~4,789 lines tests

---

## Table of Contents

1. [Concept & Vision](#1-concept--vision)
   Overview of what remora is, the problem it solves, and the conceptual goal that drives all architectural decisions.

2. [Architecture Overview](#2-architecture-overview)
   System diagram, data flow, and key abstractions. How discovery, persistence, events, execution, and surfaces compose into a reactive agent substrate.

3. [Alignment Refactor Summary](#3-alignment-refactor-summary)
   What was cleaned up in the alignment refactor, what changed, and verification that all backward-compatibility artifacts have been removed.

4. [Module-by-Module Review](#4-module-by-module-review)
   - 4.1 Core Types & Models (`core/types.py`, `core/node.py`)
   - 4.2 Configuration (`core/config.py`)
   - 4.3 Database Layer (`core/db.py`)
   - 4.4 Graph & Agent Stores (`core/graph.py`)
   - 4.5 Event System (`core/events/`)
   - 4.6 Actor & Runner (`core/actor.py`, `core/runner.py`)
   - 4.7 Workspace Integration (`core/workspace.py`)
   - 4.8 Code Discovery (`code/discovery.py`, `code/languages.py`)
   - 4.9 Reconciler & Projections (`code/reconciler.py`, `code/projections.py`)
   - 4.10 Grail Tool System (`core/grail.py`)
   - 4.11 LSP Server (`lsp/`)
   - 4.12 Web Server & UI (`web/`)
   - 4.13 CLI (`__main__.py`)
   - 4.14 Bundle System (`bundles/`)

5. [Conceptual Alignment Assessment](#5-conceptual-alignment-assessment)
   Are there parts of the codebase that don't fully align with remora's conceptual goal? Naming, abstractions, and architectural decisions evaluated against the vision.

6. [Previous Code Review: Issue Status](#6-previous-code-review-issue-status)
   Each of the 15 issues from the pre-refactor code review, with current status (Fixed / Still Open / Partially Addressed).

7. [Strengths](#7-strengths)
   What the codebase does well.

8. [Issues & Recommendations](#8-issues--recommendations)
   Prioritized issues and actionable recommendations for the current codebase.

---

## 1. Concept & Vision

Remora is a **reactive agent substrate** that transforms source code into a living graph of autonomous AI agents. Every meaningful code element — function, class, method, directory — becomes a **node** in a persistent graph, and each node is backed by an LLM-powered **actor** that can observe, reason about, and act on its corresponding code.

### The Core Idea

Traditional static analysis tools examine code but don't *inhabit* it. Remora inverts this: it discovers code structure using tree-sitter, materializes each element as a first-class graph node, and then lets AI agents autonomously observe and react to changes in their code via an event-driven architecture. When you edit a function, the function's agent knows. It can analyze the change, update its understanding, communicate with neighboring agents, or take action.

### What Remora Is

- **A code graph runtime**: Discovers code elements → persists them as nodes in SQLite → maintains edges (parent/child, containment) → provides CRUD and query APIs.
- **An event-driven agent loop**: File changes → tree-sitter re-parse → diff against known state → emit events (discovered/changed/removed) → subscription matching → actor inbox delivery → LLM-powered agent turns with sandboxed tools.
- **A multi-surface system**: Web UI (live graph visualization + chat), LSP adapter (code lens, hover, event forwarding), CLI (orchestration entry point).

### What Remora Is Not

- Not an IDE plugin (though it has an LSP adapter for editor integration).
- Not a one-shot code analysis tool (it's a persistent, reactive runtime).
- Not a multi-model orchestration framework (it uses one model per turn, configured per-bundle).

### The Conceptual Goal

Every architectural decision should serve this goal: **make code elements into first-class autonomous agents that can observe, communicate, and act within their codebase in real time.** The system should be reactive (event-driven, not polling), composable (bundle overlays, not hardcoded behavior), and observable (web UI, LSP, event streaming).

---

## 2. Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                          CLI (Typer)                             │
│                   remora start / remora discover                 │
├──────────────┬──────────────────┬────────────────────────────────┤
│  Web Server  │   LSP Server     │         RuntimeServices        │
│  (Starlette) │   (pygls)        │    (central DI container)      │
├──────────────┴──────────────────┤                                │
│                                 │                                │
│  ┌───────────┐  ┌────────────┐  │  ┌──────────────────────────┐  │
│  │ EventBus  │←→│ EventStore │  │  │   FileReconciler         │  │
│  └───────────┘  │ (SQLite)   │  │  │   (watchfiles + scan)    │  │
│                 └─────┬──────┘  │  └──────────────────────────┘  │
│                       │         │                                │
│           ┌───────────▼──────┐  │  ┌───────────────────────────┐ │
│           │TriggerDispatcher │──│──│ ActorPool                 │ │
│           │ (subscriptions)  │  │  │  └─ Actor (per node_id)   │ │
│           └──────────────────┘  │  │     ├─ inbox (Queue)      │ │
│                                 │  │     ├─ outbox (EventStore)│ │
│  ┌──────────────────────────┐   │  │     ├─ kernel (LLM)       │ │
│  │ NodeStore + AgentStore   │   │  │     └─ tools (Grail)      │ │
│  │ (SQLite graph)           │   │  └───────────────────────────┘ │
│  └──────────────────────────┘   │                                │
│                                 │  ┌──────────────────────────┐  │
│  ┌──────────────────────────┐   │  │ CairnWorkspaceService    │  │
│  │ Discovery (tree-sitter)  │   │  │ (per-agent sandboxed fs) │  │
│  │ Python / Markdown / TOML │   │  └──────────────────────────┘  │
│  └──────────────────────────┘   │                                │
└─────────────────────────────────┴────────────────────────────────┘
```

### Key Abstractions

| Abstraction | Purpose |
|-------------|---------|
| **Node** | Unified model joining a discovered code element with agent runtime state. The atomic unit of the graph. |
| **Actor** | Per-node processing loop with inbox queue, outbox emitter, cooldown/depth policies. Executes LLM turns. |
| **ActorPool** | Manages actor lifecycle: lazy creation, dispatch routing, idle eviction. |
| **EventStore** | Append-only SQLite event log with dual fan-out: in-memory EventBus + TriggerDispatcher. |
| **TurnContext** | Per-turn capability API exposed to agent tools. Scoped to one node, one correlation. |
| **AgentWorkspace** | Per-agent sandboxed filesystem (Cairn-backed) with KV store. Tools read/write here. |
| **Bundle** | Three-tier overlay (system → role → instance) providing tools, prompts, and config per agent type. |
| **FileReconciler** | Keeps the node graph in sync with source files via mtime detection + watchfiles streaming. |

### Data Flow

1. **Discovery**: Tree-sitter parses source files → `CSTNode` list (immutable, per-parse)
2. **Projection**: `CSTNode` → `Node` (persisted to SQLite `nodes` table, hash-based change detection)
3. **Reconciliation**: `FileReconciler` detects changes → emits `NodeDiscoveredEvent`, `NodeChangedEvent`, `NodeRemovedEvent`
4. **Subscription matching**: `TriggerDispatcher` resolves which agents care about an event via `SubscriptionRegistry`
5. **Actor execution**: Events routed to `Actor.inbox` → semaphore-gated LLM turn with Grail tools
6. **Fan-out**: Actor's `Outbox` emits new events → cycle continues

---

## 3. Alignment Refactor Summary

The alignment refactor removed all backward-compatibility shims, legacy aliases, migration validators, and internal property escape hatches. The goal: a codebase with one name for each concept and no dead code paths.

### What Was Removed

| Category | Items Removed |
|----------|--------------|
| **Type aliases** | `CodeElement`, `CodeNode` (node.py), `AgentActor` (actor.py), `AgentRunner` (runner.py), `AgentContext` (externals.py) |
| **Migration validators** | `bundle_name` → `role` validator on `DiscoveredElement` and `Agent`; `bundle_mapping`/`swarm_root` validator on `Config` |
| **Legacy methods** | `TurnContext.to_externals_dict()`, `EventStore.initialize()`, `SubscriptionRegistry.initialize()` |
| **Internal escape hatches** | `EventStore.connection`, `EventStore.lock`, `NodeStore.db`, `SubscriptionRegistry.db` properties |
| **DB migration helpers** | `NodeStore._migrate_role_columns()`, `NodeStore._table_columns()`, `AgentStore._migrate_role_column()`, migration calls in `create_tables()` |
| **Star imports** | `events/__init__.py` replaced `from .types import *` with explicit imports and `__all__` |
| **Stale config keys** | `remora.yaml.example` updated from `bundle_mapping`/`swarm_root` to `bundle_overlays`/`workspace_root` |
| **Git-tracked artifacts** | `.grail/` directory removed from tracking, added to `.gitignore` |
| **Stale UI copy** | Web UI subtitle changed from "Live swarm graph and companion panel" to "Live agent graph" |
| **Stale docstrings** | Updated references to "CodeNodes" in projections.py and legacy actor docstrings |

### What Was Fixed

- `rewrite_self.pym`: Changed `propose_rewrite` → `apply_rewrite` to match `TurnContext` capabilities.
- `LSP __init__.py`: Changed from unconditional import to lazy import with clear error message for missing `pygls`.
- `NodeStore`: Added `list_all_edges()` method to replace raw DB access in web server.

### Verification

- All `__all__` exports use only current names — no aliases.
- `grep -r "CodeElement\|CodeNode\|AgentActor\|AgentRunner\|AgentContext" src/` returns zero hits (excluding comments in test files asserting removal).
- `.grail/` has 0 tracked files; `.gitignore` includes `.grail/` entry.
- `remora.yaml.example` uses only `bundle_overlays` and `workspace_root`.

---

## 4. Module-by-Module Review

### 4.1 Core Types & Models (`core/types.py`, `core/node.py`)

**Quality: Very Good** (improved from Good)

Post-refactor state:
- Clean enum definitions (`NodeStatus`, `NodeType`, `ChangeType`) with explicit status transition validation via `validate_status_transition()`.
- Three model tiers: `DiscoveredElement` (immutable, discovery-time), `Agent` (runtime state), and `Node` (combined view with SQLite round-trip).
- `__all__ = ["DiscoveredElement", "Agent", "Node"]` — no aliases.
- No migration validators — the `bundle_name` → `role` migration code is gone.
- `Node` has clean `to_element()` and `to_agent()` decomposition methods.

**Remaining observations:**
- `to_row()` methods still use `hasattr(data["status"], "value")` checks which are always true for enum values — a minor clarity improvement would be to call `.value` directly.
- `Node` decomposition (`to_element()` / `to_agent()`) exists but isn't leveraged by most consumers — they pass `Node` objects directly. This is fine for now; the decomposition is there if needed.

### 4.2 Configuration (`core/config.py`)

**Quality: Very Good** (improved from Good)

- Frozen Pydantic `BaseSettings` loaded from `remora.yaml` with env var expansion.
- No legacy field names — only `bundle_overlays`, `workspace_root`, and current field names.
- No migration validators — the `bundle_mapping`/`swarm_root` migration code is gone.
- `_expand_env_vars()` utility is clean and recursive.

**No issues.**

### 4.3 Database Layer (`core/db.py`)

**Quality: Very Good**

- Clean async wrapper over synchronous sqlite3 with `asyncio.Lock` + `asyncio.to_thread`.
- WAL mode and busy timeout configured by default.
- Simple API: `execute`, `fetch_one`, `fetch_all`, `insert`, `delete`, `execute_script`, `execute_many`.
- Individual auto-commit per operation; `execute_many` wraps in a single transaction.

**Remaining observations:**
- Single connection shared via lock — no pooling. Appropriate for the single-process, local-first design.
- No WAL checkpoint management — long-running processes may accumulate WAL segments. Low risk in practice.

### 4.4 Graph & Agent Stores (`core/graph.py`)

**Quality: Good**

Post-refactor state:
- No `db` property on `NodeStore` — internal database access is fully encapsulated.
- No migration methods (`_migrate_role_columns`, `_table_columns`, `_migrate_role_column`) — all removed.
- New `list_all_edges()` method provides clean access for the web server (replacing raw DB access).
- `Edge` is a frozen dataclass with `from_id`, `to_id`, `edge_type`.

**Remaining issues:**
- **Table creation duplication**: `NodeStore.create_tables()` creates both `nodes` AND `agents` tables. `AgentStore.create_tables()` also creates the `agents` table. Both are called during `RuntimeServices.initialize()`. The `CREATE TABLE IF NOT EXISTS` prevents errors, but the ownership is unclear and confusing.
- SQL in `upsert_node()` uses f-string column interpolation — safe since columns come from `model_dump()` keys, but not idiomatic.

### 4.5 Event System (`core/events/`)

**Quality: Very Good**

Post-refactor state:
- `events/__init__.py` uses explicit imports and an explicit `__all__` list — no star imports.
- `EventStore`: no `initialize()` alias, no `connection`/`lock` properties.
- `SubscriptionRegistry`: no `initialize()` alias, no `db` property.
- Clean event hierarchy rooted at `Event` base class with auto-populated `event_type`.
- `to_envelope()` helper provides clean serialization.
- `EventBus`: MRO-aware in-memory pub/sub with streaming support.
- `TriggerDispatcher`: Routes events to agents via a pluggable `router` callback.

**Remaining observations:**
- `EventStore.subscriptions` property has no return type annotation (`# noqa: ANN201`). Minor — the type is clear from context.
- `EventBus.emit()` awaits each handler sequentially. Under high throughput, a slow handler blocks subsequent handlers.
- `SubscriptionRegistry._rebuild_cache()` loads ALL subscriptions on every cache miss. Could use incremental updates at scale.

### 4.6 Actor & Runner (`core/actor.py`, `core/runner.py`)

**Quality: Good**

Post-refactor state:
- `__all__ = ["Outbox", "RecordingOutbox", "Trigger", "Actor"]` — no `AgentActor` alias.
- `__all__ = ["ActorPool"]` — no `AgentRunner` alias.
- `Actor._execute_turn()` docstring updated to "Execute one agent turn." (no longer references "old ActorPool._execute_turn").
- `Outbox` docstring is clear: "Write-through emitter that tags events with actor metadata. Not a buffer."
- `RecordingOutbox`: clean test double.

**Remaining issues:**
- **`_execute_turn()` complexity**: Still ~120 lines handling 7+ responsibilities (status transition, workspace access, bundle config loading, prompt building, kernel creation, LLM call, result processing, error handling, cleanup). This is the most complex method in the codebase. Would benefit from extraction into helper methods.
- **`_read_bundle_config()` rigidity**: Explicitly validates each key. Adding a new `bundle.yaml` key requires code changes.
- **Depth tracking semantics**: The `finally` block decrements depth after turn completion. The depth check in `_should_trigger` prevents new triggers but doesn't limit in-flight turns.
- **`ActorPool.run_forever()`**: Sleeps 1 second between eviction checks — essentially a timer. Works but is an unusual pattern.

### 4.7 Workspace Integration (`core/workspace.py`)

**Quality: Good**

- `AgentWorkspace`: Per-agent sandboxed filesystem with per-workspace locking.
- `CairnWorkspaceService`: Manages lifecycle, caching, and bundle provisioning with ordered overlay support.
- KV store operations (`kv_get`, `kv_set`, `kv_delete`, `kv_list`) well-integrated.

**Remaining observations:**
- `provision_bundle()` re-writes files every time (no caching of already-provisioned bundles). Called during reconciliation which can be frequent.
- Lock contention: Each operation acquires its lock independently. Sequential read-modify-write operations aren't atomic.

### 4.8 Code Discovery (`code/discovery.py`, `code/languages.py`)

**Quality: Very Good**

- Plugin architecture via `LanguagePlugin` protocol. Python, Markdown, and TOML plugins.
- Externalized tree-sitter query files (`.scm`), overridable via `query_paths`.
- Hierarchical parent resolution via tree walking. Deterministic node IDs (`file_path::full_name`).
- LRU caching for parsers and queries.

**Remaining observations:**
- `discover()` creates a new `LanguageRegistry` on every call — lightweight but wasteful.
- No file size guard on `_parse_file()`.
- Duplicate node ID resolution (`@start_byte` suffix) is fragile across renames.

### 4.9 Reconciler & Projections (`code/reconciler.py`, `code/projections.py`)

**Quality: Good**

- Full startup scan + continuous watchfiles-based reconciliation with add/change/delete handling.
- Directory materialization derives directory nodes from file paths.
- Bundle provisioning and subscription registration are co-located with node lifecycle.

**Remaining issues:**
- **Stale comment** (reconciler.py lines 51-52): `"Re-register directory subscriptions once after startup so older subscription shapes are migrated without requiring a DB reset."` — The phrase "older subscription shapes are migrated" is legacy language. After the alignment refactor, this should just say "Re-register directory subscriptions once after startup to ensure consistency."
- **`code_node` variable name** (projections.py line 44): Local variable `code_node = Node(...)` still uses the old `code_node` naming pattern. Should be `node` for consistency with the current naming convention.
- **`_materialize_directories()`** remains the longest method (~100 lines) with complex conditional logic. Would benefit from splitting.
- **Reconciler race condition**: `_on_content_changed()` and `run_forever()` can trigger concurrent `_reconcile_file()` calls for the same file. No per-file locking or deduplication.
- **`_stop_event()` task leak**: Creates an `asyncio.Task` via `asyncio.create_task(_checker())` that is never stored — it could be garbage collected or leak.
- **`_subscriptions_bootstrapped` / `_bundles_bootstrapped` flags**: Create "first run is different" code paths that add complexity.

### 4.10 Grail Tool System (`core/grail.py`)

**Quality: Good**

- `GrailTool` wraps Grail scripts as structured-agents tools. Clean schema generation from Grail input declarations.
- Content-hash caching avoids re-parsing identical tools.
- `discover_tools()` loads `.pym` files from `_bundle/tools/` in agent workspaces.
- Capabilities filtering: only passes externals that the script declares with `@external`.

**Remaining issues:**
- **Dual parameter naming**: Both `GrailTool.__init__()` and `discover_tools()` accept `capabilities` AND `externals` parameters (lines 70-71, 143-144). The `externals` parameter is a vestigial compatibility pattern — internally everything uses `capabilities`. The `externals` fallback should be removed.
- **`_SCRIPT_CACHE` memory leak**: Module-level dict never cleared. Long-running processes with many unique scripts will accumulate entries indefinitely.
- **Type mapping limitation**: `_TYPE_MAP` only handles `str`, `int`, `float`, `bool` — no `list`, `dict`, or complex types.

### 4.11 LSP Server (`lsp/`)

**Quality: Adequate — but thin**

Post-refactor state:
- `lsp/__init__.py` now has lazy import with clear error message for missing `pygls`. This is an improvement over the previous unconditional import.
- Implements: `textDocument/codeLens`, `textDocument/hover`, `textDocument/didSave`, `textDocument/didOpen`.

**Remaining issues:**
- **Not started by the CLI**: `remora start` doesn't launch the LSP server. No `remora lsp` command exists.
- **No `textDocument/didChange` handler**: No cursor position tracking.
- **`remora.showNode` command not registered**: Referenced in CodeLens but clicking it would fail.
- **`_uri_to_path()` redundancy**: Dual path handling — `file://` prefix removed both via `urlparse` and `removeprefix`.
- **No LSP → Web bridge**: LSP state doesn't flow to the web server.

### 4.12 Web Server & UI (`web/`)

**Quality: Good for MVP**

Post-refactor state:
- `api_all_edges()` now uses `node_store.list_all_edges()` instead of raw `node_store.db.fetch_all(...)`. Clean.
- UI subtitle updated to "Live agent graph".
- Starlette app with REST API + SSE streaming.
- Sigma.js + graphology force-directed graph, node detail sidebar, chat input, live event log.

**Remaining observations:**
- Graph layout uses random initial positions + 30 ForceAtlas2 iterations — layout quality varies.
- No authentication or CORS configuration — fine for local use.
- `_INDEX_HTML` loaded at import time — requires process restart for changes.
- No request validation on `/api/chat` (doesn't verify node exists before routing the message).

### 4.13 CLI (`__main__.py`)

**Quality: Good**

- Two commands: `start` (full runtime) and `discover` (scan-only).
- Clean async orchestration with managed asyncio tasks.
- Rotating file logging + optional event activity logging.
- Graceful shutdown with task cancellation.

**Remaining observations:**
- No `remora lsp` command — the LSP server is disconnected from the CLI.
- `_stop_event()` creates an untracked asyncio task (same pattern as reconciler).

### 4.14 Bundle System (`bundles/`)

**Quality: Good**

- Three-tier overlay: `system` (always loaded) → role-specific (`code-agent`, `directory-agent`).
- Bundle YAML configures: `system_prompt`, `system_prompt_extension`, `prompts.chat`, `prompts.reactive`, `model`, `max_turns`.
- System tools (12 `.pym` scripts) cover messaging, subscriptions, reflection, workspace, and graph queries.
- Role-specific tools: code-agents get `rewrite_self` + `scaffold`; directory-agents get `list_children`, `get_parent`, `broadcast_children`, `summarize_tree`.

Post-refactor: `rewrite_self.pym` now correctly uses `apply_rewrite` external.

**Remaining observations:**
- KV tool scripts (`kv_get.pym`, `kv_set.pym`) are trivial wrappers — the overhead of Grail script parsing for simple delegation is questionable but consistent with the pattern.

---

## 5. Conceptual Alignment Assessment

This section evaluates whether every part of the codebase is in full alignment with remora's conceptual goal: **code elements as first-class autonomous agents that observe, communicate, and act within their codebase in real time.**

### Well-Aligned Areas

**Discovery → Node → Actor pipeline**: This is the conceptual core and it's clean. Tree-sitter discovers code elements, projects them to Nodes, and each Node gets an Actor with inbox/outbox. The naming is consistent: `Node`, `Actor`, `ActorPool`, `TurnContext`. Events flow through `EventStore` → `TriggerDispatcher` → `Actor.inbox`. This pipeline fully embodies the concept.

**Bundle overlay system**: The three-tier overlay (system → role → instance) is well-aligned. Different node types (function, class, method, directory) get different agent behaviors via bundle configuration. This supports the "each code element is its own kind of agent" vision.

**Event-driven reactivity**: The subscription-based dispatch with pattern matching (`event_types`, `path_glob`, `to_agent`, `from_agents`) is architecturally sound and conceptually aligned. Agents react to events about their code — exactly what the vision demands.

### Partially Aligned Areas

**1. Dual parameter naming in `grail.py`**
`GrailTool.__init__()` and `discover_tools()` both accept `capabilities` and `externals` parameters. Internally, `capabilities` is the canonical name (matching `TurnContext.to_capabilities_dict()`), but the `externals` fallback remains. This is a vestigial compatibility pattern that survived the alignment refactor.

**Impact**: Minor naming confusion. A new developer reading `grail.py` would wonder why two parameter names exist for the same thing.

**2. `code_node` variable in `projections.py`**
Line 44: `code_node = Node(...)`. The `code_` prefix is from the old `CodeNode` era. The current naming convention uses `Node` without prefix.

**Impact**: Cosmetic. One local variable in one file.

**3. Reconciler comment referencing migration**
Lines 51-52: `"Re-register directory subscriptions once after startup so older subscription shapes are migrated without requiring a DB reset."` The word "migrated" implies backward compatibility with old data formats — but after the alignment refactor, there are no "older subscription shapes" to migrate. The re-registration is just for consistency.

**Impact**: Misleading comment that suggests legacy support that no longer exists.

**4. LSP server is architecturally disconnected**
The LSP adapter has no CLI entry point, no connection to the web server, and is missing key handlers (`didChange`, `showNode` command). It exists as a separate module but isn't wired into the runtime. This is *conceptually* misaligned because the vision includes editor integration as a core surface, not an afterthought.

**Impact**: The LSP is currently a stub rather than a first-class surface.

**5. README mentions "proposal approval flow"**
The README references concepts that may not reflect the current architecture. Documentation-code drift weakens conceptual clarity.

### Misaligned Areas

**No significant misalignment found.** The alignment refactor successfully removed the backward-compatibility layer. The remaining issues above are minor — vestigial naming in 2-3 locations and one disconnected module. The core architecture is conceptually tight.

---

## 6. Previous Code Review: Issue Status

Each issue from the pre-refactor code review, with current status.

| # | Issue | Severity | Status | Notes |
|---|-------|----------|--------|-------|
| 1 | `rewrite_self.pym` broken (`propose_rewrite` → `apply_rewrite`) | Critical | **FIXED** | Now correctly references `apply_rewrite` |
| 2 | LSP server not started by CLI | Critical | **Still Open** | No `remora lsp` command. No `--lsp` flag. |
| 3 | `Actor._execute_turn()` too complex (~120 lines) | High | **Still Open** | No decomposition applied. Same complexity. |
| 4 | `NodeStore`/`AgentStore` table creation duplication | High | **Still Open** | Both still create `agents` table. |
| 5 | `_SCRIPT_CACHE` memory leak (never cleared) | High | **Still Open** | Module-level dict, no eviction. |
| 6 | Reconciler race condition (`_on_content_changed` + `run_forever`) | High | **Still Open** | No per-file locking added. |
| 7 | `EventBus.emit()` sequential handler execution | Medium | **Still Open** | Still awaits each handler one at a time. |
| 8 | Missing `textDocument/didChange` LSP handler | Medium | **Still Open** | No cursor tracking capability. |
| 9 | Web UI graph layout instability | Medium | **Still Open** | Random positions + fixed FA2 iterations. |
| 10 | No request validation on web API (`/api/chat`) | Medium | **Still Open** | Doesn't verify node exists. |
| 11 | Backward-compat aliases (`CodeElement`, etc.) | Low | **FIXED** | All aliases removed. |
| 12 | `_uri_to_path()` redundant dual path handling | Low | **Still Open** | Still removes `file://` twice. |
| 13 | Bundle provisioning on every reconcile (no fingerprinting) | Low | **Still Open** | Still re-writes files every time. |
| 14 | `_stop_event()` task leak (untracked asyncio task) | Low | **Still Open** | Task still not stored or cancelled. |
| 15 | Tree-sitter query path hardcoding | Low | **Effectively Resolved** | `query_paths` config exists and is used. The default path is package-relative, which is correct behavior. |

**Summary**: 3 of 15 issues fixed (issues 1, 11, 15). 12 remain open. The alignment refactor correctly targeted conceptual alignment (aliases, migration code, naming) rather than structural/behavioral issues. The remaining issues are architectural improvements, not alignment problems.

---

## 7. Strengths

1. **Conceptual clarity after refactor**: One name per concept, no aliases, no migration shims. The codebase reads cleanly — `Node`, `Actor`, `ActorPool`, `TurnContext`, `EventStore` are each exactly what they claim to be.

2. **Clean architecture**: Clear separation between discovery, persistence, events, execution, and surfaces. `RuntimeServices` provides clean dependency injection.

3. **Event-driven consistency**: Everything flows through `EventStore` → `EventBus` + `TriggerDispatcher`. No direct coupling between components.

4. **Pragmatic database design**: SQLite with WAL mode is the right choice for a single-process, local-first system. The `AsyncDB` wrapper is clean and minimal.

5. **Actor model with per-actor policy**: Cooldown and depth tracking per-actor prevent runaway cascades without global coordination. The `Outbox` as a write-through tagger (not a buffer) is a good design choice.

6. **Extensible language support**: Plugin-based tree-sitter discovery with external query overrides. Adding a language requires only a `LanguagePlugin` class and a `.scm` file.

7. **Bundle overlay system**: Three-tier configuration provides good defaults with full customizability per agent type. Grail tool isolation means agents can't access each other's state directly.

8. **Comprehensive test suite**: ~4,789 lines of tests covering every module with both unit and integration tests. Factory helpers reduce boilerplate. Tests use real SQLite.

9. **SSE streaming with replay**: Real-time event propagation to web clients, with replay for late joiners.

10. **Small, focused codebase**: ~4,173 lines of source for a full reactive agent substrate with web UI, LSP adapter, event system, actor model, and multi-language code discovery. Impressive density.

11. **Clean `__all__` exports everywhere**: Every module declares explicit `__all__` — no accidental API surface.

---

## 8. Issues & Recommendations

### Critical

**C1. LSP server not started by CLI** (carried from previous review #2)
`remora start` doesn't launch the LSP server. There's no `remora lsp` command or `--lsp` flag. The LSP module is architecturally disconnected.
**Recommendation**: Add a `remora lsp` command, or integrate LSP startup into `remora start` with an `--lsp` flag.

### High Priority

**H1. `Actor._execute_turn()` too complex** (carried from #3)
~120-line method with 7+ responsibilities. The most complex method in the codebase.
**Recommendation**: Extract into helper methods: `_build_messages()`, `_resolve_tools()`, `_run_llm_turn()`, `_finalize_turn()`.

**H2. `NodeStore`/`AgentStore` table creation duplication** (carried from #4)
Both create the `agents` table. `CREATE TABLE IF NOT EXISTS` prevents errors but ownership is unclear.
**Recommendation**: Remove `agents` table creation from `NodeStore.create_tables()`. Let `AgentStore` be the sole owner.

**H3. `_SCRIPT_CACHE` memory leak** (carried from #5)
Module-level `dict[str, GrailScript]` never cleared.
**Recommendation**: Replace with `functools.lru_cache` or add a max-size eviction policy.

**H4. Reconciler race condition** (carried from #6)
`_on_content_changed()` and `run_forever()` can trigger concurrent `_reconcile_file()` calls for the same file path.
**Recommendation**: Add per-file `asyncio.Lock` or a deduplication queue.

**H5. Dual parameter naming in `grail.py`** (new — alignment issue)
`GrailTool.__init__()` and `discover_tools()` both accept `capabilities` AND `externals` parameters. The `externals` parameter is a vestigial compatibility pattern.
**Recommendation**: Remove the `externals` parameter from both. All callers already use `capabilities`.

### Medium Priority

**M1. `EventBus.emit()` sequential execution** (carried from #7)
Each handler is awaited one at a time. A slow handler blocks all subsequent handlers.
**Recommendation**: Consider `asyncio.gather()` for independent handlers.

**M2. Missing `textDocument/didChange` LSP handler** (carried from #8)
Required for any cursor-tracking or live editing feature.
**Recommendation**: Add handler that emits a cursor/edit position event.

**M3. Web UI graph layout instability** (carried from #9)
Random initial positions + fixed 30 ForceAtlas2 iterations produces inconsistent layouts.
**Recommendation**: Use deterministic initial layout (hierarchy-based) or run FA2 continuously.

**M4. No request validation on `/api/chat`** (carried from #10)
Doesn't verify the target node exists before routing the message.
**Recommendation**: Check `node_store.get_node(node_id)` and return 404 if missing.

**M5. `_stop_event()` task leak** (carried from #14, elevated)
Both reconciler and CLI create untracked `asyncio.Task` instances for stop signaling.
**Recommendation**: Store the task reference and cancel it during cleanup.

### Low Priority

**L1. `_uri_to_path()` redundant dual handling** (carried from #12)
Removes `file://` prefix twice.
**Recommendation**: Simplify to single `urlparse` path.

**L2. Bundle provisioning on every reconcile** (carried from #13)
`provision_bundle()` re-writes files every time with no fingerprinting.
**Recommendation**: Hash template contents and skip provisioning when unchanged.

**L3. Stale reconciler comment** (new — alignment issue)
Lines 51-52 reference "older subscription shapes are migrated" — no longer applicable post-refactor.
**Recommendation**: Update to "Re-register directory subscriptions once after startup to ensure consistency."

**L4. `code_node` variable name in `projections.py`** (new — alignment issue)
Line 44 uses `code_node` instead of `node`.
**Recommendation**: Rename to `node` for consistency with current naming convention.

**L5. `discover()` creates new `LanguageRegistry` per call** (carried, low priority)
Lightweight but wasteful.
**Recommendation**: Accept an optional pre-built registry or cache at module level.

---

*End of Post-Alignment Code Review*
