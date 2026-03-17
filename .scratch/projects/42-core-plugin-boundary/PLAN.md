# NO SUBAGENTS

## Objective
Implement all phases in `CORE_REFACTOR_GUIDE.md`, verify intern partial work, and finish the core/plugin-boundary refactor with stepwise commits.

## Execution Plan
1. Audit intern changes from `HEAD~1`, `HEAD`, and working tree, then record completed/partial/pending items.
2. Fix/finish Phase 2 (config-driven language registry) where incomplete or inconsistent.
3. Implement Phase 3 (template-driven prompts) and update callsites/tests.
4. Implement Phase 4 (bundle/query search path resolution) and remove `bundle_root` usage.
5. Implement Phase 5 completion (defaults-driven behavior config cleanup + tests).
6. Implement Phase 6 (externals API versioning contract and validation).
7. Implement Phase 7 (search optional capability boundary cleanup).
8. Run Phase 8 verification checks and final full test pass.

## Per-Step Workflow
1. Write/adjust failing tests for the step.
2. Implement minimal code changes to satisfy tests.
3. Run targeted tests for the touched area.
4. Commit and push before moving to the next step.

## Acceptance Criteria
1. Guide phases 1-8 are fully complete (including follow-up gaps from intern work).
2. No remaining `bundle_root` callsites in source/tests.
3. Prompt construction is template-driven and bundle-overridable.
4. Bundle/version/search boundaries are clean and tested.
5. Final verification passes.

# NO SUBAGENTS
