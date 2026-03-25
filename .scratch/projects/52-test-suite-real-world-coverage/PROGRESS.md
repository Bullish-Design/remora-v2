# Progress

## Step Status

- [x] 1. Environment/baseline setup
- [x] 2. Bug fix: review-agent `graph_list_nodes` -> `graph_query_nodes`
- [x] 3. Task A: companion integration tests
- [x] 4. Task B: review-agent integration tests
- [x] 5. Task C: test-agent integration tests
- [x] 6. Task D: directory-agent integration tests
- [x] 7. Task E: system tool integration tests
- [x] 8. Task F: code-agent tool integration tests
- [x] 9. Acceptance test additions
- [ ] 10. Full verification run

## Log

- Initialized project tracking files and implementation plan.
- Completed dependency sync and verified vLLM model endpoint reachability.
- Captured reusable helper/test patterns in `BASELINE_NOTES.md`.
- Fixed `review-agent/tools/list_recent_changes.pym` to call `graph_query_nodes`.
- Added regression alignment in `tests/integration/test_virtual_reactive_flow.py`.
- Verified with `devenv shell -- pytest tests/integration/test_virtual_reactive_flow.py -q` (5 passed).
- Added `tests/integration/test_llm_companion.py` with two real-LLM tests using copied production bundles.
- Verified Task A with:
  - `devenv shell -- pytest tests/integration/test_llm_companion.py -m real_llm -v` (2 passed)
  - `devenv shell -- ruff check tests/integration/test_llm_companion.py` (clean)
- Added `tests/integration/test_llm_review_agent.py` with two real-LLM tests for list/review/submit and second-pass diff detection.
- Fixed `review_diff.pym` source lookup from `source_code` to `text` (with fallback) so live graph node data is diffed correctly.
- Verified Task B with:
  - `devenv shell -- pytest tests/integration/test_llm_review_agent.py -m real_llm -v` (2 passed)
  - `devenv shell -- pytest tests/integration/test_virtual_reactive_flow.py -q` (5 passed)
- Added `tests/integration/test_llm_test_agent.py` with two real-LLM tests for `suggest_tests` and `scaffold_test`.
- Fixed `suggest_tests.pym` source lookup from `source_code` to `text` (with fallback).
- Verified Task C with:
  - `devenv shell -- pytest tests/integration/test_llm_test_agent.py -m real_llm -v` (2 passed)
- Added `tests/integration/test_llm_directory_agent.py` with 4 real-LLM tests for `list_children`, `summarize_tree`, `get_parent`, and `broadcast_children`.
- Verified Task D with:
  - `devenv shell -- pytest tests/integration/test_llm_directory_agent.py -m real_llm -v` (4 passed)
- Added `tests/integration/test_llm_system_tools.py` with 4 real-LLM tests for `broadcast`, `query_agents`, `reflect`, and `subscribe`/`unsubscribe`.
- Fixed system tool runtime issues uncovered by live tests:
  - `query_agents.pym` no-argument query path for stable execution without optional Input defaults.
  - `reflect.pym` no longer depends on reading a pre-existing reflection file.
  - `subscribe.pym` no longer depends on optional Input defaults for extra filters.
- Verified Task E with:
  - `devenv shell -- pytest tests/integration/test_llm_system_tools.py -m real_llm -v` (4 passed)
- Extended `tests/integration/test_llm_turn.py` with Task F code-agent real-LLM tests:
  - `test_real_llm_code_agent_reflect_writes_to_workspace`
  - `test_real_llm_code_agent_subscribe_to_events`
- Verified Task F with:
  - `devenv shell -- pytest tests/integration/test_llm_turn.py -k \"code_agent_reflect_writes_to_workspace or code_agent_subscribe_to_events\" -m real_llm -v` (2 passed)
- Extended acceptance coverage in `tests/acceptance/test_live_runtime_real_llm.py`:
  - `test_acceptance_companion_reacts_to_code_agent_complete`
  - `test_acceptance_review_agent_reacts_to_node_changed`
- Added acceptance project writers for production-style companion and review-agent flows.
- Fixed companion helper tools for grail type/runtime compatibility:
  - `companion_summarize.pym`
  - `companion_reflect.pym`
  - `companion_link.pym`
- Verified Step 9 with:
  - `devenv shell -- pytest tests/acceptance/test_live_runtime_real_llm.py -k \"companion_reacts_to_code_agent_complete or review_agent_reacts_to_node_changed\" -m real_llm -v` (2 passed)
