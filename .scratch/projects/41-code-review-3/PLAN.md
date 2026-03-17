# PLAN

## Rule Reminder
- NEVER use subagents (Task tool).
- Continue until all guide sections are complete.

## Objective
Implement all refactors in `REVIEW_REFACTOR_GUIDE.md` sections 1.1 through 5.5 with TDD and checkpoint commit/push after each section.

## Ordered Execution
1. 1.1 Unify node model and remove projections layer.
2. 1.2 Remove test-driven production indirection.
3. 1.3 Make env expansion API public.
4. 1.4 Enforce strict prompt keys in bundle config.
5. 1.5 Remove dead `file` bundle overlay default.
6. 1.6 Add `project_root` property to workspace service.
7. 2.1 Replace class-name event strings with stable `EventType` values.
8. 2.2 Move send-message rate limiter state to actor lifetime.
9. 3.1 Decompose reconciler into focused modules.
10. 3.2 Decompose web server into focused modules.
11. 4.1 Simplify turn executor boundaries.
12. 4.2 Decompose externals/TurnContext capabilities.
13. 5.1 Batch event commits.
14. 5.2 Simplify grail caching.
15. 5.3 Fix transaction semantics in `NodeStore.batch()`.
16. 5.4 Use `asyncio.iscoroutinefunction` in event bus.
17. 5.5 Misc polish from guide.

## Verification Strategy
- Per section: run targeted tests in guide.
- Per section: run full suite `devenv shell -- pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q`.
- If failures appear, fix before checkpoint commit.

## Rule Reminder
- NEVER use subagents (Task tool).
- Continue until all guide sections are complete.
