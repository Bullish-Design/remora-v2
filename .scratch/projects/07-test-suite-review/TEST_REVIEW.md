# Test Suite Review

## Executive Summary

The remora-v2 test suite contains **163 tests** across **30 test files**. All tests pass. The suite provides good coverage of individual components but has significant gaps in integration testing and relies heavily on mocking for the most critical execution paths.

**Key Concern:** The test suite gives a false sense of confidence. Core agent execution paths (kernel calls, LLM interactions, tool execution) are heavily mocked, meaning the actual "agent running" behavior is never tested end-to-end against a real LLM.

---

## Part 1: Test Suite Inventory

### 1.1 Test File Distribution

| Directory | Files | Tests | Purpose |
|-----------|-------|-------|---------|
| `tests/unit/` | 27 | ~150 | Unit tests for individual components |
| `tests/integration/` | 2 | 6 | E2E and performance tests |
| `tests/` | 2 | 0 | Fixtures and factories |
| **Total** | **31** | **163** | |

### 1.2 Unit Test Coverage by Module

| Module | Test File | Tests | Coverage Quality |
|--------|-----------|-------|------------------|
| `core/actor.py` | `test_actor.py` | 13 | Good — tests actor lifecycle, outbox, cooldown |
| `core/runner.py` | `test_runner.py` | 7 | Fair — tests routing, not actual execution |
| `core/externals.py` | `test_externals.py` | 9 | Good — tests all external functions |
| `core/graph.py` | `test_graph.py` | 11 | Good — covers NodeStore operations |
| `core/workspace.py` | `test_workspace.py` | 12 | Good — tests workspace operations and layering |
| `core/events/` | `test_event_store.py`, `test_event_bus.py`, `test_subscription_registry.py` | ~15 | Good — covers event flow |
| `core/grail.py` | `test_grail.py` | 6 | Fair — uses stubs for scripts |
| `core/config.py` | `test_config.py` | 6 | Good — covers loading and validation |
| `core/node.py` | `test_node.py` | 4 | Minimal — only creation and roundtrip |
| `core/kernel.py` | `test_kernel.py` | ? | **MISSING FILE** — no tests for kernel wrapper |
| `code/discovery.py` | `test_discovery.py` | 12 | Good — tests all languages and edge cases |
| `code/reconciler.py` | `test_reconciler.py` | 8 | Good — tests reconciliation flow |
| `code/projections.py` | `test_projections.py` | 4 | Minimal |
| `code/languages.py` | `test_languages.py` | 3 | Minimal |
| `web/server.py` | `test_web_server.py` | 11 | Good — tests API endpoints |
| `lsp/server.py` | `test_lsp_server.py` | 3 | Minimal |
| `__main__.py` | `test_cli.py` | ? | CLI tests |

### 1.3 Integration Test Coverage

| Test File | Tests | Scope |
|-----------|-------|-------|
| `test_e2e.py` | 3 | E2E human chat → rewrite flow |
| `test_performance.py` | 3 | Performance benchmarks |

---

## Part 2: Mocking Analysis

### 2.1 Mocking Patterns Found

| Pattern | Count | Location | What's Mocked |
|---------|-------|----------|---------------|
| `monkeypatch.setattr` | 12 | Multiple files | Functions, modules, imports |
| `MockKernel` class | 2 | `test_e2e.py`, `test_actor.py` | Entire LLM kernel |
| `FakeRewriteTool` class | 1 | `test_e2e.py` | Tool execution |
| `_WorkspaceStub` class | 1 | `test_grail.py` | Workspace filesystem |
| `ScriptStub` class | 2 | `test_grail.py` | Grail script execution |
| `SimpleNamespace` | 3 | Multiple | Fake objects |

### 2.2 Critical Paths That Are Mocked

#### 2.2.1 LLM Kernel Execution

**Location:** `test_e2e.py:120-139`, `test_actor.py:179-188`

```python
class MockKernel:
    async def run(self, messages, tool_schemas, max_turns=8):
        # Returns fake response without calling LLM
        return SimpleNamespace(final_message=Message(role="assistant", content="ok"))

monkeypatch.setattr("remora.core.actor.create_kernel", lambda **kwargs: MockKernel())
```

**Problem:** The entire LLM interaction is bypassed. No test verifies:
- Correct prompt construction
- Tool schema generation
- Response parsing
- Token limits
- Timeout handling
- Error recovery from LLM failures

#### 2.2.2 Tool Discovery and Execution

**Location:** `test_e2e.py:170-173`, `test_actor.py:188`

