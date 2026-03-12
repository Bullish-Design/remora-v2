# Plan: Refactor 2 Implementation

## NO SUBAGENTS - Do all work directly.

## Source of Truth
- `.scratch/projects/04-refactor-2/REFACTORING_GUIDE_2.md`
- `.scratch/CRITICAL_RULES.md`
- `.scratch/REPO_RULES.md`

## Ordered Steps
1. Phase 0 implementation: Apply critical bug fixes C1, C2, C3, H2, H3.
2. Phase 0 testing: Run and update tests for runner status reset behavior, span-based rewrite targeting, removed approve/reject API routes, and reconciler loop fault isolation.

3. Phase 1 implementation: Introduce `AsyncDB`, migrate `NodeStore`, `SubscriptionRegistry`, `EventStore`, and update startup wiring.
4. Phase 1 testing: Add `test_db.py`, migrate fixtures to `db` fixture, run full suite for constructor and wiring compatibility.

5. Phase 2 implementation: Split `events.py` into `core/events/` package (`types`, `bus`, `subscriptions`, `store`, `dispatcher`) and update all callers.
6. Phase 2 testing: Validate re-exports/backward imports, dispatcher-driven trigger flow, event summaries, and full regression suite.

7. Phase 3 implementation: Add enums (`NodeStatus`, `NodeType`, `ChangeType`), apply to models/events, enforce status transitions, make discovery IDs collision-safe, remove dead code.
8. Phase 3 testing: Add validation/transition/collision tests and update existing tests for enum-backed fields.

9. Phase 4 implementation: Separate `CodeElement` and `Agent`, add `AgentStore`, evolve schema (`agents` table), and update runner/reconciler integration.
10. Phase 4 testing: Verify agent lifecycle persistence, status transitions via `AgentStore`, and compatibility of combined migration view (`CodeNode`).

11. Phase 5 implementation: Create `AgentContext` class in `externals.py`, move externals out of runner closures, simplify runner wiring.
12. Phase 5 testing: Add `test_externals.py` for independent `AgentContext` method coverage and keep existing externals behavior parity.

13. Phase 6 implementation: Remove proposal persistence/lifecycle surfaces and make `AgentContext.apply_rewrite` the single direct rewrite path with emitted `ContentChangedEvent`.
14. Phase 6 testing: Validate direct rewrite lifecycle, verify no proposal endpoints/models remain, and ensure rewrite events include expected metadata.

15. Phase 7 implementation: Add `paths.py`, migrate path consumers, implement language plugin protocol/registry, refactor discovery to plugins, cache Grail scripts by content hash.
16. Phase 7 testing: Add plugin and path-resolution tests, confirm discovery behavior parity, and verify cache hit behavior.

17. Phase 8 implementation: Add event-driven reconciler flow with `watchfiles`-first mode and polling fallback; subscribe reconciler to content-change events.
18. Phase 8 testing: Verify watcher mode, fallback mode, parse-error isolation, and event-triggered reconcile behavior.

19. Phase 9 implementation: Move web HTML to static file, add missing SSE handlers, add batch edges endpoint, fix LSP `__all__` exports.
20. Phase 9 testing: Validate web UI event handling and `/api/edges` usage, plus unit coverage for removed/changed node SSE behavior.

21. Phase 10 implementation: Introduce `RuntimeServices` container and simplify `__main__.py` startup/shutdown orchestration.
22. Phase 10 testing: Verify runtime initialization, service lifecycle shutdown, and end-to-end startup flow.

23. Phase 11 implementation: Create `tests/factories.py`, migrate duplicated helpers, and add missing coverage listed in the guide.
24. Phase 11 testing: Run full unit suite, ensure new coverage areas pass, and confirm consolidated factories are used across tests.

25. Phase 12 implementation: Produce event-sourcing design artifacts only (no runtime migration in this pass).
26. Phase 12 validation: Confirm architecture sketch and recommendation are documented and linked for future work.

27. Final validation: Run full project test command from repo rules and confirm all phase acceptance criteria from `REFACTORING_GUIDE_2.md` are satisfied.
28. Final project updates: Update `PROGRESS.md`, `CONTEXT.md`, and `DECISIONS.md`; record blockers in `ISSUES.md` if any remain.

## Execution Notes
- Run dependency sync before first test run: `devenv shell -- uv sync --extra dev`
- Use `devenv shell --` for tests, linting, and project tooling commands.
- Do not begin the next phase until the current phase test step passes.

## NO SUBAGENTS - Do all work directly.
