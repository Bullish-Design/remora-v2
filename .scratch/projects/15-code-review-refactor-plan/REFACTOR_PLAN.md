# Refactor Plan — Code Review Remediation

## Table of Contents

1. Scope and Inputs
2. Prioritization Model
3. Phased Execution Plan
4. Core Recommendation Backlog (R1-R15)
5. Demo Readiness Backlog (D1-D4)
6. Verification Strategy
7. Risks and Dependencies
8. Definition of Done

## 1. Scope and Inputs

- Source document: `.scratch/projects/14-code-review-and-demo/CODE_REVIEW.md`
- Mandatory scope: all consolidated recommendations in section 8 (15 total items)
- Additional scope: demo-readiness build recommendations in section 6

## 2. Prioritization Model

- P0 (Critical): runtime breakage / unusable core surface
- P1 (High): correctness, concurrency, maintainability risks
- P2 (Medium): feature gaps and performance improvements
- P3 (Low): cleanup and long-term maintainability

## 3. Phased Execution Plan

### Phase 1: Critical Runtime Fixes (P0)
- R1: fix broken `rewrite_self.pym` external binding.
- R2: wire LSP server startup into CLI (`remora lsp` and/or `start --lsp`).

### Phase 2: High-Risk Structural Fixes (P1)
- R3: decompose `Actor._execute_turn()`.
- R4: consolidate `agents` table ownership.
- R5: add bounded eviction for `_SCRIPT_CACHE`.
- R6: prevent concurrent reconcile on same file.

### Phase 3: Medium Feature/Behavior Improvements (P2)
- R7: make EventBus emission concurrent-safe for independent handlers.
- R8: add LSP `textDocument/didChange` support.
- R9: make graph layout deterministic/stable.
- R10: enforce request validation for node existence on `/api/chat`.

### Phase 4: Low-Priority Debt (P3)
- R11: define deprecation timeline for compatibility aliases.
- R12: simplify `_uri_to_path()`.
- R13: add provisioning fingerprinting to skip unchanged bundle sync.
- R14: fix `_stop_event()` task lifecycle management.
- R15: make tree-sitter default query root configurable.

### Phase 5: Demo Track (post core stabilization)
- D1-D4 from section 6 to support cursor-following companion demo.

## 4. Core Recommendation Backlog (R1-R15)

| ID | Priority | Recommendation | Planned Action | Primary Targets | Verification |
|---|---|---|---|---|---|
| R1 | P0 | `rewrite_self.pym` references missing `propose_rewrite` | Rename external usage to `apply_rewrite` and validate capabilities contract | `bundles/code-agent/tools/rewrite_self.pym`, externals tests | Grail runtime tool test for rewrite success |
| R2 | P0 | LSP server not started by CLI | Add `remora lsp` command and/or `start --lsp` integration | `src/remora/__main__.py`, LSP startup wiring | CLI integration test starts LSP path |
| R3 | P1 | `Actor._execute_turn()` too complex | Extract cohesive helpers (`_build_context`, `_resolve_tools`, `_run_llm_turn`, completion/error handlers) | `src/remora/core/actor.py` | Existing actor tests + new unit tests for extracted helpers |
| R4 | P1 | NodeStore/AgentStore table duplication | Assign single schema owner for `agents` table and remove duplicate create path | `src/remora/core/graph.py`, runtime init | Store initialization tests |
| R5 | P1 | `_SCRIPT_CACHE` leak risk | Add LRU/TTL cache bound and invalidation policy | `src/remora/core/grail.py` | Cache behavior unit tests (eviction + reuse) |
| R6 | P1 | Reconciler race on same file | Introduce per-file lock or dedupe queue for `_reconcile_file` | `src/remora/code/reconciler.py` | Concurrent reconciliation test |
| R7 | P2 | EventBus emits handlers sequentially | Use concurrent dispatch (`gather`) with isolation and ordering policy | `src/remora/core/events/bus.py` | EventBus concurrency and failure-isolation tests |
| R8 | P2 | Missing `textDocument/didChange` | Implement didChange handler and position tracking updates | `src/remora/lsp/server.py` | Expanded LSP tests covering didChange |
| R9 | P2 | Unstable web graph layout | Replace random seeding with deterministic init and tune update loop | `src/remora/web/static/index.html` | UI behavior check + deterministic layout assertion where feasible |
| R10 | P2 | `/api/chat` lacks node existence check | Validate `node_id` exists before dispatching chat event | `src/remora/web/server.py` | API test expects 404/400 for unknown node |
| R11 | P3 | Backward-compat alias sprawl | Create deprecation policy, warnings, and removal milestones | `src/remora/core/*`, docs/changelog | Deprecation tests and docs updates |
| R12 | P3 | `_uri_to_path()` redundancy | Remove duplicated prefix handling and keep one canonical path parse | `src/remora/lsp/server.py` | LSP URI parsing tests |
| R13 | P3 | Bundle reprovisioning on every reconcile | Add content fingerprint check before provisioning write | `src/remora/core/workspace.py`, `src/remora/code/reconciler.py` | Provisioning skip/rebuild tests |
| R14 | P3 | `_stop_event()` task leak | Store/cancel awaited stop task explicitly | `src/remora/code/reconciler.py` | Lifecycle/shutdown tests |
| R15 | P3 | Query root hardcoded | Add config for default tree-sitter query directory | `src/remora/code/discovery.py`, config model | Config loading + override tests |

## 5. Demo Readiness Backlog (D1-D4)

| ID | Priority | Recommendation | Planned Action | Primary Targets | Verification |
|---|---|---|---|---|---|
| D1 | Demo-P1 | Cursor focus tracking in LSP | Emit `CursorFocusEvent` from didChange/custom notification with node mapping | `src/remora/lsp/server.py`, event types | LSP event emission tests |
| D2 | Demo-P1 | LSP-to-web cursor bridge | Add `/api/cursor` API + SSE broadcast path for cursor focus | `src/remora/web/server.py`, SSE flow | API/SSE integration tests |
| D3 | Demo-P2 | Companion sidebar content | Add companion content endpoint and read from agent workspace artifacts | `src/remora/web/server.py`, workspace reads | Endpoint tests + smoke UI flow |
| D4 | Demo-P2 | VS Code integration | Build basic extension for cursor notifications and companion panel | extension workspace (new) | Manual demo script + basic extension tests |

## 6. Verification Strategy

- Follow TDD for each backlog item: failing test first, then implementation.
- Prefer module-local unit tests plus integration tests for cross-component behavior (CLI/LSP/SSE/reconciler concurrency).
- Preserve or improve existing coverage in actor, reconciler, grail, web, and LSP suites.

## 7. Risks and Dependencies

- R2 and R8 are prerequisites for meaningful D1 progress.
- R6 may change reconcile scheduling behavior; regression testing is mandatory.
- R7 introduces concurrency semantics; handler exception isolation rules must be explicit.
- D4 depends on stabilized cursor/event contracts from D1/D2.

## 8. Definition of Done

- All R1-R15 items implemented or explicitly waived with rationale in `DECISIONS.md`.
- Tests added/updated for each implemented item and suite remains green.
- `PROGRESS.md` reflects completion status by item/phase.
- `CONTEXT.md` updated with final summary and any deferred follow-ups.
