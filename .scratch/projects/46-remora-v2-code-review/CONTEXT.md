# Context - 46-remora-v2-code-review

## Current State

- Implementation guide `.scratch/projects/46-remora-v2-code-review/IMPLEMENTATION_GUIDE.md` is complete through Step 8.
- Intern commits for Steps 1-3 were audited and corrected where needed.
- Remaining Steps 4-7 were implemented end-to-end in source, tests, bundles, and docs.
- Full regression command set from the guide has been executed successfully.

## What Was Fixed During Audit

1. Step 3 lifecycle tests had invalid `await reconciler.stop()` calls; fixed to sync `stop()`.
2. Step 1 queue overflow tests only asserted queue size; expanded to assert retained message order for `drop_new` and `drop_oldest`.

## Major Implementation Outcomes

1. Actor inbox backpressure is bounded and policy-driven with overflow metrics.
2. `TurnDigestedEvent.summary` conflict removed via `digest_summary`.
3. Reconciler subscription lifecycle is explicit, idempotent, and tested.
4. Chat/conversation API bounds are configurable and enforced.
5. Reconciler query-path resolution is cached in `__init__`.
6. Capability return contracts normalized (`None` returns + structured `send_message` result).
7. Externals version bumped to 2 across runtime defaults, bundles, and docs.
8. Lifecycle/documentation alignment updates applied.

## Validation Snapshot

- Baseline smoke subset: 98 passed
- Unit sweep (events/externals/config/services): 73 passed
- Integration trio: 6 passed, 5 skipped
- Acceptance test file: 1 passed, 3 skipped

## Next Action If Work Resumes

- No pending implementation tasks from this guide.
- Optional next step: split the current branch into the suggested PR breakdown if desired.
