# Context — 20-agent-consolidation-refactor

## Current State
The guide has been fully implemented. Runtime now uses NodeStore as the single source of truth for node/agent lifecycle and status.

## What Was Done
- Deleted `AgentStore`, `Agent`, and `DiscoveredElement`
- Removed all `agent_store` wiring from actor/runtime/reconciler/services paths
- Deleted `tests/unit/test_agent_store.py`
- Updated all affected unit/integration fixtures and constructors
- Ran full tests and audit grep checks
- Added separate concept doc describing a clean virtual-agent layer on top of consolidated nodes

## What's Next
This project is complete. The follow-on design work is implementing the virtual-agent layer described in `VIRTUAL_AGENT_CONCEPT.md`.
