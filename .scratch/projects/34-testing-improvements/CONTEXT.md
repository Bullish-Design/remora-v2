# Context

New project created to implement section 6 testing improvements from recommendations.

Current status:
- Implemented all section 6 testing improvements.
- Added concurrent actor-pool trigger test in `tests/unit/test_runner.py`.
- Added Hypothesis property tests for subscription matching in `tests/unit/test_subscription_registry.py`.
- Added startup/shutdown integration test with `_start(..., run_seconds=2.0)` in `tests/integration/test_startup_shutdown.py`.
- Added reconciler load test for 1000 files x 10 nodes in `tests/integration/test_performance.py`.
- Updated 5 real-LLM integration tests to use explicit `@pytest.mark.skipif(..., reason=...)` decorators in `tests/integration/test_llm_turn.py`.
- Fixed baseline reconciler test monkeypatch signature regression in `tests/unit/test_reconciler.py`.
- Added `hypothesis` to `[project.optional-dependencies].dev` in `pyproject.toml` for property tests.

Validation summary:
- `devenv shell -- pytest -v tests/unit/test_reconciler.py::test_reconciler_survives_cycle_error`
- `devenv shell -- pytest -v tests/unit/test_runner.py::test_runner_handles_concurrent_triggers_across_agents`
- `devenv shell -- pytest -v tests/unit/test_subscription_registry.py -k "property_subscription"`
- `devenv shell -- pytest -v tests/integration/test_startup_shutdown.py`
- `devenv shell -- pytest -v tests/integration/test_performance.py -k "perf_reconciler_load_1000_files_10_nodes_each"`
- `devenv shell -- pytest -q -rs tests/integration/test_llm_turn.py -k "test_real_llm"` (5 skipped with explicit reason output)
- `devenv shell -- ruff check tests/unit/test_runner.py tests/unit/test_subscription_registry.py tests/integration/test_startup_shutdown.py tests/integration/test_performance.py tests/unit/test_reconciler.py`

Next:
- Ready for review and optional broader suite execution.
