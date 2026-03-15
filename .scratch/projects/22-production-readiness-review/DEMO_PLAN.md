# Remora v2 — Demo Plan (Neovim + Web UI)

**Title:** "Your Code is Alive: Every Function is an Autonomous Agent"
**Duration:** 8-10 minutes
**Audience:** Technical (AI-knowledgeable) + Business stakeholders
**Setup:** Single machine, local vLLM on tailnet, neovim + browser side-by-side

---

## Table of Contents

1. [Demo Concept & Emotional Arc](#1-demo-concept--emotional-arc)
2. [Hardware & Software Setup](#2-hardware--software-setup)
3. [Demo Project](#3-demo-project)
4. [Demo Script (Minute-by-Minute)](#4-demo-script-minute-by-minute)
5. [Technical Prerequisites](#5-technical-prerequisites)
6. [What Needs Building](#6-what-needs-building)
7. [Pre-Demo Checklist](#7-pre-demo-checklist)
8. [Fallback Options](#8-fallback-options)
9. [Risk Mitigation](#9-risk-mitigation)
10. [Key Commands](#10-key-commands)

---

## 1. Demo Concept & Emotional Arc

### The Core Story

"What if every function in your codebase had its own AI agent — watching, understanding, and ready to help? Not a monolithic chatbot that searches your code, but a living network of specialized agents, each one an expert on exactly one piece of your system."

The demo makes this tangible. The audience sees code transform from static text into a living graph. They watch agents wake up, react to changes, and talk to each other. They ask a function a question and it answers with deep contextual knowledge.

### Why This Wows

**Business audience:** "Imagine onboarding a new engineer. Instead of reading docs for a week, they open their editor and every function can explain itself, its relationships, and its history. That's what Remora does."

**Technical audience:** "This isn't RAG over your codebase. Each agent has its own persistent workspace, tools, and memory. They're autonomous — they react to changes without being asked, coordinate with each other, and maintain their own understanding over time. It's a swarm, not a search engine."

### Emotional Arc

| Time | Beat | Audience Feeling |
|------|------|-----------------|
| 0:00-1:30 | "Here's an ordinary Python project in neovim" | Familiarity |
| 1:30-3:00 | "One command — every function is now an autonomous agent" | Surprise, curiosity |
| 3:00-4:30 | "Watch: I edit a function, and the swarm reacts in real-time" | Delight, engagement |
| 4:30-6:30 | "I can talk to any function. It knows its context, its callers, its history." | Wonder |
| 6:30-8:00 | "Agents coordinate — ask one about another, and they communicate" | Insight, vision |
| 8:00-9:00 | "This is extensible — any language, any tools, any behavior" | Ambition |
| 9:00-10:00 | "This is Remora. Your code, alive." | Inspiration |

---

## 2. Hardware & Software Setup

### Machine Layout

```
┌─────────────────────────────────────────────────────────────┐
│                     Demo Machine                             │
│                                                              │
│  ┌──────────────────────┐  ┌──────────────────────────────┐ │
│  │     Neovim (Left)    │  │      Browser (Right)         │ │
│  │                      │  │                               │ │
│  │  calculator.py       │  │  ┌─────────────┬───────────┐ │ │
│  │  with CodeLens:      │  │  │ Agent Graph │ Sidebar   │ │ │
│  │                      │  │  │ (Sigma.js)  │ ┌───────┐ │ │ │
│  │  Remora: idle        │  │  │             │ │ Node  │ │ │ │
│  │  def add(a, b):      │  │  │   ● ─── ●  │ │ Info  │ │ │ │
│  │      return a + b    │  │  │  /       \  │ │       │ │ │ │
│  │                      │  │  │ ●    ●    ● │ │ Chat  │ │ │ │
│  │  Remora: idle        │  │  │  \  / \  /  │ │       │ │ │ │
│  │  def subtract(a, b): │  │  │   ● ─── ●  │ │Events │ │ │ │
│  │      return a - b    │  │  │             │ └───────┘ │ │ │
│  │                      │  │  └─────────────┴───────────┘ │ │
│  └──────────────────────┘  └──────────────────────────────┘ │
│                                                              │
│  ┌──────────────────────────────────────────────────────────┐│
│  │  Terminal (Bottom): remora start output + event log      ││
│  └──────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘

Remote (Tailnet):
┌────────────────────┐
│  vLLM Server       │
│  Qwen3-4B-Instruct │
│  :8000/v1          │
└────────────────────┘
```

### Software Requirements

| Component | Version | Purpose |
|-----------|---------|---------|
| Neovim | 0.10+ | Editor with built-in LSP client |
| Python | 3.13+ | Runtime |
| Remora | 0.5.0+ | Agent substrate |
| vLLM | Latest | Local LLM serving |
| Qwen3-4B-Instruct | FP8 or similar | Small, fast model for demo speed |
| Browser | Any modern | Web UI display |
| tmux/wezterm | Any | Split terminal layout |

### Neovim Configuration

```lua
-- ~/.config/nvim/lua/remora.lua

-- LSP client for Remora
vim.api.nvim_create_autocmd("FileType", {
  pattern = {"python", "markdown", "toml"},
  callback = function()
    local root = vim.fs.root(0, {"remora.yaml"})
    if not root then return end
    vim.lsp.start({
      name = "remora",
      cmd = {"remora", "lsp", "--project-root", root},
      root_dir = root,
    })
  end,
})

-- Auto-refresh CodeLens on save
vim.api.nvim_create_autocmd({"BufWritePost", "BufEnter"}, {
  callback = function()
    vim.lsp.codelens.refresh()
  end,
})

-- Cursor tracking → Remora web API (for companion panel)
local cursor_timer = nil
vim.api.nvim_create_autocmd({"CursorHold", "CursorHoldI"}, {
  callback = function()
    if cursor_timer then
      cursor_timer:stop()
    end
    cursor_timer = vim.defer_fn(function()
      local cursor = vim.api.nvim_win_get_cursor(0)
      local file = vim.api.nvim_buf_get_name(0)
      if file == "" then return end
      vim.fn.jobstart({
        "curl", "-s", "-X", "POST",
        "http://localhost:8080/api/cursor",
        "-H", "Content-Type: application/json",
        "-d", vim.fn.json_encode({
          file_path = file,
          line = cursor[1],
          character = cursor[2],
        }),
      }, {detach = true})
    end, 0)
  end,
})
```

---

## 3. Demo Project

A purpose-built Python project: small enough to graph cleanly, interconnected enough to show agent coordination, immediately understandable.

```
demo-project/
├── remora.yaml
├── bundles/
│   ├── system/         (from remora-v2, symlinked or copied)
│   ├── code-agent/
│   └── directory-agent/
├── queries/
│   └── python.scm      (from remora-v2)
└── src/
    ├── calculator.py    # Core math: add, subtract, multiply, divide
    ├── validator.py     # Input validation: is_number, check_divisor
    ├── formatter.py     # Output formatting: format_result, format_error
    └── api.py           # Orchestrator: calculate(op, a, b) imports all others
```

**~120 lines total, ~12-15 discovered nodes, 4 files, clear call relationships.**

### Why This Project Works

- **Instantly understandable** — everyone knows what a calculator does
- **Natural relationships** — `api.py` imports the others, `divide` calls `check_divisor`
- **Perfect for live editing** — adding a zero-division check to `divide()` is a natural, small change
- **Good graph topology** — star pattern (api → others) with cross-file edges

### `calculator.py`

```python
"""Core calculator operations."""


def add(a: float, b: float) -> float:
    """Add two numbers."""
    return a + b


def subtract(a: float, b: float) -> float:
    """Subtract b from a."""
    return a - b


def multiply(a: float, b: float) -> float:
    """Multiply two numbers."""
    return a * b


def divide(a: float, b: float) -> float:
    """Divide a by b."""
    return a / b
```

### `validator.py`

```python
"""Input validation utilities."""


def is_number(value) -> bool:
    """Check if a value can be used as a number."""
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def check_divisor(b: float) -> bool:
    """Check that a divisor is not zero."""
    return b != 0
```

### `formatter.py`

```python
"""Output formatting for calculator results."""


def format_result(operation: str, a: float, b: float, result: float) -> str:
    """Format a calculation result for display."""
    return f"{a} {operation} {b} = {result}"


def format_error(operation: str, error: str) -> str:
    """Format an error message for display."""
    return f"Error in {operation}: {error}"
```

### `api.py`

```python
"""Calculator API — ties together validation, computation, and formatting."""

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
    """Perform a calculation with validation and formatting."""
    if not is_number(a) or not is_number(b):
        return format_error(operation, "Invalid input")

    a, b = float(a), float(b)

    if operation == "divide" and not check_divisor(b):
        return format_error(operation, "Division by zero")

    func = OPERATIONS.get(operation)
    if func is None:
        return format_error(operation, f"Unknown operation: {operation}")

    result = func(a, b)
    return format_result(operation, a, b, result)
```

### `remora.yaml` (for demo project)

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

**Key demo tuning:**
- `max_turns: 4` — keeps agent responses fast
- `timeout_s: 120.0` — generous for cold model starts
- `trigger_cooldown_ms: 2000` — prevents cascading overwhelm during live editing

---

## 4. Demo Script (Minute-by-Minute)

### Act 1: "Here's Some Ordinary Code" (0:00-1:30)

**[0:00-0:30] Opening — Set the scene**

*Neovim is open with `calculator.py` visible. Browser shows an empty Remora page. Terminal is visible at the bottom.*

> "This is a simple Python project. Four files — a calculator, a validator, a formatter, and an API that ties them together. Twelve functions. Nothing special."

- Quickly scroll through files in neovim: `calculator.py`, `validator.py`, `api.py`
- Pause on `divide()` — "This function has a bug. We'll come back to that."

**[0:30-1:30] Start Remora — The moment of transformation**

- Switch to terminal:
  ```
  remora start --project-root ./demo-project --port 8080 --log-events
  ```
- Terminal output scrolls:
  ```
  Discovered 15 nodes
  Starting web server on 0.0.0.0:8080
  Event activity logging enabled
  ```
- Switch to browser — the graph is already populating
  - Nodes appear as colored dots: blue (functions), teal (methods), gray (directories)
  - Force-directed layout pulls them into clusters
  - Labels appear: `add`, `subtract`, `multiply`, `divide`, `calculate`, ...

> "One command. Every function, every class, every directory in this project now has its own autonomous AI agent. Each one has its own workspace, tools, and memory."

*Pause for effect. Let the graph settle.*

### Act 2: "The Code Knows Itself" (1:30-3:00)

**[1:30-2:00] Neovim CodeLens**

- Switch to neovim with `calculator.py`
- Point out the CodeLens annotations above each function:
  ```
  Remora: idle
  def add(a, b):
  ```

> "Back in the editor, Remora's LSP server annotates every discovered element. These aren't just decorations — they reflect the live state of each agent."

**[2:00-2:30] Hover for context**

- Hover cursor over `divide()` — a tooltip appears:
  ```
  ### calculator.divide
  - Node ID: `/path/to/src/calculator.py::divide`
  - Type: function
  - Status: idle
  - File: src/calculator.py:16-18
  ```

> "Hover over any function and you see its agent identity — the node ID, its type, its current status."

**[2:30-3:00] Graph exploration**

- Click `calculator.add` node in the web graph
- Sidebar shows: source code, type, status, file location

> "Each of these nodes is a living agent. It has its own sandboxed filesystem, a KV store for memory, and a toolkit specific to its role. A function agent can rewrite its own source. A directory agent can coordinate its children."

### Act 3: "Watch the Swarm React" (3:00-5:00)

**[3:00-3:30] Set up the edit**

> "Remember that `divide()` function with the bug? Let's fix it. Watch the graph while I edit."

- Position browser graph prominently
- In neovim, navigate to `divide()`:
  ```python
  def divide(a: float, b: float) -> float:
      """Divide a by b."""
      return a / b
  ```

**[3:30-4:30] The live edit — the money shot**

- Edit `divide()` to add a zero-division check:
  ```python
  def divide(a: float, b: float) -> float:
      """Divide a by b, with zero-division protection."""
      if b == 0:
          raise ValueError("Cannot divide by zero")
      return a / b
  ```
- **Save the file (`:w`)**
- **Immediately visible in the browser:**
  - The `divide` node flashes **orange** (AgentStartEvent — the agent is processing)
  - Terminal shows: `NodeChangedEvent → AgentStartEvent → ...tools executing... → AgentCompleteEvent`
  - After 2-5 seconds, `divide` returns to **blue** (idle)
  - The `src` directory node briefly flashes orange too — it noticed a subtree change

> "The agent saw the change, analyzed the diff, and updated its internal understanding. And look — the directory agent noticed too. This isn't one agent reacting. The swarm coordinates."

**[4:30-5:00] Show the event cascade**

- Point to the events panel in the web UI:
  ```
  AgentCompleteEvent: src/calculator.py::divide
  AgentStartEvent: src/calculator.py::divide
  NodeChangedEvent: src/calculator.py::divide
  ```

> "You can see the full event cascade in the log. Node changed, agent started, agent completed. Every event is persisted, timestamped, and correlated."

### Act 4: "Talk to Your Code" (5:00-7:00)

**[5:00-5:30] Start a conversation**

- Click on `calculator.divide` in the web graph
- Type in the chat box: **"What do you do and who depends on you?"**
- Click Send

**[5:30-6:00] Watch the agent think**

- `divide` node goes **orange** in the graph
- Terminal shows the agent's tool calls:
  ```
  Tool start: query_agents
  Tool start: send_message
  ```
- After a few seconds, the response appears in the chat panel:

> *"I'm the divide function in calculator.py. I take two floats and return their quotient, with zero-division protection. The calculate() function in api.py calls me when the operation is 'divide'. The check_divisor() function in validator.py is my safety partner — api.py checks divisors before calling me."*

> "You can talk to any function in your codebase. It has context about itself, its relationships, and its history. This isn't RAG — the agent used its tools to inspect the graph, find its callers, and formulate a contextual response."

**[6:00-7:00] Cross-agent coordination**

- Type: **"Ask the validator if there are any edge cases you should know about"**
- Send

- `divide` goes orange → sends a message → `check_divisor` goes orange
- Two agents communicate, then `divide` responds:

> *"I asked check_divisor about edge cases. It noted that it currently only checks for exactly zero — but negative zero, NaN, and infinity are technically valid float values that could cause unexpected behavior. I should consider adding checks for those."*

> "Agents don't just respond to you — they coordinate with each other. The divide agent sent a message to the validator, the validator processed it, and the divide agent synthesized both perspectives. This is a swarm."

### Act 5: "Extensible by Design" (7:00-9:00)

**[7:00-7:45] Show the bundle system**

- In neovim, open `bundles/code-agent/bundle.yaml`:
  ```yaml
  name: code-agent
  system_prompt_extension: |
    You are an autonomous AI agent embodying a code element...
  ```

> "Every agent gets its behavior from bundles — YAML configs with system prompts and tool definitions. You can create new agent roles, new tools, new behaviors — all without touching Remora's core."

- Show a `.pym` tool script:
  ```python
  from grail import Input, external

  new_source: str = Input("new_source")

  @external
  async def apply_rewrite(new_source: str) -> bool: ...

  success = await apply_rewrite(new_source)
  ```

> "Tools are written in Grail — a Python dialect designed for agent tool scripts. Each tool gets access to workspace, graph, and event capabilities through injected externals."

**[7:45-8:30] Multi-language support**

> "Remora isn't just Python."

- Show `queries/python.scm` briefly:
  ```scheme
  (function_definition name: (identifier) @node.name) @node
  ```

> "Discovery uses tree-sitter with language-specific query files. Python, Markdown, TOML are built in. Add a query file for any tree-sitter grammar — Go, Rust, TypeScript, even your config files — and those elements become agents too."

**[8:30-9:00] The vision**

> "Think about what this means. Your Markdown documentation headers are agents that can update themselves when the code changes. Your TOML config sections are agents that validate their own values. Every structural element in your project can be intelligent and autonomous."

### Act 6: Close (9:00-10:00)

- Pull back to the full graph view in the browser
- All nodes are blue (idle), the graph is settled

> "Every function in this codebase is now an autonomous agent with memory, tools, and the ability to communicate. They watch for changes, maintain their own understanding, and coordinate as a swarm."

> "This runs on your local machine, with your local LLM. No data leaves your network. No cloud dependency. Your code, alive."

> "This is Remora."

---

## 5. Technical Prerequisites

### Before Demo Day

| Item | Command | Expected |
|------|---------|----------|
| vLLM running on tailnet | `curl http://remora-server:8000/v1/models` | Model listed |
| Remora installed | `remora --help` | CLI help text |
| Demo project set up | `ls demo-project/src/` | 4 Python files |
| Neovim LSP configured | Open .py file, `:LspInfo` | remora attached |
| Neovim helper copied | `ls ~/.config/nvim/lua/remora.lua` | file exists |
| Web UI accessible | `curl http://localhost:8080/` | HTML response |
| Bundles copied | `ls demo-project/bundles/` | system, code-agent, directory-agent |
| Queries available | `ls demo-project/queries/` | python.scm |

### Pre-Warm Checklist

1. Start vLLM server, send a test prompt to warm the model
2. Run `remora start` once against the demo project to populate workspaces
3. Send a test chat message to verify LLM connectivity
4. Stop Remora, clean `.remora/` for a fresh demo start
5. Test the full demo flow once end-to-end

---

## 6. What Needs Building

### Tier 1: Must Have for Any Demo (~5 hours)

| # | Item | Description | Effort |
|---|------|-------------|--------|
| 1 | **Chat response display** | Web UI shows AgentMessageEvent content when `to_agent="user"` in a chat-like panel | 2-3 hrs |
| 2 | **Fix agent response truncation** | Remove 200-char limit on AgentCompleteEvent.result_summary | 30 min |
| 3 | **Fix LSP logging conflict** | Redirect log output to stderr/file when `--lsp` active | 30 min |
| 4 | **Fix `remora.yaml` directory overlay** | Add `directory: "directory-agent"` to bundle_overlays | 5 min |
| 5 | **Add `--bind` option** | Allow web server to bind to 0.0.0.0 for tailnet | 30 min |
| 6 | **Fix `rewrite_self.pym`** | Distinct success/failure messages | 10 min |

### Tier 2: Needed for Full Neovim Demo (~8 hours)

| # | Item | Description | Effort |
|---|------|-------------|--------|
| 7 | **`remora lsp` standalone command** | Run LSP server connecting to shared SQLite | 3-4 hrs |
| 8 | **Neovim LSP config** | Documented config with CodeLens, hover | 1-2 hrs |
| 9 | **`/api/cursor` endpoint** | Accept cursor position POST, broadcast CursorFocusEvent via SSE | 1-2 hrs |
| 10 | **Web companion panel** | Show focused node's context when CursorFocusEvent fires | 2-3 hrs |

### Tier 3: Wow Factor Polish (~8 hours)

| # | Item | Description | Effort |
|---|------|-------------|--------|
| 11 | **Neovim cursor tracking** | CursorHold autocmd → POST /api/cursor | 1 hr |
| 12 | **Graph clustering by file** | Visual grouping of nodes from same file | 2-3 hrs |
| 13 | **Tool descriptions** | Extract from Grail scripts for better LLM tool selection | 2 hrs |
| 14 | **LLM retry logic** | Single retry with backoff for transient failures | 1 hr |
| 15 | **Prompt tuning** | Optimize bundle prompts for demo project + Qwen3-4B | 2 hrs |

### Minimum Viable Demo (Tier 1 only)

With only Tier 1 complete (~5 hours), the demo can show:
1. `remora start` → graph populates (Acts 1)
2. Click nodes, see details (Act 2 partial — no cursor tracking)
3. Edit a file → watch agents light up and cascade (Act 3)
4. Chat with a function → see the response (Act 4)
5. Show bundles and multi-language (Act 5)

This covers ~7 minutes and delivers strong wow factor from the live graph + reactivity + visible chat responses. **The neovim LSP integration becomes a bonus rather than a requirement.**

---

## 7. Pre-Demo Checklist

### T-1 Day

- [ ] Full end-to-end rehearsal
- [ ] vLLM model warmed and responsive (< 3s for short prompts)
- [ ] Demo project bundles tuned — test all prompts manually
- [ ] Screen layout arranged and tested (neovim left, browser right, terminal bottom)
- [ ] Backup plan ready (pre-recorded video of each act)
- [ ] Chat responses verified — agent replies are coherent and on-topic

### T-1 Hour

- [ ] Start vLLM server, verify `curl http://remora-server:8000/v1/models`
- [ ] Send warm-up prompt: `curl -X POST http://remora-server:8000/v1/chat/completions ...`
- [ ] Clean demo project: `rm -rf demo-project/.remora`
- [ ] Open neovim with `calculator.py`
- [ ] Open browser to `http://localhost:8080` (will show empty until remora starts)
- [ ] Terminal ready with `remora start` command pre-typed

### T-0 (Go Time)

- [ ] Deep breath
- [ ] Hit enter on `remora start`
- [ ] Watch the graph populate
- [ ] Follow the script

---

## 8. Fallback Options

### If LLM is slow (> 10s per response)

- **Option A:** Reduce `max_turns` to 2 in bundle configs
- **Option B:** Pre-seed agent workspaces with cached tool results
- **Option C:** Use a mock kernel that returns pre-written responses for known prompts
- **Strategy:** Time the responses in rehearsal. If > 5s, fill the silence by narrating what the agent is doing: "You can see in the terminal — the agent is inspecting the graph, checking its neighbors..."

### If LLM gives bad responses

- **Option A:** Tune prompts extensively with the specific model beforehand
- **Option B:** Have a fallback demo project with pre-tested prompts that reliably produce good output
- **Option C:** Use the event log to narrate the *process* even if the specific response isn't perfect: "The important thing isn't the specific answer — it's that the agent used its tools, inspected the graph, and formulated a contextual response."

### If Neovim LSP doesn't work

- **Fallback:** Use web UI only. Skip Acts involving CodeLens and cursor tracking. The web UI chat + graph + live reactivity still makes a compelling 7-minute demo.
- **Recovery:** If LSP crashes mid-demo, smoothly switch to "let me show you the web interface" and continue with the graph.

### If Graph layout looks messy

- **Option A:** Use `data-sigma-iterations="100"` for more layout settling time
- **Option B:** Reduce to 3 files / ~8 nodes
- **Option C:** Pre-compute layout positions and hardcode as initial node positions

### If SSE drops

- Refresh browser — SSE replay parameter fetches recent events
- The graph state is fetched from `/api/nodes` on page load regardless of SSE

---

## 9. Risk Mitigation

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| LLM latency ruins live feel | Medium | High | Pre-warm model. Use small model (4B). Low max_turns. Have pre-written fallback. Fill silence with narration. |
| Agent gives incoherent response | Medium | High | Extensive prompt testing with demo project. Fallback responses ready. Narrate the process, not just the output. |
| Neovim LSP crashes | Low | Medium | Web-only fallback is complete and tested. |
| Watchfiles misses a change | Low | Low | Save explicitly with `:w`. The LSP `didSave` handler also triggers reconciliation. |
| SQLite lock under demo load | Very Low | Medium | Single-user, single-connection. WAL mode handles concurrent reads. |
| vLLM server unreachable | Low | Critical | Test connectivity 5 min before demo. Have the model running locally as backup. |
| Browser crashes | Very Low | Medium | Refresh recovers full state (nodes from API, events from replay). |
| Network issues with tailnet | Low | Critical | Have vLLM running on the same machine as backup. Change `model_base_url` to `localhost`. |

---

## 10. Key Commands

```bash
# Start Remora
remora start --project-root ./demo-project --port 8080 --bind 0.0.0.0 --log-events

# Discovery dry-run
remora discover --project-root ./demo-project

# Web UI
open http://localhost:8080

# Watch events (alternative to web UI)
curl -N http://localhost:8080/sse

# Send a chat message via API
curl -X POST http://localhost:8080/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"node_id": "src/calculator.py::divide", "message": "What do you do?"}'

# List nodes via API
curl http://localhost:8080/api/nodes | python -m json.tool

# Check vLLM status
curl http://remora-server:8000/v1/models

# Test LLM connectivity
curl -X POST http://remora-server:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model": "Qwen/Qwen3-4B-Instruct-2507-FP8", "messages": [{"role": "user", "content": "Hello"}], "max_tokens": 50}'
```

---

*End of Demo Plan*
