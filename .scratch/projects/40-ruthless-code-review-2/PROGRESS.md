# Progress

## Status Legend
- pending
- in-progress
- done

## Phase Tracking
- [x] Phase 0 Preparation
- [x] Phase 1 Correctness Fixes
- [x] Phase 2 Delete Dead Weight
- [x] Phase 3 Type the Untyped
- [x] Phase 4 Extract BundleConfig Model
- [x] Phase 5 Decompose actor.py
- [x] Phase 6 Refactor web/server.py
- [x] Phase 7 Fix Event System Issues
- [x] Phase 8 Decompose _materialize_directories
- [x] Phase 9 Performance Fixes
- [x] Phase 10 Fix Encapsulation Violations
- [x] Phase 11 Clean Up Global State
- [x] Phase 12 Logging & Error Boundary Cleanup
- [x] Phase 13 Minor Fixes & Polish
- [ ] Phase 14 Test Suite Improvements

## Step Tracking

### Phase 1
- [x] Step 1.1 Fix TurnContext class-level mutable state
- [x] Step 1.2 Fix NodeStore batch() error handling and rollback
- [x] Step 1.3 Remove NodeStore.set_status and migrate callers

### Phase 2
- [x] Step 2.1 Delete Actor delegation wrappers
- [x] Step 2.2 Delete Actor compatibility property shims
- [x] Step 2.3 Update tests for deleted Actor compatibility APIs
- [x] Step 2.4 Fix reconciler `_normalize_dir_id` no-op

### Phase 3
- [x] Step 3.1 Create `SearchServiceProtocol`
- [x] Step 3.2 Replace search_service `object|Any` usages with protocol typing
- [x] Step 3.3 Replace search_service getattr duck-typing checks
- [x] Step 3.4 Type remaining `Any` parameters (externals/workspace/lifecycle)

### Phase 4
- [x] Step 4.1 Create `BundleConfig` and `SelfReflectConfig` models
- [x] Step 4.2 Replace `AgentTurnExecutor._read_bundle_config` manual validation
- [x] Step 4.3 Update bundle config callers/types

### Phase 5
- [x] Step 5.1 Create `core/outbox.py` and move outbox classes
- [x] Step 5.2 Create `core/trigger.py` and move trigger policy
- [x] Step 5.3 Create `core/prompt.py` and move prompt builder
- [x] Step 5.4 Create `core/turn_executor.py` and move turn executor
- [x] Step 5.5 Slim down `core/actor.py` to orchestration only
- [x] Step 5.6 Update imports and re-export verification
- [x] Step 5.7 Run full-suite verification for decomposition

### Phase 6
- [x] Step 6.1 Create `WebDeps` handler dependency dataclass
- [x] Step 6.2 Extract web handlers into module-level groups
- [x] Step 6.3 Move web helper functions to module level
- [x] Step 6.4 Simplify `create_app` wiring around `WebDeps`
- [x] Step 6.5 Verify/refactor-web commit checkpoint

### Phase 7
- [x] Step 7.1 Fix TurnDigestedEvent.tags shadow
- [x] Step 7.2 Fix CustomEvent payload nesting
- [x] Step 7.3 Fix EventBus.unsubscribe ghost registrations
- [x] Step 7.4 Verify/commit checkpoint

### Phase 8
- [x] Step 8.1 Extract helper methods from `_materialize_directories`
- [x] Step 8.2 Simplify `_materialize_directories` orchestration
- [x] Step 8.3 Verify/commit checkpoint

### Phase 9
- [x] Step 9.1 Add `EventStore.get_latest_event_by_type`
- [x] Step 9.2 Replace rewrite-proposal linear scans with targeted lookup
- [x] Step 9.3 Add `NodeStore.get_nodes_by_ids`
- [x] Step 9.4 Fix N+1 in `code/projections.py`
- [x] Step 9.5 Improve SSE event wait loop
- [x] Step 9.6 Fix N+1 in `_do_reconcile_file`
- [x] Step 9.7 Verify/commit checkpoint

### Phase 10
- [x] Step 10.1 Add `NodeStore.count_nodes()`
- [x] Step 10.2 Use `count_nodes()` in web health endpoint
- [x] Step 10.3 Update OutboxObserver dispatch strategy
- [x] Step 10.4 Verify/commit checkpoint

### Phase 11
- [x] Step 11.1 Bound Grail script source cache
- [x] Step 11.2 Add discovery cache clear helper
- [x] Step 11.3 Verify/commit checkpoint

### Phase 12
- [x] Step 12.1 Demote hot-path logs to DEBUG
- [x] Step 12.2 Document catch-all error boundaries
- [x] Step 12.3 Verify/commit checkpoint

### Phase 13
- [x] Step 13.1 Replace SHA-1 with SHA-256 in workspace safe IDs
- [x] Step 13.2 Make web chat rate limiting per-client
- [x] Step 13.3 Pass configured web port into LSP chat command URI
- [x] Step 13.4 Skip `_discover` async signature churn (per guide)
- [x] Step 13.5 Remove dead `name_node` parameter from discovery name builder
- [x] Step 13.6 Skip language-property refactor (per guide)
- [x] Step 13.7 Remove redundant subscriptions create_tables call
- [x] Step 13.8 Verify/commit checkpoint
