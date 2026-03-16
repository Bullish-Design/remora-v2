# Context

Implementation complete.

What was delivered:
- New process-boundary acceptance suite in `tests/acceptance/test_live_runtime_real_llm.py` covering:
  1. Live web ingress -> dispatcher -> actor pool -> real-vLLM tool/message flow
  2. Real model proposal generation -> `/api/proposals/{node}/diff` -> `/accept` materialization
  3. Live reactive trigger flow leading to deterministic `reactive-ok` tool message
  4. Process-level standalone LSP JSON-RPC open/save smoke with event verification
- Operational suggestions implemented:
  - Added pytest markers (`acceptance`, `real_llm`) in `pyproject.toml`
  - Tagged real-LLM integration module (`tests/integration/test_llm_turn.py`) with `real_llm`
  - Added test profile/run guidance to `README.md`

Validation highlights:
- `pytest tests/integration/test_llm_turn.py -m real_llm -q -rs` -> 5 passed
- `pytest tests/acceptance -m 'acceptance and real_llm' -q -rs` -> 3 passed, 1 deselected
- `pytest tests/acceptance/test_live_runtime_real_llm.py::test_acceptance_process_lsp_open_save_emits_content_changed_event -q -rs` -> 1 passed

All requested implementation items were committed and pushed step-by-step.
