# Context — Embeddy Integration

## Current State

EMBEDDY_IMPLEMENTATION_PLAN.md is complete. It covers 9 implementation steps across 13 files, with ~350 lines of new/modified code plus tests.

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
