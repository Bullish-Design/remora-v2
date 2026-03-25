# Baseline Notes

## Environment

- Dependency sync completed: `devenv shell -- uv sync --extra dev`
- vLLM reachability confirmed via:
  - `curl -s http://remora-server:8000/v1/models | python -m json.tool`
  - Model present: `Qwen/Qwen3-4B-Instruct-2507-FP8`

## Reusable Real-LLM Test Helpers

- Canonical runtime helper: `tests/integration/test_llm_turn.py::_setup_llm_runtime`
  - Returns: `(actor, node, event_store, workspace_service, db, source_path)`
  - Handles DB/EventStore/NodeStore/workspace/reconciler setup + full scan
- Existing real-LLM patterns:
  - marker: `pytestmark = pytest.mark.real_llm`
  - trigger execution: `actor._execute_turn(trigger, outbox)`
  - event assertions use `event_store.get_events(...)` and payload checks
- Acceptance patterns live in:
  - `tests/acceptance/test_live_runtime_real_llm.py`
  - Includes lifecycle startup/wait-for-health/event stream assertions

## Implementation Direction

- New tests should copy production bundle directories from `src/remora/defaults/bundles`.
- Bundle overrides should be minimal and only for deterministic prompting/model value.
- Keep test coverage organized by guide tasks:
  - Integration files for companion/review-agent/test-agent/directory-agent/system tools
  - `test_llm_turn.py` additions for code-agent tools
  - Acceptance file additions for end-to-end reactive flows
