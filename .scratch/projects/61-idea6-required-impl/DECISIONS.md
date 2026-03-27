# Decisions — 61-idea6-required-impl

1. Implemented strategy B (conservative semantic refresh over known Python files when Python changes are detected) from REPO_UPDATES P0-1.
Rationale: meets required reliability behavior quickly and deterministically, including target-only symbol-change backfill.

2. Centralized semantic refresh trigger logic and invoked it from cycle/watch/content-change paths.
Rationale: guarantees parity (P0-2) and prevents path-specific drift.

3. Added API-level lifecycle test with bounded polling helper.
Rationale: validates demo-visible contract (`/api/health` + `/api/edges`) rather than only internal store state.
