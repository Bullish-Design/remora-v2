# Remora-v2 Revised Recommendations

## Table of Contents

1. Executive Summary - What changes, what we drop, and why.
2. Ground Truth Findings - Confirmed issues from `CODE_REVIEW_REVIEW.md`.
3. Architecture Direction - Minimal, high-leverage structural changes.
4. Priority 0 (Immediate) - Reliability and correctness fixes.
5. Priority 1 (Near-Term) - Performance and API cleanup.
6. Priority 2 (Polish) - Design consistency and maintainability.
7. Logging Policy - Full prompt/response logging retained by design.
8. Explicit Non-Recommendations - Intern suggestions intentionally rejected.
9. Validation Plan - Tests and acceptance criteria for each change.
10. Execution Roadmap - Suggested sequencing over two weeks.
11. Definition of Done - Criteria for considering the refactor complete.

## 1. Executive Summary

This revised plan replaces the intern's recommendation set with a narrower, evidence-based refactor plan.

Key principles:
- Prioritize objectively validated defects over style opinions.
- Allow breaking changes where they improve architectural clarity.
- Keep full prompt/response logging intact (explicit product decision).
- Sequence work to reduce runtime risk first, then clean interfaces.

Primary outcomes targeted:
- Bounded runtime memory behavior under message load.
- Clearer lifecycle behavior for event subscriptions.
- Cleaner API and tool capability contracts.
- Removal of known runtime warning from event model design.
- Lower per-file reconcile overhead.

## 2. Ground Truth Findings

Confirmed from `CODE_REVIEW_REVIEW.md`:
- Actor inboxes are unbounded (`src/remora/core/agents/actor.py`, `src/remora/core/agents/runner.py`).
- `FileReconciler.start()` subscribes to event bus without explicit unsubscribe symmetry (`src/remora/code/reconciler.py`).
- `resolve_query_paths(...)` is recomputed inside per-file reconcile path (`src/remora/code/reconciler.py`).
- Several capability methods return `bool` but always return `True` (`src/remora/core/tools/capabilities.py`).
- `/api/chat` lacks explicit max input length and `/api/conversation` lacks entry-count bound (`src/remora/web/routes/chat.py`, `src/remora/web/routes/nodes.py`).
- `TurnDigestedEvent.summary` shadows base `Event.summary()` and emits warnings (`src/remora/core/events/types.py`).

Not treated as defects:
- Full prompt/response logging in turn execution is intentional and should remain enabled.

## 3. Architecture Direction

Keep architecture changes focused and incremental.

Recommended direction:
1. Introduce explicit flow-control boundaries at event ingress points.
2. Normalize public API/tool contracts to be semantically honest.
3. Make subscription lifecycle explicit and idempotent.
4. Remove unnecessary repeated compute in hot paths.

Avoid broad, speculative rewrites (clean-architecture mega-migration, technology replacement, DI framework adoption) until the validated issues above are resolved.

## 4. Priority 0 (Immediate)

### 4.1 Add Backpressure for Actor Inboxes

Problem:
- `actor.inbox` is unbounded and `put_nowait()` accepts unlimited events.

Recommendation:
- Use bounded queue for actor inbox.
- Introduce explicit overflow policy with one of:
  - `drop_oldest`
  - `drop_new`
  - `reject` (surface metric/error)
- Make policy configurable under `RuntimeConfig`.

Breaking change guidance:
- It is acceptable for event routing behavior to become loss-aware under overload.

Acceptance criteria:
- Under synthetic overload, memory remains bounded.
- Overflow events are observable via metrics/logs.
- Existing concurrency unit tests continue passing; add overload test coverage.

### 4.2 Fix Event Model Naming Conflict

Problem:
- `TurnDigestedEvent.summary` collides with `Event.summary()` method semantics.

Recommendation:
- Rename field to a non-conflicting name such as `digest_summary`.
- Keep `summary()` method behavior explicit for event serialization summary fields.

Breaking change guidance:
- Rename the payload field directly; update all call sites and tests.

Acceptance criteria:
- Warning disappears from test runs.
- Event payload contracts remain clear and consistent.

### 4.3 Make Reconciler Subscription Lifecycle Explicit

Problem:
- `start()` subscribes; no explicit stop/unsubscribe symmetry.

Recommendation:
- Track subscription state in `FileReconciler`.
- Add idempotent `start()` and unsubscribe on `stop()` or explicit `close()`.

Acceptance criteria:
- Repeated lifecycle start/stop cycles do not duplicate handlers.
- Add a unit test covering repeated start/stop behavior.

## 5. Priority 1 (Near-Term)

### 5.1 Add API Input/Output Bounds

