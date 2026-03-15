# Self-Generating Codebases — Implementation Proposal

## Table of Contents

1. [Decisions Summary](#1-decisions-summary)
2. [Architecture](#2-architecture)
3. [Config Schema](#3-config-schema)
4. [Implementation Plan](#4-implementation-plan)
5. [File-by-File Changes](#5-file-by-file-changes)
6. [Scaffold Execution Flow](#6-scaffold-execution-flow)
7. [Cycle & Conflict Handling](#7-cycle--conflict-handling)
8. [Example: End-to-End Walkthrough](#8-example-end-to-end-walkthrough)

---

## 1. Decisions Summary

| Question | Decision | Rationale |
|----------|----------|-----------|
| Integration model | **Option A**: extend existing + thin template registry | Minimal code (~200 lines), leverages existing reconciler/actor/event machinery |
| Ownership | **Transfer by default**, opt-in retention per output | Safe default prevents overwriting human edits; boilerplate and derived artifacts opt into retention |
| Section granularity | **Top-level tables**, with `[tool.*]` split to second level | Matches human mental model; maps to tree-sitter TOML captures cleanly |
| Self-modification | **Yes**, but `approval: propose` is mandatory | Enables opinionated convention enforcement; proposal flow is the cycle-breaker |
| Template definitions | **`remora.yaml`** for declarations, **bundle dir** for logic | Per-project config; Remora ships zero built-in templates |
| File matching | **Filename + optional path_glob** to start | Simple, fast (no content scanning), covers 90% of cases |
| Section extraction | **Tree-sitter queries** for boundaries, **Grail scripts** for content | Fast discovery, flexible generation |
| Conflict resolution | **Default: warn** (emit event, AWAITING_REVIEW); overridable to skip or marker-based | Human decides by default; templates can override for known-safe outputs |

---

## 2. Architecture

### How It Fits Into Remora

```
                          remora.yaml
                              |
                    ┌─────────┴──────────┐
                    │  TemplateRegistry   │  (new: ~30 lines in config.py)
                    │  - match rules      │
                    │  - scaffold specs   │
                    │  - bundle overrides │
                    └─────────┬──────────┘
                              │
                              ▼
┌──────────┐   file created   ┌──────────────┐
│ watchfiles├─────────────────►│ FileReconciler│  (modified: ~50 lines)
└──────────┘                  │              │
                              │ 1. discover()│
                              │ 2. match     │
                              │    template? │
                              │ 3. if yes:   │
                              │    run       │
                              │    scaffold  │
                              └──────┬───────┘
                                     │
                         ┌───────────┼────────────┐
                         ▼           ▼            ▼
                   Inward        Scaffold      Section
                   expansion     runner        bundle
                   (existing     (new:         override
                    discovery)    ~80 lines)   (existing
                                              bundle_rules)
                         │           │
                         ▼           ▼
                   Section nodes   Files written
                   get actors      → ContentChangedEvent
                   + bundles       → reconciler picks up
                                   → cascading
```

### Key Principle: No New Node Types

Template files produce regular `table`/`section` nodes via existing discovery. Template *behavior* is driven by bundle assignment and scaffold scripts. The reconciler gains a small hook: "after discovering this file, check if it matches a template and run scaffolds if needed."

---

## 3. Config Schema

### New Pydantic Models (in `config.py`)

```python
class ScaffoldOutputConfig(BaseModel):
    """One output declaration from a scaffold script."""
    path: str                              # glob or explicit path
    ownership: str = "transferred"         # "transferred" | "retained"

class ScaffoldConfig(BaseModel):
    """A scaffold script to run when a template triggers."""
    script: str                            # path to .pym relative to bundle_root
    trigger: str = "on_create"             # "on_create" | "on_change" | "on_manual"
    approval: str = "propose"             # "auto" | "propose" | "confirm"
    modifies_source: bool = False          # true = script edits the seed file itself
    outputs: tuple[ScaffoldOutputConfig, ...] = ()

    @field_validator("approval")
    @classmethod
    def _validate_self_mod_approval(cls, v, info):
        """Enforce: modifies_source requires approval=propose."""
        if info.data.get("modifies_source") and v == "auto":
            raise ValueError("modifies_source=true requires approval='propose' or 'confirm'")
        return v

class TemplateMatchConfig(BaseModel):
    """File matching rule for a template."""
    filename: str | None = None            # exact filename match
    path_glob: str | None = None           # fnmatch-style path glob

class TemplateBundleRuleConfig(BaseModel):
    """Per-template bundle override for discovered sections."""
    node_type: str
    name_pattern: str | None = None
    bundle: str

class TemplateConfig(BaseModel):
    """A template declaration: match rule + section bundles + scaffold scripts."""
    name: str
    match: TemplateMatchConfig
    bundle: str | None = None              # default bundle for the file-level node
    bundle_rules: tuple[TemplateBundleRuleConfig, ...] = ()
    scaffold: tuple[ScaffoldConfig, ...] = ()
    section_granularity: str = "table"     # "table" | "depth-2" | "top-level"
```

### In the top-level `Config` class

```python
class Config(BaseSettings):
    # ... existing fields ...
    templates: tuple[TemplateConfig, ...] = ()
```

### Example `remora.yaml`

```yaml
templates:
  - name: python-project
    match:
      filename: "pyproject.toml"
    bundle: "pyproject-agent"
    bundle_rules:
      - node_type: "table"
        name_pattern: "project"
        bundle: "project-meta-agent"
      - node_type: "table"
        name_pattern: "tool.*"
        bundle: "tool-config-agent"
      - node_type: "table"
        name_pattern: "build-system"
        bundle: "build-config-agent"
    scaffold:
      - script: "generators/python-layout.pym"
        trigger: "on_create"
        approval: auto
        outputs:
          - { path: "src/*/__init__.py", ownership: retained }
          - { path: "tests/__init__.py", ownership: retained }
          - { path: "tests/conftest.py", ownership: transferred }
      - script: "generators/enforce-ruff.pym"
        trigger: "on_create"
        approval: propose
        modifies_source: true

  - name: devenv-config
    match:
      filename: "devenv.nix"
    bundle: "devenv-agent"
    scaffold:
      - script: "generators/devenv-envrc.pym"
        trigger: "on_create"
        approval: auto
        outputs:
          - { path: ".envrc", ownership: retained }

  - name: openapi-spec
    match:
      path_glob: "**/openapi.{yaml,yml}"
    bundle: "api-spec-agent"
    scaffold:
      - script: "generators/api-routes.pym"
        trigger: "on_create"
        approval: propose
      - script: "generators/api-models.pym"
        trigger: "on_change"
        approval: propose
```

---

## 4. Implementation Plan

### Phase 1: Config + Template Matching (~30 lines)

Add `TemplateConfig` and related models to `config.py`. Add `templates` field to `Config`. Add a `match_template(file_path: str) -> TemplateConfig | None` method to `Config` that checks filename/path_glob against all templates.

```python
def match_template(self, file_path: str) -> TemplateConfig | None:
    """Return the first matching template for a file path, or None."""
    name = Path(file_path).name
    for template in self.templates:
        m = template.match
        if m.filename and m.filename == name:
            return template
        if m.path_glob and fnmatch(file_path, m.path_glob):
            return template
    return None
```

### Phase 2: Reconciler Hook (~50 lines)

Modify `FileReconciler._do_reconcile_file` to check for template matches after discovery. When matched:

1. Apply the template's `bundle_rules` as overrides during projection (these merge with the global `bundle_rules` — template rules take priority)
2. Check if scaffolds should fire (based on trigger type and whether the file is new vs changed)
3. Hand off to the scaffold runner

```python
async def _do_reconcile_file(self, file_path, mtime_ns, *, sync_existing_bundles=False):
    # ... existing discovery + projection code ...

    template = self._config.match_template(file_path)
    if template is not None:
        is_new_file = file_path not in self._file_state
        await self._run_template_scaffolds(
            template, file_path, is_new_file, projected,
        )

    # ... rest of existing method ...
```

### Phase 3: Scaffold Runner (~80 lines)

New module `core/scaffold.py` (or method group on `FileReconciler`):

```python
class ScaffoldRunner:
    """Executes scaffold .pym scripts with template context."""

    def __init__(
        self,
        config: Config,
        workspace_service: CairnWorkspaceService,
        event_store: EventStore,
        project_root: Path,
    ):
        self._config = config
        self._workspace_service = workspace_service
        self._event_store = event_store
        self._project_root = project_root

    async def run_scaffolds(
        self,
        template: TemplateConfig,
        seed_file_path: str,
        is_new_file: bool,
        seed_node_id: str,
    ) -> None:
        """Run matching scaffold scripts for a template trigger."""
        for scaffold in template.scaffold:
            if not self._should_run(scaffold, is_new_file):
                continue
            if await self._already_ran(seed_node_id, scaffold):
                continue
            await self._execute_scaffold(scaffold, seed_file_path, seed_node_id)

    def _should_run(self, scaffold: ScaffoldConfig, is_new: bool) -> bool:
        if scaffold.trigger == "on_create" and not is_new:
            return False
        if scaffold.trigger == "on_manual":
            return False  # only triggered by explicit user action
        return True

    async def _already_ran(self, node_id: str, scaffold: ScaffoldConfig) -> bool:
        """Check KV for previous execution (idempotency)."""
        workspace = await self._workspace_service.get_agent_workspace(node_id)
        key = f"_scaffold/{scaffold.script}"
        return await workspace.kv_get(key) is not None

    async def _execute_scaffold(
        self, scaffold: ScaffoldConfig, seed_file_path: str, seed_node_id: str,
    ) -> None:
        workspace = await self._workspace_service.get_agent_workspace(seed_node_id)
        seed_content = Path(seed_file_path).read_text(encoding="utf-8")

        # Load and run the Grail script
        script_path = Path(self._config.bundle_root) / scaffold.script
        source = script_path.read_text(encoding="utf-8")
        script = _load_script_from_source(source, script_path.stem)

        capabilities = {
            "write_file": workspace.write,
            "read_file": workspace.read,
            "file_exists": workspace.exists,
            "list_dir": workspace.list_dir,
        }

        result = await script.run(
            inputs={
                "source_content": seed_content,
                "project_root": str(self._project_root),
                "seed_file": seed_file_path,
            },
            externals={
                name: fn for name, fn in capabilities.items()
                if name in script.externals
            },
        )

        if scaffold.approval == "auto":
            await self._materialize_auto(workspace, seed_node_id, scaffold)
        elif scaffold.approval == "propose":
            await self._emit_proposal(workspace, seed_node_id, scaffold)

        # Record execution for idempotency
        await workspace.kv_set(f"_scaffold/{scaffold.script}", {
            "ran_at": time.time(),
            "seed_hash": hashlib.sha256(seed_content.encode()).hexdigest(),
        })
```

### Phase 4: Template State Tracking (~40 lines)

Track what's been generated using the existing workspace KV store:

- `_scaffold/<script-name>` → `{ ran_at, seed_hash }` — prevents re-running on restart
- `_scaffold/<script-name>/outputs` → list of generated file paths — for ownership tracking
- `_scaffold/<script-name>/output_hashes` → content hashes at generation time — for conflict detection

When `ownership: retained` and the seed file changes:
1. Read stored `seed_hash`, compare to current
2. If changed, re-run the scaffold
3. Before overwriting, check if output file hash matches stored hash (no manual edits)
4. If manual edits detected, fall back to `approval: propose` regardless of config

---

## 5. File-by-File Changes

| File | Change | Lines |
|------|--------|-------|
| `core/config.py` | Add `TemplateConfig`, `ScaffoldConfig`, `TemplateMatchConfig`, `TemplateBundleRuleConfig`, `ScaffoldOutputConfig` models. Add `templates` field to `Config`. Add `match_template()` method. | ~60 |
| `code/reconciler.py` | Add template check in `_do_reconcile_file`. Merge template `bundle_rules` with global rules during projection. Call scaffold runner. | ~30 |
| `core/scaffold.py` | **New file**. `ScaffoldRunner` class with `run_scaffolds`, `_should_run`, `_already_ran`, `_execute_scaffold`, `_materialize_auto`, `_emit_proposal`. | ~120 |
| `core/services.py` | Instantiate `ScaffoldRunner` and pass to `FileReconciler`. | ~5 |
| **Total** | | **~215** |

No changes to: `types.py`, `node.py`, `events/`, `actor.py`, `runner.py`, `graph.py`, `kernel.py`, `externals.py`, `grail.py`, `web/`, `lsp/`, `discovery.py`, `languages.py`, `paths.py`, `projections.py`.

---

## 6. Scaffold Execution Flow

### 6.1 `approval: auto` (Structural Scaffolding)

```
User creates pyproject.toml
  → watchfiles detects change
  → reconciler._do_reconcile_file("pyproject.toml")
  → discover() → CSTNodes for each table
  → config.match_template("pyproject.toml") → TemplateConfig
  → scaffold_runner.run_scaffolds(template, ...)
    → generators/python-layout.pym runs
    → writes src/pkg/__init__.py to workspace
    → _materialize_auto():
        → reads workspace outputs
        → writes directly to disk (no proposal)
        → emits ContentChangedEvent per file
  → reconciler picks up ContentChangedEvent
  → discovers new .py files as regular nodes
  → normal agent lifecycle begins
```

### 6.2 `approval: propose` (Code Generation)

```
User creates openapi.yaml
  → reconciler discovers it, matches api-spec template
  → scaffold_runner runs generators/api-routes.pym
    → writes route stubs to workspace
    → _emit_proposal():
        → emits RewriteProposalEvent
        → node transitions to AWAITING_REVIEW
  → Web UI shows proposal with diffs
  → Human clicks "Accept"
    → api_proposal_accept writes files to disk
    → emits ContentChangedEvent per file
  → reconciler picks up new files
  → Python discovery creates function nodes
  → code-agent bundles assigned, agents start
```

### 6.3 `modifies_source: true` (Self-Modification)

```
User creates pyproject.toml with [project] only
  → reconciler discovers it, matches python-project template
  → scaffold_runner runs generators/enforce-ruff.pym
    → script detects [tool.ruff] is missing
    → writes modified pyproject.toml to workspace (with [tool.ruff] added)
    → _emit_proposal() (mandatory for modifies_source)
  → Human reviews: "Add [tool.ruff] with org defaults?"
  → Human clicks "Accept"
    → pyproject.toml is updated on disk
    → ContentChangedEvent emitted
  → reconciler re-runs for pyproject.toml
    → discovers new [tool.ruff] table node
    → config.match_template() matches again
    → scaffold_runner checks _already_ran() for enforce-ruff.pym
      → seed_hash matches current content? No — content changed
      → BUT: the scaffold is modifies_source=true and same correlation_id
      → scaffold checks: did MY output cause this change? Yes
      → skip re-run (cycle prevented)
    → [tool.ruff] node gets tool-config-agent bundle
    → normal agent lifecycle
```

---

## 7. Cycle & Conflict Handling

### 7.1 Cycle Prevention

Three layers of protection, all using existing Remora mechanisms:

| Layer | Mechanism | Handles |
|-------|-----------|---------|
| **Idempotency** | KV-stored `seed_hash` — skip if seed hasn't changed | Same file re-reconciled without edits |
| **Correlation tracking** | `modifies_source` scaffolds emit events with same correlation_id → actor depth limits apply | Self-modification cycles |
| **Seen set** | `_already_ran()` checks KV per scaffold per node | Restart/re-reconciliation re-triggering |

### 7.2 Conflict Detection for Retained Outputs

When `ownership: retained` and the scaffold re-runs:

```python
async def _check_conflict(self, disk_path: Path, scaffold: ScaffoldConfig) -> str:
    """Returns 'clean', 'modified', or 'missing'."""
    if not disk_path.exists():
        return "missing"
    current_hash = hashlib.sha256(disk_path.read_bytes()).hexdigest()
    stored_hash = await workspace.kv_get(f"_scaffold/{scaffold.script}/hash/{disk_path}")
    if stored_hash is None:
        return "modified"  # we didn't generate this — someone else created it
    if current_hash != stored_hash:
        return "modified"  # human edited since last generation
    return "clean"         # untouched since we generated it
```

| Conflict state | `ownership: retained` behavior |
|---------------|-------------------------------|
| `clean` | Overwrite silently (or per approval mode) |
| `modified` | Force `approval: propose` regardless of config |
| `missing` | Generate normally |

### 7.3 Cascade Depth

Template cascading (file A generates file B which matches template C) is bounded by the existing `max_trigger_depth` config. Each `ContentChangedEvent` emitted by scaffold materialization carries the originating correlation_id. Actors receiving these events check depth before triggering.

Default `max_trigger_depth: 5` is generous. In practice, cascades rarely go deeper than 2 (pyproject → src/pkg/__init__.py → python discovery).

---

## 8. Example: End-to-End Walkthrough

### Starting State

Empty directory. User writes one file:

**`remora.yaml`**:
```yaml
discovery_paths: ["src/", "."]
language_map:
  ".py": "python"
  ".toml": "toml"
bundle_root: "bundles"

templates:
  - name: python-project
    match:
      filename: "pyproject.toml"
    bundle_rules:
      - { node_type: "table", name_pattern: "project", bundle: "project-meta-agent" }
      - { node_type: "table", name_pattern: "tool.*", bundle: "tool-config-agent" }
    scaffold:
      - script: "generators/python-layout.pym"
        trigger: "on_create"
        approval: auto
        outputs:
          - { path: "src/*/__init__.py", ownership: retained }
          - { path: "tests/__init__.py", ownership: retained }
          - { path: "tests/conftest.py", ownership: transferred }
      - script: "generators/enforce-conventions.pym"
        trigger: "on_create"
        approval: propose
        modifies_source: true
```

**`bundles/generators/python-layout.pym`**:
```python
# Generate Python project layout from pyproject.toml
input source_content: str
external write_file

import tomllib

config = tomllib.loads(source_content)
name = config.get("project", {}).get("name", "myproject")

await write_file(f"source/src/{name}/__init__.py", f'"""{name} package."""\n')
await write_file("source/tests/__init__.py", "")
await write_file("source/tests/conftest.py", '"""Shared pytest fixtures."""\n')

result = f"Created layout for {name}"
result
```

### User Action

User creates **`pyproject.toml`**:
```toml
[project]
name = "acme"
version = "0.1.0"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

### What Happens

```
t=0  watchfiles: pyproject.toml created
t=1  reconciler._do_reconcile_file("pyproject.toml")
t=2    discover() via TomlPlugin → CSTNodes:
         - pyproject.toml::project    (table)
         - pyproject.toml::build-system (table)
t=3    project_nodes() → Nodes upserted to DB
         - pyproject.toml::project     → bundle: project-meta-agent
         - pyproject.toml::build-system → bundle: (default)
t=4    config.match_template("pyproject.toml") → python-project template
t=5    scaffold_runner.run_scaffolds():
         - python-layout.pym: trigger=on_create, is_new=true → RUN
           - reads pyproject.toml, extracts name="acme"
           - writes src/acme/__init__.py to workspace
           - writes tests/__init__.py to workspace
           - writes tests/conftest.py to workspace
           - approval=auto → materialize directly to disk
           - emits ContentChangedEvent for each file
         - enforce-conventions.pym: trigger=on_create, is_new=true → RUN
           - detects [tool.ruff] missing
           - writes modified pyproject.toml to workspace
           - approval=propose → emits RewriteProposalEvent
           - node → AWAITING_REVIEW
t=6  reconciler picks up ContentChangedEvent for src/acme/__init__.py
t=7    discover() via PythonPlugin → (empty file, no functions/classes yet)
t=8  Web UI shows proposal: "Add [tool.ruff] section to pyproject.toml"
t=9  User clicks Accept
t=10   pyproject.toml updated on disk with [tool.ruff] section
t=11   ContentChangedEvent for pyproject.toml
t=12 reconciler re-runs for pyproject.toml
t=13   discover() → now finds 3 tables: project, build-system, tool.ruff
t=14   new node: pyproject.toml::tool.ruff → bundle: tool-config-agent
t=15   template match → scaffold_runner:
         - python-layout.pym: _already_ran() → true, seed changed but
           this scaffold's outputs are on disk → skip
         - enforce-conventions.pym: _already_ran() with matching correlation → skip
t=16 NodeDiscoveredEvent for pyproject.toml::tool.ruff
t=17 tool-config-agent actor starts for [tool.ruff] node
```

### Resulting Project Structure

```
.
├── pyproject.toml          (user-created, then template-enriched)
├── remora.yaml             (user-created)
├── bundles/
│   └── generators/
│       ├── python-layout.pym
│       └── enforce-conventions.pym
├── src/
│   └── acme/
│       └── __init__.py     (auto-generated, ownership: retained)
└── tests/
    ├── __init__.py          (auto-generated, ownership: retained)
    └── conftest.py          (auto-generated, ownership: transferred → human-owned)
```

### Node Graph

```
.                           (directory node)
├── pyproject.toml::project         (table, project-meta-agent)
├── pyproject.toml::build-system    (table, default bundle)
├── pyproject.toml::tool.ruff       (table, tool-config-agent)
├── src                     (directory node)
│   └── src/acme            (directory node)
└── tests                   (directory node)
```

The user wrote 2 files (`remora.yaml` + `pyproject.toml`). The system generated 3 files, enriched the pyproject with conventions, created 7 nodes, and assigned 3 specialized agent bundles — all through existing Remora machinery with ~215 lines of new code.
