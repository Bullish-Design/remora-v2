# Assumptions — 49-demo-v2-update

## Project Audience
- **Primary**: Downstream demo authors who integrate `remora-v2` as a library/runtime.
- **Secondary**: Operators running Remora in dev/staging environments where internet may be restricted.

## Constraints
1. All changes are upstream in `remora-v2` — no downstream-only patches.
2. Must not break existing tests or public API surface.
3. Virtual bundles (review-agent, companion) must remain default-enabled.
4. Web UI must remain a single `index.html` + vendored static assets (no build step).
5. LSP and search remain optional extras (`remora[lsp]`, `remora[search]`).

## Key Invariants
- EventStore is the single source of truth; all new event types must go through it.
- AgentNode is a single Pydantic BaseModel — no subclasses.
- Grail tools (.pym) are the only tool execution mechanism for bundles.
- `devenv shell` is required for all test/execution commands.

## Scenarios Driving This Work
1. Demo repo needed "no-tools reactive" fallback because default virtual agents hit type-check errors during reactive turns.
2. Demo validation scripts couldn't reliably detect meaningful agent actions from `/api/events` due to missing/inconsistent error fields.
3. Demo setup required a custom script to patch `index.html` CDN references for offline use.
4. Operators hit opaque errors when search/LSP extras were not installed.
