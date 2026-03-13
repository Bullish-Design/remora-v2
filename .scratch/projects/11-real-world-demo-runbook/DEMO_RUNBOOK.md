# 10-Minute Real-World Demo Runbook (Setup -> Live Demo -> Shutdown)

This runbook shows Remora as a real engineering assistant over a small but realistic Python service repo, including:
- directory/root nodes (`"."`, `src`, `src/services`, etc.)
- live reconcile (discover/change/remove)
- event stream visibility
- agent triggering via `/api/chat`
- optional autonomous rewrite if model is available

## 1. Prereqs

Use 3 terminals:
- `T1`: Remora server
- `T2`: API + control commands
- `T3`: live SSE stream

Assume:
- Remora repo is at `/home/andrew/Documents/Projects/remora-v2`
- You can run `devenv shell -- ...`

In `T2`:
```bash
export REMORA_ROOT=/home/andrew/Documents/Projects/remora-v2
export DEMO_ROOT=/tmp/remora-realworld-demo
cd "$REMORA_ROOT"
devenv shell -- uv sync --extra dev
```

Optional (for full autonomous rewrite):
```bash
export REMORA_MODEL_BASE_URL=http://127.0.0.1:8000/v1
export REMORA_MODEL_API_KEY=dummy
export REMORA_MODEL=Qwen/Qwen3-4B
```

## 2. Create a realistic demo project

In `T2`:
```bash
rm -rf "$DEMO_ROOT"
mkdir -p "$DEMO_ROOT/src/api" "$DEMO_ROOT/src/services" "$DEMO_ROOT/src/utils"

cat > "$DEMO_ROOT/src/api/orders.py" << 'PYEOF'
from src.services.pricing import compute_total
from src.services.discounts import discount_for_tier

def create_order(user_tier: str, item_prices: list[float]) -> dict:
    subtotal = compute_total(item_prices)
    discount = discount_for_tier(user_tier, subtotal)
    total = subtotal - discount
    return {"subtotal": subtotal, "discount": discount, "total": total}
PYEOF

cat > "$DEMO_ROOT/src/services/pricing.py" << 'PYEOF'
def compute_total(item_prices: list[float]) -> float:
    return sum(item_prices)
PYEOF

cat > "$DEMO_ROOT/src/services/discounts.py" << 'PYEOF'
def discount_for_tier(tier: str, subtotal: float) -> float:
    if tier == "gold":
        return subtotal * 0.15
    if tier == "silver":
        return subtotal * 0.05
    return 0.0
PYEOF

cat > "$DEMO_ROOT/src/utils/money.py" << 'PYEOF'
def format_usd(value: float) -> str:
    return f"${value:.2f}"
PYEOF

cat > "$DEMO_ROOT/src/main.py" << 'PYEOF'
from src.api.orders import create_order

if __name__ == "__main__":
    result = create_order("gold", [10.0, 20.0, 5.0])
    print(result)
PYEOF

cat > "$DEMO_ROOT/remora.yaml" << EOF2
discovery_paths:
  - src
discovery_languages:
  - python
swarm_root: .remora
bundle_root: ${REMORA_ROOT}/bundles
model_base_url: \${REMORA_MODEL_BASE_URL:-http://localhost:8000/v1}
model_api_key: \${REMORA_MODEL_API_KEY:-}
model_default: \${REMORA_MODEL:-Qwen/Qwen3-4B}
bundle_mapping:
  function: code-agent
  class: code-agent
  method: code-agent
  file: code-agent
  directory: directory-agent
EOF2

cd "$DEMO_ROOT"
git init
git add .
git commit -m "demo baseline"
```

## 3. Start Remora

In `T1`:
```bash
cd "$REMORA_ROOT"
devenv shell -- remora start --project-root "$DEMO_ROOT" --port 8080
```

Keep this running.

## 4. Verify graph + directory hierarchy

In `T2`:

```bash
curl -sS http://127.0.0.1:8080/api/nodes | jq 'length'
```

Show node counts by type:
```bash
curl -sS http://127.0.0.1:8080/api/nodes | \
jq -r 'group_by(.node_type)[] | "\(.[0].node_type)\t\(length)"'
```

Show directory parent chain:
```bash
curl -sS http://127.0.0.1:8080/api/nodes | \
jq -r '.[] | select(.node_type=="directory") | [.node_id, (.parent_id // "null")] | @tsv' | sort
```

