# Plan: Initial Refactor

## NO SUBAGENTS — Do all work directly.

---

## Overview

Replace the ast-based Python-only discovery with tree-sitter multi-language discovery, implement a unified `FileReconciler`, fix all critical/high bugs from the code review, and clean up dead code.

## Dependencies (must install first)

Add to `pyproject.toml` `[project.dependencies]`:
- `tree-sitter-python>=0.25`
- `tree-sitter-markdown>=0.5`
- `tree-sitter-toml>=0.7`

Remove `tree-sitter>=0.24` — it's pulled in transitively by the grammar packages.

## File Changes Summary

| File | Action |
|------|--------|
| `pyproject.toml` | Update deps, fix version |
| `src/remora/__init__.py` | Fix version to match pyproject |
| `src/remora/core/config.py` | Add `language_map` config field, add `query_paths` field |
| `src/remora/core/events.py` | Add `NodeRemovedEvent` |
| `src/remora/core/node.py` | Add `node_type` validation via Literal (nice-to-have) |
| `src/remora/core/runner.py` | Fix `event_emit` payload, fix `_read_bundle_config`, fix `_workspace_file_paths` encapsulation |
| `src/remora/core/workspace.py` | Add `list_all_paths()` method |
| `src/remora/code/discovery.py` | **Full rewrite** — tree-sitter based |
| `src/remora/code/queries/python.scm` | **New** — default Python query |
| `src/remora/code/queries/markdown.scm` | **New** — default Markdown query |
| `src/remora/code/queries/toml.scm` | **New** — default TOML query |
| `src/remora/code/reconciler.py` | **Full rewrite** — `FileReconciler` class |
| `src/remora/code/projections.py` | Minor update for stale node handling |
| `src/remora/code/__init__.py` | Update exports |
| `src/remora/__main__.py` | Wire in `FileReconciler`, remove duplicated path logic |
| `src/remora/web/views.py` | Fix XSS |
| `src/remora/web/server.py` | Fix approve endpoint, remove unused `runner` param |
| `src/remora/lsp/server.py` | Remove unused `runner` param |
| Tests | Update all discovery/reconciler tests, add tree-sitter tests |

---

## Step-by-Step Implementation

### Phase 1: Foundation Changes (no behavior change)

#### Step 1.1: Fix version mismatch
- `pyproject.toml`: set `version = "0.5.0"`
- `__init__.py`: already says `"0.5.0"` — no change needed
- Verify: `grep -r "version" pyproject.toml src/remora/__init__.py`

#### Step 1.2: Update dependencies in pyproject.toml
- Add `tree-sitter-python>=0.25`, `tree-sitter-markdown>=0.5`, `tree-sitter-toml>=0.7` to `[project.dependencies]`
- Remove standalone `tree-sitter>=0.24` (transitive dep)
- Run `devenv shell -- uv sync --extra dev`

#### Step 1.3: Add `NodeRemovedEvent` to events.py
- New event class with `node_id`, `node_type`, `file_path`, `name` fields (mirrors `NodeDiscoveredEvent`)
- Add to `__all__`
- Test: unit test for instantiation and serialization

#### Step 1.4: Add `language_map` and `query_paths` to Config
- `language_map`: `dict[str, str]` — maps file extension to tree-sitter language name
  - Default: `{".py": "python", ".md": "markdown", ".toml": "toml"}`
- `query_paths`: `tuple[str, ...]` — additional directories to search for `.scm` query overrides
  - Default: `("queries/",)` (project-relative)
- Test: config loads with defaults, YAML override works

#### Step 1.5: Fix standalone bugs

**1.5a: Fix `event_emit` payload discard** (`runner.py:268-271`)
- Current: `del payload; event = Event(event_type=event_type, correlation_id=correlation_id)`
- Fix: Create event with payload data. Since `Event` is a base model, we need to handle arbitrary payload. Best approach: add a `payload` field to the base `Event` model as `dict[str, Any] | None = None`, or create the event with the type string and attach payload to the correlation context.
- Simplest correct fix: Keep `Event` base clean. Create a `CustomEvent(Event)` subclass with a `payload: dict[str, Any]` field. The `event_emit` external creates `CustomEvent(event_type=event_type, payload=payload, correlation_id=correlation_id)`.
- Test: emit an event via the external and verify the payload is in the stored event.

