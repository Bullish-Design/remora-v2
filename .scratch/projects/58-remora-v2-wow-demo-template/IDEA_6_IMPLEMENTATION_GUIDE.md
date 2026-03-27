# IDEA 6 Implementation Guide — Instant Local Knowledge Graph Boot (Click)

## Table of Contents
1. Purpose and Demo Contract
Description: Define exactly what the intern is implementing and what “done” means for technical-demo quality.

2. Current State Snapshot (Do This First)
Description: Verify the current remora-v2 implementation state before writing any new code or scripts.

3. Environment and Tooling Setup
Description: Prepare a reproducible local environment with required dependencies and command conventions.

4. Deliverables to Build
Description: Enumerate concrete artifacts the intern must create (scripts, config templates, runbook, presenter cues).

5. Phase A — Demo Scaffold and Setup Automation
Description: Build executable scripts to clone Click, write config, clean/reset workspace, and run Remora deterministically.

6. Phase B — Graph Data Extraction and Hotspot Scripts
Description: Add reusable commands/scripts for node/edge stats and semantic hotspot extraction (imports/inherits-focused).

7. Phase C — Runtime Reliability Validation
Description: Validate that cross-file relationships populate immediately and reliably after cold start.

8. Phase D — Demo Narrative and Stage Flow
Description: Convert technical steps into a 10-minute live flow with clear claims and evidence checkpoints.

9. Phase E — Hardening and Failure Recovery
Description: Add deterministic fallback paths for network, startup, or API timing issues.

10. Acceptance Criteria (Ship Gate)
Description: Objective pass criteria that must be true before marking Idea #6 implementation complete.

11. Troubleshooting Playbook
Description: Common failure modes and exact diagnostic commands.

12. Handoff Checklist
Description: What the intern must provide when requesting review/approval.

## 1) Purpose and Demo Contract

### Goal
Implement a production-quality demo flow that takes a fresh clone of `pallets/click` and produces a trustworthy Remora knowledge graph quickly enough for a live technical presentation.

### Implementation Scope for This Intern Task
- Primary work is demo scaffolding and validation assets (scripts + docs), not core remora runtime changes.
- Core runtime behavior needed for this demo already exists in current `main`:
  - startup full scan before web serves traffic (`src/remora/core/services/lifecycle.py`)
  - second-pass relationship refresh for changed-file batches (`src/remora/code/reconciler.py`)
  - semantic edge cleanup helpers in storage (`src/remora/core/storage/graph.py`)

### Non-Negotiable Demo Claims
The implementation must support these claims with direct API evidence:
1. Fresh clone (no prebuilt graph cache) can be scanned and materialized quickly.
2. Graph data is queryable from APIs (`/api/health`, `/api/nodes`, `/api/edges`, `/api/events`, `/sse`).
3. Semantic relationships (`imports`, `inherits`) are available immediately after startup and are not order-dependent.
4. Hotspot outputs are based on semantic edges, not only structural `contains` edges.

### Out of Scope
- Building a new dashboard frontend.
- Replacing current web graph renderer.
- Model-quality tuning (this demo is graph-first, not LLM-response-first).

## 2) Current State Snapshot (Do This First)

Run these checks before creating any new files. The objective is to verify baseline behavior in your current checkout.

### 2.1 Verify branch and clean working state
```bash
git branch --show-current
git status --short
```

### 2.2 Confirm dependency sync
```bash
devenv shell -- uv sync --extra dev
```

### 2.3 Confirm relevant unit coverage passes
```bash
devenv shell -- pytest \
  tests/unit/test_graph.py \
  tests/unit/test_relationships.py \
  tests/unit/test_reconciler_edges.py \
  tests/unit/test_externals.py \
  tests/unit/test_web_server.py \
  -q --tb=short
```

Expected: all tests pass.

### 2.4 Confirm relationship reliability behavior exists
You should be on a revision where cross-file relationships are refreshed in a second pass for changed file batches.
Check these files for presence:
- `src/remora/code/reconciler.py`
- `src/remora/core/storage/graph.py`

Look for:
- batch reconcile with `refresh_relationships=False` first, then `_refresh_relationships(...)`
- `delete_outgoing_edges_by_type(...)` in NodeStore

