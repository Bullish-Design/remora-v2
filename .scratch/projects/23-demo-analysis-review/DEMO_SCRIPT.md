# Demo Script - Remora v2 (Current Library)

## Table of Contents
1. Demo Goal and Format
2. Pre-Demo Setup
3. Terminal and Window Layout
4. Step-by-Step Demo Walkthrough
5. Live Narration Prompts
6. Fallback Paths
7. Post-Demo Wrap

## 1. Demo Goal and Format

Goal:
- Show that Remora turns code elements into autonomous agents that react, communicate, and can be interacted with through Neovim and a live web graph.

Format:
- Duration: 8-10 minutes.
- Surfaces: terminal + Neovim + browser.
- Backend: vLLM at `http://remora-server:8000/v1`.

## 2. Pre-Demo Setup

### 2.1 One-time repo setup

Run from repo root:

```bash
devenv shell -- uv sync --extra dev
devenv shell -- python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q
```

Expected:
- Tests pass (current baseline: `217 passed, 5 skipped`).

### 2.2 Create the dedicated demo project (recommended)

The repo currently has no `demo-project/` directory. Create one to keep the graph small and clear:

```bash
mkdir -p demo-project/{src,queries,bundles}
cp -r bundles/system bundles/code-agent bundles/directory-agent demo-project/bundles/
cp src/remora/code/queries/python.scm demo-project/queries/
```

Create `demo-project/src/calculator.py`:

```python
"""Core calculator operations."""

def add(a: float, b: float) -> float:
    return a + b

def subtract(a: float, b: float) -> float:
    return a - b

def multiply(a: float, b: float) -> float:
    return a * b

def divide(a: float, b: float) -> float:
    return a / b
```

Create `demo-project/src/validator.py`:

```python
def is_number(value) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False

def check_divisor(b: float) -> bool:
    return b != 0
```

Create `demo-project/src/formatter.py`:

```python
def format_result(operation: str, a: float, b: float, result: float) -> str:
    return f"{a} {operation} {b} = {result}"

def format_error(operation: str, error: str) -> str:
    return f"Error in {operation}: {error}"
```

Create `demo-project/src/api.py`:

```python
from calculator import add, subtract, multiply, divide
from validator import is_number, check_divisor
from formatter import format_result, format_error

OPERATIONS = {
    "add": add,
    "subtract": subtract,
    "multiply": multiply,
    "divide": divide,
}

def calculate(operation: str, a, b) -> str:
    if not is_number(a) or not is_number(b):
        return format_error(operation, "Invalid input")
    a, b = float(a), float(b)
    if operation == "divide" and not check_divisor(b):
        return format_error(operation, "Division by zero")
    fn = OPERATIONS.get(operation)
    if fn is None:
        return format_error(operation, f"Unknown operation: {operation}")
    return format_result(operation, a, b, fn(a, b))
```

Create `demo-project/remora.yaml`:

```yaml
project_path: "."
discovery_paths:
  - "src/"
language_map:
  ".py": "python"
query_paths:
  - "queries/"
bundle_root: "bundles"
bundle_overlays:
  function: "code-agent"
  class: "code-agent"
  method: "code-agent"
  directory: "directory-agent"
model_base_url: "http://remora-server:8000/v1"
model_default: "Qwen/Qwen3-4B-Instruct-2507-FP8"
model_api_key: ""
timeout_s: 120.0
max_turns: 4
workspace_root: ".remora"
max_concurrency: 4
trigger_cooldown_ms: 2000
```

### 2.3 Neovim helper

Copy helper:

```bash
mkdir -p ~/.config/nvim/lua
cp contrib/neovim/remora.lua ~/.config/nvim/lua/remora.lua
```

Add to Neovim config:

```lua
require("remora").setup({
  web_url = "http://localhost:8080",
  filetypes = { "python" },
})
```

### 2.4 Final preflight checks

```bash
curl -sS http://remora-server:8000/v1/models
devenv shell -- remora discover --project-root ./demo-project
```

Expected:
- Model list returned.
- Demo project discovery returns a small node set.

## 3. Terminal and Window Layout

Use three panes:
1. Left: Neovim opened at `demo-project/src/calculator.py`.
2. Right: browser at `http://localhost:8080`.
3. Bottom: terminal for `remora start` logs.

## 4. Step-by-Step Demo Walkthrough

### 4.1 Start runtime (0:00-1:00)

```bash
devenv shell -- remora start --project-root ./demo-project --port 8080 --bind 0.0.0.0 --log-events
```

What to show:
- Discovery complete line.
- Web graph populating with nodes.

### 4.2 Show node identity in Neovim and web (1:00-2:30)

In Neovim:
- Open `calculator.py` and place cursor on `divide`.
- Show CodeLens/hover identity if available.

In browser:
- Click `divide` node.
- Show node metadata and source in sidebar.

### 4.3 Trigger reactive behavior with a code edit (2:30-4:30)

Edit `divide` in Neovim:

```python
def divide(a: float, b: float) -> float:
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b
```

Save file.

What to show:
- Event stream receives `NodeChangedEvent`.
- Agent transitions (`AgentStartEvent` then `AgentCompleteEvent`).
- Node color changes in graph while running.

### 4.4 Chat with a function agent (4:30-6:30)

In web chat on selected `divide` node, ask:
- `What do you do and what depends on you?`

What to show:
- User message appears immediately in chat panel.
- Agent response appears via `AgentMessageEvent` to `user`.

### 4.5 Show cursor-following companion behavior (6:30-7:30)

In Neovim:
- Move cursor across different functions.

In browser:
- Companion panel updates to focused node.
- Camera animates and highlights focused node.

### 4.6 Close with extensibility (7:30-9:00)

Show:
- `bundles/code-agent/bundle.yaml`
- One tool script, for example `bundles/system/tools/send_message.pym`
- `contrib/neovim/remora.lua`

Point:
- Behavior is bundle/tool driven and configurable.

## 5. Live Narration Prompts

Use these concise lines during the walkthrough:

1. "Each function is a separate agent identity with its own workspace and tools."
2. "A code save emits events; subscriptions route those events to interested agents."
3. "This is not one global chatbot; it is a graph of autonomous nodes."
4. "I can message any node directly, and it can coordinate with other agents via tools."
5. "Editor cursor focus and web graph are synced live through API events."

## 6. Fallback Paths

If LLM is slow:
1. Continue narrating event flow in the event panel while waiting.
2. Reduce pressure by asking shorter prompts.

If Neovim LSP fails:
1. Continue with web-only demo: click nodes, edit file, show events and chat.

If model endpoint fails:
1. Show discovery + graph + event reactivity without chat.
2. Keep a backup recording of a successful chat sequence.

## 7. Post-Demo Wrap

Close with:
1. "Runtime is local-first and event-driven."
2. "Every code element can carry role-specific behavior through bundles/tools."
3. "This provides an extensible base for review, testing, documentation, and architecture agents."
