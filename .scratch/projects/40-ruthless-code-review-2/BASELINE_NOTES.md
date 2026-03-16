# Phase 0 Baseline Notes

## Step 0.1 Dependency Sync
Command:
`devenv shell -- uv sync --extra dev`

Result:
- Completed successfully.
- Environment updates removed 10 packages:
  - coverage
  - librt
  - mypy
  - mypy-extensions
  - nvidia-ml-py
  - pathspec
  - py-cpuinfo
  - pynvml
  - pytest-benchmark
  - pytest-cov

## Step 0.2 Full Test Suite
Command:
`devenv shell -- python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q`

Result:
- `349 passed, 8 skipped, 3 warnings in 161.87s`
- Warning highlights:
  - `TurnDigestedEvent.summary` shadows parent `Event` attribute
  - websockets legacy deprecation warnings in acceptance path

## Step 0.3 Linter
Command:
`devenv shell -- ruff check src/`

Result:
- Non-zero exit from pre-existing style issues.
- 3 line-length violations:
  - `src/remora/core/actor.py:48` (102 > 100)
  - `src/remora/core/actor.py:244` (106 > 100)
  - `src/remora/core/search.py:42` (103 > 100)
