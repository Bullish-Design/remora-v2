# IMPLEMENTATION_GUIDE.md

## Table of Contents

1. Purpose and Scope
2. Quick Orientation to the Codebase
3. Working Rules for This Implementation
4. Delivery Strategy and Commit Plan
5. Step 0 - Environment Setup and Baseline Verification
6. Step 1 - Add Actor Inbox Backpressure and Overflow Policy (P0)
7. Step 2 - Fix `TurnDigestedEvent.summary` Naming Conflict (P0)
8. Step 3 - Make Reconciler Subscription Lifecycle Explicit and Idempotent (P0)
9. Step 4 - Add API Input/Output Bounds for Chat and Conversation (P1)
10. Step 5 - Cache Query Path Resolution in Reconciler (P1)
11. Step 6 - Normalize Capability Return Semantics (P1)
12. Step 7 - Priority 2 Cleanup: Lifecycle Consistency and Documentation Alignment (P2)
13. Step 8 - Final Validation, Regression Sweep, and Definition of Done
14. Appendix A - File-by-File Change Map
15. Appendix B - Test Command Checklist
16. Appendix C - Suggested PR Breakdown

## 1. Purpose and Scope

This guide translates the validated recommendations in:

1. `.scratch/projects/46-remora-v2-code-review/CODE_REVIEW_REVIEW.md`
2. `.scratch/projects/46-remora-v2-code-review/REVISED_RECOMMENDATIONS.md`

into an implementation plan an intern can execute safely.

This is not a broad rewrite plan. This is a focused reliability and contract cleanup plan.

The implementation scope includes all validated items from the revised recommendations:

1. Bounded actor inboxes and explicit overflow behavior.
2. `TurnDigestedEvent.summary` field rename to remove class design conflict.
3. Explicit subscribe/unsubscribe lifecycle for `FileReconciler`.
4. `/api/chat` and `/api/conversation` payload bounds.
5. Query-path resolution caching in `FileReconciler`.
6. Capability return-contract cleanup for methods currently returning always-`True` booleans.
7. Targeted lifecycle and documentation cleanup after behavior changes are complete.

Out of scope for this implementation:

1. Framework migrations.
2. Large architecture rewrites.
3. Unvalidated security/performance claims from the original intern report.
4. Removing full prompt/response logging. Logging remains intentionally enabled.

## 2. Quick Orientation to the Codebase

Before coding, read these files once to understand where each change lands.

1. `src/remora/core/agents/actor.py`
2. `src/remora/core/agents/runner.py`
3. `src/remora/code/reconciler.py`
4. `src/remora/core/events/types.py`
5. `src/remora/web/routes/chat.py`
6. `src/remora/web/routes/nodes.py`
7. `src/remora/core/tools/capabilities.py`
8. `src/remora/core/tools/context.py`
9. `src/remora/core/model/config.py`
10. `src/remora/web/server.py`
11. `src/remora/web/deps.py`

High-level ownership map:

1. Actor flow control is split between `Actor` (queue container) and `ActorPool` (routing behavior).
2. Reconciler lifecycle is owned by `FileReconciler` and wired by `RuntimeServices`.
3. API limits are enforced in web route handlers, with shared values carried in `WebDeps`.
4. Tool/externals contracts are defined in capabilities/context and consumed by bundle `.pym` scripts plus tests.
5. Configurable limits belong in `RuntimeConfig`.

## 3. Working Rules for This Implementation

Follow this process exactly to avoid environment and regression issues.

1. Run dependency sync before the first test command in this session. 

```bash
devenv shell -- uv sync --extra dev
```

2. Use `devenv shell --` for all tests and runtime commands.
3. Keep changes in small, reviewable commits aligned to steps in this guide. Commit after each step. 
4. Update tests in the same commit as the behavior change.
5. Do not start a new step until the previous step's test checklist is green.
6. Use failing-test-first workflow for each behavior change.
7. Keep logging policy unchanged: do not remove existing full prompt/response debug logging.

## 4. Delivery Strategy and Commit Plan

Implement in this order to minimize risk:

