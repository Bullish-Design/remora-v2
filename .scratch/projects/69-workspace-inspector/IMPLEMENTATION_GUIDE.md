# Implementation Guide — Workspace Inspector

This guide walks through the exact changes needed, file by file, with precise insertion points. Follow each step in order. Do not skip steps or reorder them.

**Files to modify (4 total):**

1. `src/remora/web/routes/nodes.py` — three new API endpoints
2. `src/remora/web/static/index.html` — modal HTML + CSS
3. `src/remora/web/static/panels.js` — inspect button visibility
4. `src/remora/web/static/main.js` — modal open/close/tab logic

---

## Step 1: Backend endpoints — `src/remora/web/routes/nodes.py`

### 1a. Add the fsdantic import

At the top of the file, after the existing `from remora.web.deps import _deps_from_request` line (line 11), add:

```python
from fsdantic import FileNotFoundError as FsdFileNotFoundError
```

### 1b. Add the three endpoint functions

Insert these three functions **after** `api_conversation` (after line 112) and **before** the `def routes()` function (line 115):

```python
async def api_workspace_files(request: Request) -> JSONResponse:
    """List all file paths in a node's Cairn workspace."""
    deps = _deps_from_request(request)
    if deps.workspace_service is None:
        return JSONResponse({"error": "No workspace service"}, status_code=503)
    node_id = request.path_params["node_id"]
    if not deps.workspace_service.has_workspace(node_id):
        return JSONResponse({"error": "No workspace for this node"}, status_code=404)
    workspace = await deps.workspace_service.get_agent_workspace(node_id)
    paths = await workspace.list_all_paths()
    return JSONResponse({"node_id": node_id, "files": paths})


async def api_workspace_file_content(request: Request) -> JSONResponse:
    """Read a single file from a node's Cairn workspace."""
    deps = _deps_from_request(request)
    if deps.workspace_service is None:
        return JSONResponse({"error": "No workspace service"}, status_code=503)
    node_id = request.path_params["node_id"]
    file_path = request.path_params["file_path"]
    workspace = await deps.workspace_service.get_agent_workspace(node_id)
    try:
        content = await workspace.read(file_path)
    except (FileNotFoundError, FsdFileNotFoundError):
        return JSONResponse({"error": f"File not found: {file_path}"}, status_code=404)
    return JSONResponse({"path": file_path, "content": content})


async def api_workspace_kv(request: Request) -> JSONResponse:
    """Dump all KV entries from a node's Cairn workspace."""
    deps = _deps_from_request(request)
    if deps.workspace_service is None:
        return JSONResponse({"error": "No workspace service"}, status_code=503)
    node_id = request.path_params["node_id"]
    if not deps.workspace_service.has_workspace(node_id):
        return JSONResponse({"error": "No workspace for this node"}, status_code=404)
    workspace = await deps.workspace_service.get_agent_workspace(node_id)
    keys = await workspace.kv_list()
    entries: dict[str, Any] = {}
    for key in keys:
        entries[key] = await workspace.kv_get(key)
    return JSONResponse({"node_id": node_id, "entries": entries})
```

### 1c. Register routes

In the `routes()` function, add the three new routes. They **must go before** the catch-all `Route("/api/nodes/{node_id:path}", endpoint=api_node)` on line 123, otherwise the path parameter greedily matches and these routes will never trigger.

Insert them right after the `/companion` route and before the catch-all:

```python
def routes() -> list[Route]:
    return [
        Route("/api/nodes", endpoint=api_nodes),
        Route("/api/edges", endpoint=api_all_edges),
        Route("/api/nodes/{node_id:path}/edges", endpoint=api_edges),
        Route("/api/nodes/{node_id:path}/relationships", endpoint=api_node_relationships),
        Route("/api/nodes/{node_id:path}/conversation", endpoint=api_conversation),
        Route("/api/nodes/{node_id:path}/companion", endpoint=api_node_companion),
        Route("/api/nodes/{node_id:path}/workspace/files/{file_path:path}", endpoint=api_workspace_file_content),
        Route("/api/nodes/{node_id:path}/workspace/files", endpoint=api_workspace_files),
        Route("/api/nodes/{node_id:path}/workspace/kv", endpoint=api_workspace_kv),
        Route("/api/nodes/{node_id:path}", endpoint=api_node),
    ]
```

