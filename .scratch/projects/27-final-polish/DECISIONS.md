# Decisions

- Decision 001: Implement proposals in strict A->G order.
  - Rationale: matches proposal dependencies and user request.

- Decision 002: Include `tags` in replay SSE payload shape to match live event envelope.
  - Rationale: preserves a single event payload contract across replay and live streams.

- Decision 003: Added `human_input_timeout_s` to config and injected it into `TurnContext` from `Actor`.
  - Rationale: keeps timeout policy centralized and testable instead of hardcoded in externals.

- Decision 004: Workspace proposal file mapping supports `source/{node_id}` as canonical self-rewrite path.
  - Rationale: deterministic mapping from agent workspace content to on-disk node file during accept.

