# Assumptions

- Scope includes every fix/improvement/recommendation listed in `.scratch/projects/14-code-review-and-demo/CODE_REVIEW.md` section 8.
- Demo-readiness recommendations from section 6 are captured as a secondary track after core runtime stability items.
- Work should be delivered incrementally with tests-first changes for behavioral safety.
- Existing public behavior should remain compatible unless an explicit deprecation plan is documented.
- LSP-related work must remain safe when optional LSP dependencies are not installed.
- Refactors prioritize clarity and maintainability without expanding architecture beyond current needs.