1. Step 1 (backpressure) first, because unbounded memory growth is the highest runtime risk.
2. Step 2 (event naming conflict) and Step 3 (reconciler lifecycle) next, because both are correctness/stability fixes.
3. Step 4 to Step 6 after P0 is green.
4. Step 7 documentation/lifecycle polish after all behavior changes are merged.
5. Step 8 final regression and DoD verification at the end.

Recommended commit boundaries:

1. Commit A: Runtime config fields and actor inbox backpressure core logic.
2. Commit B: Backpressure tests and metrics assertions.
3. Commit C: `TurnDigestedEvent` rename and all payload/test consumers.
4. Commit D: Reconciler subscribe/unsubscribe lifecycle and idempotency tests.
5. Commit E: API bounds and endpoint tests.
6. Commit F: Query-path cache and reconciler performance guard tests.
7. Commit G: Capability contract normalization plus bundle/test fixture updates.
8. Commit H: P2 docs/lifecycle alignment and final cleanup.

Testing cadence rules for every commit:

1. Run the step-local tests listed in that section.
2. Run the baseline suite from revised recommendations:

```bash
devenv shell -- pytest tests/unit/test_event_bus.py tests/unit/test_runner.py tests/unit/test_reconciler.py tests/unit/test_web_server.py -q
```

3. If the commit touches externals capabilities, also run:

```bash
devenv shell -- pytest tests/unit/test_externals.py tests/integration/test_grail_runtime_tools.py tests/integration/test_e2e.py tests/integration/test_llm_turn.py -q
```

## 5. Step 0 - Environment Setup and Baseline Verification

Goal: establish a known-good baseline before refactoring.

Implementation tasks:

1. Create a feature branch.
2. Sync dependencies.
3. Run the current baseline tests and record results.
4. Confirm the currently known warning exists before you fix it in Step 2.

Commands:

```bash
git checkout -b feature/revised-recommendations-implementation

devenv shell -- uv sync --extra dev

devenv shell -- pytest tests/unit/test_event_bus.py tests/unit/test_runner.py tests/unit/test_reconciler.py tests/unit/test_web_server.py -q

devenv shell -- pytest tests/unit/test_events.py -q
```

What to record in your notes before coding:

1. Baseline pass count for the targeted suite.
2. Whether `tests/unit/test_events.py` shows the `TurnDigestedEvent.summary` shadow warning.
3. Current behavior of overloaded routing is unbounded queue growth (document this expected pre-change behavior).

Testing required for Step 0:

1. The baseline command suite must run successfully.
2. You must save the baseline output in your notes so regressions are measurable later.

## 6. Step 1 - Add Actor Inbox Backpressure and Overflow Policy (P0)

Goal: bound memory under load and make overflow behavior explicit and observable.

### 6.1 Files to change

1. `src/remora/core/model/config.py`
2. `src/remora/core/agents/actor.py`
3. `src/remora/core/agents/runner.py`
4. `src/remora/core/services/metrics.py`
5. `tests/unit/test_runner.py`
6. `tests/unit/test_config.py`
7. `tests/unit/test_web_server.py` (only if health metric snapshot assertions need updates)

### 6.2 Implementation tasks

1. Add runtime config for queue bounds and policy.
2. Ensure actor inbox queue is bounded with `maxsize` from config.
3. Route events through a policy-aware enqueue path in `ActorPool`.
4. Emit observability signals for overflow events.
5. Keep `pending_inbox_items` gauge behavior correct after policy handling.

Detailed implementation instructions:

