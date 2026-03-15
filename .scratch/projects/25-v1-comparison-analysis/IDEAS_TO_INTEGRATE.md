# Ideas from Remora v1 Worth Integrating into v2

> Good ideas and patterns discovered in the v1 codebase and concept document that would enhance remora-v2.

---

## Table of Contents

1. [Critical: Web Agent Panel (Browser Sidebar)](#1-critical-web-agent-panel-browser-sidebar)
2. [Critical: Human-in-the-Loop Events](#2-critical-human-in-the-loop-events)
3. [Critical: Rewrite Proposal Workflow](#3-critical-rewrite-proposal-workflow)
4. [High: LSP Code Actions](#4-high-lsp-code-actions)
5. [High: Rich Hover with Graph Context](#5-high-rich-hover-with-graph-context)
6. [High: Cursor-Driven Panel Sync](#6-high-cursor-driven-panel-sync)
7. [Medium: Tags on Subscription Patterns](#7-medium-tags-on-subscription-patterns)
8. [Medium: Extension Config System](#8-medium-extension-config-system)
9. [Medium: Kernel Events as First-Class](#9-medium-kernel-events-as-first-class)
10. [Medium: UI State Projector](#10-medium-ui-state-projector)
11. [Low: Event Replay Endpoint](#11-low-event-replay-endpoint)
12. [Low: Agent Status Icons](#12-low-agent-status-icons)
13. [Low: Per-Agent Event Caching](#13-low-per-agent-event-caching)
14. [Implementation Priority Order](#14-implementation-priority-order)

---

## 1. Critical: Web Agent Panel (Browser Sidebar)

### What v1 Had

v1's Neovim panel (`panel.lua`, 1131 lines) was a full agent interaction surface:

```
┌─── Agent ────────────────────────┐
│  get_user                        │
│  Type: function  Status: idle    │
│  Lines: 15-28                    │
│                                  │
│ ▶ Tools (5)  [t to toggle]      │
│                                  │
│ ─── Chat ────────────────────    │
│  You         12:01:03            │
│    Add error handling for        │
│    network timeouts              │
│                                  │
│  Agent       12:01:05            │
│    I'll add a try/except with    │
│    a configurable timeout...     │
│                                  │
│  ✎ Rewrite proposal  12:01:06   │
│    + try:                        │
│    +     response = requests...  │
│    - response = requests.get...  │
│                                  │
│ [q] close [t] tools [⏎] send    │
├──────────────────────────────────┤
│  Message agent...                │
│                                  │
└──────────────────────────────────┘
```

### What v2 Should Build

A browser-based panel that provides the same experience. This is the **single most important feature** to add to v2. The web UI already has the SSE infrastructure and REST APIs; it needs the front-end panel.

### Implementation Approach

Extend `index.html` (or create a separate panel view) with:

1. **Agent Detail Panel** (replaces current basic sidebar):
   - Agent name, type, status with colored status indicator
   - File path and line range
   - Parent node link
   - Collapsible tools section showing available Grail tools

2. **Chat History Section**:
   - Per-agent message history (scrollable)
   - Event-type-specific rendering:
     - User messages (blue)
     - Agent responses (green)
     - Tool call results (grey, compact)
     - Error events (red)
     - Proposal diffs (+/- coloring)
   - Timestamp on each event

3. **Message Input**:
   - Text input at the bottom of the panel
   - Send button (or Enter to send)
   - POSTs to `/api/chat` endpoint

4. **Human Input Response**:
   - When agent requests input, display the question prominently
   - Show options if provided
   - Input field for response
   - Submit sends back via API

### New API Endpoints Needed

```
GET  /api/nodes/{node_id}/events?limit=50  → Per-agent event history
POST /api/nodes/{node_id}/respond          → Submit human input response
GET  /api/nodes/{node_id}/tools            → List available tools for agent
POST /api/nodes/{node_id}/trigger          → Manually trigger agent
```

### Key Design Decision

The panel should work with SSE for real-time updates. When viewing agent X:
- Subscribe to SSE with a filter for events where `agent_id == X`
- New events append to the chat history in real-time
- No polling needed

---

## 2. Critical: Human-in-the-Loop Events

### What v1 Had

Two event types enabling agents to ask humans for input:

```python
class HumanInputRequestEvent:
    agent_id: str
    request_id: str
    question: str
    options: list[str]  # Optional choices

class HumanInputResponseEvent:
    request_id: str
    response: str
```

The flow:
1. Agent calls a tool that emits `HumanInputRequestEvent`
2. UI detects the event and displays the question
3. Human types a response
4. UI emits `HumanInputResponseEvent`
5. Agent's turn resumes with the response

### Why This Matters

Without human-in-the-loop, agents can only:
- Run autonomously and hope for the best
- Write directly to files (risky)
- Communicate with other agents only

With human-in-the-loop, agents can:
- Propose changes and wait for approval
- Ask clarifying questions before acting
- Present options and let the human choose
- Implement a review workflow where nothing is applied without consent

### Implementation for v2

1. Add event types to `src/remora/core/events/types.py`:

```python
class HumanInputRequestEvent(Event):
    agent_id: str
    request_id: str
    question: str
    options: list[str] = Field(default_factory=list)

class HumanInputResponseEvent(Event):
    request_id: str
    response: str
    agent_id: str | None = None
```

2. Add an external function `request_human_input()` to `TurnContext`:

```python
async def request_human_input(self, question: str, options: list[str] | None = None) -> str:
    request_id = str(uuid.uuid4())
    await self._emit(HumanInputRequestEvent(
        agent_id=self.node_id,
        request_id=request_id,
        question=question,
        options=options or [],
    ))
    # Block until response arrives (via event bus listener)
    response = await self._wait_for_response(request_id)
    return response
```

3. Add `/api/nodes/{node_id}/respond` endpoint to web server
4. Add response display + input in the web panel

---

## 3. Critical: Rewrite Proposal Workflow

### What v1 Had

A complete proposal lifecycle:

```
Agent proposes rewrite
  → RewriteProposalEvent (contains diff, new_source, agent_id, proposal_id)
  → LSP diagnostic (warning squiggles on affected lines)
  → Panel shows diff with +/- coloring
  → User can:
    - Accept → RewriteAppliedEvent → file modified
    - Reject → feedback prompt → RewriteRejectedEvent → agent re-triggered
```

### Why This Matters

This is the **safety layer** between AI suggestions and code changes. Without it, `apply_rewrite()` directly modifies files — no review, no undo, no feedback loop. The proposal workflow is essential for trust.

### Implementation for v2

1. Add event types:

```python
class RewriteProposalEvent(Event):
    agent_id: str
    proposal_id: str
    file_path: str
    start_line: int
    end_line: int
    old_source: str
    new_source: str
    diff: str  # unified diff
    reason: str = ""

class RewriteAppliedEvent(Event):
    agent_id: str
    proposal_id: str

class RewriteRejectedEvent(Event):
    agent_id: str
    proposal_id: str
    feedback: str = ""
```

2. Modify `apply_rewrite()` in externals to create a proposal instead of direct write
3. Add proposal storage (in-memory dict or DB table)
4. Add accept/reject API endpoints
5. Display proposals in web panel with diff view
6. Optionally: emit as LSP diagnostic for Neovim users

---

## 4. High: LSP Code Actions

### What v1 Had

The LSP server registered these commands:
- `remora.chat` → open chat with agent at cursor
- `remora.requestRewrite` → ask agent to rewrite itself
- `remora.executeTool` → run a specific tool on an agent
- `remora.acceptProposal` → accept a rewrite proposal
- `remora.rejectProposal` → reject with feedback
- `remora.selectAgent` → select/focus agent
- `remora.messageNode` → send message to another agent
- `remora.getAgentPanel` → get full agent panel data

Custom LSP notifications:
- `$/remora/requestInput` (server → client) → ask user for input
- `$/remora/submitInput` (client → server) → submit user response
- `$/remora/event` (server → client) → push live events to client
- `$/remora/cursorMoved` (client → server) → report cursor position

### Why This Matters

Without code actions, the LSP integration is passive — it shows information (lenses, hover) but doesn't enable interaction. Code actions turn the editor into an agent control surface.

### Implementation for v2

Add to `lsp/server.py`:

```python
@server.feature(lsp.TEXT_DOCUMENT_CODE_ACTION)
async def code_action(params: lsp.CodeActionParams) -> list[lsp.CodeAction]:
    ns, es = await get_stores()
    file_path = _uri_to_path(params.text_document.uri)
    nodes = await ns.list_nodes(file_path=file_path)
    node = _find_node_at_line(nodes, params.range.start.line + 1)
    if not node:
        return []
    return [
        lsp.CodeAction(
            title=f"Chat with {node.name}",
            kind=lsp.CodeActionKind.Empty,
            command=lsp.Command(title="Chat", command="remora.chat", arguments=[node.node_id]),
        ),
        lsp.CodeAction(
            title=f"Trigger {node.name}",
            kind=lsp.CodeActionKind.Empty,
            command=lsp.Command(title="Trigger", command="remora.trigger", arguments=[node.node_id]),
        ),
    ]
```

The code action can open the web panel focused on that agent — since the sidebar is in the browser, the command just needs to emit an event or signal the web UI.

---

## 5. High: Rich Hover with Graph Context

### What v1 Had

Hover showed: name, ID, type, status, parent, callers, callees, extension name, and recent events from the EventLog.

### Implementation for v2

Enhance `_node_to_hover()` to include:
- Parent node name (query by `parent_id`)
- Edge information (callers/callees from edge table)
- Recent events for the agent (from EventStore)
- Current subscription count

```python
async def hover(params: lsp.HoverParams) -> lsp.Hover | None:
    ns, es = await get_stores()
    ...
    edges = await ns.get_edges(node.node_id)
    callers = [e.from_id for e in edges if e.to_id == node.node_id]
    callees = [e.to_id for e in edges if e.from_id == node.node_id]
    events = await es.get_events_for_agent(node.node_id, limit=5)
    
    value = (
        f"### {node.full_name}\n"
        f"- **ID**: `{node.node_id}`  **Type**: `{node_type}`  **Status**: `{status}`\n"
        f"- **Parent**: `{node.parent_id or 'None'}`\n"
        f"- **Callers**: {', '.join(f'`{c}`' for c in callers) or 'None'}\n"
        f"- **Callees**: {', '.join(f'`{c}`' for c in callees) or 'None'}\n"
    )
    if events:
        value += "\n---\n\n**Recent Events**\n"
        for ev in events[:5]:
            value += f"- `{ev.get('event_type', '?')}` at {ev.get('timestamp', '')}\n"
    
    return lsp.Hover(contents=lsp.MarkupContent(kind=lsp.MarkupKind.Markdown, value=value))
```

---

## 6. High: Cursor-Driven Panel Sync

### What v1 Had

When the user moves their cursor in Neovim:
1. `CursorHold` autocmd fires (debounced 300ms)
2. Panel fetches agent data for the new cursor position
3. If agent changed, panel switches to show the new agent's tools and chat history
4. Per-agent event cache preserves history when switching back

### Why This Matters

This makes the sidebar feel "alive" — it automatically shows context for whatever code you're looking at. Without it, the user must manually click nodes in the graph.

### Implementation for v2

Since the sidebar is in the browser, cursor sync needs a bridge:

1. **LSP → Web**: When LSP receives cursor position (already has `$/remora/cursorMoved` concept), emit a `CursorFocusEvent` to EventStore
2. **SSE → Browser**: Web UI receives `CursorFocusEvent` via SSE stream
3. **Browser Panel**: Automatically switches to show the agent identified in the cursor event
4. **Bidirectional**: Clicking a node in the graph could send cursor position back to editor (via LSP notification)

This creates a two-way sync: move cursor in editor → panel updates in browser; click node in browser → editor navigates to code.

---

## 7. Medium: Tags on Subscription Patterns

### What v1 Had

A `tags` field on `SubscriptionPattern` enabling semantic routing:

```python
SubscriptionPattern(event_types=["AgentCompleteEvent"], tags=["scaffold"])
```

This enabled clean multi-step workflows:
```
scaffold agent completes (tags=["scaffold"]) → interface agent triggers
interface agent completes (tags=["interface"]) → implementation agent triggers
implementation agent completes (tags=["implementation"]) → test agent triggers
```

### Implementation for v2

1. Add `tags: list[str] | None = None` to `SubscriptionPattern`
2. Add `tags: list[str] = Field(default_factory=list)` to `Event` base class
3. Add tag matching to `SubscriptionPattern.matches()`:
```python
if self.tags:
    event_tags = getattr(event, "tags", []) or []
    if not any(tag in event_tags for tag in self.tags):
        return False
```

This is a small change with large workflow implications — it enables clean pipeline architectures.

---

## 8. Medium: Extension Config System

### What v1 Had

A data-driven extension system where Python files in `.remora/models/` define specializations:

```python
class TestFunctionExtension(AgentExtension):
    @staticmethod
    def matches(node_type: str, name: str) -> bool:
        return node_type == "function" and name.startswith("test_")
    
    @staticmethod
    def get_extension_data() -> dict:
        return {
            "extension_name": "TestFunction",
            "custom_system_prompt": "You are a test function...",
            "extra_tools": [ToolSchema(name="run_test", ...)],
            "extra_subscriptions": [SubscriptionPattern(...)],
        }
```

### Why This Matters

Without extensions, all functions use the same bundle regardless of their semantic role. A `test_calculate_total` function behaves identically to `calculate_total` — same prompt, same tools, same subscriptions. Extensions add domain awareness.

### Implementation for v2

v2 already has some of this via virtual agents in YAML. The gap is pattern-based matching at discovery time. Two options:

**Option A**: Adopt v1's Python extension system (`.remora/models/*.py`). More powerful but requires Python code loading.

**Option B**: Extend virtual agent YAML declarations with name patterns:

```yaml
virtual_agents:
  - name: test-function
    bundle: test-agent
    match:
      node_type: function
      name_pattern: "test_*"
    subscriptions:
      - event_types: [ContentChangedEvent]
        path_glob: "src/**/*.py"
```

Option B fits v2's declarative style better and avoids the security/complexity of loading arbitrary Python.

---

## 9. Medium: Kernel Events as First-Class

### What v1 Had

All kernel events (`ToolCallEvent`, `ModelResponseEvent`, `KernelStartEvent`, etc.) were written to the EventLog and received full subscription treatment. This enabled:
- **Monitor agents** watching what tools other agents use
- **Safety agents** flagging dangerous tool calls
- **Learning agents** studying LLM response patterns
- **Coordinator agents** observing turn completion to orchestrate workflows

### Implementation for v2

v2's `Actor` already emits `AgentStartEvent`, `AgentCompleteEvent`, `AgentErrorEvent`, and `ToolResultEvent`. To match v1:

1. Add event types for kernel-level events:
```python
class ModelRequestEvent(Event):
    agent_id: str
    model: str
    prompt_tokens: int = 0

class ModelResponseEvent(Event):
    agent_id: str
    response_preview: str = ""
    completion_tokens: int = 0

class ToolCallEvent(Event):
    agent_id: str
    tool_name: str
    arguments: dict = Field(default_factory=dict)
```

2. Emit these from `Actor._run_turn()` at appropriate points
3. They automatically flow through EventStore → subscriptions → triggering

This is straightforward to implement since the Actor already has the data; it just needs to emit more events.

---

## 10. Medium: UI State Projector

### What v1 Had

`UiStateProjector` (`ui/projector.py`) reduced the event stream into a JSON-serializable state snapshot:

```python
{
    "events": [...],        # Recent events (200 max)
    "blocked": [...],       # Pending human input requests
    "agent_states": {...},  # Per-agent status map
    "progress": {           # Aggregate progress
        "total": 12,
        "completed": 8,
        "failed": 1
    },
    "results": [...],       # Recent agent completions
    "recent_targets": [...]  # Recently accessed files
}
```

### Why This Matters

The projector transforms a raw event stream into structured UI state. Without it, the web UI has to do all the reduction logic in JavaScript. With it, the server provides ready-to-render state.

### Implementation for v2

Add a `UiStateProjector` that subscribes to the EventBus and maintains aggregate state. Expose via `/api/snapshot` endpoint. The web panel can poll this for initial state and then overlay live SSE events.

---

## 11. Low: Event Replay Endpoint

### What v1 Had

`GET /replay?graph_id=X&follow=true` — replay all events from a specific agent run, optionally following live updates.

### Why This Matters

Useful for debugging agent behavior and demonstrating the system. v2 already has `/api/events?limit=N` and SSE with `Last-Event-ID` reconnection, so this is partially covered.

### Implementation for v2

Add `/api/replay?agent_id=X&from=timestamp` endpoint that combines:
1. Historical events from `EventStore.get_events_for_agent()`
2. Live events via SSE with agent_id filtering

---

## 12. Low: Agent Status Icons

### What v1 Had

Nerd Font icons for agent status in both CodeLens and panel:

```lua
status_icons = {
    active = " ",    -- nf-fa-circle
    running = " ",   -- nf-fa-play
    pending_approval = " ",  -- nf-fa-pause
    orphaned = " ",  -- nf-fa-warning
}
```

And event type icons:
```lua
event_icons = {
    AgentTextResponse = " ",
    AgentStartEvent = " ",
    AgentCompleteEvent = " ",
    AgentErrorEvent = " ",
    RewriteProposalEvent = " ",
    HumanChatEvent = " ",
    ToolResultEvent = " ",
}
```

### Implementation for v2

Use Unicode/emoji equivalents in the web UI. Add status icon mapping to CodeLens labels in LSP.

---

## 13. Low: Per-Agent Event Caching

### What v1 Had

Client-side (Lua) per-agent event cache with LRU eviction:

```lua
M._event_cache = {}  -- { [agent_id] = { events = {...}, seen = {...} } }
M._event_cache_limit = 200
```

This enabled instant panel switching — when you move cursor from function A to function B and back, function A's chat history is still there.

### Implementation for v2

Implement in JavaScript in the web panel:
```javascript
const eventCache = new Map();  // agent_id → { events: [], seen: Set }
const CACHE_LIMIT = 200;
```

---

## 14. Implementation Priority Order

Based on impact and dependency analysis, here is the recommended implementation order:

### Phase 1: Foundation (enables everything else)
1. **Human-in-the-loop events** (#2) — add `HumanInputRequestEvent`/`HumanInputResponseEvent` to event types
2. **Rewrite proposal events** (#3) — add `RewriteProposalEvent`/`RewriteAppliedEvent`/`RewriteRejectedEvent`
3. **Tags on subscriptions** (#7) — add `tags` field to `SubscriptionPattern` and `Event`

### Phase 2: Web Panel (the main goal)
4. **Web agent panel** (#1) — HTML/CSS/JS panel in the browser with:
   - Agent header (name, type, status)
   - Chat history (per-agent, event-type-specific rendering)
   - Message input
   - Human input response UI
   - Proposal diff display with accept/reject
   - Tools section
5. **Per-agent event caching** (#13) — JavaScript event cache for instant panel switching
6. **Cursor-driven panel sync** (#6) — CursorFocusEvent → SSE → panel auto-switch

### Phase 3: Editor Integration
7. **LSP code actions** (#4) — chat, trigger, accept/reject proposal commands
8. **Rich hover** (#5) — graph context + recent events in hover info
9. **Agent status icons** (#12) — better visual indicators

### Phase 4: Advanced Features
10. **Kernel events** (#9) — meta-agent observation capability
11. **Extension configs** (#8) — data-driven agent specialization
12. **UI state projector** (#10) — server-side state aggregation
13. **Event replay** (#11) — debugging and demo capability

This order ensures each phase builds on the previous one and delivers usable value at each step.

