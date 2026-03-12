# Context

## Status
Setup complete. Awaiting user direction to begin implementation.

## What Was Done
1. Created project directory: `.scratch/projects/05-dual-path-removals/`
2. Wrote comprehensive `BACKUP_PATH_REVIEW.md` with detailed analysis of 8 dual-path patterns
3. Created `PLAN.md` with 5-phase implementation approach

## Key Findings

### Primary Backup Path (HIGH PRIORITY)
- **FileReconciler watchfiles → polling fallback** (`reconciler.py:76-133`)
- Currently silently falls back to 1-second polling if `watchfiles` not installed
- Should fail fast during development

### Secondary Issues
- ContentChangedEvent + watchfiles dual detection (potential duplicate reconciliation)
- Language resolution fallback chain (masks config errors)
- Broad exception handlers (hide root causes)

### Patterns to Keep (Intentional)
- Agent → stable workspace fallback (valid architecture)
- Env var expansion with defaults (explicit config)
- Subscription cache lazy rebuild (optimization)

## Next Steps
User to review `BACKUP_PATH_REVIEW.md` and decide which phases to implement.

## Files Created
- `.scratch/projects/05-dual-path-removals/BACKUP_PATH_REVIEW.md`
- `.scratch/projects/05-dual-path-removals/PLAN.md`
- `.scratch/projects/05-dual-path-removals/CONTEXT.md` (this file)