Problem:
- `/api/chat` only validates non-empty fields.
- `/api/conversation` limits message length but not message count.

Recommendation:
- Introduce explicit max message size for chat input.
- Introduce explicit max history entries for conversation response (configurable).
- Return deterministic validation errors when limits are exceeded.

Breaking change guidance:
- Hard-limit behavior and error payloads can change now.

Acceptance criteria:
- Large payloads are rejected with stable 4xx responses.
- Conversation endpoint payload size is bounded.
- Add endpoint tests for limit behavior.

### 5.2 Cache Query Path Resolution in Reconciler

Problem:
- Query paths are resolved repeatedly in `_do_reconcile_file`.

Recommendation:
- Resolve query paths once during reconciler initialization and reuse.
- Refresh only when config/project root changes (not in normal runtime path).

Acceptance criteria:
- Behavior unchanged for discovery results.
- Reduced overhead in file-heavy reconcile cycles.
- Existing reconciler tests remain green.

### 5.3 Normalize Capability Return Semantics

Problem:
- Multiple methods return `bool` but never return `False`.

Recommendation:
- For command-style operations, return `None` and raise on failure.
- Reserve `bool` only for meaningful true/false outcomes.

Target methods include:
- `write_file`
- `kv_set`
- `kv_delete`
- `event_emit`
- `send_message` (consider explicit result object if limiter can deny)

Acceptance criteria:
- Function signatures reflect real behavior.
- Tool scripts and call sites updated accordingly.
- Capability unit tests updated for revised contracts.

## 6. Priority 2 (Polish)

### 6.1 Tighten Lifecycle Boundaries

Recommendation:
- Ensure service start/stop interfaces are consistently idempotent.
- Keep long-lived subscriptions/tasks visibly owned and explicitly released.

### 6.2 Targeted Naming and Contract Cleanup

Recommendation:
- Improve only where semantics are ambiguous.
- Do not spend cycles on large-scale renaming that does not improve behavior.

### 6.3 Documentation Alignment

Recommendation:
- Update docs to reflect the final APIs and behavior after P0/P1 changes.
- Focus on architecture and operational semantics, not verbosity.

## 7. Logging Policy

Policy decision:
- Keep full prompt/response logging enabled.

Rationale:
- Personal/local project, explicit requirement for complete observability.

Operational recommendations (non-blocking):
- Retain log rotation (`RotatingFileHandler`) and verify retention settings remain practical.
- Optionally add a dedicated logger namespace for prompt/response dumps for easier filtering.
- Preserve current behavior of full content capture.

## 8. Explicit Non-Recommendations

The following intern recommendations are intentionally rejected for now:
- Full event-system rewrite into a new middleware framework.
- Immediate migration to large clean-architecture layering.
- Framework swaps (for example Starlette to FastAPI) without a validated need.
- Security findings unsupported by current code paths (for example claimed path traversal at node lookup).
- Performance claims not grounded in actual query behavior (for example claimed N+1 at current node fetch path).

Reason:
- These changes are high-cost and weakly justified compared to validated defects.

## 9. Validation Plan

### Test Baseline

Before and after each workstream, run at minimum:
- `devenv shell -- pytest tests/unit/test_event_bus.py tests/unit/test_runner.py tests/unit/test_reconciler.py tests/unit/test_web_server.py -q`

Recommended additional coverage:
- Add overload test for bounded actor queue behavior.
- Add lifecycle test for reconciler subscribe/unsubscribe idempotency.
- Add API limit tests for chat payload and conversation history bounds.
- Add capability contract tests for revised return types.

### Acceptance Checks by Priority

P0 checks:
- No warning from `TurnDigestedEvent` field/method conflict.
- Actor queue behavior bounded and observable.
- Reconciler lifecycle does not duplicate subscriptions.

P1 checks:
- API size bounds enforced.
- Query-path caching in place without behavior regression.
- Capability signatures semantically clean.

P2 checks:
- Documentation and lifecycle contracts updated.

## 10. Execution Roadmap

### Week 1

1. Implement bounded actor inbox with overflow policy and metrics.
2. Rename `TurnDigestedEvent.summary` field and update call sites.
3. Add reconciler subscription lifecycle symmetry and tests.

### Week 2

1. Add `/api/chat` input size limits and `/api/conversation` history-entry cap.
2. Cache query path resolution in reconciler.
3. Normalize capability return types and update tool/test contracts.
4. Refresh docs to match new contracts.

## 11. Definition of Done

This recommendation set is complete when:
- All P0 and P1 items are merged.
- Targeted unit tests pass with no warning from event model naming conflict.
- Runtime behavior under overload is bounded and observable.
- API and capability contracts reflect real semantics.
- Full prompt/response logging remains intact and documented as intentional.

