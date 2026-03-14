# Plan

The plan follows the critical/high/medium/low priority ordering from section 8 of the alignment refactor review. Each step lists the files in scope and the actionable refactor sub-steps.

## Critical
1. **Expose the LSP server via the CLI (`C1`).**
   - Add a `remora lsp` command (or a `--lsp` flag under `remora start`) that initializes the runtime services and passes the resulting `AsyncDB`, `NodeStore`, `EventStore`, and workspace services to `remora.lsp.server.create_lsp_server`.
   - Ensure the CLI waits for the LSP server `serve()` future and wires in proper shutdown handling (cancel tasks, close DB, stop reconciler). `remora/__main__.py` and `lsp/__init__.py` must be updated accordingly.
   - Update documentation (README) and `remora.yaml.example` instructions to mention the new command.

## High Priority
2. **Simplify `Actor._execute_turn()` (`H1`).**
   - Extract helper methods from `_execute_turn()` in `src/remora/core/actor.py`: e.g., `_prepare_agent_state()`, `_build_prompt()`, `_run_kernel()`, `_finalize_turn()`.
   - Move bundle config loading and prompt assembly into dedicated functions so `_execute_turn()` orchestrates high-level flow only.
   - Update tests referencing `Actor._execute_turn()` behavior to use the new helpers if needed.
3. **Centralize table creation (`H2`).**
   - Remove the `agents` table creation SQL from `NodeStore.create_tables()` in `src/remora/core/graph.py` so `AgentStore.create_tables()` owns it.
   - Ensure runtime initialization still calls both `NodeStore.create_tables()` and `AgentStore.create_tables()` in the correct order.
4. **Fix `_SCRIPT_CACHE` leak (`H3`).**
   - Replace the module-level `_SCRIPT_CACHE` dict in `src/remora/core/grail.py` with an `@functools.lru_cache(maxsize=256)` decorated helper or an `LRUCache` class to bound memory usage.
   - Remove manual cache invalidation code since the decorator handles it.
5. **Prevent reconciler race conditions (`H4`).**
   - Introduce a per-path `asyncio.Lock` or `asyncio.BoundedSemaphore` in `src/remora/code/reconciler.py` to serialize `_reconcile_file()` executions for the same file.
   - Ensure `_run_reconcile()` (watch loop and `_on_content_changed`) acquire the lock before dispatching; release via `finally`.
6. **Remove `externals` parameter duplication in Grail tools (`H5`).**
   - Update `GrailTool.__init__()` and `discover_tools()` to accept only `capabilities`.
   - Update all call sites (e.g., `core/actor.py` bundle provisioning, tests) to pass `capabilities` explicitly.

## Medium Priority
7. **Improve `EventBus.emit()` concurrency (`M1`).**
   - Allow the event bus to fire handlers concurrently (e.g., gather tasks) while preserving ordering semantics where necessary.
   - Add configuration/ comments to describe whether handlers run sequentially or concurrently.
8. **Add `textDocument/didChange` handler (`M2`).**
   - Implement `didChange` in `src/remora/lsp/server.py` (or equivalent) to parse the new document text, trigger a reconciler update (via events), and respond with diagnostics.
9. **Stabilize web layout (`M3`).**
   - Switch the Sigma rendering pipeline to deterministic initial positions (e.g., hierarchical/grid).
   - Document any new config (e.g., `SIGMA_ITERATIONS`) in `web/static/index.html`.
10. **Validate `/api/chat` requests (`M4`).**
    - Update `src/remora/web/server.py` `/api/chat` handler to check that `node_store.get_node(node_id)` returns a node and return 404 otherwise.
    - Add tests in `tests/unit/test_web_server.py` covering invalid node IDs.
11. **Track `_stop_event()` tasks (`M5`).**
    - Store the `asyncio.Task` created for `_stop_event()` in both `FileReconciler` and `remora/__main__.py` (wherever the pattern exists).
    - Cancel the task during shutdown to avoid leaks.

## Low Priority
12. **Fix `_uri_to_path()` redundancy (`L1`).**
    - Consolidate URI parsing in the LSP helper to a single `urlparse` pass, removing the duplicate `removeprefix` call.
13. **Avoid redundant bundle provisioning (`L2`).**
    - Hash each template directory’s fingerprints and skip provisioning if the agent’s workspace already has matching hashes.
    - Store the last provisioning hash in KV (e.g., `_bundle/metadata.json` or agent workspace KV store) so future reconciles can compare.
14. **Update reconciler comment (`L3`).**
    - Reword the comment around subscription re-registration to describe consistency rather than migration.
15. **Rename `code_node` local variable (`L4`).**
    - In `src/remora/code/projections.py`, rename the `code_node` variable to `node` and adjust any references accordingly.
16. **Cache `LanguageRegistry` (`L5`).**
    - Modify `code/discovery.py` to reuse a singleton or injected `LanguageRegistry` instead of instantiating a new one per `discover()` call.
    - Provide tests that reuse the registry to ensure no regressions.

## Validation
- Run `uv run pytest tests/` after the above refactors are implemented to ensure the entire suite still passes.
- Manually verify `remora start` can optionally launch the LSP server and that the web API + SSE behave as expected.
