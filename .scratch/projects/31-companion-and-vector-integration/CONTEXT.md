# Context — Companion & Vector Integration

## Status: COMPLETE (brainstorming phase)

Both brainstorming documents have been written:

### COMPANION_BRAINSTORMING.md
- Analyzed v1's companion system (NodeAgent, 4 MicroSwarms, sidebar composer, router)
- Identified that v2's Actor already provides most of what NodeAgent did
- Proposed **post-turn hook pipeline**: one LLM call producing a `TurnDigest` (summary, tags, reflection, links) instead of 4 separate swarm classes with 3-4 LLM calls
- Agent memory stored in workspace KV under `companion/` prefix
- Memory injected into system prompt via `_build_companion_context()`
- Sidebar replaced by web API endpoint reading KV data
- **Total new code: ~255 lines** (vs v1's ~1,200 lines)
- **One new file**: `core/hooks.py`

### VECTOR_BRAINSTORMING.md
- Analyzed embeddy's full API (SPEC.md, Pipeline, SearchService, EmbeddyClient)
- Identified v1's problems: local-only, hardcoded collections, companion-only, no auto-indexing
- Proposed `SearchService` wrapping EmbeddyClient (remote) or Pipeline (local)
- Remote-first design: thin HTTP client, no torch dependency for default mode
- Automatic index maintenance hooked into FileReconciler
- Agent-accessible via TurnContext + Grail tool
- Web API search endpoint
- **Total new code: ~320 lines**
- **One new file**: `core/search.py` + one `.pym` tool
