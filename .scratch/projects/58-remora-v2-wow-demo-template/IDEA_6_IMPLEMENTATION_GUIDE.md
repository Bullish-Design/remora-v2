# IDEA 6 Implementation Guide — Two-Repo Plan (`remora-v2` + `remora-test`)

## Table of Contents
1. Goal and Repo Boundaries
Description: Define what Idea #6 delivers and how responsibilities split across the library repo and the demo repo.

2. Execution Strategy and Branch Model
Description: Set a safe implementation order so `remora-test` always points to a known-good `remora-v2` revision.

3. Workstream A — `remora-v2` Changes
Description: Required runtime/library checks and conditional implementation tasks needed to guarantee immediate semantic edge availability.

4. Workstream B — `remora-test` Changes
Description: Required demo assets (scripts, configs, cue sheet, tests) that operationalize Idea #6 in the demo repo.

5. End-to-End Rehearsal Flow
Description: Exact command sequence to run the Click clone -> boot -> evidence flow from `remora-test`.

6. Acceptance Criteria
Description: Repo-specific ship gates for both `remora-v2` and `remora-test`.

7. Intern Handoff Format
Description: Required output for review, including commands run and evidence artifacts.

## 1) Goal and Repo Boundaries

### Demo Goal
Deliver a reliable live demo that does this in one flow:
1. Clones `pallets/click`.
2. Starts Remora against that clone.
3. Shows API-backed graph evidence immediately after startup.
4. Extracts semantic hotspots from `imports`/`inherits` edges.

### Repo Responsibility Split

`remora-v2` (`/home/andrew/Documents/Projects/remora-v2`):
- Owns runtime correctness.
- Owns graph relationship completeness behavior.
- Owns API behavior (`/api/health`, `/api/nodes`, `/api/edges`, `/api/events`, `/sse`).
- Owns tests that guarantee semantic edge reliability.

`remora-test` (`/home/andrew/Documents/Projects/remora-test`):
- Owns demo packaging and operator UX.
- Owns scripts/config/templates for the Click boot demo.
- Owns presenter cue sheet and runbook.
- Owns contract tests that ensure demo assets are present and executable.

### Important Constraint
Do not put Idea #6 demo scaffolding scripts inside `remora-v2` product code. Keep demo automation in `remora-test`.

## 2) Execution Strategy and Branch Model

### Recommended Order
1. Validate `remora-v2` behavior baseline and apply any required runtime fixes there first.
2. Pin `remora-test` to that known-good `remora-v2` revision.
3. Build demo scripts/assets in `remora-test`.
4. Rehearse full end-to-end flow from `remora-test`.

### Branches
Use two branches, one per repo:
- `remora-v2`: `feature/idea6-graph-boot-readiness` (name can vary)
- `remora-test`: `feature/idea6-click-demo-pack`

### Dependency Pinning Rule (`remora-test`)
`/home/andrew/Documents/Projects/remora-test/pyproject.toml` currently uses git `main` for `remora`.
For active development, switch to local path source:
```toml
[tool.uv.sources]
remora = { path = "../remora-v2", editable = true }
```
After `remora-v2` changes are merged, either:
1. keep path source for local tandem development, or
2. pin to a specific commit/tag in git source for reproducible CI.

### Baseline Commands
In both repos before changes:
```bash
# remora-v2
cd /home/andrew/Documents/Projects/remora-v2
devenv shell -- uv sync --extra dev

# remora-test
cd /home/andrew/Documents/Projects/remora-test
devenv shell -- uv sync --extra dev
```

## 3) Workstream A — `remora-v2` Changes

This workstream is about runtime correctness and reliability guarantees.

### A0. Current Expectation
For this demo, `remora-v2` should already support:
- startup full scan before web server start (`src/remora/core/services/lifecycle.py`)
- two-pass relationship refresh within reconcile cycle (`src/remora/code/reconciler.py`)
- edge cleanup per relationship type (`src/remora/core/storage/graph.py`)

If all checks pass, no new runtime feature work is required for Idea #6.

### A1. Verify Required Runtime Behavior
From `remora-v2` root:
```bash
cd /home/andrew/Documents/Projects/remora-v2

git branch --show-current
git status --short

devenv shell -- pytest \
  tests/unit/test_reconciler_edges.py \
  tests/unit/test_graph.py \
  tests/unit/test_relationships.py \
  tests/unit/test_web_server.py \
  -q --tb=short
```

Manual code checks:
```bash
rg -n "refresh_relationships=False|_refresh_relationships\(" src/remora/code/reconciler.py
rg -n "delete_outgoing_edges_by_type" src/remora/core/storage/graph.py
```

