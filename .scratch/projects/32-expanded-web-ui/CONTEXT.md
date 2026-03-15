# Context — Expanded Web UI

## Status: COMPLETE (brainstorming phase)

### WEB_UI_BRAINSTORMING.md

- Analyzed current web UI capabilities: Sigma graph, node inspection, agent panel, proposal review, SSE streaming, cursor following
- Identified the gap: current UI is a monitoring dashboard, not a development workspace
- Designed a "structured browser + agent-mediated editing" paradigm with three-panel layout (file tree, main content, agent panel)
- Three user journeys: exploring existing codebase, creating new codebase from scratch, high-level refactoring
- Core capabilities: file tree, file viewer, symbol outline, command bar, proposal review, project generation
- Agent interaction model: command bar routing, multi-agent coordination, configurable approval flow
- Backend API additions: 16 new endpoints, 6 new SSE event types, CommandTask data model
- Frontend architecture: stay single-file with component-via-functions pattern, upgrade to Vite+Preact/Svelte when >3K lines
- Codebase generation flow: user input → architect agent plans → per-file agents generate → validation → iteration
- 4-phase implementation roadmap: ~2,460 total new lines across all phases
- Alternative approaches analyzed: embedded IDE, notebook, chat-only, kanban, visual programming — all rejected in favor of structured browser approach
