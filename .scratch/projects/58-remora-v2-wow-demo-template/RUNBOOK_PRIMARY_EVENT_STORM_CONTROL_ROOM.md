# Runbook — Primary Demo: Event Storm Control Room

## Goal
Run a 10-minute live demo where remora-v2 absorbs a burst of code events, routes reactive work to virtual agents, and exposes every step through graph + event observability.

## What the audience should see
1. Real-time graph and timeline movement in the web UI.
2. High event throughput with controlled convergence (not chaos).
3. Inspectable agent behavior via `/api/events`, `/api/nodes`, and `/api/proposals`.

## Preconditions
1. Terminal access at repository root: `/home/andrew/Documents/Projects/remora-v2`.
2. Browser available for `http://127.0.0.1:8080`.
3. Reachable model endpoint (recommended default in this repo): `http://remora-server:8000/v1`.

## Terminal Layout
1. Terminal A: run remora runtime.
2. Terminal B: live observability and event forensics.
3. Browser: graph + timeline + agent panel.

## Setup (8-10 minutes before demo)

### 1) Sync dependencies
```bash
devenv shell -- uv sync --extra dev
```

### 2) Create fixture project via setup script
```bash
devenv shell -- \
  ./.scratch/projects/58-remora-v2-wow-demo-template/setup_primary_event_storm_demo.py \
  --force
```

### 3) Start runtime (Terminal A)
```bash
devenv shell -- remora start \
  --project-root /tmp/remora-demo-storm \
  --config /tmp/remora-demo-storm/remora.yaml \
  --port 8080 \
  --bind 127.0.0.1 \
  --log-level INFO \
  --log-events
```

### 4) Readiness checks (Terminal B)
```bash
curl -sS http://127.0.0.1:8080/api/health | jq
curl -sS http://127.0.0.1:8080/api/nodes | jq 'length'
curl -sS http://127.0.0.1:8080/api/edges | jq 'length'
```

## Live Script (10 minutes)

### Minute 0-2: Baseline and architecture framing
1. Open `http://127.0.0.1:8080`.
2. Show node graph and timeline panel.
3. In Terminal B, show current event mix:

```bash
curl -sS "http://127.0.0.1:8080/api/events?limit=200" | \
  jq 'sort_by(.event_type) | group_by(.event_type) | map({event_type: .[0].event_type, count: length}) | sort_by(-.count)'
```

### Minute 2-5: Trigger controlled event storm
Run in Terminal B:

```bash
for n in $(seq 1 14); do
  RATE="0.0$((7 + (n % 3)))"
  LIMIT=$((1500 + (n * 15)))
  perl -0pi -e "s/tax_rate: float = [0-9.]+/tax_rate: float = ${RATE}/" /tmp/remora-demo-storm/src/billing/pricing.py
  perl -0pi -e "s/order_total > [0-9]+/order_total > ${LIMIT}/" /tmp/remora-demo-storm/src/risk/policy.py
  sleep 0.18
done
```

Immediately show impact:

```bash
curl -sS "http://127.0.0.1:8080/api/events?limit=300" | \
  jq '[.[] | select(.event_type=="node_changed" or .event_type=="agent_start" or .event_type=="agent_complete" or .event_type=="agent_error")]'
```

### Minute 5-7: Time-travel one decision chain
1. Pull one recent correlation id:

```bash
CORR_ID=$(curl -sS "http://127.0.0.1:8080/api/events?limit=300" | \
  jq -r '.[] | select(.correlation_id != null and .correlation_id != "") | .correlation_id' | head -n 1)
echo "$CORR_ID"
```

2. Replay just that chain:

```bash
curl -sS "http://127.0.0.1:8080/api/events?limit=500&correlation_id=${CORR_ID}" | \
  jq '[.[] | {event_type, correlation_id, payload}]'
```

### Minute 7-9: Directed interaction with review lane
1. Send a direct message to review-agent:

```bash
curl -sS -X POST "http://127.0.0.1:8080/api/chat" \
  -H "content-type: application/json" \
  -d '{"node_id":"review-agent","message":"Summarize the three highest-risk changes from the last storm burst in concise bullets."}' | jq
```

2. Show resulting conversation state:

```bash
curl -sS "http://127.0.0.1:8080/api/nodes/review-agent/conversation" | jq
```

### Minute 9-10: Optional proposal flow
If proposals exist:

```bash
curl -sS "http://127.0.0.1:8080/api/proposals" | jq
```

If the list is non-empty, show diff for first proposal:

```bash
PROPOSAL_NODE=$(curl -sS "http://127.0.0.1:8080/api/proposals" | jq -r '.[0].node_id // empty')
if [ -n "${PROPOSAL_NODE}" ]; then
  curl -sS "http://127.0.0.1:8080/api/proposals/${PROPOSAL_NODE}/diff" | jq
fi
```

## On-stage narration points
1. "Every state transition is in the event log; nothing is hidden."
2. "This graph is not decorative: it is the runtime's routing substrate."
3. "We can audit any decision chain by correlation, not guess from logs."

## Recovery Branches

### Branch A: Model endpoint slows down
1. Stop storm early after 6-8 ticks.
2. Pivot to event forensics section and explain bounded backpressure (`max_reactive_turns_per_correlation`).

### Branch B: No proposals appear
1. Skip proposal section.
2. Use `review-agent` conversation + `remora_tool_result` events as proof of autonomous tool execution.

### Branch C: Browser gets noisy
1. Keep browser on graph only.
2. Move all evidence to Terminal B (`/api/events`, `/api/nodes`, `/api/proposals`).

## Hard Stop / Cleanup
1. `Ctrl+C` Terminal A.
2. Optional cleanup:

```bash
rm -rf /tmp/remora-demo-storm
```
