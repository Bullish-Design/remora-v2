# Progress — 21-virtual-agent-implementation

- [x] Create project template docs
- [x] Add failing tests for virtual-agent behavior
- [x] Implement config + runtime changes
- [x] Add/adjust bundles/config examples
- [x] Run full and real integration tests
- [ ] Commit and push

## Validation
- `devenv shell -- env REMORA_TEST_MODEL_URL='http://remora-server:8000/v1' REMORA_TEST_MODEL_NAME='Qwen/Qwen3-4B-Instruct-2507-FP8' python -m pytest tests/integration/test_llm_turn.py -q -rs`
  - Result: `5 passed`
- `devenv shell -- env REMORA_TEST_MODEL_URL='http://remora-server:8000/v1' REMORA_TEST_MODEL_NAME='Qwen/Qwen3-4B-Instruct-2507-FP8' python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q`
  - Result: `212 passed`
