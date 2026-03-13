# Context

## Current Status
REFINED_CONCEPT_OVERVIEW.md has been written and corrected after studying the Cairn codebase.

Key correction: Cairn workspaces are **fsdantic database files** (`.db`), not filesystem directories. Each workspace is backed by a libsql database via `Fsdantic.open(path=...)`. They provide a virtual filesystem API (`workspace.files.read/write/query/search`) plus a KV store (`workspace.kv.get/set/delete/list`). The data layout is `.remora/stable.db` + `.remora/agents/{safe_id}.db` per node.

## Key Decisions
1. **State storage**: Cairn workspace databases for all internal node state.
2. **HumanChatEvent**: Replace with AgentMessageEvent(from_agent="user"). Migrate now.
3. **Turn modes**: Prompt-level injection only. Two modes: chat and reactive.
4. **Node spawning**: Deferred.

## What Just Happened
- Studied Cairn codebase in `.context/cairn/` — understood fsdantic, database-backed workspaces, KV store, overlay semantics.
- Corrected workspace descriptions throughout REFINED_CONCEPT_OVERVIEW.md (was incorrectly describing filesystem directories).
- Added two new appendix items: A16 (use workspace KV store for structured state) and A17 (use fsdantic overlay semantics instead of hand-rolled fallback in AgentWorkspace).

## Next Step
User reviews the corrected document. Then iterate on feedback or begin implementation planning.