### 2.5 Confirm API payload fields used by demo scripts
Check route implementations so jq queries use correct keys:
- `src/remora/web/routes/health.py` (`status`, `version`, `nodes`)
- `src/remora/web/routes/nodes.py` (`node_id`, `node_type`, `file_path`; edges with `from_id`, `to_id`, `edge_type`)
- `src/remora/web/routes/events.py` (`event_type`, `timestamp`, `payload`, `limit<=500`)

## 3) Environment and Tooling Setup

### 3.1 Required commands and tools
- `devenv shell -- ...` for all project code execution.
- `jq` for API result shaping.
- `curl` for API calls.
- `git` for clone/setup steps.

### 3.2 Demo runtime assumptions
- Remora binds web server on `127.0.0.1:8080` by default.
- Demo target path: `/tmp/remora-demo-click`
- Demo workspace root in target repo: `.remora-demo`

### 3.3 One-time sanity check
```bash
devenv shell -- remora --help
```

## 4) Deliverables to Build

Create the following files under:
`.scratch/projects/58-remora-v2-wow-demo-template/`

1. `setup_idea6_click_demo.py`
Purpose: end-to-end setup automation.
Responsibilities:
- clone (or refresh) `pallets/click`
- write demo config
- optionally clean previous `.remora-demo`
- print exact next commands

2. `run_idea6_click_demo.py`
Purpose: deterministic runtime launcher wrapper.
Responsibilities:
- run `remora start` with fixed flags
- emit startup timestamps and command echo

3. `idea6_queries.sh`
Purpose: reusable API query pack for stage and rehearsal.
Responsibilities:
- node count
- edge count by type
- node type distribution
- semantic hotspots (`imports` + `inherits` only)
- optional SSE replay sample

4. `IDEA_6_PRESENTER_CUE_SHEET.md`
Purpose: minute-by-minute stage narration with commands and expected outputs.

5. Update existing overview document
File: `IDEA_6_INSTANT_LOCAL_KNOWLEDGE_GRAPH_BOOT_OVERVIEW.md`
Required updates:
- remove `bundle_overlays.file`
- correct graph UX language to “instant loaded graph” (not “watch fill in”) unless runtime order changes
- replace hotspot query with semantic-edge-filtered version

## 5) Phase A — Demo Scaffold and Setup Automation

### Step A1: Create `setup_idea6_click_demo.py`
Create an executable Python script:
```bash
touch .scratch/projects/58-remora-v2-wow-demo-template/setup_idea6_click_demo.py
chmod +x .scratch/projects/58-remora-v2-wow-demo-template/setup_idea6_click_demo.py
```

### Step A2: Implement setup script behavior
Implement these CLI flags:
- `--repo-dir` (default: `/tmp/remora-demo-click`)
- `--force` (delete existing repo dir and reclone from scratch)
- `--skip-clone` (reuse existing clone, only rewrite config)
- `--clean-workspace` (remove `repo_dir/.remora-demo` before next run)

Implementation requirements:
1. Clone command:
```bash
git clone --depth 1 https://github.com/pallets/click.git /tmp/remora-demo-click
```
2. Write `/tmp/remora-demo-click/remora.demo.yaml` with this exact baseline:
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
3. If `--force`, remove existing `repo_dir` tree before cloning.
4. If `--clean-workspace`, remove `repo_dir/.remora-demo` only.
5. Print next-step command block at the end:
```bash
devenv shell -- ./.scratch/projects/58-remora-v2-wow-demo-template/run_idea6_click_demo.py
```

### Step A3: Create `run_idea6_click_demo.py`
This script should execute `remora start` directly (no nested `devenv shell` call inside script):
```bash
remora start \
  --project-root /tmp/remora-demo-click \
  --config /tmp/remora-demo-click/remora.demo.yaml \
  --port 8080 \
  --bind 127.0.0.1 \
  --log-level INFO \
  --log-events
```

Add options:
- `--repo-dir` (default `/tmp/remora-demo-click`)
- `--port` (default `8080`)
- `--bind` (default `127.0.0.1`)

Run this script from repo root via:
```bash
devenv shell -- ./.scratch/projects/58-remora-v2-wow-demo-template/run_idea6_click_demo.py
```

### Step A4: Validate Phase A
```bash
devenv shell -- python -m py_compile \
  .scratch/projects/58-remora-v2-wow-demo-template/setup_idea6_click_demo.py \
  .scratch/projects/58-remora-v2-wow-demo-template/run_idea6_click_demo.py
```
Expected: no output, exit code 0.

