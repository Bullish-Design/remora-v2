# Plan — 61-idea6-required-impl

1. Add required P0 failing tests for:
- target-only semantic backfill,
- target symbol removal cleanup,
- watch-path parity,
- startup API semantic-edge visibility,
- no duplicate semantic edges across repeated cycles.

2. Implement reconciler backfill behavior with parity across:
- `reconcile_cycle`,
- `_handle_watch_changes`,
- `_on_content_changed`.

3. Validate with required pytest gate and touched-file lint.

4. Record outcomes and residual risks.

NO SUBAGENTS.