```python
async def fake_discover_tools(_workspace, externals):
    return [FakeRewriteTool(externals)]

monkeypatch.setattr("remora.core.actor.discover_tools", fake_discover_tools)
```

**Problem:** Real Grail tool parsing and execution is bypassed. No test verifies:
- Tool discovery from `.pym` files
- External injection
- Script compilation
- Runtime errors in tools

#### 2.2.3 watchfiles Integration

**Location:** `test_reconciler.py:158-169`

```python
async def fake_awatch(*_args, **_kwargs):
    yield {(1, str(source))}
    yield {(1, str(source))}

monkeypatch.setitem(sys.modules, "watchfiles", SimpleNamespace(awatch=fake_awatch))
```

**Problem:** Filesystem watching is mocked. No test verifies:
- Real file change detection
- Platform-specific behavior
- watchfiles library integration

### 2.3 What IS Tested Without Mocking

| Component | Real Test | Verified Behavior |
|-----------|-----------|-------------------|
| SQLite operations | ✅ Yes | All NodeStore, EventStore, AgentStore operations |
| Workspace filesystem | ✅ Yes | Cairn workspace read/write/exists |
| Tree-sitter discovery | ✅ Yes | Real parsing with actual grammars |
| Event routing | ✅ Yes | EventBus, SubscriptionRegistry |
| HTTP API | ✅ Yes | Starlette endpoints via httpx |
| Reconciliation flow | ✅ Yes | File scanning, projection, events |

---

## Part 3: Gap Analysis

### 3.1 Missing Tests

