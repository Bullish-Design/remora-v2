# Context

Project initialized from `REVIEW_REFACTORING_GUIDE.md`.
Phase 0 complete and documented in `BASELINE_NOTES.md`.

Current baseline:
- Dependency sync completed via `devenv shell -- uv sync --extra dev`
- Tests baseline: `349 passed, 8 skipped`
- Ruff baseline: 3 pre-existing `E501` violations

Next action:
- Start Phase 1 correctness fixes, beginning with Step 1.1 (TurnContext class-level mutable state).
