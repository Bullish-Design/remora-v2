# Context

- Project 55 is focused on technical due diligence and implementation guidance for embeddy local-model enablement impacts on remora-v2.
- Investigation covered:
  - remora service layer: `src/remora/core/services/search.py`
  - web route: `src/remora/web/routes/search.py`
  - CLI indexing flow: `src/remora/__main__.py` (`_index`)
  - tests/docs: `tests/unit/test_search.py`, `tests/unit/test_web_server.py`, `tests/integration/test_search_remote_backend.py`, `docs/HOW_TO_USE_REMORA.md`, `remora.yaml.example`
  - embeddy reference implementation in `.context/embeddy`
- Deliverable created: `EMBEDDY_EDITS_ANALYSIS.md` with necessity verdicts and clean implementation strategy.
- Deliverable created: `EMBEDDY_REFACTORING_GUIDE.md` with ordered, file-level implementation steps and validation matrix.
