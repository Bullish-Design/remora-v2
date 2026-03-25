# Decisions

## Decision 001
Use a minimal, local fix in `api_proposal_accept` (event emission ordering + correlation-aware verification tests) rather than introducing new event infrastructure.

### Rationale
- Resolves the observed demo breakage directly.
- Lowest risk and smallest blast radius.
- Preserves existing proposal and reconciler architecture.
