# Remora-v2 Test Suite: Full Analysis for Real-World E2E Readiness

## Executive Summary
The suite is broad and stable for component-level behavior. It also already contains real-vLLM integration tests and they pass against `http://remora-server:8000/v1`.

The central gap is not model connectivity; it is full-path realism. The current real-vLLM tests exercise `Actor._execute_turn(...)` directly instead of driving user-realistic runtime boundaries (`remora start`, web API input, dispatcher/routing loop, actor pool scheduling, SSE observability, and optional LSP process IO).

## What Is Strong Today
- Core logic coverage is substantial (286 tests, 281 pass + 5 env-gated model tests by default).
- Real-vLLM behavior is exercised in five targeted scenarios:
  - `tests/integration/test_llm_turn.py:275`
  - `tests/integration/test_llm_turn.py:358`
  - `tests/integration/test_llm_turn.py:414`
  - `tests/integration/test_llm_turn.py:485`
  - `tests/integration/test_llm_turn.py:585`
- Web API semantics are heavily validated, including SSE replay/live payload shape and security checks, via ASGI transport:
  - setup via in-memory ASGI client at `tests/unit/test_web_server.py:64-71`
- LSP features are validated through internal handler invocation:
  - handler access at `tests/unit/test_lsp_server.py:45-47`
- Startup/shutdown lifecycle has a smoke test:
  - `_start(..., no_web=True, lsp=False)` at `tests/integration/test_startup_shutdown.py:30-39`

## Realism Gaps (Prioritized)

### P0: No full user-path acceptance test with real vLLM and live runtime loop
Evidence:
- `_start` can run full runtime including web/LSP (`src/remora/__main__.py:143-275`), but integration coverage uses no-web/no-lsp mode only (`tests/integration/test_startup_shutdown.py:30-39`).
- Real-vLLM tests invoke `Actor._execute_turn` directly (`tests/integration/test_llm_turn.py:336`, `:390`, `:442`, `:467`, `:565`, `:612`) rather than routing a user event through running services.

Impact:
- Misses regressions in orchestration path: HTTP ingress -> event persistence -> trigger dispatch -> actor pool scheduling -> actor turn -> emitted events -> SSE egress.

### P0: “E2E” tests are partly simulation-first
Evidence:
- `test_e2e_human_chat_to_rewrite` monkeypatches kernel and tool discovery (`tests/integration/test_e2e.py:156-159`, `:190-193`).
- `test_e2e_two_agents_interact_via_send_message_tool` monkeypatches kernel (`tests/integration/test_e2e.py:294-297`).

Impact:
- Useful for deterministic behavior, but not sufficient for real-world runtime confidence under true model/tool execution.

### P1: Web tests are ASGI-internal, not network/server-process level
Evidence:
- Uses `httpx.ASGITransport(app=app)` directly (`tests/unit/test_web_server.py:69-70`, `:119-120`).

Impact:
- Does not verify uvicorn socket binding, lifecycle startup timing, or external-client interaction quirks.

### P1: LSP tests bypass `start_io` transport boundary
Evidence:
- Tests call exposed handlers directly (`tests/unit/test_lsp_server.py:45-47`, `:141-143`, etc.).
- CLI path launches `start_io()` in production (`src/remora/__main__.py:138-140` and `:231-236`) without process-level protocol tests.

Impact:
- Missing confidence on real editor-protocol interaction boundary and stdin/stdout lifecycle behavior.

### P2: Missing explicit `RuntimeServices` composition tests
Evidence:
- `src/remora/core/services.py` has no direct tests; behavior is inferred indirectly via startup tests.

Impact:
- Composition regressions may surface late if initialization ordering changes.

## Assessment of Real-vLLM Coverage Quality
Current real-vLLM tests are valuable and should be kept. They verify:
- tool-call execution success path
- stateful KV tool interactions
- failure handling when bundle mutates to invalid model
- virtual-agent reactive behavior
- reactive prompt mode selection

But they are “actor-level real LLM” tests, not “system-level real user” tests.

## Recommended E2E Expansion Plan

### 1) Add acceptance test: live web + dispatcher + actor pool + real vLLM
Target flow:
1. Start runtime with web enabled (`_start(..., no_web=False, lsp=False)` or CLI subprocess).
2. POST `/api/chat` with a prompt requiring tool use.
3. Observe `AgentCompleteEvent` and expected tool side effect from `/api/events` and/or `/sse`.
4. Assert no `AgentErrorEvent` for correlation.

This covers the full operational chain missing today.

### 2) Add acceptance test: proposal flow with real model-generated rewrite
Target flow:
1. Send prompt requiring rewrite/proposal.
2. Confirm `RewriteProposalEvent` appears.
3. Call `/api/proposals/{node}/diff` then `/accept`.
4. Assert file materialized and `ContentChangedEvent` emitted.

### 3) Add acceptance test: reactive trigger with live runtime and real vLLM
Target flow:
1. Start runtime + reconciler loop.
2. Modify file on disk.
3. Confirm reactive-triggered turn leads to expected tool message/content.

### 4) Add process-level LSP smoke
Target flow:
1. Start runtime.
2. Launch standalone LSP process against runtime DB.
3. Drive minimal JSON-RPC sequence for open/save.
4. Assert content-change event appears in DB/event API.

## Operational Suggestions
- Introduce markers (`acceptance`, `real_llm`) to separate deterministic CI runs from environment-dependent runs.
- Keep current actor-level real-vLLM tests for fast signal; add a small number of system-level tests for orchestration correctness.
- Use strict timeouts and correlation IDs to keep acceptance tests deterministic.

## Bottom Line
Today’s suite proves most internals and actor-level real-vLLM behavior. It does not yet fully prove user-realistic, process-boundary, end-to-end behavior with vLLM in the middle of a live Remora runtime. The highest ROI is adding 2-4 acceptance tests that exercise the full runtime chain without monkeypatching core execution paths.
