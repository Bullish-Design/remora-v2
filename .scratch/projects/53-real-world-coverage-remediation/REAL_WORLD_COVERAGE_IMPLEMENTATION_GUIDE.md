# Real-World Coverage Remediation Guide

## 1. Goal

Implement full behavioral coverage for the gaps identified in the audit, with emphasis on production bundle scripts and end-to-end runtime flows.

Hard requirement:

- Every default bundle `.pym` script under `src/remora/defaults/bundles/**/tools/*.pym` must be executed by agent turns that use real calls to the vLLM endpoint.
- Parse-only checks are not sufficient for sign-off.

## 2. Coverage Gaps to Close

1. Production `code-agent` tools (`rewrite_self`, `scaffold`) are not covered in real-world usage paths.
2. `system/companion` tools (`companion_*`, `find_links`, `categorize`, `summarize`) are mostly parse/existence tested.
3. Real-LLM integration is missing for `ask_human`, `semantic_search`, and `categorize`.
4. Search backend coverage is mostly mocked.
5. Frontend graph behavior has no browser automation tests.
6. LSP process acceptance is narrow (open/save only).

## 3. Global Rules

- Run all project code via `devenv shell --`.
- Use deterministic system prompts in real-LLM tests: direct tool-call instructions with fixed arguments.
- Prefer production bundle copies for integration tests unless deterministic fixture tools are required for infra harnessing.
- Keep one commit per workstream step.
- For completion, each default `.pym` must have at least one passing real-LLM test correlation proving tool execution (`remora_tool_result` for that `tool_name`).

## 4. Environment Setup

```bash
devenv shell -- uv sync --extra dev

export REMORA_TEST_MODEL_URL="http://remora-server:8000/v1"
export REMORA_TEST_MODEL_NAME="Qwen/Qwen3-4B-Instruct-2507-FP8"
export REMORA_TEST_MODEL_API_KEY="EMPTY"
export REMORA_TEST_TIMEOUT_S="90"
```

Optional search backend gate:

```bash
export REMORA_TEST_SEARCH_URL="http://localhost:8585"
```

## 5. Workstream Plan

## WS1: Production `code-agent` Real-World Tool Coverage

### Objective
Exercise production `rewrite_self.pym` and `scaffold.pym` through actor runtime with model-driven tool invocation.

### Files

- Update: `tests/integration/test_llm_turn.py`
- Optional helper refactor: `tests/integration/test_llm_turn.py` bundle writer helpers

### Required Tests

1. `test_real_llm_code_agent_rewrite_self_proposes_changes`
2. `test_real_llm_code_agent_scaffold_emits_scaffold_request`

### Assertions

- Tool call/result events exist with `tool_name` matching production script name.
- `rewrite_self` writes to workspace path `source/{node_id}` and emits `rewrite_proposed`.
- `scaffold` emits `ScaffoldRequestEvent` with expected payload fields.
- No `agent_error` for correlation.

### Notes

- Do not rely on custom `rewrite_to_magic` helper in this workstream.
- Copy production `code-agent` and `system` bundles.

## WS2: Behavioral Coverage for Parse-Only System/Companion Tools

### Objective
Convert parse/existence-only checks into behavior tests that execute script logic with realistic externals.

### Files

- New: `tests/unit/test_system_companion_tool_behavior.py`
- Keep existing parse tests; do not delete.

### Required Tool Behavior Cases

1. `companion_summarize`: writes bounded `companion/chat_index`, supports string/list tags.
2. `companion_reflect`: appends reflection entries with correlation id.
3. `companion_link`: deduplicates target links and preserves relationship metadata.
4. `summarize`: writes `notes/summary.md` from event history.
5. `find_links`: writes `meta/links.md` from graph edges.
6. `categorize`: writes `meta/categories.md` with deterministic category from source.

### Harness Approach

- Use `grail.load(...).run(inputs=..., externals=...)` for deterministic script execution.
- Provide stub async externals for `kv_get/kv_set`, `write_file`, `graph_get_node`, `graph_get_edges`, `my_correlation_id`, `event_get_history`.

## WS3: Missing Real-LLM `system` Tool Scenarios

### Objective
Add real-LLM tests for `ask_human`, `semantic_search`, and `categorize`.

### Files

- Update: `tests/integration/test_llm_system_tools.py`

### Required Tests

1. `test_real_llm_system_ask_human_roundtrip`
2. `test_real_llm_system_semantic_search` (gated if backend unavailable)
3. `test_real_llm_system_categorize_writes_meta_file`
4. `test_real_llm_system_find_links_writes_meta_file`
5. `test_real_llm_system_summarize_writes_summary_file`
6. `test_real_llm_system_companion_summarize_records_chat_index`
7. `test_real_llm_system_companion_reflect_records_reflection`
8. `test_real_llm_system_companion_link_records_link`

### Harness Additions

- For `ask_human`, add programmable broker support in integration runtime helper:
  - create pending request, resolve response, assert `human_input_request` event and completion.
- For search tests, conditionally skip when search backend unavailable.
- For `categorize`, verify `meta/categories.md` exists and includes expected sections.
- For companion helper tools, assert KV state writes for expected keys and shape.

### Gate Pattern

- Use a helper that checks backend health and skips with explicit reason when unavailable.

## WS4: Real Backend Search Integration Coverage

