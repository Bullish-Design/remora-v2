# Plan: Comprehensive Code Review

## Goal
Produce an exhaustive, honest code review of the remora-v2 codebase covering architecture,
code quality, correctness, testing, security, and maintainability.

## Approach
1. Use parallel subagents to deep-read all subsystems simultaneously
2. Synthesize findings into a single master REVIEW.md document
3. Organize by severity (critical → major → minor → nit)

## Subsystems to Review
- Core agents (actor, runner, turn, kernel, outbox, trigger, prompt)
- Storage (db, graph, workspace, transaction)
- Events (types, store, bus, dispatcher, subscriptions)
- Tools (context, capabilities, grail)
- Code discovery (reconciler, discovery, directories, virtual_agents, subscriptions, watcher)
- Web + LSP (server, sse, deps, middleware, routes/*, lsp/server)
- Services (container, lifecycle, search, metrics, broker, rate_limit)
- Config + model (config, types, node, errors)
- Tests (unit, integration, acceptance)
- Bundles + architecture holistic view
