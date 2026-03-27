# DECISIONS

1. Scope decision: focus the initial spec on runtime orchestration and event-driven agent behavior.
- Rationale: this is the highest-cohesion domain boundary visible in code (`reconciler`, `event store/dispatcher`, `actor/turn`, `workspace + tool capabilities`).

2. Modeling decision: treat transport/API and persistence schema details as implementation and exclude them.
- Rationale: stakeholders care about behavioral guarantees, not Starlette route wiring or SQLite column definitions.

3. Modeling decision: represent event routing and actor execution as domain rules with guards for cooldown/depth/overflow.
- Rationale: these are explicit behavior constraints, not accidental internals.
