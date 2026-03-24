# Context — 49-demo-v2-update

## Current State
- WS1 and WS2 implementations completed from `DEMO_UPDATE_IMPLEMENTATION_GUIDE.md`.
- Real-world WS1 runtime tests and WS2 observability/filter tests added and passing.
- Runtime loop guard bounds reactive turns per `correlation_id` per agent.

## Files Changed For WS1
- `src/remora/defaults/bundles/review-agent/tools/review_diff.pym`
- `src/remora/defaults/bundles/review-agent/tools/list_recent_changes.pym`
- `src/remora/defaults/bundles/review-agent/tools/submit_review.pym`
- `src/remora/defaults/bundles/review-agent/bundle.yaml`
- `src/remora/defaults/bundles/companion/tools/aggregate_digest.pym`
- `src/remora/defaults/bundles/companion/bundle.yaml`
- `src/remora/core/agents/trigger.py`
- `src/remora/core/model/config.py`
- `tests/integration/test_virtual_reactive_flow.py`
- `tests/unit/test_actor.py`
- `tests/unit/test_config.py`

## Files Changed For WS2
- `src/remora/core/events/types.py` (structured error fields)
- `src/remora/core/agents/outbox.py` (tool error extraction + turn error summary)
- `src/remora/core/agents/turn.py` (structured `AgentErrorEvent` fields)
- `src/remora/core/events/store.py` (`get_events` filters)
- `src/remora/web/routes/events.py` (stable envelope + query filters)
- `tests/unit/test_events.py`
- `tests/unit/test_event_store.py`
- `tests/unit/test_web_server.py`
- `tests/unit/test_actor.py`

## Verification Results
- `devenv shell -- pytest tests/integration/test_virtual_reactive_flow.py tests/unit/test_actor.py tests/unit/test_config.py tests/unit/test_grail.py tests/unit/test_companion_tools.py tests/unit/test_bundle_configs.py tests/unit/test_runner.py tests/integration/test_grail_runtime_tools.py -q`
  - Result: `126 passed`
- `devenv shell -- pytest tests/unit/test_events.py tests/unit/test_event_store.py tests/unit/test_web_server.py tests/unit/test_actor.py tests/unit/test_runner.py tests/unit/test_grail.py tests/unit/test_companion_tools.py tests/unit/test_bundle_configs.py tests/unit/test_config.py tests/integration/test_grail_runtime_tools.py tests/integration/test_virtual_reactive_flow.py tests/integration/test_llm_turn.py -q`
  - Result: `204 passed, 5 skipped`
- `devenv shell -- ruff check tests/integration/test_virtual_reactive_flow.py tests/unit/test_actor.py tests/unit/test_config.py src/remora/core/agents/trigger.py src/remora/core/model/config.py`
  - Result: all checks passed
- `devenv shell -- ruff check src/remora/core/events/types.py src/remora/core/agents/outbox.py src/remora/core/events/store.py src/remora/web/routes/events.py tests/unit/test_events.py tests/unit/test_event_store.py tests/unit/test_web_server.py tests/unit/test_actor.py`
  - Result: all checks passed

## What's Next
- WS1 + WS2 are done. Next implementation targets are WS3 (offline-safe web UI defaults) and WS4 (search/LSP operator UX).
