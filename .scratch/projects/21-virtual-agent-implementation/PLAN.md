# Plan — 21-virtual-agent-implementation

**ABSOLUTE RULE: NO SUBAGENTS (Task tool). Do ALL work directly.**

## Goal
Implement virtual agents as first-class nodes declared via config, with runtime bootstrap, subscriptions, prompt behavior, and real integration verification against `remora-server:8000`.

## Steps
1. Add config schema for `virtual_agents` and subscription declarations.
2. Extend `NodeType` with `VIRTUAL`.
3. Add reconciler bootstrap for virtual nodes + declarative subscriptions.
4. Update actor prompt construction for virtual node role framing.
5. Add/extend bundles and sample config as needed.
6. Add tests (config, reconciler, actor, integration) for virtual agent behavior.
7. Run full tests and real vLLM-backed integration tests.
8. Commit and push.

## Acceptance
- Virtual nodes are persisted in `nodes` with type `virtual`.
- Virtual subscriptions are registered and match events via dispatcher.
- Virtual actors execute turns with role-oriented prompt flow.
- Real integration tests run against `http://remora-server:8000/v1` and pass.

**REMINDER: NO SUBAGENTS. Do ALL work directly.**
