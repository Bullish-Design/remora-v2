# Decisions

## 2026-03-15 - Path traversal handling in proposal endpoints
- Decision: Reject any resolved proposal target path outside `workspace_service._project_root` with HTTP 400.
- Rationale: Prevent arbitrary file read/write from crafted workspace proposal paths while returning explicit client-visible rejection instead of 500.
