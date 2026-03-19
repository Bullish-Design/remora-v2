# Implementation Progress - Remora V2 Code Review Refactoring

## Project Status: IN PROGRESS

## Implementation Steps

### Step 0 - Environment Setup and Baseline Verification
- [x] Create feature branch: feature/revised-recommendations-implementation
- [x] Sync dependencies: uv sync --extra dev completed
- [x] Run baseline tests: 88 passed, 1 warning
- [x] Record baseline results:
  - Baseline: 88 passed, 1 warning
  - Warning confirmed: `TurnDigestedEvent.summary` shadows parent `Event.summary` attribute
  - Branch: feature/revised-recommendations-implementation

### Step 1 - Actor Inbox Backpressure (P0)
- [ ] Add runtime config for queue bounds
- [ ] Implement bounded inbox in Actor
- [ ] Implement overflow policy handling
- [ ] Add metrics for overflow events
- [ ] Add tests for all policies

### Step 2 - TurnDigestedEvent.summary Naming Fix (P0)
- [ ] Rename field to `digest_summary`
- [ ] Add `summary()` method override
- [ ] Update all call sites
- [ ] Update tests
- [ ] Update UI/bundle references

### Step 3 - Reconciler Subscription Lifecycle (P0)
- [ ] Add subscription state tracking
- [ ] Make `start()` idempotent
- [ ] Implement unsubscribe in `stop()`
- [ ] Add lifecycle tests

### Step 4 - API Input/Output Bounds (P1)
- [ ] Add config fields for API limits
- [ ] Pass limits to WebDeps
- [ ] Enforce chat message max length
- [ ] Enforce conversation bounds
- [ ] Add tests

### Step 5 - Query Path Caching (P1)
- [ ] Resolve paths once in __init__
- [ ] Cache in instance variable
- [ ] Update _do_reconcile_file
- [ ] Add caching test

### Step 6 - Capability Return Semantics (P1)
- [ ] Update return types: write_file, kv_set, kv_delete, event_emit
- [ ] Update send_message to return result object
- [ ] Update externals version
- [ ] Update bundle scripts
- [ ] Update tests and docs

### Step 7 - Documentation Alignment (P2)
- [ ] Review lifecycle methods for idempotency
- [ ] Update docstrings
- [ ] Update documentation files

### Step 8 - Final Validation
- [ ] Run full regression suite
- [ ] Manual verification checklist
- [ ] Definition of Done verification

## Notes

- Working branch: feature/revised-recommendations-implementation
- Target: Implement all validated recommendations from CODE_REVIEW_REVIEW.md and REVISED_RECOMMENDATIONS.md
- All changes must include tests in same commit
- No backwards compatibility shims
