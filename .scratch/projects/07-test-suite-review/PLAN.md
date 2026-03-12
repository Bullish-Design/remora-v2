# Plan

## Project Goal
Thoroughly review the test suite and identify gaps where mocks provide false confidence. Ensure key functionality is tested as it will be used.

---

## Phase 1: Add Missing Unit Tests [HIGH PRIORITY]

- [ ] Create `tests/unit/test_kernel.py`
  - [ ] Test `create_kernel()` with all parameter combinations
  - [ ] Test `extract_response_text()` with various result types
  - [ ] Test kernel timeout configuration
- [ ] Add status state machine exhaustive tests
- [ ] Add semaphore/concurrent execution tests

## Phase 2: Add Integration Tests [HIGH PRIORITY]

- [ ] Create `tests/integration/test_grail_integration.py`
  - [ ] Real Grail script execution with real externals
  - [ ] Tool discovery from actual `.pym` files
  - [ ] Error handling in script execution
- [ ] Create `tests/integration/test_llm_integration.py` (optional, requires API key)
  - [ ] Real kernel call with simple prompt
  - [ ] Timeout handling with real LLM
  - [ ] Tool schema generation verification

## Phase 3: Improve Test Organization [MEDIUM PRIORITY]

- [ ] Add pytest markers (unit, integration, e2e, slow, requires_llm)
- [ ] Add contract tests for mock classes
- [ ] Add coverage reporting configuration
- [ ] Document test categories in README

## Phase 4: Add Error Path Tests [MEDIUM PRIORITY]

- [ ] LLM timeout handling
- [ ] LLM rate limiting
- [ ] Tool execution failure propagation
- [ ] Workspace write failures
- [ ] SQLite lock contention

---

## Key Decisions

1. **Prioritize real execution tests** — Add integration tests that call real Grail scripts, not mocks
2. **Keep mocks for unit tests** — Unit tests should remain fast and isolated
3. **Add markers for categorization** — Allow running "fast unit" vs "slow integration" separately
4. **Contract tests for mocks** — Ensure mocks stay in sync with real implementations

---

## IMPORTANT

**NO SUBAGENTS.** Do all work directly — read files, search, write, edit, run commands. No delegation.

**ALWAYS CONTINUE.** Do not stop after compaction. Resume from CONTEXT.md and PROGRESS.md immediately.
