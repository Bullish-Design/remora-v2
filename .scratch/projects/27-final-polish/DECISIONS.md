# Decisions

- Decision 001: Implement proposals in strict A->G order.
  - Rationale: matches proposal dependencies and user request.

- Decision 002: Include `tags` in replay SSE payload shape to match live event envelope.
  - Rationale: preserves a single event payload contract across replay and live streams.

