# Context

- Active project: `52-test-suite-real-world-coverage`.
- Source guide: `.scratch/projects/52-test-suite-real-world-coverage/TEST_SUITE_IMPROVEMENT_GUIDE.md`.
- Current state: Task F complete (new code-agent tests in `test_llm_turn.py` pass with real LLM).
- Key notes:
  - `review_diff` now reads node `text` for actual diffing.
  - `suggest_tests` now reads node `text` for real source context.
- Next action: implement Step 9 acceptance additions in `tests/acceptance/test_live_runtime_real_llm.py`.
