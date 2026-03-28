# Plan — 63-web-ui-improvement-template

NO SUBAGENTS.

## Goal
Improve the Remora web UI for clarity, usability, and demo quality while preserving core workflows.

## Phases
1. Baseline audit
- Inventory current UI flows, pain points, and technical constraints.
- Capture screenshots/notes for current state.

2. UX spec + visual direction
- Define information hierarchy for nodes, edges, events, chat, proposals.
- Define interaction model for filtering/search/focus/detail panels.
- Define visual system: typography, spacing, color tokens, states.

3. Implementation
- Refactor page structure/components in `index.html`.
- Add/adjust styles and client-side state handling.
- Add graph-centric affordances (edge-type filters, drilldown, quick stats).

4. Validation
- Verify mobile + desktop rendering.
- Verify keyboard + basic accessibility behavior.
- Verify API interactions still function under failure modes.

5. Polish and docs
- Document new UI behavior and shortcuts.
- Add/update tests for any UI/API contract assumptions.

## Acceptance Criteria
- Key workflows are faster to execute (node discovery, edge interpretation, event follow-up).
- Visual hierarchy is significantly clearer at first load.
- No regression in existing API-backed actions.
- UI remains responsive with realistic graph/event volume.

NO SUBAGENTS.
