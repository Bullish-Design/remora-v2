# Assumptions

- Goal is development-time fail-fast behavior, specifically removing watchfiles->polling backup behavior.
- Scope includes updating tests to reflect single-path watchfiles reconciliation.
- `watchfiles` is a hard dependency (already in `[project.dependencies]`) and should be imported unconditionally.
- After code change commit/push, a second deep-dive review document is required in project `05-dual-path-removals`.