1. In `RuntimeConfig`, add `actor_inbox_max_items: int` with a safe default like `1000`.
2. In `RuntimeConfig`, add `actor_inbox_overflow_policy: str` with allowed values `drop_oldest`, `drop_new`, and `reject`.
3. Add validation in config so invalid policy values fail fast.
4. In `Actor.__init__`, replace `asyncio.Queue()` with `asyncio.Queue(maxsize=config.runtime.actor_inbox_max_items)`.
5. In `ActorPool`, replace direct `actor.inbox.put_nowait(event)` with a helper that handles `QueueFull` according to policy.
6. Implement policy behavior:
7. For `drop_oldest`, remove one oldest item with `get_nowait()` and enqueue the new event.
8. For `drop_new`, keep existing queue contents and discard the incoming event.
9. For `reject`, do not enqueue and treat as explicit rejected route.
10. Add metrics counters in `Metrics` such as `actor_inbox_overflow_total`, `actor_inbox_dropped_oldest_total`, `actor_inbox_dropped_new_total`, and `actor_inbox_rejected_total`.
11. Increment counters in `ActorPool` helper when overflow happens.
12. Add warning-level log entries for each overflow event with `agent_id`, policy, and queue size.
13. Keep behavior no-op when `_accepting_events` is false, same as current design.

Implementation notes for intern:

1. `Actor._run` should remain unchanged for this step.
2. Do not add blocking `await inbox.put(...)` in routing path.
3. Keep queue operations non-blocking and policy-driven in router path.
4. If `drop_oldest` sees an empty queue unexpectedly, handle defensively and log once.

### 6.3 Tests to add or update

Add tests in `tests/unit/test_runner.py`:

1. `drop_new` policy keeps queue length capped and drops newest event.
2. `drop_oldest` policy keeps queue length capped and evicts earliest event.
3. `reject` policy keeps queue length capped and increments reject metrics.
4. A synthetic overload test that routes many events and asserts queue never exceeds `actor_inbox_max_items`.
5. Metrics assertions for overflow counters.

Update or add tests in `tests/unit/test_config.py`:

1. Default values for `actor_inbox_max_items` and `actor_inbox_overflow_policy`.
2. Invalid policy string raises validation error.
3. Optional sanity validation for minimum queue size greater than zero.

### 6.4 Step 1 test execution checklist

Run these commands after implementing Step 1:

```bash
devenv shell -- pytest tests/unit/test_config.py tests/unit/test_runner.py -q

devenv shell -- pytest tests/unit/test_event_bus.py tests/unit/test_runner.py tests/unit/test_reconciler.py tests/unit/test_web_server.py -q
```

Step 1 acceptance criteria:

1. Queue size never exceeds configured max in tests.
2. Overflow policy behavior is deterministic and tested.
3. Overflow metrics are updated and visible in `Metrics.snapshot()`.
4. No regressions in baseline test suite.

## 7. Step 2 - Fix `TurnDigestedEvent.summary` Naming Conflict (P0)

Goal: remove the model warning and make event field semantics explicit.

### 7.1 Files to change

1. `src/remora/core/events/types.py`
2. `tests/unit/test_events.py`
3. `src/remora/web/static/index.html` (timeline summary fallback)
4. `src/remora/defaults/bundles/companion/bundle.yaml` (prompt wording)
5. Any other `TurnDigestedEvent(..., summary=...)` call sites discovered by search

### 7.2 Implementation tasks

1. Rename `TurnDigestedEvent.summary` field to `digest_summary`.
2. Add explicit `summary()` method override on `TurnDigestedEvent` that returns `digest_summary`.
3. Update all tests and payload expectations to use `digest_summary` key.
4. Update UI/event-consumer fallback code to read `digest_summary` where appropriate.

Detailed implementation instructions:

1. In `src/remora/core/events/types.py`, change the field declaration from `summary: str = ""` to `digest_summary: str = ""`.
2. In the same class, add:

```python
def summary(self) -> str:
    return self.digest_summary
```

3. In `tests/unit/test_events.py`, update all `TurnDigestedEvent` constructor arguments and assertions.
4. In `tests/unit/test_events.py`, update envelope payload assertions from `payload["summary"]` to `payload["digest_summary"]`.
5. In `src/remora/web/static/index.html`, adjust timeline fallback to include `payload.digest_summary` before generic fallbacks.
6. In `src/remora/defaults/bundles/companion/bundle.yaml`, update reactive prompt wording from `summary` to `digest_summary` so prompt language matches runtime payload.

Implementation notes for intern:

1. Keep event type name `turn_digested` unchanged.
2. Do not rename `Event.summary()` base method.
3. Verify no stale references remain with:

```bash
rg -n "TurnDigestedEvent\(|digest_summary|payload\[\"summary\"\]|\.summary\b" src tests
```

### 7.3 Tests to add or update

1. Update `test_turn_digested_event_defaults` to assert `event.digest_summary == ""`.
2. Update `test_turn_digested_event_full` to pass/verify `digest_summary`.
3. Update `test_turn_digested_event_envelope` to assert payload key is `digest_summary`.
4. Add or update one assertion verifying `event.summary()` returns the `digest_summary` value.

### 7.4 Step 2 test execution checklist

```bash
devenv shell -- pytest tests/unit/test_events.py -q -W error

devenv shell -- pytest tests/unit/test_event_bus.py tests/unit/test_runner.py tests/unit/test_reconciler.py tests/unit/test_web_server.py -q
```

Step 2 acceptance criteria:

1. The naming-conflict warning disappears under `-W error` execution.
2. `TurnDigestedEvent` payload keys are consistent and explicit.
3. No regressions in baseline suite.

## 8. Step 3 - Make Reconciler Subscription Lifecycle Explicit and Idempotent (P0)

Goal: prevent duplicate event-bus handlers across start/stop cycles.

### 8.1 Files to change

1. `src/remora/code/reconciler.py`
2. `src/remora/core/services/container.py` (only if wiring changes needed)
3. `tests/unit/test_reconciler.py`
4. `tests/unit/test_services.py` (if constructor/start contract changes)

### 8.2 Implementation tasks

1. Add explicit subscription state tracking inside `FileReconciler`.
2. Make `start()` idempotent.
3. Unsubscribe in `stop()` (or add explicit `close()` and call it from `stop()`).
4. Preserve current watcher stop behavior.

Detailed implementation instructions:

1. In `FileReconciler.__init__`, add private fields such as `_event_bus: EventBus | None` and `_content_subscription_active: bool`.
2. In `start(event_bus)`, return early if already subscribed.
3. In `start(event_bus)`, save the bus reference and subscribe exactly once.
4. In `stop()`, call watcher stop as today, then unsubscribe handler if currently subscribed.
5. After unsubscribe, clear subscription state so future `start()` can subscribe again.
6. Keep method signatures compatible with existing runtime wiring where possible.

Implementation notes for intern:

1. `EventBus.unsubscribe(handler)` removes all registrations for that handler, which is useful for safety.
2. Keep `_on_content_changed` behavior unchanged except lifecycle ownership.
3. Avoid introducing async requirements into `stop()` unless absolutely necessary.

### 8.3 Tests to add or update

Add tests in `tests/unit/test_reconciler.py`:

1. Calling `start(event_bus)` twice does not duplicate handling.
2. Calling `stop()` after `start()` unsubscribes the content-change handler.
3. Calling `start()` after `stop()` re-subscribes exactly once.
4. Emitting one `ContentChangedEvent` after a double-start still causes one reconcile call.
5. Emitting `ContentChangedEvent` after stop causes zero reconcile calls.

Suggested strategy for these tests:

1. Monkeypatch `reconciler._reconcile_file` to increment a counter.
2. Emit `ContentChangedEvent` through a real `EventBus`.
3. Assert exact call count for each lifecycle scenario.

### 8.4 Step 3 test execution checklist

```bash
devenv shell -- pytest tests/unit/test_reconciler.py tests/unit/test_services.py -q

devenv shell -- pytest tests/unit/test_event_bus.py tests/unit/test_runner.py tests/unit/test_reconciler.py tests/unit/test_web_server.py -q
```

Step 3 acceptance criteria:

1. No duplicate handler execution after repeated starts.
2. No handler execution after stop.
3. Lifecycle remains compatible with `RuntimeServices.initialize()` and `RuntimeServices.close()`.
4. Baseline suite remains green.

## 9. Step 4 - Add API Input/Output Bounds for Chat and Conversation (P1)

Goal: enforce deterministic API size limits and keep payload sizes bounded.

