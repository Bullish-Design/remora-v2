# Idea #6 Detailed Overview (Click Edition) — Instant Local Knowledge Graph Boot

## 1) Demo Thesis
Clone a real Python repository (`pallets/click`) and immediately generate a navigable knowledge graph with Remora v2.  
The value shown on stage is rapid architectural orientation: from unknown codebase to actionable structural insight in minutes.

## 2) Why `pallets/click` Is the Right Repo for This Demo
- Real and recognizable to Python engineers.
- Moderate complexity: enough graph richness without overwhelming startup latency.
- Clean layout (`src/`, `tests/`) that produces understandable clusters fast.
- Better credibility than toy repos while staying operationally safe for live demo timing.

## 3) Core Promise
From `git clone` to "I know where to review/refactor first" within one short live segment.

## 4) Audience-Visible Outcomes
1. Cold start: no prebuilt graph or cache.
2. Immediate graph materialization after runtime startup.
3. Concrete structural summaries:
   - node/edge counts
   - node-type distribution
   - top hotspot files/directories
4. API-backed evidence that the map is real, inspectable system state.

## 5) Technical Capabilities Demonstrated
- Discovery + reconciliation (`FileReconciler.full_scan`).
- Persistent event and graph state (`EventStore`, `NodeStore`).
- Web observability (`/api/health`, `/api/nodes`, `/api/edges`, `/api/events`, `/sse`).
- Fast "codebase orientation" workflow powered by graph queries, not manual file-by-file spelunking.

## 6) Demo Environment and Inputs

### Target Repo
```bash
git clone --depth 1 https://github.com/pallets/click.git /tmp/remora-demo-click
```

### Demo Config (write inside clone)
```bash
cat > /tmp/remora-demo-click/remora.demo.yaml <<'EOF'
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
  file: "code-agent"
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
EOF
```

### Runtime Start
```bash
devenv shell -- remora start \
  --project-root /tmp/remora-demo-click \
  --config /tmp/remora-demo-click/remora.demo.yaml \
  --port 8080 \
  --bind 127.0.0.1 \
  --log-level INFO \
  --log-events
```

## 7) Live Narrative (10 Minutes)

### Minute 0-1: Frame the challenge
- "Fresh clone, no prior indexing, no handcrafted architecture doc."
- "Goal: get immediate structural intelligence."

### Minute 1-2: Clone and launch
- Clone Click.
- Start Remora against that clone.

### Minute 2-4: Confirm graph boot
```bash
curl -sS http://127.0.0.1:8080/api/health | jq
curl -sS http://127.0.0.1:8080/api/nodes | jq 'length'
curl -sS http://127.0.0.1:8080/api/edges | jq 'length'
```
- Open `http://127.0.0.1:8080` and show the graph filling in.

### Minute 4-6: Show structural profile
```bash
curl -sS http://127.0.0.1:8080/api/nodes | \
  jq 'sort_by(.node_type) | group_by(.node_type) | map({node_type: .[0].node_type, count: length}) | sort_by(-.count)'
```

```bash
curl -sS http://127.0.0.1:8080/api/nodes | \
  jq 'sort_by(.file_path) | group_by(.file_path) | map({file_path: .[0].file_path, node_count: length}) | sort_by(-.node_count)[:12]'
```

### Minute 6-8: Extract hotspots for action
```bash
curl -sS http://127.0.0.1:8080/api/edges | \
  jq 'sort_by(.from_id) | group_by(.from_id) | map({from_id: .[0].from_id, out_degree: length}) | sort_by(-.out_degree)[:12]'
```
- Narrate 2-3 likely "review next" locations based on concentration and connectivity.

### Minute 8-10: Trust and reproducibility
```bash
curl -sN "http://127.0.0.1:8080/sse?replay=40&once=true"
```
- Explain that the graph and timeline are backed by event/logged state, not transient UI-only calculations.

## 8) The "Wow" Moments
1. `git clone` to live architecture graph in one continuous flow.
2. Non-trivial repository (Click) rendered into understandable clusters quickly.
3. Immediate hotspot extraction from graph APIs without reading dozens of files manually.

## 9) Success Metrics (Rehearsal Checklist)
- Time from clone completion to `/api/health` ready.
- Time to first non-empty `/api/nodes`.
- Time to stable node/edge counts.
- Time to first credible hotspot list.
- Total stage segment duration (target: 10 minutes).

## 10) Risks and Mitigations
- Risk: network hiccup during clone.
  - Mitigation: keep a pre-cloned fallback at `/tmp/remora-demo-click`.
- Risk: graph is visually dense.
  - Mitigation: anchor story on API summaries first, UI second.
- Risk: discovery takes longer than expected on stage machine.
  - Mitigation: scope `discovery_paths` to `src` only for backup timing profile.

## 11) Why This Demo Is Strategically Useful
This positions Remora as an engineering acceleration tool for unfamiliar repositories:  
"I can bootstrap architectural context immediately, with inspectable evidence, before making risky edits."

## 12) Recommended Next Step
Create a Click-specific one-page presenter sheet with:
1. exact command order,
2. expected numeric ranges (node/edge counts) from rehearsal,
3. 4-5 fixed narration lines tied to each command block.