## 6) Phase B — Graph Data Extraction and Hotspot Scripts

### Step B1: Create `idea6_queries.sh`
Make it executable and include the following commands.

Health and base counts:
```bash
curl -sS http://127.0.0.1:8080/api/health | jq
curl -sS http://127.0.0.1:8080/api/nodes | jq 'length'
curl -sS http://127.0.0.1:8080/api/edges | jq 'length'
```

Node type distribution:
```bash
curl -sS http://127.0.0.1:8080/api/nodes | \
  jq 'sort_by(.node_type) | group_by(.node_type) | map({node_type: .[0].node_type, count: length}) | sort_by(-.count)'
```

Edge type distribution:
```bash
curl -sS http://127.0.0.1:8080/api/edges | \
  jq 'sort_by(.edge_type) | group_by(.edge_type) | map({edge_type: .[0].edge_type, count: length}) | sort_by(-.count)'
```

Semantic hotspots (critical):
```bash
curl -sS http://127.0.0.1:8080/api/edges | \
  jq '[.[] | select(.edge_type=="imports" or .edge_type=="inherits")] \
      | sort_by(.from_id) \
      | group_by(.from_id) \
      | map({from_id: .[0].from_id, semantic_out_degree: length}) \
      | sort_by(-.semantic_out_degree)[:20]'
```

Semantic hotspots by file path (recommended for stage readability):
```bash
NODES_JSON="$(mktemp)"
EDGES_JSON="$(mktemp)"
curl -sS http://127.0.0.1:8080/api/nodes > "$NODES_JSON"
curl -sS http://127.0.0.1:8080/api/edges > "$EDGES_JSON"

jq -n --slurpfile nodes "$NODES_JSON" --slurpfile edges "$EDGES_JSON" '
  ($nodes[0] | map({key: .node_id, value: .}) | from_entries) as $by_id
  | $edges[0]
  | map(select(.edge_type=="imports" or .edge_type=="inherits"))
  | map(select($by_id[.from_id] != null))
  | map({file_path: $by_id[.from_id].file_path, edge_type: .edge_type})
  | sort_by(.file_path)
  | group_by(.file_path)
  | map({
      file_path: .[0].file_path,
      semantic_out_degree: length,
      imports: (map(select(.edge_type=="imports")) | length),
      inherits: (map(select(.edge_type=="inherits")) | length)
    })
  | sort_by(-.semantic_out_degree)[:20]
'

rm -f "$NODES_JSON" "$EDGES_JSON"
```

SSE replay evidence:
```bash
curl -sN "http://127.0.0.1:8080/sse?replay=40&once=true"
```

### Step B2: Add a one-command mode
Optional but recommended: accept arguments (`health`, `counts`, `hotspots`, `all`) so presenter can run one command quickly.

### Step B3: Validate Phase B
With Remora running, execute:
```bash
bash .scratch/projects/58-remora-v2-wow-demo-template/idea6_queries.sh
```
Expected:
- non-empty node count
- non-empty edge count
- edge types include `contains` and ideally `imports`/`inherits`

## 7) Phase C — Runtime Reliability Validation

### Step C1: Cold-start reliability test
1. Remove old state:
```bash
rm -rf /tmp/remora-demo-click/.remora-demo
```
2. Start demo runtime.
3. Query semantic edge types immediately after health returns.

Pass condition:
- `imports` edges are present without needing extra file edits.
- `inherits` edges should appear when class hierarchies are present.

### Step C2: Order-independence sanity test
Create a tiny temporary project where importer filename sorts before import target (`a.py` imports `b.py`).

Expected:
- After first reconcile/startup, semantic edges from `a.py` to `b.py` exist.

### Step C3: Regression test run
```bash
devenv shell -- pytest \
  tests/unit/test_reconciler_edges.py \
  tests/unit/test_graph.py \
  tests/unit/test_relationships.py \
  -q --tb=short
```

### Step C4: Lint check
```bash
devenv shell -- ruff check \
  src/remora/code/reconciler.py \
  src/remora/core/storage/graph.py \
  tests/unit/test_reconciler_edges.py \
  tests/unit/test_graph.py
```

## 8) Phase D — Demo Narrative and Stage Flow

Create `IDEA_6_PRESENTER_CUE_SHEET.md` with this exact timing structure:

