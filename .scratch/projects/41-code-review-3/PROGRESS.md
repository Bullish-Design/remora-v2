# Project 41: Code Review 3 - Implementation Progress

## Status Legend
- pending
- in-progress
- done

## Phase Tracking
- [ ] Phase 1 Model Cleanup & Quick Wins
- [ ] Phase 2 Bug Fixes & Type Safety
- [ ] Phase 3 Structural Decomposition
- [ ] Phase 4 Turn Pipeline Simplification
- [ ] Phase 5 Performance & Polish

## Step Tracking

### Phase 1
- [ ] 1.1 Unify the Node Model (CSTNode -> Node)
- [ ] 1.2 Remove Test-Driven Production Indirection
- [ ] 1.3 Make `_expand_env_vars` Public
- [ ] 1.4 Fix Config Silent Drops
- [ ] 1.5 Remove Dead Config
- [ ] 1.6 Add `project_root` Property to Workspace Service

### Phase 2
- [ ] 2.1 Fix Event Type Dispatch
- [ ] 2.2 Fix the Rate Limiter Bug

### Phase 3
- [ ] 3.1 Decompose the Reconciler
- [ ] 3.2 Decompose the Web Server

### Phase 4
- [ ] 4.1 Simplify the Turn Executor
- [ ] 4.2 Decompose the Externals God-Object

### Phase 5
- [ ] 5.1 Batch Event Commits
- [ ] 5.2 Clean Up Grail Caching
- [ ] 5.3 Fix NodeStore.batch() Transaction Management
- [ ] 5.4 Use asyncio.iscoroutinefunction in EventBus
- [ ] 5.5 Miscellaneous Polish