**1.5b: Fix `_read_bundle_config` missing FsdFileNotFoundError** (`runner.py:377-381`)
- Add `FsdFileNotFoundError` to the except clause
- Test: already covered implicitly by existing runner tests

**1.5c: Fix XSS in web UI** (`views.py`)
- Change `<pre>${node.source_code}</pre>` to use `textContent`:
  ```javascript
  const pre = document.createElement('pre');
  pre.textContent = node.source_code;
  ```
- Or escape HTML entities before interpolation.
- Test: verify GRAPH_HTML doesn't use innerHTML for user content

**1.5d: Fix `_workspace_file_paths` encapsulation** (`runner.py:383-412`)
- Add `async def list_all_paths(self) -> list[str]` to `AgentWorkspace`
- Move the `ViewQuery` logic from runner into `AgentWorkspace`
- Update runner to call `workspace.list_all_paths()` instead of accessing private attrs
- Test: unit test for `list_all_paths()`

**1.5e: Fix approve endpoint file truncation risk** (`server.py:120`)
- The `propose_rewrite` external in `runner.py:317-333` stores `node.source_code` as `old_source` and the agent-provided `new_source`. The approve endpoint writes `new_source` as the entire file.
- Fix: Change `propose_rewrite` to read the full file, perform the replacement (old_source → new_source within the file), and store the complete file content as `new_source` in the event. This way, approval always writes a complete, correct file.
- Test: e2e test with a multi-function file verifying approval preserves other functions

### Phase 2: Tree-sitter Discovery (core rewrite)

#### Step 2.1: Write default .scm query files

**`src/remora/code/queries/python.scm`:**
```scheme
; Top-level and nested function definitions
(function_definition
  name: (identifier) @node.name) @node

; Class definitions
(class_definition
  name: (identifier) @node.name) @node

; Decorated definitions (same captures, matches decorated variants)
(decorated_definition
  definition: (function_definition
    name: (identifier) @node.name)) @node

(decorated_definition
  definition: (class_definition
    name: (identifier) @node.name)) @node
```

**`src/remora/code/queries/markdown.scm`:**
```scheme
; Sections (hierarchical by heading depth)
(section
  (atx_heading
    (inline) @node.name)) @node
```

**`src/remora/code/queries/toml.scm`:**
```scheme
; Tables with bare keys
(table
  (bare_key) @node.name) @node

; Tables with dotted keys
(table
  (dotted_key) @node.name) @node
```

Test: each query file loads without error against its language.

#### Step 2.2: Rewrite `discovery.py`

The new module needs:

**Language registry** (module-level):
```python
_GRAMMAR_REGISTRY: dict[str, tuple[ModuleType, Callable]] = {
    "python": (tree_sitter_python, tree_sitter_python.language),
    "markdown": (tree_sitter_markdown, tree_sitter_markdown.language),
    "toml": (tree_sitter_toml, tree_sitter_toml.language),
}
```

**`_get_language(name: str) -> Language`** — cached Language creation from grammar module.

**`_get_parser(language: str) -> Parser`** — cached Parser creation.

**`_load_query(language: str, query_paths: list[Path]) -> Query`** — loads `.scm` file with override precedence:
1. Check user `query_paths` (project-relative) for `{language}.scm`
2. Fall back to package default `src/remora/code/queries/{language}.scm`
3. Error if no query found

**`_build_name_from_tree(node: tree_sitter.Node, name_node: tree_sitter.Node) -> str`** — walks up the tree-sitter syntax tree from the matched node to build a hierarchical name:
- For each ancestor that is also a captured `@node`, prepend its `@node.name` text
- Join with `.`
- e.g., `class_definition` > `function_definition` → `"MyClass.method"`
- For markdown: `section` > `section` → `"Top Heading.Installation"`
- For TOML: tables are flat (no nesting in tree) → just use the key text `"tool.ruff.lint"`

