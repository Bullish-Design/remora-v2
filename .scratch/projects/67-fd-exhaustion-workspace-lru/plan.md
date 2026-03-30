# Plan: LRU Eviction for Cairn Workspace Connections

## Approach

Add a bounded LRU cache to `CairnWorkspaceService` that closes least-recently-used workspace connections when the count exceeds a configurable cap. The on-disk data is unaffected — evicted workspaces simply reopen on next access.

## Key Insight

All callers already go through `get_agent_workspace(node_id)`, which handles cache misses by opening the workspace. No caller changes are needed — eviction is transparent.

## Changes

### `src/remora/core/storage/workspace.py`

1. **Replace `dict` with `OrderedDict`** for `_agent_workspaces` and `_raw_agent_workspaces`
2. **Add `_MAX_OPEN_WORKSPACES = 128`** class constant (leaves ample FD headroom for main DB, web server, SSE, inotify, etc.)
3. **On cache hit**: `move_to_end(node_id)` to mark as recently used
4. **After inserting a new workspace**: call `_evict_lru()` which:
   - While `len > _MAX_OPEN_WORKSPACES`: pop from front (oldest)
   - Close the evicted `Workspace` via `await raw_workspace.close()`
   - Remove from `self._manager._active_workspaces` (untrack from cairn manager)
5. **Update `close()`** to work with OrderedDict (no behavioral change needed, `.clear()` works the same)

### Optional: `src/remora/core/model/config.py`

Make the cap configurable via `Config.infra.max_open_workspaces` (default 128). Lower priority — the constant is fine for now.

## What NOT to change

- No changes to callers (`reconciler.py`, `turn.py`, `subscriptions.py`, web routes)
- No changes to `AgentWorkspace` wrapper (it becomes stale on eviction, but `get_agent_workspace` transparently replaces it)
- No changes to Cairn/Fsdantic internals

## Verification

1. `devenv shell -- pytest tests/unit/ -x`
2. `devenv shell -- pytest tests/integration/ -x`
3. Manual demo run — confirm discovery completes without FD errors
4. Confirm evicted workspaces reopen transparently with data intact
