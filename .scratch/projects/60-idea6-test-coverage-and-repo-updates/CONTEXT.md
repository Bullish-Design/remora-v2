# Context — 60-idea6-test-coverage-and-repo-updates

User asked to create a new numbered project template directory and produce two detailed documents:
1. `TEST_COVERAGE_UPDATES.md` — concrete test coverage gaps/updates.
2. `REPO_UPDATES.md` — `remora-v2` library changes that should be implemented for the Idea #6 demo (including ongoing edge detection/reliability topics).

Current status:
- Project directory and standard files have been initialized.
- Authored `TEST_COVERAGE_UPDATES.md` with:
  - prioritized P0/P1 coverage gaps,
  - concrete new test cases by target file,
  - validation/CI commands and completion criteria.
- Authored `REPO_UPDATES.md` with:
  - required `remora-v2` P0 update for ongoing semantic edge backfill on target-only changes,
  - watch/content-change path parity requirements,
  - recommended API/observability enhancements (`/api/graph/stats`, `/api/graph/hotspots`, health metadata).

Key conclusion:
- For Idea #6 demo trust, the primary library behavior gap to implement is ongoing semantic edge detection/backfill when only target files change.
