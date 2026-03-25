# Progress

## Step Status

- [x] Create new numbered project directory
- [x] Add project planning/tracking files
- [x] Create detailed implementation guide
- [x] WS1: Production `code-agent` real-vLLM coverage (`rewrite_self`, `scaffold`)
- [x] WS2: Behavioral unit coverage for parse-only system/companion tools
- [x] WS3: Missing real-LLM `system` tool scenarios (`ask_human`, `semantic_search`, `categorize`, etc.)
- [x] WS4: Real remote search integration tests (env-gated module added)
- [x] WS5: Web graph browser automation tests (Playwright-gated module added)
- [x] WS6: Process-level LSP acceptance expansion (`hover`, `codeAction`, `executeCommand`, change cycle)
- [ ] Final matrix run in an environment with both `REMORA_TEST_SEARCH_URL` and Playwright Chromium
- [ ] Commit and push staged project workstream changes

## Log

- Created project directory: `.scratch/projects/53-real-world-coverage-remediation/`.
- Added standard project files: `PLAN.md`, `ASSUMPTIONS.md`, `PROGRESS.md`, `CONTEXT.md`, `DECISIONS.md`, `ISSUES.md`.
- Added `REAL_WORLD_COVERAGE_IMPLEMENTATION_GUIDE.md` with detailed, actionable workstreams and verification matrix.
- Updated guide and plan to enforce hard requirement: every default bundle `.pym` must be exercised via real-vLLM test turns.
- Added real-vLLM integration coverage in `tests/integration/test_llm_turn.py` for:
  - `test_real_llm_code_agent_rewrite_self_proposes_changes`
  - `test_real_llm_code_agent_scaffold_emits_scaffold_request`
- Added expanded real-vLLM system coverage in `tests/integration/test_llm_system_tools.py`, including:
  - `send_message`, `kv_set/kv_get`, `categorize`, `find_links`, `summarize`
  - `companion_summarize`, `companion_reflect`, `companion_link`
  - `semantic_search`, `ask_human`
- Added WS2 behavioral test module: `tests/unit/test_system_companion_tool_behavior.py`.
- Added WS4 remote backend integration module: `tests/integration/test_search_remote_backend.py`.
- Added WS5 browser automation module: `tests/acceptance/test_web_graph_ui.py`.
- Added WS6 process-level LSP acceptance in `tests/acceptance/test_live_runtime_real_llm.py`.
- Validation snapshots:
  - `tests/integration/test_llm_turn.py -k "rewrite_self_proposes_changes or scaffold_emits_scaffold_request" -m real_llm`: passed.
  - `tests/integration/test_llm_system_tools.py -m real_llm`: passed.
  - `tests/unit/test_system_companion_tool_behavior.py`: passed.
  - `tests/acceptance/test_live_runtime_real_llm.py -k "process_lsp"`: passed.
  - `tests/integration/test_search_remote_backend.py`: skipped when `REMORA_TEST_SEARCH_URL` unavailable.
  - `tests/acceptance/test_web_graph_ui.py`: skipped when Playwright/Chromium unavailable.
