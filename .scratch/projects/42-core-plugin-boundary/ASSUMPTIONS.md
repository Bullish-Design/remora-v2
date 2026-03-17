# Assumptions

1. No backwards compatibility shims are required unless the guide explicitly asks for them.
2. Existing uncommitted changes in `src/remora/core/config.py` and `src/remora/defaults/__init__.py` are intern carry-over for project 42 and can be integrated/corrected.
3. Commit granularity follows meaningful guide steps (not necessarily every sub-bullet), with tests run per step.
4. `devenv shell -- uv sync --extra dev` must be run before first test execution in this session.
5. `.scratch/projects/42-core-plugin-boundary/` is the only location for this project’s scratch/planning/progress notes.
