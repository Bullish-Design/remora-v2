# Context — Companion Integration

## Current State
Comparison analysis complete at `APPROACH_COMPARISON.md`. Analyzed inline hooks vs virtual agent observer across 9 dimensions. Recommendation: inline hooks for Phase 1, optional observer for Phase 2 cross-agent features.

Awaiting user review and decision before proceeding to write the full implementation plan.

## Source Document
`.scratch/projects/31-companion-and-vector-integration/COMPANION_BRAINSTORMING.md`

## Key Files Studied
- `core/actor.py` — AgentTurnExecutor.execute_turn(), _complete_agent_turn(), PromptBuilder
- `core/externals.py` — TurnContext API, workspace sandboxing, KV methods
- `core/events/types.py` — AgentCompleteEvent (has full_response, lacks user_message)
- `core/events/dispatcher.py` — TriggerDispatcher.dispatch()
- `core/events/subscriptions.py` — SubscriptionPattern.matches(), from_agent matching
- `core/runner.py` — ActorPool, semaphore, _route_to_actor
- `core/services.py` — RuntimeServices container
- `core/config.py` — VirtualAgentConfig, Config
- `code/reconciler.py` — _sync_virtual_agents(), subscription registration
- `core/workspace.py` — AgentWorkspace KV methods
