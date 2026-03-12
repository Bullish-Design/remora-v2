# Context

## Status
Setup complete. Comprehensive test suite review written. Awaiting user direction.

## What Was Done
1. Created project directory: `.scratch/projects/07-test-suite-review/`
2. Analyzed all 30 test files and 163 tests
3. Identified mocking patterns and coverage gaps
4. Wrote comprehensive `TEST_REVIEW.md` with:
   - Test inventory by module
   - Mocking analysis (12 monkeypatch, 6 custom stub classes)
   - Gap analysis (no kernel tests, no real LLM calls, no real Grail execution)
   - Test quality assessment (good/bad patterns)
   - 10 recommendations with code examples
   - Proposed test file structure

## Key Findings

### Critical Gaps
1. **No `test_kernel.py`** — Kernel module has no tests at all
2. **No real LLM calls** — All LLM interaction is mocked via `MockKernel`
3. **No real Grail execution** — Tools tested via stubs, not actual scripts
4. **Error paths untested** — Timeouts, rate limits, failures not covered

### What IS Tested Well
- SQLite operations (real database, no mocks)
- Workspace filesystem (real Cairn workspaces)
- Tree-sitter discovery (real parsing)
- Event routing and subscriptions
- HTTP API endpoints

### Mock Usage
- `MockKernel` — Bypasses all LLM interaction
- `FakeRewriteTool` — Bypasses tool execution
- `_WorkspaceStub` — Bypasses workspace (but workspace tests use real)
- `ScriptStub` — Bypasses Grail script parsing

### False Confidence Tests
- `test_e2e_human_chat_to_rewrite` — Claims E2E but mocks kernel and tools
- `test_actor_processes_inbox_message` — Claims message processing but mocks execution

## Recommended Priority Actions
1. Add `test_kernel.py` (trivial effort)
2. Add Grail integration test with real scripts (small effort)
3. Add test markers for categorization (trivial effort)
4. Add error path tests (medium effort)

## Files Created
- `.scratch/projects/07-test-suite-review/TEST_REVIEW.md`
- `.scratch/projects/07-test-suite-review/PLAN.md`
- `.scratch/projects/07-test-suite-review/CONTEXT.md` (this file)
