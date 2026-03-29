# Decisions — 64-graph-ui-refactor

## D-001: Keep scaffold isolated from runtime initially
- Decision: create template module skeletons under project scratch space first.
- Rationale: allows review/alignment before touching production `index.html` execution path.
- Inputs: phased migration and low-risk rollout guidance in `GRAPH_IMPLEMENTATION_GUIDE.md`.

## D-002: Mirror target architecture one-to-one in template files
- Decision: scaffold `graph-state.js`, `layout-engine.js`, `renderer.js`, `interactions.js`, `events.js`, `panels.js`, `main.js`.
- Rationale: reduces translation overhead when moving into production source.
- Inputs: section 3.1 target architecture.

## D-003: Exclude demo-repo scaffolding from this project
- Decision: remove scaffold placeholders for demo repository checks and keep this project focused on `remora-v2` web UI code changes.
- Rationale: user requested that cross-repo demo files be ignored for now.
- Inputs: direct user clarification after initial scaffold.
