# Final Polish Proposal: v1 Ideas Integrated into v2

> A concrete, opinionated proposal for integrating the best ideas from Remora v1 into
> the v2 codebase — rethought to fit v2's architecture, ethos, and conventions.
> No backwards compatibility concerns. Only clean, elegant design.

---

## Table of Contents

1. [Guiding Principles](#1-guiding-principles)
2. [Proposal A: Event Tags on Subscriptions](#2-proposal-a-event-tags-on-subscriptions)
3. [Proposal B: Human-in-the-Loop via Futures](#3-proposal-b-human-in-the-loop-via-futures)
4. [Proposal C: Rewrite Proposals (Safety Layer)](#4-proposal-c-rewrite-proposals-safety-layer)
5. [Proposal D: Rich Hover and LSP Code Actions](#5-proposal-d-rich-hover-and-lsp-code-actions)
6. [Proposal E: Agent Panel in Web UI](#6-proposal-e-agent-panel-in-web-ui)
7. [Proposal F: Kernel Observability Events](#7-proposal-f-kernel-observability-events)
8. [Proposal G: Pattern-Matched Bundle Overlays](#8-proposal-g-pattern-matched-bundle-overlays)
9. [What We Should NOT Add](#9-what-we-should-not-add)
10. [Implementation Order](#10-implementation-order)

---

## 1. Guiding Principles

Before diving in, the principles that govern what gets in and how:

1. **Events are the universal join.** Every new feature should express itself as events
   flowing through EventStore → EventBus → SubscriptionRegistry → TriggerDispatcher.
   No side-channels, no special-case notification systems.

2. **The Actor is the boundary.** Human input, proposals, and observability all flow
   through the existing Actor inbox/outbox pattern. Nothing bypasses the Outbox.

3. **Declarative over imperative.** Where v1 used Python extension classes, v2 uses
   YAML declarations. New features should extend the declarative surface, not introduce
   plugin loading.

4. **Grail tools are the agent's hands.** New agent capabilities (proposing rewrites,
   requesting human input) manifest as new `.pym` tools in bundles, not as hardcoded
   methods on TurnContext. TurnContext provides the low-level externals; tools compose them.

5. **The web UI is a projection of the event stream.** The browser receives SSE events
   and renders them. Server-side aggregation is kept minimal — the client reduces.

6. **Small, orthogonal changes.** Each proposal is independently implementable and testable.
   No proposal depends on another unless explicitly noted.

---

## 2. Proposal A: Event Tags on Subscriptions

### Problem

Subscription patterns match on event type, agent IDs, and path globs — but there's no
semantic routing. Two agents that both emit `AgentCompleteEvent` are indistinguishable
to subscribers unless they filter by `from_agents`. This forces agents to know each
other's IDs, coupling them tightly.

### Solution

Add a `tags` field to both `Event` and `SubscriptionPattern`.

### Changes

**`core/events/types.py`** — Add to `Event` base class:

```python
class Event(BaseModel):
    event_type: str = ""
    timestamp: float = Field(default_factory=time.time)
    correlation_id: str | None = None
    tags: tuple[str, ...] = ()       # ← NEW
```

**`core/events/subscriptions.py`** — Add to `SubscriptionPattern`:

```python
class SubscriptionPattern(BaseModel):
    event_types: list[str] | None = None
    from_agents: list[str] | None = None
    to_agent: str | None = None
    path_glob: str | None = None
    tags: list[str] | None = None    # ← NEW

    def matches(self, event: Event) -> bool:
        # ... existing checks ...

        if self.tags:
            event_tags = event.tags
            if not any(tag in event_tags for tag in self.tags):
                return False

        return True
```

**`core/config.py`** — Extend `VirtualSubscriptionConfig`:

```python
class VirtualSubscriptionConfig(BaseModel):
    event_types: tuple[str, ...] | None = None
    from_agents: tuple[str, ...] | None = None
    to_agent: str | None = None
    path_glob: str | None = None
    tags: tuple[str, ...] | None = None   # ← NEW
```

**`core/externals.py`** — Extend `event_emit()`:

```python
async def event_emit(
    self,
    event_type: str,
    payload: dict[str, Any],
    tags: list[str] | None = None,
) -> bool:
    event = CustomEvent(
        event_type=event_type,
        payload=payload,
        tags=tuple(tags or ()),
        correlation_id=self.correlation_id,
    )
    await self._emit(event)
    return True
```

**`core/events/store.py`** — Persist tags in the events table:

Add a `tags` TEXT column (JSON-encoded list) to the events table. Include tags in
`to_envelope()` and restore them on read.

### Usage Example (remora.yaml)

```yaml
virtual_agents:
  - id: "test-runner"
    role: "test-agent"
    subscriptions:
      - event_types: ["AgentCompleteEvent"]
        tags: ["scaffold"]
```

An agent emits `AgentCompleteEvent` with `tags=("scaffold",)` → only subscribers
matching the `scaffold` tag are triggered. Clean pipeline semantics without ID coupling.

### Scope

~50 lines changed across 4 files. Purely additive. Fully backwards compatible in the
sense that existing events have `tags=()` and existing patterns have `tags=None` (wildcard).

---

## 3. Proposal B: Human-in-the-Loop via Futures

### Problem

Agents currently run autonomously with no way to pause and ask for human guidance.
The `apply_rewrite()` function writes directly to disk. There's no approval workflow.

### Solution

Add `HumanInputRequestEvent` / `HumanInputResponseEvent` event types, plus a pending
futures registry in EventStore that lets an agent's turn block on a human response.

### Design

The key insight: an agent turn runs inside `Actor._execute_turn()`, which is async.
We can await a `Future` that resolves when the human submits a response. This keeps
the actor model clean — the actor's inbox loop isn't blocked (the semaphore is held,
which is correct — the agent IS busy waiting for human input).

### Changes

**`core/events/types.py`** — New event types:

```python
class HumanInputRequestEvent(Event):
    """Agent is asking the human a question."""
    agent_id: str
    request_id: str
    question: str
    options: tuple[str, ...] = ()

class HumanInputResponseEvent(Event):
    """Human has answered an agent's question."""
    agent_id: str
    request_id: str
    response: str
```

**`core/events/store.py`** — Pending response registry:

```python
class EventStore:
    def __init__(self, ...):
        # ... existing ...
        self._pending_responses: dict[str, asyncio.Future[str]] = {}

    def create_response_future(self, request_id: str) -> asyncio.Future[str]:
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending_responses[request_id] = future
        return future

    def resolve_response(self, request_id: str, response: str) -> bool:
        future = self._pending_responses.pop(request_id, None)
        if future is None or future.done():
            return False
        future.set_result(response)
        return True
```

**`core/externals.py`** — New external function:

```python
async def request_human_input(
    self, question: str, options: list[str] | None = None
) -> str:
    """Ask the human a question and block until they respond."""
    import uuid
    request_id = str(uuid.uuid4())
    future = self._event_store.create_response_future(request_id)
    await self._emit(HumanInputRequestEvent(
        agent_id=self.node_id,
        request_id=request_id,
        question=question,
        options=tuple(options or ()),
    ))
    return await future
```

**`web/server.py`** — New endpoint:

```python
Route("/api/nodes/{node_id:path}/respond", endpoint=api_respond, methods=["POST"])
```

Handler:

```python
async def api_respond(request: Request) -> JSONResponse:
    data = await request.json()
    request_id = str(data.get("request_id", "")).strip()
    response = str(data.get("response", "")).strip()
    if not request_id or not response:
        return JSONResponse({"error": "request_id and response required"}, status_code=400)

    node_id = request.path_params["node_id"]
    resolved = event_store.resolve_response(request_id, response)
    if not resolved:
        return JSONResponse({"error": "no pending request"}, status_code=404)

    await event_store.append(HumanInputResponseEvent(
        agent_id=node_id,
        request_id=request_id,
        response=response,
    ))
    return JSONResponse({"status": "ok"})
```

**Bundle tool** — `bundles/system/tools/ask_human.pym`:

```python
# Ask the human a question and return their response
from remora.externals import request_human_input

input question: str
input options: str = ""

option_list = [o.strip() for o in options.split(",") if o.strip()] if options else []
result = await request_human_input(question, option_list)
return result
```

### Node Status Additions

Proposals B and C together add two new statuses to `NodeStatus`:

```python
class NodeStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    AWAITING_INPUT = "awaiting_input"    # ← NEW (Proposal B)
    AWAITING_REVIEW = "awaiting_review"  # ← NEW (Proposal C)
    ERROR = "error"
```

Update `STATUS_TRANSITIONS`:

```python
STATUS_TRANSITIONS = {
    NodeStatus.IDLE: {NodeStatus.RUNNING},
    NodeStatus.RUNNING: {NodeStatus.IDLE, NodeStatus.ERROR, NodeStatus.AWAITING_INPUT, NodeStatus.AWAITING_REVIEW},
    NodeStatus.AWAITING_INPUT: {NodeStatus.RUNNING, NodeStatus.IDLE},
    NodeStatus.AWAITING_REVIEW: {NodeStatus.IDLE, NodeStatus.RUNNING},
    NodeStatus.ERROR: {NodeStatus.IDLE, NodeStatus.RUNNING},
}
```

The actor transitions to `AWAITING_INPUT` when `request_human_input` is called (and
back to `RUNNING` when the future resolves), and to `AWAITING_REVIEW` when
`propose_changes` is called (reset on accept/reject). Both give the UI accurate
status display in CodeLens and the web panel.

### Timeout

Add a configurable timeout (default 300s) to `request_human_input`. If no response
arrives, raise a `TimeoutError` that the agent can handle or that becomes an
`AgentErrorEvent`.

### Scope

~120 lines across 5 files + 1 new tool script. The Futures pattern is clean, testable,
and fits naturally into the async actor model.

---

## 4. Proposal C: Rewrite Proposals via Cairn Workspace (Safety Layer)

### Problem

`apply_rewrite()` in `TurnContext` writes directly to the filesystem. There's no
review, no undo, no feedback loop. This is the biggest trust gap in the system.

### Solution: Workspace-Native Proposals

Each agent already has its own Cairn workspace — a sandboxed filesystem with KV store.
Rather than inventing a separate `ProposalStore`, we use the workspace as the proposal
itself. The agent freely writes and iterates on code within its Cairn sandbox, then
signals "ready for review" when satisfied. Acceptance is simply materializing the
workspace content back to disk.

This is architecturally cleaner than a diff-based proposal store because:

1. **The agent already writes to its workspace.** Tools like `write_file()` already
   work against the Cairn FS. The agent can freely iterate — write, read back, refine —
   without any new API. The workspace IS the scratch pad.

2. **No redundant storage.** Instead of duplicating `old_source` and `new_source` in
   event payloads and an in-memory dict, the workspace holds the complete proposed state.

3. **Multi-file proposals are free.** An agent that wants to refactor across multiple
   files just writes them all to its workspace. The proposal event says "I'm ready"
   and the accept handler materializes everything that changed.

4. **Reviewable at any time.** The workspace content can be read via API at any point,
   not just when a proposal event fires.

### Design

```
Agent writes to Cairn workspace (existing tools)
  → Agent calls `propose_changes(reason="...")` tool
    → RewriteProposalEvent emitted (metadata only: agent_id, file list, reason)
    → Node status → AWAITING_REVIEW
  → Web UI shows proposal with diff (reads workspace vs disk)
  → Human clicks Accept
    → Workspace files materialized to disk
    → RewriteAcceptedEvent + ContentChangedEvent emitted
    → Node status → IDLE
  → Human clicks Reject (with optional feedback)
    → RewriteRejectedEvent emitted (triggers agent re-think)
    → Node status → IDLE
```

### Changes

**`core/events/types.py`** — New event types:

```python
class RewriteProposalEvent(Event):
    """Agent signals its workspace changes are ready for human review."""
    agent_id: str
    proposal_id: str
    files: tuple[str, ...] = ()   # workspace paths that changed
    reason: str = ""

class RewriteAcceptedEvent(Event):
    """Human accepted a workspace proposal."""
    agent_id: str
    proposal_id: str

class RewriteRejectedEvent(Event):
    """Human rejected a workspace proposal."""
    agent_id: str
    proposal_id: str
    feedback: str = ""
```

Note: `RewriteProposalEvent` carries only metadata (file list, reason), not the full
source content. The actual content lives in the Cairn workspace and is read on demand.

**`core/types.py`** — Add review status:

```python
class NodeStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    AWAITING_REVIEW = "awaiting_review"   # ← NEW
    ERROR = "error"
```

**`core/externals.py`** — New external function:

```python
async def propose_changes(self, reason: str = "") -> str:
    """Signal that workspace changes are ready for human review."""
    import uuid
    proposal_id = str(uuid.uuid4())

    # Discover which workspace files differ from on-disk originals
    changed_files = await self._collect_changed_files()

    await self._emit(RewriteProposalEvent(
        agent_id=self.node_id,
        proposal_id=proposal_id,
        files=tuple(changed_files),
        reason=reason,
    ))
    return proposal_id

async def _collect_changed_files(self) -> list[str]:
    """List workspace files that differ from their on-disk counterparts."""
    all_paths = await self.workspace.list_all_paths()
    # Filter to non-bundle files (exclude _bundle/ prefix)
    return [p for p in all_paths if not p.startswith("_bundle/")]
```

The existing `write_file()`, `read_file()`, etc. remain unchanged — they already
operate on the Cairn workspace. The agent just uses them normally, then calls
`propose_changes()` when ready.

Remove `apply_rewrite()` from the public externals. It was the only function that
wrote directly to disk, and it's replaced by the propose→accept flow.

**`web/server.py`** — New endpoints:

```
GET  /api/proposals                          → list pending proposals (query nodes with AWAITING_REVIEW)
GET  /api/proposals/{node_id}/diff           → compute diff between workspace and disk
POST /api/proposals/{node_id}/accept         → materialize workspace to disk
POST /api/proposals/{node_id}/reject         → send feedback, reset status
```

The diff endpoint:

```python
async def api_proposal_diff(request: Request) -> JSONResponse:
    node_id = request.path_params["node_id"]
    node = await node_store.get_node(node_id)
    if node is None:
        return JSONResponse({"error": "not found"}, status_code=404)

    workspace = await workspace_service.get_agent_workspace(node_id)
    diffs = []
    # Read workspace version of agent's source file
    try:
        workspace_source = await workspace.read(f"source/{node.name}")
    except FileNotFoundError:
        workspace_source = None

    if workspace_source is not None:
        diffs.append({
            "file": node.file_path,
            "old": node.source_code,
            "new": workspace_source,
        })

    return JSONResponse({"node_id": node_id, "diffs": diffs})
```

The accept handler materializes changed workspace files to the real filesystem using
the same byte-offset replacement logic currently in `apply_rewrite()`, then emits
`ContentChangedEvent` + `RewriteAcceptedEvent`.

**Bundle tool** — `bundles/code-agent/tools/rewrite_self.pym`:

Update the existing `rewrite_self.pym`:

```python
# Propose a rewrite of this agent's source code. Writes to workspace sandbox,
# then signals readiness for human review. Does NOT modify the real file.
from grail import Input, external

new_source: str = Input("new_source")
reason: str = Input("reason", default="")

@external
async def write_file(path: str, content: str) -> bool: ...

@external
async def propose_changes(reason: str) -> str: ...

@external
async def my_node_id() -> str: ...

# Write proposed source to workspace
node_id = await my_node_id()
await write_file(f"source/{node_id}", new_source)

# Signal ready for review
proposal_id = await propose_changes(reason or "Code rewrite proposed")
f"Proposal {proposal_id} submitted. Awaiting human review."
```

### Why This Is Better Than a ProposalStore

| Aspect | ProposalStore (original) | Cairn Workspace (revised) |
|--------|------------------------|--------------------------|
| Storage | In-memory dict (lost on restart) | Cairn FS (persistent) |
| Multi-file | One proposal = one file | Agent writes any files to workspace |
| Iteration | Agent must re-propose each revision | Agent freely edits workspace |
| Diff source | Stored in event payload | Computed on-demand from workspace vs disk |
| New code | ~150 lines + new module | ~80 lines, no new module |
| Existing infra | None | Reuses AgentWorkspace, CairnWorkspaceService |

### Scope

~80 lines across 3 files. Reuses existing workspace infrastructure entirely. The
proposal is the workspace itself — no redundant storage layer.

---

## 5. Proposal D: Rich Hover and LSP Code Actions (Neovim-Native)

### Problem

The LSP integration is passive: CodeLens shows status, hover shows basic node info.
There are no code actions, no graph context in hover, and no way to interact with
agents from the editor.

### Neovim Compatibility — Verified

All LSP features proposed here are fully supported by Neovim's built-in LSP client:

- **`textDocument/codeAction`** — Neovim has native support. Users invoke via
  `vim.lsp.buf.code_action()` (typically mapped to `<leader>ca`). Enhanced by
  popular plugins like [tiny-code-action.nvim](https://github.com/rachartier/tiny-code-action.nvim)
  and [Lspsaga](https://nvimdev.github.io/lspsaga/codeaction/).

- **`workspace/executeCommand`** — Fully supported. When a code action returns a
  `Command`, Neovim sends `workspace/executeCommand` to the server. pygls handles
  this via its `@server.command()` decorator.

- **`window/showDocument` with `external=true`** — Supported since Neovim 0.8+.
  Neovim's handler calls `vim.ui.open(uri)` which opens URLs in the system browser.
  This is how `remora.chat` will open the web panel.

- **`textDocument/hover`** — Obviously supported. Neovim renders markdown hover
  content in a floating window.

- **`textDocument/codeLens`** — Already working in the current codebase.

### Solution

Enhance hover with graph context (parent, edges, recent events) and add code actions
for common operations — all using standard LSP, no Neovim-specific hacks.

### Changes

**`lsp/server.py`** — Enhanced hover:

```python
@server.feature(lsp.TEXT_DOCUMENT_HOVER)
async def hover(params: lsp.HoverParams) -> lsp.Hover | None:
    ns, es = await get_stores()
    file_path = _uri_to_path(params.text_document.uri)
    nodes = await ns.list_nodes(file_path=file_path)
    node = _find_node_at_line(nodes, params.position.line + 1)
    if node is None:
        return None

    node_type = node.node_type.value if hasattr(node.node_type, "value") else str(node.node_type)
    status = node.status.value if hasattr(node.status, "value") else str(node.status)

    # Graph context
    edges = await ns.get_edges(node.node_id)
    callers = [e.from_id for e in edges if e.to_id == node.node_id]
    callees = [e.to_id for e in edges if e.from_id == node.node_id]

    # Recent events
    events = await es.get_events_for_agent(node.node_id, limit=5)

    parts = [
        f"### {node.full_name}",
        f"- **ID**: `{node.node_id}`",
        f"- **Type**: `{node_type}` | **Status**: `{status}`",
        f"- **Lines**: {node.start_line}–{node.end_line}",
    ]
    if node.parent_id:
        parts.append(f"- **Parent**: `{node.parent_id}`")
    if callers:
        parts.append(f"- **Callers**: {', '.join(f'`{c}`' for c in callers[:5])}")
    if callees:
        parts.append(f"- **Callees**: {', '.join(f'`{c}`' for c in callees[:5])}")
    if events:
        parts.append("\n---\n**Recent Events**")
        for ev in events[:5]:
            etype = ev.get("event_type", "?")
            summary = ev.get("summary", "")
            parts.append(f"- `{etype}` {summary[:60]}")

    value = "\n".join(parts)
    return lsp.Hover(
        contents=lsp.MarkupContent(kind=lsp.MarkupKind.Markdown, value=value)
    )
```

**`lsp/server.py`** — Code actions:

```python
@server.feature(lsp.TEXT_DOCUMENT_CODE_ACTION)
async def code_action(params: lsp.CodeActionParams) -> list[lsp.CodeAction]:
    ns, _es = await get_stores()
    file_path = _uri_to_path(params.text_document.uri)
    nodes = await ns.list_nodes(file_path=file_path)
    node = _find_node_at_line(nodes, params.range.start.line + 1)
    if not node:
        return []
    return [
        lsp.CodeAction(
            title=f"Remora: Chat with {node.name}",
            kind=lsp.CodeActionKind.Empty,
            command=lsp.Command(
                title="Chat", command="remora.chat",
                arguments=[node.node_id],
            ),
        ),
        lsp.CodeAction(
            title=f"Remora: Trigger {node.name}",
            kind=lsp.CodeActionKind.Empty,
            command=lsp.Command(
                title="Trigger", command="remora.trigger",
                arguments=[node.node_id],
            ),
        ),
    ]
```

In Neovim, these appear in the code action menu (`:lua vim.lsp.buf.code_action()`).
The user selects one, Neovim sends `workspace/executeCommand` to the server.

**`lsp/server.py`** — Command execution via pygls `@server.command()`:

```python
@server.command("remora.chat")
async def chat_command(ls: LanguageServer, args: list[Any]) -> None:
    node_id = args[0] if args else None
    if node_id:
        # window/showDocument with external=true → Neovim calls vim.ui.open()
        # which opens the URL in the system browser
        ls.show_document(
            lsp.ShowDocumentParams(
                uri=f"http://localhost:8080/?node={node_id}",
                external=True,
            )
        )

@server.command("remora.trigger")
async def trigger_command(ls: LanguageServer, args: list[Any]) -> None:
    node_id = args[0] if args else None
    if node_id:
        _, es = await get_stores()
        await es.append(AgentMessageEvent(
            from_agent="user", to_agent=node_id,
            content="Manual trigger from editor",
        ))
```

### CodeLens Status Icons

Enhance CodeLens labels with Unicode status indicators (no Nerd Fonts required,
though users with Nerd Fonts could override via Neovim config):

```python
_STATUS_ICONS = {
    "idle": "○",
    "running": "▶",
    "awaiting_input": "⏸",
    "awaiting_review": "⏳",
    "error": "✗",
}

def _node_to_lens(node: Node) -> lsp.CodeLens:
    status = node.status.value if hasattr(node.status, "value") else str(node.status)
    icon = _STATUS_ICONS.get(status, "○")
    return lsp.CodeLens(
        range=...,
        command=lsp.Command(
            title=f"Remora {icon} {status}",
            command="remora.showNode",
            arguments=[node.node_id],
        ),
        ...
    )
```

### Neovim Integration Notes

For users setting up Neovim, the LSP client config is standard:

```lua
-- In lspconfig or manual setup:
vim.lsp.start({
  name = "remora",
  cmd = { "remora", "lsp", "--project-root", vim.fn.getcwd() },
  root_dir = vim.fn.getcwd(),
})
```

All features (hover, code lens, code actions, commands) work out of the box with
Neovim's native LSP client. No additional plugins required, though Lspsaga or
tiny-code-action.nvim enhance the code action UI.

### Scope

~100 lines in `lsp/server.py`. No new modules needed. All features use standard LSP
protocol that Neovim supports natively.

---

## 6. Proposal E: Agent Panel in Web UI

### Problem

The web UI shows a graph visualization and a basic sidebar with node details, but
there's no chat interface, no event history per agent, and no way to interact with
agents from the browser.

### Solution

Extend `index.html` with an agent detail panel that shows chat history, accepts
messages, displays proposals for review, and shows human input requests.

### Design Philosophy

The panel is a **projection of the SSE event stream**, filtered by the currently
selected agent. No new server-side endpoints are needed beyond what already exists
(`/api/chat`, `/api/nodes/{id}`, `/api/nodes/{id}/conversation`, `/sse`) plus the
new endpoints from Proposals B and C (`/api/nodes/{id}/respond`, `/api/proposals/*`).

### Client-Side Architecture

```
SSE stream → EventRouter → per-agent EventCache → PanelRenderer
                                                 ↑
                             graph click / cursor event → agent selection
```

**EventCache** (JavaScript):

```javascript
const agentEventCache = new Map();  // agent_id → Event[]
const CACHE_LIMIT = 200;

function cacheEvent(event) {
  const agentId = event.payload?.agent_id
    || event.payload?.from_agent
    || event.payload?.to_agent;
  if (!agentId) return;

  if (!agentEventCache.has(agentId)) {
    agentEventCache.set(agentId, []);
  }
  const cache = agentEventCache.get(agentId);
  cache.push(event);
  if (cache.length > CACHE_LIMIT) cache.shift();
}
```

**Panel Sections**:

1. **Agent Header** — Name, type, status badge (colored), file path, line range
2. **Chat History** — Scrollable list of events filtered to the selected agent:
   - `AgentMessageEvent` (from_agent="user") → user bubble (right-aligned, blue)
   - `AgentCompleteEvent` → agent bubble (left-aligned, green)
   - `AgentStartEvent` → compact status line
   - `AgentErrorEvent` → red error block
   - `ToolResultEvent` → collapsible grey block
   - `HumanInputRequestEvent` → prominent question card with input field
   - `RewriteProposalEvent` → diff view with Accept/Reject buttons
3. **Message Input** — Text input + send button at the bottom. POSTs to `/api/chat`.

**Cursor-Driven Panel Sync**:

The `CursorFocusEvent` already exists and flows through SSE. When the browser
receives it, auto-switch the panel to the focused node:

```javascript
eventSource.addEventListener("CursorFocusEvent", (e) => {
  const data = JSON.parse(e.data);
  const nodeId = data.payload?.node_id;
  if (nodeId) selectAgent(nodeId);
});
```

This creates the two-way sync: cursor moves in editor → LSP emits CursorFocusEvent →
web panel switches. Clicking a node in the graph → panel switches (already works).

**Proposal Diff Rendering**:

For `RewriteProposalEvent`, render a simple unified diff using line-by-line comparison
with `+`/`-` prefix coloring:

```javascript
function renderDiff(oldSource, newSource) {
  const oldLines = oldSource.split('\n');
  const newLines = newSource.split('\n');
  // Simple line-level diff with -, + coloring
  // (No external dependency needed for basic display)
}
```

### What the Panel Does NOT Need

- **No framework** — vanilla JS is sufficient for this panel. The existing `index.html`
  is already frameworkless and works well.
- **No separate page** — the panel replaces/extends the existing sidebar. When an agent
  is selected, the sidebar transforms into the agent panel.
- **No WebSocket** — SSE is sufficient and already implemented.
- **No server-side aggregation** — the client-side EventCache handles state.

### Scope

~300-400 lines of HTML/CSS/JS added to `index.html`. This is the largest single
change but requires zero Python changes (assuming Proposals B and C provide the API
endpoints).

---

## 7. Proposal F: Kernel Observability Events

### Problem

The Actor emits `AgentStartEvent`, `AgentCompleteEvent`, `AgentErrorEvent`, and
`ToolResultEvent`. But there's no visibility into what happens *during* a turn —
which model was called, how many tokens were used, which tools were invoked with
what arguments.

### Solution

Bridge structured_agents' Observer interface into Remora's event pipeline, forwarding
kernel-level events through the Outbox.

### structured_agents Observer — Verified

The structured_agents library (v0.4.0) already emits rich kernel events via its
`Observer` protocol. The protocol is a single-method interface:

```python
class Observer(Protocol):
    async def emit(self, event: Event) -> None: ...
```

The kernel emits these event types automatically during `kernel.run()`:

| Kernel Event | Emitted When | Data Available |
|---|---|---|
| `KernelStartEvent` | `run()` begins | max_turns, tools_count |
| `ModelRequestEvent` | Before each LLM call | turn, model, messages_count, tools_count |
| `ModelResponseEvent` | After each LLM response | turn, duration_ms, content, tool_calls_count, usage (tokens) |
| `ToolCallEvent` | Before each tool execution | turn, tool_name, call_id, arguments |
| `ToolResultEvent` | After each tool execution | turn, tool_name, is_error, duration_ms, output_preview |
| `TurnCompleteEvent` | After each turn cycle | turn, tool_calls_count, errors_count |
| `KernelEndEvent` | `run()` completes | turn_count, termination_reason, total_duration_ms |

All of these are already emitted by `AgentKernel.step()` and `AgentKernel.run()` —
Remora just needs to listen. Currently Remora passes `NullObserver()` which discards
them all.

### Implementation

**`core/actor.py`** — `OutboxObserver` bridges kernel events to Remora events:

```python
from structured_agents.events.types import (
    Event as KernelEvent,
    ModelRequestEvent as KernelModelRequest,
    ModelResponseEvent as KernelModelResponse,
    ToolCallEvent as KernelToolCall,
    ToolResultEvent as KernelToolResult,
    TurnCompleteEvent as KernelTurnComplete,
)

class OutboxObserver:
    """Bridges structured_agents kernel events into Remora's event pipeline."""

    def __init__(self, outbox: Outbox, agent_id: str) -> None:
        self._outbox = outbox
        self._agent_id = agent_id

    async def emit(self, event: KernelEvent) -> None:
        remora_event = self._translate(event)
        if remora_event is not None:
            await self._outbox.emit(remora_event)

    def _translate(self, event: KernelEvent) -> Event | None:
        if isinstance(event, KernelModelRequest):
            return ModelRequestEvent(
                agent_id=self._agent_id,
                model=event.model,
                tool_count=event.tools_count,
                turn=event.turn,
            )
        if isinstance(event, KernelModelResponse):
            return ModelResponseEvent(
                agent_id=self._agent_id,
                response_preview=(event.content or "")[:200],
                duration_ms=event.duration_ms,
                tool_calls_count=event.tool_calls_count,
                turn=event.turn,
            )
        if isinstance(event, KernelToolCall):
            return RemoraToolCallEvent(
                agent_id=self._agent_id,
                tool_name=event.tool_name,
                arguments_summary=str(event.arguments)[:200],
                turn=event.turn,
            )
        if isinstance(event, KernelToolResult):
            return RemoraToolResultEvent(
                agent_id=self._agent_id,
                tool_name=event.tool_name,
                is_error=event.is_error,
                duration_ms=event.duration_ms,
                output_preview=event.output_preview,
                turn=event.turn,
            )
        if isinstance(event, KernelTurnComplete):
            return TurnCompleteEvent(
                agent_id=self._agent_id,
                turn=event.turn,
                tool_calls_count=event.tool_calls_count,
                errors_count=event.errors_count,
            )
        return None
```

**`core/events/types.py`** — New Remora event types (wrapping kernel data with agent_id):

```python
class ModelRequestEvent(Event):
    """LLM API request initiated by an agent."""
    agent_id: str
    model: str = ""
    tool_count: int = 0
    turn: int = 0

class ModelResponseEvent(Event):
    """LLM API response received by an agent."""
    agent_id: str
    response_preview: str = ""
    duration_ms: int = 0
    tool_calls_count: int = 0
    turn: int = 0

class RemoraToolCallEvent(Event):
    """Agent is about to call a tool."""
    agent_id: str
    tool_name: str
    arguments_summary: str = ""
    turn: int = 0

class RemoraToolResultEvent(Event):
    """Tool execution completed."""
    agent_id: str
    tool_name: str
    is_error: bool = False
    duration_ms: int = 0
    output_preview: str = ""
    turn: int = 0

class TurnCompleteEvent(Event):
    """One turn cycle (model call + tool executions) completed."""
    agent_id: str
    turn: int = 0
    tool_calls_count: int = 0
    errors_count: int = 0
```

Note: `RemoraToolCallEvent` and `RemoraToolResultEvent` are prefixed to avoid name
collision with the existing `ToolResultEvent` (which serves a different purpose in
the current codebase). The existing `ToolResultEvent` could be deprecated in favor
of the richer `RemoraToolResultEvent`.

**`core/kernel.py`** — Pass observer to kernel:

```python
def create_kernel(
    *,
    model_name: str,
    base_url: str,
    api_key: str,
    timeout: float = 300.0,
    tools: list[Any] | None = None,
    observer: Any | None = None,    # ← already accepts this
    ...
) -> AgentKernel:
```

`create_kernel()` already accepts an `observer` parameter. Currently `Actor._run_kernel()`
passes nothing (defaults to `NullObserver`). The change is simply:

```python
# In Actor._run_kernel():
kernel = create_kernel(
    model_name=model_name,
    base_url=self._config.model_base_url,
    api_key=self._config.model_api_key,
    timeout=self._config.timeout_s,
    tools=tools,
    observer=OutboxObserver(outbox=outbox, agent_id=node_id),  # ← NEW
)
```

One line change in `_run_kernel()`, plus the `OutboxObserver` class.

### Use Cases

- **Monitor agents** — Subscribe to `RemoraToolCallEvent` to watch what tools other agents use
- **Cost tracking** — Subscribe to `ModelRequestEvent` to aggregate model usage per agent
- **Safety agents** — Flag dangerous tool calls before they execute
- **Debugging** — Full turn trace in the event log, visible in web UI and LSP hover
- **Performance** — `duration_ms` on model responses and tool results enables latency analysis

### Scope

~80 lines total: `OutboxObserver` class (~45 lines) + new event types (~30 lines) +
1-line change in `_run_kernel()`. No new modules needed. Fully verified against
structured_agents v0.4.0 — every event type and the Observer protocol are confirmed
to exist and work as described.

---

## 8. Proposal G: Pattern-Matched Bundle Overlays

### Problem

The `bundle_overlays` config maps node types to bundles (`function → code-agent`,
`directory → directory-agent`), but there's no way to specialize by name pattern.
A test function gets the same bundle as a business logic function.

### Solution

Extend `bundle_overlays` to support pattern-based matching with a priority system.

### Changes

**`core/config.py`** — New overlay model:

```python
class BundleOverlayRule(BaseModel):
    """A bundle overlay rule with optional pattern matching."""
    node_type: str
    name_pattern: str | None = None   # fnmatch pattern
    bundle: str

# In Config:
class Config(BaseSettings):
    bundle_overlays: dict[str, str] = Field(...)  # simple type→bundle
    bundle_rules: tuple[BundleOverlayRule, ...] = ()  # pattern rules (higher priority)
```

**`code/reconciler.py`** — Resolution logic:

```python
def _resolve_bundle(self, node: Node) -> str | None:
    """Resolve bundle name: rules (most specific) > overlays (by type) > None."""
    node_type = node.node_type.value if hasattr(node.node_type, "value") else str(node.node_type)

    # Check rules first (pattern-matched, order = priority)
    for rule in self._config.bundle_rules:
        if rule.node_type != node_type:
            continue
        if rule.name_pattern is None or fnmatch.fnmatch(node.name, rule.name_pattern):
            return rule.bundle

    # Fall back to simple type mapping
    return self._config.bundle_overlays.get(node_type)
```

### Usage Example (remora.yaml)

```yaml
bundle_overlays:
  function: "code-agent"
  class: "code-agent"
  directory: "directory-agent"

bundle_rules:
  - node_type: "function"
    name_pattern: "test_*"
    bundle: "test-agent"
  - node_type: "class"
    name_pattern: "Test*"
    bundle: "test-agent"
```

### Why YAML Over Python Extensions

v1's Python extension system (`AgentExtension` classes loaded from `.remora/models/`)
was powerful but:

1. **Security risk** — loading arbitrary Python at runtime
2. **Complexity** — class hierarchy, `matches()` protocol, dynamic imports
3. **Opaque** — behavior not visible in config

v2's YAML approach is:

1. **Auditable** — all routing visible in one config file
2. **Safe** — no code execution at config time
3. **Composable** — rules are ordered, first match wins

The only thing Python extensions can do that YAML rules can't is complex matching
logic (e.g., "functions with more than 50 lines" or "functions that import X").
This is a good tradeoff — if you need that, use a virtual agent with subscriptions
that filters programmatically.

### Scope

~40 lines across 2 files. Clean extension of existing config.

---

## 9. What We Should NOT Add

Some v1 ideas don't fit v2's architecture or aren't worth the complexity:

### UI State Projector (v1 Idea #10) — Skip

v1's `UiStateProjector` was a server-side event reducer that produced a JSON snapshot.
In v2, the web client already receives the raw SSE stream and can compute any
projections it needs client-side. Adding a server-side projector creates two sources
of truth and couples the server to UI concerns.

**Alternative**: If snapshot state is needed (e.g., for a newly-connected client),
the existing `/api/events?limit=N` and `/api/nodes` endpoints already provide
bootstrap data. The client reduces from there.

### Event Replay Endpoint (v1 Idea #11) — Already Covered

v2 already has:
- `/sse?replay=N` — replay last N events on SSE connect
- `Last-Event-ID` header support for reconnection
- `/api/events?limit=N` — historical event query
- `/api/nodes/{id}/conversation` — per-agent conversation history

A dedicated `/api/replay` endpoint would be redundant.

### Per-Agent Event Caching (v1 Idea #13) — Client-Side Only

Covered in Proposal E as part of the web panel's JavaScript EventCache. No server
changes needed.

### Cursor-Driven Panel Sync (v1 Idea #6) — Already Covered

`CursorFocusEvent` already exists. The LSP server already has `$/remora/cursorMoved`
concept via `api_cursor`. The web UI already receives it via SSE. Proposal E connects
the last mile (auto-switch panel). No separate proposal needed.

---

## 10. Implementation Order

Ordered by: foundation first, then features that build on them, then polish.

### Phase 1: Event Foundation (~2 hours)
1. **Proposal A: Event Tags** — Adds `tags` to Event and SubscriptionPattern.
   Pure data model change, no behavioral changes. Everything else works with or without it.

### Phase 2: Interaction Layer (~4 hours)
2. **Proposal B: Human-in-the-Loop** — Adds HumanInput events, response futures, web endpoint.
   Enables agents to ask questions.
3. **Proposal C: Rewrite Proposals via Cairn** — Adds proposal events, workspace-based review
   flow, web diff/accept/reject endpoints. Replaces direct `apply_rewrite()` with workspace
   sandbox → propose → review workflow. No new storage module — reuses Cairn workspaces.

### Phase 3: Editor Integration (~2 hours)
4. **Proposal D: Rich Hover + Code Actions** — Enhances LSP with graph context and
   interactive commands. Uses data from Phase 1-2 (shows pending proposals, input requests
   in hover).

### Phase 4: Web Panel (~4 hours)
5. **Proposal E: Agent Panel** — The big web UI change. Depends on Phases 2-3 for
   full functionality (human input UI, proposal diff view) but can be built incrementally.

### Phase 5: Observability (~2 hours)
6. **Proposal F: Kernel Events** — Adds fine-grained turn observability. Independent of
   other proposals.
7. **Proposal G: Bundle Rules** — Adds pattern-matched bundle resolution. Independent of
   other proposals.

### Estimated Total

~14 hours of focused implementation. Each phase is independently shippable and testable.
No phase requires all previous phases to be useful — Phase 1 is valuable alone, Phase 5
items are standalone enhancements.

### What Each Phase Enables

| Phase | Agents Can... | Humans Can... |
|-------|--------------|---------------|
| 1 | Tag events for pipeline routing | — |
| 2 | Ask humans questions, wait for answers | Respond to agent questions via web |
| 3 | Propose rewrites instead of direct writes | Review, accept, reject proposals via web |
| 4 | — | Chat with agents, trigger agents from editor |
| 5 | See agent chat, events, proposals in browser | Full interaction surface in the browser |
| 6 | Observe other agents' tool calls/model usage | See fine-grained turn traces |
| 7 | Get specialized bundles by name pattern | Configure per-pattern agent behavior in YAML |
