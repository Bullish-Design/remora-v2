# Plan — 20-agent-consolidation-refactor

**ABSOLUTE RULE: NO SUBAGENTS (Task tool). Do ALL work directly.**

## Overview
Consolidate Node/Agent into a single source of truth by deleting AgentStore, Agent model, and DiscoveredElement. Remove all dual-status coordination. Align all tests.

## Steps
See REFACTORING_GUIDE.md for the full 20-step implementation plan with exact before/after code.

### Phase 1: Delete models (Steps 1-2)
- Delete Agent, DiscoveredElement classes from node.py
- Delete AgentStore class from graph.py

### Phase 2: Update source files (Steps 3-7)
- Remove agent_store from actor.py, externals.py, runner.py, reconciler.py, services.py
- Simplify all dual-status coordination to NodeStore-only

### Phase 3: Update tests (Steps 8-17)
- Delete test_agent_store.py
- Update test_node.py, test_actor.py, test_externals.py, test_runner.py, test_reconciler.py
- Update integration tests (test_e2e.py, test_llm_turn.py)
- Update test_refactor_naming.py

### Phase 4: Verify (Steps 18-20)
- Clean up imports
- Run full test suite
- Final audit grep

**REMINDER: NO SUBAGENTS. Do ALL work directly.**
