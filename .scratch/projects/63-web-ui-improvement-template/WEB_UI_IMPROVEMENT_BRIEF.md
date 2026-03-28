# Web UI Improvement Brief

## Primary UX Outcomes
1. Faster graph understanding after startup.
2. Clear separation of graph state, event stream, and action panel.
3. Reduced cognitive load when switching between nodes and proposals.

## Candidate Workstreams
1. Layout modernization
- Rework panel structure for graph, details, timeline, and actions.

2. Interaction improvements
- Edge-type toggles (`contains`, `imports`, `inherits`), node-type filters, search/focus.

3. Visual system
- Introduce CSS variables for color/spacing/typography.
- Improve contrast, spacing rhythm, and focus states.

4. Resilience/feedback
- Improve loading, empty, and error states for API-backed sections.
- Add explicit refresh and reconnect signals.

## Non-goals (initial pass)
1. Backend architecture rewrite.
2. New authentication system.
3. Full design system extraction.
