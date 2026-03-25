# Context

- Active project: `52-test-suite-real-world-coverage`.
- Source guide: `.scratch/projects/52-test-suite-real-world-coverage/TEST_SUITE_IMPROVEMENT_GUIDE.md`.
- Current state: Task D complete (`tests/integration/test_llm_directory_agent.py` passes with real LLM).
- Key notes:
  - `review_diff` now reads node `text` for actual diffing.
  - `suggest_tests` now reads node `text` for real source context.
- Next action: implement Task E in `tests/integration/test_llm_system_tools.py` for system bundle extended tool coverage.
