# Decisions — 20-agent-consolidation-refactor

## D1: Consolidate into NodeStore (Option B)
**Decision**: Merge Node/Agent into NodeStore as single source of truth, rather than using the Agent/Node split to support virtual agents (Option A).

**Rationale**: The current split doesn't actually support virtual agents (`agent_id == node_id` is a hard invariant). Consolidating first, then adding AgentRole as a clean subscription-based layer later, is simpler and more elegant.

## D2: Delete DiscoveredElement
**Decision**: Delete DiscoveredElement entirely.

**Rationale**: It's dead code — only used by `Node.to_element()`, which is itself unused except in tests. Pure deletion target.

## D3: Node.from_row signature change
**Decision**: Change `sqlite3.Row | dict[str, Any]` to `dict[str, Any]` only.

**Rationale**: With aiosqlite migration complete, sqlite3.Row is no longer used. Simplifies the type signature.