**Implementation approach**: Since tree-sitter queries return flat capture lists, we need to post-process to establish hierarchy. Strategy:
1. Run the query on the file, collect all `(node, name)` pairs from matches
2. Sort by byte offset
3. For each captured node, walk up the tree to find the closest ancestor that is also a captured node → that's the parent
4. Build `full_name` by joining parent chain names with `.`
5. Build `node_id` as `f"{file_path}::{full_name}"`

**`discover(paths, *, language_map, query_paths, ignore_patterns) -> list[CSTNode]`** — main entry point:
- Walk files using `_walk_source_files` (keep existing, works fine)
- For each file, look up language from `language_map` (by extension)
- Parse with tree-sitter, run query, build CSTNodes
- `CSTNode` model unchanged — already has all needed fields

**`_parse_file(path, language, query_paths) -> list[CSTNode]`** — parse one file:
- Read file bytes
- Parse with tree-sitter
- Run query with QueryCursor.matches()
- For each match, extract `@node` and `@node.name` captures
- Build hierarchy via ancestor walk
- Construct CSTNode with proper byte offsets from tree-sitter (start_byte, end_byte, start_point, end_point)

**Remove**: `_parse_python`, `_line_start_offsets`, `_col_to_bytes`, `_build_node`, ast import — all replaced by tree-sitter.

**Keep**: `_walk_source_files` (file walking is language-independent), `CSTNode` model.

**Update `_detect_language`**: Use `language_map` dict instead of hardcoded `_EXT_TO_LANGUAGE`.

Tests:
- Python: function, class, method, async function, decorated definitions
- Markdown: h1, h2, h3 sections with hierarchical names
- TOML: bare key tables, dotted key tables
- Ignore patterns still work
- Multiple files, empty dirs
- CSTNode still frozen
- Custom query override from user path
- Language not in registry → skip file gracefully

#### Step 2.3: Update `__main__.py` discovery path

- Remove duplicated discovery path construction (extract to a config method or standalone function)
- Update `_discover` to pass `language_map` and `query_paths` from config
- Test: CLI discover command still works

### Phase 3: FileReconciler (reconciler rewrite)

#### Step 3.1: Implement `FileReconciler` class

```python
class FileReconciler:
    def __init__(
        self,
        config: Config,
        node_store: NodeStore,
        event_store: EventStore,
        workspace_service: CairnWorkspaceService,
        project_root: Path,
    ):
        self._config = config
        self._node_store = node_store
        self._event_store = event_store
        self._workspace_service = workspace_service
        self._project_root = project_root
        self._file_state: dict[str, tuple[int, set[str]]] = {}
        # key: file_path (str), value: (mtime_ns, set of node_ids)
        self._running = False
```

**`async def full_scan(self) -> list[CodeNode]`**:
- Called on startup (empty `_file_state` → everything is "new")
- Same logic as `reconcile_cycle` but processes all files

**`async def reconcile_cycle(self) -> None`**:
1. Walk source files, compare mtimes
2. Classify: UNCHANGED / MODIFIED / NEW / DELETED
3. For MODIFIED + NEW files:
   - Run tree-sitter discovery on just those files
   - Get existing node_ids for those files from `_file_state`
   - Diff: new_ids - old_ids = additions, old_ids - new_ids = removals, intersection = potential updates
   - For additions: project_nodes → register subscriptions → emit NodeDiscoveredEvent
   - For updates: check hash → if changed, re-project → emit NodeChangedEvent
   - For removals: unsubscribe → delete from NodeStore → emit NodeRemovedEvent
   - Update `_file_state` for those files
4. For DELETED files:
   - Unsubscribe all nodes
   - Delete all nodes from NodeStore
   - Emit NodeRemovedEvent for each
   - Remove from `_file_state`

