# Assumptions — 58-remora-v2-wow-demo-template

## Project Audience
- Primary: technical audience (staff/principal engineers, AI tooling engineers, developer platform teams).
- Secondary: potential adopters evaluating remora-v2 for code intelligence and autonomous workflows.

## Demo Goals
1. Show remora-v2 as more than "chat over code": event-native, graph-aware, and agentic.
2. Deliver visible, measurable outcomes during a short live session (8-15 minutes).
3. Maximize "wow" while preserving reliability and repeatability.

## Constraints
1. Demo concepts should map to current remora-v2 architecture (EventStore, AgentNode, projections, tool layer).
2. Concepts should prefer deterministic setup with minimal external dependencies.
3. Presentation should include observability (events, proposals, decisions), not only final output.

## Key Invariants
- EventStore remains the source of truth for state transitions.
- AgentNode remains data-driven via extensions, not subclass specialization.
- Demo value comes from real orchestration behavior, not hardcoded script theater.
