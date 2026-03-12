# Decisions

## D1: Node ID Scheme — Query-Captured Name (Option A)

**Decision**: Node IDs are `file_path::name_from_query`, where the `.scm` query captures `@node` (the CodeNode) and `@node.name` (its identity text). Python code is uniform: `node_id = f"{file_path}::{name}"`. Language-specific naming logic lives exclusively in `.scm` files.

**Rationale**: Human-readable, stable across content edits, zero language-specific logic in Python. Rename = new identity is correct semantics. Collisions (duplicate names in one file) are rare and should produce a warning during discovery.

**Informed by**: ASSUMPTIONS.md constraint that custom deps are stable, REPO_RULES mandate for no isinstance in business logic (query-driven dispatch aligns).

## D2: File Reconciler — Unified Incremental Reconciliation

**Decision**: Replace both `reconcile_on_startup` and `watch_and_reconcile` with a single `FileReconciler` class. Tracks `file_path → (mtime_ns, set[node_id])`. On each cycle, only re-parses changed/new files. Detects additions, changes, and deletions. Idempotent subscription management. Runs as an asyncio task using polling.

**Rationale**: Current system has no stale node cleanup, subscriptions accumulate, and the watcher is dead code. Unified reconciler solves all three. Startup is just a full scan with empty state.

## D3: Tree-sitter Languages — Python, Markdown, TOML

**Decision**: Ship `tree-sitter-python`, `tree-sitter-markdown`, and `tree-sitter-toml` as hard dependencies, and keep direct `tree-sitter` dependency for runtime parser/query APIs. Remove Python `ast`-based parser entirely.

**Rationale**: Grammar packages provide language objects, while the parser/query runtime still imports `tree_sitter` directly (`Language`, `Parser`, `Query`, `QueryCursor`). Three languages cover the core use case. ast fallback adds complexity for no benefit.

## D4: .scm Query Files — Ship Defaults, Allow Overrides

**Decision**: Ship default `.scm` queries in `src/remora/code/queries/`. Users can override via a `queries/` directory in their project or a config path. Project queries take precedence.

## D5: Bug Fixes Included

**Decision**: Bundle all critical/high bugs from the code review into this refactor:
- `event_emit` payload discard
- `FsdFileNotFoundError` missing catch
- Subscription accumulation (solved by FileReconciler)
- Stale node cleanup (solved by FileReconciler)
- Version mismatch
- Approve endpoint file truncation risk
- XSS in web UI
