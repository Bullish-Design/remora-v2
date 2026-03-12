# Decisions

## D1: Guide-first execution
Implementation order and scope are driven by `REFACTORING_GUIDE_2.md` phase sequencing unless new constraints require updates.

## D2: No-proposals MVP path
Refactor implementation follows the revised no-proposals architecture, with direct rewrites and future Jujutsu integration hooks.

## D3: Event sourcing deferred (design captured)
Event sourcing is documented as a future architecture path in `EVENT_SOURCING_DESIGN.md` (and guide Appendix C), but runtime migration is intentionally deferred in this refactor to avoid introducing high-complexity state model changes in the same pass.
