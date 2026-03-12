# Review of `BACKUP_PATH_REVIEW.md`

## Table of Contents

1. Scope and Framing
   - Defines what counts as a harmful "backup path" versus an intentional composition pattern.
2. Overall Assessment of the Review
   - Evaluates the quality of the junior developer's analysis and where it was strongest/weakest.
3. Deep Dive on Remaining Findings (Items 2-8)
   - Detailed technical assessment of each non-watchfiles recommendation from the original review.
4. Recommended Fail-Fast Policy for remora-v2
   - Concrete development-time policy for strict behavior without destabilizing core runtime loops.
5. Prioritized Action Plan
   - Ordered next steps to reduce hidden dual-path behavior while preserving operability.
6. Final Verdict on the Junior Developer's Ideas
   - Summary judgment and coaching-style feedback on what to adopt, adjust, or reject.

## 1. Scope and Framing

The watchfiles polling fallback (Item 1) was correctly identified as the highest-impact backup path and has now been removed in code (`FileReconciler` no longer falls back to polling, and missing watch paths are treated as hard failure).

This review focuses on the **remaining items (2-8)** and applies a stricter definition:

A problematic backup path is one that:
- silently changes runtime behavior after a primary path fails,
- can hide configuration or integration errors,
- increases behavioral/test surface without clear product value.

A non-problematic dual path is one that:
- represents explicit product semantics (composition),
- is deterministic and documented,
- does not pretend to be a fallback for missing dependencies.

That distinction is important. Some entries in `BACKUP_PATH_REVIEW.md` are true fail-fast concerns; others are legitimate architecture patterns that should be made more explicit rather than removed.

## 2. Overall Assessment of the Review

The junior developer did a good first pass. The strongest parts were:
- Correctly prioritizing the watchfiles fallback as critical.
- Identifying silent behavior differences that could hide issues in development.
- Separating findings by severity instead of treating all dual-path behavior equally.

Where the analysis overreached:
- It sometimes labels intentional architecture (workspace layering, lazy cache rebuild) as "fallback" risk when those are primarily composition/performance patterns.
- It proposes global fail-fast behavior without distinguishing **developer correctness failures** from **operational resilience boundaries**.

In short: the review is directionally strong, but needs sharper classification so we don't remove useful architecture while chasing strictness.

## 3. Deep Dive on Remaining Findings (Items 2-8)

## 3.1 Item 2: `ContentChangedEvent` + filesystem watching (dual change inputs)

### Assessment
I agree with the concern. This is not a classic fallback, but it is a dual-ingest path to the same side effect (`_reconcile_file`) and can create duplicate work.

### Why this matters
Current behavior allows both:
- OS watcher events (`watchfiles.awatch`), and
- logical events (`ContentChangedEvent` via event bus)

to trigger reconciliation independently. In development, this can blur causality and make timing-dependent issues harder to diagnose.

### Recommended direction
Adopt a **single execution gate** instead of forcing single source immediately:
- Keep both inputs for now (they serve different producers).
- Route both through one dedupe/coalescing function (e.g., `_schedule_reconcile(path, mtime, source)`),
- Skip duplicate reconcile requests when mtime/hash is unchanged within a short window.

### Verdict
`ADOPT WITH MODIFICATION` (keep dual producers, unify trigger gate).

## 3.2 Item 3: Agent workspace -> stable workspace read fallback

### Assessment
I disagree that this should be treated as a backup-path smell. This is a valid overlay filesystem model, and it is central to bundle/template composition in remora.

### Real issue
The issue is not fallback semantics; it is **visibility**. Callers can't always tell whether data came from agent-local vs stable source.

### Recommended direction
Keep architecture unchanged, but improve debuggability:
- Add optional strict APIs for diagnostics (`read_local_only`, `exists_local_only`),
- Add DEBUG tracing for source-of-read when fallback occurs,
- Document overlay precedence in class docstrings and external API docs.

### Verdict
`KEEP` architecture; improve observability and explicitness.

## 3.3 Item 4: Discovery language resolution fallback chain

### Assessment
This is a legitimate fail-fast concern. The current chain can mask config mistakes by silently recovering through extension defaults.

### Risk profile
If config says one thing and registry fallback does another, behavior may appear "working" while configuration is wrong.

### Recommended direction
Use a strict rule set:
1. If extension is present in `language_map`, resolve by configured name only.
2. If configured plugin name is unknown -> hard error.
3. If extension is absent from `language_map`, either:
   - skip with DEBUG log (default), or
   - hard error in `fail_fast` mode.

This keeps explicit config authoritative and avoids silent repair.