### 9.1 Files to change

1. `src/remora/core/model/config.py`
2. `src/remora/web/deps.py`
3. `src/remora/web/server.py`
4. `src/remora/web/routes/chat.py`
5. `src/remora/web/routes/nodes.py`
6. `tests/unit/test_web_server.py`
7. `tests/unit/test_config.py`

### 9.2 Implementation tasks

1. Add runtime config limits for chat and conversation payloads.
2. Pass those limits into web dependencies.
3. Enforce `chat` input max length with stable 4xx response.
4. Enforce conversation history entry cap and configurable content truncation.

Detailed implementation instructions:

1. In `RuntimeConfig`, add fields:
2. `chat_message_max_chars: int` with default like `4000`.
3. `conversation_history_max_entries: int` with default like `200`.
4. `conversation_message_max_chars: int` with default `2000` (replaces hard-coded constant in route).
5. Add validation to guarantee all three values are positive.
6. In `WebDeps`, add matching fields for these limits.
7. In `create_app(...)`, provide these values when constructing `WebDeps`.
8. Use runtime config from lifecycle wiring so production values come from `remora.yaml`.
9. In `/api/chat`, after empty checks, reject oversized message with deterministic JSON error and status `413`.
10. In `/api/conversation`, cap history list length to the last `conversation_history_max_entries` entries.
11. In `/api/conversation`, cap each message content length to `conversation_message_max_chars`.
12. Optionally include response metadata fields such as `truncated: true/false` and `history_limit` to make clipping observable.

Suggested `/api/chat` error payload shape:

```json
{
  "error": "message exceeds max length",
  "max_chars": 4000,
  "received_chars": 5600
}
```

Implementation notes for intern:

1. Keep existing non-empty validation and `404 node not found` behavior.
2. Keep rate limiting behavior unchanged.
3. Preserve response shape for successful chat calls.

### 9.3 Tests to add or update

Add/update in `tests/unit/test_web_server.py`:

1. Chat request at exact max length succeeds.
2. Chat request above max length returns `413` with stable payload keys.
3. Conversation endpoint returns at most configured history entries.
4. Conversation endpoint returns the most recent entries when truncated.
5. Conversation message content is truncated to configured max chars.

Add/update in `tests/unit/test_config.py`:

1. Defaults for new runtime fields are loaded.
2. Invalid non-positive limits raise validation errors.

### 9.4 Step 4 test execution checklist

```bash
devenv shell -- pytest tests/unit/test_web_server.py tests/unit/test_config.py -q

devenv shell -- pytest tests/unit/test_event_bus.py tests/unit/test_runner.py tests/unit/test_reconciler.py tests/unit/test_web_server.py -q
```

Step 4 acceptance criteria:

1. Oversized chat input is deterministically rejected.
2. Conversation payload size is bounded by entry count and content length.
3. No regression in web endpoint behavior outside new limits.

## 10. Step 5 - Cache Query Path Resolution in Reconciler (P1)

Goal: remove repeated query-path resolution from per-file hot path.

### 10.1 Files to change

1. `src/remora/code/reconciler.py`
2. `tests/unit/test_reconciler.py`

### 10.2 Implementation tasks

1. Resolve query paths once during `FileReconciler` initialization.
2. Reuse cached paths in `_do_reconcile_file`.
3. Keep behavior identical for discovery output.

Detailed implementation instructions:

1. In `FileReconciler.__init__`, create `self._query_paths = resolve_query_paths(self._config, self._project_root)`.
2. In `_do_reconcile_file`, replace inline `resolve_query_paths(...)` call with `self._query_paths`.
3. Add a helper `refresh_query_paths()` only if you want explicit future support for config/project-root mutation.
4. Do not change discovery behavior or language-map logic.

Implementation notes for intern:

1. This is a performance cleanliness change, not a behavior change.
2. Discovery output should remain byte-for-byte equivalent for same input files.

### 10.3 Tests to add or update

In `tests/unit/test_reconciler.py`, add one focused test:

