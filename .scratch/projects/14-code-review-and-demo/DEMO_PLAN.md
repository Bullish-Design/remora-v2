# Remora v2 — Demo Plan (5-10 Minutes)

**Title:** "Your Code is Alive: Autonomous Agent Swarm for Every Function"

---

## Table of Contents

1. [Demo Overview](#1-demo-overview)
2. [Prerequisites & Setup](#2-prerequisites--setup)
3. [Demo Script (Minute-by-Minute)](#3-demo-script-minute-by-minute)
4. [Technical Requirements & What Needs Building](#4-technical-requirements--what-needs-building)
5. [Fallback Options](#5-fallback-options)
6. [Risk Mitigation](#6-risk-mitigation)

---

## 1. Demo Overview

### Concept

The demo shows Remora transforming a small Python project into a living, breathing system of autonomous AI agents — one for every function, class, and directory. The viewer sees:

1. **Discovery**: Code is parsed, and agents materialize on a live graph
2. **LSP Integration**: Editor annotations show agent status inline
3. **Companion Sidebar**: Moving the cursor between functions updates a web-based companion panel showing the agent's understanding of that code element
4. **Live Reactivity**: Editing a function triggers an event cascade visible in real-time — agents light up, coordinate, and respond
5. **Chat**: The viewer types a question to a specific agent and gets a contextual response

### Target Emotional Arc

| Time | Beat | Feeling |
|------|------|---------|
| 0:00-1:00 | "Here's a boring Python file" | Familiarity |
| 1:00-2:30 | "Run one command and every function has its own AI agent" | Surprise |
| 2:30-4:00 | "Move your cursor — the sidebar knows what you're looking at" | Wow |
| 4:00-6:00 | "Edit a function — watch the swarm react" | Delight |
| 6:00-8:00 | "Talk to your code — it talks back and coordinates with neighbors" | Wonder |
| 8:00-10:00 | "This is extensible — add languages, tools, behaviors" | Ambition |

---

## 2. Prerequisites & Setup

### Demo Project

Create a small, self-contained Python project (~5-8 files, ~200 lines) with clear structure:

```
demo-project/
├── remora.yaml
├── bundles/
│   ├── system/
│   │   ├── bundle.yaml
│   │   └── tools/
│   ├── code-agent/
│   │   ├── bundle.yaml
│   │   └── tools/
│   └── directory-agent/
│       ├── bundle.yaml
│       └── tools/
├── src/
│   ├── calculator.py      # Simple calculator with add/subtract/multiply/divide
│   ├── validator.py        # Input validation functions
│   ├── formatter.py        # Output formatting
│   └── api.py              # Ties them together, imports the others
└── queries/
    └── python.scm
```

**Why this project:** Small enough to graph cleanly, interconnected enough to show agent coordination, understandable at a glance.

### Infrastructure

- **LLM backend**: Local Qwen3-4B via vLLM or compatible OpenAI-API server
- **Terminal**: For `remora start` command
- **VS Code**: With Remora extension installed
- **Browser**: Showing `http://localhost:8080` (Remora web UI)
- **Screen layout**: VS Code (left 50%) + Browser (right 50%)

---

## 3. Demo Script (Minute-by-Minute)

### Act 1: Discovery & The Living Graph (0:00-2:30)

**[0:00-0:30] Opening — Show the raw code**

- VS Code open with `calculator.py` visible
- "This is a simple Python project. Four files, a few functions. Nothing special."
- Quick scroll through the files

**[0:30-1:30] Start Remora — Watch the graph come alive**

- Switch to terminal, run: `remora start --project-root ./demo-project`
- Terminal shows: `Discovered 18 nodes` (functions, classes, directories)
- Switch to browser — the Sigma.js graph is populating in real-time
  - Nodes appear one by one (SSE `NodeDiscoveredEvent`)
  - Colors differentiate: blue (functions), purple (classes), teal (methods)
  - Force-directed layout settles into clusters by file
- "One command. Every function, every class, every directory now has its own autonomous AI agent."

**[1:30-2:30] Explore the graph**

- Click a function node (e.g., `calculator.add`) in the graph
- Sidebar shows: node ID, type, status, file location, source code
- Click a directory node — shows the tree structure
- "Each of these nodes is a living agent with its own workspace, tools, and memory."

### Act 2: The Companion Sidebar (2:30-4:00)

**[2:30-3:00] Switch to the editor — Show LSP integration**

- Switch to VS Code with `calculator.py` open
- CodeLens annotations visible above each function: `Remora: idle`
- Hover over a function — tooltip shows node metadata
- "Remora's LSP server annotates every discovered element right in your editor."

**[3:00-4:00] Cursor-following companion (the wow moment)**

- Move cursor to `add()` function
- Browser sidebar updates: shows companion content for `add()`
  - Agent's understanding of the function
  - Related nodes (calls, callers, siblings)
  - Recent event history for this node
- Move cursor to `divide()` function
- Sidebar smoothly transitions to `divide()`'s companion view
  - Shows different context: input validation dependencies, error handling
- "As you navigate your code, the AI companion follows along, providing contextual intelligence about wherever you are."

### Act 3: Live Reactivity (4:00-6:00)

**[4:00-5:00] Edit a function — Watch the cascade**

- In VS Code, modify `divide()` to add a zero-division check
- Save the file
- **Immediately visible:**
  - Terminal: reconciler detects change, emits `NodeChangedEvent`
  - Browser graph: `divide` node lights up orange (running)
  - SSE event log: `NodeChangedEvent` → `AgentStartEvent` → `AgentCompleteEvent`
  - Node returns to blue (idle) after processing
- "The agent saw the change, analyzed the diff, and updated its internal understanding."

**[5:00-6:00] Show the cascade effect**

- The change to `divide()` may trigger the directory agent
  - Directory node lights up briefly — it noticed a change in its subtree
- If `api.py` imports `divide`, its agent might also react (via subscription)
- Event log shows the cascade: who triggered who
- "This isn't just one agent reacting. The entire swarm coordinates. Directory agents track structural changes. Related agents update their understanding."

### Act 4: Chat with Your Code (6:00-8:00)

**[6:00-7:00] Direct conversation**

- Click on `calculator.add` in the web UI graph
- Type in chat box: "What do you do and who calls you?"
- Send → `AgentStartEvent` fires → node goes orange
- Agent processes: reads its source, checks graph edges, formulates response
- Response appears (via agent message event in SSE log)
- "You can talk to any function in your codebase. It has context about itself, its relationships, and its history."

**[7:00-8:00] Cross-agent coordination**

- Type: "Ask the validator about what inputs you should check for"
- Agent sends `AgentMessageEvent` to the validator agent
- Validator agent activates → processes → responds
- Show the event flow in the SSE log: request → delivery → response
- "Agents don't just respond to you — they coordinate with each other. This is a swarm."

### Act 5: Extensibility & Close (8:00-10:00)

**[8:00-9:00] Show the bundle system**

- Briefly show `bundles/code-agent/bundle.yaml` — system prompt, tools
- Show a `.pym` tool script — "Tools are defined in Grail, a Python-like scripting language"
- "Every agent gets these tools. You can add new tools, new behaviors, new agent roles."

**[9:00-9:30] Show multi-language support**

- "Remora isn't just Python. It uses tree-sitter queries for discovery."
- Briefly show `queries/python.scm` — "Add a query file, add a language plugin, and now your Markdown headers, TOML tables, even Go functions are agents."

**[9:30-10:00] Closing**

- Pull back to the full graph view
- "Every function in your codebase is now an autonomous agent with memory, tools, and the ability to communicate. This is Remora."

---

## 4. Technical Requirements & What Needs Building

### Tier 1: Works Today (Acts 1, 3 partial, 4, 5)

These demo segments work with the current codebase:

- `remora start` → discovery → web graph ✓
- Click node → sidebar details ✓
- Chat via web UI → agent turn → response ✓
- File edit → watchfiles → reconciler → event cascade ✓
- SSE event streaming to web UI ✓
- Bundle/tool system overview ✓

### Tier 2: Minor Additions (Act 3 polish)

| Item | Description | Effort |
|------|-------------|--------|
| Fix `rewrite_self.pym` | Change `propose_rewrite` → `apply_rewrite` | 5 min |
| Add agent response display | Show AgentMessageEvent content in web sidebar when `to_agent="user"` | 1-2 hours |
| Tune graph layout | Better initial positioning, continuous layout | 1-2 hours |

### Tier 3: New Features for Full Demo (Act 2 — Companion Sidebar)

| Item | Description | Effort |
|------|-------------|--------|
| `CursorFocusEvent` | New event type with file_path, line, node_id | 30 min |
| LSP cursor handler | Track `textDocument/didChange` or cursor notifications | 2-3 hours |
| Start LSP from CLI | Add `--lsp` flag or `remora lsp` command | 1-2 hours |
| VS Code extension | Basic extension that starts LSP + opens webview sidebar | 4-8 hours |
| Cursor → Web API | `/api/cursor` POST endpoint + SSE broadcast | 1-2 hours |
| Companion agent turn | Trigger companion content generation on cursor focus | 2-3 hours |
| Companion web UI | Sidebar component that shows companion content | 2-3 hours |
| **Subtotal** | | **13-22 hours** |

### Tier 4: Nice-to-Have Polish

| Item | Description | Effort |
|------|-------------|--------|
| Graph clustering by file | Visual file boundaries on the graph | 2-3 hours |
| Agent-to-agent message visualization | Animated edges when messages flow | 2-3 hours |
| History timeline | Scrollable event timeline with agent highlights | 3-4 hours |
| Sound effects | Subtle audio cues for agent activation | 1 hour |

---

## 5. Fallback Options

### If LLM is slow/unavailable

- Pre-seed agent workspaces with companion content
- Use a mock kernel that returns canned responses
- Lower `max_turns` to 1 for faster completion

### If VS Code extension isn't ready

- **Fallback A:** Use the web UI only. Skip the cursor-tracking companion entirely. Focus on Acts 1, 3, 4, 5.
- **Fallback B:** Use a simple script that `POST`s cursor position to `/api/cursor` on a timer, simulating cursor movement. Show the web UI responding.
- **Fallback C:** Pre-record the VS Code portion as a video clip embedded in the live demo.

### If graph layout looks messy

- Reduce to 3-4 files with 8-10 total nodes
- Use deterministic initial positions (pre-computed layout saved as JSON)

### Minimum Viable Demo (no new code)

If zero new features are built, the demo can still show:

1. `remora start` → graph populates (impressive with SSE animation)
2. Click nodes, see details
3. Edit a file → watch nodes light up
4. Chat with a function
5. Show agent-to-agent message cascade

This covers ~5 minutes and still has wow factor from the live graph + real-time reactivity.

---

## 6. Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| LLM latency ruins the live feel | Pre-warm the model. Use small model (Qwen3-4B). Set low max_turns (2). Have pre-seeded fallback. |
| Graph layout is ugly | Use small project (10-15 nodes). Pre-compute layout. Manually adjust if needed. |
| Agent gives bad/irrelevant response | Test prompts extensively beforehand. Tune bundle prompts for demo project. Have fallback responses ready. |
| VS Code extension crashes | Have the web-only demo ready as backup. |
| Watchfiles doesn't detect change fast enough | The `_on_content_changed` handler from `didSave` ensures immediate detection. Make sure to save the file explicitly. |
| SSE drops connection | Refresh browser. SSE replay parameter re-fetches recent events. |
| SQLite lock contention under demo load | Shouldn't be an issue with single-user demo. Monitor with `--log-level DEBUG`. |

---

## Appendix: Key Commands for Demo Day

```bash
# Start Remora
remora start --project-root ./demo-project --port 8080 --log-events

# Discovery only (dry run)
remora discover --project-root ./demo-project

# Web UI
open http://localhost:8080

# Watch events (alternative to web)
curl -N http://localhost:8080/sse

# Send a chat message via API
curl -X POST http://localhost:8080/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"node_id": "src/calculator.py::add", "message": "What do you do?"}'

# List nodes via API
curl http://localhost:8080/api/nodes | python -m json.tool
```

---

*End of Demo Plan*
