# Context

- Proposals A-G are fully implemented and each proposal was committed and pushed in sequence.
- Proposal G complete: `bundle_rules` with pattern matching now overrides type-only `bundle_overlays`; resolution is centralized in `Config.resolve_bundle()` and consumed by projection/reconciler.
- Final verification sweep completed over actor/events/externals/web/lsp/config/projections/reconciler + e2e integration tests.
- Current status: implementation complete and validated.