### Verdict
`ADOPT` (with explicit strictness mode controls).

## 3.4 Item 5: Broad exception suppression across runtime boundaries

### Assessment
Partially agree. A blanket "crash on any error" policy is too blunt for long-running agent systems, but current broad catches can hide defects during development.

### Better framing
Different exceptions belong to different boundaries:
- **Configuration/bootstrap errors**: always fail fast.
- **Programmer errors in internal code paths**: fail fast in dev, structured error in prod.
- **User/tool input errors (e.g., bad tool script)**: often should remain non-fatal but visible.

### Recommended direction
Add a clear `Config.fail_fast` behavior matrix:
- `reconciler` watch-batch exceptions: re-raise in fail-fast mode.
- `runner` turn boundary exceptions: re-raise in fail-fast mode after status/event emission attempt.
- `grail` tool load errors: fail hard in fail-fast mode; warning-and-skip in non-fail-fast mode.

Also add high-signal telemetry event on caught exceptions (`RuntimeBoundaryErrorEvent`) to avoid invisible logs.

### Verdict
`ADOPT WITH POLICY MATRIX`, not global blanket crash behavior.

## 3.5 Item 6: Env var expansion with default (`${VAR:-default}`)

### Assessment
Agree with the original review: this is not a hidden backup path.

### Caveat
Defaults can still be unsafe if they silently enable insecure behavior (e.g., placeholder API keys). The pattern itself is fine; defaults chosen must be deliberate.

### Recommended direction
Keep implementation. Optionally add warnings when sensitive fields resolve to known placeholder defaults.

### Verdict
`KEEP`.

## 3.6 Item 7: LRU caches with stale query/parser state

### Assessment
Agree this is a development friction point. Not a backup path, but definitely a hidden stale-state behavior.

### Why it matters
When query files are edited, stale cache content can make developers think changes are ignored or parser behavior is inconsistent.

### Recommended direction
Two-level approach:
- Immediate: expose explicit cache clear function(s) and call during dev/test workflows.
- Better: include file mtime (or content hash) in cache key for query load.

Given fail-fast goals, stale cache should be treated as correctness risk in developer loops.

### Verdict
`ADOPT` (cache invalidation/refresh strategy).

## 3.7 Item 8: Lazy subscription cache rebuild

### Assessment
Agree with original review that this is acceptable. Lazy rebuild is a normal optimization and not a hidden backup path.

### Potential improvement
For diagnostics, emit debug metrics on cache misses/rebuild count so cache churn is visible during heavy subscription churn.

### Verdict
`KEEP` (with optional observability improvements).

## 4. Recommended Fail-Fast Policy for remora-v2

A practical policy should distinguish between "must crash" and "must remain live" classes of failure.

### 4.1 Always fail-fast
- Missing hard dependency or invalid runtime prerequisites.
- Invalid/unknown configured plugin names.
- Invalid discovery path configuration (already moving this direction).
- Startup wiring errors in `RuntimeServices`.

### 4.2 Fail-fast in dev mode (`fail_fast=true`)
- Internal boundary exceptions in runner/reconciler loops.
- Tool registration/load failures.
- Unexpected event schema/dispatch errors.

### 4.3 Non-fatal but explicit
- Agent-level execution errors caused by prompt/tool/user content.
- External transient IO failures where retry behavior is intended.

This gives strict developer feedback without turning normal long-lived runtime behavior into brittle crash loops.

## 5. Prioritized Action Plan

1. Done: remove watchfiles polling fallback.
2. Implement strict discovery resolution semantics (Item 4).
3. Add `fail_fast` mode with boundary-specific behavior (Item 5).
4. Add reconcile trigger dedupe/coalescing path for watch + event dual producers (Item 2).
5. Add query cache invalidation strategy (Item 7).
6. Improve workspace overlay observability/documentation (Item 3).
7. Add cache hit/rebuild debug metrics for subscriptions (Item 8, optional).

## 6. Final Verdict on the Junior Developer's Ideas

The junior developer's work is good and mostly aligned with the fail-fast direction. The high-confidence conclusions were correct, especially around watchfiles fallback and discovery/config strictness.

The main adjustment needed is conceptual discipline:
- Not every dual path is a bad backup path.
- Some are intentional architecture choices and should be made explicit, not removed.
- Fail-fast policy should be targeted by failure class, not applied uniformly.

Recommended coaching summary:
- Keep the same investigative rigor.
- Improve classification between fallback, composition, and resilience boundaries.
- Pair every "remove fallback" recommendation with a runtime semantics note: what behavior is intentionally preserved, and why.
