# 69 — Workspace Inspector

## Goal

Add an on-demand UI for inspecting any node's Cairn filesystem workspace and KV store. Triggered by a button in the node detail panel; displayed as a modal overlay so it doesn't disturb the main graph view.

---

## Context

Every discovered node gets a Cairn workspace — a per-node SQLite-backed virtual filesystem (fsdantic/Turso). It stores:

- **Files** — bundle YAML, tool scripts, agent-written files (e.g. `_bundle/bundle.yaml`, `_bundle/tools/*.pym`, anything an agent writes during a turn)
- **KV store** — structured data the agent and system write at runtime (e.g. `companion/reflections`, `companion/chat_index`, `_system/self_reflect`, `_bundle/template_fingerprint`)

Today there is no way to inspect this at runtime without directly querying the SQLite database on disk. The companion endpoint (`/api/nodes/{id}/companion`) fetches a few hardcoded KV keys, but there is no general-purpose inspection tool.

---

## Relevant Existing Code

### Backend

| File | Relevance |
|---|---|
| `src/remora/web/routes/nodes.py` | All node API endpoints live here; new endpoints go here |
| `src/remora/core/storage/workspace.py` | `AgentWorkspace` — has `list_all_paths()`, `read(path)`, `kv_list(prefix)`, `kv_get(key)` |
| `src/remora/web/deps.py` | `_deps_from_request` — provides `deps.workspace_service` |

### Frontend

| File | Relevance |
|---|---|
| `src/remora/web/static/index.html` | All CSS and HTML — modal markup and styles go here |
| `src/remora/web/static/main.js` | All UI JS — button wiring and modal logic go here |
| `src/remora/web/static/panels.js` | Node detail panel — button placement and `setNode()` are here |

### `AgentWorkspace` API surface used

```python
await workspace.list_all_paths()          # → list[str]
await workspace.read(path)                # → str
await workspace.kv_list(prefix="")        # → list[str]
await workspace.kv_get(key)              # → Any | None
```

---

## Design Decision: Option A + Option 1

**Backend**: Two lazy endpoints (file list up front, content on demand) + one KV dump endpoint.
**Frontend**: Centered modal with two tabs (Files / KV).

Rationale: modal gives enough space for a two-pane file browser; lazy file content means the modal opens instantly. All changes fit in `nodes.py`, `index.html`, and `main.js` — no new files.

---

## What Won't Be Changed

- `AgentWorkspace` — no modifications needed, public API is sufficient
- `CairnWorkspaceService` — no modifications needed
- Any other route files, JS modules, or Python modules