1. Monkeypatch `remora.code.reconciler.resolve_query_paths` with a counting wrapper.
2. Instantiate `FileReconciler` and run multiple reconcile operations.
3. Assert path resolution happens once at initialization, not once per file.

Also run existing reconciler tests to ensure no behavior regression.

### 10.4 Step 5 test execution checklist

```bash
devenv shell -- pytest tests/unit/test_reconciler.py -q

devenv shell -- pytest tests/unit/test_event_bus.py tests/unit/test_runner.py tests/unit/test_reconciler.py tests/unit/test_web_server.py -q
```

Step 5 acceptance criteria:

1. Query path resolution is not repeated per file reconcile.
2. Existing reconciler behavior tests remain green.

## 11. Step 6 - Normalize Capability Return Semantics (P1)

Goal: remove misleading always-`True` return contracts and make tool semantics honest.

### 11.1 Files to change

1. `src/remora/core/tools/capabilities.py`
2. `src/remora/core/tools/context.py`
3. `src/remora/defaults/defaults.yaml`
4. `src/remora/defaults/bundles/*/bundle.yaml` files with `externals_version`
5. Bundle tool scripts in `src/remora/defaults/bundles/**/tools/*.pym`
6. `tests/unit/test_externals.py`
7. `tests/integration/test_grail_runtime_tools.py`
8. `tests/integration/test_llm_turn.py`
9. `tests/integration/test_e2e.py`
10. `tests/acceptance/test_live_runtime_real_llm.py`
11. `tests/fixtures/grail_runtime_tools/*.pym`
12. `docs/externals-api.md`
13. `docs/externals-contract.md`

### 11.2 Contract decisions for this step

Apply these exact return-contract changes:

1. `write_file(...) -> None`.
2. `kv_set(...) -> None`.
3. `kv_delete(...) -> None`.
4. `event_emit(...) -> None`.
5. Keep `graph_set_status(...) -> bool` because it is a meaningful true/false transition result.
6. Replace `send_message(...) -> bool` with explicit result object to capture denied sends:
7. Example shape: `{"sent": bool, "reason": "sent" | "rate_limited"}`.

### 11.3 Implementation tasks

1. Update capability method signatures and returns in `capabilities.py`.
2. Keep behavior unchanged except return contracts.
3. Update `send_message` limiter path to return explicit result object instead of bare `False`.
4. Update all bundle `.pym` scripts that assume bool values.
5. Update test fixtures and integration test inline scripts that assume bool return values.
6. Bump externals contract version from `1` to `2`.
7. Update docs to match new signatures and behavior.

Detailed implementation instructions:

1. In `FileCapabilities.write_file`, remove `return True` and return `None`.
2. In `KVCapabilities.kv_set` and `kv_delete`, remove `return True` and return `None`.
3. In `EventCapabilities.event_emit`, remove `return True` and return `None`.
4. In `CommunicationCapabilities.send_message`, return object with fields `sent` and `reason`.
5. For rate-limited sends, return `{"sent": false, "reason": "rate_limited"}` without emitting event.
6. For successful sends, return `{"sent": true, "reason": "sent"}` after emit.
7. In bundle scripts, replace patterns like `ok = await kv_set(...)` with plain `await kv_set(...)` and unconditional success messages.
8. In scripts that branch on send status, branch on `result.get("sent")` from the new object.
9. Update `EXTERNALS_VERSION` in `src/remora/core/tools/context.py` to `2`.
10. Update `externals_version` declarations in default bundle YAML files to `2`.
11. Update defaults-layer `externals_version` in `src/remora/defaults/defaults.yaml` to `2`.
12. Update docs for new signatures and versioned contract.

Implementation notes for intern:

1. Use `rg` aggressively to find stale bool signatures and bool-branch usage.
2. Suggested searches:

```bash
rg -n "-> bool: \.\.\." src/remora/defaults tests docs
rg -n "await (write_file|kv_set|kv_delete|event_emit|send_message)\(" src/remora/defaults tests
```

3. Expect many test fixture string literals to need updates.
4. Treat this as a controlled breaking change with full test updates in the same PR.

### 11.4 Tests to add or update