**Route ordering matters.** The `file_content` route (with `{file_path:path}`) must come before the bare `workspace/files` route, and all three must come before the `{node_id:path}` catch-all.

### 1d. Update `__all__`

Add the three new function names to the `__all__` list (keep it sorted):

```python
__all__ = [
    "api_all_edges",
    "api_conversation",
    "api_edges",
    "api_node",
    "api_node_companion",
    "api_node_relationships",
    "api_nodes",
    "api_workspace_file_content",
    "api_workspace_files",
    "api_workspace_kv",
    "routes",
]
```

### Verify step 1

Run `devenv shell -- python -c "from remora.web.routes.nodes import routes; print(len(routes()))"` — should print `10` (was 7).

---

## Step 2: Modal CSS — `src/remora/web/static/index.html`

Add the following CSS rules inside the `<style>` block, just **before** the closing `</style>` tag (currently at line 352):

```css
    /* Workspace inspector modal */
    .ws-modal-backdrop {
      position: fixed;
      inset: 0;
      z-index: 100;
      background: rgba(0, 0, 0, 0.55);
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .ws-modal {
      width: min(860px, 90vw);
      height: min(580px, 85vh);
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 12px;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }
    .ws-modal-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 12px 16px;
      border-bottom: 1px solid var(--line);
      font-size: 0.92rem;
      font-weight: 600;
    }
    .ws-modal-header button {
      background: transparent;
      color: var(--muted);
      font-size: 1.1rem;
      padding: 4px 8px;
      margin: 0;
      cursor: pointer;
      border: none;
    }
    .ws-modal-header button:hover { color: var(--ink); }
    .ws-tab-bar {
      display: flex;
      gap: 0;
      border-bottom: 1px solid var(--line);
    }
    .ws-tab {
      flex: 1;
      padding: 8px 12px;
      font-size: 0.82rem;
      background: transparent;
      color: var(--muted);
      border: none;
      border-bottom: 2px solid transparent;
      cursor: pointer;
      margin: 0;
      border-radius: 0;
    }
    .ws-tab.active {
      color: var(--accent);
      border-bottom-color: var(--accent);
    }
    .ws-tab-panel {
      flex: 1;
      overflow: hidden;
      display: flex;
    }
    .ws-files-split {
      display: flex;
      flex: 1;
      overflow: hidden;
    }
    .ws-file-list {
      width: 240px;
      min-width: 180px;
      overflow-y: auto;
      border-right: 1px solid var(--line);
      padding: 6px 0;
      font-size: 0.78rem;
    }
    .ws-file-entry {
      padding: 5px 12px;
      cursor: pointer;
      color: var(--muted);
      word-break: break-all;
    }
    .ws-file-entry:hover { background: rgba(255, 255, 255, 0.04); color: var(--ink); }
    .ws-file-entry.active { background: rgba(34, 211, 238, 0.1); color: var(--accent); }
    .ws-file-content {
      flex: 1;
      overflow: auto;
      margin: 0;
      padding: 12px;
      font-size: 0.78rem;
      white-space: pre-wrap;
      word-break: break-word;
      color: var(--ink);
      background: #0d1520;
    }
    .ws-kv-list {
      flex: 1;
      overflow-y: auto;
      padding: 10px 14px;
    }
    .ws-kv-entry {
      margin-bottom: 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }
    .ws-kv-key {
      padding: 6px 10px;
      font-size: 0.76rem;
      font-weight: 600;
      color: var(--accent);
      background: rgba(255, 255, 255, 0.03);
      border-bottom: 1px solid var(--line);
      word-break: break-all;
    }
    .ws-kv-value {
      padding: 8px 10px;
      font-size: 0.76rem;
      white-space: pre-wrap;
      word-break: break-word;
      color: var(--muted);
      max-height: 180px;
      overflow: auto;
    }
    .ws-empty {
      padding: 24px;
      text-align: center;
      color: var(--muted);
      font-size: 0.85rem;
    }
    .ws-error {
      padding: 16px;
      color: var(--error);
      font-size: 0.85rem;
    }
    #btn-inspect-workspace {
      font-size: 0.78rem;
      padding: 5px 10px;
      background: transparent;
      border: 1px solid var(--line);
      color: var(--muted);
      cursor: pointer;
    }
    #btn-inspect-workspace:hover {
      color: var(--accent);
      border-color: var(--accent);
    }
```

