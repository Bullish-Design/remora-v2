# Assumptions

- Real-LLM acceptance tests should be env-gated and not block default deterministic local runs.
- `http://remora-server:8000/v1` is a valid vLLM-compatible endpoint in this environment when explicitly configured.
- Process-boundary tests must prioritize deterministic teardown and bounded runtime to avoid flakes.
