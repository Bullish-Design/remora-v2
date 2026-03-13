# Test Review Review

## Intern's Review: What They Got Wrong

The intern's review contains several factual errors that undermine its credibility:

1. **"163 tests across 30 test files"** — Actually **183 tests across 31 files**. They missed entire test files (`test_views.py`, `test_db.py`, `test_events.py`, `test_agent_store.py`, `test_paths.py`, `test_system_tools.py`, `test_code_tools.py`, `test_companion_tools.py`, `test_directory_tools.py`) and miscounted tests in files they did find.

2. **"No kernel.py tests — MISSING FILE"** — `tests/unit/test_kernel.py` exists with 2 tests (`test_create_kernel`, `test_extract_response_text`). The intern either didn't look or looked at an older version of the repo.

3. **"No Grail tool execution tests"** — `tests/integration/test_grail_runtime_tools.py` exists with 2 tests that execute real Grail scripts against real externals, using actual `.pym` fixture files and real bundle tools from `bundles/`. This is a significant miss — the intern flagged the *most tested* integration path as untested.

4. **Miscounted tests in nearly every file** — `test_actor.py` has 17 tests (they said 13), `test_grail.py` has 10 (they said 6), `test_workspace.py` has 13 (they said 12), `test_externals.py` has 11 (they said 9), `test_reconciler.py` has 12 (they said 8). The only counts they got right were for the integration tests.

5. **"Only 2 integration test files"** — There are 3: `test_e2e.py`, `test_performance.py`, and `test_grail_runtime_tools.py`.

6. **Coverage estimates are unsubstantiated** — The "estimated coverage" table (e.g., "Kernel ~10%", "Grail tools ~30%") appears to be guesswork. `kernel.py` is a 59-line thin wrapper — the 2 existing tests cover both exported functions. That's closer to 90% line coverage, not 10%.

The review's structure and recommendations are reasonable in the abstract, but because the factual foundation is wrong, several of the "high priority" recommendations are already done.

---

## What the Intern Got Right

Despite the errors, the core insight is sound: **the agent execution path (Event → Actor → Kernel → Tool → Response) is only tested with a mocked kernel**. The E2E tests in `test_e2e.py` mock both `create_kernel` and `discover_tools`, meaning we never verify that:

- A real LLM receives correctly-formed prompts
- A real LLM can invoke tools via the structured_agents agentic loop
- Tool results flow back correctly through the kernel
- The full turn completes end-to-end with a real model

This is the genuine gap. Everything else the intern flagged either already exists or is low-value.

---

## Actual State of the Test Suite

### What's Well-Tested (Real Components, No Mocks)

| Component | Tests | Approach |
|-----------|-------|----------|
| SQLite (AsyncDB, NodeStore, AgentStore, EventStore) | ~25 | Real SQLite via `tmp_path` |
| Event system (EventBus, SubscriptionRegistry, dispatcher) | ~18 | Real in-memory bus + real SQLite store |
| Workspace (CairnWorkspaceService, AgentWorkspace) | 13 | Real filesystem via `tmp_path` + real cairn COW |
| Code discovery (tree-sitter) | 12 | Real tree-sitter parsing of real source files |
| Reconciliation (FileReconciler) | 12 | Real file I/O, real discovery, real events |
| Externals (AgentContext) | 11 | Real stores, real workspace ops |
| Grail tools | 10 unit + 2 integration | Real Grail script execution, real `.pym` files |
| Web API | 11 | Real Starlette ASGI via httpx |
| Bundle tool parsing | 8 | Real YAML + real Grail script loading |
| Runner | 7 | Real actor creation, routing, eviction |
| Actor model primitives | 10 (outbox, lifecycle, cooldown, depth) | Real stores, real config |
| Config | 6 | Real YAML parsing, real env var expansion |
| Performance | 3 | Real benchmarks with thresholds |

### What's Mocked

Only two things are mocked in the entire suite:

1. **`create_kernel`** — Mocked in `test_actor.py` (4 tests) and `test_e2e.py` (1 test) to avoid real LLM calls.
2. **`discover_tools`** — Mocked alongside the kernel in `test_e2e.py` only. Note: `test_actor.py` mocks it to return `[]` (empty), which is a valid degenerate case.
3. **`watchfiles.awatch`** — Mocked in `test_reconciler.py` to simulate file change events without actual filesystem watching.

That's it. The intern's review made it sound like mocking was pervasive — it isn't. The suite is predominantly real-component testing. The mocking is concentrated at exactly one boundary: the LLM API call.

---

## The Real Gap: No Real LLM Integration Test

The one genuine, significant gap is that no test verifies the full agent turn with a real LLM. Here's exactly what's untested:

```
Actor._execute_turn()
  → create_kernel(model_name=..., base_url=..., api_key=..., tools=...)
  → kernel.run(messages, tool_schemas, max_turns=N)
    → LLM generates response with tool_calls
    → structured_agents executes GrailTool.execute() for each call
    → Tool results fed back to LLM
    → LLM generates final response
  → extract_response_text(result)
```