### Objective
Validate actual search service path beyond mocked clients.

### Files

- New: `tests/integration/test_search_remote_backend.py`
- Optional update: `tests/unit/test_search.py` for additional edge handling found during integration

### Required Cases

1. `SearchService.initialize()` with real backend health check.
2. `search()` returns structured records (or empty deterministic response).
3. `index_file()` and `delete_source()` execute without client protocol errors.
4. `/api/search` route works end-to-end against real service with realistic payload.

### Notes

- Gate entire module by `REMORA_TEST_SEARCH_URL`.
- Avoid brittle score assertions; assert schema/shape and request echo fields.

## WS5: Frontend Graph Browser Automation

### Objective
Add automated regression checks for graph rendering and node interaction in the live UI.

### Files

- New: `tests/acceptance/test_web_graph_ui.py`
- Optional utilities: `tests/acceptance/_web_ui_helpers.py`

### Tooling

- Use Playwright Python (headless by default in CI).

### Required Cases

1. Graph loads and node labels render (rounded label boxes visible in viewport).
2. Clicking label-hitbox selects node and updates sidebar panel.
3. Agent panel send action posts chat and produces event/timeline entry.
4. SSE disconnect/reconnect indicator changes state.

### Data Setup

- Boot runtime with small source tree and deterministic events.
- Wait on explicit DOM conditions, not fixed sleeps.

## WS6: LSP Process Acceptance Expansion

### Objective
Expand process-level LSP acceptance coverage beyond open/save into user-visible commands.

### Files

- Update: `tests/acceptance/test_live_runtime_real_llm.py`
- Optional split: new `tests/acceptance/test_lsp_process_flow.py`

### Required Cases

1. `textDocument/hover` returns node content for discovered symbol.
2. `textDocument/codeAction` returns Remora actions for node span.
3. Trigger command path emits event that reaches runtime event stream.
4. Multi-change cycle (`didOpen` -> `didChange` -> `didSave`) preserves expected event semantics.

### Assertions

- Verify JSON-RPC payload shape, ids, and expected command names.
- Verify downstream event-store side effects via web `/api/events`.

## 6.1 Complete `.pym` Real-LLM Coverage Matrix

Target: all scripts below must be exercised by real-vLLM tests.

Code-agent bundle:

- `rewrite_self` -> WS1 new test
- `scaffold` -> WS1 new test

Companion bundle:

- `aggregate_digest` -> already covered in `tests/integration/test_llm_companion.py`

Directory-agent bundle:

- `list_children` -> already covered
- `broadcast_children` -> already covered
- `summarize_tree` -> already covered
- `get_parent` -> already covered

Review-agent bundle:

- `list_recent_changes` -> already covered
- `review_diff` -> already covered
- `submit_review` -> already covered

System bundle:

- `send_message` -> already covered
- `broadcast` -> already covered
- `query_agents` -> already covered
- `subscribe` -> already covered
- `unsubscribe` -> already covered
- `kv_get` -> already covered
- `kv_set` -> already covered
- `reflect` -> already covered
- `ask_human` -> WS3 new test
- `semantic_search` -> WS3 new test
- `categorize` -> WS3 new test
- `find_links` -> WS3 new test
- `summarize` -> WS3 new test
- `companion_summarize` -> WS3 new test
- `companion_reflect` -> WS3 new test
- `companion_link` -> WS3 new test

Test-agent bundle:

- `suggest_tests` -> already covered
- `scaffold_test` -> already covered

## 7. Verification Matrix

Run in this order:

1. Fast unit behavior tests

```bash
devenv shell -- pytest \
  tests/unit/test_system_companion_tool_behavior.py \
  tests/unit/test_grail.py \
  tests/unit/test_search.py -q
```

2. Real-LLM integration set (must include every `.pym` tool listed in section 6.1)

```bash
devenv shell -- pytest \
  tests/integration/test_llm_turn.py \
  tests/integration/test_llm_system_tools.py \
  tests/integration/test_llm_companion.py \
  tests/integration/test_llm_review_agent.py \
  tests/integration/test_llm_test_agent.py \
  tests/integration/test_llm_directory_agent.py \
  -m real_llm -v
```

3. Acceptance suite

```bash
devenv shell -- pytest \
  tests/acceptance/test_live_runtime_real_llm.py \
  tests/acceptance/test_web_graph_ui.py \
  -v
```

4. Search integration gate (when backend available)

```bash
devenv shell -- pytest tests/integration/test_search_remote_backend.py -v
```

## 8. Definition of Done

- All WS1-WS6 tests implemented and passing in their enabled environments.
- No existing real-LLM tests regressed.
- New tests document skip reasons for unavailable external services.
- Final coverage summary added to this project’s `CONTEXT.md` and `PROGRESS.md`.
- Every default bundle `.pym` has at least one passing real-LLM execution path in test logs.

## 9. Commit Plan

1. `test(real-llm): cover production code-agent rewrite_self and scaffold`
2. `test(unit): add behavioral coverage for companion/system scripts`
3. `test(real-llm): add full system tool real-vllm coverage`
4. `test(integration): add real backend search service coverage`
5. `test(acceptance): add playwright graph ui coverage`
6. `test(acceptance): expand lsp process-level acceptance flows`
7. `chore(test): finalize verification matrix and stabilize flakes`
