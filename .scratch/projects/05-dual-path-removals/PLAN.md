# Dual Path Removal Plan

## Project Goal

Remove backup/fallback paths from remora-v2 to enforce fail-fast behavior during development, making issues immediately visible rather than silently degraded.

---

## Tasks

### Phase 1: Remove FileReconciler Watch → Polling Fallback [HIGH PRIORITY]

- [ ] Modify `FileReconciler.run_forever()` to fail fast if `watchfiles` unavailable
- [ ] Remove `_run_polling()` method or move to explicit opt-in mode
- [ ] Remove `_watch_mode` flag (no longer needed)
- [ ] Update tests to reflect new behavior
- [ ] Update documentation

### Phase 2: Evaluate ContentChangedEvent + Watchfiles Dual Path

- [ ] Analyze whether both mechanisms are needed
- [ ] If keeping both, add deduplication logic for same-file changes
- [ ] If removing one, document decision in DECISIONS.md

### Phase 3: Simplify Language Resolution

- [ ] Remove fallback to `get_by_extension()` in discovery
- [ ] Make unknown languages a hard error
- [ ] Update tests

### Phase 4: Add Fail-Fast Development Mode

- [ ] Add `fail_fast: bool` to Config
- [ ] Modify exception handlers to check fail_fast flag
- [ ] When fail_fast=True, raise instead of catching broad exceptions

### Phase 5: Documentation and Visibility

- [ ] Add DEBUG-level logging to workspace fallback (agent → stable)
- [ ] Add query cache invalidation mechanism
- [ ] Document all intentional fallback patterns clearly

---

## Dependencies

- None (standalone refactor)

## Acceptance Criteria

1. `watchfiles` not installed → immediate error, not silent polling
2. Misconfigured language_map → immediate error, not silent fallback
3. `--fail-fast` mode available for development
4. All tests pass
5. Documentation updated

---

## IMPORTANT

**NO SUBAGENTS.** Do all work directly — read files, search, write, edit, run commands. No delegation.

**ALWAYS CONTINUE.** Do not stop after compaction. Resume from CONTEXT.md and PROGRESS.md immediately.
