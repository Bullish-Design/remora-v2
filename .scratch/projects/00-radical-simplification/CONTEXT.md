# Context

## Current State
- Phases 0 through 8 are implemented and passing in the `remora-v2` repo.
- Phase 5 complete:
  - `src/remora/code/discovery.py` with immutable `CSTNode`, file walking, language detection, and Python discovery.
  - `src/remora/code/projections.py` with hash-based upsert/update behavior and bundle provisioning for new nodes.
  - `src/remora/code/reconciler.py` with startup reconciliation, default subscription registration, and discovery event emission.
  - `bundles/code-agent/bundle.yaml` and code tools (`rewrite_self.pym`, `scaffold.pym`).
  - Tests: discovery/projections/reconciler/code-tools checklist fully implemented.
- Phase 6 complete:
  - `src/remora/web/server.py` with Starlette routes for nodes, edges, chat, events, SSE, approve/reject.
  - `src/remora/web/views.py` with `GRAPH_HTML` including Sigma/graphology graph rendering, SSE client, chat/proposal UI wiring.
  - `bundles/companion/bundle.yaml` and companion tools (`summarize.pym`, `categorize.pym`, `find_links.pym`, `reflect.pym`).
  - Tests: web server, SSE, view HTML checks, companion tools checklist fully implemented.
- Validation:
  - Phase 5 + 6 targeted tests: 30 passed.
  - Full suite: 118 passed.
  - Lint: `ruff check src/ tests/` passed.
- Phase 7 complete:
  - Replaced CLI implementation with Typer in `src/remora/__main__.py`:
    - `remora start` with `--project-root`, `--config`, `--port`, `--no-web`
    - `--run-seconds` smoke-run control for deterministic startup/shutdown tests
    - `remora discover` command for discovery-only summaries
  - Implemented `src/remora/lsp/server.py`:
    - `create_lsp_server(node_store, event_store, runner)`
    - code lens, hover, did_save, did_open handlers
    - helper mappers and line resolution utilities
  - Added Phase 7 tests:
    - `tests/unit/test_cli.py`
    - `tests/unit/test_lsp_server.py`
- Phase 8 complete:
  - Added integration tests:
    - `tests/integration/test_e2e.py`
      - source discovery/projection/reconcile pipeline
      - human chat -> trigger -> runner turn -> rewrite proposal -> approve flow
      - agent-to-agent message trigger chain
      - content-change trigger flow
    - `tests/integration/test_performance.py`
      - 100+ node discovery latency check
      - 100 node upsert latency check
      - subscription matching throughput check
  - Phase 8 tests all passing with existing architecture.

## All Decisions Finalized
1. **Core identity**: General graph agent runner with code as primary built-in plugin
2. **Grail scope**: Push all agent behaviors into .pym tools; Python provides only primitives
3. **Cairn**: Core functionality — every agent node has its own Cairn workspace
4. **Host modes**: All survive, companion mode via web UI
5. **Node model**: CodeNode stays rich and typed (always tree-sitter parsed)
6. **Agent config**: bundle.yaml in workspace — agents own their config
7. **Execution paths**: One runner for everything
8. **Event types**: Consolidated, pydantic models
9. **Extension config**: Folded into remora.yaml
10. **structured_agents**: Keep and lean on it (+ cairn, grail)
11. **Graph viz**: Most performant option (WebGL — Sigma.js/graphology likely)
12. **Tree-sitter**: Stays in Python, core functionality
13. **Bundle resolution**: BUNDLE-IN-WORKSPACE — template copied into Cairn workspace on first discovery, agent owns it from there
14. **Implementation**: GREENFIELD in new repository

## Implementation Order
Phase 1: Foundation (config, node, events, graph, kernel)
Phase 2: Workspace + Externals (cairn, grail, externals builder)
Phase 3: Runner (single AgentRunner, system .pym tools)
Phase 4: Code plugin (discovery, reconciler, projections)
Phase 5: Web surface (SSE, graph viz, companion)
Phase 6: CLI + LSP (optional thin adapters)

## Next Pending Work
- None in plan phases 0-8. Implementation plan is complete.
