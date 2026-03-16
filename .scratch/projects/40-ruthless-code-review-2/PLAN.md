# Project 40 Plan

## Scope
Implement all refactors in `REVIEW_REFACTORING_GUIDE.md` phases 0-14, with verification per phase and incremental commits/pushes.

## Anti-Subagent Rule
NO SUBAGENTS. All work is performed directly in this session.

## Ordered Steps
1. Phase 0 baseline: sync deps, run tests/lint, document baseline.
2. Phase 1 correctness fixes.
3. Phase 2 dead code deletion and test rewrites.
4. Phase 3 typing refactors (SearchService protocol + Any cleanup).
5. Phase 4 BundleConfig model extraction.
6. Phase 5 actor decomposition into focused modules.
7. Phase 6 web server refactor out of closure soup.
8. Phase 7 event system fixes.
9. Phase 8 directory materialization decomposition.
10. Phase 9 performance fixes (N+1 + polling).
11. Phase 10 encapsulation fixes.
12. Phase 11 global state cleanup.
13. Phase 12 logging/error-boundary cleanup.
14. Phase 13 minor fixes/polish.
15. Phase 14 test suite improvements.

## Acceptance
- All guide steps implemented.
- Tests added/updated per guide.
- Full test suite green (excluding known ignored benchmark/integration paths when specified).
- Commits and pushes done incrementally between steps.

## Anti-Subagent Rule (Repeat)
NO SUBAGENTS. All work is performed directly in this session.