Everything *around* this path is tested. The tools themselves are tested (via `test_grail_runtime_tools.py`). The prompt construction is tested (via `test_runner.py::test_runner_build_prompt_via_actor`). The externals are tested. The event emission is tested. But the actual kernel↔LLM↔tool loop has never run in CI.

### Why This Matters

This is not just a coverage gap — it's a *confidence* gap. We cannot say with certainty that:

1. The prompts we construct are coherent to the model
2. The tool schemas we generate are parseable by the model
3. The structured_agents agentic loop works with our GrailTool wrapper
4. The model can successfully invoke tools and receive results
5. The full turn completes without hanging or crashing

### What We Should Do

Add a single, focused integration test that runs a real agent turn against a local LLM (e.g., the same vLLM/Ollama instance used in development). This test should:

1. Set up a real workspace with a real bundle and real tools
2. Create a real kernel pointing at the local model endpoint
3. Send a simple trigger event
4. Verify the agent completes with a coherent response
5. Optionally verify a tool was called (e.g., `send_message`)

```python
# tests/integration/test_llm_turn.py

@pytest.mark.integration
@pytest.mark.skipif(
    not os.getenv("REMORA_TEST_MODEL_URL"),
    reason="REMORA_TEST_MODEL_URL not set — skipping LLM integration test",
)
async def test_real_agent_turn_completes():
    """Full agent turn with real LLM, real tools, real workspace."""
    # 1. Set up workspace with echo tool
    # 2. Create kernel with real model endpoint
    # 3. Send HumanChatEvent("say hello using the echo tool")
    # 4. Assert AgentCompleteEvent emitted
    # 5. Assert no AgentErrorEvent emitted
```

This single test would close the biggest confidence gap in the suite.

---

## Secondary Gaps Worth Addressing

### 1. Error Path in Actor._execute_turn

The `except Exception` block at `actor.py:320` transitions the agent to ERROR status and emits `AgentErrorEvent`. This path is only implicitly tested (via `test_actor_missing_node`, which returns early before reaching the try/except). A test that forces a kernel failure (e.g., connection refused) would verify graceful degradation.

**Effort:** Small. Mock `create_kernel` to raise `ConnectionError`.

### 2. watchfiles Integration

The reconciler mocks `watchfiles.awatch`. This is reasonable for unit tests, but we should have one test that verifies real filesystem watching works. The `test_reconciler_content_changed_event_triggers_reconcile` test verifies event-driven reconciliation, which is the primary codepath anyway — the watchfiles integration is a secondary trigger.

**Effort:** Small but platform-dependent. Lower priority.

### 3. Concurrent Actor Execution

The semaphore in `actor.py:224` (`async with self._semaphore`) limits concurrent turns. No test verifies that the semaphore actually blocks when saturated. This is an asyncio primitive — the risk of it being broken is low, but a test would document the behavior.

**Effort:** Small.

### 4. Status Transition Consistency

`actor.py` transitions status in both `NodeStore` and `AgentStore`. The test for `test_actor_processes_inbox_message` only checks the final state (`idle`). A test that verifies the intermediate `RUNNING` state would catch ordering bugs. However, `test_nodestore_transition_status_valid` and `test_nodestore_transition_status_invalid` in `test_graph.py` already test the transition logic itself.

**Effort:** Trivial.

---

## What NOT to Do

The intern recommended several things that would be counterproductive:

1. **"Add contract tests for mocks"** — There's only one mock (`MockKernel`) and it's used in 5 tests. Adding a contract test framework for this is over-engineering. The real fix is to add one integration test with a real kernel.

2. **"Add test markers and categories"** — With 183 tests completing in seconds, there's no need to split into `unit`/`integration`/`e2e` categories. If the suite grows to where this matters, add it then.

3. **"Add mutation testing"** — Premature. The suite is young and growing. Mutation testing is valuable for mature, stable codebases, not actively-evolving ones.

4. **"Add coverage reporting"** — Nice to have, but won't find the actual gap (the mocked kernel path). Coverage would show `actor._execute_turn` as "covered" because the mocked tests do exercise those lines.

---

## Recommendations (Priority Order)

| # | Action | Effort | Impact |
|---|--------|--------|--------|
| 1 | Add `test_llm_turn.py` — one real agent turn against a local LLM | Medium | Closes the biggest confidence gap |
| 2 | Add error-path test for kernel failure in `_execute_turn` | Small | Verifies graceful degradation |
| 3 | Add `REMORA_TEST_MODEL_URL` to CI environment for gated integration tests | Small | Makes #1 run in CI |
| 4 | Consider a semaphore saturation test | Trivial | Documents concurrency behavior |

That's it. Four items. The suite is in better shape than the intern's review suggests — we just need to close the one real gap.