**`async def run_forever(self, *, poll_interval_s: float = 1.0) -> None`**:
- Loop: `reconcile_cycle()`, then `await asyncio.sleep(poll_interval_s)`
- Respects `self._running` flag

**`def stop(self) -> None`**: Set `self._running = False`

**Subscription management**:
- `_register_subscriptions(node: CodeNode)`: Register `to_agent` and `ContentChangedEvent` subscriptions
- `_unregister_subscriptions(node_id: str)`: Delete subscriptions by agent_id (add a `delete_by_agent` method to `SubscriptionRegistry`)
- Check before registering to avoid duplicates

**`SubscriptionRegistry` change**: Add `async def unregister_by_agent(self, agent_id: str) -> int` — deletes all subscriptions for an agent, returns count deleted, invalidates cache.

Tests:
- Full scan discovers nodes, registers subscriptions, emits events
- Modified file triggers re-parse of only that file
- New file detected and nodes created
- Deleted file removes nodes and subscriptions
- Unchanged files skipped
- Subscription idempotency (re-scan doesn't duplicate)
- NodeRemovedEvent emitted on deletion

#### Step 3.2: Wire FileReconciler into `__main__.py`

- Replace `reconcile_on_startup(...)` with `reconciler = FileReconciler(...); await reconciler.full_scan()`
- Launch `reconciler.run_forever()` as an asyncio task alongside runner and web server
- Clean up on shutdown: `reconciler.stop()`
- Remove old `reconcile_on_startup` and `watch_and_reconcile` functions

#### Step 3.3: Handle ContentChangedEvent from LSP

- The LSP `did_save` emits `ContentChangedEvent`
- FileReconciler can subscribe to this event via EventBus and trigger immediate reconciliation for that file
- OR: simpler — just let the polling pick it up within 1s. The LSP event still triggers existing agents via subscriptions.
- Decision: Start with polling only. Add event-driven reconciliation as a future optimization.

### Phase 4: Cleanup & Final Integration

#### Step 4.1: Remove dead code
- Remove `_parse_python`, `_line_start_offsets`, `_col_to_bytes`, `_build_node` from discovery.py
- Remove `_EXT_TO_LANGUAGE` hardcoded dict
- Remove `import ast` from discovery.py
- Remove old `reconcile_on_startup` and `watch_and_reconcile` from reconciler.py
- Remove `_get_parser` (old stub that returns None) and `_get_query` (old stub)
- Clean up `__all__` exports — remove private functions

#### Step 4.2: Update all tests
- Update discovery tests for tree-sitter behavior
- Update reconciler tests for FileReconciler API
- Update projection tests (if interface changed)
- Update e2e tests
- Add new tests for markdown and TOML discovery
- Add test for query override mechanism
- Add test for NodeRemovedEvent in reconciler
- Remove/update any tests that depend on ast-specific behavior

#### Step 4.3: Run full test suite
```bash
devenv shell -- python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q
```
- Fix any failures
- Verify performance tests still pass

#### Step 4.4: Update README and config example
- Update `remora.yaml.example` with `language_map` and `query_paths` fields
- README.md: update to reflect tree-sitter multi-language support

---

## Acceptance Criteria

1. `remora discover` on a project with `.py`, `.md`, and `.toml` files discovers nodes from all three
2. Python discovery produces the same nodes as before (functions, classes, methods) with correct byte spans
3. Markdown discovery produces hierarchical section nodes (e.g., `README.md::Installation.From Source`)
4. TOML discovery produces table nodes (e.g., `pyproject.toml::tool.ruff.lint`)
5. Custom `.scm` query files in project `queries/` directory override defaults
6. FileReconciler runs at startup and continuously, detecting additions/changes/deletions
7. Stale nodes are cleaned up (NodeRemovedEvent emitted)
8. No subscription accumulation on re-reconciliation
9. All bugs from code review (1-6) are fixed
10. All existing tests pass (updated as needed)
11. New tests for all new functionality

## NO SUBAGENTS — Do all work directly.
