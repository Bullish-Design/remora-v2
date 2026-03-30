# PLAN — Workspace Inspector

**NO SUBAGENTS. Do all work directly.**

---

## Step 1 — Backend: workspace files endpoint (`nodes.py`)

Add two handlers and register their routes.

### `api_workspace_files`
```
GET /api/nodes/{node_id}/workspace/files
```
- Get workspace via `deps.workspace_service.get_agent_workspace(node_id)`
- Call `await workspace.list_all_paths()`
- Return `{"node_id": node_id, "files": [...]}`
- 503 if no workspace service; 404 if node has no workspace (handle `FileNotFoundError`)

### `api_workspace_file_content`
```
GET /api/nodes/{node_id}/workspace/files/{file_path:path}
```
- Get workspace, call `await workspace.read(file_path)`
- Return `{"path": file_path, "content": "..."}`
- 404 if file not found (`FileNotFoundError`, `fsdantic.FileNotFoundError`)

Register both routes in `routes()` **before** the catch-all `{node_id:path}` route to avoid shadowing.

---

## Step 2 — Backend: workspace KV endpoint (`nodes.py`)

### `api_workspace_kv`
```
GET /api/nodes/{node_id}/workspace/kv
```
- Get workspace, call `await workspace.kv_list()` to get all keys
- For each key, call `await workspace.kv_get(key)`
- Return `{"node_id": node_id, "entries": {"key": value, ...}}`
- 503 if no workspace service

Register route alongside the others.

Update `__all__` with the three new function names.

---

## Step 3 — Frontend: modal markup and CSS (`index.html`)

### HTML — add before closing `</body>`

```html
<div id="workspace-modal" class="ws-modal-backdrop" hidden>
  <div class="ws-modal">
    <div class="ws-modal-header">
      <span id="ws-modal-title">Workspace</span>
      <button id="ws-modal-close">✕</button>
    </div>
    <div class="ws-tab-bar">
      <button class="ws-tab active" data-tab="files">Files</button>
      <button class="ws-tab" data-tab="kv">KV Store</button>
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
```

### CSS — add to `<style>`

- `.ws-modal-backdrop` — fixed inset-0, z-index 100, semi-transparent bg, flex center
- `.ws-modal` — dark panel, `width: min(820px, 90vw)`, `height: min(580px, 85vh)`, flex column, border-radius, border
- `.ws-modal-header` — flex row, title + close button
- `.ws-tab-bar` — two tab buttons, active state uses `var(--accent)`
- `.ws-tab-panel` — flex: 1, overflow hidden
- `.ws-files-split` — flex row, file list ~240px fixed left, content pane flex:1 right
- `.ws-file-list` — overflow-y auto, font-size 0.78rem, each entry is a clickable row
- `.ws-file-content` — overflow auto, `font-size: 0.78rem`, `white-space: pre-wrap`, padding, dark bg
- `.ws-kv-list` — overflow-y auto, each entry shows key (bold, muted) + value (pre-wrap JSON)

---

## Step 4 — Frontend: Inspect button (`index.html` + `panels.js`)

In `index.html`, add an **Inspect** button to the node detail section:

```html
<div id="node-inspect-bar" style="display:none; margin-bottom: 8px;">
  <button id="btn-inspect-workspace" type="button">Inspect workspace</button>
</div>
```

Place it between `<h2 id="node-name">` and `<div id="node-details">`.

Show/hide `#node-inspect-bar` from `panels.js`:
- `setNode(node)` → show bar
- `clearNodeSelection()` / `setNode(null)` → hide bar

Export a `setInspectBarVisible(bool)` helper from `panels.js`, or simply toggle display inline in `setNode`/`clearNodeSelection`.

---

## Step 5 — Frontend: modal logic (`main.js`)

Add a `wireWorkspaceInspector()` function and call it from `start()`.

### State
```js
let wsModalNodeId = null;
let wsActiveTab = "files";
```

### `openWorkspaceModal(nodeId)`
1. Set `wsModalNodeId`, update title to node name
2. Show modal (`hidden` → removed)
3. Load files tab by default: fetch `/api/nodes/{id}/workspace/files`, render path list
4. Each path row: `click` → fetch `/api/nodes/{id}/workspace/files/{path}`, set content pane

### `openKvTab(nodeId)`
- Fetch `/api/nodes/{id}/workspace/kv`
- Render each entry: key as label, value as `JSON.stringify(value, null, 2)` in a `<pre>`

### Event wiring
- `#btn-inspect-workspace` click → `openWorkspaceModal(selectedNodeId)`
- `#ws-modal-close` click → hide modal
- `#ws-modal-backdrop` click on backdrop (not modal body) → hide modal
- `document` keydown `Escape` → hide modal if open
- Tab buttons → toggle `hidden` on panels, update active tab state, lazy-load KV on first switch

---

## Acceptance Criteria

- [ ] Selecting a node shows the Inspect button
- [ ] Clicking Inspect opens the modal titled with the node name
- [ ] Files tab lists all paths in the workspace; clicking a path loads and displays its content
- [ ] KV tab lists all KV keys and their values (pretty-printed JSON)
- [ ] Modal closes on ✕ button, Esc key, and backdrop click
- [ ] Deselecting a node hides the Inspect button and closes any open modal
- [ ] 503/404 responses show a readable error message inside the modal
- [ ] No new files created; all changes in `nodes.py`, `index.html`, `main.js`, `panels.js`

---

**NO SUBAGENTS. Do all work directly.**
