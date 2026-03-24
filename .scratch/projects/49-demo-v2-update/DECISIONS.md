# Decisions — 49-demo-v2-update

_Record key decisions with rationale here as work proceeds._

## Implemented Decisions

1. **Loop guard implemented in `TriggerPolicy` (per-agent) instead of `ActorPool` router**
   - Rationale: `TriggerPolicy` already owns trigger admission decisions and per-agent state. Adding `max_reactive_turns_per_correlation` there gives direct enforcement of "per correlation_id per agent" bounds with minimal coupling.
   - Result: New runtime config field `max_reactive_turns_per_correlation` (default `3`) and policy counter map with TTL cleanup.

2. **Real-world WS1 verification uses Grail runtime execution tests**
   - Rationale: WS1 failures are runtime/script-contract issues, so tests execute actual `.pym` bundle tools through `discover_tools` + `GrailTool.execute` with realistic malformed externals/KV payloads.
   - Result: Added `tests/integration/test_virtual_reactive_flow.py` with missing-node, malformed KV, unexpected external-shape, and oversized-output scenarios.

3. **Companion max turns reduced from 3 to 2**
   - Rationale: Companion is observer/summarizer and should be single-shot or near single-shot in reactive mode; lower turn count reduces loop/amplification risk.

4. **Keep `EventStore.get_events` row shape for internal consumers; normalize envelope shape in `/api/events` route**
   - Rationale: SSE replay and internal callers depend on DB row metadata (including `id`), while downstream scripts/API clients need a stable envelope.
   - Result: Added `event_type`/`correlation_id` filtering in `EventStore.get_events`, and route-level normalization to `{event_type,timestamp,correlation_id,tags,payload}`.

5. **Derive tool error class/reason in `OutboxObserver` and aggregate per-turn error summary**
   - Rationale: structured-agents tool result events do not always provide explicit error class/reason fields.
   - Result: `RemoraToolResultEvent` now gets `error_class`/`error_reason`; `TurnCompleteEvent.error_summary` is synthesized from observed tool error classes when errors occur.

6. **Vendor graph JS dependencies in `src/remora/web/static/vendor/` and reference them via `/static/vendor/*`**
   - Rationale: offline/network-restricted environments were failing when `index.html` depended on unpkg CDN.
   - Result: vendored `graphology.umd.min.js` and `sigma.min.js`, updated `index.html` script tags, and removed CDN reliance.

7. **Explicit wheel include patterns for static JS/HTML via Hatch**
   - Rationale: enforce deterministic package distribution of UI static assets for downstream installs.
   - Result: `[tool.hatch.build.targets.wheel].include` now includes `src/remora/web/static/**/*.js` and `src/remora/web/static/**/*.html`.

8. **Introduce shared web `error_response` helper for standardized API errors**
   - Rationale: WS4 requires consistent `{error, message, docs?}` payload shape, especially for operator-facing diagnostics.
   - Result: Search and events routes now emit structured error codes/messages; events invalid limit uses `invalid_limit` code.

9. **Differentiate search API failure modes at route boundary**
   - Rationale: operators need clear remediation paths for missing feature setup vs backend outage.
   - Result:
     - `501 search_not_configured` when `search_service is None` with `uv sync --extra search`.
     - `503 search_backend_unavailable` when configured service is present but unavailable.

10. **Keep CLI import-safe and make LSP dependency failures actionable**
   - Rationale: avoid opaque CLI behavior and align install guidance with repo tooling (`devenv` + `uv sync`).
   - Result:
     - `remora lsp` now lazily imports and catches `ImportError`.
     - LSP messages now reference `uv sync --extra lsp` and docs anchor.

11. **Add WS5 regression coverage as focused unit tests using real runtime entry points**
   - Rationale: WS5 requires durable guarantees around virtual-reactive flows and event payload contracts, and these are best validated with isolated unit tests that still execute real tool/runtime code paths.
   - Result:
     - Added `tests/unit/test_virtual_reactive_flow.py` for missing-node handling, malformed companion KV recovery, and loop-guard cap checks.
     - Added `tests/unit/test_event_error_fields.py` for structured error fields and correlation-id propagation through actor execution.

12. **Align `test_metrics_snapshot` to the expanded metrics contract**
   - Rationale: `Metrics.snapshot()` now includes actor inbox backpressure counters; tests must assert the current public snapshot shape to prevent false negatives.
   - Result: `tests/unit/test_metrics.py` now includes the four actor inbox counter keys and validates default zero values.

## Pending Decisions

1. **WS6 documentation scope split**: Keep WS6 in one commit or split into architecture docs + operator docs commits?
   - Leaning: split by document group to keep review and rollback simple.
