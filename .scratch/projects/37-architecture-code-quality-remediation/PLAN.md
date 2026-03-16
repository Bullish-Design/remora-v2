# NO SUBAGENTS

## Goal
Implement all recommendations from `.scratch/projects/29-ruthless-code-review/RECOMMENDATIONS.md` in:
- Section 4: Architecture Refactors (items 4.1 through 4.5)
- Section 5: Code Quality (items 5.1 through 5.6)

Each item is implemented one-at-a-time with this cycle:
1. Make only the changes required for that item.
2. Run focused verification.
3. Commit with a single-item commit message.
4. Push to remote.
5. Update progress/context notes.

## Ordered Steps
1. 4.1 Extract Actor responsibilities into focused components.
2. 4.2 Extract runtime `_start()` lifecycle concerns into a lifecycle manager.
3. 4.3 Eliminate `hasattr(x, "value")` enum serialization pattern.
4. 4.4 Move `RecordingOutbox` out of production code and into tests.
5. 4.5 Replace monkey-patched LSP handler storage with a proper abstraction class.
6. 5.1 Fix Ruff violations in `src/remora/`.
7. 5.2 Migrate Starlette shutdown hook to lifespan API.
8. 5.3 Replace production `assert` statements with explicit runtime errors.
9. 5.4 Add type checking configuration to CI/project config.
10. 5.5 Standardize enum handling on StrEnum with boundary serialization.
11. 5.6 Import and use `__version__` in web health check.

## Acceptance Criteria
- All 11 recommendations above are implemented.
- Every item has its own commit and push.
- Tests/lint/type checks pass for touched areas.
- Scratch files (`PROGRESS.md`, `CONTEXT.md`, `DECISIONS.md`, `ISSUES.md`) are updated throughout.

# NO SUBAGENTS