1. Minute 0-1: problem framing
- Unknown repo
- Need architecture orientation quickly

2. Minute 1-2: setup
- run setup script
- show generated config path

3. Minute 2-4: runtime boot
- start runtime
- show `/api/health`, node/edge counts

4. Minute 4-6: structure summary
- node type distribution
- edge type distribution

5. Minute 6-8: semantic hotspots
- run semantic hotspot query
- pick top 2 targets and explain why

6. Minute 8-10: trust evidence
- `/api/events?limit=40` sample
- `/sse?replay=40&once=true`

Important script-language correction:
- Do not claim “graph is filling in live” unless implementation changes startup order.
- Preferred phrase: “graph is immediately available after startup scan, with API-verifiable state.”

## 9) Phase E — Hardening and Failure Recovery

### Step E1: Clone fallback
If internet is unstable, keep a prepared local fallback clone:
- `/tmp/remora-demo-click` pre-cloned
- setup script supports `--skip-clone`

### Step E2: Scope fallback
If startup is slow on demo machine, switch to:
```yaml
discovery_paths:
  - src
```
only.

### Step E3: Port fallback
If `8080` is occupied:
- start with `--port 8081`
- run query script with base URL override.

### Step E4: API fallback evidence
If UI rendering is dense/noisy, stay API-first:
- `/api/health`
- `/api/nodes`
- `/api/edges`
- `/api/events`

## 10) Acceptance Criteria (Ship Gate)

All criteria below must pass before requesting review:

1. Setup automation works end-to-end
- `setup_idea6_click_demo.py --force` completes successfully.
- `remora.demo.yaml` is created in target repo.

2. Runtime starts and serves API
- `/api/health` returns `status: ok`.
- `/api/nodes` returns non-empty list.
- `/api/edges` returns non-empty list.

3. Semantic edge visibility is present after cold start
- Edge type distribution includes `imports` and/or `inherits`.
- Semantic hotspot query returns non-empty list.

4. Order-independence confidence
- Importer-before-target test case resolves correctly on first run.
- `tests/unit/test_reconciler_edges.py` passes.

5. Demo narrative consistency
- Presenter cue sheet matches actual runtime behavior.
- No claims conflict with current startup sequence.

6. Quality gates
- Targeted tests pass.
- Ruff checks pass on modified files.

## 11) Troubleshooting Playbook

### Problem: `/api/health` does not respond
Checks:
```bash
ps -ef | rg "remora start"
curl -sS http://127.0.0.1:8080/api/health
```
Actions:
- Confirm correct `--port` and `--bind`.
- Ensure no other process is occupying port.

### Problem: Node count is zero
Checks:
```bash
cat /tmp/remora-demo-click/remora.demo.yaml
ls -la /tmp/remora-demo-click/src
```
Actions:
- Confirm `discovery_paths` exist.
- Confirm `.py` language map is present.

### Problem: Only `contains` edges, no semantic edges
Checks:
```bash
curl -sS http://127.0.0.1:8080/api/edges | jq 'group_by(.edge_type) | map({t: .[0].edge_type, c:length})'
```
Actions:
- Confirm runtime includes current reconciler logic with second-pass relationship refresh.
- Re-run targeted tests in Phase C.

### Problem: Query script output too large/noisy
Actions:
- Reduce output to top 10 entries.
- Restrict to `src` discovery path for faster, cleaner run.

### Problem: Clone fails on stage network
Actions:
- Use pre-cloned `/tmp/remora-demo-click`.
- Run setup with `--skip-clone`.

## 12) Handoff Checklist

Before asking for approval, the intern must provide:

1. Paths of created/updated files.
2. Exact commands run for validation.
3. Test summary output.
4. Ruff output.
5. A 1-minute summary of what changed and why.
6. Known limitations (if any) and recommended next steps.

### Handoff Message Template
Use this format:

```text
Implemented Idea #6 demo scaffolding and validation pack.

Files changed:
- <file 1>
- <file 2>
...

Validation run:
- <command 1>
- <command 2>

Results:
- <tests passed summary>
- <lint summary>

Notes:
- <limitation or caveat>
- <next improvement>
```

---

### Reviewer Notes
If this guide is used after major remora runtime changes, re-check:
- startup ordering in lifecycle
- relationship extraction flow in reconciler
- edge cleanup semantics in NodeStore
