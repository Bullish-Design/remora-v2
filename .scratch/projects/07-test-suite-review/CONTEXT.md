# Context

## Status
`TEST_REVIEW_REVIEW.md` recommendations are implemented for the pytest suite. Verified against a live vLLM endpoint.

## What Was Implemented

1. Added real LLM integration test:
   - `tests/integration/test_llm_turn.py`
   - Executes a real agent turn with:
     - real `FileReconciler` discovery/materialization
     - real `discover_tools` and Grail tool execution
     - real kernel call against `REMORA_TEST_MODEL_URL`
   - Asserts:
     - `AgentStartEvent` and `AgentCompleteEvent` emitted
     - no `AgentErrorEvent`
     - at least one `AgentMessageEvent` from `send_message` tool

2. Added actor error-path test:
   - `test_actor_execute_turn_emits_error_event_on_kernel_failure`
   - Forces `create_kernel` to raise `ConnectionError`.
   - Verifies `AgentErrorEvent` emission and final `ERROR` status in both `NodeStore` and `AgentStore`.

3. Added semaphore saturation test:
   - `test_actor_execute_turn_respects_shared_semaphore`
   - Two actors share `Semaphore(1)` with blocking kernel.
   - Verifies second turn blocks until first releases; max in-flight kernel runs stays at 1.

4. Added full two-agent E2E interaction test:
   - `tests/integration/test_e2e.py::test_e2e_two_agents_interact_via_send_message_tool`
   - Builds a real discovered graph with two function nodes (`alpha`, `beta`).
   - Uses real event routing + real Grail `send_message` tool execution.
   - Verifies `alpha -> beta` ping and `beta -> alpha` pong in persisted events.

5. CI recommendation handling:
   - Review recommendation suggested adding `REMORA_TEST_MODEL_URL` in CI.
   - User explicitly requested no GitHub CI work, so this was intentionally not implemented.

## Verification

- Targeted run (new/changed tests + live LLM):
  - `3 passed`
- Full suite run with live LLM env:
  - `187 passed in 19.13s`

Runtime values used for live integration verification:
- `REMORA_TEST_MODEL_URL=http://remora-server:8000/v1`
- `REMORA_TEST_MODEL_NAME=Qwen/Qwen3-4B-Instruct-2507-FP8`
