# Context — Companion Integration

## Current State
Comparison analysis complete at `APPROACH_COMPARISON.md` with 9 sections + Appendix A.

Appendix A explores four first-principles observer designs (A-D).

CONCEPT.md expands Designs A, C, and A+C in detail:
- Design A: Self-directed companion (~183 lines). Self-subscription via bundle config, tag-based loop prevention, KV-native companion tools, reflection prompt, system prompt injection.
- Design C: Scoped delegation (~206 lines). WorkspaceDelegation config model, delegated_kv_set/get on TurnContext, not_from_agents subscription filter, observer bundle, AgentCompleteEvent enrichment with user_message.
- A+C Combined (~230 lines). Layer 1 = self-directed per-agent reflection. Layer 2 = observer subscribes to TurnDigestedEvent for cross-agent analysis. No cross-workspace writes needed in combined design (observer reads events, writes to own workspace).

Key insight: The combined design eliminates Design C's biggest problem (cross-workspace writes) while adding cross-agent intelligence that Design A alone can't provide.

Awaiting user review and approach decision before writing the implementation plan.

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
