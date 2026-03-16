# Context — Embeddy Integration

## Current State

Implementation has started from `EMBEDDY_IMPLEMENTATION_PLAN.md`.

Completed:
- Step 1 dependency changes in `pyproject.toml`:
  - Added optional extras: `search`, `search-local`
  - Added embeddy to `dev` extras
- Ran verification commands from plan:
  - `devenv shell -- uv sync --extra search`
  - `devenv shell -- python -c "from embeddy.client import EmbeddyClient; print('OK')"`
  - Result: import check passes.
- Step 2 config changes:
  - Added `SearchConfig` model in `src/remora/core/config.py` with remote/local settings and `mode` validation.
  - Added `Config.search` field wired via `Field(default_factory=SearchConfig)`.
  - Added `SearchConfig` to module exports.
  - Updated `remora.yaml.example` with commented `search:` configuration block.
  - Added/ran config tests for defaults, invalid mode, dict parsing, and YAML loading.
  - Verification: `devenv shell -- pytest tests/unit/test_config.py -q` (13 passed).
- Step 3 search service:
  - Added `src/remora/core/search.py` with `SearchService`.
  - Supports remote mode via `EmbeddyClient` and local mode via lazy embeddy imports.
  - Added graceful degradation (`available` flag, no-op/empty responses when unavailable).
  - Implemented: `initialize`, `close`, `search`, `find_similar`, `index_file`, `delete_source`, `index_directory`, `collection_for_file`.
  - Added `tests/unit/test_search.py` with remote-mode and graceful-degradation coverage.
  - Verification: `devenv shell -- pytest tests/unit/test_config.py tests/unit/test_search.py -q` (21 passed).
- Step 4 runtime wiring:
  - Updated `src/remora/core/services.py` to own optional `search_service`.
  - `RuntimeServices.initialize()` now initializes `SearchService` when `config.search.enabled`.
  - Passed `search_service` into `FileReconciler` and `ActorPool` constructors.
  - `RuntimeServices.close()` now closes `search_service`.
  - Updated constructor signatures in `src/remora/code/reconciler.py` and `src/remora/core/runner.py` to accept `search_service`.
  - Added `tests/unit/test_services.py` for search disabled/enabled and cleanup behavior.
  - Verification:
    - `devenv shell -- pytest tests/unit/test_services.py -q` (2 passed)
    - `devenv shell -- pytest tests/unit/test_runner.py tests/unit/test_reconciler.py -q` (24 passed)
- Step 5 TurnContext + actor plumbing:
  - Updated `TurnContext` in `src/remora/core/externals.py` to accept `search_service`.
  - Added `semantic_search()` and `find_similar_code()` externals with graceful `[]` behavior when unavailable.
  - Exported new externals in `to_capabilities_dict()`.
  - Updated `AgentTurnExecutor` and `Actor` in `src/remora/core/actor.py` to carry/pass `search_service` into `TurnContext`.
  - Updated `ActorPool.get_or_create_actor()` in `src/remora/core/runner.py` to pass `search_service` to `Actor`.
  - Extended `tests/unit/test_externals.py` and `tests/unit/test_runner.py` for new search capabilities/plumbing.
  - Verification:
    - `devenv shell -- pytest tests/unit/test_externals.py tests/unit/test_runner.py tests/unit/test_actor.py -q` (63 passed)

## Deliverable Summary

The plan covers:
1. pyproject.toml — optional dependency groups (`search`, `search-local`)
2. core/config.py — SearchConfig model with mode, collection_map, etc.
3. core/search.py — NEW: SearchService with remote (EmbeddyClient) and local (Pipeline) modes
4. core/services.py — Wire SearchService into RuntimeServices
5. core/externals.py — semantic_search() and find_similar_code() on TurnContext
6. core/actor.py + core/runner.py — Pass search_service through the plumbing
7. bundles/system/tools/semantic_search.pym — NEW: Grail tool for agents
8. code/reconciler.py — _index_file_for_search / _deindex_file_for_search hooks
9. web/server.py — POST /api/search endpoint
10. __main__.py — `remora index` CLI bootstrap command
11. remora.yaml.example — Commented search config section

## Key Decisions Made
- Skip FTS5 baseline (embeddy-only)
- Cover both remote and local modes
- Include Grail tool as core functionality
- Include bootstrap indexing CLI command
- Detailed but not copy-pasteable test guidance
- Use `embeddy[server]` for `search`/`dev` extras instead of plain `embeddy` because current `embeddy` package import path executes `embeddy.__init__`, which imports server modules requiring FastAPI.

## Next Step
- Step 6: Add system Grail tool `bundles/system/tools/semantic_search.pym`.
