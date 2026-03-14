# Decisions — 21-virtual-agent-implementation

## D1: Declarative virtual agents are reconciler-managed state
Virtual agents are created/updated/removed from `Config.virtual_agents` in `FileReconciler.reconcile_cycle()`.

Rationale:
- Keeps lifecycle management in one place (same system that reconciles node graph state).
- Avoids introducing new services/tables.
- Ensures idempotent startup and ongoing config alignment.

## D2: Virtual subscriptions always include direct addressing
Each virtual node receives a default `to_agent=<node_id>` subscription plus declared patterns.

Rationale:
- Preserves direct messaging semantics common to all agents.
- Enables both targeted and reactive routing for virtual agents.
