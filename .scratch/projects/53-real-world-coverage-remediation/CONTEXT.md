# Context

- Project objective remains: close all real-world coverage gaps with hard requirement that every default bundle
  `.pym` has a real-vLLM execution path.

## Implemented Workstreams

- WS1 complete: real-vLLM tests for production `code-agent` tools (`rewrite_self`, `scaffold`).
- WS2 complete: behavioral unit tests added for parse-only system/companion scripts.
- WS3 complete: real-vLLM system scenarios expanded (`ask_human`, `semantic_search`, `categorize`, `find_links`,
  `summarize`, companion KV tools).
- WS4 complete in code: real remote search integration module added (`tests/integration/test_search_remote_backend.py`),
  env-gated by `REMORA_TEST_SEARCH_URL`.
- WS5 complete in code: browser automation module added (`tests/acceptance/test_web_graph_ui.py`), gated on Playwright
  availability.
- WS6 complete: process-level LSP acceptance expanded with `hover`, `codeAction`, `workspace/executeCommand`, and
  `didOpen` -> `didChange` -> `didSave` assertions against runtime events.

## Validation State

- Unit behavior matrix passes (`tests/unit/test_system_companion_tool_behavior.py`, `tests/unit/test_grail.py`, `tests/unit/test_search.py`).
- Full real-LLM integration matrix passes (`33 passed`) across:
  - `tests/integration/test_llm_turn.py`
  - `tests/integration/test_llm_system_tools.py`
  - `tests/integration/test_llm_companion.py`
  - `tests/integration/test_llm_review_agent.py`
  - `tests/integration/test_llm_test_agent.py`
  - `tests/integration/test_llm_directory_agent.py`
- Full acceptance matrix passes (`10 passed`, 2 warnings):
  - `tests/acceptance/test_live_runtime_real_llm.py`
  - `tests/acceptance/test_web_graph_ui.py`
- WS4 remote backend integration now executes and passes (`tests/integration/test_search_remote_backend.py`: `4 passed`) with `REMORA_TEST_SEARCH_URL=http://127.0.0.1:18585`.

## Next Action

- Commit and push the current workstream changes.
