# Assumptions

- The goal is analysis/reporting quality over immediate code changes unless critical blockers are obvious.
- "Real world" means running full flows with real process boundaries (server/client/LLM), not only mocked internals.
- Existing test commands and markers in this repo are the source of truth for intended coverage boundaries.
- Environment limitations may affect ability to run all E2E tests; such constraints must be documented explicitly.
