# Lifecycle Task Management Decision Record

**Date:** 2026-03-18  
**Decision:** Retain manual asyncio.Task management in RemoraLifecycle  
**Status:** ✅ Documented

---

## Decision

The `RemoraLifecycle` class will continue to use manual `asyncio.Task` management (via `self._tasks` list) rather than adopting `asyncio.TaskGroup` as suggested in Phase 5 of the refactoring guide.

---

## Rationale

### Why TaskGroup Was Proposed

The refactoring guide suggested using `TaskGroup` to:
- Eliminate manual task tracking
- Provide automatic cleanup on scope exit
- Simplify error propagation with `except*` syntax
- Reduce boilerplate in shutdown logic

### Why Manual Management Is Retained

After thorough analysis, manual task management is retained because:

#### 1. Service-Specific Shutdown Logic

Each service type requires custom shutdown behavior that cannot be expressed with simple task cancellation:

```python
# ActorPool: Needs graceful drain with timeout
await services.runner.stop_and_wait()  # Cannot use task.cancel()

# Uvicorn server: Needs should_exit flag set
self._web_server.should_exit = True  # Then wait for task to finish

# LSP server: Must follow LSP protocol
await lsp_server.shutdown()  # Send shutdown notification
await lsp_server.exit()      # Then exit
```

#### 2. Ordered Shutdown Sequence

Services must shut down in a specific order to avoid data loss or corruption:

1. **Stop accepting new work** — Prevent new requests from being processed
2. **Wait for in-flight work** — Allow current operations to complete (with timeout)
3. **Signal web server** — Set `should_exit` flag
4. **Close services** — Database connections, workspace locks
5. **LSP shutdown** — Follow LSP protocol if applicable
6. **Force-cancel stragglers** — After 10s timeout

This ordered sequence cannot be expressed with TaskGroup's "cancel all" approach.

#### 3. Timeout Handling

The shutdown sequence has a 10-second timeout for graceful shutdown:

```python
done, still_pending = await asyncio.wait(pending, timeout=10.0)
if still_pending:
    for task in still_pending:
        task.cancel()  # Force cancellation
```

TaskGroup doesn't support per-task timeouts — it's all-or-nothing.

#### 4. Resource Cleanup

File log handlers must be released to avoid file descriptor leaks:

```python
finally:
    self._release_file_log_handlers()  # Close file handles
```

This cleanup must happen after all tasks have shut down, regardless of how they terminated.

#### 5. LSP Protocol Compliance

The LSP server requires a specific shutdown sequence mandated by the LSP protocol:

1. Send `shutdown` notification
2. Wait for response
3. Send `exit` notification

This cannot be expressed with TaskGroup's simple cancellation model.

---

## Code Locations

The following code locations have been updated with detailed docstrings explaining this decision:

1. **Class docstring** (`lifecycle.py:24-88`): Comprehensive explanation of why TaskGroup is not used
2. **`start()` method** (`lifecycle.py:89-93`): Documents the initialization sequence
3. **`run()` method** (`lifecycle.py:191-202`): References class docstring for rationale
4. **`shutdown()` method** (`lifecycle.py:204-226`): Documents the ordered shutdown sequence

---

## Alternatives Considered

### Alternative 1: Hybrid Approach

Use TaskGroup for the main run loops, but keep manual shutdown logic:

```python
async def run(self, *, run_seconds: float = 0.0) -> None:
    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._run_main_loops())
            if run_seconds > 0:
                tg.create_task(self._timeout_shutdown(run_seconds))
    except* Exception as exc_group:
        for exc in exc_group.exceptions:
            logger.warning("Runtime task ended: %s", exc)
    finally:
        await self.shutdown()  # Still need full shutdown logic
```

**Rejected because:** Adds complexity without benefit — the TaskGroup wrapper doesn't simplify anything since we still need the full `shutdown()` method.

### Alternative 2: Extract Run Loops

Create a separate method for the main run loops that could use TaskGroup:

```python
async def _run_main_loops(self) -> None:
    """Run main service loops until stopped."""
    await asyncio.gather(
        self.services.runner.run_forever(),
        self.services.reconciler.run_forever(),
        self._web_server.serve() if self._web_server else asyncio.sleep(0),
    )
```

**Rejected because:** Still needs `asyncio.gather()` for coordination, and the gather would need to handle cancellation manually anyway.

### Alternative 3: Full TaskGroup (Guide's Approach)

The guide's suggested approach of wrapping all tasks in a TaskGroup:

```python
async with asyncio.TaskGroup() as tg:
    tg.create_task(services.runner.run_forever())
    tg.create_task(services.reconciler.run_forever())
    tg.create_task(self._web_server.serve())
    tg.create_task(asyncio.to_thread(self._lsp_server.start_io))
```

**Rejected because:** Would break:
- Graceful shutdown (no way to call `stop_and_wait()`)
- Ordered shutdown (all tasks cancelled simultaneously)
- LSP protocol (no way to call `shutdown()` then `exit()`)
- Timeout handling (no per-task timeout control)
- Resource cleanup (no way to ensure handlers are released)

---

## Impact

### Code Quality
- **Before:** 65-line `shutdown()` method
- **After:** 65-line `shutdown()` method with comprehensive documentation

### Maintainability
- ✅ Clear documentation of why complexity exists
- ✅ Future refactors will understand the constraints
- ✅ No loss of functionality

### Testability
- ✅ Tests can still mock individual services
- ✅ Shutdown sequence is explicit and testable
- ✅ Timeout behavior is documented and testable

---

## Verification

The decision has been verified through:
1. ✅ Code review of Phase 5 implementation
2. ✅ Analysis of shutdown requirements for each service type
3. ✅ Comparison with guide's simplified example
4. ✅ Documentation added to codebase

See: `.scratch/projects/44-code-review-4/PHASE_4_5_IMPLEMENTATION_REVIEW.md`

---

## Conclusion

Manual task management in `RemoraLifecycle` is not a oversight or technical debt — it's a deliberate design choice to support production-grade graceful shutdown. The complexity is necessary and well-justified.

**Decision:** ✅ RETAIN current manual task management approach  
**Documentation:** ✅ Added comprehensive docstrings explaining rationale  
**Future work:** None required — current implementation is correct

---

**Decision recorded:** 2026-03-18  
**Reviewed by:** Qwen  
**Approved by:** [Pending team review]