### A2. Conditional Runtime Fixes (Only If A1 Fails)
If semantic edges are not reliable on cold start or watch batches, implement/fix:

1. `src/remora/code/reconciler.py`
- In reconcile cycle/watch batch flow, perform node upserts first with `refresh_relationships=False`.
- Perform `_refresh_relationships(file_path)` in a second pass after `_name_index` is complete for the batch.

2. `src/remora/core/storage/graph.py`
- Ensure `delete_outgoing_edges_by_type(node_id, edge_type)` is present and used during relationship refresh before re-adding semantic edges.

3. `tests/unit/test_reconciler_edges.py`
- Ensure there is a forward-reference coverage case (`a.py` references symbol in `b.py`) that passes on first reconcile cycle.

### A3. Optional but Strongly Recommended `remora-v2` Enhancements
These are not required to run the demo, but improve stage ergonomics:

1. Add aggregated endpoint(s):
- `GET /api/graph/stats`
- `GET /api/graph/hotspots?edge_types=imports,inherits&limit=20`

2. Add startup metadata fields in `/api/health` (scan duration, startup phase) for clearer pacing.

Only do this if timing permits; keep Idea #6 scope focused.

### A4. Publish/Pin Contract for `remora-test`
Before implementing demo assets in `remora-test`, produce one of:
1. merged `remora-v2` commit SHA, or
2. release tag.

`remora-test` must pin to that revision before rehearsals to avoid drift.

## 4) Workstream B — `remora-test` Changes

This workstream packages the demo and keeps it reproducible.

### B1. Create a Dedicated Idea #6 Asset Folder
In `remora-test`, create:
```text
demo/idea6_click/
  README.md
  PRESENTER_CUE_SHEET.md
```

Keep executable assets in existing `scripts/` convention.

### B2. Add New Demo Scripts in `remora-test/scripts`
Create these executable files:

1. `scripts/setup_idea6_click_demo.py`
Responsibilities:
- clone `https://github.com/pallets/click.git` into `${REPO_DIR:-/tmp/remora-demo-click}`
- support flags:
  - `--repo-dir`
  - `--force`
  - `--skip-clone`
  - `--clean-workspace`
- write `${repo_dir}/remora.idea6.yaml`
- print the exact next command to start runtime

2. `scripts/run_idea6_click_demo.py`
Responsibilities:
- run `remora start` (directly, no nested `devenv` inside script)
- default args:
  - `--project-root <repo_dir>`
  - `--config <repo_dir>/remora.idea6.yaml`
  - `--bind 127.0.0.1`
  - `--port 8080`
  - `--log-level INFO`
  - `--log-events`
- support flags: `--repo-dir`, `--config`, `--bind`, `--port`

3. `scripts/idea6_queries.sh`
Responsibilities:
- API smoke: `/api/health`, node count, edge count
- edge-type distribution
- semantic hotspots only (`imports` + `inherits`)
- optional file-level hotspot table by joining nodes+edges
- SSE replay sample: `/sse?replay=40&once=true`
- accept `BASE` env var (default `http://127.0.0.1:8080`)

4. `scripts/rehearse_idea6_click_demo.sh` (recommended)
Responsibilities:
- run setup script
- remind operator to start runtime in separate shell
- run `idea6_queries.sh` once runtime is healthy

### B3. Config Generated by `setup_idea6_click_demo.py`
Write this file to `${repo_dir}/remora.idea6.yaml`:

```yaml
project_path: "."
discovery_paths:
  - src
  - tests
discovery_languages:
  - python
language_map:
  ".py": "python"
query_search_paths:
  - "@default"
bundle_search_paths:
  - "@default"
bundle_overlays:
  function: "code-agent"
  class: "code-agent"
  method: "code-agent"
  directory: "directory-agent"
workspace_root: ".remora-demo"
max_turns: 2
runtime:
  max_concurrency: 2
  max_trigger_depth: 4
  max_reactive_turns_per_correlation: 2
  trigger_cooldown_ms: 300
workspace_ignore_patterns:
  - ".git"
  - ".venv"
  - "__pycache__"
  - "node_modules"
  - ".remora-demo"
```

Notes:
- Do not include `bundle_overlays.file`.
- Keep this config local to the cloned Click repo so `project_root` semantics stay simple.

### B4. Add Demo Documentation in `remora-test`
1. `demo/idea6_click/README.md`
Include:
- purpose
- prerequisites
- command order
- expected outputs
- fallback options (`--skip-clone`, alternate port)

2. `demo/idea6_click/PRESENTER_CUE_SHEET.md`
Include minute-by-minute 10 minute flow:
1. frame problem
2. clone/setup
3. start runtime
4. confirm health/counts
5. semantic hotspots
6. trust evidence (`/api/events`, `/sse`)

