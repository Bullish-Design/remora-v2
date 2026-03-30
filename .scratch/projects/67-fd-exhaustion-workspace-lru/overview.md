# 67 — FD Exhaustion from Unbounded Cairn Workspace Connections

## Problem

During demo runs, the web server (port 8081) crashes with repeated `OSError: [Errno 24] Too many open files` errors. This happens during discovery when many nodes are created.

## Root Cause

`CairnWorkspaceService` (`src/remora/core/storage/workspace.py`) opens a separate SQLite database per node via `cairn_wm.open_workspace()`. Each workspace uses Turso + WAL mode, consuming ~3 file descriptors (`.db`, `-wal`, `-shm`) plus a worker thread.

**The caches are unbounded.** Workspaces are stored in `_agent_workspaces` and `_raw_agent_workspaces` dicts and never evicted — only closed at full shutdown via `close()`.

### Call chain during discovery

```
reconciler._do_reconcile_file()
  → reconciler._reconcile_events()
    → reconciler._provision_bundle(node_id, role)     # called for EVERY new node
      → workspace_service.get_agent_workspace(node_id) # opens + caches workspace forever
      → workspace.write(...)  / workspace.kv_set(...)
```

For a project with 300+ code elements (functions, classes, modules), this opens 300+ SQLite connections = ~900+ FDs from workspaces alone. Combined with the main DB, web server socket, SSE connections, inotify watchers, etc., this exceeds the process FD limit.

### Why it doesn't fail immediately

Workspaces are opened incrementally as nodes are discovered. The leak accumulates over the full scan, typically hitting the limit partway through or shortly after discovery completes.

## Evidence

- Error is `ERRNO 24` on the asyncio `socket.accept()` for the web server — the FD table is full process-wide
- The error cascades (many rapid failures) because the web server keeps accepting connections while no FDs are available
- Cairn workspace `open_workspace()` → `Fsdantic.open()` → `turso.aio.connect()` — each opens a real SQLite connection with a dedicated thread
