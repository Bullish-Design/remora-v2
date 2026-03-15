# Vector Search (Embeddy) Integration — Brainstorming

## Table of Contents

1. [What Embeddy Provides](#1-what-embeddy-provides)
   - 1.1 Core Capabilities
   - 1.2 Deployment Modes
   - 1.3 API Surface
2. [What v1's Integration Looked Like](#2-what-v1s-integration-looked-like)
   - 2.1 IndexingService
   - 2.2 Problems with v1's Approach
3. [v2 Integration Goals](#3-v2-integration-goals)
4. [Design: EmbeddyService as a Core Service](#4-design-embeddyservice-as-a-core-service)
   - 4.1 Service Class
   - 4.2 Lifecycle Integration
   - 4.3 Configuration
   - 4.4 Client vs. Local Mode
5. [Design: Automatic Index Maintenance](#5-design-automatic-index-maintenance)
   - 5.1 Hook into FileReconciler
   - 5.2 Incremental Reindexing on File Change
   - 5.3 Collection Strategy
6. [Design: Agent-Accessible Semantic Search](#6-design-agent-accessible-semantic-search)
   - 6.1 TurnContext API Extension
   - 6.2 Grail Tool Alternative
   - 6.3 Search Result Integration with Graph
7. [Design: Web API for Search](#7-design-web-api-for-search)
8. [Concrete Implementation Plan](#8-concrete-implementation-plan)
   - 8.1 Files to Create
   - 8.2 Files to Modify
   - 8.3 Configuration Changes
   - 8.4 Dependencies
9. [Alternative Approaches Considered](#9-alternative-approaches-considered)

---

## 1. What Embeddy Provides

### 1.1 Core Capabilities

Embeddy is an async-native Python library (v0.3.11) for:
- **Embedding**: Qwen3-VL-Embedding-2B model, 2048-dim vectors, MRL truncation support, multimodal (text/image/video)
- **Chunking**: Content-type-aware chunkers — AST-based Python chunker, heading-level Markdown chunker, paragraph chunker, sliding window, Docling bridge
- **Storage**: SQLite-backed (sqlite-vec for KNN + FTS5 for BM25), collection-based namespace, content-hash deduplication
- **Search**: Vector (KNN), full-text (BM25), and hybrid (RRF or weighted fusion) search with pre-filters
- **Pipeline**: Full ingest→chunk→embed→store orchestration with directory scanning and incremental reindex

Key properties that make it a good fit for remora:
- **Async-native**: All APIs are `async` — no thread pool hacks needed
- **SQLite-backed**: Same storage model as remora v2 (no external database dependencies)
- **Zero-config**: Works out of the box with sensible defaults
- **Client-server or in-process**: Can run locally or connect to a remote GPU server

### 1.2 Deployment Modes

1. **Local (in-process)**: `Embedder(EmbedderConfig(mode="local"))` — loads the model into the current process. Requires GPU or sufficient CPU. Good for development / single-machine setups.

2. **Remote (client)**: `EmbeddyClient(base_url="http://gpu-machine:8585")` — connects to a running embeddy server. Good for shared infrastructure where the GPU is on a different machine.

3. **Remote embedder + local store**: `Embedder(EmbedderConfig(mode="remote", remote_url="..."))` — uses remote server for embedding only, stores vectors locally. Hybrid approach.

For remora, **remote client mode is the most practical default**:
- Remora runs on the developer's machine (often CPU-only)
- The embedding model (Qwen3-VL-2B) needs a GPU for reasonable performance
- A separate embeddy server can serve multiple remora instances
- But local mode should be supported for simple setups

### 1.3 API Surface

The APIs we'll use:

**For indexing (via Pipeline or Client):**
- `pipeline.ingest_file(path)` / `client.ingest_file(path, collection)`
- `pipeline.reindex_file(path)` / `client.reindex(path, collection)`
- `pipeline.delete_source(source_path)` / `client.delete_source(source_path, collection)`
- `pipeline.ingest_directory(path, include, exclude)` / `client.ingest_directory(path, collection, include, exclude)`

**For search (via SearchService or Client):**
- `search_service.search(query, collection, top_k, mode, filters)` / `client.search(query, collection, top_k, mode, filters)`
- `search_service.find_similar(chunk_id, collection, top_k)` / `client.find_similar(chunk_id, collection, top_k)`

**For collection management:**
- `client.create_collection(name)` / `client.delete_collection(name)`
- `client.collection_stats(name)` / `client.collection_sources(name)`

---

## 2. What v1's Integration Looked Like

### 2.1 IndexingService

v1's `companion/indexing_service.py` was a thin wrapper:
- Imported `Embedder`, `Pipeline`, `SearchService`, `VectorStore` directly (local mode only)
- Created one Pipeline per collection ("python", "markdown", "config")
- Exposed `index_file()`, `reindex_file()`, `search()`, `index_directory()`
- Collection-to-file-type mapping was hardcoded (`{".py": "python", ".md": "markdown"}`)
- Called from the companion system only — agents couldn't use it directly

### 2.2 Problems with v1's Approach

1. **Local mode only.** No support for remote embeddy server. This meant remora v1 loaded the full embedding model into the LSP process — bad for memory and startup time.

2. **Hardcoded collection mapping.** Python files → "python" collection, markdown → "markdown", everything else → "config". No way to customize.

3. **Companion-only access.** The IndexingService was part of the companion subsystem. Regular agents (SwarmExecutor, AgentRunner) couldn't do semantic search.

4. **No incremental updates.** Indexing was manual — you had to call `index_directory()` or `reindex_file()` explicitly. No integration with file watching.

5. **Tightly coupled to companion config.** The IndexingConfig was nested inside CompanionConfig with embedder/store/chunk sub-configs that duplicated embeddy's own config hierarchy.

---

## 3. v2 Integration Goals

1. **Remote-first, local-optional.** Default to `EmbeddyClient` connecting to a running server. Support local mode for simple setups.

2. **Automatic index maintenance.** When files change (detected by FileReconciler / watchfiles), automatically reindex the changed files. No manual indexing step.

3. **Agent-accessible.** Any agent can do semantic search via TurnContext or Grail tools. Not locked to a companion subsystem.

4. **Configurable collections.** Map file types to collections via `remora.yaml`, not hardcoded.

5. **Graceful degradation.** If embeddy isn't configured or unavailable, remora still works. Semantic search just isn't available. No crashes, no import errors.

6. **Minimal coupling.** The integration should be a thin service that wraps EmbeddyClient/Pipeline, wired through RuntimeServices. If embeddy disappears tomorrow, we delete one service and its config block.

---

## 4. Design: EmbeddyService as a Core Service

### 4.1 Service Class

```python
# core/search.py

class SearchService:
    """Async semantic search service backed by embeddy.

    Supports remote (EmbeddyClient) and local (Pipeline + SearchService) modes.
    Gracefully degrades to no-op when embeddy is not configured.
    """

    def __init__(self, config: SearchConfig) -> None:
        self._config = config
        self._client: EmbeddyClient | None = None
        self._local_pipeline: Pipeline | None = None
        self._local_search: EmbeddySearchService | None = None
        self._available = False

    async def initialize(self) -> None:
        """Connect to embeddy server or initialize local pipeline."""
        if not self._config.enabled:
            return
        if self._config.mode == "remote":
            self._client = EmbeddyClient(
                base_url=self._config.embeddy_url,
                timeout=self._config.timeout,
            )
            # Verify connectivity
            try:
                await self._client.health()
                self._available = True
            except Exception:
                logger.warning("Embeddy server not reachable at %s", self._config.embeddy_url)
        else:
            # Local mode — lazy import to avoid torch dependency when not needed
            from embeddy import Embedder, Pipeline, SearchService as EddySearch, VectorStore
            from embeddy.config import EmbedderConfig, StoreConfig, ChunkConfig
            # ... initialize local components
            self._available = True

    @property
    def available(self) -> bool:
        return self._available

    async def search(
        self,
        query: str,
        collection: str = "code",
        top_k: int = 10,
        mode: str = "hybrid",
    ) -> list[dict[str, Any]]:
        """Search for code semantically similar to the query."""
        if not self._available:
            return []
        if self._client is not None:
            result = await self._client.search(query, collection, top_k=top_k, mode=mode)
            return result.get("results", [])
        # Local mode
        ...

    async def find_similar(
        self,
        chunk_id: str,
        collection: str = "code",
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """Find chunks similar to a given chunk."""
        if not self._available:
            return []
        ...

    async def index_file(self, path: str, collection: str | None = None) -> None:
        """Index or reindex a single file."""
        if not self._available:
            return
        target = collection or self._collection_for_file(path)
        if self._client is not None:
            await self._client.reindex(path, target)
        ...

    async def delete_source(self, path: str, collection: str | None = None) -> None:
        """Remove a file from the index."""
        if not self._available:
            return
        target = collection or self._collection_for_file(path)
        if self._client is not None:
            await self._client.delete_source(path, target)
        ...

    def _collection_for_file(self, path: str) -> str:
        """Map file extension to collection name."""
        ext = Path(path).suffix.lower()
        return self._config.collection_map.get(ext, self._config.default_collection)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
```

### 4.2 Lifecycle Integration

Wire into `RuntimeServices`:

```python
class RuntimeServices:
    def __init__(self, config, project_root, db):
        ...
        self.search_service: SearchService | None = None

    async def initialize(self):
        ...
        if config.search.enabled:
            self.search_service = SearchService(config.search)
            await self.search_service.initialize()

    async def close(self):
        ...
        if self.search_service is not None:
            await self.search_service.close()
```

### 4.3 Configuration

Add to `remora.yaml`:

```yaml
search:
  enabled: true
  mode: "remote"                    # "remote" or "local"
  embeddy_url: "http://localhost:8585"
  timeout: 30.0
  default_collection: "code"
  collection_map:
    ".py": "code"
    ".md": "docs"
    ".toml": "config"
    ".yaml": "config"
    ".yml": "config"
    ".json": "config"
  # Local mode only:
  db_path: ".remora/embeddy.db"
  model_name: "Qwen/Qwen3-VL-Embedding-2B"
  embedding_dimension: 2048
```

Pydantic config model:

```python
class SearchConfig(BaseModel):
    enabled: bool = False
    mode: str = "remote"  # "remote" or "local"
    embeddy_url: str = "http://localhost:8585"
    timeout: float = 30.0
    default_collection: str = "code"
    collection_map: dict[str, str] = Field(default_factory=lambda: {
        ".py": "code",
        ".md": "docs",
    })
    # Local mode settings
    db_path: str = ".remora/embeddy.db"
    model_name: str = "Qwen/Qwen3-VL-Embedding-2B"
    embedding_dimension: int = 2048
```

### 4.4 Client vs. Local Mode

**Remote mode (recommended):**
- Uses `EmbeddyClient` — thin HTTP wrapper, no torch dependency
- Requires a running embeddy server (separate process, possibly on a GPU machine)
- Remora stays lightweight — no model loading overhead
- `embeddy` is an optional dependency (only the client module is needed)

**Local mode:**
- Uses `Embedder`, `Pipeline`, `SearchService`, `VectorStore` directly
- Requires torch, transformers, sqlite-vec — heavy dependencies
- All in one process — simpler deployment but resource-intensive
- Good for development or machines with GPU

**Graceful fallback:**
- If `search.enabled: false` (default), no embeddy imports at all
- If remote server is unreachable, `available` stays `False`, search returns empty
- All agent tools that use search check `available` before calling

---

## 5. Design: Automatic Index Maintenance

### 5.1 Hook into FileReconciler

The `FileReconciler` already watches for file changes via watchfiles. When files are created/modified/deleted, it discovers nodes and provisions workspaces. We add a hook for search indexing:

```python
# In FileReconciler, after processing file changes:

async def _on_file_changed(self, path: Path) -> None:
    # ... existing node discovery and reconciliation ...

    # Index the file for semantic search
    if self._search_service is not None and self._search_service.available:
        await self._search_service.index_file(str(path))

async def _on_file_deleted(self, path: Path) -> None:
    # ... existing node removal ...

    # Remove from search index
    if self._search_service is not None and self._search_service.available:
        await self._search_service.delete_source(str(path))
```

### 5.2 Incremental Reindexing on File Change

Embeddy's `reindex_file()` handles the delete-then-reingest flow internally. Content-hash deduplication means unchanged files are skipped on `ingest_file()`. This gives us:

- **On first start**: `ingest_directory()` indexes everything, dedup skips already-indexed files
- **On file save**: `reindex_file()` updates just that file's chunks
- **On file delete**: `delete_source()` removes the file's chunks

### 5.3 Collection Strategy

Rather than one monolithic collection, split by content type:

| Collection | Extensions | Chunker | Why |
|-----------|-----------|---------|-----|
| `code` | `.py`, `.js`, `.ts`, `.rs`, `.go` | AST-based (Python) or paragraph | Code search semantics differ from prose |
| `docs` | `.md`, `.rst`, `.txt` | Heading-level markdown or paragraph | Documentation search |
| `config` | `.toml`, `.yaml`, `.json`, `.xml` | Paragraph | Config file search |

The collection mapping is fully configurable via `search.collection_map` in `remora.yaml`.

---

## 6. Design: Agent-Accessible Semantic Search

### 6.1 TurnContext API Extension

Add search methods to `TurnContext`:

```python
class TurnContext:
    def __init__(self, ..., search_service: SearchService | None = None):
        self._search_service = search_service

    async def semantic_search(
        self,
        query: str,
        collection: str = "code",
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """Search for code semantically similar to the query.

        Returns list of dicts with: content, score, source_path, start_line,
        end_line, name, chunk_type.
        """
        if self._search_service is None or not self._search_service.available:
            return []
        return await self._search_service.search(query, collection, top_k)

    async def find_similar_code(
        self,
        chunk_id: str,
        collection: str = "code",
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """Find code chunks similar to a given chunk."""
        if self._search_service is None or not self._search_service.available:
            return []
        return await self._search_service.find_similar(chunk_id, collection, top_k)
```

These get added to `to_capabilities_dict()` and are automatically available as Grail tool inputs.

### 6.2 Grail Tool Alternative

Instead of (or in addition to) TurnContext methods, provide a `semantic_search.pym` tool in the `system` bundle:

```python
# bundles/system/tools/semantic_search.pym
"""Search the codebase using semantic similarity."""

async def run(query: str, collection: str = "code", top_k: int = 10) -> str:
    results = await ctx.semantic_search(query, collection, top_k)
    if not results:
        return "No results found (semantic search may not be configured)."
    lines = []
    for r in results:
        source = r.get("source_path", "unknown")
        start = r.get("start_line", "?")
        name = r.get("name", "")
        score = r.get("score", 0)
        lines.append(f"- {source}:{start} {name} (score: {score:.3f})")
        lines.append(f"  {r.get('content', '')[:200]}")
    return "\n".join(lines)
```

**Recommendation: Both.** TurnContext methods for programmatic access from custom tools, and a built-in Grail tool for agents to use directly.

### 6.3 Search Result Integration with Graph

A powerful combination: use semantic search results to enrich the node graph. When an agent asks "find code similar to this function," the results can be cross-referenced with known nodes:

```python
async def semantic_search_with_graph(
    self, query: str, collection: str = "code", top_k: int = 10
) -> list[dict[str, Any]]:
    """Search and annotate results with node graph information."""
    results = await self.semantic_search(query, collection, top_k)
    for result in results:
        source = result.get("source_path", "")
        start = result.get("start_line")
        if source and start:
            # Try to find the containing node
            nodes = await self._node_store.list_nodes(file_path=source)
            for node in nodes:
                if node.start_line and node.end_line:
                    if node.start_line <= start <= node.end_line:
                        result["node_id"] = node.node_id
                        result["node_name"] = node.name
                        break
    return results
```

This bridges the gap between "chunks of text" (embeddy's world) and "named code elements" (remora's world).

---

## 7. Design: Web API for Search

Add a search endpoint to the web server:

```
POST /api/search
```

Request:
```json
{
  "query": "error handling for null inputs",
  "collection": "code",
  "top_k": 10,
  "mode": "hybrid"
}
```

Response:
```json
{
  "results": [
    {
      "content": "def handle_null_input(value):\n    ...",
      "score": 0.85,
      "source_path": "src/validators.py",
      "start_line": 42,
      "end_line": 58,
      "name": "handle_null_input",
      "chunk_type": "function",
      "node_id": "src.validators.handle_null_input"
    }
  ],
  "query": "error handling for null inputs",
  "total_results": 10,
  "elapsed_ms": 85.2
}
```

Implementation in `web/server.py`:

```python
@app.route("/api/search", methods=["POST"])
async def search(request):
    body = await request.json()
    if services.search_service is None or not services.search_service.available:
        return JSONResponse({"error": "Search not configured"}, status_code=503)
    results = await services.search_service.search(
        query=body["query"],
        collection=body.get("collection", "code"),
        top_k=body.get("top_k", 10),
        mode=body.get("mode", "hybrid"),
    )
    return JSONResponse({"results": results, "query": body["query"], ...})
```

---

## 8. Concrete Implementation Plan

### 8.1 Files to Create

| File | Purpose | ~Lines |
|------|---------|--------|
| `core/search.py` | `SearchConfig`, `SearchService` wrapping EmbeddyClient/Pipeline | ~180 |
| `bundles/system/tools/semantic_search.pym` | Agent-facing search tool | ~25 |

### 8.2 Files to Modify

| File | Change | ~Delta |
|------|--------|--------|
| `core/config.py` | Add `SearchConfig` as nested model, `search: SearchConfig` field on `Config` | +25 lines |
| `core/services.py` | Wire `SearchService` into `RuntimeServices` | +15 lines |
| `core/externals.py` | Add `semantic_search()`, `find_similar_code()` to `TurnContext` | +30 lines |
| `code/reconciler.py` | Add indexing hooks on file change/delete | +20 lines |
| `web/server.py` | Add `POST /api/search` endpoint | +20 lines |
| `__main__.py` | Pass search_service to reconciler if configured | +5 lines |

**Total new code: ~320 lines.**

Compare to v1's indexing service: ~120 lines, but v1 only supported local mode and had no automatic index maintenance, no agent access, no web API.

### 8.3 Configuration Changes

Add to `remora.yaml`:
```yaml
search:
  enabled: false    # Opt-in — no surprise GPU dependencies
  mode: "remote"
  embeddy_url: "http://localhost:8585"
  default_collection: "code"
  collection_map:
    ".py": "code"
    ".md": "docs"
```

### 8.4 Dependencies

**Remote mode (default):**
- `embeddy` — only the client module is needed
- `httpx` — already a transitive dependency of embeddy client

**Local mode:**
- Full embeddy with all dependencies (torch, transformers, sqlite-vec, etc.)
- These are heavy — should be an extras group: `pip install remora[embeddings]`

**Packaging approach:**
```toml
[project.optional-dependencies]
embeddings = ["embeddy>=0.3.11"]
```

For remote mode, only the client module import is needed. We can make embeddy an optional dependency and only import what's needed:

```python
# In search.py, for remote mode:
try:
    from embeddy.client import EmbeddyClient
except ImportError:
    EmbeddyClient = None  # type: ignore
```

---

## 9. Alternative Approaches Considered

### A. Direct HTTP Calls Instead of EmbeddyClient

**Rejected.** EmbeddyClient already handles URL construction, error parsing, and typed responses. Rolling our own HTTP client would be ~200 lines of duplicated code.

### B. Embed Search in SQLite Alongside Remora's DB

**Rejected.** Embeddy uses sqlite-vec virtual tables and FTS5, which require specific SQLite extensions. Mixing these into remora's existing aiosqlite database would create coupling and complicate the DB schema. Embeddy's separate DB is cleaner.

### C. Expose Raw Embeddy API to Agents

**Rejected.** Agents don't need collection management, chunking config, or embedding model details. They need `search(query) -> results`. The thin wrapper in SearchService provides the right abstraction level.

### D. Use Embeddy Server as a Sidecar (Always Running)

**Considered.** Running embeddy as an automatic sidecar process managed by remora would simplify deployment. However:
- It couples remora's lifecycle to embeddy's
- GPU resource management is better left to the user
- Docker/systemd/etc. handle sidecar management better than remora should

**Recommendation:** Document the setup pattern (run `embeddy serve` alongside `remora start`) but don't auto-manage the embeddy process.

### E. Make Search a Plugin/Extension Instead of Core

**Considered but rejected.** While search IS optional, the integration points (TurnContext, FileReconciler, RuntimeServices, web API) are all in core. Making it a plugin would require a plugin system we don't have. The simpler approach is a core service that gracefully no-ops when not configured. This is consistent with how v2 handles all optional features — present in code, activated by config.

---

## Appendix: Alternative Integration Approaches

The main body recommends a `SearchService` in `core/search.py` wrapping `EmbeddyClient` (remote) or `Pipeline` (local), wired into RuntimeServices with FileReconciler hooks. This appendix explores all other viable integration strategies in depth.

---

### Approach A: Embeddy as a Grail Tool Only (No Core Integration)

**How it works:** Don't add any search service to core. Instead, provide a `semantic_search.pym` Grail tool in the system bundle that makes direct HTTP calls to an embeddy server. Agents that want search use the tool; agents that don't, ignore it. No TurnContext changes, no RuntimeServices wiring, no FileReconciler hooks.

```python
# bundles/system/tools/semantic_search.pym
"""Search the codebase semantically via embeddy server."""
import httpx

async def run(query: str, top_k: int = 10) -> str:
    url = ctx.kv_get("embeddy_url") or "http://localhost:8585"
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{url}/api/v1/search", json={
            "query": query, "collection": "code", "top_k": top_k,
            "mode": "hybrid",
        })
        results = resp.json().get("results", [])
    # format results...
```

Indexing is handled externally — the user runs `embeddy ingest dir ./src` manually or via a cron job.

**Pros:**
- **Zero core changes.** Nothing touches actor.py, services.py, config.py, externals.py, reconciler.py. The entire integration is a single `.pym` file.
- **Maximum decoupling.** Remora knows nothing about embeddy. If embeddy disappears, you just delete a tool script.
- **Easiest to implement.** ~25 lines of code, no new modules, no config schema changes.
- **User controls indexing.** Power users can set up custom indexing pipelines, multiple collections with different chunking strategies, etc. — all outside remora.

**Cons:**
- **No automatic index maintenance.** When files change, the search index goes stale until someone manually reindexes. This is the biggest usability problem — semantic search is only useful if the index is fresh.
- **No graceful degradation.** If the embeddy server is down, the tool fails with an HTTP error at runtime. No pre-check, no fallback message.
- **Hardcoded server URL.** The tool needs to know where embeddy is. A KV store lookup per call is wasteful; a hardcoded URL is inflexible.
- **No web API search.** The web frontend can't offer search because there's no server-side search endpoint. Only agents (via tools) can search.
- **httpx as a Grail dependency.** Grail scripts currently have limited import access. We'd need to either pre-install httpx in the sandbox or add it to Grail's allowed imports.

**Implications:**
- This is the "minimum viable integration" — useful as a first step or proof of concept, but inadequate for production use due to stale indexes.
- Could be combined with a separate `reindex_on_save.pym` tool that agents call after modifying files, partially addressing the freshness problem. But this requires agents to know about indexing, which leaks infrastructure concerns into agent prompts.

**Opportunities:**
- If we start here and it proves insufficient, the Grail tool can be kept as the agent-facing interface while core integration handles the plumbing underneath. The tool would become a thin wrapper around `ctx.semantic_search()` instead of direct HTTP calls.
- Good for experimentation — lets users try semantic search without committing to a core integration.

---

### Approach B: Embeddy Server as Managed Subprocess

**How it works:** Remora spawns an embeddy server as a child process on startup and manages its lifecycle. The server runs in the background, remora connects to it as a client. On shutdown, remora stops the embeddy server.

```python
# In RuntimeServices.initialize():
if config.search.enabled and config.search.mode == "managed":
    self._embeddy_proc = await asyncio.create_subprocess_exec(
        "embeddy", "serve",
        "--port", str(config.search.embeddy_port),
        "--db", str(project_root / ".remora" / "embeddy.db"),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await self._wait_for_embeddy_ready()
    self.search_service = SearchService(config.search)
    await self.search_service.initialize()
```

**Pros:**
- **Single `remora start` command.** User doesn't need to separately start embeddy. Everything comes up together.
- **Lifecycle management.** Embeddy starts and stops with remora. No orphaned processes.
- **Auto-configuration.** Remora knows the port, DB path, and model config — no separate embeddy configuration needed.
- **Works on GPU machines.** If the user's machine has a GPU, the managed embeddy server uses it transparently.

**Cons:**
- **Process management complexity.** Handling subprocess startup, health checks, restart on crash, clean shutdown, signal forwarding — all non-trivial. Remora becomes a process manager.
- **GPU contention.** The embeddy server grabs GPU memory at startup. If the user is also running an LLM server (which remora uses for agent turns), GPU memory contention becomes a real problem.
- **Startup latency.** The Qwen3-VL-2B model takes 5-15 seconds to load. This delays remora startup significantly.
- **Platform issues.** Subprocess management differs across Linux/macOS/Windows. Signal handling, file descriptor inheritance, PATH resolution — all platform-specific.
- **Dependency coupling.** Remora now requires embeddy to be installed *and runnable* as a CLI. If embeddy is installed but its torch/transformers dependencies aren't, the subprocess fails cryptically.
- **Log interleaving.** Embeddy's logs mix with remora's unless carefully piped and labeled.

**Implications:**
- Adds significant operational complexity for something that could be a separate `docker-compose` service or systemd unit.
- Testing becomes harder — integration tests need to manage the subprocess lifecycle.
- The "mode: managed" option would exist alongside "mode: remote" and "mode: local", adding a third deployment configuration to document and support.

**Opportunities:**
- Could provide a `remora setup-embeddy` CLI command that generates a systemd unit file or Docker compose entry, without actually managing the process. This gives the convenience benefit without the process management complexity.
- A future `remora dev` command that starts everything (LLM server, embeddy, remora, web UI) could use this pattern for a zero-config development experience.

---

### Approach C: In-Process Embeddy (Library Mode, Shared Event Loop)

**How it works:** Import embeddy's core components directly into remora's process and use them as library calls. No HTTP client, no separate server. The `Embedder`, `VectorStore`, `Pipeline`, and `SearchService` live in the same async event loop as remora.

```python
# In core/search.py:
from embeddy import Embedder, Pipeline, SearchService, VectorStore
from embeddy.config import EmbedderConfig, StoreConfig, ChunkConfig

class InProcessSearch:
    def __init__(self, config):
        self._embedder = Embedder(EmbedderConfig(
            mode="local",
            model_name=config.model_name,
            embedding_dimension=config.dimension,
        ))
        self._store = VectorStore(StoreConfig(db_path=config.db_path))
        self._pipeline = Pipeline(self._embedder, self._store, collection="code")
        self._search = SearchService(self._embedder, self._store)

    async def initialize(self):
        await self._store.initialize()
```

**Pros:**
- **No HTTP overhead.** Function calls instead of HTTP round-trips. Search is ~10x faster (microseconds vs. milliseconds for HTTP).
- **No separate process.** Single process, single event loop, simpler deployment.
- **Shared SQLite.** Could potentially share the same aiosqlite connection pool (though embeddy uses its own DB).
- **Full API access.** Can use embeddy's complete internal API, not just what's exposed via REST.
- **Pipeline callbacks.** The `Pipeline.on_file_indexed` callback can directly emit remora events — tight integration without HTTP webhooks.

**Cons:**
- **Heavy dependencies.** `torch`, `transformers`, `qwen-vl-utils`, `sqlite-vec` — collectively ~2GB of dependencies. Remora goes from a lightweight CLI tool to a machine learning workload.
- **Memory usage.** The Qwen3-VL-2B model uses ~4GB GPU memory or ~8GB CPU memory. Remora's process balloons from ~100MB to ~8GB.
- **Startup time.** Model loading adds 5-15 seconds to remora startup.
- **GPU lock.** While embedding, the GPU is busy. If remora also uses the GPU for LLM inference (vLLM local), there's contention.
- **Python GIL.** CPU-intensive embedding work (if on CPU) blocks the event loop despite being async. Torch operations release the GIL for matrix math but not for tokenization.
- **Crash radius.** If embeddy hits an OOM or torch segfault, it takes remora down with it.

**Implications:**
- This is the "local mode" described in the main body, but taken further — no remote fallback, no HTTP client, everything in-process.
- Only viable for machines with GPU and sufficient memory. Not suitable as the default.
- Makes sense for a `remora[full]` install target, where the user explicitly opts into heavy dependencies.

**Opportunities:**
- The Pipeline callback integration is genuinely powerful. `on_file_indexed` can emit `ContentIndexedEvent` directly into remora's EventBus, enabling agents to react to indexing completion (e.g., "new code was indexed, re-analyze related nodes").
- In-process mode enables embedding agent workspace contents — not just source files. An agent's reflections, notes, and conversation history could be embedded for semantic retrieval. This is much harder to do with a remote server that can't access Cairn workspaces.

---

### Approach D: Agent-Owned Embeddings (Per-Agent Micro-Indexes)

**How it works:** Instead of a global project-wide index, each agent maintains its own small vector index in its workspace. The agent indexes its own source code, related files, and conversation history. Search is always scoped to the agent's local context.

```python
# Agent workspace structure:
_embeddy/
├── embeddy.db        # Per-agent sqlite-vec database
├── collection.json   # Collection metadata
```

The agent's TurnContext provides `self_search(query)` that queries only its local index.

**Pros:**
- **No global coordination.** Each agent manages its own index independently. No shared service, no central database.
- **Scoped results.** Search results are always relevant to the agent's domain — a function agent searches its own file and related files, not the entire project.
- **Workspace-native.** The index lives in Cairn, so it's automatically persisted, backed up, and cleaned up with the workspace.
- **No embeddy server needed.** Can use a minimal local embedding approach (e.g., sentence-transformers with a small model) or even TF-IDF for basic similarity.

**Cons:**
- **No cross-agent search.** "Find code similar to X anywhere in the project" is impossible — each agent only knows about its own context.
- **Redundant storage.** If 50 agents all index the same shared utility file, it's stored 50 times.
- **Model loading per agent.** Each agent would need to load an embedding model (or share one), which is complex to manage.
- **Limited context.** An agent for a function in `auth.py` might not have `user_model.py` in its index, even though they're closely related.
- **Embedding in Cairn.** Storing vector databases inside Cairn workspaces adds significant size to each workspace and complicates workspace management.

**Implications:**
- This is more of a "knowledge base per agent" pattern than a "search the codebase" pattern. Different use case.
- Could work well for agents that maintain rich workspaces (docs, notes, conversation history) where local semantic search over accumulated knowledge is valuable.
- Not a replacement for project-wide search — but could complement it.

**Opportunities:**
- A hybrid model: global project-wide index via embeddy (for cross-project search), plus per-agent micro-indexes of their workspace contents (for local knowledge retrieval). The agent tool surface would have both `semantic_search(query)` (global) and `workspace_search(query)` (local).
- Per-agent indexes could use a much cheaper embedding approach (TF-IDF, BM25-only, or a tiny 128-dim model) since the corpus is small (a few KB of notes and history, not gigabytes of code).

---

### Approach E: Event-Driven Index Maintenance (Dedicated Indexer Actor)

**How it works:** Instead of hooking into FileReconciler, create a virtual agent (e.g., `indexer`) that subscribes to `ContentChangedEvent` and `NodeDiscoveredEvent`. When files change, the indexer agent calls embeddy to reindex them. The indexer is a normal actor with a bundle that includes indexing tools.

```yaml
virtual_agents:
  - id: indexer
    role: search-indexer
    subscriptions:
      - event_types: ["ContentChangedEvent", "NodeRemovedEvent"]
```

```yaml
# bundles/indexer/bundle.yaml
system_prompt: |
  You are a search index maintenance agent. When files change,
  reindex them. When files are deleted, remove them from the index.
  Do not produce conversational output.
model: "Qwen/Qwen3-0.6B"  # Tiny model — just needs to call tools
max_turns: 1
```

**Pros:**
- **Uses existing infrastructure.** Virtual agents, subscriptions, bundles, tools — all already built. No new concepts.
- **Fully configurable.** The indexer's behavior is defined by its bundle. Want to skip certain files? Adjust the prompt or add filter tools.
- **Visible in the system.** The indexer appears in the web UI as an agent. You can see its status, history, and errors.
- **Self-healing.** If indexing fails, the agent can retry or escalate (request human input).

**Cons:**
- **LLM overhead for a non-LLM task.** Indexing is a mechanical operation (call embeddy with a file path). Using an LLM to decide "yes, reindex this file" is unnecessary overhead — it's always the correct action.
- **Latency.** ContentChangedEvent → EventStore → Dispatcher → Indexer inbox → Actor._execute_turn() → semaphore wait → LLM call → tool call → embeddy HTTP call. That's a lot of hops for what should be `reindex(path)`.
- **Concurrency slot consumption.** The indexer takes a semaphore slot while "deciding" to reindex, blocking real agent work.
- **Over-engineering.** An LLM agent that always does the same thing is just a function with extra steps.

**Implications:**
- The "agent for everything" philosophy has limits. Not every reactive behavior needs an LLM in the loop. Indexing is a good example of a behavior that should be a direct function call, not an agent turn.
- However, the virtual agent approach does make indexing *visible* — you can see in the web UI that indexing happened, when, and whether it succeeded.

**Opportunities:**
- A variant without the LLM: a "headless" actor type that runs tool scripts directly (no kernel, no LLM call) in response to events. This would be a useful pattern for purely mechanical reactive behaviors — but it's a new concept that doesn't exist in v2 yet.
- The indexer could be smarter than just reindexing: it could also update collection metadata, manage index size, prune stale entries, etc. At that point, the LLM overhead might be justified.

---

### Approach F: FTS5-Only Search (No Embeddings, No Embeddy)

**How it works:** Skip vector embeddings entirely. Use SQLite FTS5 (full-text search) directly within remora's existing aiosqlite database. When nodes are discovered, store their source code in an FTS5 virtual table. Search uses BM25 ranking.

```sql
CREATE VIRTUAL TABLE node_fts USING fts5(
    node_id, name, file_path, source_code,
    content='nodes', content_rowid='rowid',
    tokenize='porter unicode61'
);
```

```python
async def search(self, query: str, top_k: int = 10) -> list[dict]:
    rows = await self._db.execute_fetchall(
        "SELECT node_id, name, file_path, rank FROM node_fts WHERE node_fts MATCH ? ORDER BY rank LIMIT ?",
        (query, top_k),
    )
    return [{"node_id": r[0], "name": r[1], "file_path": r[2], "score": r[3]} for r in rows]
```

**Pros:**
- **Zero new dependencies.** FTS5 is built into SQLite. No embeddy, no torch, no GPU, no external server.
- **Instant search.** BM25 on a FTS5 index is sub-millisecond for project-sized codebases.
- **Trivial implementation.** ~50 lines of SQL + Python. Add an FTS5 table to NodeStore, populate on discovery, query on search.
- **Always available.** No configuration needed, no graceful degradation logic, no service health checks.
- **Integrated with node graph.** Results are node IDs, not opaque chunk IDs. No need to bridge between "chunks" and "nodes."
- **Automatic maintenance.** FTS5 content syncs with the nodes table — when nodes are updated, FTS is updated.

**Cons:**
- **No semantic understanding.** BM25 is keyword-based. "find code that handles authentication" won't find a function called `verify_credentials` unless the word "authentication" appears in its source.
- **No similarity search.** Can't do "find functions similar to this one" — that requires embeddings.
- **No cross-language understanding.** A Python function and a TypeScript function doing the same thing won't match unless they use the same words.
- **Limited ranking quality.** BM25 works well for natural language but is noisy for code (variable names, import statements, boilerplate all affect ranking).

**Implications:**
- This is the "80% solution" — covers most keyword-based search needs with zero overhead. For many projects, BM25 is sufficient.
- Could be implemented as the default search with embeddy as an optional upgrade. The search interface is the same; only the backend differs.

**Opportunities:**
- **Compelling as a baseline.** Every remora instance gets FTS5 search for free. Users who want semantic search can add embeddy. This is the graceful degradation story the main design tries to achieve with `available: False`, but better — FTS5 actually provides results instead of empty lists.
- **Hybrid with embeddy.** Use FTS5 for "quick local search" and embeddy for "deep semantic search." The TurnContext could offer `search_content()` (FTS5, always available) and `semantic_search()` (embeddy, optional). Agents naturally fall back to the cheaper option.
- **FTS5 for workspace search too.** Agent workspace contents could be indexed in FTS5 for full-text search across workspace files — useful for the companion memory use case.

---

### Approach G: Node-Aware Embeddings (Custom Chunking via Remora's Graph)

**How it works:** Instead of letting embeddy chunk files generically, use remora's tree-sitter node graph to produce chunks. Each node (function, class, method) becomes exactly one chunk. The chunk's metadata includes node_id, node_type, parent, and edges. This produces higher-quality chunks than generic AST/paragraph chunking because remora already knows the exact boundaries and relationships.

```python
# During FileReconciler, after node discovery:
for node in discovered_nodes:
    await search_service.index_node(
        node_id=node.node_id,
        content=node.source_code,
        metadata={
            "node_type": node.node_type,
            "file_path": node.file_path,
            "name": node.name,
            "parent_id": node.parent_id,
            "start_line": node.start_line,
            "end_line": node.end_line,
        },
    )
```

On the embeddy side, this uses `pipeline.ingest_text()` with pre-set metadata rather than `ingest_file()` with auto-chunking.

**Pros:**
- **Perfect chunk boundaries.** No chunking heuristics — every chunk is exactly one code element as defined by tree-sitter. No split functions, no merged classes.
- **Rich metadata.** Each chunk carries node_id, type, parent, edges — enabling graph-aware search results without post-processing.
- **Node ID as chunk ID.** Search results directly reference graph nodes, eliminating the file_path + start_line → node_id lookup.
- **Consistent with remora's model.** The unit of search is the same as the unit of agent assignment — a code element.

**Cons:**
- **File-level content missed.** Comments, imports, module-level code, and documentation between functions don't map to nodes. They'd need special handling (a "file preamble" chunk, or ignored).
- **Non-code files.** Markdown docs, config files, READMEs don't have tree-sitter nodes. These still need generic chunking via embeddy's pipeline.
- **Tighter coupling.** Remora is now responsible for chunking (via its graph) instead of delegating to embeddy. If embeddy improves its Python chunker, remora doesn't benefit.
- **Reindexing complexity.** When a file changes, we need to diff the old nodes vs. new nodes, delete removed chunks, update changed chunks, add new chunks. More complex than `reindex_file()`.

**Implications:**
- Requires a custom ingest path for code files (node-based) and a fallback to embeddy's pipeline for non-code files.
- The embeddy `Pipeline.ingest_text()` API supports this — we pass the node source as text with source metadata.
- Chunk IDs should be node IDs to maintain the graph ↔ search mapping.

**Opportunities:**
- **Graph-enhanced search.** "Find functions similar to X that are called by Y" — combine semantic similarity with graph traversal. This is a unique capability that neither pure embeddy nor pure graph search can provide alone.
- **Relationship-aware embeddings.** Include a node's edges/relationships in its embedding text (e.g., "Function `calculate_total` called by `process_order`, calls `get_price`"). This enriches the embedding with structural context, potentially improving semantic search quality for code.
- **Incremental re-embedding.** When a node changes, only re-embed that one node. No need to re-chunk or re-embed the entire file. This is more efficient than file-level reindexing.

---

### Summary Comparison Matrix

| Approach | New Dependencies | Index Freshness | Search Quality | Core Changes | Agent Access | Complexity |
|----------|:---------------:|:--------------:|:--------------:|:------------:|:------------:|:----------:|
| **Recommended (SearchService)** | embeddy (optional) | Auto (reconciler hooks) | Hybrid (semantic+BM25) | ~320 lines | TurnContext + tool | Medium |
| **A. Grail Tool Only** | httpx in Grail | Manual | Hybrid | ~25 lines | Tool only | Low |
| **B. Managed Subprocess** | embeddy (full) | Auto | Hybrid | ~400 lines | TurnContext + tool | High |
| **C. In-Process Library** | embeddy+torch | Auto | Hybrid | ~250 lines | TurnContext + tool | Medium |
| **D. Per-Agent Micro-Indexes** | embeddy (light) | Per-agent | Local only | ~300 lines | Local search | High |
| **E. Indexer Virtual Agent** | embeddy (optional) | Event-driven | Hybrid | ~100 lines | TurnContext + tool | Medium |
| **F. FTS5-Only** | None | Auto (SQL triggers) | BM25 only | ~50 lines | TurnContext | Very Low |
| **G. Node-Aware Embeddings** | embeddy (optional) | Auto (node-level) | Hybrid + graph | ~400 lines | TurnContext + tool | High |

**Recommended combination:** Start with Approach F (FTS5-only) as the always-available baseline — it's free, fast, and covers keyword search. Layer the main document's SearchService (embeddy remote) on top for semantic search when configured. Consider Approach G (node-aware chunking) as a future enhancement once the basic integration is proven, as the graph-enriched search results would be a genuinely differentiating capability.
