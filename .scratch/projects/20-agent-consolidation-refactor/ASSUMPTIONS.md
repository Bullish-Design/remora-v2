# Assumptions — 20-agent-consolidation-refactor

## Audience
- Junior developer following a step-by-step guide
- Has access to the full codebase and can run tests

## Constraints
- NO backwards compatibility — cleanest possible result
- NO shims, aliases, or backup paths
- All code and tests must be aligned to the new single-source-of-truth model
- `agent_id == node_id` invariant means the Agent table adds zero information

## Key Invariants
- NodeStore is the single source of truth for node/agent status
- `to_agent` as an event field name (AgentMessageEvent.to_agent) is unrelated to Node.to_agent() and must NOT be changed
- The agents table, AgentStore class, Agent model, and DiscoveredElement class are all pure deletion targets