Show top-level children of root:
```bash
curl -sS http://127.0.0.1:8080/api/nodes | \
jq -r '.[] | select(.parent_id==".") | [.node_type, .node_id] | @tsv' | sort
```

## 5. Start live event stream

In `T3`:
```bash
curl -N "http://127.0.0.1:8080/sse?replay=20"
```

You’ll see event lines streaming in as changes happen.

## 6. Live structural change demo (real-time reconcile)

In `T2`, make three changes:

1) add file:
```bash
cat > "$DEMO_ROOT/src/services/tax.py" << 'PYEOF'
def apply_tax(amount: float, rate: float = 0.07) -> float:
    return amount * (1.0 + rate)
PYEOF
```

2) modify file:
```bash
cat > "$DEMO_ROOT/src/services/pricing.py" << 'PYEOF'
def compute_total(item_prices: list[float]) -> float:
    subtotal = sum(item_prices)
    return round(subtotal, 2)
PYEOF
```

3) remove file:
```bash
rm -f "$DEMO_ROOT/src/utils/money.py"
```

Now narrate from `T3` stream:
- `NodeDiscoveredEvent` for new nodes
- `NodeChangedEvent` on changed nodes/directories
- `NodeRemovedEvent` for removed nodes
- `ContentChangedEvent` where applicable

Re-query directory structure in `T2`:
```bash
curl -sS http://127.0.0.1:8080/api/nodes | \
jq -r '.[] | select(.node_type=="directory") | [.node_id, (.parent_id // "null")] | @tsv' | sort
```

## 7. Trigger agents via real API chat

Pick node IDs dynamically:

```bash
ORDER_NODE=$(curl -sS http://127.0.0.1:8080/api/nodes | jq -r '.[] | select(.name=="create_order") | .node_id' | head -n1)
DIR_NODE="src/services"
echo "ORDER_NODE=$ORDER_NODE"
echo "DIR_NODE=$DIR_NODE"
```

Send a directory-level request:
```bash
curl -sS -X POST http://127.0.0.1:8080/api/chat \
  -H 'Content-Type: application/json' \
  -d "{\"node_id\":\"$DIR_NODE\",\"message\":\"Summarize your immediate children and suggest one refactor.\"}"
```

Send a function-level request:
```bash
curl -sS -X POST http://127.0.0.1:8080/api/chat \
  -H 'Content-Type: application/json' \
  -d "{\"node_id\":\"$ORDER_NODE\",\"message\":\"Review create_order for robustness and apply a minimal safe rewrite if needed.\"}"
```

Inspect lifecycle events:
```bash
curl -sS "http://127.0.0.1:8080/api/events?limit=80" | \
jq -r '.[] | select(.event_type=="AgentStartEvent" or .event_type=="AgentCompleteEvent" or .event_type=="AgentErrorEvent") | [.event_type, (.payload.agent_id // ""), (.payload.error // .payload.result_summary // "")] | @tsv'
```

## 8. Optional: show autonomous code change (if model is available)

Check diff:
```bash
git -C "$DEMO_ROOT" diff -- src/api/orders.py src/services/pricing.py
```

If there’s no edit yet, send a more explicit instruction:
```bash
curl -sS -X POST http://127.0.0.1:8080/api/chat \
  -H 'Content-Type: application/json' \
  -d "{\"node_id\":\"$ORDER_NODE\",\"message\":\"Use rewrite_self to add input validation: reject empty item_prices and unknown user_tier values.\"}"
```

Then re-check:
```bash
sleep 3
git -C "$DEMO_ROOT" diff -- src/api/orders.py
```

## 9. Quick project root orchestrator moment

Send to root node:
```bash
curl -sS -X POST http://127.0.0.1:8080/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"node_id":".","message":"Give a 5-line project structure summary and one cross-directory improvement suggestion."}'
```

Then show recent events:
```bash
curl -sS "http://127.0.0.1:8080/api/events?limit=30" | jq -r '.[].event_type'
```

## 10. Shutdown

In `T1`, stop Remora with `Ctrl+C`.

Verify stopped (`T2`):
```bash
pgrep -af "remora start --project-root $DEMO_ROOT" || echo "Remora stopped"
```

Optional cleanup:
```bash
rm -rf "$DEMO_ROOT/.remora"
# Or remove full demo:
# rm -rf "$DEMO_ROOT"
```