---

## Step 3: Modal HTML + Inspect button — `src/remora/web/static/index.html`

### 3a. Add the Inspect button in the sidebar

Find this section (around line 423-426):

```html
    <section>
      <h2 id="node-name">Select a node</h2>
      <div id="node-details"></div>
    </section>
```

Change it to:

```html
    <section>
      <h2 id="node-name">Select a node</h2>
      <div id="node-inspect-bar" style="display: none; margin-bottom: 8px;">
        <button id="btn-inspect-workspace" type="button">Inspect workspace</button>
      </div>
      <div id="node-details"></div>
    </section>
```

### 3b. Add the modal markup

Insert this **before** the closing `</body>` tag and **after** the `</aside>` closing tag. Currently the end of the file looks like:

```html
  </aside>

  <script type="module" src="/static/main.js"></script>
</body>
```

Change it to:

```html
  </aside>

  <div id="workspace-modal" class="ws-modal-backdrop" hidden>
    <div class="ws-modal">
      <div class="ws-modal-header">
        <span id="ws-modal-title">Workspace</span>
        <button id="ws-modal-close" type="button">&times;</button>
      </div>
      <div class="ws-tab-bar">
        <button class="ws-tab active" data-ws-tab="files">Files</button>
        <button class="ws-tab" data-ws-tab="kv">KV Store</button>
      </div>
      <div id="ws-tab-files" class="ws-tab-panel">
        <div class="ws-files-split">
          <div id="ws-file-list" class="ws-file-list"></div>
          <pre id="ws-file-content" class="ws-file-content">(select a file)</pre>
        </div>
      </div>
      <div id="ws-tab-kv" class="ws-tab-panel" hidden>
        <div id="ws-kv-list" class="ws-kv-list"></div>
      </div>
    </div>
  </div>

  <script type="module" src="/static/main.js"></script>
</body>
```

---

## Step 4: Inspect button visibility — `src/remora/web/static/panels.js`

### 4a. Cache the element reference

Inside `createPanels`, at the top where all the `doc.getElementById` calls are (lines 19-34), add after the existing element lookups:

```js
  const inspectBarEl = doc.getElementById("node-inspect-bar");
```

### 4b. Show the inspect bar when a node is selected

In the `setNode(node)` function, add one line to show the bar when a node is present, and hide it when null.

After line 52 (`if (selectionHelperEl) selectionHelperEl.style.display = "none";`), add:

```js
    if (inspectBarEl) inspectBarEl.style.display = "";
```

And inside the `if (!node)` branch (after line 48, `if (selectionHelperEl) selectionHelperEl.style.display = "";`), add:

```js
      if (inspectBarEl) inspectBarEl.style.display = "none";
```

So the full `setNode` function will look like this:

```js
  function setNode(node) {
    if (nodeNameEl) {
      nodeNameEl.textContent = node ? (node.full_name || node.name || node.node_id) : "Select a node";
    }
    if (!nodeDetailsEl) return;
    if (!node) {
      if (selectionHelperEl) selectionHelperEl.style.display = "";
      if (inspectBarEl) inspectBarEl.style.display = "none";
      nodeDetailsEl.innerHTML = "";
      return;
    }
    if (selectionHelperEl) selectionHelperEl.style.display = "none";
    if (inspectBarEl) inspectBarEl.style.display = "";
    const summary = [
      `id: ${node.node_id}`,
      `type: ${node.node_type}`,
      `status: ${node.status || "idle"}`,
      `file: ${node.file_path || ""}`,
      `lines: ${node.start_line ?? "?"}-${node.end_line ?? "?"}`,
    ].join("\n");
    nodeDetailsEl.innerHTML = `<pre>${escHtml(summary)}\n\n${escHtml(node.text || "")}</pre>`;
  }
```

No changes to `clearNodeSelection` — it calls `setNode(null)`, which will hide the bar.

---

## Step 5: Modal logic — `src/remora/web/static/main.js`

### 5a. Add the `wireWorkspaceInspector` function

Insert this **before** the `async function start()` function (currently at line 772). Place it after `wireSidebarResize` ends (after line 770):

```js
function wireWorkspaceInspector() {
  const modal = document.getElementById("workspace-modal");
  const titleEl = document.getElementById("ws-modal-title");
  const closeBtn = document.getElementById("ws-modal-close");
  const fileListEl = document.getElementById("ws-file-list");
  const fileContentEl = document.getElementById("ws-file-content");
  const kvListEl = document.getElementById("ws-kv-list");
  const tabFilesEl = document.getElementById("ws-tab-files");
  const tabKvEl = document.getElementById("ws-tab-kv");
  const inspectBtn = document.getElementById("btn-inspect-workspace");
  if (!modal) return;

  let activeNodeId = null;
  let kvLoaded = false;

  function show(nodeId) {
    activeNodeId = nodeId;
    kvLoaded = false;
    const attrs = graph.hasNode(nodeId) ? graph.getNodeAttributes(nodeId) : {};
    if (titleEl) titleEl.textContent = attrs.full_name || attrs.node_name || nodeId;
    fileListEl.innerHTML = "";
    fileContentEl.textContent = "(select a file)";
    kvListEl.innerHTML = "";
    setActiveTab("files");
    modal.hidden = false;
    loadFileList(nodeId);
  }

  function hide() {
    modal.hidden = true;
    activeNodeId = null;
  }

  function setActiveTab(tab) {
    modal.querySelectorAll(".ws-tab").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.wsTab === tab);
    });
    if (tabFilesEl) tabFilesEl.hidden = tab !== "files";
    if (tabKvEl) tabKvEl.hidden = tab !== "kv";
    if (tab === "kv" && !kvLoaded && activeNodeId) {
      kvLoaded = true;
      loadKv(activeNodeId);
    }
  }

  async function loadFileList(nodeId) {
    fileListEl.innerHTML = '<div class="ws-empty">Loading...</div>';
    try {
      const data = await getJson(`/api/nodes/${encodeURIComponent(nodeId)}/workspace/files`);
      const files = data.files || [];
      fileListEl.innerHTML = "";
      if (files.length === 0) {
        fileListEl.innerHTML = '<div class="ws-empty">(empty workspace)</div>';
        return;
      }
      for (const path of files) {
        const row = document.createElement("div");
        row.className = "ws-file-entry";
        row.textContent = path;
        row.addEventListener("click", () => {
          fileListEl.querySelectorAll(".ws-file-entry").forEach((el) => el.classList.remove("active"));
          row.classList.add("active");
          loadFileContent(nodeId, path);
        });
        fileListEl.appendChild(row);
      }
    } catch (err) {
      fileListEl.innerHTML = `<div class="ws-error">${String(err.message || err)}</div>`;
    }
  }

  async function loadFileContent(nodeId, path) {
    fileContentEl.textContent = "Loading...";
    try {
      const data = await getJson(`/api/nodes/${encodeURIComponent(nodeId)}/workspace/files/${encodeURIComponent(path)}`);
      fileContentEl.textContent = data.content ?? "(empty)";
    } catch (err) {
      fileContentEl.textContent = `Error: ${String(err.message || err)}`;
    }
  }

  async function loadKv(nodeId) {
    kvListEl.innerHTML = '<div class="ws-empty">Loading...</div>';
    try {
      const data = await getJson(`/api/nodes/${encodeURIComponent(nodeId)}/workspace/kv`);
      const entries = data.entries || {};
      const keys = Object.keys(entries);
      kvListEl.innerHTML = "";
      if (keys.length === 0) {
        kvListEl.innerHTML = '<div class="ws-empty">(no KV entries)</div>';
        return;
      }
      for (const key of keys.sort()) {
        const entry = document.createElement("div");
        entry.className = "ws-kv-entry";
        const keyEl = document.createElement("div");
        keyEl.className = "ws-kv-key";
        keyEl.textContent = key;
        const valEl = document.createElement("div");
        valEl.className = "ws-kv-value";
        try {
          valEl.textContent = JSON.stringify(entries[key], null, 2);
        } catch (_e) {
          valEl.textContent = String(entries[key]);
        }
        entry.appendChild(keyEl);
        entry.appendChild(valEl);
        kvListEl.appendChild(entry);
      }
    } catch (err) {
      kvListEl.innerHTML = `<div class="ws-error">${String(err.message || err)}</div>`;
    }
  }

  // --- Event wiring ---

  inspectBtn?.addEventListener("click", () => {
    const selected = interactions.getState().selectedNodeId;
    if (selected) show(selected);
  });

  closeBtn?.addEventListener("click", hide);

  modal.addEventListener("click", (e) => {
    if (e.target === modal) hide();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !modal.hidden) hide();
  });

  modal.querySelector(".ws-tab-bar")?.addEventListener("click", (e) => {
    const tab = e.target.closest(".ws-tab")?.dataset?.wsTab;
    if (tab) setActiveTab(tab);
  });
}
```