Update `tests/unit/test_externals.py`:

1. Remove assertions expecting truthy returns for `write_file`, `kv_set`, `kv_delete`, `event_emit`.
2. Add assertions that operations complete and effects are persisted.
3. Update send-message tests to assert explicit result object fields.
4. Keep rate-limit tests but assert result object indicates denied reason.

Update integration and acceptance tests:

1. Update inline `.pym` tool source snippets to new signatures and branch logic.
2. Update fixture tool `send_prefixed_message.pym` to consume result object.
3. Ensure Grail runtime tests still validate output strings from updated scripts.

Update docs tests or docs references if present.

### 11.5 Step 6 test execution checklist

```bash
devenv shell -- pytest tests/unit/test_externals.py tests/integration/test_grail_runtime_tools.py tests/integration/test_e2e.py tests/integration/test_llm_turn.py -q

devenv shell -- pytest tests/unit/test_event_bus.py tests/unit/test_runner.py tests/unit/test_reconciler.py tests/unit/test_web_server.py -q
```

If acceptance tests are enabled in your environment, also run:

```bash
devenv shell -- pytest tests/acceptance/test_live_runtime_real_llm.py -q
```

Step 6 acceptance criteria:

1. Always-true bool contracts are removed from target capability methods.
2. `send_message` denial is explicit and test-covered.
3. Externals contract version is updated and aligned in defaults/bundles/docs.
4. Unit and integration suites pass with updated script fixtures.

## 12. Step 7 - Priority 2 Cleanup: Lifecycle Consistency and Documentation Alignment (P2)

Goal: finalize consistency and documentation after all behavior changes are stable.

### 12.1 Files to review/update

1. `src/remora/core/agents/runner.py`
2. `src/remora/code/reconciler.py`
3. `src/remora/core/services/container.py`
4. `docs/architecture.md`
5. `docs/externals-api.md`
6. `docs/externals-contract.md`
7. `docs/user-guide.md` (only where limits/contracts are user-visible)

### 12.2 Implementation tasks

1. Verify lifecycle methods are idempotent where expected.
2. Ensure ownership of long-lived subscriptions is explicit in code comments/docstrings.
3. Align docs with actual behavior after Steps 1 to 6.

Detailed implementation instructions:

1. Confirm `ActorPool.stop()` and `ActorPool.stop_and_wait()` can be called repeatedly without side effects.
2. Confirm `FileReconciler.stop()` is safe to call when already stopped.
3. Update architecture docs where actor backpressure and reconciler lifecycle semantics changed.
4. Update externals docs so signatures and examples match new return semantics and externals version.
5. Keep documentation concise and behavior-focused.

### 12.3 Tests to add or update

1. Add one idempotency test for repeated stop calls if not already covered.
2. Keep doc-only changes separate when possible, but still run smoke tests after merge.

### 12.4 Step 7 test execution checklist

```bash
devenv shell -- pytest tests/unit/test_runner.py tests/unit/test_reconciler.py tests/unit/test_services.py -q
```

Optional integration confidence pass:

```bash
devenv shell -- pytest tests/integration/test_lifecycle.py -q
```

Step 7 acceptance criteria:

1. Lifecycle APIs are clearly idempotent and tested.
2. Documentation matches runtime behavior and contracts.

## 13. Step 8 - Final Validation, Regression Sweep, and Definition of Done

Goal: verify all revised recommendations are implemented correctly with no regressions.

### 13.1 Full regression command set

Run in this order:

```bash
devenv shell -- uv sync --extra dev

devenv shell -- pytest tests/unit/test_event_bus.py tests/unit/test_runner.py tests/unit/test_reconciler.py tests/unit/test_web_server.py -q

devenv shell -- pytest tests/unit/test_events.py tests/unit/test_externals.py tests/unit/test_config.py tests/unit/test_services.py -q

devenv shell -- pytest tests/integration/test_grail_runtime_tools.py tests/integration/test_e2e.py tests/integration/test_llm_turn.py -q
```

If your environment supports it, run acceptance coverage:

