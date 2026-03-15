# Remora v2 Example Repo Setup Guide

> A step-by-step guide for setting up the `remora-test` example repository as a fully runnable demo of the remora-v2 library. Written for someone who doesn't know the remora internals.

---

## Table of Contents

1. [Overview](#1-overview) — What remora-v2 is and what the demo will show
2. [Prerequisites](#2-prerequisites) — What you need installed before starting
3. [Repository Layout](#3-repository-layout) — What's already in remora-test and what each piece does
4. [Step 1: Enter the Dev Shell](#4-step-1-enter-the-dev-shell) — Activate the devenv environment
5. [Step 2: Install Dependencies](#5-step-2-install-dependencies) — Sync Python packages with uv
6. [Step 3: Fix the remora.yaml Configuration](#6-step-3-fix-the-remorayaml-configuration) — Correct known config issues
7. [Step 4: Scaffold the .remora Directory](#7-step-4-scaffold-the-remora-directory) — Ensure workspace dirs exist
8. [Step 5: Start the LLM Backend](#8-step-5-start-the-llm-backend) — Get a model server running
9. [Step 6: Run Discovery](#9-step-6-run-discovery) — Verify remora can find your code nodes
10. [Step 7: Start the Full Runtime](#10-step-7-start-the-full-runtime) — Launch remora with web UI
11. [Step 8: Open the Web Dashboard](#11-step-8-open-the-web-dashboard) — See your agents in the browser
12. [Step 9: Chat with an Agent](#12-step-9-chat-with-an-agent) — Send a message and see it respond
13. [Step 10: Watch Live Events via SSE](#13-step-10-watch-live-events-via-sse) — Monitor the event stream
14. [Step 11: Edit Code and Watch Reconciliation](#14-step-11-edit-code-and-watch-reconciliation) — Trigger reactive agent behavior
15. [Step 12: Use the LSP in Neovim (Optional)](#15-step-12-use-the-lsp-in-neovim-optional) — Editor integration
16. [Troubleshooting](#16-troubleshooting) — Common problems and fixes
17. [Architecture Reference](#17-architecture-reference) — How the pieces fit together
18. [Appendix: Key API Endpoints](#18-appendix-key-api-endpoints) — REST and SSE endpoints

---

## 1. Overview

**Remora v2** is a reactive agent substrate. It takes your source code, parses it into a graph of nodes (functions, classes, methods, files, directories), and gives each node an autonomous AI agent. These agents:

- React to code changes (file edits trigger events, events trigger agents)
- Communicate with each other via message events
- Can be chatted with by humans through the web UI or LSP
- Have persistent workspaces with key-value memory
- Use tools (rewrite code, query the graph, send messages, etc.)

The **remora-test** repo is a small order-pricing Python project that serves as a demo target. By the end of this guide, you'll have remora running against it with a live web dashboard showing your agent graph, and you'll be able to chat with individual code agents.

---

## 2. Prerequisites

You need:

| Tool | Why | Install |
|------|-----|---------|
| **devenv** | Manages the Nix-based dev shell | https://devenv.sh/getting-started/ |
| **uv** | Python package manager (provided by devenv) | Comes with the shell |
| **git** | Version control | Comes with the shell |
| **An LLM server** | Agents need a model to think | See Step 5 |

The devenv shell provides Python 3.13, uv, git, and jq automatically.

**LLM options** (pick one):
- A local vLLM instance serving a Qwen model (recommended for local dev)
- Any OpenAI-compatible API (OpenAI, Anthropic proxy, Ollama, etc.)
- The machine at `remora-server:8000` if you have that configured in your network

---

## 3. Repository Layout

Here's what's already in `/home/andrew/Documents/Projects/remora-test`:

```
remora-test/
├── .git/                    # Git repo (already initialized)
├── .gitignore               # Ignores .remora/, .venv/, etc.
├── .remora/                 # Remora workspace (auto-created, gitignored)
│   ├── remora.db            # SQLite database (nodes, events, subscriptions)
│   ├── remora.log           # Runtime log file
│   ├── stable               # Stable node store snapshot
│   └── agents/              # Per-agent workspace directories
├── configs/
│   └── app.toml             # App config (not used by remora, just demo data)
├── devenv.nix               # Nix dev shell config
├── devenv.yaml              # Nix inputs
├── docs/
│   └── architecture.md      # Brief architecture notes
├── pyproject.toml           # Python project config (depends on remora)
├── README.md                # Basic readme
├── remora.yaml              # ** REMORA CONFIG ** — the key file
├── scripts/
│   └── reconcile_demo.sh    # Placeholder script
├── src/
│   ├── main.py              # Entry point for the demo app
│   ├── api/
│   │   └── orders.py        # Order creation orchestrator
│   ├── models/
│   │   └── order.py         # OrderRequest / OrderSummary dataclasses
│   ├── services/
│   │   ├── discounts.py     # Tier-based discount logic
│   │   ├── fraud.py         # Risk scoring
│   │   ├── fulfillment/
│   │   │   └── allocator.py # Warehouse allocation
│   │   ├── pricing.py       # Price computation
│   │   └── tax.py           # Tax application
│   └── utils/
│       └── money.py         # USD formatting
└── uv.lock                  # Locked dependencies
```

**What remora will discover**: Every Python function, class, and method in `src/`. Each becomes a node in the graph with its own agent.

Expected nodes include: `create_order`, `OrderRequest`, `OrderSummary`, `compute_total`, `apply_tax`, `risk_score`, `discount_for_tier`, `choose_warehouse`, `format_usd`, plus file-level and directory-level nodes.

---

## 4. Step 1: Enter the Dev Shell

```bash
cd /home/andrew/Documents/Projects/remora-test
devenv shell
```

This activates the Nix environment with Python 3.13, uv, git, and jq. You should see output like:

```
hello from devenv
git version 2.x.x
```

If you don't have devenv, you can set up a plain Python 3.13 venv instead:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install uv
```

---

## 5. Step 2: Install Dependencies

```bash
uv sync
```

This installs all dependencies from `pyproject.toml` and `uv.lock`, including remora-v2 itself. The remora package is pulled from GitHub:

```toml
# In pyproject.toml:
[tool.uv.sources]
remora = { git = "https://github.com/Bullish-Design/remora-v2.git", rev = "main" }
```

**Alternative: Use a local checkout** (faster iteration):

If you have remora-v2 checked out locally at `/home/andrew/Documents/Projects/remora-v2`, edit `pyproject.toml`:

```toml
[tool.uv.sources]
remora = { path = "../remora-v2", editable = true }
```

Then re-run `uv sync`.

**Verify the install:**

```bash
python -c "import remora; print('remora OK')"
remora --help
```

You should see the Typer help output with commands: `start`, `discover`, `lsp`.

---

## 6. Step 3: Fix the remora.yaml Configuration

The current `remora.yaml` has a config key mismatch. The file uses `bundle_mapping` but remora-v2's Config model expects `bundle_overlays`. Open and fix it:

**Current (broken):**
```yaml
bundle_mapping:
  function: code-agent
  class: code-agent
  method: code-agent
  file: code-agent
  directory: directory-agent
```

**Fixed:**
```yaml
bundle_overlays:
  function: code-agent
  class: code-agent
  method: code-agent
  file: code-agent
  directory: directory-agent
```

Here's the full corrected `remora.yaml`:

```yaml
# Remora v2 configuration for the test workspace
discovery_paths:
  - src

discovery_languages:
  - python

# Workspace
swarm_root: .remora

# Bundles — point at the remora-v2 built-in bundles
# If using a local checkout:
#   bundle_root: /home/andrew/Documents/Projects/remora-v2/bundles
# If remora is installed as a package, the bundles ship with it.
bundle_root: /home/andrew/Documents/Projects/remora-v2/bundles

# Map node types to bundle names
bundle_overlays:
  function: code-agent
  class: code-agent
  method: code-agent
  file: code-agent
  directory: directory-agent

# LLM settings — adjust for your setup
model_base_url: ${REMORA_MODEL_BASE_URL:-http://localhost:8000/v1}
model_api_key: ${REMORA_MODEL_API_KEY:-EMPTY}
model_default: ${REMORA_MODEL:-Qwen/Qwen3-4B-Instruct-2507-FP8}

# Execution limits
max_concurrency: 4
max_turns: 8
timeout_s: 300.0
max_trigger_depth: 5
trigger_cooldown_ms: 1000
```

**Understanding the key fields:**

| Field | What it does |
|-------|-------------|
| `discovery_paths` | Directories to scan for source code |
| `discovery_languages` | Only discover these languages (python, markdown, toml) |
| `swarm_root` | Where remora stores its database and agent workspaces (`.remora/`) |
| `bundle_root` | Path to the bundle definitions (system prompts + tools for each agent type) |
| `bundle_overlays` | Maps node types (function, class, etc.) to bundle names |
| `model_base_url` | OpenAI-compatible API endpoint |
| `model_default` | Which model to use |
| `max_concurrency` | Max agents running simultaneously |
| `max_turns` | Max LLM turns per agent activation |

---

## 7. Step 4: Scaffold the .remora Directory

The `.remora/` directory may already exist from a previous run. If starting fresh:

```bash
# Remove old state (optional — do this for a clean start)
rm -rf .remora

# The directory will be auto-created by remora on startup.
# But you can pre-create it:
mkdir -p .remora
```

Remora auto-creates the SQLite database (`remora.db`) and agent workspace directories on first run. The `workspace_root` config field (default: `.remora`) controls where this lives.

**Make sure `.remora/` is in `.gitignore:**

```bash
grep -q '.remora' .gitignore || echo '.remora/' >> .gitignore
```

---

## 8. Step 5: Start the LLM Backend

Agents need an LLM to think. Choose one option:

### Option A: Local vLLM (if you have a GPU)

```bash
# In a separate terminal:
vllm serve Qwen/Qwen3-4B-Instruct-2507-FP8 \
    --enable-auto-tool-choice \
    --tool-call-parser qwen3_xml \
    --max-num-seqs 32 \
    --max-model-len 32768 \
    --enable-prefix-caching
```

This serves on `http://localhost:8000/v1` (the default `model_base_url`).

### Option B: Use an existing server

If you have `remora-server` in your `/etc/hosts` or DNS:

```bash
export REMORA_MODEL_BASE_URL="http://remora-server:8000/v1"
```

### Option C: Use OpenAI API

```bash
export REMORA_MODEL_BASE_URL="https://api.openai.com/v1"
export REMORA_MODEL_API_KEY="sk-your-key-here"
export REMORA_MODEL="gpt-4o-mini"
```

### Option D: Use Ollama

```bash
# Start Ollama with a model:
ollama serve
ollama pull qwen3:4b

export REMORA_MODEL_BASE_URL="http://localhost:11434/v1"
export REMORA_MODEL="qwen3:4b"
export REMORA_MODEL_API_KEY="ollama"
```

### Verify the LLM is reachable

```bash
curl -s "${REMORA_MODEL_BASE_URL:-http://localhost:8000/v1}/models" | jq .
```

You should see a JSON response listing available models.

---

## 9. Step 6: Run Discovery

Before starting the full runtime, verify that remora can find your code:

```bash
remora discover --project-root .
```

Expected output (approximately):

```
Discovered 15 nodes
function src/api/orders.py::create_order
class    src/models/order.py::OrderRequest
class    src/models/order.py::OrderSummary
function src/services/pricing.py::compute_total
function src/services/tax.py::apply_tax
function src/services/fraud.py::risk_score
function src/services/discounts.py::discount_for_tier
function src/services/fulfillment/allocator.py::choose_warehouse
function src/utils/money.py::format_usd
file     src/main.py
file     src/api/orders.py
...
```

**What's happening**: Remora uses tree-sitter to parse every Python file under `src/`, extracting functions, classes, and methods as `CSTNode` objects. Each gets a unique `node_id` (content hash of path + name).

**If you see 0 nodes**: Check that `discovery_paths` in `remora.yaml` points to the right directory and `discovery_languages` includes `python`.

---

## 10. Step 7: Start the Full Runtime

This is the main command. It starts everything:

```bash
remora start --project-root . --port 8080 --log-level INFO --log-events
```

**What this launches:**

1. **RuntimeServices** — initializes the SQLite database, node store, event store, event bus, subscription registry, trigger dispatcher, workspace service
2. **Full discovery scan** — finds all code nodes and persists them to the database
3. **FileReconciler** (`run_forever`) — watches for file changes using `watchfiles`, re-parses changed files, emits `NodeChangedEvent`/`NodeDiscoveredEvent`/`NodeRemovedEvent`
4. **ActorPool** (`run_forever`) — polls for triggered agents and runs them (LLM turns with tools)
5. **Web server** (uvicorn + Starlette) — serves the dashboard at `http://127.0.0.1:8080`

**Flags explained:**

| Flag | What it does |
|------|-------------|
| `--project-root .` | The root of the project to analyze |
| `--port 8080` | Web dashboard port |
| `--bind 127.0.0.1` | Only listen on localhost (default) |
| `--log-level INFO` | Show info-level logs |
| `--log-events` | Print a log line for every event emitted |
| `--no-web` | (Optional) Skip the web server |
| `--lsp` | (Optional) Also start the LSP server on stdin/stdout |
| `--run-seconds N` | (Optional) Auto-shutdown after N seconds (for smoke tests) |

**Expected startup output:**

```
2026-03-14 ... INFO remora.__main__ [-:- -]: Initializing runtime services
2026-03-14 ... INFO remora.__main__ [-:- -]: Starting full discovery scan
2026-03-14 ... INFO remora.__main__ [-:- -]: Discovery complete: nodes=15 duration=0.12s
2026-03-14 ... INFO remora.__main__ [-:- -]: Event activity logging enabled
2026-03-14 ... INFO remora.__main__ [-:- -]: Starting web server on 127.0.0.1:8080
```

**Leave this running** in the terminal. Open a new terminal for the next steps.

---

## 11. Step 8: Open the Web Dashboard

Open your browser to:

```
http://127.0.0.1:8080
```

You'll see the **Remora Web Dashboard** with:

- **Force-directed graph** (Sigma.js + ForceAtlas2) showing all discovered nodes as circles, connected by edges (parent-child, caller-callee)
- **Node list** on the side — click any node to see details
- **Event feed** — live stream of system events
- **Chat interface** — send messages to individual agents

**What to look for:**

- Each Python function/class appears as a node in the graph
- Directory nodes (like `src/`, `src/services/`) connect to their child file nodes
- File nodes connect to the functions/classes they contain
- The graph should have ~15-20 nodes for the remora-test codebase

---

## 12. Step 9: Chat with an Agent

### Via the Web UI

1. Click on a node in the graph (e.g., `compute_total`)
2. In the detail panel, type a message like: "What do you do?"
3. Click Send

The message becomes an `AgentMessageEvent` in the event store. The ActorPool picks it up, activates the agent, which runs LLM turns with its tools, and responds via `send_message` back to "user".

### Via curl

```bash
# Find a node ID first:
curl -s http://127.0.0.1:8080/api/nodes | jq '.[0].node_id'

# Send a chat message (replace NODE_ID with an actual ID):
curl -X POST http://127.0.0.1:8080/api/chat \
  -H "Content-Type: application/json" \
  -d '{"node_id": "NODE_ID_HERE", "message": "What do you do?"}'
```

**Expected response:** `{"status": "sent"}`

The agent's reply will appear in the event stream (SSE) and can be fetched via the conversation endpoint:

```bash
curl -s http://127.0.0.1:8080/api/nodes/NODE_ID_HERE/conversation | jq .
```

**Rate limit**: The chat endpoint allows 10 messages per 60 seconds.

---

## 13. Step 10: Watch Live Events via SSE

Open a second terminal and connect to the SSE stream:

```bash
curl -N http://127.0.0.1:8080/sse
```

You'll see a stream of server-sent events:

```
: connected

event: AgentMessageEvent
data: {"event_type":"AgentMessageEvent","timestamp":"...","payload":{...}}

event: AgentStartEvent
data: {"event_type":"AgentStartEvent","timestamp":"...","payload":{...}}

event: AgentCompleteEvent
data: {"event_type":"AgentCompleteEvent","timestamp":"...","payload":{...}}
```

**Useful SSE parameters:**

| Parameter | Effect |
|-----------|--------|
| `?replay=50` | Replay the last 50 events before streaming live |
| `?once=true` | Return current events and disconnect (no streaming) |
| Header: `Last-Event-ID: <id>` | Resume from a specific event (for reconnection) |

**Example with replay:**

```bash
curl -N "http://127.0.0.1:8080/sse?replay=20"
```

---

## 14. Step 11: Edit Code and Watch Reconciliation

With remora running, edit a source file:

```bash
# In a separate terminal:
echo '# demo change' >> /home/andrew/Documents/Projects/remora-test/src/services/pricing.py
```

Watch the remora terminal. You should see:

1. **File change detected** by the FileReconciler (uses `watchfiles`)
2. **Re-parse** of the changed file
3. **`NodeChangedEvent`** or `ContentChangedEvent` emitted
4. **Agents triggered** — any agent subscribed to changes in that file will activate

The event will also appear in the SSE stream and in the web dashboard's event feed.

**Undo the change:**

```bash
cd /home/andrew/Documents/Projects/remora-test
git checkout src/services/pricing.py
```

---

## 15. Step 12: Use the LSP in Neovim (Optional)

Remora v2 includes an LSP server that provides CodeLens and Hover for your editor.

### Option A: Start with the main runtime

```bash
remora start --project-root . --port 8080 --lsp
```

This starts the LSP on stdin/stdout alongside the web server. Configure your editor to connect to it.

### Option B: Standalone LSP (connects to existing database)

If `remora start` is already running (and has created `.remora/remora.db`):

```bash
remora lsp --project-root .
```

This reads from the existing database without starting its own runtime.

### Neovim Configuration

Add to your Neovim config (`init.lua` or equivalent):

```lua
vim.api.nvim_create_autocmd("FileType", {
  pattern = { "python" },
  callback = function()
    vim.lsp.start({
      name = "remora",
      cmd = { "remora", "lsp", "--project-root", "/home/andrew/Documents/Projects/remora-test" },
      root_dir = vim.fs.root(0, { "remora.yaml", ".git" }),
    })
  end,
})
```

**What you get:**
- **Code lenses** above each function/class showing `"Remora: idle"` (or current status)
- **Hover** info showing node ID, type, status, and file location

---

## 16. Troubleshooting

### "No module named 'remora'"
Run `uv sync` again. Make sure you're in the devenv shell or have the venv activated.

### "Database not found" when running `remora lsp`
The standalone LSP needs `remora start` to have run first (to create `.remora/remora.db`). Either start the full runtime first, or use `remora start --lsp` to run both together.

### Agents don't respond to chat
- Check the LLM server is running and reachable: `curl $REMORA_MODEL_BASE_URL/models`
- Check remora logs in `.remora/remora.log`
- Ensure `bundle_root` points to a directory containing `system/bundle.yaml` and `code-agent/bundle.yaml`
- Use `--log-events` to see if events are being emitted

### "bundle_mapping" not recognized
Rename `bundle_mapping` to `bundle_overlays` in `remora.yaml`. This is a v1→v2 naming change.

### Graph shows no edges
Edges are discovered from code analysis (caller/callee relationships, parent/child containment). If you only see nodes with no connections, the tree-sitter queries may not have extracted relationships. Check `remora discover` output.

### Port already in use
Change the port: `remora start --port 8081`

### Old .remora state causing issues
Delete and re-run:
```bash
rm -rf .remora
remora start --project-root . --port 8080
```

### SSE stream disconnects
The SSE endpoint supports automatic reconnection via `Last-Event-ID`. If using `curl`, it won't auto-reconnect — use EventSource in the browser or a proper SSE client.

---

## 17. Architecture Reference

```
┌─────────────────────────────────────────────────┐
│                   remora start                   │
│                                                  │
│  ┌──────────┐  ┌───────────┐  ┌──────────────┐  │
│  │ Discovery │  │ Reconciler│  │   ActorPool  │  │
│  │ (CST)    │──│ (watchfiles)│─│  (LLM turns) │  │
│  └──────────┘  └───────────┘  └──────────────┘  │
│       │              │               │           │
│       ▼              ▼               ▼           │
│  ┌─────────────────────────────────────────┐     │
│  │           SQLite Database               │     │
│  │  ┌──────────┐ ┌──────────┐ ┌─────────┐ │     │
│  │  │NodeStore │ │EventStore│ │SubsReg  │ │     │
│  │  └──────────┘ └──────────┘ └─────────┘ │     │
│  └─────────────────────────────────────────┘     │
│       │              │               │           │
│       ▼              ▼               ▼           │
│  ┌──────────┐  ┌───────────┐  ┌──────────────┐  │
│  │ EventBus │──│ Trigger   │──│   Cairn      │  │
│  │ (pub/sub)│  │ Dispatcher│  │ Workspaces   │  │
│  └──────────┘  └───────────┘  └──────────────┘  │
│       │                                          │
│       ▼                                          │
│  ┌──────────────────────────────────────────┐    │
│  │         Web Server (Starlette)           │    │
│  │  REST API + SSE + Static Files (Sigma.js)│    │
│  └──────────────────────────────────────────┘    │
│       │                                          │
│  ┌──────────────────────────────────────────┐    │
│  │         LSP Server (pygls) [optional]    │    │
│  │  CodeLens + Hover + didSave/Open/Close   │    │
│  └──────────────────────────────────────────┘    │
└─────────────────────────────────────────────────┘
```

**Data flow:**

1. **Discovery** parses files with tree-sitter → `CSTNode` objects
2. **Reconciler** compares CSTNodes to stored Nodes → emits `NodeDiscoveredEvent`, `NodeChangedEvent`, `NodeRemovedEvent`
3. **EventStore** persists events to SQLite, notifies **EventBus**
4. **TriggerDispatcher** matches events against **SubscriptionRegistry** → identifies which agents to trigger
5. **ActorPool** creates **Actor** instances for triggered agents → runs LLM turns with tools
6. **Actors** use tools (from bundles: `send_message`, `query_agents`, `rewrite_self`, etc.) → these emit more events → cycle continues
7. **Web server** exposes REST APIs for nodes/edges/events + SSE for live streaming
8. **LSP server** provides CodeLens/Hover by querying NodeStore

**Key concepts:**

| Concept | What it is |
|---------|-----------|
| **Node** | A code element (function, class, method, file, directory) with a unique ID |
| **Agent** | An LLM-powered actor attached to a Node, with its own workspace and tools |
| **Bundle** | A package defining an agent's system prompt and available tools (e.g., `code-agent/`) |
| **Event** | A timestamped message in the event store (AgentMessage, NodeChanged, etc.) |
| **Subscription** | A pattern that matches events to trigger an agent (by event type, source, path glob) |
| **Grail tool** | A `.pym` script that defines a tool an agent can call (Python with a special header) |
| **Cairn workspace** | Per-agent persistent storage directory with key-value memory |

---

## 18. Appendix: Key API Endpoints

### REST APIs

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Web dashboard (HTML) |
| GET | `/api/nodes` | List all discovered nodes |
| GET | `/api/nodes/{node_id}` | Get a specific node |
| GET | `/api/edges` | List all edges |
| GET | `/api/nodes/{node_id}/edges` | Get edges for a specific node |
| GET | `/api/nodes/{node_id}/conversation` | Get an agent's conversation history |
| POST | `/api/chat` | Send a message to an agent (`{"node_id": "...", "message": "..."}`) |
| GET | `/api/events?limit=50` | Get recent events (max 500) |
| GET | `/api/health` | Health check with node count and metrics |
| POST | `/api/cursor` | Report cursor position (`{"file_path": "...", "line": N, "character": N}`) |

### SSE Stream

| Endpoint | Description |
|----------|-------------|
| GET `/sse` | Live event stream |
| GET `/sse?replay=N` | Replay last N events then stream live |
| GET `/sse?once=true` | Return events and disconnect |
| Header: `Last-Event-ID` | Resume from a specific event ID |

### Quick Test Script

```bash
#!/usr/bin/env bash
# test_remora.sh — Quick smoke test for the running remora instance
set -euo pipefail

BASE="http://127.0.0.1:8080"

echo "=== Health ==="
curl -s "$BASE/api/health" | jq .

echo ""
echo "=== Nodes ==="
NODES=$(curl -s "$BASE/api/nodes")
echo "$NODES" | jq 'length'
echo "First node:"
echo "$NODES" | jq '.[0]'

echo ""
echo "=== Edges ==="
curl -s "$BASE/api/edges" | jq 'length'

echo ""
echo "=== Recent Events ==="
curl -s "$BASE/api/events?limit=5" | jq 'length'

echo ""
echo "=== Chat Test ==="
NODE_ID=$(echo "$NODES" | jq -r '.[0].node_id')
echo "Sending message to node: $NODE_ID"
curl -s -X POST "$BASE/api/chat" \
  -H "Content-Type: application/json" \
  -d "{\"node_id\": \"$NODE_ID\", \"message\": \"What do you do?\"}" | jq .

echo ""
echo "Done! Check the web dashboard at $BASE"
```

Save this as `scripts/test_remora.sh`, make it executable (`chmod +x scripts/test_remora.sh`), and run it to verify everything works.

---

*Guide written for remora-v2 v0.5.0 against the remora-test example workspace.*
