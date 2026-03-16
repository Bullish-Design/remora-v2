# Embeddy Integration — Step-by-Step Implementation Plan

This document provides a detailed, ordered guide for integrating the `embeddy` library into remora-v2. It covers creating a `SearchService`, wiring it into the runtime, adding agent-accessible search tools, hooking into file change events for automatic index maintenance, exposing a web API endpoint, and adding a bootstrap indexing command.

**Reference documents:**
- Embeddy library spec: `.context/embeddy/SPEC.md`
- Embeddy client source: `.context/embeddy/src/embeddy/client/client.py`
- Brainstorming design: `.scratch/projects/31-companion-and-vector-integration/VECTOR_BRAINSTORMING.md`

---

## Table of Contents

1. [Overview & Architecture](#1-overview--architecture)
   - 1.1 What We're Building
   - 1.2 Integration Points Summary
   - 1.3 Dependency Strategy
2. [Step 1: Add Embeddy as an Optional Dependency](#2-step-1-add-embeddy-as-an-optional-dependency)
   - 2.1 pyproject.toml Changes
   - 2.2 Verification
3. [Step 2: Create SearchConfig](#3-step-2-create-searchconfig)
   - 3.1 The Config Model
   - 3.2 Wire into Config
   - 3.3 Update remora.yaml.example
   - 3.4 Tests to Write
4. [Step 3: Create SearchService](#4-step-3-create-searchservice)
   - 4.1 File: `core/search.py`
   - 4.2 Remote Mode Implementation
   - 4.3 Local Mode Implementation
   - 4.4 Graceful Degradation
   - 4.5 Bootstrap Indexing
   - 4.6 Tests to Write
5. [Step 4: Wire SearchService into RuntimeServices](#5-step-4-wire-searchservice-into-runtimeservices)
   - 5.1 Changes to `core/services.py`
   - 5.2 Changes to `core/lifecycle.py`
   - 5.3 Tests to Write
6. [Step 5: Add Search Methods to TurnContext](#6-step-5-add-search-methods-to-turncontext)
   - 6.1 Changes to `core/externals.py`
   - 6.2 Changes to Actor's TurnContext Construction
   - 6.3 Tests to Write
7. [Step 6: Create the Grail Tool](#7-step-6-create-the-grail-tool)
   - 7.1 File: `bundles/system/tools/semantic_search.pym`
   - 7.2 How Grail Tools Work
   - 7.3 Testing Approach
8. [Step 7: Add FileReconciler Indexing Hooks](#8-step-7-add-filereconciler-indexing-hooks)
   - 8.1 Changes to `code/reconciler.py`
   - 8.2 Design Considerations
   - 8.3 Tests to Write
9. [Step 8: Add Web API Search Endpoint](#9-step-8-add-web-api-search-endpoint)
   - 9.1 Changes to `web/server.py`
   - 9.2 Tests to Write
10. [Step 9: Add Bootstrap Index CLI Command](#10-step-9-add-bootstrap-index-cli-command)
    - 10.1 Changes to `__main__.py`
    - 10.2 Tests to Write
11. [Summary: All Files Changed](#11-summary-all-files-changed)
12. [Testing Strategy](#12-testing-strategy)
    - 12.1 Mocking EmbeddyClient
    - 12.2 Test Categories
    - 12.3 Running Tests

---

## 1. Overview & Architecture

### 1.1 What We're Building

A `SearchService` that wraps embeddy's `EmbeddyClient` (remote mode) or `Pipeline` + `SearchService` (local mode) and integrates into remora at these layers:

```
remora.yaml (config)
    ↓
SearchConfig (Pydantic model)
    ↓
SearchService (core/search.py)
    ↓
┌────────────────────────────────────────────────┐
│  Consumers:                                     │
│  - TurnContext.semantic_search()     (agents)   │
│  - semantic_search.pym Grail tool   (agents)   │
│  - FileReconciler hooks             (indexing)  │
│  - POST /api/search                 (web API)   │
│  - remora index CLI command         (bootstrap) │
└────────────────────────────────────────────────┘
```

### 1.2 Integration Points Summary

| File | What Changes | Why |
|------|-------------|-----|
| `pyproject.toml` | Add `embeddy` optional dependency | Make embeddy available |
| `core/config.py` | Add `SearchConfig` nested model | Configuration |
| `core/search.py` | **New file** — `SearchService` class | Core service |
| `core/services.py` | Wire `SearchService` into `RuntimeServices` | Lifecycle management |
| `core/lifecycle.py` | Pass search_service for bootstrap indexing | Startup integration |
| `core/externals.py` | Add `semantic_search()`, `find_similar_code()` to `TurnContext` | Agent API |
| `core/actor.py` | Pass `search_service` when constructing `TurnContext` | Plumbing |
| `core/runner.py` | Pass `search_service` through to `Actor` | Plumbing |
| `code/reconciler.py` | Add indexing hooks on file change/delete | Auto-indexing |
| `web/server.py` | Add `POST /api/search` endpoint | Web API |
| `__main__.py` | Add `remora index` CLI command | Bootstrap |
| `bundles/system/tools/semantic_search.pym` | **New file** — Grail tool | Agent tool |
| `remora.yaml.example` | Add `search:` section | Documentation |

### 1.3 Dependency Strategy

Embeddy is an **optional dependency**. The integration must never crash if embeddy is not installed.

- **Remote mode**: Only needs `embeddy.client.EmbeddyClient` (which itself only needs `httpx`). This is the lightweight path.
- **Local mode**: Needs the full embeddy package with torch, transformers, sqlite-vec, etc. This is the heavy path.
- **Neither installed**: SearchService is simply not available. All consumer code checks `search_service.available` or `search_service is None` before calling.

The import pattern throughout is:

```python
try:
    from embeddy.client import EmbeddyClient
except ImportError:
    EmbeddyClient = None  # type: ignore[assignment,misc]
```

---

## 2. Step 1: Add Embeddy as an Optional Dependency

### 2.1 pyproject.toml Changes

Embeddy is already configured as a uv source in `pyproject.toml`:

```toml
[tool.uv.sources]
embeddy = { git = "https://github.com/Bullish-Design/embeddy.git", rev = "main" }
```

Add it as an optional dependency group. Open `pyproject.toml` and add a new extras group after the existing `dev` group:

```toml
[project.optional-dependencies]
lsp = [
  "pygls>=1.0",
  "lsprotocol>=2024.0",
]
search = [
  "embeddy>=0.3.11",
]
search-local = [
  "embeddy[all]>=0.3.11",
]
dev = [
  "pytest>=8.0",
  "pytest-asyncio>=0.24",
  "hypothesis>=6.0",
  "ruff>=0.8",
  "pyright>=1.1.0",
  "pygls>=1.0",
  "lsprotocol>=2024.0",
  "embeddy>=0.3.11",
]
```

**Explanation:**
- `search` — installs just the embeddy package (client module + httpx). Sufficient for remote mode.
- `search-local` — installs embeddy with all its heavy dependencies (torch, transformers, etc.). Needed for local mode.
- `dev` — also includes embeddy so tests can import it.

### 2.2 Verification

After editing, run:

```bash
devenv shell -- uv sync --extra search
```

Then verify the import works:

```bash
devenv shell -- python -c "from embeddy.client import EmbeddyClient; print('OK')"
```

---

## 3. Step 2: Create SearchConfig

### 3.1 The Config Model

Add a `SearchConfig` Pydantic model to `core/config.py`. This model captures all the settings needed for the SearchService.

Add this class **before** the `Config` class definition:

```python
class SearchConfig(BaseModel):
    """Configuration for semantic search via embeddy."""

    enabled: bool = False
    mode: str = "remote"  # "remote" or "local"
    embeddy_url: str = "http://localhost:8585"
    timeout: float = 30.0
    default_collection: str = "code"
    collection_map: dict[str, str] = Field(default_factory=lambda: {
        ".py": "code",
        ".md": "docs",
        ".toml": "config",
        ".yaml": "config",
        ".yml": "config",
        ".json": "config",
    })
    # Local mode settings
    db_path: str = ".remora/embeddy.db"
    model_name: str = "Qwen/Qwen3-VL-Embedding-2B"
    embedding_dimension: int = 2048
```

**Field-by-field explanation:**

| Field | Default | Purpose |
|-------|---------|---------|
| `enabled` | `False` | Opt-in. No surprise imports or network calls unless explicitly configured. |
| `mode` | `"remote"` | `"remote"` uses EmbeddyClient (HTTP to a server). `"local"` uses in-process Pipeline. |
| `embeddy_url` | `"http://localhost:8585"` | URL of the embeddy server for remote mode. |
| `timeout` | `30.0` | HTTP timeout for remote calls (seconds). |
| `default_collection` | `"code"` | Fallback collection when file extension isn't in `collection_map`. |
| `collection_map` | `{".py": "code", ...}` | Maps file extensions to collection names. Used to route files to the right collection during indexing. |
| `db_path` | `".remora/embeddy.db"` | SQLite path for local mode's vector store. Relative to project root. |
| `model_name` | `"Qwen/Qwen3-VL-Embedding-2B"` | HuggingFace model ID for local mode embedding. |
| `embedding_dimension` | `2048` | Output vector dimension for local mode. |

Add a validator for `mode`:

```python
    @field_validator("mode")
    @classmethod
    def _validate_mode(cls, value: str) -> str:
        if value not in {"remote", "local"}:
            raise ValueError("search mode must be 'remote' or 'local'")
        return value
```

### 3.2 Wire into Config

Add a `search` field to the `Config` class:

```python
class Config(BaseSettings):
    # ... existing fields ...

    # Search (optional embeddy integration)
    search: SearchConfig = Field(default_factory=SearchConfig)
```

Since `Config` uses `frozen=True`, this is fine — `SearchConfig` is itself immutable (BaseModel defaults to non-frozen, but since it's nested in a frozen model and only read, this is acceptable).

**Important**: Add `SearchConfig` to the `__all__` list at the bottom of the file.

### 3.3 Update remora.yaml.example

Add a commented-out search section at the bottom of `remora.yaml.example`:

```yaml
# Semantic search via embeddy (optional).
# Requires: pip install remora[search] and a running embeddy server.
# search:
#   enabled: true
#   mode: "remote"
#   embeddy_url: "http://localhost:8585"
#   timeout: 30.0
#   default_collection: "code"
#   collection_map:
#     ".py": "code"
#     ".md": "docs"
#     ".toml": "config"
#     ".yaml": "config"
```

### 3.4 Tests to Write

Create a test in `tests/unit/test_config.py` (or extend the existing one):

1. **Test default SearchConfig**: `SearchConfig()` should have `enabled=False`, `mode="remote"`, etc.
2. **Test invalid mode**: `SearchConfig(mode="invalid")` should raise `ValidationError`.
3. **Test Config with search section**: Load a `Config` with a search config dict and verify it parses correctly.
4. **Test YAML loading with search**: Write a temporary `remora.yaml` that includes a `search:` section and verify `load_config()` picks it up.

---

## 4. Step 3: Create SearchService

### 4.1 File: `core/search.py`

Create a new file at `src/remora/core/search.py`. This is the core of the integration — a service class that wraps embeddy for both remote and local modes.

**Module structure:**

```python
"""Semantic search service backed by embeddy."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from remora.core.config import SearchConfig

logger = logging.getLogger(__name__)

# Conditional imports — embeddy is optional
try:
    from embeddy.client import EmbeddyClient
except ImportError:
    EmbeddyClient = None  # type: ignore[assignment,misc]


class SearchService:
    """Async semantic search service backed by embeddy.

    Supports remote (EmbeddyClient) and local (Pipeline + SearchService) modes.
    Gracefully degrades to no-op when embeddy is not configured or unavailable.
    """

    def __init__(self, config: SearchConfig, project_root: Path) -> None: ...

    @property
    def available(self) -> bool: ...

    async def initialize(self) -> None: ...
    async def close(self) -> None: ...

    async def search(
        self,
        query: str,
        collection: str | None = None,
        top_k: int = 10,
        mode: str = "hybrid",
    ) -> list[dict[str, Any]]: ...

    async def find_similar(
        self,
        chunk_id: str,
        collection: str | None = None,
        top_k: int = 10,
    ) -> list[dict[str, Any]]: ...

    async def index_file(self, path: str, collection: str | None = None) -> None: ...
    async def delete_source(self, path: str, collection: str | None = None) -> None: ...
    async def index_directory(
        self,
        path: str,
        collection: str | None = None,
        include: list[str] | None = None,
        exclude: list[str] | None = None,
    ) -> dict[str, Any]: ...

    def collection_for_file(self, path: str) -> str: ...
```

### 4.2 Remote Mode Implementation

The remote mode is the primary path. It uses `EmbeddyClient` which is a thin httpx wrapper.

**`__init__`:**

```python
def __init__(self, config: SearchConfig, project_root: Path) -> None:
    self._config = config
    self._project_root = project_root
    self._client: Any = None      # EmbeddyClient when in remote mode
    self._pipeline: Any = None     # Pipeline when in local mode
    self._search_svc: Any = None   # embeddy SearchService when in local mode
    self._store: Any = None        # VectorStore when in local mode
    self._available = False
```

**`initialize` (remote):**

```python
async def initialize(self) -> None:
    if not self._config.enabled:
        logger.info("Search service disabled by configuration")
        return

    if EmbeddyClient is None:
        logger.warning(
            "Search enabled but embeddy is not installed. "
            "Install with: pip install remora[search]"
        )
        return

    if self._config.mode == "remote":
        self._client = EmbeddyClient(
            base_url=self._config.embeddy_url,
            timeout=self._config.timeout,
        )
        try:
            await self._client.health()
            self._available = True
            logger.info("Search service connected to %s", self._config.embeddy_url)
        except Exception:
            logger.warning(
                "Embeddy server not reachable at %s — search unavailable",
                self._config.embeddy_url,
            )
    elif self._config.mode == "local":
        await self._initialize_local()
```

**`search` (remote):**

```python
async def search(
    self,
    query: str,
    collection: str | None = None,
    top_k: int = 10,
    mode: str = "hybrid",
) -> list[dict[str, Any]]:
    if not self._available:
        return []
    target = collection or self._config.default_collection
    if self._client is not None:
        result = await self._client.search(
            query, target, top_k=top_k, mode=mode
        )
        return result.get("results", [])
    # Local mode path (see §4.3)
    ...
```

**Key point about the EmbeddyClient API**: The `search()` method signature is:

```python
await client.search(
    query,                  # positional: str
    collection="default",   # positional: str
    *,                      # keyword-only after this
    top_k=10,
    mode="hybrid",
    filters=None,
    min_score=None,
    hybrid_alpha=0.7,
    fusion="rrf",
)
```

It returns a dict like:

```python
{
    "results": [
        {
            "chunk_id": "uuid",
            "content": "...",
            "score": 0.85,
            "source_path": "src/auth.py",
            "content_type": "python",
            "chunk_type": "function",
            "start_line": 42,
            "end_line": 67,
            "name": "authenticate_user",
            "metadata": {}
        }
    ],
    "query": "...",
    "collection": "code",
    "mode": "hybrid",
    "total_results": 10,
    "elapsed_ms": 85.2
}
```

Similarly implement `find_similar`, `index_file`, `delete_source`, `index_directory`, and `close` for remote mode. Each follows the same pattern:

1. Check `self._available` — return early if False
2. Determine collection via `collection or self._config.default_collection` (or `self.collection_for_file(path)` for file operations)
3. Call the corresponding `self._client.xxx()` method
4. Return the relevant portion of the response

**`collection_for_file`:**

```python
def collection_for_file(self, path: str) -> str:
    ext = Path(path).suffix.lower()
    return self._config.collection_map.get(ext, self._config.default_collection)
```

**`close`:**

```python
async def close(self) -> None:
    if self._client is not None:
        await self._client.close()
    if self._store is not None:
        await self._store.close()
```

### 4.3 Local Mode Implementation

Local mode uses embeddy's in-process components directly. Since these require heavy dependencies (torch, transformers, etc.), all imports are **lazy** — done inside the `_initialize_local()` method, not at module level.

```python
async def _initialize_local(self) -> None:
    """Initialize local (in-process) embeddy components."""
    try:
        from embeddy import Embedder, Pipeline, VectorStore
        from embeddy.config import ChunkConfig, EmbedderConfig, StoreConfig
        from embeddy.search import SearchService as EmbeddySearchService
    except ImportError:
        logger.warning(
            "Search local mode requires full embeddy installation. "
            "Install with: pip install remora[search-local]"
        )
        return

    db_path = self._project_root / self._config.db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)

    embedder_config = EmbedderConfig(
        mode="local",
        model_name=self._config.model_name,
        embedding_dimension=self._config.embedding_dimension,
    )
    store_config = StoreConfig(db_path=str(db_path))
    chunk_config = ChunkConfig(strategy="auto")

    embedder = Embedder(embedder_config)
    self._store = VectorStore(store_config)
    await self._store.initialize()

    self._pipeline = Pipeline(
        embedder,
        self._store,
        collection=self._config.default_collection,
        chunk_config=chunk_config,
    )
    self._search_svc = EmbeddySearchService(embedder, self._store)
    self._available = True
    logger.info("Search service initialized in local mode (model: %s)", self._config.model_name)
```

**Local mode search:**

```python
# Inside search(), after the remote path:
if self._search_svc is not None:
    from embeddy.models import SearchMode
    mode_enum = SearchMode(mode)
    results = await self._search_svc.search(
        query, target, top_k=top_k, mode=mode_enum
    )
    # Convert SearchResults to list[dict] for uniform API
    return [
        {
            "chunk_id": r.chunk_id,
            "content": r.content,
            "score": r.score,
            "source_path": r.source_path,
            "content_type": r.content_type,
            "chunk_type": r.chunk_type,
            "start_line": r.start_line,
            "end_line": r.end_line,
            "name": r.name,
            "metadata": r.metadata,
        }
        for r in results.results
    ]
return []
```

**Local mode `index_file`:**

```python
# Inside index_file(), after the remote path:
if self._pipeline is not None:
    target = collection or self.collection_for_file(path)
    # Pipeline's default collection might differ, create a new Pipeline
    # or use reindex_file which handles delete+reingest
    await self._pipeline.reindex_file(path)
```

**Important note on local mode Pipeline**: The `Pipeline` is created with a default collection. If you need to index into different collections based on file type, you'll either need to create multiple Pipeline instances (one per collection) or use the `ingest_text()` method with explicit source metadata. For simplicity in the initial implementation, you can use a single collection for local mode and document the multi-collection limitation as a future enhancement.

### 4.4 Graceful Degradation

The key design principle: **every consumer checks before calling**. There are two levels:

1. **Service-level**: `RuntimeServices.search_service` can be `None` if search isn't enabled
2. **Availability-level**: `search_service.available` can be `False` if the server is unreachable

Pattern for consumers:

```python
# Level 1: service might not exist
if services.search_service is not None and services.search_service.available:
    results = await services.search_service.search(query)

# Or in TurnContext where it's stored as an attribute:
if self._search_service is not None and self._search_service.available:
    return await self._search_service.search(query, collection, top_k)
return []  # graceful empty result
```

**Never raise exceptions for missing search** — always return empty results or no-op.

### 4.5 Bootstrap Indexing

Add a method for bulk initial indexing:

```python
async def index_directory(
    self,
    path: str,
    collection: str | None = None,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> dict[str, Any]:
    """Index all files in a directory. Used for initial bootstrap.

    Returns a dict with stats about the indexing operation.
    """
    if not self._available:
        return {"error": "search service not available"}

    target = collection or self._config.default_collection
    if self._client is not None:
        return await self._client.ingest_directory(
            path, target, include=include, exclude=exclude
        )
    if self._pipeline is not None:
        stats = await self._pipeline.ingest_directory(
            path, include=include, exclude=exclude
        )
        return {
            "files_processed": stats.files_processed,
            "chunks_created": stats.chunks_created,
            "chunks_embedded": stats.chunks_embedded,
            "chunks_stored": stats.chunks_stored,
            "chunks_skipped": stats.chunks_skipped,
            "errors": [{"file_path": e.file_path, "error": e.error} for e in stats.errors],
            "elapsed_seconds": stats.elapsed_seconds,
        }
    return {"error": "no backend available"}
```

This method is called by the `remora index` CLI command (Step 9) and can also be called programmatically. The embeddy `ingest_directory()` API handles content-hash deduplication internally, so re-running it on an already-indexed directory is cheap — only changed files get re-indexed.

### 4.6 Tests to Write

Create `tests/unit/test_search.py`:

1. **Test SearchService with disabled config**: Create a `SearchService(SearchConfig(enabled=False), project_root)`, call `initialize()`, verify `available` is `False`, verify `search()` returns `[]`.

2. **Test SearchService with no embeddy installed**: Mock `EmbeddyClient = None` (simulating import failure), create service with `enabled=True`, verify graceful degradation.

3. **Test SearchService remote mode — connected**: Mock `EmbeddyClient` as a class with async methods. Mock `health()` to succeed, verify `available` is `True`. Mock `search()` to return a canned result, verify the service extracts `results` correctly.

4. **Test SearchService remote mode — unreachable**: Mock `health()` to raise `Exception`, verify `available` is `False`.

5. **Test `collection_for_file`**: Verify `.py` → `"code"`, `.md` → `"docs"`, `.unknown` → default collection.

6. **Test `index_file` delegates to client**: Mock `EmbeddyClient.reindex()`, call `index_file("src/foo.py")`, verify `reindex` was called with the right path and collection.

7. **Test `delete_source` delegates to client**: Mock `EmbeddyClient.delete_source()`, verify delegation.

8. **Test `index_directory` delegates to client**: Mock `EmbeddyClient.ingest_directory()`, verify delegation with correct arguments.

**Mocking pattern**: Since `EmbeddyClient` may not be installed in test environments, create a mock class:

```python
class MockEmbeddyClient:
    def __init__(self, base_url="", *, timeout=30.0):
        self.base_url = base_url
        self.health_response = {"status": "ok"}
        self.search_response = {"results": [], "query": "", "total_results": 0}
        # ... other canned responses

    async def health(self):
        return self.health_response

    async def search(self, query, collection="default", **kwargs):
        return self.search_response

    async def close(self):
        pass

    # ... other methods
```

Then monkey-patch `EmbeddyClient` in the module under test:

```python
import remora.core.search as search_module
search_module.EmbeddyClient = MockEmbeddyClient
```

---

## 5. Step 4: Wire SearchService into RuntimeServices

### 5.1 Changes to `core/services.py`

Add `SearchService` as an optional member of `RuntimeServices`.

**Import** (at the top of the file):

```python
from remora.core.search import SearchService
```

**In `__init__`**, add after the existing service initializations:

```python
self.search_service: SearchService | None = None
```

**In `initialize()`**, add after the existing initialization calls (e.g., after `self.reconciler` is created but before `self.reconciler.start()`):

```python
if config.search.enabled:
    self.search_service = SearchService(config.search, project_root)
    await self.search_service.initialize()
```

**Important ordering**: The search service should be initialized **before** the reconciler starts, because the reconciler will use the search service to index files as they're discovered. However, the initial full_scan happens in `lifecycle.py` after `services.initialize()`, so the search service will be ready by then.

Also pass the `search_service` to the `FileReconciler` constructor (we'll modify the reconciler in Step 7):

```python
self.reconciler = FileReconciler(
    self.config,
    self.node_store,
    self.event_store,
    self.workspace_service,
    self.project_root,
    search_service=self.search_service,  # NEW
)
```

And to `ActorPool` (we'll use it in the actor to pass to TurnContext):

```python
self.runner = ActorPool(
    self.event_store,
    self.node_store,
    self.workspace_service,
    self.config,
    dispatcher=self.dispatcher,
    metrics=self.metrics,
    search_service=self.search_service,  # NEW
)
```

**In `close()`**, add before `await self.db.close()`:

```python
if self.search_service is not None:
    await self.search_service.close()
```

### 5.2 Changes to `core/lifecycle.py`

No direct changes needed to lifecycle.py for basic wiring — RuntimeServices handles it. However, if you want to log search service status at startup, you could add after the `await services.initialize()` line:

```python
if services.search_service is not None and services.search_service.available:
    logger.info("Semantic search available via %s", config.search.mode)
```

### 5.3 Tests to Write

Extend existing `tests/unit/test_services.py` (or create one if it doesn't exist):

1. **Test RuntimeServices with search disabled**: Default config has `search.enabled=False`. Verify `services.search_service` is `None` after `initialize()`.

2. **Test RuntimeServices with search enabled**: Config with `search.enabled=True`, mock the EmbeddyClient. Verify `services.search_service` is not `None` and `available` is `True`.

3. **Test RuntimeServices.close() calls search_service.close()**: Verify cleanup order.

---

## 6. Step 5: Add Search Methods to TurnContext

### 6.1 Changes to `core/externals.py`

Add a `search_service` parameter to `TurnContext.__init__` and two new methods.

**In `__init__`**, add a new parameter:

```python
def __init__(
    self,
    node_id: str,
    workspace: AgentWorkspace,
    correlation_id: str | None,
    node_store: NodeStore,
    event_store: EventStore,
    outbox: Any,
    human_input_timeout_s: float = 300.0,
    search_content_max_matches: int = 1000,
    broadcast_max_targets: int = 50,
    send_message_rate_limit: int = 10,
    send_message_rate_window_s: float = 1.0,
    search_service: Any = None,  # NEW — SearchService or None
) -> None:
    # ... existing assignments ...
    self._search_service = search_service
```

**Note**: We use `Any` for the type annotation to avoid importing `SearchService` at module level (keeping the import optional). You could alternatively use a `TYPE_CHECKING` import:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from remora.core.search import SearchService
```

And then use `SearchService | None` in the annotation.

**Add two new methods** after the existing methods:

```python
async def semantic_search(
    self,
    query: str,
    collection: str | None = None,
    top_k: int = 10,
    mode: str = "hybrid",
) -> list[dict[str, Any]]:
    """Search the codebase using semantic similarity.

    Returns a list of search results, each a dict with: content, score,
    source_path, start_line, end_line, name, chunk_type, chunk_id.
    Returns an empty list if search is not configured.
    """
    if self._search_service is None or not self._search_service.available:
        return []
    return await self._search_service.search(query, collection, top_k, mode)

async def find_similar_code(
    self,
    chunk_id: str,
    collection: str | None = None,
    top_k: int = 10,
) -> list[dict[str, Any]]:
    """Find code chunks similar to a given chunk.

    Returns a list of search results similar to the given chunk.
    Returns an empty list if search is not configured.
    """
    if self._search_service is None or not self._search_service.available:
        return []
    return await self._search_service.find_similar(chunk_id, collection, top_k)
```

**Update `to_capabilities_dict()`** to include the new methods:

```python
def to_capabilities_dict(self) -> dict[str, Any]:
    return {
        # ... existing entries ...
        "my_correlation_id": self.my_correlation_id,
        "semantic_search": self.semantic_search,          # NEW
        "find_similar_code": self.find_similar_code,      # NEW
    }
```

### 6.2 Changes to Actor's TurnContext Construction

The `TurnContext` is constructed in `core/actor.py` in the `_prepare_turn_context` method. The `Actor` needs access to the `SearchService`.

**In `core/runner.py`** — modify `ActorPool.__init__` to accept and store `search_service`:

```python
def __init__(
    self,
    event_store: EventStore,
    node_store: NodeStore,
    workspace_service: CairnWorkspaceService,
    config: Config,
    dispatcher: TriggerDispatcher | None = None,
    metrics: Metrics | None = None,
    search_service: Any = None,  # NEW
):
    # ... existing code ...
    self._search_service = search_service
```

**In `ActorPool.get_or_create_actor`**, pass it through to the Actor:

```python
actor = Actor(
    node_id=node_id,
    event_store=self._event_store,
    node_store=self._node_store,
    workspace_service=self._workspace_service,
    config=self._config,
    semaphore=self._semaphore,
    metrics=self._metrics,
    search_service=self._search_service,  # NEW
)
```

**In `core/actor.py`** — modify `Actor.__init__` to accept `search_service`:

```python
def __init__(
    self,
    node_id: str,
    event_store: EventStore,
    node_store: NodeStore,
    workspace_service: CairnWorkspaceService,
    config: Config,
    semaphore: asyncio.Semaphore,
    metrics: Metrics | None = None,
    search_service: Any = None,  # NEW
):
    # ... existing code ...
    self._search_service = search_service
```

**In `Actor._prepare_turn_context`**, pass it when constructing the TurnContext:

```python
context = TurnContext(
    node_id=node_id,
    workspace=workspace,
    correlation_id=trigger.correlation_id,
    node_store=self._node_store,
    event_store=self._event_store,
    outbox=outbox,
    human_input_timeout_s=self._config.human_input_timeout_s,
    search_content_max_matches=self._config.search_content_max_matches,
    broadcast_max_targets=self._config.broadcast_max_targets,
    send_message_rate_limit=self._config.send_message_rate_limit,
    send_message_rate_window_s=self._config.send_message_rate_window_s,
    search_service=self._search_service,  # NEW
)
```

### 6.3 Tests to Write

Extend `tests/unit/test_externals.py`:

1. **Test `semantic_search` with no search service**: Create TurnContext without search_service (default None). Verify `semantic_search("query")` returns `[]`.

2. **Test `semantic_search` with unavailable service**: Create a mock search service with `available=False`. Verify returns `[]`.

3. **Test `semantic_search` delegates correctly**: Create a mock search service with `available=True` and a canned `search()` return. Verify `semantic_search("query", "code", 5, "hybrid")` calls `search_service.search("query", "code", 5, "hybrid")` and returns the results.

4. **Test `find_similar_code` similar pattern**: Same three-tier test as above.

5. **Test `to_capabilities_dict` includes new methods**: Verify the dict has `"semantic_search"` and `"find_similar_code"` keys.

---

## 7. Step 6: Create the Grail Tool

### 7.1 File: `bundles/system/tools/semantic_search.pym`

Create a new file at `bundles/system/tools/semantic_search.pym`:

```python
# Search the codebase using semantic similarity. Finds code related to a natural
# language query. Returns results with file paths, line numbers, and relevance scores.
from grail import Input, external

query: str = Input("query")
collection: str = Input("collection", default="")
top_k: int = Input("top_k", default=10)


@external
async def semantic_search(
    query: str, collection: str | None, top_k: int, mode: str
) -> list[dict]: ...


collection_value: str | None = collection.strip() if collection.strip() else None
results = await semantic_search(query, collection_value, int(top_k), "hybrid")

if not results:
    result = "No results found. Semantic search may not be configured, or no matches were found."
else:
    lines = []
    for r in results:
        source = r.get("source_path", "unknown")
        start = r.get("start_line", "?")
        name = r.get("name", "")
        score = r.get("score", 0)
        chunk_type = r.get("chunk_type", "")
        label = f"{name} ({chunk_type})" if name else chunk_type or "chunk"
        lines.append(f"- {source}:{start}  {label}  [score: {score:.3f}]")
        content_preview = r.get("content", "")[:200].replace("\n", " ")
        if content_preview:
            lines.append(f"  {content_preview}")
    result = "\n".join(lines)
result
```

### 7.2 How Grail Tools Work

Understanding the Grail tool pattern is important for getting this right. Looking at existing tools like `send_message.pym` and `query_agents.pym`:

1. **Imports**: `from grail import Input, external` — these are Grail framework primitives.

2. **Inputs**: `Input("name", default=...)` — declares tool parameters that the LLM fills in. The LLM sees these as the tool's input schema.

3. **`@external` functions**: These are stubs that declare the signature of externals (methods from `TurnContext.to_capabilities_dict()`). At runtime, Grail resolves these to the actual TurnContext methods. The function body is `...` (never executed — the actual implementation comes from the capabilities dict).

4. **Script body**: The actual tool logic runs as top-level script code. It calls the external functions and produces a `result` variable. The last expression in the script (or the variable named `result`) is returned to the LLM as the tool output.

**Critical**: The `@external` function name must **exactly match** a key in `to_capabilities_dict()`. Since we added `"semantic_search"` to that dict in Step 5, the Grail tool can reference it with `@external async def semantic_search(...)`.

### 7.3 Testing Approach

Grail tools are tested at the integration level — you need the Grail runtime to execute `.pym` scripts. The typical test approach:

1. **Verify the tool is discovered**: When the system bundle is loaded for an agent workspace, `semantic_search.pym` should appear in the tool list. This is already tested by the existing bundle discovery tests — adding a new `.pym` file should automatically be picked up.

2. **Manual verification**: Start remora with search configured, send a chat message to an agent asking it to search, verify the agent invokes the `semantic_search` tool.

3. **Unit test the formatting logic**: You could extract the result formatting into a helper function and unit-test it, but for a Grail script this level of testing is usually not done — the logic is simple enough to verify by inspection.

---

## 8. Step 7: Add FileReconciler Indexing Hooks

### 8.1 Changes to `code/reconciler.py`

The FileReconciler already processes file changes and deletions. We add hooks to index/deindex files.

**Modify `__init__`** to accept a search service:

```python
def __init__(
    self,
    config: Config,
    node_store: NodeStore,
    event_store: EventStore,
    workspace_service: CairnWorkspaceService,
    project_root: Path,
    search_service: Any = None,  # NEW
):
    # ... existing code ...
    self._search_service = search_service
```

**Add a helper method** that performs the actual indexing in a fire-and-forget manner (indexing should not block reconciliation):

```python
async def _index_file_for_search(self, file_path: str) -> None:
    """Index a file for semantic search. Non-blocking — errors are logged, not raised."""
    if self._search_service is None or not self._search_service.available:
        return
    try:
        await self._search_service.index_file(file_path)
    except Exception:  # noqa: BLE001
        logger.debug("Search indexing failed for %s", file_path, exc_info=True)

async def _deindex_file_for_search(self, file_path: str) -> None:
    """Remove a file from the search index. Non-blocking."""
    if self._search_service is None or not self._search_service.available:
        return
    try:
        await self._search_service.delete_source(file_path)
    except Exception:  # noqa: BLE001
        logger.debug("Search deindexing failed for %s", file_path, exc_info=True)
```

**Hook into `_do_reconcile_file`** — add at the end of the method, after `self._file_state[file_path] = (mtime_ns, new_ids)`:

```python
# Index the file for semantic search
await self._index_file_for_search(file_path)
```

**Hook into file deletion** — in `reconcile_cycle()`, inside the deleted_paths loop, after removing nodes but before removing from `_file_state`:

```python
for file_path in deleted_paths:
    _mtime, node_ids = self._file_state[file_path]
    for node_id in sorted(node_ids):
        await self._remove_node(node_id)
    await self._deindex_file_for_search(file_path)  # NEW
    self._file_state.pop(file_path, None)
```

Also in `_run_watching()`, in the deletion branch:

```python
elif str(p) in self._file_state:
    _mtime, node_ids = self._file_state[str(p)]
    for node_id in sorted(node_ids):
        await self._remove_node(node_id)
    await self._deindex_file_for_search(str(p))  # NEW
    self._file_state.pop(str(p), None)
```

### 8.2 Design Considerations

**Why not use `asyncio.create_task` for fire-and-forget?**

You could wrap the indexing in `create_task()` to avoid blocking reconciliation. However, this adds complexity around task lifecycle management and error handling. Since embeddy's `reindex()` is an HTTP call that typically completes in ~100ms (remote mode) or a few seconds (local mode), the simpler approach of awaiting inline is acceptable. If indexing latency becomes a problem, this is a straightforward optimization to make later.

**Why use `reindex_file` instead of `ingest_file`?**

For the FileReconciler hooks, `reindex_file` is correct because:
- It handles the delete-old-chunks + reingest flow atomically
- It bypasses content-hash deduplication (which would skip changed files that happen to have the same hash)
- It's the right operation for "this file was modified"

For the initial bootstrap `index_directory`, `ingest_directory` is correct because:
- It uses content-hash deduplication (skips already-indexed files)
- It's more efficient for bulk operations
- Running it again on an already-indexed directory is a no-op

**Should we filter which files get indexed?**

The reconciler already filters files via `walk_source_files` and `workspace_ignore_patterns`. Only files that pass discovery filters are reconciled, so only those files get indexed. This is the right behavior — we don't want to index `.git/` contents or `node_modules/`.

However, note that the reconciler only processes files in `discovery_paths`. If the user has files outside those paths that they want indexed, they'd need to use the `remora index` CLI command or configure additional discovery paths.

### 8.3 Tests to Write

Extend `tests/unit/test_reconciler.py`:

1. **Test reconciler without search service**: Create FileReconciler without search_service. Verify reconciliation works normally (no errors).

2. **Test reconciler with search service**: Create a mock SearchService. After reconciling a file change, verify `index_file()` was called with the correct path.

3. **Test reconciler deindexes on file delete**: After a file is removed, verify `delete_source()` was called.

4. **Test indexing failure doesn't break reconciliation**: Mock `index_file()` to raise an exception. Verify reconciliation still completes successfully (the exception is caught and logged).

---

## 9. Step 8: Add Web API Search Endpoint

### 9.1 Changes to `web/server.py`

Add a `POST /api/search` endpoint to the web server.

**Modify `create_app` signature** to accept the search service:

```python
def create_app(
    event_store: EventStore,
    node_store: NodeStore,
    event_bus: EventBus,
    metrics: Metrics | None = None,
    actor_pool: ActorPool | None = None,
    workspace_service: CairnWorkspaceService | None = None,
    search_service: Any = None,  # NEW
) -> Starlette:
```

**Add the search endpoint handler** inside `create_app`, alongside the other handlers:

```python
async def api_search(request: Request) -> JSONResponse:
    if search_service is None or not search_service.available:
        return JSONResponse(
            {"error": "Semantic search is not configured"},
            status_code=503,
        )
    data = await request.json()
    query = str(data.get("query", "")).strip()
    if not query:
        return JSONResponse({"error": "query is required"}, status_code=400)

    collection = data.get("collection") or "code"
    top_k = min(100, max(1, int(data.get("top_k", 10))))
    mode = data.get("mode", "hybrid")
    if mode not in {"vector", "fulltext", "hybrid"}:
        return JSONResponse({"error": "mode must be vector, fulltext, or hybrid"}, status_code=400)

    import time
    start = time.perf_counter()
    results = await search_service.search(query, collection, top_k, mode)
    elapsed_ms = (time.perf_counter() - start) * 1000

    return JSONResponse({
        "results": results,
        "query": query,
        "collection": collection,
        "mode": mode,
        "total_results": len(results),
        "elapsed_ms": round(elapsed_ms, 1),
    })
```

**Add the route** to the routes list:

```python
routes = [
    # ... existing routes ...
    Route("/api/health", endpoint=api_health),
    Route("/api/search", endpoint=api_search, methods=["POST"]),  # NEW
    Route("/api/cursor", endpoint=api_cursor, methods=["POST"]),
    Route("/sse", endpoint=sse_stream),
]
```

**Update `lifecycle.py`** to pass the search service to `create_app`:

```python
web_app = create_app(
    services.event_store,
    services.node_store,
    services.event_bus,
    metrics=services.metrics,
    actor_pool=services.runner,
    workspace_service=services.workspace_service,
    search_service=services.search_service,  # NEW
)
```

### 9.2 Tests to Write

Extend `tests/unit/test_web_server.py` (or create one):

1. **Test POST /api/search with no search service**: Create the app with `search_service=None`. POST to `/api/search` with a query. Verify 503 response with "not configured" error.

2. **Test POST /api/search without query**: Create app with a mock search service. POST with empty body. Verify 400 response.

3. **Test POST /api/search with invalid mode**: POST with `mode: "invalid"`. Verify 400 response.

4. **Test POST /api/search happy path**: Mock search service that returns canned results. POST with `{"query": "auth", "collection": "code", "top_k": 5}`. Verify 200 response with correct structure.

5. **Test top_k clamping**: POST with `top_k: 9999`. Verify it's clamped to 100.

---

## 10. Step 9: Add Bootstrap Index CLI Command

### 10.1 Changes to `__main__.py`

Add a `remora index` command that runs initial indexing for a project.

**Add the command** after the existing `discover_command`:

```python
@app.command("index")
def index_command(
    project_root: Annotated[Path, PROJECT_ROOT_ARG] = Path("."),
    config_path: Annotated[Path | None, CONFIG_ARG] = None,
    collection: Annotated[str | None, typer.Option("--collection", "-c")] = None,
    include: Annotated[list[str] | None, typer.Option("--include", "-i")] = None,
    exclude: Annotated[list[str] | None, typer.Option("--exclude", "-e")] = None,
    log_level: Annotated[str, LOG_LEVEL_ARG] = "INFO",
) -> None:
    """Index project files for semantic search via embeddy."""
    _configure_logging(log_level)
    try:
        asyncio.run(_index(
            project_root=project_root,
            config_path=config_path,
            collection=collection,
            include=include,
            exclude=exclude,
        ))
    except KeyboardInterrupt:
        pass
```

**Add the async implementation**:

```python
async def _index(
    *,
    project_root: Path,
    config_path: Path | None,
    collection: str | None,
    include: list[str] | None,
    exclude: list[str] | None,
) -> None:
    project_root = project_root.resolve()
    config = load_config(config_path)

    if not config.search.enabled:
        typer.echo("Error: search is not enabled in remora.yaml", err=True)
        typer.echo("Add 'search: { enabled: true }' to your config.", err=True)
        raise typer.Exit(code=1)

    from remora.core.search import SearchService

    service = SearchService(config.search, project_root)
    await service.initialize()

    if not service.available:
        typer.echo("Error: search service is not available.", err=True)
        typer.echo("Check that embeddy is installed and the server is running.", err=True)
        raise typer.Exit(code=1)

    # Index each discovery path
    from remora.code.paths import resolve_discovery_paths
    paths = resolve_discovery_paths(config, project_root)

    total_stats = {"files_processed": 0, "chunks_created": 0, "errors": []}
    for path in paths:
        if not path.exists():
            typer.echo(f"Skipping non-existent path: {path}")
            continue
        typer.echo(f"Indexing {path}...")
        stats = await service.index_directory(
            str(path),
            collection=collection,
            include=include,
            exclude=exclude,
        )
        files = stats.get("files_processed", 0)
        chunks = stats.get("chunks_created", 0)
        errors = stats.get("errors", [])
        total_stats["files_processed"] += files
        total_stats["chunks_created"] += chunks
        total_stats["errors"].extend(errors)
        typer.echo(f"  {files} files → {chunks} chunks")
        for err in errors:
            typer.echo(f"  Error: {err}", err=True)

    typer.echo(
        f"\nDone: {total_stats['files_processed']} files, "
        f"{total_stats['chunks_created']} chunks, "
        f"{len(total_stats['errors'])} errors"
    )
    await service.close()
```

**What this does:**

1. Loads config and verifies search is enabled
2. Creates a standalone `SearchService` (not through RuntimeServices, since we don't need the full runtime)
3. Iterates over each discovery path from the config
4. Calls `index_directory()` for each path
5. Reports stats as it goes
6. Clean shutdown

**Usage:**

```bash
# Index with default settings from remora.yaml
remora index

# Index into a specific collection
remora index --collection code

# Index with file filters
remora index --include "*.py" --include "*.md" --exclude "test_*"

# Index a different project root
remora index --project-root /path/to/project
```

### 10.2 Tests to Write

1. **Test index command with search disabled**: Run `_index()` with a config that has `search.enabled=False`. Verify it exits with code 1 and an error message.

2. **Test index command happy path**: Mock the SearchService, run `_index()`, verify `index_directory()` is called for each discovery path.

---

## 11. Summary: All Files Changed

### New Files

| File | ~Lines | Purpose |
|------|--------|---------|
| `src/remora/core/search.py` | ~200 | SearchConfig, SearchService |
| `bundles/system/tools/semantic_search.pym` | ~30 | Agent-facing Grail tool |
| `tests/unit/test_search.py` | ~150 | Tests for SearchService |

### Modified Files

| File | ~Delta | Change |
|------|--------|--------|
| `pyproject.toml` | +6 | Add `search` and `search-local` extras |
| `src/remora/core/config.py` | +25 | Add `SearchConfig` model, `search` field on `Config` |
| `src/remora/core/services.py` | +12 | Wire SearchService into RuntimeServices |
| `src/remora/core/externals.py` | +30 | Add `semantic_search()`, `find_similar_code()` to TurnContext |
| `src/remora/core/actor.py` | +5 | Accept and pass `search_service` |
| `src/remora/core/runner.py` | +5 | Accept and pass `search_service` |
| `src/remora/core/lifecycle.py` | +3 | Pass search_service to create_app |
| `src/remora/code/reconciler.py` | +25 | Add `_index_file_for_search`, `_deindex_file_for_search`, hooks |
| `src/remora/web/server.py` | +30 | Add `POST /api/search` endpoint |
| `src/remora/__main__.py` | +50 | Add `remora index` CLI command |
| `remora.yaml.example` | +12 | Add commented search config section |

**Total new/modified code: ~350 lines** (excluding tests).

---

## 12. Testing Strategy

### 12.1 Mocking EmbeddyClient

Since embeddy may not be installed in all test environments, you need a robust mocking strategy.

**Option A: Module-level monkey-patching** (recommended for unit tests)

Create a `tests/conftest.py` fixture or a helper in `tests/helpers/`:

```python
class MockEmbeddyClient:
    """Test double for embeddy.client.EmbeddyClient."""

    def __init__(self, base_url="", *, timeout=30.0):
        self.base_url = base_url
        self.timeout = timeout
        self.calls: list[tuple[str, tuple, dict]] = []
        self._health_ok = True
        self._search_results: list[dict] = []

    async def health(self):
        self.calls.append(("health", (), {}))
        if not self._health_ok:
            raise ConnectionError("mock: server unreachable")
        return {"status": "ok"}

    async def search(self, query, collection="default", **kwargs):
        self.calls.append(("search", (query, collection), kwargs))
        return {"results": self._search_results, "total_results": len(self._search_results)}

    async def reindex(self, path, collection="default"):
        self.calls.append(("reindex", (path, collection), {}))
        return {"files_processed": 1, "chunks_created": 5}

    async def delete_source(self, source_path, collection="default"):
        self.calls.append(("delete_source", (source_path, collection), {}))
        return {"deleted_count": 3}

    async def ingest_directory(self, path, collection="default", **kwargs):
        self.calls.append(("ingest_directory", (path, collection), kwargs))
        return {"files_processed": 10, "chunks_created": 50}

    async def close(self):
        self.calls.append(("close", (), {}))
```

Use it in tests by patching:

```python
import remora.core.search as search_mod

@pytest.fixture
def mock_embeddy_client():
    original = search_mod.EmbeddyClient
    mock_cls = MockEmbeddyClient
    search_mod.EmbeddyClient = mock_cls
    yield mock_cls
    search_mod.EmbeddyClient = original
```

**Option B: pytest-mock / unittest.mock**

Use `monkeypatch` to replace `EmbeddyClient` in the search module:

```python
def test_search_remote(monkeypatch, tmp_path):
    monkeypatch.setattr("remora.core.search.EmbeddyClient", MockEmbeddyClient)
    config = SearchConfig(enabled=True, mode="remote")
    service = SearchService(config, tmp_path)
    # ...
```

### 12.2 Test Categories

| Category | Location | What It Tests |
|----------|----------|---------------|
| Config | `test_config.py` | SearchConfig validation, YAML loading |
| SearchService | `test_search.py` | Remote/local modes, graceful degradation, all methods |
| TurnContext | `test_externals.py` | `semantic_search()`, `find_similar_code()`, capabilities dict |
| Reconciler | `test_reconciler.py` | Indexing hooks on change/delete, error isolation |
| Web API | `test_web_server.py` | POST /api/search endpoint |
| CLI | `test_cli.py` | `remora index` command |

### 12.3 Running Tests

```bash
# Run all search-related tests
devenv shell -- pytest tests/unit/test_search.py -v

# Run all tests to verify no regressions
devenv shell -- pytest tests/unit/ -v

# Run with coverage
devenv shell -- pytest tests/unit/ --cov=remora.core.search -v
```
