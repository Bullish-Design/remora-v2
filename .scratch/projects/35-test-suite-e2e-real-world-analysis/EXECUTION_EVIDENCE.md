# Execution Evidence (2026-03-16)

## Environment Sync
Command:
- `devenv shell -- uv sync --extra dev`

Result:
- Successful dependency audit/sync.

## Baseline Suite (Default Env)
Command:
- `devenv shell -- pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q -ra`

Result:
- `281 passed, 5 skipped in 104.08s`
- All 5 skips are real-LLM tests in `tests/integration/test_llm_turn.py` due missing `REMORA_TEST_MODEL_URL`.

## Real-vLLM Endpoint Reachability
Command:
- `devenv shell -- curl -sS -m 8 -i http://remora-server:8000/v1/models`

Result:
- HTTP 200
- Available model included: `Qwen/Qwen3-4B-Instruct-2507-FP8`

## Real-vLLM Integration Run
Command:
- `devenv shell -- env REMORA_TEST_MODEL_URL='http://remora-server:8000/v1' REMORA_TEST_MODEL_NAME='Qwen/Qwen3-4B-Instruct-2507-FP8' pytest tests/integration/test_llm_turn.py -q -rs`

Result:
- `5 passed in 17.12s`
- Confirms real request/response flow via vLLM-compatible endpoint for current `test_llm_turn` scenarios.

## Additional Spot Checks
- `devenv shell -- pytest tests/unit/test_metrics.py -q` -> `2 passed`
- `devenv shell -- pytest tests/integration/test_e2e.py -q` -> `4 passed`
