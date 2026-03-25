# Context

- Active project: `52-test-suite-real-world-coverage`.
- Source guide: `.scratch/projects/52-test-suite-real-world-coverage/TEST_SUITE_IMPROVEMENT_GUIDE.md`.
- Current state: Task B complete (`tests/integration/test_llm_review_agent.py` passes with real LLM).
- Key note: `review_diff` required a runtime fix to read node `text` instead of `source_code`.
- Next action: implement Task C in `tests/integration/test_llm_test_agent.py` for `suggest_tests` and `scaffold_test`.
