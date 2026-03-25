# Assumptions

- The project root remains `/home/andrew/Documents/Projects/remora-v2`.
- Real-LLM tests target `remora-server:8000` with `Qwen/Qwen3-4B-Instruct-2507-FP8` unless explicitly overridden.
- `devenv shell --` is required for execution, linting, and testing commands.
- Existing Project 52 tests are the baseline and should not be regressed.
- New tests should prioritize deterministic prompts/fixtures to reduce model variance.
- Search backend real-world coverage may require optional environment gating when embeddy is unavailable.
