# Runbook — Backup Demo: Graph Boot + Event Time-Travel (No LLM Dependency)

## When to switch to this backup
1. Model endpoint is unavailable or too slow for live interaction.
2. You need deterministic behavior with minimal moving parts.
3. You still want a technical "wow": live graph projection + event replay + forensic queries.

## Goal
Demonstrate remora-v2's event-native graph runtime without relying on successful model turns.

## Demo promise
1. Cold-start to useful graph projection in one run.
2. Live node discovery/removal events from filesystem operations.
3. Repeatable event forensics via `/api/events` and `/sse?replay=...`.

## Setup (5-7 minutes)

### 1) Sync dependencies
```bash
devenv shell -- uv sync --extra dev
```

### 2) Create deterministic fixture project via setup script
```bash
devenv shell -- \
  ./.scratch/projects/58-remora-v2-wow-demo-template/setup_backup_graph_boot_demo.py \
  --force
```

### 3) Start runtime
```bash
devenv shell -- remora start \
  --project-root /tmp/remora-demo-backup \
  --config /tmp/remora-demo-backup/remora.yaml \
  --port 8080 \
  --bind 127.0.0.1 \
  --log-level INFO \
  --log-events
```

## Live Script (8 minutes)

### Minute 0-2: Graph materialization
1. Open `http://127.0.0.1:8080`.
2. In terminal, confirm baseline:

```bash
curl -sS http://127.0.0.1:8080/api/health | jq
curl -sS http://127.0.0.1:8080/api/nodes | jq 'length'
curl -sS http://127.0.0.1:8080/api/edges | jq 'length'
```

### Minute 2-4: Structural intelligence query
Show top fan-out nodes from the current edge set:

```bash
curl -sS http://127.0.0.1:8080/api/edges | \
  jq 'sort_by(.from_id) | group_by(.from_id) | map({from_id: .[0].from_id, out_degree: length}) | sort_by(-.out_degree)[:10]'
```

Show node-type distribution:

```bash
curl -sS http://127.0.0.1:8080/api/nodes | \
  jq 'sort_by(.node_type) | group_by(.node_type) | map({node_type: .[0].node_type, count: length}) | sort_by(-.count)'
```

### Minute 4-6: Live deterministic event generation (no chat needed)
Create a new source file to trigger `node_discovered`:

```bash
mkdir -p /tmp/remora-demo-backup/src/experiments
cat > /tmp/remora-demo-backup/src/experiments/what_if.py <<'EOF'
def scenario_score(probability: float, impact: float) -> float:
    return round(probability * impact, 4)
EOF
```

Check new discovery events:

```bash
curl -sS "http://127.0.0.1:8080/api/events?event_type=node_discovered&limit=50" | jq
```

Remove that file to trigger `node_removed`:

```bash
rm -f /tmp/remora-demo-backup/src/experiments/what_if.py
curl -sS "http://127.0.0.1:8080/api/events?event_type=node_removed&limit=50" | jq
```

### Minute 6-8: Event time-travel playback
Replay recent stream frames:

```bash
curl -sN "http://127.0.0.1:8080/sse?replay=40&once=true"
```

Then summarize event mix:

```bash
curl -sS "http://127.0.0.1:8080/api/events?limit=200" | \
  jq 'sort_by(.event_type) | group_by(.event_type) | map({event_type: .[0].event_type, count: length}) | sort_by(-.count)'
```

## On-stage narration points
1. "Even with model behavior removed from the critical path, the runtime remains observable and inspectable."
2. "Node graph state is projected from append-only events, so replay and forensics are straightforward."
3. "This gives us deterministic operations posture when external model systems are unstable."

## Fast Pivot Protocol (from primary to backup)
1. Keep browser open.
2. Stop primary runtime with `Ctrl+C`.
3. Start this backup runtime on the same port (`8080`) so URLs stay unchanged.
4. Begin at `Graph materialization` step above.

## Cleanup
```bash
rm -rf /tmp/remora-demo-backup
```
