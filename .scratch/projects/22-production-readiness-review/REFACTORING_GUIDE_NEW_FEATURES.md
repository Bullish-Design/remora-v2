# Remora v2 — Refactoring Guide: New Features for Demo

**Date:** 2026-03-14
**Scope:** Step-by-step guide for new functionality required to deliver the full DEMO_PLAN.md
**Prerequisite:** Complete REFACTORING_GUIDE_FIXES.md first — all existing issues must be fixed before adding features
**Test command:** `devenv shell -- pytest tests/`

---

## Table of Contents

1. [Chat Response Display in Web UI](#1-chat-response-display-in-web-ui) — Add a chat panel that shows `AgentMessageEvent` content where `to_agent="user"`, making agent responses visible
2. [Standalone `remora lsp` Command](#2-standalone-remora-lsp-command) — New CLI command that runs the LSP server as a separate process connecting to a shared SQLite database
3. [Neovim LSP Client Configuration](#3-neovim-lsp-client-configuration) — Documented Lua config for neovim with CodeLens, hover, and didSave integration
4. [`/api/cursor` Endpoint and CursorFocusEvent](#4-apicursor-endpoint-and-cursorfocusevent) — Accept cursor position POSTs from neovim, resolve to nearest node, broadcast via SSE
5. [Web UI Companion Panel](#5-web-ui-companion-panel) — Sidebar panel that follows CursorFocusEvent, showing focused node context and agent workspace data
6. [Neovim Cursor Tracking Integration](#6-neovim-cursor-tracking-integration) — CursorHold autocmd that POSTs cursor position to `/api/cursor` for companion panel sync
7. [Graph Clustering by File](#7-graph-clustering-by-file) — Visual file boundaries on the Sigma.js graph with grouped layout and subtle backgrounds
8. [Prompt Tuning for Demo Project](#8-prompt-tuning-for-demo-project) — Optimize bundle prompts for Qwen3-4B with the calculator demo project

---

## 1. Chat Response Display in Web UI

**Priority:** Tier 1 (Must Have) | **Effort:** 2-3 hours | **Demo Act:** Act 4 — "Talk to Your Code"

### What This Enables

When a user sends a chat message to a node via the web UI, the agent processes it and calls `send_message` with `to_agent="user"`. Currently this emits an `AgentMessageEvent` that appears only as a raw event type name in the event log. After this feature, agent chat responses appear in a readable chat panel in the sidebar.

### Implementation

#### Step 1: Add AgentMessageEvent SSE handler in `index.html`

**File:** `src/remora/web/static/index.html` — after the `AgentErrorEvent` listener (line 283)

Add a new SSE event listener for `AgentMessageEvent`:

```javascript
evtSource.addEventListener("AgentMessageEvent", (event) => {
  const data = JSON.parse(event.data);
  if (data.to_agent === "user") {
    appendChatMessage(data.from_agent, data.content, "agent");
  }
  appendEventLine(`AgentMessageEvent: ${data.from_agent} → ${data.to_agent}`);
});
```

#### Step 2: Add chat message display area in HTML

**File:** `src/remora/web/static/index.html` — in the sidebar section

Add a chat messages container above the chat input. Find the existing chat input area and add a scrollable message list above it:

```html
<div id="chat-messages" style="
  max-height: 300px;
  overflow-y: auto;
  padding: 8px;
  margin-bottom: 8px;
  border: 1px solid #333;
  border-radius: 4px;
  background: #1a1a2e;
  display: none;
"></div>
```

#### Step 3: Add `appendChatMessage` JavaScript function

```javascript
function appendChatMessage(sender, content, role) {
  const container = document.getElementById("chat-messages");
  container.style.display = "block";
  const msg = document.createElement("div");
  msg.style.cssText = `
    margin-bottom: 8px;
    padding: 8px;
    border-radius: 6px;
    background: ${role === "agent" ? "#16213e" : "#0f3460"};
    color: #e0e0e0;
    font-size: 13px;
    word-wrap: break-word;
  `;
  const senderLabel = document.createElement("div");
  senderLabel.style.cssText = "font-weight: bold; margin-bottom: 4px; color: #64ffda; font-size: 11px;";
  senderLabel.textContent = sender.split("::").pop();
  msg.appendChild(senderLabel);

  const text = document.createElement("div");
  text.textContent = content;
  msg.appendChild(text);

  container.appendChild(msg);
  container.scrollTop = container.scrollHeight;
}
```

#### Step 4: Show user messages in chat too

Update the chat send handler to also display the user's outgoing message:

```javascript
document.getElementById("chat-send").addEventListener("click", async () => {
  const message = document.getElementById("chat-input").value.trim();
  if (!selectedNode || !message) return;
  appendChatMessage("You", message, "user");
  await fetch("/api/chat", {
    method: "POST",
    headers: {"content-type": "application/json"},
    body: JSON.stringify({ node_id: selectedNode, message })
  });
  document.getElementById("chat-input").value = "";
});
```

#### Step 5: Clear chat when selecting a different node

When the user clicks a different node, clear the chat panel:

```javascript
// Inside the node click handler
function selectNode(nodeId) {
  selectedNode = nodeId;
  document.getElementById("chat-messages").innerHTML = "";
  document.getElementById("chat-messages").style.display = "none";
  // ... existing node detail display code
}
```

### Test

```bash
devenv shell -- pytest tests/unit/test_web_server.py -v
```

Manual verification:
1. Start `remora start`, open web UI
2. Click a node, send a chat message
3. The agent's response should appear in the chat panel within a few seconds
4. The user's sent message should also be visible

---

## 2. Standalone `remora lsp` Command

**Priority:** Tier 2 (Full Neovim Demo) | **Effort:** 3-4 hours | **Demo Act:** Act 2 — "The Code Knows Itself"

### What This Enables

A separate `remora lsp` CLI command that runs the LSP server as a standalone process. It connects to the same SQLite database as the running `remora start` process, enabling neovim to get CodeLens annotations and hover data without stdio conflicts.

### Implementation

#### Step 1: Create read-only NodeStore and EventStore access

The LSP process needs read-only access to the SQLite database. Since SQLite in WAL mode supports concurrent readers, the LSP process can open its own connection.

**File:** `src/remora/__main__.py` — add new command

```python
LSP_PROJECT_ROOT_ARG = typer.Option(
    "--project-root",
    exists=True,
    file_okay=False,
    dir_okay=True,
)
LSP_LOG_LEVEL_ARG = typer.Option("--log-level")


@app.command("lsp")
def lsp_command(
    project_root: Annotated[Path, LSP_PROJECT_ROOT_ARG] = Path("."),
    config_path: Annotated[Path | None, CONFIG_ARG] = None,
    log_level: Annotated[str, LSP_LOG_LEVEL_ARG] = "INFO",
) -> None:
    """Start the LSP server standalone (connects to a running Remora instance's database)."""
    import sys
    _configure_logging(log_level, lsp_mode=True)
    asyncio.run(_lsp(project_root=project_root, config_path=config_path))
```

#### Step 2: Implement `_lsp` async function

```python
async def _lsp(
    *,
    project_root: Path,
    config_path: Path | None,
) -> None:
    import sys
    logger = logging.getLogger(__name__)
    project_root = project_root.resolve()
    config = load_config(config_path)

    db_path = project_root / config.workspace_root / "remora.db"
    if not db_path.exists():
        logger.error(
            "Database not found at %s. Is 'remora start' running?", db_path
        )
        raise typer.Exit(code=1)

    db = await open_database(db_path)
    node_store = NodeStore(db)
    # Don't create tables — the main process owns schema
    event_store = EventStore(
        db=db,
        event_bus=EventBus(),
        dispatcher=TriggerDispatcher(SubscriptionRegistry(db)),
    )

    lsp_server = create_lsp_server(node_store, event_store)
    logger.info("Starting standalone LSP server on stdin/stdout")
    try:
        lsp_server.start_io()
    finally:
        await db.close()
```

Note: Need to add missing imports at the top of `__main__.py`:

```python
from remora.core.graph import NodeStore
from remora.core.events import EventBus, EventStore, SubscriptionRegistry, TriggerDispatcher
```

#### Step 3: Handle the async-in-sync challenge

`lsp_server.start_io()` is synchronous (it runs its own event loop), but we have an async `db` connection. Restructure:

```python
@app.command("lsp")
def lsp_command(
    project_root: Annotated[Path, LSP_PROJECT_ROOT_ARG] = Path("."),
    config_path: Annotated[Path | None, CONFIG_ARG] = None,
    log_level: Annotated[str, LSP_LOG_LEVEL_ARG] = "INFO",
) -> None:
    """Start the LSP server standalone (connects to a running Remora instance's database)."""
    _configure_logging(log_level, lsp_mode=True)
    logger = logging.getLogger(__name__)
    project_root = project_root.resolve()
    config = load_config(config_path)

    db_path = project_root / config.workspace_root / "remora.db"
    if not db_path.exists():
        logger.error(
            "Database not found at %s. Is 'remora start' running?", db_path
        )
        raise typer.Exit(code=1)

    # pygls runs its own event loop, so we set up services within it
    # by making the LSP server create its DB connection on startup
    lsp_server = create_lsp_server_standalone(db_path)
    logger.info("Starting standalone LSP server on stdin/stdout")
    lsp_server.start_io()
```

This requires a new factory function:

#### Step 4: Add `create_lsp_server_standalone` to `lsp/server.py`

```python
async def _open_standalone_stores(db_path: Path) -> tuple[NodeStore, EventStore]:
    """Open read-only database connection for standalone LSP mode."""
    db = await open_database(db_path)
    node_store = NodeStore(db)
    event_store = EventStore(
        db=db,
        event_bus=EventBus(),
        dispatcher=TriggerDispatcher(SubscriptionRegistry(db)),
    )
    return node_store, event_store


def create_lsp_server_standalone(db_path: Path) -> LanguageServer:
    """Create an LSP server that opens its own DB connection for standalone mode."""
    server = LanguageServer("remora", "2.0.0")
    documents = DocumentStore()

    # Lazy-initialized stores — opened when first request arrives
    _stores: dict[str, Any] = {}

    async def _get_stores():
        if "node_store" not in _stores:
            ns, es = await _open_standalone_stores(db_path)
            _stores["node_store"] = ns
            _stores["event_store"] = es
        return _stores["node_store"], _stores["event_store"]

    @server.feature(lsp.TEXT_DOCUMENT_CODE_LENS)
    async def code_lens(params: lsp.CodeLensParams) -> list[lsp.CodeLens]:
        node_store, _ = await _get_stores()
        file_path = _uri_to_path(params.text_document.uri)
        nodes = await node_store.list_nodes(file_path=file_path)
        return [_node_to_lens(node) for node in nodes]

    @server.feature(lsp.TEXT_DOCUMENT_HOVER)
    async def hover(params: lsp.HoverParams) -> lsp.Hover | None:
        node_store, _ = await _get_stores()
        file_path = _uri_to_path(params.text_document.uri)
        nodes = await node_store.list_nodes(file_path=file_path)
        node = _find_node_at_line(nodes, params.position.line + 1)
        if node is None:
            return None
        return _node_to_hover(node)

    @server.feature(lsp.TEXT_DOCUMENT_DID_SAVE)
    async def did_save(params: lsp.DidSaveTextDocumentParams) -> None:
        _, event_store = await _get_stores()
        file_path = _uri_to_path(params.text_document.uri)
        await event_store.append(ContentChangedEvent(path=file_path, change_type="modified"))

    @server.feature(lsp.TEXT_DOCUMENT_DID_OPEN)
    async def did_open(params: lsp.DidOpenTextDocumentParams) -> None:
        documents.open(params.text_document.uri, params.text_document.text)

    @server.feature(lsp.TEXT_DOCUMENT_DID_CLOSE)
    async def did_close(params: lsp.DidCloseTextDocumentParams) -> None:
        documents.close(params.text_document.uri)

    @server.feature(lsp.TEXT_DOCUMENT_DID_CHANGE)
    async def did_change(params: lsp.DidChangeTextDocumentParams) -> None:
        documents.apply_changes(params.text_document.uri, params.content_changes)

    return server
```

#### Step 5: Update `lsp/__init__.py` exports

```python
from remora.lsp.server import create_lsp_server, create_lsp_server_standalone

__all__ = ["create_lsp_server", "create_lsp_server_standalone"]
```

### Test

```bash
devenv shell -- pytest tests/unit/test_lsp_server.py -v
```

Manual verification:
1. Start `remora start --project-root ./demo-project`
2. In another terminal: `remora lsp --project-root ./demo-project`
3. Or configure neovim to spawn `remora lsp` (see Section 3)
4. Open a Python file in neovim — CodeLens annotations should appear

---

## 3. Neovim LSP Client Configuration

**Priority:** Tier 2 (Full Neovim Demo) | **Effort:** 1-2 hours | **Demo Act:** Act 2

### What This Enables

A documented, tested neovim LSP configuration that connects to the Remora LSP server, shows CodeLens annotations above each discovered function/class, and provides hover metadata.

### Implementation

#### Step 1: Create the Lua configuration file

**File:** `contrib/neovim/remora.lua`

```lua
-- Remora LSP integration for Neovim
-- Copy to ~/.config/nvim/lua/remora.lua and require("remora") in init.lua

local M = {}

--- Default configuration
M.config = {
  -- File types to attach the LSP client to
  filetypes = { "python", "markdown", "toml" },
  -- Command to start the LSP server
  cmd = { "remora", "lsp" },
  -- Marker file for project root detection
  root_marker = "remora.yaml",
  -- Remora web server URL (for cursor tracking)
  web_url = "http://localhost:8080",
  -- Enable cursor tracking (posts to /api/cursor)
  cursor_tracking = true,
  -- Cursor tracking debounce in milliseconds
  cursor_debounce_ms = 300,
}

--- Start the Remora LSP client
function M.setup(opts)
  opts = vim.tbl_deep_extend("force", M.config, opts or {})

  -- Auto-attach LSP on matching filetypes
  vim.api.nvim_create_autocmd("FileType", {
    pattern = opts.filetypes,
    group = vim.api.nvim_create_augroup("RemoraLSP", { clear = true }),
    callback = function()
      local root = vim.fs.root(0, { opts.root_marker })
      if not root then return end
      vim.lsp.start({
        name = "remora",
        cmd = vim.list_extend(vim.deepcopy(opts.cmd), { "--project-root", root }),
        root_dir = root,
        capabilities = vim.lsp.protocol.make_client_capabilities(),
      })
    end,
  })

  -- Auto-refresh CodeLens on save and buffer enter
  vim.api.nvim_create_autocmd({ "BufWritePost", "BufEnter", "InsertLeave" }, {
    group = vim.api.nvim_create_augroup("RemoraCodeLens", { clear = true }),
    callback = function()
      local clients = vim.lsp.get_clients({ name = "remora" })
      if #clients > 0 then
        vim.lsp.codelens.refresh()
      end
    end,
  })

  -- Cursor tracking (optional)
  if opts.cursor_tracking then
    M._setup_cursor_tracking(opts)
  end
end

--- Set up CursorHold-based cursor tracking
function M._setup_cursor_tracking(opts)
  vim.api.nvim_create_autocmd({ "CursorHold", "CursorHoldI" }, {
    group = vim.api.nvim_create_augroup("RemoraCursor", { clear = true }),
    callback = function()
      local file = vim.api.nvim_buf_get_name(0)
      if file == "" then return end
      local cursor = vim.api.nvim_win_get_cursor(0)
      local url = opts.web_url .. "/api/cursor"
      local payload = vim.fn.json_encode({
        file_path = file,
        line = cursor[1],
        character = cursor[2],
      })
      vim.fn.jobstart({
        "curl", "-s", "-X", "POST", url,
        "-H", "Content-Type: application/json",
        "-d", payload,
      }, { detach = true })
    end,
  })
end

return M
```

#### Step 2: Create minimal `init.lua` example

**File:** `contrib/neovim/example-init.lua`

```lua
-- Minimal Remora configuration for neovim
-- Add to your init.lua:

-- Option 1: Default settings (assumes remora is on PATH)
require("remora").setup()

-- Option 2: Custom settings
require("remora").setup({
  web_url = "http://localhost:8080",
  cursor_tracking = true,
  filetypes = { "python" },
})
```

#### Step 3: Add to DEMO_PLAN prerequisites

Document that the neovim config must be in place before the demo.

### Test

Manual verification:
1. Copy `contrib/neovim/remora.lua` to `~/.config/nvim/lua/remora.lua`
2. Add `require("remora").setup()` to `init.lua`
3. Start `remora start --project-root ./demo-project`
4. Open `demo-project/src/calculator.py` in neovim
5. Verify: CodeLens annotations appear above each function (`Remora: idle`)
6. Verify: Hover over a function shows node metadata
7. Verify: Save a file triggers reconciliation (check remora logs)

---

## 4. `/api/cursor` Endpoint and CursorFocusEvent

**Priority:** Tier 2 (Full Neovim Demo) | **Effort:** 1-2 hours | **Demo Act:** Act 2 — Companion Sidebar

### What This Enables

Neovim posts cursor position to `/api/cursor`. The server resolves the position to the nearest node and broadcasts a `CursorFocusEvent` via SSE. The web UI companion panel listens for this event to show context for the cursor-focused node.

### Implementation

#### Step 1: Add `CursorFocusEvent` to event types

**File:** `src/remora/core/events/types.py`

```python
class CursorFocusEvent(Event):
    """Emitted when the editor cursor focuses on a code element."""
    file_path: str
    line: int
    character: int
    node_id: str | None = None
    node_name: str | None = None
    node_type: str | None = None
```

Update `__all__`:

```python
__all__ = [
    ...,
    "CursorFocusEvent",
]
```

Update `src/remora/core/events/__init__.py` to export `CursorFocusEvent`.

#### Step 2: Add `/api/cursor` endpoint to web server

**File:** `src/remora/web/server.py`

Add the import:

```python
from remora.core.events import AgentMessageEvent, CursorFocusEvent
```

Add the endpoint function inside `create_app`:

```python
async def api_cursor(request: Request) -> JSONResponse:
    data = await request.json()
    file_path = str(data.get("file_path", "")).strip()
    line = int(data.get("line", 0))
    character = int(data.get("character", 0))

    if not file_path:
        return JSONResponse({"error": "file_path is required"}, status_code=400)

    # Resolve cursor to nearest node
    nodes = await node_store.list_nodes(file_path=file_path)
    # Find narrowest node containing this line
    containing = [n for n in nodes if n.start_line <= line <= n.end_line]
    focused = min(containing, key=lambda n: n.end_line - n.start_line) if containing else None

    event = CursorFocusEvent(
        file_path=file_path,
        line=line,
        character=character,
        node_id=focused.node_id if focused else None,
        node_name=focused.full_name if focused else None,
        node_type=focused.node_type.value if focused and hasattr(focused.node_type, "value") else None,
    )

    # Emit directly to bus (no need for DB persistence — cursor events are ephemeral)
    await event_bus.emit(event)

    return JSONResponse({
        "status": "ok",
        "node_id": focused.node_id if focused else None,
    })
```

Add the route:

```python
routes = [
    ...,
    Route("/api/cursor", endpoint=api_cursor, methods=["POST"]),
    Route("/sse", endpoint=sse_stream),
]
```

#### Step 3: Handle CursorFocusEvent in SSE

The SSE stream already streams all bus events. Since `CursorFocusEvent` goes through the bus (not the event store), we need to make sure it reaches SSE clients. The `event_bus.stream()` in the SSE handler will pick it up automatically since `subscribe_all` captures all events.

However, `CursorFocusEvent` inherits from `Event` and has `model_dump()`, so the live SSE serialization at line 116-117 will work as-is.

### Test

```bash
devenv shell -- pytest tests/unit/test_web_server.py tests/unit/test_events.py -v
```

Add tests:

```python
async def test_cursor_endpoint_resolves_node(client, node_store):
    # Create a node at lines 1-5
    node = Node(node_id="test::func", name="func", ...)
    await node_store.upsert_node(node)

    response = await client.post("/api/cursor", json={
        "file_path": "/path/to/test.py",
        "line": 3,
        "character": 0,
    })
    assert response.status_code == 200
    data = response.json()
    assert data["node_id"] == "test::func"
```

---

## 5. Web UI Companion Panel

**Priority:** Tier 2 (Full Neovim Demo) | **Effort:** 2-3 hours | **Demo Act:** Act 2 — Companion Sidebar

### What This Enables

The web UI sidebar shows a "companion" panel that updates when the editor cursor moves. It shows the focused node's source code, metadata, workspace state, and recent events. This is the "wow moment" — the audience sees the web UI following along as the presenter navigates code in neovim.

### Implementation

#### Step 1: Add companion panel HTML

**File:** `src/remora/web/static/index.html` — in the sidebar

Add a companion section above or alongside the existing node details:

```html
<div id="companion-panel" style="
  display: none;
  padding: 12px;
  margin-bottom: 12px;
  border: 1px solid #333;
  border-radius: 6px;
  background: #16213e;
">
  <div style="font-size: 11px; color: #888; margin-bottom: 4px;">
    FOLLOWING CURSOR
  </div>
  <div id="companion-node-name" style="
    font-weight: bold;
    font-size: 16px;
    color: #64ffda;
    margin-bottom: 8px;
  "></div>
  <div id="companion-meta" style="
    font-size: 12px;
    color: #aaa;
    margin-bottom: 8px;
  "></div>
  <div id="companion-source" style="
    font-family: monospace;
    font-size: 11px;
    background: #0d1117;
    padding: 8px;
    border-radius: 4px;
    max-height: 200px;
    overflow-y: auto;
    white-space: pre-wrap;
    color: #c9d1d9;
  "></div>
</div>
```

#### Step 2: Add CursorFocusEvent SSE handler

```javascript
evtSource.addEventListener("CursorFocusEvent", (event) => {
  const data = JSON.parse(event.data);
  const panel = document.getElementById("companion-panel");

  if (!data.node_id) {
    panel.style.display = "none";
    return;
  }

  panel.style.display = "block";
  document.getElementById("companion-node-name").textContent = data.node_name || data.node_id;
  document.getElementById("companion-meta").textContent =
    `${data.node_type || "unknown"} · ${data.file_path}:${data.line}`;

  // Fetch full node details
  fetch(`/api/nodes/${encodeURIComponent(data.node_id)}`)
    .then(r => r.json())
    .then(node => {
      if (node.source_code) {
        document.getElementById("companion-source").textContent = node.source_code;
      } else {
        document.getElementById("companion-source").textContent = "(no source)";
      }
    })
    .catch(() => {
      document.getElementById("companion-source").textContent = "(failed to load)";
    });

  // Also highlight the node in the graph
  if (graph.hasNode(data.node_id)) {
    // Pulse effect — briefly enlarge the node
    const prevSize = graph.getNodeAttribute(data.node_id, "size");
    graph.setNodeAttribute(data.node_id, "size", prevSize * 1.5);
    renderer.refresh();
    setTimeout(() => {
      if (graph.hasNode(data.node_id)) {
        graph.setNodeAttribute(data.node_id, "size", prevSize);
        renderer.refresh();
      }
    }, 500);
  }
});
```

#### Step 3: Graph camera follows focused node

When a `CursorFocusEvent` arrives, smoothly animate the graph camera to center on the focused node:

```javascript
// Inside the CursorFocusEvent handler, after the fetch
if (graph.hasNode(data.node_id)) {
  const nodePos = graph.getNodeAttributes(data.node_id);
  renderer.getCamera().animate(
    { x: nodePos.x, y: nodePos.y, ratio: 0.5 },
    { duration: 300 }
  );
}
```

### Test

Manual verification:
1. Start remora, open web UI and neovim side by side
2. Move cursor in neovim between functions
3. Web UI companion panel should update within 300-500ms showing the focused function
4. Graph should center on the focused node

---

## 6. Neovim Cursor Tracking Integration

**Priority:** Tier 3 (Wow Factor) | **Effort:** 1 hour | **Demo Act:** Act 2

### What This Enables

This is the neovim-side integration for the companion panel. When the cursor rests on a function for ~300ms (controlled by `updatetime`), neovim POSTs the cursor position to `/api/cursor`.

### Implementation

Already covered in the `contrib/neovim/remora.lua` file from Section 3. The `_setup_cursor_tracking` function handles this via `CursorHold` autocmd.

#### Additional optimization: Set `updatetime`

Add to the setup function:

```lua
-- Set updatetime for faster CursorHold triggering (default is 4000ms)
if vim.o.updatetime > 500 then
  vim.o.updatetime = 300
end
```

Note: This affects all CursorHold behavior in neovim, not just Remora. Users who already have `updatetime` set low won't be affected.

#### Debounce optimization

To avoid flooding the API during rapid cursor movement, add debouncing:

```lua
local _cursor_timer = nil

function M._setup_cursor_tracking(opts)
  vim.api.nvim_create_autocmd({ "CursorHold", "CursorHoldI" }, {
    group = vim.api.nvim_create_augroup("RemoraCursor", { clear = true }),
    callback = function()
      if _cursor_timer then
        _cursor_timer:stop()
        _cursor_timer = nil
      end
      _cursor_timer = vim.defer_fn(function()
        _cursor_timer = nil
        local file = vim.api.nvim_buf_get_name(0)
        if file == "" then return end
        local cursor = vim.api.nvim_win_get_cursor(0)
        local url = opts.web_url .. "/api/cursor"
        local payload = vim.fn.json_encode({
          file_path = file,
          line = cursor[1],
          character = cursor[2],
        })
        vim.fn.jobstart({
          "curl", "-s", "-X", "POST", url,
          "-H", "Content-Type: application/json",
          "-d", payload,
        }, { detach = true })
      end, 0)
    end,
  })
end
```

### Test

Manual verification:
1. Open neovim with remora LSP attached
2. Open the browser network tab to watch `/api/cursor` requests
3. Move cursor between functions — requests should appear with ~300ms debounce
4. Companion panel should update in the web UI

---

## 7. Graph Clustering by File

**Priority:** Tier 3 (Wow Factor) | **Effort:** 2-3 hours | **Demo Act:** Act 1

### What This Enables

Instead of randomly positioned nodes, nodes from the same file cluster together visually. Each file forms a visual group with a subtle background color. This makes the graph immediately readable — the audience can see "those are the calculator functions, those are the validator functions."

### Implementation

#### Step 1: Assign initial positions by file during graph load

**File:** `src/remora/web/static/index.html` — in the `loadGraph` function

Currently, `deterministicPosition(nodeId)` uses a hash to place nodes. Instead, calculate positions based on file path:

```javascript
// File-based clustering
const fileGroups = {};
let fileIndex = 0;

function getFileCluster(filePath) {
  if (!fileGroups[filePath]) {
    const angle = (fileIndex / 6) * 2 * Math.PI;  // Arrange in a circle
    const radius = 3;
    fileGroups[filePath] = {
      cx: radius * Math.cos(angle),
      cy: radius * Math.sin(angle),
      index: fileIndex,
      count: 0,
    };
    fileIndex++;
  }
  const cluster = fileGroups[filePath];
  const offset = cluster.count * 0.3;
  cluster.count++;
  return {
    x: cluster.cx + (Math.random() - 0.5) * 1.5,
    y: cluster.cy + (Math.random() - 0.5) * 1.5,
  };
}
```

Update `loadGraph` to use file-based positioning:

```javascript
nodes.forEach(node => {
  const filePath = node.file_path || "";
  const pos = filePath ? getFileCluster(filePath) : deterministicPosition(node.node_id);
  graph.addNode(node.node_id, {
    label: node.name || node.node_id.split("::").pop(),
    size: 8,
    x: pos.x,
    y: pos.y,
    node_type: node.node_type || "function",
    file_path: filePath,
    color: nodeColor(node.node_type, node.status || "idle"),
  });
});
```

#### Step 2: Add file labels

After the graph loads, add label nodes or use Sigma.js node reducers to show file names as larger, dimmer labels at each cluster center:

```javascript
// After nodes are added, add file label pseudo-nodes
Object.entries(fileGroups).forEach(([filePath, cluster]) => {
  const labelId = `__label__${filePath}`;
  const shortName = filePath.split("/").pop();
  graph.addNode(labelId, {
    label: shortName,
    size: 3,
    x: cluster.cx,
    y: cluster.cy,
    color: "#444",
    node_type: "__label__",
    hidden: false,
    type: "label",
  });
});
```

Use a Sigma.js node reducer to render label nodes differently (larger text, no circle):

```javascript
const renderer = new Sigma(graph, container, {
  ...,
  nodeReducer: (node, data) => {
    if (data.node_type === "__label__") {
      return { ...data, size: 2, color: "#555", label: data.label, labelSize: 14 };
    }
    return data;
  },
});
```

#### Step 3: Color-code file backgrounds (optional enhancement)

Use a Sigma.js `beforeRender` hook to draw translucent convex hulls around file groups. This is more complex and can be deferred if time is limited.

### Test

Manual verification:
1. Start remora with the demo project
2. Open web UI — nodes should cluster by file
3. File labels should appear near each cluster
4. ForceAtlas2 layout should keep clusters roughly together

---

## 8. Prompt Tuning for Demo Project

**Priority:** Tier 3 (Wow Factor) | **Effort:** 2 hours | **Demo Act:** Acts 3 & 4

### What This Enables

The agent prompts are tuned for the Qwen3-4B model and the calculator demo project. This means agents give coherent, contextual responses during the demo instead of generic or confused output.

### Implementation

#### Step 1: Enhance code-agent system prompt with explicit tool instructions

**File:** `bundles/code-agent/bundle.yaml` — `system_prompt_extension`

Replace the current extension with more explicit instructions for a small model:

```yaml
system_prompt_extension: |
  You are an autonomous AI agent embodying a specific code element (function, class, or method).

  ## Your Identity
  You ARE the code element described in the user message. Speak in the first person.
  When asked "what do you do?" answer as if you ARE the function.

  ## Tools Available
  - send_message: Send a message to another agent or to "user" for chat. ALWAYS use this to reply to the user.
  - query_agents: Search the node graph for related agents. Use this to find callers, callees, and siblings.
  - rewrite_self: Modify your own source code. Use carefully.
  - reflect: Write notes to your workspace for future reference.
  - kv_get/kv_set: Read/write your persistent memory.
  - subscribe/unsubscribe: Manage your event subscriptions.

  ## Responding to Chat Messages
  When you receive a message from the user:
  1. Read and understand the question
  2. Use query_agents to find relevant context if needed
  3. Use send_message with to_node_id="user" to send your response
  4. Keep responses concise but informative (2-4 sentences)

  ## Responding to Code Changes
  When triggered by a NodeChangedEvent:
  1. Review the change in your source code
  2. Use reflect to note what changed
  3. Use kv_set to update your understanding
  4. Do NOT automatically rewrite code unless specifically asked

prompts:
  chat: |
    You received a direct message from a user. They want to talk to you about your code.
    Read their message carefully. Use your tools to gather context, then respond using send_message with to_node_id="user".
    Be concise, specific, and speak in the first person as the code element.
  reactive: |
    A change was detected in your code or a related element. Review what happened.
    Use reflect to update your understanding. Only respond if the change is significant.
```

#### Step 2: Enhance directory-agent prompts

**File:** `bundles/directory-agent/bundle.yaml`

```yaml
system_prompt_extension: |
  You are an autonomous AI agent managing a directory in the project.

  ## Your Identity
  You manage all code elements within your directory. You are the coordinator.

  ## Tools Available
  - list_children: See all child nodes in your directory.
  - broadcast_children: Send a message to all children.
  - summarize_tree: Get a summary of your directory structure.
  - get_parent: Get info about your parent directory.
  - send_message: Communicate with other agents or the user.
  - query_agents: Search the full node graph.

  ## Responding to Changes
  When a child element changes, you may be notified. Review the change and decide if coordination is needed.
  Only broadcast to children when something affects multiple elements.
```

#### Step 3: Add description comments to tool .pym files

Add a header comment to each tool file so the description extraction (from REFACTORING_GUIDE_FIXES.md Section 8) has content to work with:

**`bundles/system/tools/send_message.pym`** — add first line:
```python
# Send a message to another agent by node_id, or to "user" to reply to chat.
```

**`bundles/system/tools/query_agents.pym`** — add first line:
```python
# Query the node graph for agents. Filter by node_type, status, or file_path pattern.
```

**`bundles/system/tools/reflect.pym`** — add first line:
```python
# Write a reflection note to your workspace. Used to record observations and maintain memory.
```

**`bundles/system/tools/kv_get.pym`** — add first line:
```python
# Read a value from your persistent key-value store by key.
```

**`bundles/system/tools/kv_set.pym`** — add first line:
```python
# Write a key-value pair to your persistent store. Used for remembering facts between turns.
```

**`bundles/system/tools/broadcast.pym`** — add first line:
```python
# Broadcast a message to all agents whose node_id matches a glob pattern.
```

**`bundles/system/tools/subscribe.pym`** — add first line:
```python
# Subscribe to events matching specified event_types and an optional path glob.
```

**`bundles/system/tools/unsubscribe.pym`** — add first line:
```python
# Remove a subscription by subscription_id.
```

**`bundles/code-agent/tools/rewrite_self.pym`** — add first line:
```python
# Rewrite this code element's source code with new_source. Use carefully — changes are applied immediately.
```

**`bundles/code-agent/tools/scaffold.pym`** — add first line:
```python
# Create scaffolding files in the agent's workspace for organizing analysis and notes.
```

**`bundles/directory-agent/tools/list_children.pym`** — add first line:
```python
# List all child nodes (functions, classes, subdirectories) in this directory.
```

**`bundles/directory-agent/tools/broadcast_children.pym`** — add first line:
```python
# Send a message to all child nodes in this directory.
```

**`bundles/directory-agent/tools/summarize_tree.pym`** — add first line:
```python
# Summarize the full directory tree structure below this node.
```

**`bundles/directory-agent/tools/get_parent.pym`** — add first line:
```python
# Get information about this node's parent directory agent.
```

#### Step 4: Test with actual vLLM

After making prompt changes, test the full flow:

1. Start vLLM with Qwen3-4B
2. Start remora with the demo project
3. Send a chat message: "What do you do and who depends on you?"
4. Verify the response is coherent, contextual, and uses tools correctly
5. Edit a file, verify the reactive response is reasonable
6. Iterate on prompts until responses are consistently good

### Test

```bash
devenv shell -- pytest tests/ -v
```

Prompt changes don't affect unit tests, but verify no YAML syntax errors in bundle configs.

---

*End of Refactoring Guide: New Features for Demo*
