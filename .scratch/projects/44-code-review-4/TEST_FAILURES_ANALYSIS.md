# Test Failures Analysis Report

**Date:** 2026-03-18  
**Issue:** 4 test failures after Phase 4 (Extract HumanInputBroker) implementation  
**Status:** ✅ FIXED

---

## Summary

All 4 test failures were caused by **test mocks not being updated** to match the new signatures introduced in Phase 4 (Extract HumanInputBroker from EventStore). The production code was correct; only the test fixtures needed updating.

---

## Root Cause

Phase 4 of the refactoring guide successfully introduced `HumanInputBroker` as a separate service, but the test mocks were not updated to include the new `broker` parameter:

1. **`ActorPool.__init__()`** now accepts `broker: HumanInputBroker | None = None`
2. **`WebDeps`** dataclass now requires `human_input_broker: HumanInputBroker` field

The test mocks (`_DummyActorPool` and `WebDeps` instantiation) were still using the old signatures.

---

## Issues Fixed

### Issue 1: `_DummyActorPool` Missing `broker` Parameter

**File:** `tests/unit/test_services.py:63-78`  
**Tests affected:**
- `test_runtime_services_search_disabled`
- `test_runtime_services_search_enabled`

**Error:**
```
TypeError: _DummyActorPool.__init__() got an unexpected keyword argument 'broker'
```

**Fix:** Added `broker=None` parameter to `_DummyActorPool.__init__()`:
```python
def __init__(
    self,
    event_store,
    node_store,
    workspace_service,
    config,
    *,
    dispatcher=None,
    metrics=None,
    search_service=None,
    broker=None,  # ← Added
) -> None:
    del event_store, node_store, workspace_service, config, dispatcher, metrics, broker
    type(self).last_search_service = search_service
```

### Issue 2: `WebDeps` Missing `human_input_broker`

**File:** `tests/unit/test_web_decomposition.py:31-41, 51-61`  
**Tests affected:**
- `test_get_chat_limiter_reuses_per_ip`
- `test_chat_limiter_evicts_oldest_when_capacity_reached`

**Error:**
```
TypeError: WebDeps.__init__() missing 1 required positional argument: 'human_input_broker'
```

**Fix:** 
1. Added import: `from remora.core.services.broker import HumanInputBroker`
2. Added `human_input_broker=HumanInputBroker()` to `WebDeps` instantiation:
```python
deps = WebDeps(
    event_store=SimpleNamespace(),
    node_store=SimpleNamespace(),
    event_bus=SimpleNamespace(),
    human_input_broker=HumanInputBroker(),  # ← Added
    metrics=None,
    actor_pool=None,
    workspace_service=None,
    search_service=None,
    shutdown_event=asyncio.Event(),
    chat_limiters={},
)
```

---

## Verification

### Before Fix
```
FAILED tests/unit/test_services.py::test_runtime_services_search_disabled
FAILED tests/unit/test_services.py::test_runtime_services_search_enabled  
FAILED tests/unit/test_web_decomposition.py::test_get_chat_limiter_reuses_per_ip
FAILED tests/unit/test_web_decomposition.py::test_chat_limiter_evicts_oldest_when_capacity_reached

4 failed, 378 passed, 5 skipped
```

### After Fix
```
✅ All 4 tests PASSED
✅ Full test suite: 382 passed, 5 skipped, 0 failed
```

---

## Files Modified

1. **`tests/unit/test_services.py`**
   - Added `broker=None` parameter to `_DummyActorPool.__init__()`
   - Added `broker` to the `del` statement to suppress unused variable warnings

2. **`tests/unit/test_web_decomposition.py`**
   - Added import: `from remora.core.services.broker import HumanInputBroker`
   - Added `human_input_broker=HumanInputBroker()` to both `WebDeps` instantiations

---

## Key Insight

This is a **classic symptom of Phase 4 done right**:

1. ✅ The production code correctly separates `HumanInputBroker` from `EventStore`
2. ✅ Dependency injection properly threads `HumanInputBroker` through `RuntimeServices`
3. ✅ The `ActorPool` and `WebDeps` correctly require `broker` as a parameter
4. ⚠️ Test mocks lagged behind the signature changes

The fact that only test mocks broke (not production code) validates that Phase 4 was implemented correctly in the core architecture.

---

## Recommendation

**No further action required.** The test fixes are minimal and surgical - they only update the test fixtures to match the new signatures. No production code changes needed.

The test failures were expected growing pains from Phase 4, not indicators of architectural problems.

---

**Analysis completed:** 2026-03-18  
**Status:** ✅ RESOLVED - All tests passing
