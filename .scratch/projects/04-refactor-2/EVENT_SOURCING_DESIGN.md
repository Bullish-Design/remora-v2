# Event Sourcing Design Outline (Phase 12 / R22)

## Scope
- This phase is design-only.
- No runtime migration is implemented in this pass.

## Proposed Architecture
1. Keep `EventStore` as the append-only source of truth.
2. Introduce projections that materialize read models from events:
   - `NodeProjection`
   - `AgentProjection`
   - `SubscriptionProjection`
   - `RewriteProjection`
3. Convert write paths from direct store mutation to event emission:
   - `StatusTransitionEvent`
   - `RewriteAppliedEvent`
   - `SubscriptionCreatedEvent`
   - `SubscriptionRemovedEvent`
4. Add snapshot + replay:
   - Load latest snapshot on startup
   - Replay events from snapshot offset to head
   - Continue live projection application

## Migration Boundaries
- Keep existing `NodeStore`/`AgentStore` behavior for now.
- Add event types and projection framework first.
- Move one write-path at a time to event-first semantics.
- Defer full cutover until startup replay and snapshot performance are validated.

## Risk / Cost Summary
- Benefits: full audit trail, deterministic replay, easier state forensics.
- Costs: larger conceptual complexity, strict projection consistency requirements, snapshot lifecycle management.
- Estimated effort from guide appendix: 2-3 weeks focused implementation.

## Recommendation
- Defer full event-sourcing migration at current project scale.
- Revisit when one or more conditions are true:
  - Production debugging demands full replay/time-travel.
  - Multi-process/distributed runtime is planned.
  - Team capacity exists for migration + operational tooling.

## References
- Guide phase: `.scratch/projects/04-refactor-2/REFACTORING_GUIDE_2.md` (Phase 12)
- Full sketch: `.scratch/projects/04-refactor-2/REFACTORING_GUIDE_2.md` (Appendix C)
