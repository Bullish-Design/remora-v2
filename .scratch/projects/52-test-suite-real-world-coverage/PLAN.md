# Plan

NO SUBAGENTS. Do all work directly.

## Objective
Implement all steps in `.scratch/projects/52-test-suite-real-world-coverage/TEST_SUITE_IMPROVEMENT_GUIDE.md` with test-first workflow and per-step commit/push.

## Ordered Steps

1. Environment/baseline setup
   - Sync deps via `devenv shell -- uv sync --extra dev`
   - Confirm vLLM reachability and inspect existing real-LLM test helpers.
2. Step 4 bug fix
   - Fix `review-agent/tools/list_recent_changes.pym` to use `graph_query_nodes`.
   - Add/adjust test coverage if needed for this external name mapping.
3. Task A
   - Add `tests/integration/test_llm_companion.py` with 2 real-LLM tests using real production bundles.
4. Task B
   - Add `tests/integration/test_llm_review_agent.py` with 2 tests for `list_recent_changes` + `review_diff` + `submit_review`.
5. Task C
   - Add `tests/integration/test_llm_test_agent.py` with 2 tests for `suggest_tests` + `scaffold_test`.
6. Task D
   - Add `tests/integration/test_llm_directory_agent.py` with 4 tests for directory tools.
7. Task E
   - Add `tests/integration/test_llm_system_tools.py` with 4 tests for `broadcast/query_agents/reflect/subscribe-unsubscribe`.
8. Task F
   - Extend `tests/integration/test_llm_turn.py` with 2 code-agent tests for `reflect` and `subscribe`.
9. Acceptance additions
   - Extend `tests/acceptance/test_live_runtime_real_llm.py` with 2 full-stack tests for companion and review-agent flows.
10. Full verification
   - Run targeted + aggregate real-LLM commands from guide and fix failures.

## Commit Strategy
- Commit and push after each numbered implementation step above.
- Commit messages: `test(real-llm): <step summary>` or `fix(bundle): <step summary>`.

## Acceptance Criteria
- Guide checklist items implemented.
- New tests use production bundle tool scripts.
- All relevant `-m real_llm` tests pass in devenv with configured model endpoint.

NO SUBAGENTS. Do all work directly.
