# Remora-v2 Test Suite Inventory

## Scope Snapshot
- Total tests: 286
- Unit tests: 270
- Integration tests: 16
- Skip gates: 5 (all real-LLM integration tests)
- Special markers (`integration`, `acceptance`, `e2e`, `slow`): none declared

## High-Volume Test Modules
- `tests/unit/test_web_server.py`: 37
- `tests/unit/test_actor.py`: 29
- `tests/unit/test_externals.py`: 20
- `tests/unit/test_grail.py`: 16
- `tests/unit/test_workspace.py`: 15
- `tests/unit/test_reconciler.py`: 15
- `tests/unit/test_graph.py`: 15

## Integration Modules
- `tests/integration/test_e2e.py` (4): event-routing and actor interactions, but with mocked kernels/tools in key tests.
- `tests/integration/test_grail_runtime_tools.py` (2): grail tool execution runtime behavior using workspace stubs.
- `tests/integration/test_llm_turn.py` (5): real LLM calls through configured model endpoint (skip-gated by env var).
- `tests/integration/test_performance.py` (4): latency/memory thresholds for discovery/store/subscriptions/reconciler load.
- `tests/integration/test_startup_shutdown.py` (1): `_start(..., no_web=True, lsp=False, run_seconds=2.0)` lifecycle smoke.

## Real-vLLM Coverage Summary
File: `tests/integration/test_llm_turn.py`
- Env gate: `REMORA_TEST_MODEL_URL` (`skipif`)
- Scenarios:
  - tool invocation and completion
  - kv set/get roundtrip plus message
  - runtime bundle mutation and model-failure path
  - virtual agent reacting to `NodeChangedEvent`
  - reactive trigger mode prompt selection

Important realism limitation:
- These tests invoke `Actor._execute_turn(...)` directly rather than routing through full running runtime (`ActorPool.run_forever`, web API, and live trigger dispatch loop).

## Notable Coverage Areas (Strong)
- Event bus/store/subscription behavior
- Graph/node persistence and transitions
- Workspace provisioning/layering + bundle behavior
- Web API semantics and SSE payload behavior (via ASGI transport)
- LSP handler logic (via directly exposed handler functions)
- Actor turn behavior, retries, prompts, observability events

## Notable Coverage Areas (Thin or Missing)
- Full process-level web runtime test against running `remora start` with web enabled
- Full process-level LSP IO test (`start_io`) against a live server process
- End-to-end user chat path with real vLLM through `/api/chat` -> dispatcher -> actor pool -> model -> SSE
- Multi-agent, real-vLLM concurrent routing under live `ActorPool.run_forever`
- Direct tests for `RuntimeServices` lifecycle as a composed unit