### 5b. Wire it up in `start()`

Inside the `start()` function, add `wireWorkspaceInspector();` after `wireSidebarResize();`:

```js
async function start() {
  wireUiControls();
  wireRendererInteractions();
  wireSidebarResize();
  wireWorkspaceInspector();
  ...
```

---

## Step 6: Verify

### Quick smoke test

1. Start the server: `devenv shell -- remora serve`
2. Open the web UI at http://localhost:8081
3. Click a node on the graph
4. Confirm the **Inspect workspace** button appears below the node name
5. Click it — modal opens with the Files tab listing workspace file paths
6. Click a file path — content appears in the right pane
7. Click the **KV Store** tab — KV entries load and display
8. Press Escape — modal closes
9. Click backdrop — modal closes
10. Deselect the node (click stage) — Inspect button disappears

### Edge cases to test

- Node with no workspace yet (e.g. freshly discovered, no bundle provisioned) — should show "No workspace for this node" error or empty file list
- File that doesn't exist (unlikely via the UI, but the 404 path should be handled gracefully)
- Very large KV values — confirm the `.ws-kv-value` max-height + scroll works
- Empty workspace (all files deleted) — should show "(empty workspace)"
- Empty KV store — should show "(no KV entries)"

---

## Summary of all changes

| File | Lines added (approx) | What |
|---|---|---|
| `src/remora/web/routes/nodes.py` | ~45 | 3 endpoint functions, 1 import, 3 routes, 3 `__all__` entries |
| `src/remora/web/static/index.html` | ~120 | CSS rules (~100 lines), Inspect button HTML (~3 lines), modal HTML (~17 lines) |
| `src/remora/web/static/panels.js` | ~3 | Element ref + show/hide in `setNode` |
| `src/remora/web/static/main.js` | ~115 | `wireWorkspaceInspector` function + 1 call in `start()` |
