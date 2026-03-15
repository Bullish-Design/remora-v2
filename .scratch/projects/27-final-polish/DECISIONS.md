# Decisions

- Decision 001: Implement proposals in strict A->G order.
  - Rationale: matches proposal dependencies and user request.

- Decision 002: Include `tags` in replay SSE payload shape to match live event envelope.
  - Rationale: preserves a single event payload contract across replay and live streams.

- Decision 003: Added `human_input_timeout_s` to config and injected it into `TurnContext` from `Actor`.
  - Rationale: keeps timeout policy centralized and testable instead of hardcoded in externals.

- Decision 004: Workspace proposal file mapping supports `source/{node_id}` as canonical self-rewrite path.
  - Rationale: deterministic mapping from agent workspace content to on-disk node file during accept.

- Decision 005: Implemented LSP code actions as command-backed actions (`remora.chat`, `remora.trigger`) to keep client integration fully standard.
  - Rationale: no editor-specific protocol extensions required; Neovim-compatible via native codeAction + executeCommand flow.

- Decision 006: Keep panel state client-side using SSE-reduced `agentEventCache` and avoid new server aggregation endpoints.
  - Rationale: aligns with event-projection architecture and keeps UI updates low-latency and decoupled.

- Decision 007: Kernel observer translation uses event class-name dispatch (string-based) instead of hard importing structured event classes.
  - Rationale: keeps coupling loose and avoids version-fragile runtime dependencies while preserving structured telemetry.

- Decision 008: Centralized bundle selection in `Config.resolve_bundle()` and reused it in both projection and reconciler paths.
  - Rationale: avoids duplicated rule logic and guarantees consistent role assignment semantics.

