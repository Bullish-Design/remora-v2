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

- Real-vLLM reruns passed for updated WS1/WS3 suites:
  - `tests/integration/test_llm_turn.py -k "rewrite_self_proposes_changes or scaffold_emits_scaffold_request" -m real_llm`
  - `tests/integration/test_llm_system_tools.py -m real_llm`
- WS2 unit module passes.
- WS6 process-level LSP acceptance subset passes.
- WS4/WS5 modules are present and lint-clean, but runtime execution was skipped in this environment when optional
  dependencies/services were unavailable.

## Next Action

- Commit and push the current workstream changes.
- In an environment with both search backend and Playwright Chromium available, run final gated modules:
  - `tests/integration/test_search_remote_backend.py`
  - `tests/acceptance/test_web_graph_ui.py`
