# Decisions

- Decision: split remediation into independent workstreams (WS1-WS6) with explicit acceptance criteria.
  - Rationale: allows incremental delivery and commit-by-workstream without losing traceability.
- Decision: prioritize high-risk behavioral gaps before broadening infra-level coverage.
  - Rationale: prevents regressions in production bundle scripts used by agent runtime.
- Decision: keep WS4 and WS5 as environment-gated integration/acceptance modules.
  - Rationale: remote search backend and Playwright Chromium are optional runtime dependencies; skip reasons are explicit
    and deterministic when unavailable.
- Decision: assert `workspace/executeCommand` trigger behavior semantically in WS6 (manual trigger event emitted), not
  by strict target-node equality.
  - Rationale: process-level pygls argument normalization can vary; event-path coverage is the stable acceptance target.
