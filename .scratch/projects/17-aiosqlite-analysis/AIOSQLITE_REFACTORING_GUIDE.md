# aiosqlite Refactoring Guide

**Goal:** Replace the custom `AsyncDB` wrapper with direct `aiosqlite` usage, and fix the LSP `didChange` handler to use an in-memory document model instead of writing to disk. No backward compatibility. Zero shims.

---

## Table of Contents

1. [Phase A: Fix LSP didChange Handler](#phase-a-fix-lsp-didchange-handler)
   Remove disk-writing from `didChange`, replace with an in-memory document store, and emit reconciliation events only.

2. [Phase B: Add aiosqlite Dependency](#phase-b-add-aiosqlite-dependency)
   Add `aiosqlite` to `pyproject.toml` and `devenv.nix` (if applicable). Verify installation.

3. [Phase C: Replace `db.py` with `open_database()` Factory](#phase-c-replace-dbpy-with-open_database-factory)
   Delete the `AsyncDB` class. Replace it with an async factory function returning a raw `aiosqlite.Connection`. Update the type signature everywhere.

4. [Phase D: Update All Store Classes](#phase-d-update-all-store-classes)
   Rewrite `NodeStore`, `AgentStore`, `EventStore`, and `SubscriptionRegistry` to use `aiosqlite.Connection` directly. Replace all `_db.execute()` / `_db.fetch_one()` / etc. calls with native `aiosqlite` cursor methods.

5. [Phase E: Update `RuntimeServices` and CLI](#phase-e-update-runtimeservices-and-cli)
   Change `RuntimeServices.__init__()` to accept an `aiosqlite.Connection`. Make `_start()` in `__main__.py` `await` the async connection factory. Update `close()` to be fully async.

6. [Phase F: Update All Tests](#phase-f-update-all-tests)
   Update `conftest.py` shared fixture, `test_db.py`, and every test file that creates an `AsyncDB`. All fixtures become async.

7. [Phase G: Verify and Clean Up](#phase-g-verify-and-clean-up)
   Run full test suite. Grep for any remaining `AsyncDB` references. Remove dead imports. Verify zero shims.

---

## Phase A: Fix LSP didChange Handler

### Problem

The current `didChange` handler in `src/remora/lsp/server.py` (lines 51-65) **writes file contents to disk** on every text change event. This is wrong for an LSP server — the editor owns the file on disk. Writing back to disk on every keystroke can:

- Cause save-loop conflicts with the editor's own save logic
- Trigger watchfiles → reconciler cycles on every keystroke
- Corrupt files if the editor and LSP race on writes

### Solution

Replace disk-writing with an **in-memory document store** that the LSP maintains. The `didChange` handler updates the in-memory text. The `didSave` handler (which fires when the user actually saves) remains the trigger for reconciliation events. The `didChange` handler should only emit a lightweight event for real-time features (e.g., cursor tracking, live preview).

### Step A1: Create the document store

Add a simple `DocumentStore` class to `src/remora/lsp/server.py` (or a separate `src/remora/lsp/documents.py` if you prefer isolation — but for this small codebase, inline is fine):

```python
class DocumentStore:
    """In-memory document text tracked by the LSP server."""

    def __init__(self) -> None:
        self._documents: dict[str, str] = {}

    def open(self, uri: str, text: str) -> None:
        self._documents[uri] = text

    def close(self, uri: str) -> None:
        self._documents.pop(uri, None)

    def get(self, uri: str) -> str | None:
        return self._documents.get(uri)

    def apply_changes(
        self,
        uri: str,
        changes: Sequence[lsp.TextDocumentContentChangeEvent],
    ) -> str:
        text = self._documents.get(uri, "")
        for change in changes:
            change_text = getattr(change, "text", "") or ""
            range_value = getattr(change, "range", None)
            if range_value is None:
                text = change_text
                continue
            start = _position_to_offset(text, range_value.start)
            end = _position_to_offset(text, range_value.end)
            text = text[:start] + change_text + text[end:]
        self._documents[uri] = text
        return text
```

### Step A2: Wire into the LSP server

In `create_lsp_server()`, create a `DocumentStore` instance and update the handlers:

```python
def create_lsp_server(node_store, event_store) -> LanguageServer:
    server = LanguageServer("remora", "2.0.0")
    documents = DocumentStore()

    @server.feature(lsp.TEXT_DOCUMENT_DID_OPEN)
    async def did_open(params: lsp.DidOpenTextDocumentParams) -> None:
        documents.open(params.text_document.uri, params.text_document.text)
        file_path = _uri_to_path(params.text_document.uri)
        await event_store.append(ContentChangedEvent(path=file_path, change_type="opened"))

    @server.feature(lsp.TEXT_DOCUMENT_DID_CHANGE)
    async def did_change(params: lsp.DidChangeTextDocumentParams) -> None:
        documents.apply_changes(params.text_document.uri, params.content_changes)
        # No disk write. No ContentChangedEvent.
        # The editor will trigger did_save when the user saves.

    @server.feature(lsp.TEXT_DOCUMENT_DID_SAVE)
    async def did_save(params: lsp.DidSaveTextDocumentParams) -> None:
        file_path = _uri_to_path(params.text_document.uri)
        await event_store.append(ContentChangedEvent(path=file_path, change_type="modified"))

    # ... rest unchanged
```

### Step A3: Remove dead code

- Delete `_resolve_document_text()` function (lines 130-149 of current `server.py`). Its logic is now inside `DocumentStore.apply_changes()`.
- Keep `_position_to_offset()` — it's used by `DocumentStore.apply_changes()`.

### Step A4: Clean up `create_lsp_server()` signature

The current signature accepts `workspace_service` and `db` parameters that are immediately `del`-ed:

```python
def create_lsp_server(node_store, event_store, workspace_service=None, db=None):
    del workspace_service, db
```

Since we don't care about backward compatibility, simplify to:

```python
def create_lsp_server(node_store, event_store) -> LanguageServer:
```

Update the one caller in `__main__.py` (line 183-188):

```python
# Before:
lsp_server = create_lsp_server(
    services.node_store, services.event_store,
    services.workspace_service, services.db,
)
# After:
lsp_server = create_lsp_server(services.node_store, services.event_store)
```

### Step A5: Update tests

In `tests/unit/test_lsp_server.py`, update `test_lsp_did_change_writes_file_and_emits_event` (lines 89-117):

- The test currently asserts that `did_change` writes to disk (`assert file_path.read_text(...) == "print('goodbye')\n"`).
- Change the test to verify that the `DocumentStore` holds the updated text and that **no** `ContentChangedEvent` is emitted by `didChange`.
- Add a test for the `did_open` → `did_change` → `did_save` sequence to verify the full lifecycle.

### Step A6: Expose `DocumentStore` for testing

Add `documents` to the `_remora_handlers` dict:

```python
server._remora_handlers = {
    "code_lens": code_lens,
    "hover": hover,
    "did_save": did_save,
    "did_open": did_open,
    "did_change": did_change,
    "documents": documents,
}
```

### Verification

```bash
devenv shell -- pytest tests/unit/test_lsp_server.py -v
```

All LSP tests pass. The `didChange` handler no longer touches the filesystem.

---

## Phase B: Add aiosqlite Dependency

### Step B1: Add to `pyproject.toml`

In `pyproject.toml`, add `aiosqlite` to the main dependencies:

```toml
dependencies = [
  "aiosqlite>=0.20",   # <-- add this line
  "pydantic>=2.0",
  # ... rest unchanged
]
```

### Step B2: Verify installation

```bash
devenv shell -- python -c "import aiosqlite; print(aiosqlite.__version__)"
```

### Step B3: Verify `aiosqlite.Row` compatibility

Quick sanity check that `aiosqlite.Row` supports dict-like access (the `row["column_name"]` pattern used throughout the stores):

```bash
devenv shell -- python -c "
import asyncio, aiosqlite
async def check():
    async with aiosqlite.connect(':memory:') as db:
        db.row_factory = aiosqlite.Row
        await db.execute('CREATE TABLE t (name TEXT)')
        await db.execute('INSERT INTO t VALUES (?)', ('hello',))
        async with db.execute('SELECT name FROM t') as cursor:
            row = await cursor.fetchone()
            print(row['name'])  # should print 'hello'
asyncio.run(check())
"
```

---

## Phase C: Replace `db.py` with `open_database()` Factory

### Step C1: Rewrite `src/remora/core/db.py`

Delete the entire `AsyncDB` class. Replace with:

```python
"""Database connection factory."""

from __future__ import annotations

from pathlib import Path

import aiosqlite


async def open_database(db_path: Path | str) -> aiosqlite.Connection:
    """Open an aiosqlite connection with WAL mode and standard pragmas."""
    db = await aiosqlite.connect(str(db_path))
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA busy_timeout=5000")
    return db


__all__ = ["open_database"]
```

That's the entire file. ~15 lines replacing ~116 lines.

### Step C2: Type alias (optional clarity)

If you want a readable type alias for annotations across the codebase, add one line:

```python
# At the top of db.py, after imports:
Connection = aiosqlite.Connection
```

Then stores can do `from remora.core.db import Connection` for readability. This is optional — using `aiosqlite.Connection` directly is equally clean.

### Key Differences from `AsyncDB`

| `AsyncDB` method | `aiosqlite.Connection` equivalent |
|-----------------|----------------------------------|
| `await db.execute(sql, params)` | `await db.execute(sql, params)` then `await db.commit()` |
| `await db.execute_script(sql)` | `await db.executescript(sql)` then `await db.commit()` |
| `await db.execute_many(stmts)` | Loop `await db.execute(sql, params)` then one `await db.commit()` |
| `await db.fetch_one(sql, params)` | `cursor = await db.execute(sql, params)` then `await cursor.fetchone()` |
| `await db.fetch_all(sql, params)` | `cursor = await db.execute(sql, params)` then `await cursor.fetchall()` |
| `await db.insert(sql, params)` | `cursor = await db.execute(sql, params)` then `await db.commit()` → `cursor.lastrowid` |
| `await db.delete(sql, params)` | `cursor = await db.execute(sql, params)` then `await db.commit()` → `cursor.rowcount` |
| `db.close()` | `await db.close()` |

**Critical difference:** `aiosqlite` does NOT auto-commit. You must call `await db.commit()` after mutations. `aiosqlite` does its own internal serialization, so **no manual `asyncio.Lock` is needed**.

---

## Phase D: Update All Store Classes

This is the largest phase. Each store currently calls `self._db.execute()`, `self._db.fetch_one()`, etc. These must be rewritten to use `aiosqlite.Connection` directly.

### Step D1: Update `NodeStore` (`src/remora/core/graph.py`)

**Change constructor type:**

```python
# Before:
from remora.core.db import AsyncDB
class NodeStore:
    def __init__(self, db: AsyncDB):
        self._db = db

# After:
import aiosqlite
class NodeStore:
    def __init__(self, db: aiosqlite.Connection):
        self._db = db
```

**Update each method.** Here's the pattern for every method — showing two representative examples:

`create_tables()`:
```python
# Before:
await self._db.execute_script("""CREATE TABLE IF NOT EXISTS nodes ...""")

# After:
await self._db.executescript("""CREATE TABLE IF NOT EXISTS nodes ...""")
await self._db.commit()
```

`upsert_node()`:
```python
# Before:
await self._db.execute(
    f"INSERT OR REPLACE INTO nodes ({columns}) VALUES ({placeholders})",
    tuple(row.values()),
)

# After:
await self._db.execute(
    f"INSERT OR REPLACE INTO nodes ({columns}) VALUES ({placeholders})",
    tuple(row.values()),
)
await self._db.commit()
```

`get_node()`:
```python
# Before:
row = await self._db.fetch_one("SELECT * FROM nodes WHERE node_id = ?", (node_id,))

# After:
cursor = await self._db.execute("SELECT * FROM nodes WHERE node_id = ?", (node_id,))
row = await cursor.fetchone()
```

`list_nodes()`:
```python
# Before:
rows = await self._db.fetch_all(sql, tuple(params))

# After:
cursor = await self._db.execute(sql, tuple(params))
rows = await cursor.fetchall()
```

`delete_node()`:
```python
# Before:
await self._db.execute("DELETE FROM edges WHERE from_id = ? OR to_id = ?", (node_id, node_id))
deleted = await self._db.delete("DELETE FROM nodes WHERE node_id = ?", (node_id,))
return deleted > 0

# After:
await self._db.execute("DELETE FROM edges WHERE from_id = ? OR to_id = ?", (node_id, node_id))
cursor = await self._db.execute("DELETE FROM nodes WHERE node_id = ?", (node_id,))
await self._db.commit()
return cursor.rowcount > 0
```

Apply the same pattern to: `set_status()`, `transition_status()`, `add_edge()`, `get_edges()`, `delete_edges()`, `list_all_edges()`, `get_children()`.

### Step D2: Update `AgentStore` (`src/remora/core/graph.py`)

Same pattern. Change constructor type from `AsyncDB` to `aiosqlite.Connection`. Update all methods:

- `create_tables()` → `executescript` + `commit`
- `upsert_agent()` → `execute` + `commit`
- `get_agent()` → `execute` + `fetchone`
- `set_status()` → `execute` + `commit`
- `transition_status()` → uses `get_agent()` + `set_status()`, no direct change needed
- `list_agents()` → `execute` + `fetchall`
- `delete_agent()` → `execute` + `commit` + `cursor.rowcount`

### Step D3: Update `EventStore` (`src/remora/core/events/store.py`)

Change constructor:

```python
# Before:
from remora.core.db import AsyncDB
def __init__(self, db: AsyncDB, ...):
    self._db = db

# After:
import aiosqlite
def __init__(self, db: aiosqlite.Connection, ...):
    self._db = db
```

Update methods:

`create_tables()` → `executescript` + `commit`

`append()`:
```python
# Before:
event_id = await self._db.insert("INSERT INTO events ...", (...))

# After:
cursor = await self._db.execute("INSERT INTO events ...", (...))
await self._db.commit()
event_id = cursor.lastrowid
```

`get_events()` and `get_events_for_agent()`:
```python
# Before:
rows = await self._db.fetch_all(sql, params)

# After:
cursor = await self._db.execute(sql, params)
rows = await cursor.fetchall()
```

### Step D4: Update `SubscriptionRegistry` (`src/remora/core/events/subscriptions.py`)

Same pattern. Change constructor type. Update:

- `create_tables()` → `executescript` + `commit`
- `register()` → `execute` + `commit` + `cursor.lastrowid`
- `unregister()` → `execute` + `commit` + `cursor.rowcount`
- `unregister_by_agent()` → `execute` + `commit` + `cursor.rowcount`
- `_rebuild_cache()` → `execute` + `fetchall`

### Step D5: Remove `AsyncDB` import from `graph.py`

Remove:
```python
from remora.core.db import AsyncDB
```

Replace with:
```python
import aiosqlite
```

Same for `events/store.py` and `events/subscriptions.py`.

### Verification

```bash
devenv shell -- pytest tests/unit/test_graph.py tests/unit/test_event_store.py -v
```

---

## Phase E: Update `RuntimeServices` and CLI

### Step E1: Update `RuntimeServices` (`src/remora/core/services.py`)

**Constructor:** Change `db: AsyncDB` to `db: aiosqlite.Connection`:

```python
# Before:
from remora.core.db import AsyncDB
class RuntimeServices:
    def __init__(self, config: Config, project_root: Path, db: AsyncDB):
        self.db = db
        # ...

# After:
import aiosqlite
class RuntimeServices:
    def __init__(self, config: Config, project_root: Path, db: aiosqlite.Connection):
        self.db = db
        # ...
```

**`close()` method:** `db.close()` becomes `await db.close()`:

```python
# Before:
self.db.close()

# After:
await self.db.close()
```

### Step E2: Update CLI (`src/remora/__main__.py`)

The `_start()` function currently creates the DB synchronously:

```python
# Before:
from remora.core.db import AsyncDB
db = AsyncDB.from_path(db_path)
services = RuntimeServices(config, project_root, db)

# After:
from remora.core.db import open_database
db = await open_database(db_path)
services = RuntimeServices(config, project_root, db)
```

Since `_start()` is already `async`, this is a one-line change.

### Step E3: Update `create_lsp_server` call

After Phase A, this already simplified to:
```python
lsp_server = create_lsp_server(services.node_store, services.event_store)
```

No further changes needed here.

### Verification

```bash
devenv shell -- pytest tests/integration/test_e2e.py -v
```

---

## Phase F: Update All Tests

### Step F1: Update shared fixture (`tests/conftest.py`)

The `db` fixture must become async:

```python
# Before:
from remora.core.db import AsyncDB

@pytest.fixture
def db(tmp_path):
    database = AsyncDB.from_path(tmp_path / "test.db")
    yield database
    database.close()

# After:
import pytest_asyncio
from remora.core.db import open_database

@pytest_asyncio.fixture
async def db(tmp_path):
    database = await open_database(tmp_path / "test.db")
    yield database
    await database.close()
```

### Step F2: Update `tests/unit/test_db.py`

Rewrite all 4 tests to use `open_database` instead of `AsyncDB.from_path`. Every test is already `async`, so just change the factory call and close:

```python
# Before:
db = AsyncDB.from_path(tmp_path / "db1.sqlite")
# ... test body ...
db.close()

# After:
db = await open_database(tmp_path / "db1.sqlite")
# ... test body using aiosqlite directly ...
await db.close()
```

Update the test body to use `aiosqlite` methods directly:

```python
# Before:
await db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
await db.execute("INSERT INTO t(name) VALUES (?)", ("a",))
row = await db.fetch_one("SELECT name FROM t WHERE id = 1")

# After:
await db.executescript("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
await db.execute("INSERT INTO t(name) VALUES (?)", ("a",))
await db.commit()
cursor = await db.execute("SELECT name FROM t WHERE id = 1")
row = await cursor.fetchone()
```

### Step F3: Update all other test files

Every test file that imports `AsyncDB` and calls `AsyncDB.from_path()` needs the same change. Here is the complete list:

| File | Instances |
|------|-----------|
| `tests/conftest.py` | 1 fixture |
| `tests/unit/test_db.py` | 4 tests |
| `tests/unit/test_actor.py` | 2 fixtures |
| `tests/unit/test_event_store.py` | 5 tests |
| `tests/unit/test_externals.py` | 1 fixture |
| `tests/unit/test_graph.py` | uses shared `db` fixture (updated in F1) |
| `tests/unit/test_lsp_server.py` | 1 fixture |
| `tests/unit/test_projections.py` | 2 fixtures |
| `tests/unit/test_reconciler.py` | 1 fixture |
| `tests/unit/test_runner.py` | 1 fixture |
| `tests/unit/test_web_server.py` | 1 fixture |
| `tests/integration/test_e2e.py` | 1 fixture |
| `tests/integration/test_llm_turn.py` | 2 fixtures |
| `tests/integration/test_performance.py` | 2 fixtures |

**For each file, the change is mechanical:**

1. Replace `from remora.core.db import AsyncDB` with `from remora.core.db import open_database`
2. Replace `AsyncDB.from_path(path)` with `await open_database(path)`
3. Replace `db.close()` with `await db.close()`
4. If the fixture uses `@pytest.fixture`, change to `@pytest_asyncio.fixture` and make it `async`
5. If the test has a type annotation `AsyncDB`, change to `aiosqlite.Connection`

### Step F4: Update `tests/integration/test_llm_turn.py` return type

Line 179 has:
```python
) -> tuple[Actor, object, EventStore, CairnWorkspaceService, AsyncDB, Path]:
```

Change `AsyncDB` to `aiosqlite.Connection`:
```python
) -> tuple[Actor, object, EventStore, CairnWorkspaceService, aiosqlite.Connection, Path]:
```

### Verification

```bash
devenv shell -- pytest --tb=short -q
```

All tests should pass with the new `aiosqlite` backend.

---

## Phase G: Verify and Clean Up

### Step G1: Grep for dead references

```bash
grep -r "AsyncDB" src/ tests/
```

Expected: **zero hits**. If any remain, fix them.

```bash
grep -r "from_path" src/ tests/
```

Expected: zero hits referencing `AsyncDB.from_path`.

```bash
grep -r "asyncio.to_thread" src/remora/core/db.py
```

Expected: zero hits (the file no longer exists as a wrapper).

### Step G2: Verify no shims/aliases

```bash
grep -r "AsyncDB\|from_path\|\.connection\|\.lock" src/remora/core/db.py
```

The file should contain only `open_database` and the import. No classes, no properties, no compatibility helpers.

### Step G3: Run full test suite

```bash
devenv shell -- pytest --tb=short -q
```

All tests pass. Zero warnings about deprecated APIs.

### Step G4: Verify line count

The new `db.py` should be ~15 lines (down from 116). The total codebase size should decrease by ~100 lines net.

---

## Summary of Changes

| File | Action |
|------|--------|
| `src/remora/lsp/server.py` | Add `DocumentStore`, remove disk writes from `didChange`, simplify signature |
| `src/remora/core/db.py` | Delete `AsyncDB` class, replace with `open_database()` factory (~15 lines) |
| `src/remora/core/graph.py` | Change `AsyncDB` → `aiosqlite.Connection`, update all SQL calls |
| `src/remora/core/events/store.py` | Same — `AsyncDB` → `aiosqlite.Connection` |
| `src/remora/core/events/subscriptions.py` | Same |
| `src/remora/core/services.py` | Change constructor type, `await db.close()` |
| `src/remora/__main__.py` | `await open_database(path)` instead of `AsyncDB.from_path(path)` |
| `pyproject.toml` | Add `aiosqlite>=0.20` |
| `tests/conftest.py` | Async fixture with `open_database` |
| `tests/unit/test_db.py` | Rewrite to test `aiosqlite` directly |
| `tests/unit/test_*.py` (10 files) | Mechanical `AsyncDB.from_path` → `await open_database` |
| `tests/integration/test_*.py` (3 files) | Same mechanical update |

**Net result:** ~100 fewer lines, no manual locking, no thread-hopping, native async transactions, one fewer abstraction layer. The codebase uses `aiosqlite` directly with zero wrappers.