| Gap | Severity | Impact |
|-----|----------|--------|
| **No kernel.py tests** | HIGH | Kernel creation and response extraction untested |
| **No real LLM calls** | HIGH | Core functionality never tested end-to-end |
| **No Grail tool execution tests** | HIGH | Tools never execute against real scripts |
| **No status state machine tests** | MEDIUM | Status transitions not exhaustively tested |
| **No concurrent execution tests** | MEDIUM | Semaphore behavior untested |
| **No error path tests for LLM** | MEDIUM | LLM failures not tested |
| **No timeout tests** | MEDIUM | Timeout handling untested |
| **No LSP integration tests** | LOW | LSP tested in isolation only |
| **No config hot-reload tests** | LOW | (Feature doesn't exist) |

### 3.2 Tests That Give False Confidence

#### `test_e2e_human_chat_to_rewrite`

**Claim:** Tests "human chat → rewrite → approval" flow
**Reality:** Mocks kernel, tools, and rewrite execution. Only tests:
- Event routing
- Actor instantiation
- Fixture setup

The actual rewrite logic (byte-based patching) IS tested elsewhere (`test_apply_rewrite_duplicate_source_blocks`), but the integration with LLM decision-making is completely mocked.

#### `test_actor_processes_inbox_message`

**Claim:** Tests actor message processing
**Reality:** Mocks kernel and tools. Only tests:
- Actor lifecycle
- Status transitions
- Event emission

### 3.3 Untested Error Paths

| Error Condition | Tested? | Risk |
|-----------------|---------|------|
| LLM API failure | ❌ No | Agent hangs or crashes ungracefully |
| LLM timeout | ❌ No | Timeout handling untested |
| LLM rate limiting | ❌ No | No retry logic tested |
| Tool execution failure | Partial | Only in `test_grail_tool_error_handling` |
| Malformed tool response | ❌ No | Parsing errors unhandled |
| Workspace write failure | ❌ No | Disk full, permissions |
| SQLite lock contention | ❌ No | Concurrent access behavior unknown |
| OOM during large file parse | ❌ No | Memory exhaustion |

---

## Part 4: Test Quality Assessment

### 4.1 Good Patterns

1. **Real database testing** — Uses actual SQLite, not mocks
2. **Real filesystem testing** — Uses `tmp_path` fixtures, not memory mocks
3. **Real tree-sitter parsing** — Tests with actual source code
4. **Good fixture organization** — Reusable fixtures in `conftest.py` and `factories.py`
5. **Async test support** — Proper use of `pytest-asyncio`

### 4.2 Anti-Patterns

1. **Over-mocking at boundaries** — Core execution is mocked, edges are tested
2. **No contract testing** — Mocks don't verify they match real implementations
3. **Stub classes duplicate interfaces** — `MockKernel` could diverge from real `AgentKernel`
4. **No test markers** — Missing `@pytest.mark.integration` or `@pytest.mark.e2e`
5. **No test categories** — Can't run "fast unit tests only" vs "slow integration tests"

### 4.3 Test Coverage Metrics (Estimated)

| Category | Coverage | Notes |
|----------|----------|-------|
| Storage layer | ~90% | Well tested |
| Event system | ~85% | Well tested |
| Discovery | ~80% | Good coverage |
| Workspace | ~75% | Good coverage |
| Web API | ~70% | Good coverage |
| Runner/Actor | ~40% | Heavily mocked |
| Kernel | ~10% | Almost untested |
| Grail tools | ~30% | Stubs used |
| E2E flows | ~20% | Mocked execution |

---

## Part 5: Recommendations

### 5.1 Tier 1: Add Real Integration Tests (HIGH PRIORITY)

#### R1. Add LLM Integration Test Suite

Create `tests/integration/test_llm_integration.py`:

```python
@pytest.mark.integration
@pytest.mark.skipif(not os.getenv("REMORA_TEST_API_KEY"), reason="No API key")
async def test_real_kernel_call():
    """Test actual LLM kernel execution with a simple prompt."""
    config = load_test_config()
    kernel = create_kernel(
        model_name=config.model_default,
        base_url=config.model_base_url,
        api_key=config.model_api_key,
        timeout=30.0,
    )
    messages = [Message(role="user", content="Say 'hello world'")]
    result = await kernel.run(messages, [], max_turns=1)
    await kernel.close()
    assert "hello" in extract_response_text(result).lower()
```

#### R2. Add Grail Tool Integration Tests

Create `tests/integration/test_grail_integration.py`:

```python
@pytest.mark.integration
async def test_real_grail_tool_execution():
    """Test Grail script execution with real externals."""
    workspace = await create_test_workspace()
    await workspace.write("_bundle/tools/echo.pym", """
from grail import Input, external
message: str = Input("message")
@external
async def send_message(to_node_id: str, content: str) -> bool: ...
result = await send_message("target", message)
return result
""")
    externals = {"send_message": lambda to, content: f"sent: {content}"}
    tools = await discover_tools(workspace, externals)
    assert len(tools) == 1
    result = await tools[0].execute({"message": "hello"}, None)
    assert "sent: hello" in result.output
```

#### R3. Add E2E Flow with Real Components

```python
@pytest.mark.e2e
@pytest.mark.skipif(not os.getenv("REMORA_TEST_API_KEY"), reason="No API key")
async def test_full_agent_turn_with_real_llm():
    """Complete agent turn from event to completion with real LLM."""
    # Set up real runtime
    # Send HumanChatEvent
    # Wait for AgentCompleteEvent
    # Verify response is coherent
```

### 5.2 Tier 2: Improve Test Organization (MEDIUM PRIORITY)

#### R4. Add Test Markers

Create `pyproject.toml` additions:

```toml
[tool.pytest.ini_options]
markers = [
    "unit: Fast unit tests with no external dependencies",
    "integration: Tests that use real databases/filesystems",
    "e2e: End-to-end tests requiring external services",
    "slow: Tests that take >1 second",
    "requires_llm: Tests that need LLM API access",
]
```

#### R5. Add `kernel.py` Tests

Create `tests/unit/test_kernel.py`:

```python
def test_create_kernel_default_params():
    kernel = create_kernel(
        model_name="test-model",
        base_url="http://localhost:8000",
        api_key="test-key",
    )
    assert kernel is not None

def test_extract_response_text_with_final_message():
    result = SimpleNamespace(final_message=Message(role="assistant", content="Hello"))
    assert extract_response_text(result) == "Hello"

def test_extract_response_text_fallback():
    result = SimpleNamespace()
    assert extract_response_text(result) == str(result)
```

#### R6. Add Contract Tests for Mocks

Ensure mock implementations match real interfaces:

```python
def test_mock_kernel_matches_real_kernel():
    """Verify MockKernel implements same interface as AgentKernel."""
    import inspect
    from structured_agents import AgentKernel
    
    mock_methods = set(dir(MockKernel))
    real_methods = set(dir(AgentKernel))
    
    # Check all public methods exist
    for method in ["run", "close"]:
        assert method in mock_methods
```

### 5.3 Tier 3: Test Error Paths (MEDIUM PRIORITY)

#### R7. Add Error Scenario Tests

```python
@pytest.mark.asyncio
async def test_kernel_timeout_handling():
    """Test that kernel timeout is properly handled."""
    config = Config(timeout_s=0.001)  # Very short timeout
    # Expect timeout error or graceful handling

@pytest.mark.asyncio  
async def test_llm_rate_limiting():
    """Test behavior when LLM rate limits."""
    # Mock 429 response, verify retry or error handling

@pytest.mark.asyncio
async def test_tool_execution_failure_propagates():
    """Test that tool failures are properly reported."""
    # Tool raises exception, verify error event is emitted
```

### 5.4 Tier 4: Test Infrastructure (LOW PRIORITY)

#### R8. Add Test Fixtures for LLM Testing

```python
# tests/conftest.py
@pytest.fixture
def llm_config():
    """Load config with test API key from environment."""
    api_key = os.getenv("REMORA_TEST_API_KEY")
    if not api_key:
        pytest.skip("REMORA_TEST_API_KEY not set")
    return Config(
        model_api_key=api_key,
        model_base_url=os.getenv("REMORA_TEST_BASE_URL", "http://localhost:8000/v1"),
    )

@pytest.fixture
async def test_workspace(tmp_path):
    """Create a workspace with test bundles."""
    # Copy test bundles to workspace
    # Provision for test node
```

#### R9. Add Coverage Reporting

```bash
# Run with coverage
devenv shell -- pytest tests/ --cov=remora --cov-report=html --cov-report=term-missing
```

#### R10. Add Mutation Testing

Consider using `mutmut` to verify tests catch real bugs:

```bash
mutmut run --paths-to-mutate src/remora/
```

---

## Part 6: Recommended Test Suite Additions

### 6.1 Critical Tests to Add

| Test | Priority | Effort | Impact |
|------|----------|--------|--------|
| Real LLM call test | HIGH | Small | Validates core functionality |
| Real Grail execution test | HIGH | Small | Validates tool system |
| Full E2E with real LLM | HIGH | Medium | Validates entire flow |
| Kernel creation test | HIGH | Trivial | Basic coverage |
| Status state machine test | MEDIUM | Small | Prevents C1 bug |
| Timeout handling test | MEDIUM | Small | Error path coverage |
| Concurrent execution test | MEDIUM | Medium | Semaphore behavior |

### 6.2 Test File Structure Proposal

```
tests/
├── conftest.py                    # Shared fixtures
├── factories.py                   # Test data factories
├── unit/                          # Fast unit tests (mocked boundaries)
│   ├── test_actor.py
│   ├── test_config.py
│   ├── test_discovery.py
│   ├── test_event_bus.py
│   ├── test_event_store.py
│   ├── test_externals.py
│   ├── test_grail.py
│   ├── test_graph.py
│   ├── test_kernel.py             # NEW
│   ├── test_languages.py
│   ├── test_lsp_server.py
│   ├── test_node.py
│   ├── test_projections.py
│   ├── test_reconciler.py
│   ├── test_runner.py
│   ├── test_subscription_registry.py
│   ├── test_web_server.py
│   └── test_workspace.py
├── integration/                   # Real component tests
│   ├── test_e2e.py
│   ├── test_performance.py
│   ├── test_grail_integration.py  # NEW
│   └── test_llm_integration.py    # NEW
└── contracts/                     # Mock contract tests
    └── test_mock_contracts.py     # NEW
```

---

## Part 7: Summary

### Current State

- **163 tests, all passing**
- Good coverage of storage, events, discovery, workspace
- Weak coverage of kernel, LLM interaction, tool execution
- Heavy mocking creates false confidence

### Key Risks

1. **No test verifies LLM actually works** — Could ship with broken kernel
2. **No test verifies tools execute correctly** — Could ship with broken Grail integration
3. **Mock divergence** — Mocks may not match real implementation
4. **Error paths untested** — Failures may crash instead of graceful handling

### Priority Actions

1. Add `test_kernel.py` with basic tests (trivial effort)
2. Add LLM integration test with real API call (small effort)
3. Add Grail tool execution test with real script (small effort)
4. Add test markers for categorization (trivial effort)
5. Add error path tests (medium effort)

---

## Appendix: Test Count by Category

| Category | Count | Percentage |
|----------|-------|------------|
| Storage (NodeStore, EventStore) | 26 | 16% |
| Events (EventBus, Subscriptions) | 15 | 9% |
| Discovery (tree-sitter, languages) | 15 | 9% |
| Workspace (Cairn) | 12 | 7% |
| Runner/Actor | 20 | 12% |
| Externals | 9 | 6% |
| Config | 6 | 4% |
| Web API | 11 | 7% |
| LSP | 3 | 2% |
| Grail | 6 | 4% |
| E2E | 3 | 2% |
| Performance | 3 | 2% |
| Other | 34 | 21% |
| **Total** | **163** | **100%** |