```bash
devenv shell -- pytest tests/acceptance/test_live_runtime_real_llm.py -q
```

### 13.2 Manual verification checklist

1. Start runtime and verify `/api/health` returns metrics including new overflow counters.
2. Send a deliberately oversized `/api/chat` payload and verify deterministic `413` response.
3. Generate a long actor history and verify `/api/conversation` entry count cap.
4. Trigger overload scenario and verify queue size stays bounded and overflow is observable.

### 13.3 Definition of done

You are done only when all are true:

1. All P0 and P1 changes are implemented and tested.
2. `TurnDigestedEvent` warning is eliminated.
3. Actor inbox behavior is bounded and policy-driven.
4. Reconciler subscription lifecycle is explicit and idempotent.
5. API bounds are enforced and covered by tests.
6. Query path caching is in place without discovery regressions.
7. Capability return contracts are semantically accurate and docs are updated.
8. Full prompt/response logging remains intact.

## 14. Appendix A - File-by-File Change Map

Use this map while implementing to avoid missing required updates.

| Area | Primary Files | Secondary Files |
|---|---|---|
| Actor backpressure | `src/remora/core/agents/actor.py`, `src/remora/core/agents/runner.py` | `src/remora/core/model/config.py`, `src/remora/core/services/metrics.py`, `tests/unit/test_runner.py`, `tests/unit/test_config.py` |
| Event naming conflict | `src/remora/core/events/types.py`, `tests/unit/test_events.py` | `src/remora/web/static/index.html`, `src/remora/defaults/bundles/companion/bundle.yaml` |
| Reconciler lifecycle | `src/remora/code/reconciler.py`, `tests/unit/test_reconciler.py` | `tests/unit/test_services.py`, `src/remora/core/services/container.py` |
| API bounds | `src/remora/web/routes/chat.py`, `src/remora/web/routes/nodes.py` | `src/remora/web/deps.py`, `src/remora/web/server.py`, `src/remora/core/model/config.py`, `tests/unit/test_web_server.py`, `tests/unit/test_config.py` |
| Query path caching | `src/remora/code/reconciler.py` | `tests/unit/test_reconciler.py` |
| Capability contracts | `src/remora/core/tools/capabilities.py`, `src/remora/core/tools/context.py` | bundle `.pym` scripts, defaults/bundle YAML externals versions, integration/acceptance tests, docs externals references |
| Documentation alignment | `docs/architecture.md`, `docs/externals-api.md`, `docs/externals-contract.md` | `docs/user-guide.md` |

## 15. Appendix B - Test Command Checklist

Run these exact commands as you complete each stage.

Step 1:

```bash
devenv shell -- pytest tests/unit/test_config.py tests/unit/test_runner.py -q
```

Step 2:

```bash
devenv shell -- pytest tests/unit/test_events.py -q -W error
```

Step 3:

```bash
devenv shell -- pytest tests/unit/test_reconciler.py tests/unit/test_services.py -q
```

Step 4:

```bash
devenv shell -- pytest tests/unit/test_web_server.py tests/unit/test_config.py -q
```

Step 5:

```bash
devenv shell -- pytest tests/unit/test_reconciler.py -q
```

Step 6:

```bash
devenv shell -- pytest tests/unit/test_externals.py tests/integration/test_grail_runtime_tools.py tests/integration/test_e2e.py tests/integration/test_llm_turn.py -q
```

Baseline smoke after every step:

```bash
devenv shell -- pytest tests/unit/test_event_bus.py tests/unit/test_runner.py tests/unit/test_reconciler.py tests/unit/test_web_server.py -q
```

## 16. Appendix C - Suggested PR Breakdown

If you are opening multiple PRs, use this sequence:

1. PR 1: Step 1 only.
2. PR 2: Steps 2 and 3.
3. PR 3: Steps 4 and 5.
4. PR 4: Step 6 only.
5. PR 5: Step 7 docs/lifecycle polish and Step 8 final validation evidence.

For each PR description include:

1. Which step(s) from this guide are included.
2. Exact test commands run and pass status.
3. Any intentionally deferred items.