3. Update top-level `README.md`
Add a section linking to `demo/idea6_click/README.md`.

### B5. Update `remora-test` Contract Tests

1. Update `tests/integration/test_demo_contract.py`
Add required paths:
- `scripts/setup_idea6_click_demo.py`
- `scripts/run_idea6_click_demo.py`
- `scripts/idea6_queries.sh`
- `demo/idea6_click/README.md`
- `demo/idea6_click/PRESENTER_CUE_SHEET.md`

Also assert executability for all new scripts.

2. Add `tests/unit/test_idea6_script_contracts.py`
Validate script invariants, for example:
- setup script writes `remora.idea6.yaml`
- run script invokes `remora start`
- query script filters to semantic edges (`imports`/`inherits`)

### B6. `remora-test` Validation Commands
From `/home/andrew/Documents/Projects/remora-test`:
```bash
devenv shell -- python -m py_compile \
  scripts/setup_idea6_click_demo.py \
  scripts/run_idea6_click_demo.py

bash -n scripts/idea6_queries.sh

devenv shell -- pytest \
  tests/integration/test_demo_contract.py \
  tests/unit/test_idea6_script_contracts.py \
  -q --tb=short
```

## 5) End-to-End Rehearsal Flow

Run this from `remora-test` after both workstreams are complete.

### 5.1 Install with Correct `remora-v2` Source
```bash
cd /home/andrew/Documents/Projects/remora-test
devenv shell -- uv sync --extra dev
```

### 5.2 Setup Click Clone + Config
```bash
devenv shell -- python scripts/setup_idea6_click_demo.py --force
```

Expected outcome:
- `/tmp/remora-demo-click` exists
- `/tmp/remora-demo-click/remora.idea6.yaml` exists

### 5.3 Start Runtime (separate shell)
```bash
cd /home/andrew/Documents/Projects/remora-test
devenv shell -- python scripts/run_idea6_click_demo.py
```

### 5.4 Query Evidence (first shell)
```bash
cd /home/andrew/Documents/Projects/remora-test
bash scripts/idea6_queries.sh
```

Must show:
- `/api/health` status ok
- non-zero nodes and edges
- edge type distribution with semantic edges (`imports` expected; `inherits` when present)
- hotspot output from semantic edges only

### 5.5 Stage Fallbacks
1. If clone fails on network: rerun setup with `--skip-clone` against pre-cloned path.
2. If port 8080 is busy: run runtime with `--port 8081`, then `BASE=http://127.0.0.1:8081 bash scripts/idea6_queries.sh`.
3. If graph is too dense: reduce discovery scope to `src` in generated config.

## 6) Acceptance Criteria

### `remora-v2` Acceptance
1. Targeted reliability tests pass:
- `tests/unit/test_reconciler_edges.py`
- `tests/unit/test_graph.py`
- `tests/unit/test_relationships.py`

2. Reconciler behavior present:
- batch upsert first
- second-pass relationship refresh
- typed edge cleanup before re-add

3. A stable revision is provided for downstream pinning (commit SHA or tag).

### `remora-test` Acceptance
1. Required assets exist and are executable:
- `scripts/setup_idea6_click_demo.py`
- `scripts/run_idea6_click_demo.py`
- `scripts/idea6_queries.sh`
- `demo/idea6_click/README.md`
- `demo/idea6_click/PRESENTER_CUE_SHEET.md`

2. Contract tests pass:
- `tests/integration/test_demo_contract.py`
- `tests/unit/test_idea6_script_contracts.py`

3. Live rehearsal passes manually:
- clone/setup/start/query sequence works without ad-hoc edits
- semantic hotspot output is non-empty and explainable

## 7) Intern Handoff Format

Intern must submit two grouped summaries: one for each repo.

### Handoff Message Template
```text
Implemented Idea #6 two-repo delivery.

Repo A: remora-v2
Branch: <branch>
Commit(s):
- <sha1> <message>
Changes:
- <file>
- <file>
Validation:
- <command>
- <result>

Repo B: remora-test
Branch: <branch>
Commit(s):
- <sha1> <message>
Changes:
- <file>
- <file>
Validation:
- <command>
- <result>

Rehearsal evidence:
- Health payload summary
- Node/edge counts
- Semantic edge type counts
- Top hotspot rows

Known limitations:
- <item>
```

### Reviewer Quick Checklist
1. Is `remora-test` pinned to the intended `remora-v2` revision?
2. Do scripts run from clean checkout with only documented prerequisites?
3. Do outputs prove semantic relationships, not just structural `contains` edges?
4. Does presenter cue language match runtime truth (instant loaded graph after startup scan)?
