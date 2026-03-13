# 10-Minute Real-World Demo Runbook (Using `/home/andrew/Documents/Projects/remora-test`)

This runbook demonstrates Remora against a prebuilt sample repo at:

`/home/andrew/Documents/Projects/remora-test`

It shows:
- Directory/root nodes (`.` plus folder hierarchy)
- Live reconcile (discover/change/remove)
- Event streaming over SSE
- Agent triggering through `/api/chat`
- Optional autonomous rewrite flow

## 1. Terminals and Environment

Use 3 terminals:
- `T1`: Remora runtime
- `T2`: Control commands and API calls
- `T3`: SSE event stream

In `T2`:
```bash
export REMORA_ROOT=/home/andrew/Documents/Projects/remora-v2
export DEMO_ROOT=/home/andrew/Documents/Projects/remora-test
cd "$REMORA_ROOT"
devenv shell -- uv sync --extra dev
```

Optional model settings:
```bash
export REMORA_MODEL_BASE_URL=http://127.0.0.1:8000/v1
export REMORA_MODEL_API_KEY=dummy
export REMORA_MODEL=Qwen/Qwen3-4B-Instruct-2507-FP8
```

## 2. Reset Demo Repo to Baseline (repeatable)

The sample project is already initialized as a git repo. Before each demo run:

```bash
cd "$DEMO_ROOT"
git reset --hard HEAD
git clean -fd
```

Quick sanity checks:
```bash
find src -maxdepth 3 -type f | sort
cat remora.yaml
```

## 3. Start Remora

In `T1`:
```bash
cd "$REMORA_ROOT"
devenv shell -- remora start --project-root "$DEMO_ROOT" --port 8080
```

## 4. Verify Graph and Directory Hierarchy

In `T2`:
```bash
curl -sS http://127.0.0.1:8080/api/nodes | jq 'length'
```

Node counts by type:
```bash
curl -sS http://127.0.0.1:8080/api/nodes | \
jq -r 'group_by(.node_type)[] | "\(.[0].node_type)\t\(length)"'
```

Directory chain:
```bash
curl -sS http://127.0.0.1:8080/api/nodes | \
jq -r '.[] | select(.node_type=="directory") | [.node_id, (.parent_id // "null")] | @tsv' | sort
```

Children of root (`.`):
```bash
curl -sS http://127.0.0.1:8080/api/nodes | \
jq -r '.[] | select(.parent_id==".") | [.node_type, .node_id] | @tsv' | sort
```

## 5. Start Live Event Stream

In `T3`:
```bash
curl -N "http://127.0.0.1:8080/sse?replay=20"
```

## 6. Trigger Real Structural Changes

In `T2`, perform three realistic repo edits:

1) Add new service file:
```bash
cat > "$DEMO_ROOT/src/services/fraud.py" << 'PYEOF'
def risk_score(amount: float, user_tier: str) -> float:
    base = amount / 100.0
    if user_tier.lower().strip() == "gold":
        return max(0.0, base - 0.2)
    return min(1.0, base)
PYEOF
```

2) Modify existing pricing logic:
```bash
cat > "$DEMO_ROOT/src/services/pricing.py" << 'PYEOF'
def compute_total(item_prices: list[float]) -> float:
    subtotal = sum(item_prices)
    # Guard against tiny floating artifacts
    return round(subtotal, 2)
PYEOF
```

3) Remove utility file:
```bash
rm -f "$DEMO_ROOT/src/utils/money.py"
```

Narrate from `T3` as events appear:
- `NodeDiscoveredEvent`
- `NodeChangedEvent`
- `NodeRemovedEvent`
- `ContentChangedEvent`

Re-check hierarchy in `T2`:
```bash
curl -sS http://127.0.0.1:8080/api/nodes | \
jq -r '.[] | select(.node_type=="directory") | [.node_id, (.parent_id // "null")] | @tsv' | sort
```

## 7. Trigger Directory and Function Agents

In `T2`, select targets dynamically:
```bash
ORDER_NODE=$(curl -sS http://127.0.0.1:8080/api/nodes | jq -r '.[] | select(.name=="create_order") | .node_id' | head -n1)
DIR_NODE="src/services"
echo "ORDER_NODE=$ORDER_NODE"
echo "DIR_NODE=$DIR_NODE"
```

Ask directory node for structural coordination insight:
```bash
curl -sS -X POST http://127.0.0.1:8080/api/chat \
  -H 'Content-Type: application/json' \
  -d "{\"node_id\":\"$DIR_NODE\",\"message\":\"Summarize your immediate children and suggest one refactor for service cohesion.\"}"
```

Ask function node for robustness review:
```bash
curl -sS -X POST http://127.0.0.1:8080/api/chat \
  -H 'Content-Type: application/json' \
  -d "{\"node_id\":\"$ORDER_NODE\",\"message\":\"Review create_order for input safety and suggest a minimal safe patch.\"}"
```

Show lifecycle events:
```bash
curl -sS "http://127.0.0.1:8080/api/events?limit=80" | \
jq -r '.[] | select(.event_type=="AgentStartEvent" or .event_type=="AgentCompleteEvent" or .event_type=="AgentErrorEvent") | [.event_type, (.payload.agent_id // ""), (.payload.error // .payload.result_summary // "")] | @tsv'
```

## 8. Optional Autonomous Rewrite Proof

Inspect current patch:
```bash
cd "$DEMO_ROOT"
git diff -- src/api/orders.py src/services/pricing.py
```

If needed, send explicit rewrite instruction:
```bash
curl -sS -X POST http://127.0.0.1:8080/api/chat \
  -H 'Content-Type: application/json' \
  -d "{\"node_id\":\"$ORDER_NODE\",\"message\":\"Use rewrite_self to add validation: reject empty item_prices and unknown user_tier values.\"}"
```

Then check patch again:
```bash
sleep 3
git -C "$DEMO_ROOT" diff -- src/api/orders.py
```

## 9. Root Project Node Moment

Ask the root orchestrator:
```bash
curl -sS -X POST http://127.0.0.1:8080/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"node_id":".","message":"Give a 5-line project structure summary and one cross-directory improvement suggestion."}'
```

Show recent event mix:
```bash
curl -sS "http://127.0.0.1:8080/api/events?limit=30" | jq -r '.[].event_type'
```

## 10. Shutdown

In `T1`: `Ctrl+C`

Verify process stopped (`T2`):
```bash
pgrep -af "remora start --project-root $DEMO_ROOT" || echo "Remora stopped"
```

Optional cleanup between demos:
```bash
cd "$DEMO_ROOT"
git reset --hard HEAD
git clean -fd
rm -rf .remora
```
