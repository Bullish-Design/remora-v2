# Assumptions

- NO SUBAGENTS: all work is done directly in this session.
- The guide `TEST_SUITE_IMPROVEMENT_GUIDE.md` is the source of truth for required steps.
- "Commit and push between each step" means one logical commit per numbered guide step (bug fix, Tasks A-F, acceptance additions, final verification), pushed immediately after each commit.
- Real-world coverage means tests use production bundle tool scripts from `src/remora/defaults/bundles/*` rather than simplified synthetic scripts unless required for determinism.
- Real LLM tests run against `http://remora-server:8000/v1` with env vars used by current suite helpers.
- Existing helper patterns in `tests/integration/test_llm_turn.py` should be reused to avoid duplicate runtime setup logic.
- Changes should preserve existing test markers (`real_llm`, `acceptance`) and existing suite structure.
