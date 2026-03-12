# Remora-v2 Comprehensive Code Review

## Table of Contents
- [1. Library Overview](#1-library-overview)
- [2. Architecture Map](#2-architecture-map)
- [3. Module-by-Module Analysis](#3-module-by-module-analysis)
- [4. Cross-Cutting Concerns](#4-cross-cutting-concerns)
- [5. Test Suite Analysis](#5-test-suite-analysis)
- [6. Correctness Issues (by severity)](#6-correctness-issues)
- [7. Strengths](#7-strengths)
- [8. Refactoring Recommendations & Opportunities](#8-refactoring-recommendations--opportunities)

---

## 1. Library Overview

### What Remora Is

Remora is an **event-driven autonomous agent runtime** that transforms discovered code elements (functions, classes, methods, markdown sections, TOML tables) into independent agents. Each code node becomes an agent with its own identity, workspace, toolset, and subscription-driven lifecycle.

### What It Does

1. **Discovers** code structure using tree-sitter queries across multiple languages (Python, Markdown, TOML)
2. **Projects** discovered CST nodes into persisted `CodeNode` agents with graph relationships
3. **Reconciles** file changes continuously, keeping the agent graph in sync with source code
4. **Routes events** through a subscription system that triggers agent execution
5. **Executes agents** via an LLM kernel (structured-agents) with Grail tool scripts
6. **Exposes** the graph state via a web UI (Sigma.js graph visualization + REST/SSE) and LSP integration

### How It Does It (Data Flow)

```
Source Files → [tree-sitter discovery] → CSTNode[]
    → [project_nodes] → CodeNode[] (persisted in SQLite)
    → [FileReconciler] → NodeDiscovered/Changed/Removed events
    → [EventStore + SubscriptionRegistry] → trigger queue
    → [AgentRunner] → LLM kernel execution with Grail tools
    → [Web/LSP adapters] → human-facing surfaces
```

### Key Dependencies

- **cairn** — workspace filesystem abstraction (per-agent sandboxed storage)
- **fsdantic** — filesystem data models (used by cairn)
- **structured-agents** — LLM kernel, message types, tool schema
- **grail** — scripted tool runtime (`.pym` files)
- **tree-sitter** — multi-language parsing
- **pydantic / pydantic-settings** — data models and config
- **starlette / uvicorn** — web server
- **pygls / lsprotocol** — LSP server
- **typer** — CLI

### Scale

- **3,173 lines** of source across 21 Python files
- **125 tests** (all passing) across 25 test files
- 3 tree-sitter query files (.scm)
- 3 bundle directories with 11 Grail tool scripts

---

## 2. Architecture Map

### Module Layout

```
remora/
├── __init__.py          (3 lines — version only)
├── __main__.py          (204 lines — CLI + async startup orchestration)
├── utils/__init__.py    (1 line — empty package)
├── core/
│   ├── config.py        (117 lines — pydantic-settings Config + YAML loader)
│   ├── events.py        (553 lines — Event types + EventBus + SubscriptionRegistry + EventStore)
│   ├── node.py          (54 lines — CodeNode model)
│   ├── graph.py         (221 lines — NodeStore SQLite persistence)
│   ├── runner.py        (432 lines — AgentRunner + externals contract)
│   ├── workspace.py     (187 lines — Cairn workspace integration)
│   ├── grail.py         (123 lines — Grail tool loading)
│   └── kernel.py        (59 lines — structured-agents kernel wrapper)
├── code/
│   ├── discovery.py     (303 lines — tree-sitter discovery)
│   ├── projections.py   (69 lines — CSTNode → CodeNode projection)
│   ├── reconciler.py    (240 lines — FileReconciler)
│   └── queries/         (3 .scm files)
├── web/
│   ├── server.py        (188 lines — Starlette REST/SSE API)
│   └── views.py         (297 lines — inline HTML/JS template)
└── lsp/
    └── server.py        (103 lines — pygls LSP adapter)
```

### Dependency Graph (internal modules)

```
__main__ → config, events, graph, runner, workspace, reconciler, discovery, web.server
runner → config, events, graph, workspace, grail, kernel, node
reconciler → config, events, graph, workspace, discovery, projections
projections → config, graph, workspace, discovery, node
events → (self-contained — models, bus, subscriptions, store)
graph → node
workspace → config
grail → workspace
web.server → events, web.views
lsp.server → events, node
```

---

## 3. Module-by-Module Analysis

### 3.1 `core/events.py` (553 lines) — THE GOD MODULE

This is the largest and most concerning module. It contains **four fundamentally different responsibilities**:

1. **Event type definitions** (12 event classes): Lines 17-114
2. **EventBus** (in-memory pub/sub): Lines 120-178
3. **SubscriptionRegistry** (SQLite-persisted pattern matching): Lines 181-339
4. **EventStore** (SQLite event log + trigger queue): Lines 342-553

**Issues:**
- **Single Responsibility Violation**: Four distinct concerns in one file. EventBus, SubscriptionRegistry, and EventStore are each substantial abstractions that deserve their own modules.
- **EventStore dual-initialization**: Can be constructed with either `db_path` OR `connection`, leading to two code paths, `assert self._conn is not None` sprinkled around, and a `_owns_connection` flag. This is a sign the constructor is doing too much.
- **SubscriptionRegistry lazy initialization**: The `await self.initialize()` call is repeated at the top of every public method. This is a defensive pattern that suggests the object isn't properly initialized at construction time.
- **Trigger queue coupling**: EventStore owns `_trigger_queue` (the pipeline between event persistence and agent execution). This tightly couples storage to execution dispatch.
- **`_summarize` is hardcoded switch**: Static method that pattern-matches on event types to extract summary text. This should be a method on each Event subclass.
- **`SubscriptionPattern.matches` uses `getattr` for duck-typed field access**: Lines 195-208. Pattern matching against events uses `getattr(event, "from_agent", None)`, `getattr(event, "to_agent", None)`, etc. This bypasses type safety entirely and means patterns silently fail to match if event field names change.

### 3.2 `core/runner.py` (432 lines) — EXTERNALS SPRAWL

The runner has two jobs: orchestrating agent turns and defining the externals contract (the API surface exposed to agent tools).

**Issues:**
- **`_build_externals` is 170+ lines of inline closures**: Lines 205-379. This single method defines 18 async closure functions that capture `node_id`, `workspace`, and `correlation_id` from the enclosing scope. This is the entire tool API expressed as nested functions.
- **`pending_approval` status is still overwritten**: The `finally` block at line 176-185 unconditionally resets status to `idle`, clobbering the `pending_approval` state set by `propose_rewrite`. This was flagged in CODE_REVIEW_1 and **remains unfixed**.
- **`propose_rewrite` uses string replacement**: Line 334 does `full_source.replace(old_source, new_source, 1)`. If the same code block appears twice in a file, this patches the wrong one.
- **No state machine for node status**: Status transitions are ad-hoc: `set_status(node_id, "running")` at line 120, `set_status(node_id, "idle")` at line 178, `set_status(node_id, "pending_approval")` at line 351. There's no enforcement of valid transitions.
- **`search_content` is O(n*m) brute force**: Lines 227-241. Reads every file in the workspace, scans every line for a substring match. For large workspaces this will be extremely slow.
- **Fire-and-forget task creation**: Line 106 creates a task with `asyncio.create_task` but never stores or awaits it. If the task fails silently, there's no tracking.

### 3.3 `core/graph.py` (221 lines) — CLEAN BUT LOW-LEVEL

NodeStore is well-structured SQLite persistence with proper locking. However:

**Issues:**
- **Every method acquires the global lock and uses `to_thread`**: Even for trivial reads. This serializes all graph access through a single lock + thread-hop pair. For a single-writer SQLite database in WAL mode, this is over-conservative for reads.
- **`list_nodes` builds SQL dynamically**: Lines 112-124 construct WHERE clauses from optional parameters. This is correct but fragile — adding new filter dimensions means growing the conditional chain.
- **`Edge` is defined here but barely used**: The `Edge` dataclass exists, but edges are primarily used by the web API as dicts (converted immediately in `runner._build_externals`). Edges don't carry weight, metadata, or timestamps — they're effectively unused beyond basic "calls" relationships.
- **`caller_ids`/`callee_ids` on CodeNode are JSON-serialized lists**: These are stored as JSON strings in SQLite but are also duplicated as proper edges in the `edges` table. This is redundant.

### 3.4 `core/node.py` (54 lines) — MUTABLE DATA MODEL

**Issues:**
- **`CodeNode` is mutable** (`frozen=False`): Yet it's used as both a database row representation AND an in-memory working model. Mutability means any code holding a reference can change it, leading to subtle bugs when the same object is accessed from multiple contexts.
- **`status` is a bare `str`**: No validation, no enum, no state machine. Any string is accepted.
- **`node_type` is a bare `str`**: Same issue. The set of valid types (`function`, `class`, `method`, `section`, `table`) is implicit.
- **Dual serialization**: `to_row()`/`from_row()` hand-rolls JSON serialization for list fields. Pydantic already has serialization machinery — this is unnecessary manual work.

### 3.5 `core/workspace.py` (187 lines) — WELL-LAYERED

AgentWorkspace is a clean facade over Cairn's raw workspace API with stable-workspace fallthrough. CairnWorkspaceService manages workspace lifecycle.

**Issues:**
- **`AgentWorkspace` has a per-instance lock**: Line 25. This serializes ALL operations on a workspace, even reads that could safely be concurrent. For a workspace that wraps an already-safe filesystem abstraction, this is potentially unnecessary overhead.
- **`list_all_paths` is expensive**: It queries both agent and stable workspaces with a `**/*` glob pattern. Called by `search_files` and `search_content` in externals, this could be called multiple times per agent turn.
- **`_safe_id` uses SHA-1**: Line 182. SHA-1 is considered cryptographically weak. While this is just for filesystem names, SHA-256 would be more consistent with the rest of the codebase (which uses SHA-256 for content hashing).
- **Unbounded workspace cache**: `_agent_workspaces` dict grows forever. In a long-running system with many node churn cycles, this leaks memory.

### 3.6 `core/grail.py` (123 lines) — REASONABLE THIN WRAPPER

Grail tool loading writes source to a temp file, parses it, and wraps it in a `GrailTool` adapter.

**Issues:**
- **Every tool load creates and destroys a temp directory**: `_load_script_from_source` creates a `TemporaryDirectory` per script per load. Tools are re-loaded on every agent turn (via `discover_tools`), meaning temp dirs are churned rapidly.
- **No caching of loaded scripts**: If the same tool is used by 100 agents, it's parsed 100 times from source each turn.
- **`_TYPE_MAP` is incomplete**: Only maps `str`, `int`, `float`, `bool`. Grail may support additional types.

### 3.7 `core/kernel.py` (59 lines) — CLEAN ADAPTER

Thin wrapper around structured-agents. No significant issues. The `extract_response_text` function is fragile with duck-typing (`hasattr` checks) but acceptable for a boundary adapter.

### 3.8 `core/config.py` (117 lines) — SOLID

pydantic-settings with YAML loading, env var expansion, and config file discovery. Well-structured.

**Minor issues:**
- **`frozen=True` prevents runtime modification**: While generally good, this means config can't be updated without full re-creation. For a runtime that might want to hot-reload config, this could be limiting.
- **No validation of `language_map` values against `_GRAMMAR_REGISTRY`**: Config accepts any string as a language name. Invalid languages are silently skipped at discovery time rather than caught at config load.

### 3.9 `code/discovery.py` (303 lines) — GOOD BUT COMPLEX

Tree-sitter based discovery. The core algorithm is solid.

**Issues:**
- **`_parse_file` is 80+ lines**: This function does parsing, query execution, deduplication, parent-chain resolution, and CSTNode construction. It should be decomposed.
- **`_node_key` is (start_byte, end_byte, type)**: This tuple is used as the canonical identity within a file parse. If two different syntactic constructs happen to occupy the same byte range with the same type (unlikely but theoretically possible with tree-sitter ambiguity), they'd collide.
- **Node ID collisions**: IDs are `file_path::full_name`. Two functions with the same name at different scopes (e.g., two `__init__` methods in different classes in the same file) will collide if the parent-chain somehow resolves identically. This was flagged in CODE_REVIEW_1.
- **`_resolve_node_type` is a hardcoded dispatch**: Lines 237-255. Language-specific type resolution is embedded in a series of if/elif chains. Adding a new language requires modifying this function.
- **`_has_class_ancestor` re-walks the tree**: For every function node, this walks up the entire parent chain checking for class ancestors. The parent-chain is already computed in `_parse_file` — this is redundant work.
- **`lru_cache` on `_load_query` with string key**: Line 133. The cache key is the query file path as a string. If the file changes on disk, the cache returns stale content until the process restarts.

### 3.10 `code/projections.py` (69 lines) — CLEAN

Straightforward CSTNode → CodeNode mapping with bundle provisioning.

**Issues:**
- **Queries NodeStore per node**: Line 27 calls `await node_store.get_node(cst.node_id)` for every CSTNode in the batch. For large files with many nodes, this is N individual SQLite queries where a batch query would suffice.
- **Bundle provisioning side effect**: The function both persists nodes AND provisions workspaces. These are conceptually different operations.

### 3.11 `code/reconciler.py` (240 lines) — GOOD STRUCTURE, DUPLICATED LOGIC

**Issues:**
- **`_iter_source_files` duplicates `_walk_source_files` from discovery.py**: Lines 188-230 implement nearly identical file walking + ignore pattern logic as `discovery._walk_source_files` (lines 78-114). Same patterns, same `fnmatch` logic, same `rglob` approach. This was flagged in CODE_REVIEW_1 as "path resolution/walking logic is duplicated across modules."
- **`_resolve_query_paths` duplicates logic from `__main__._discover`**: Lines 232-239 resolve query paths from config exactly as `__main__.py` lines 183-188 do.
- **No fault isolation in `run_forever`**: If `reconcile_cycle` raises an unexpected exception, `run_forever` exits and the background task dies silently. This was flagged in CODE_REVIEW_1.
- **Full re-discovery of changed files**: `_reconcile_file` calls `discover([Path(file_path)], ...)` which creates a new parser, loads query files, and parses from scratch. There's no incremental parsing support leveraged from tree-sitter.

### 3.12 `web/server.py` (188 lines) — FUNCTIONAL BUT FRAGILE

**Issues:**
- **`_find_proposal` scans last 1000 events**: Line 159. Proposal lookup is a linear scan of the most recent 1000 events. In a busy system, old proposals become unfindable. This was flagged in CODE_REVIEW_1.
- **No concurrency guard on `api_approve`**: Line 118 writes to the file without checking that the file hasn't changed since the proposal was created. Stale approvals can overwrite newer edits. Flagged in CODE_REVIEW_1.
- **Closure-based route handlers**: All routes are defined as closures inside `create_app`, capturing `event_store`, `node_store`, etc. This is functional but makes the handlers hard to test independently and hard to extend.
- **`Any` type annotations on parameters**: `create_app` takes `event_store: Any`, `node_store: Any`, etc. This loses all type safety.
- **No request validation middleware**: JSON parsing failures from malformed POST bodies would produce unhelpful 500 errors.

### 3.13 `web/views.py` (297 lines) — INLINE HTML TEMPLATE

**Issues:**
- **Entire web UI is a single Python string**: 290 lines of HTML/CSS/JS inlined in a Python file. This makes the frontend impossible to lint, format, test, or iterate on with web development tools.
- **CDN dependencies with pinned versions**: Graphology, Sigma, and ForceAtlas2 are loaded from unpkg.com. No integrity hashes, no fallback.
- **No NodeRemovedEvent handling**: The SSE listener handles `NodeDiscoveredEvent`, `AgentStartEvent`, `AgentCompleteEvent`, `AgentErrorEvent` — but NOT `NodeRemovedEvent` or `NodeChangedEvent`. Stale nodes persist in the graph until page reload. Flagged in CODE_REVIEW_1.
- **`loadGraph` fetches edges per-node**: Line 158. For N nodes, this makes N+1 HTTP requests. A batch endpoint would be better.

### 3.14 `lsp/server.py` (103 lines) — CLEAN

Well-structured LSP adapter. Minor issues:
- **`_remora_handlers` monkey-patch**: Line 45 attaches handlers to the server instance for testing. This is a pragmatic workaround but breaks encapsulation.
- **`__all__` exports private functions**: `_node_to_lens`, `_node_to_hover`, `_find_node_at_line` are exported despite being underscore-prefixed.

### 3.15 `__main__.py` (204 lines) — ORCHESTRATION BLOAT

**Issues:**
- **`_start` is 80+ lines of setup**: Database creation, store initialization, reconciler creation, runner creation, web server creation, task management, and shutdown logic all in one function.
- **`_discover` duplicates path resolution logic**: Lines 177-188 resolve `discovery_paths` and `query_paths` from config. The reconciler does this same thing in `_iter_source_files` and `_resolve_query_paths`.
- **SQLite connection management**: Lines 92-97 set up SQLite with pragmas. This is duplicated in `EventStore.initialize()` (lines 396-397 of events.py).
- **No dependency injection**: All wiring is done procedurally. There's no container, factory, or builder pattern. Adding a new component means modifying `_start`.

---

## 4. Cross-Cutting Concerns

### 4.1 SQLite Usage Pattern

Every SQLite-backed class follows the same pattern:
1. Accept `connection` and `lock` in constructor
2. Define `async def method(self)` that wraps a `def run()` closure
3. Acquire lock: `async with self._lock:`
4. Hop to thread: `await asyncio.to_thread(run)`
5. Call `self._conn.commit()` inside `run()`

This pattern is repeated ~25 times across `NodeStore`, `EventStore`, `SubscriptionRegistry`. It's correct but extremely verbose. Each method is ~15 lines of boilerplate around 2-3 lines of actual SQL.

**Opportunity**: A simple async SQLite wrapper that handles lock + thread-hop + commit would eliminate ~300 lines of boilerplate.

### 4.2 Error Handling Philosophy

The codebase uses broad exception catches at boundaries:
- `except Exception: # noqa: BLE001` in runner, grail, workspace
- These are appropriate at system boundaries but some catches are too broad (e.g., `_execute_turn` catches everything including `KeyboardInterrupt` via the `Exception` base class — though in practice Python 3.13's BaseException hierarchy makes this less of an issue)

**Missing**: No structured error propagation. When an agent tool fails, the error becomes a string in a `ToolResult`. When reconciliation fails on a file, the exception propagates and kills the cycle. There's no error event emission for infrastructure failures.

### 4.3 Type Safety

- **`Any` proliferates**: `events.py` uses `dict[str, Any]` for event queries. `runner.py` uses `dict[str, Any]` for externals. `web/server.py` uses `Any` for all its constructor parameters.
- **`str` as enum**: `node_type`, `status`, `edge_type`, `event_type`, `change_type` are all bare strings with no validation.
- **`getattr` for field access**: `SubscriptionPattern.matches()` and `EventStore._summarize()` use `getattr` to duck-type event fields.

### 4.4 Configuration Propagation

Config is passed explicitly through constructor chains: `_start` → `FileReconciler(config, ...)` → uses `config.discovery_paths`, `config.language_map`, etc. Multiple modules independently resolve config paths (discovery paths, query paths) with identical logic.

### 4.5 Async Patterns

- **Everything is async**: Even synchronous operations like `_walk_source_files` (pure filesystem traversal) are called from async contexts, sometimes with unnecessary `await`s.
- **`asyncio.to_thread` everywhere**: Used for all SQLite operations. This is correct for thread-safety but means every DB call incurs thread pool overhead.
- **No structured concurrency**: Tasks are created with `asyncio.create_task` and gathered in `_start`. The runner creates fire-and-forget tasks for each agent turn.

---

## 5. Test Suite Analysis

### Coverage

- **125 tests** across 25 files
- **Good unit coverage**: events, event bus, event store, subscriptions, graph/node store, discovery, projections, reconciler, runner, workspace, grail, kernel, config, CLI, LSP, web server, views
- **Integration tests**: e2e flow (human chat → rewrite → approval), agent message chain, file change triggers
- **Performance tests**: Discovery of 100+ nodes, 100 upserts, 1000 subscription matches

### Gaps

1. **No test for `pending_approval` persistence after turn completion**: The critical bug where `finally` resets status to `idle` is not caught by any test.
2. **No test for duplicate `old_source` replacement correctness**: The string-replace rewrite bug is untested.
3. **No test for stale proposal rejection on concurrent edits**: The approval endpoint's lack of concurrency checks is untested.
4. **No test for reconciler fault isolation**: No test verifies that a single-file parse error doesn't kill the reconciler loop.
5. **No test for `NodeRemovedEvent`/`NodeChangedEvent` in web views**: The SSE event handling gap is untested.
6. **No test for `broadcast` with `"siblings"` or `"file:"` patterns**: Only `"*"` broadcast is tested.
7. **No negative tests for config validation**: Invalid language maps, invalid paths, etc.
8. **Test helpers are duplicated**: `_node()`, `_write()`, `_make_cst()`, `_write_bundle_templates()` are defined independently in 6+ test files.

### Test Quality

- Tests are well-structured with clean fixtures
- Good use of `monkeypatch` for dependency isolation
- Async tests use `pytest-asyncio` correctly
- Integration tests exercise realistic multi-component flows
- Performance tests have reasonable thresholds

---

## 6. Correctness Issues

### Critical

**C1. `pending_approval` status is clobbered by `finally` block**
- Location: `runner.py:176-180`
- The `_execute_turn` `finally` block unconditionally sets status to `idle`, overwriting `pending_approval` set by `propose_rewrite` during the same turn.
- Impact: The approval workflow is semantically broken. A node that proposed a rewrite appears as `idle` in the UI immediately after the turn ends.
- First flagged in CODE_REVIEW_1 (finding #1). **Still unfixed.**

**C2. Rewrite uses string replacement, not span-based patching**
- Location: `runner.py:334`
- `full_source.replace(old_source, new_source, 1)` finds the first textual match. If identical code blocks exist in the file (e.g., duplicated functions, copy-pasted blocks), this patches the wrong one.
- Impact: Silent data corruption in edge cases.
- First flagged in CODE_REVIEW_1 (finding #2). **Still unfixed.**

**C3. Approval endpoint has no concurrency guard**
- Location: `web/server.py:117-118`
- `file_path.write_text(str(proposal["new_source"]))` writes without checking that the file hasn't changed since the proposal was created. No hash/content comparison.
- Impact: Stale approvals can silently overwrite newer edits.
- First flagged in CODE_REVIEW_1 (finding #3). **Still unfixed.**

### High

**H1. Discovery ID collisions for same-name definitions**
- Location: `discovery.py:220`
- `node_id = f"{file_path}::{full_name}"`. Two overloaded functions, two `__init__` methods in nested classes, or any same-name definitions in one file produce the same ID.
- Impact: One node silently shadows the other. The persisted graph is corrupted.
- First flagged in CODE_REVIEW_1 (finding #4). **Still unfixed.**

**H2. Reconciler loop has no fault isolation**
- Location: `reconciler.py:71-79`
- Any unexpected exception in `reconcile_cycle` (e.g., file permission error, tree-sitter parse error on malformed source) propagates through `run_forever` and kills the background task.
- Impact: The system silently stops tracking file changes.
- First flagged in CODE_REVIEW_1 (finding #5). **Still unfixed.**

**H3. `_cooldowns` and `_depths` dicts grow unbounded**
- Location: `runner.py:64-65`
- `_cooldowns: dict[str, float]` and `_depths: dict[str, int]` are never cleaned up for nodes that no longer exist. In a long-running system with node churn, these leak memory.

### Medium

**M1. `_find_proposal` is bounded to last 1000 events**
- Location: `web/server.py:159`
- Linear scan makes old proposals undiscoverable. In production with active agents, 1000 events could be exhausted in minutes.

**M2. Web graph doesn't handle `NodeRemovedEvent` or `NodeChangedEvent`**
- Location: `web/views.py:240-288`
- SSE listeners exist for discovered/start/complete/error but not removed/changed. Deleted nodes persist as stale graph entries.

**M3. Tool scripts are re-parsed from source on every agent turn**
- Location: `grail.py:99-120` + `runner.py:139`
- `discover_tools` is called per turn, loads tool source from workspace, writes to temp dir, parses with grail. No caching.

---

## 7. Strengths

1. **Clean separation of discovery/projection/reconciliation**: The three-phase pipeline (discover → project → reconcile) is well-defined with clear data models at each boundary.

2. **Tree-sitter query system with overrides**: The `.scm` query file mechanism with user-override precedence is elegant and extensible.

3. **Test coverage breadth**: 125 tests covering core flows with good isolation and realistic integration tests.

4. **Workspace sandboxing**: Per-agent workspaces with stable fallthrough is a solid isolation model.

5. **Event-driven architecture**: The EventBus + SubscriptionRegistry + trigger queue pattern is sound and decoupled.

6. **Pydantic data models**: Consistent use of Pydantic for event types, configuration, and node models provides good serialization and validation.

7. **Security**: XSS handling in views, project-root path checks in the approval endpoint, and workspace isolation all show security awareness.

---

## 8. Refactoring Recommendations & Opportunities

These are ordered from highest-impact architectural changes to incremental improvements. Since backwards compatibility is not a concern, these represent the full spectrum of options.

### Tier 1: Architectural Redesign

#### R1. Split `events.py` into a proper event system package

The 553-line god module should become:

```
core/events/
├── __init__.py      — re-exports
├── types.py         — Event base + all event type classes
├── bus.py           — EventBus (in-memory pub/sub)
├── subscriptions.py — SubscriptionPattern + SubscriptionRegistry
└── store.py         — EventStore (persistence + trigger queue)
```

Or even further — extract the trigger queue into its own `dispatcher.py`, since trigger dispatch is a distinct concern from event persistence.

**Why**: Every module in the codebase imports from `events.py`. Splitting it reduces coupling, makes each piece independently testable, and makes the architecture self-documenting through file structure.

#### R2. Extract an async SQLite layer

Create a reusable async SQLite wrapper that handles the lock + thread-hop + commit pattern once:

```python
class AsyncDB:
    def __init__(self, conn: sqlite3.Connection, lock: asyncio.Lock):
        ...

    async def execute(self, sql: str, params=()) -> sqlite3.Cursor: ...
    async def fetch_one(self, sql: str, params=()) -> sqlite3.Row | None: ...
    async def fetch_all(self, sql: str, params=()) -> list[sqlite3.Row]: ...
```

Then `NodeStore`, `EventStore`, and `SubscriptionRegistry` all use this instead of each implementing the same pattern. This eliminates ~300 lines of boilerplate and centralizes connection management.

**Consider also**: Whether `aiosqlite` would be a better fit than hand-rolling async wrappers. It provides native async SQLite support and is mature.

#### R3. Introduce a formal domain service layer

Currently, `__main__.py` does all wiring, the runner owns the entire externals contract, and the reconciler imports from 6 modules. Introducing a service layer would make the architecture more testable and composable:

```
RuntimeServices:
    - node_service: NodeService (wraps NodeStore + status state machine)
    - event_service: EventService (wraps EventStore + EventBus)
    - workspace_service: CairnWorkspaceService (already exists)
    - discovery_service: DiscoveryService (wraps discovery + path resolution)
    - proposal_service: ProposalService (wraps proposal lifecycle)
```

This would eliminate the scattered path resolution duplication, centralize status transitions, and make the runner's externals a thin delegation layer.

#### R4. Redesign the externals contract

The 18-closure `_build_externals` method is the single worst code organization in the codebase. Options:

**Option A — Protocol-based tool backends:**
```python
class AgentToolBackend(Protocol):
    async def read_file(self, path: str) -> str: ...
    async def write_file(self, path: str, content: str) -> bool: ...
    async def propose_rewrite(self, new_source: str) -> str: ...
    # ... etc
```
A concrete implementation is created per-turn and passed to Grail tools.

**Option B — External registry with decorators:**
```python
class Externals:
    @external
    async def read_file(self, path: str) -> str:
        return await self.workspace.read(path)
```

**Option C — Move externals to individual modules:**
Each external function becomes its own file or class, registered in a discoverable way. This would enable per-tool-type configuration and testing.

Any of these would dramatically improve testability and readability versus the current nested-closure approach.

#### R5. Replace the proposal system with a dedicated model

Proposals are currently scraped from event history via `_find_proposal` (linear scan of last 1000 events). A proper proposal model would:

- Have its own SQLite table: `proposals (id, file_path, agent_id, base_hash, old_source, new_source, status, created_at)`
- Use span-based patching (start_byte/end_byte) instead of string replacement
- Validate base content hash before applying
- Support explicit lifecycle: `pending → approved → applied` or `pending → rejected`

This eliminates C2, C3, and M1 in one architectural change.

### Tier 2: Module-Level Improvements

#### R6. Introduce a node status state machine

```python
class NodeStatus(Enum):
    IDLE = "idle"
    RUNNING = "running"
    PENDING_APPROVAL = "pending_approval"
    ERROR = "error"

VALID_TRANSITIONS = {
    NodeStatus.IDLE: {NodeStatus.RUNNING},
    NodeStatus.RUNNING: {NodeStatus.IDLE, NodeStatus.PENDING_APPROVAL, NodeStatus.ERROR},
    NodeStatus.PENDING_APPROVAL: {NodeStatus.IDLE},
    NodeStatus.ERROR: {NodeStatus.IDLE},
}
```

The runner's `finally` block would check current status before transitioning:
```python
current = await self._node_store.get_status(node_id)
if current == NodeStatus.RUNNING:
    await self._node_store.set_status(node_id, NodeStatus.IDLE)
# Don't touch PENDING_APPROVAL
```

This fixes C1 and prevents any future status-related bugs.

#### R7. Centralize path resolution and file walking

Create a single utility:

```python
# code/paths.py
def resolve_discovery_paths(config: Config, project_root: Path) -> list[Path]: ...
def resolve_query_paths(config: Config, project_root: Path) -> list[Path]: ...
def walk_source_files(paths: list[Path], ignore_patterns: tuple[str, ...]) -> list[Path]: ...
```

Used by `__main__._discover`, `FileReconciler._iter_source_files`, and `discovery._walk_source_files`. The current duplication (three independent implementations of the same logic) is a maintenance hazard.

#### R8. Make discovery identity collision-safe

Options:
- **Append line number**: `file_path::full_name:L{start_line}` — simple, mostly unique
- **Append scope hash**: `file_path::full_name#{short_hash_of_parent_chain}` — robust but less readable
- **Collision detection**: On ID conflict, log a warning and append a disambiguator
- **UUID-based**: Use a deterministic UUID derived from (file_path, full_name, start_byte, end_byte)

The simplest correct approach: include `start_byte` in the ID to make it position-dependent.

#### R9. Add fault isolation to background loops

```python
async def run_forever(self, *, poll_interval_s: float = 1.0) -> None:
    self._running = True
    while self._running:
        try:
            await self.reconcile_cycle()
        except Exception:
            logger.exception("Reconcile cycle failed, will retry")
            # Optionally emit an error event
        await asyncio.sleep(poll_interval_s)
```

Same pattern for the runner's trigger consumption loop.

#### R10. Cache Grail tool scripts

```python
_tool_cache: dict[str, tuple[str, GrailScript]] = {}  # path → (content_hash, script)
```

Only re-parse when tool source content changes. This eliminates M3 and reduces temp directory churn.

### Tier 3: Code Quality & Cleanup

#### R11. Move the web UI to a proper static file

Extract `GRAPH_HTML` from `views.py` to a `static/index.html` file served by Starlette. This:
- Enables HTML/CSS/JS linting and formatting
- Allows use of web dev tools
- Reduces the Python source by ~290 lines

#### R12. Add `NodeRemovedEvent` and `NodeChangedEvent` handling to SSE

Add two more event listeners in the graph JS:
```javascript
evtSource.addEventListener("NodeRemovedEvent", (event) => {
    const data = JSON.parse(event.data);
    if (graph.hasNode(data.node_id)) {
        graph.dropNode(data.node_id);
        renderer.refresh();
    }
});
```

#### R13. Add a batch edges endpoint

Replace N+1 edge fetching with:
```
GET /api/edges → returns all edges
```

#### R14. Consolidate test helpers

Create a `tests/factories.py`:
```python
def make_node(node_id: str, **overrides) -> CodeNode: ...
def make_cst(file_path: str, name: str, **overrides) -> CSTNode: ...
def write_file(path: Path, text: str) -> None: ...
def write_bundles(root: Path) -> None: ...
```

Currently these helpers are independently defined in 6+ test files with slight variations.

#### R15. Use Literal/Enum types for stringly-typed fields

```python
NodeType = Literal["function", "class", "method", "section", "table"]
EdgeType = Literal["calls", "parent_of", "imports"]
ChangeType = Literal["modified", "created", "deleted", "opened"]
```

This provides IDE autocomplete, catches typos at construction time, and documents the valid value space.

#### R16. Remove dead code

- `utils/__init__.py` is an empty package with no contents and no usages
- `code/__init__.py` re-exports everything but these re-exports aren't used (callers import from specific modules)
- `Edge` dataclass is barely used — callers immediately destructure to dicts
- `caller_ids`/`callee_ids` on CodeNode are never populated by discovery or reconciliation (always empty lists for new nodes, preserved for existing)

#### R17. Make `_summarize` a method on Event

Instead of:
```python
@staticmethod
def _summarize(event: Event) -> str:
    if isinstance(event, AgentCompleteEvent | ToolResultEvent):
        return event.result_summary
    ...
```

Make it:
```python
class Event(BaseModel):
    def summary(self) -> str:
        return ""

class AgentCompleteEvent(Event):
    def summary(self) -> str:
        return self.result_summary
```

### Tier 4: 10,000-Foot Opportunities

These are larger strategic options that could fundamentally improve the architecture:

#### R18. Consider replacing SQLite with an in-memory store + WAL journal

The current architecture uses SQLite for three stores (nodes, events, subscriptions) accessed through a single connection with a single async lock. For a single-process runtime, an in-memory store with periodic disk snapshots might be simpler, faster, and eliminate the `to_thread` overhead entirely.

**Trade-off**: Loses crash-resume capability. Could be mitigated with periodic WAL-style journaling.

#### R19. Consider a plugin architecture for language support

Currently, adding a new language requires:
1. Adding a grammar dependency to `pyproject.toml`
2. Adding it to `_GRAMMAR_REGISTRY` in `discovery.py`
3. Adding a `.scm` query file
4. Adding logic to `_resolve_node_type`
5. Adding it to the default `language_map` in `config.py`

A plugin architecture would encapsulate all of this:
```python
class LanguagePlugin(Protocol):
    name: str
    extensions: list[str]
    def get_language(self) -> Language: ...
    def get_default_query(self) -> str: ...
    def resolve_node_type(self, node: Any) -> str: ...
```

Each language becomes a self-contained plugin, and new languages can be added without modifying any existing code.

#### R20. Consider making the reconciler event-driven rather than polling

The current reconciler polls at 1-second intervals. An alternative is to use filesystem watchers (e.g., `watchfiles` or `inotify`) to get immediate notification of changes. The LSP server already emits `ContentChangedEvent` on save — the reconciler could subscribe to these events AND use filesystem watching as a fallback.

**Trade-off**: More complex, platform-dependent. But eliminates the 1-second latency and reduces CPU usage for idle projects.

#### R21. Consider separating the "agent identity" from "code element"

Currently, `CodeNode` is both a code element (with source code, byte spans, file path) AND an agent (with status, bundle name, workspace). These are conceptually different:

- A **code element** has identity, location, and content
- An **agent** has status, tools, workspace, and execution history

Separating these would allow:
- Multiple agents per code element (e.g., a reviewer agent AND a refactorer agent for the same function)
- Agents that aren't tied to code elements (e.g., a project-level orchestrator)
- Code elements that don't need agents (e.g., trivial utility functions)

#### R22. Consider a proper event sourcing pattern

The EventStore already stores all events immutably. But the system doesn't fully leverage event sourcing — node state is maintained as a separate mutable store that can drift from the event log. A full event-sourcing approach would derive all state (nodes, edges, subscriptions, proposals) from the event stream, making the system:
- Fully replayable
- Self-consistent by construction
- Debuggable through event replay

**Trade-off**: Significant complexity increase. Event sourcing is powerful but requires careful projection management.

#### R23. Unify the storage layer

Currently there are three independent SQLite-backed stores (NodeStore, EventStore, SubscriptionRegistry) sharing a connection and lock. These could be unified behind a single `RemoraStore` or `Database` class that manages all tables, provides typed query methods, and owns the connection lifecycle.

This eliminates the awkward connection/lock passing in `__main__.py` and the `EventStore` dual-initialization problem.

---

## Summary: Priority Matrix

| Priority | Fix | Effort | Impact |
|----------|-----|--------|--------|
| **Now** | C1: Fix pending_approval clobber | Small | Critical correctness |
| **Now** | C2: Span-based rewrite patching | Medium | Critical correctness |
| **Now** | C3: Concurrency guard on approve | Small | Critical correctness |
| **Now** | H2: Reconciler fault isolation | Small | High reliability |
| **Soon** | R1: Split events.py | Medium | Architecture clarity |
| **Soon** | R2: Async SQLite layer | Medium | Code reduction |
| **Soon** | R4: Redesign externals | Large | Maintainability |
| **Soon** | R5: Proposal model | Medium | Correctness + UX |
| **Soon** | R6: Status state machine | Small | Correctness |
| **Soon** | R7: Centralize path resolution | Small | DRY |
| **Plan** | R3: Service layer | Large | Architecture |
| **Plan** | R8: Collision-safe IDs | Medium | Correctness |
| **Plan** | R19: Language plugins | Large | Extensibility |
| **Plan** | R21: Separate agent from code element | Large | Architecture |
| **Plan** | R23: Unified storage | Medium | Simplification |
