# Context — 49-demo-v2-update

## Current State
- WS1, WS2, WS3, WS4, WS5, and WS6 implementations completed from `DEMO_UPDATE_IMPLEMENTATION_GUIDE.md`.
- Search and LSP operator diagnostics are now explicit/actionable.
- `/api/events` invalid parameter errors now follow structured response shape.
- WS5 regression tests now cover virtual reactive runtime behavior, structured event error fields, and correlation propagation.
- WS6 documentation set now published for virtual agents, event semantics, and offline/search/lsp operator setup.

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

## Files Changed For WS3
- `src/remora/web/static/vendor/graphology.umd.min.js`
- `src/remora/web/static/vendor/sigma.min.js`
- `src/remora/web/static/index.html` (local vendor script paths)
- `pyproject.toml` (wheel static include patterns)
- `tests/unit/test_views.py`
- `tests/unit/test_web_static_assets.py`

## Files Changed For WS4
- `src/remora/web/routes/_errors.py`
- `src/remora/web/routes/search.py`
- `src/remora/web/routes/events.py`
- `src/remora/lsp/__init__.py`
- `src/remora/__main__.py`
- `src/remora/core/services/search.py`
- `tests/unit/test_web_server.py`
- `tests/unit/test_cli.py`

## Files Changed For WS5
- `tests/unit/test_virtual_reactive_flow.py` (new)
- `tests/unit/test_event_error_fields.py` (new)
- `tests/unit/test_metrics.py` (snapshot key assertion aligned with current metrics fields)

## Files Changed For WS6
- `docs/virtual-agents.md` (new)
- `docs/event-semantics.md` (new)
- `docs/HOW_TO_USE_REMORA.md` (offline UI + search/lsp setup + troubleshooting updates)

## Verification Results
- `devenv shell -- pytest tests/integration/test_virtual_reactive_flow.py tests/unit/test_actor.py tests/unit/test_config.py tests/unit/test_grail.py tests/unit/test_companion_tools.py tests/unit/test_bundle_configs.py tests/unit/test_runner.py tests/integration/test_grail_runtime_tools.py -q`
  - Result: `126 passed`
- `devenv shell -- pytest tests/unit/test_events.py tests/unit/test_event_store.py tests/unit/test_web_server.py tests/unit/test_actor.py tests/unit/test_runner.py tests/unit/test_grail.py tests/unit/test_companion_tools.py tests/unit/test_bundle_configs.py tests/unit/test_config.py tests/integration/test_grail_runtime_tools.py tests/integration/test_virtual_reactive_flow.py tests/integration/test_llm_turn.py -q`
  - Result: `204 passed, 5 skipped`
- `devenv shell -- pytest tests/unit/test_events.py tests/unit/test_event_store.py tests/unit/test_web_server.py tests/unit/test_views.py tests/unit/test_web_static_assets.py tests/unit/test_actor.py tests/unit/test_runner.py tests/unit/test_grail.py tests/unit/test_companion_tools.py tests/unit/test_bundle_configs.py tests/unit/test_config.py tests/integration/test_grail_runtime_tools.py tests/integration/test_virtual_reactive_flow.py tests/integration/test_llm_turn.py -q`
  - Result: `213 passed, 5 skipped`
- `devenv shell -- pytest tests/unit/test_cli.py tests/unit/test_events.py tests/unit/test_event_store.py tests/unit/test_web_server.py tests/unit/test_views.py tests/unit/test_web_static_assets.py tests/unit/test_actor.py tests/unit/test_runner.py tests/unit/test_grail.py tests/unit/test_companion_tools.py tests/unit/test_bundle_configs.py tests/unit/test_config.py tests/unit/test_search.py tests/integration/test_grail_runtime_tools.py tests/integration/test_virtual_reactive_flow.py tests/integration/test_llm_turn.py -q`
  - Result: `236 passed, 5 skipped`
- `devenv shell -- ruff check tests/integration/test_virtual_reactive_flow.py tests/unit/test_actor.py tests/unit/test_config.py src/remora/core/agents/trigger.py src/remora/core/model/config.py`
  - Result: all checks passed
- `devenv shell -- ruff check src/remora/core/events/types.py src/remora/core/agents/outbox.py src/remora/core/events/store.py src/remora/web/routes/events.py tests/unit/test_events.py tests/unit/test_event_store.py tests/unit/test_web_server.py tests/unit/test_actor.py`
  - Result: all checks passed
- `devenv shell -- ruff check tests/unit/test_views.py tests/unit/test_web_static_assets.py tests/unit/test_web_server.py tests/unit/test_events.py tests/unit/test_event_store.py tests/unit/test_actor.py src/remora/web/routes/events.py src/remora/core/events/store.py src/remora/core/events/types.py src/remora/core/agents/outbox.py src/remora/core/agents/turn.py`
  - Result: all checks passed
- `devenv shell -- ruff check src/remora/web/routes/_errors.py src/remora/web/routes/search.py src/remora/web/routes/events.py src/remora/lsp/__init__.py src/remora/__main__.py src/remora/core/services/search.py tests/unit/test_web_server.py tests/unit/test_cli.py`
  - Result: all checks passed
- `devenv shell -- uv sync --extra dev`
  - Result: dependencies synced
- `devenv shell -- pytest tests/unit/test_virtual_reactive_flow.py tests/unit/test_event_error_fields.py -vv`
  - Result: `6 passed`
- `devenv shell -- ruff check tests/unit/test_virtual_reactive_flow.py tests/unit/test_event_error_fields.py tests/unit/test_metrics.py`
  - Result: all checks passed
- `devenv shell -- pytest tests/unit -q`
  - Result: `420 passed`
- `rg -n "^### Offline Web UI|^### LSP Setup|^### Search Setup|docs/event-semantics.md|docs/virtual-agents.md|search_not_configured|search_backend_unavailable" docs/HOW_TO_USE_REMORA.md docs/event-semantics.md docs/virtual-agents.md`
  - Result: required WS6 sections and references present
- Manual source alignment check:
  - `src/remora/core/events/types.py`
  - `src/remora/web/routes/events.py`
  - `src/remora/web/routes/search.py`
  - `src/remora/web/sse.py`
  - Result: docs match current envelope fields, event types, and search diagnostics

## What's Next
- All guide workstreams (WS1-WS6) are complete.
