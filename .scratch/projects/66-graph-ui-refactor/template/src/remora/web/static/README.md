# Graph UI Refactor Template Modules

This directory is a scaffold for splitting the monolithic web graph script into focused ES modules.

Planned module responsibilities:
- `graph-state.js`: canonical node/edge state + diff apply semantics.
- `layout-engine.js`: force-layout lifecycle (init/reheat/pin/dispose).
- `renderer.js`: Sigma setup, reducers, draw pass hooks.
- `interactions.js`: selection, hover, filters, search, camera controls.
- `events.js`: SSE queue and event-to-state reconciliation.
- `panels.js`: sidebar panel rendering and view updates.
- `main.js`: bootstrap wiring and lifecycle ownership.

This scaffold is not wired into runtime yet.
