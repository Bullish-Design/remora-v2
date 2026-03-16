# Assumptions — Embeddy Integration

## Project Audience
- The implementation plan will be given to an **intern** — must be detailed, step-by-step, with no ambiguity
- The intern has access to the remora-v2 codebase and the embeddy library reference (SPEC.md + source in .context/embeddy/)
- The intern can write Python, understands async/await, Pydantic, and pytest

## Architecture Constraints
- Remora v2 follows: reactive agents, event-driven, SQLite persistence, Cairn workspaces, Grail tool scripts
- Config is loaded from `remora.yaml` via Pydantic `BaseSettings` in `core/config.py`
- Services are wired through `RuntimeServices` in `core/services.py`
- Agent tools are exposed via `TurnContext` in `core/externals.py` → `to_capabilities_dict()`
- File watching: `FileReconciler` in `code/reconciler.py` handles file change/add/delete events
- Web server: Starlette app in `web/server.py`, function-based route handlers

## Embeddy Integration Scope
- **Remote-first, local-optional** (per brainstorming recommendation)
- **Recommended approach**: FTS5 as always-available baseline + embeddy SearchService for semantic search when configured
- `EmbeddyClient` is the primary integration point for remote mode (thin httpx wrapper)
- embeddy is an **optional dependency** — no hard imports at module level
- Graceful degradation: if embeddy not configured or server unreachable, search returns empty results

## Integration Points (from brainstorming §8)
1. `core/search.py` — new file: SearchConfig + SearchService
2. `core/config.py` — add SearchConfig to Config
3. `core/services.py` — wire SearchService into RuntimeServices
4. `core/externals.py` — add semantic_search() and find_similar_code() to TurnContext
5. `code/reconciler.py` — add indexing hooks on file change/delete
6. `web/server.py` — add POST /api/search endpoint
7. `bundles/system/tools/semantic_search.pym` — agent-facing Grail tool

## Testing Approach
- TDD: failing test first, then implement
- Unit tests mock EmbeddyClient (no real server needed)
- Integration tests can use httpx ASGITransport against embeddy's test app if available
- Tests go in `tests/unit/` and `tests/integration/`

## What We're NOT Doing
- No FTS5 baseline in this project (brainstorming recommended it as future enhancement)
- No node-aware embeddings (Approach G — future enhancement)
- No managed subprocess mode (Approach B — rejected)
- No per-agent micro-indexes (Approach D — different use case)
