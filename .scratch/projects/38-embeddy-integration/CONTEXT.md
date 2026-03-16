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
- Step 3: Add `src/remora/core/search.py` `SearchService` with remote/local modes and graceful degradation, plus unit tests in `tests/unit/test_search.py`.
