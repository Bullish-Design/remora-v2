# Assumptions for Developer Onboarding Guide

## Project Audience
- New developers joining the remora-v2 project
- Existing developers needing to refresh their understanding
- Contributors planning to make changes to the codebase
- Architects evaluating the system for extension

## User Scenarios
1. A new developer clones the repository and needs to understand how to run and explore the codebase
2. A developer wants to add a new language plugin for tree-sitter discovery
3. A developer needs to debug why agents aren't being triggered on file changes
4. A developer wants to understand how to extend the web interface with new API endpoints
5. A developer needs to modify the agent execution model or add new event types

## Constraints
- Must accurately reflect the current state of the remora-v2 codebase
- Should focus on core concepts and architecture rather than edge cases
- Examples should be drawn from the actual codebase
- Guidance should be practical and actionable for immediate code exploration
- Must avoid speculation about future features or hypothetical designs

## Invariants
- The core purpose remains: a reactive agent substrate where code nodes can be represented and executed as autonomous agents
- The event-driven architecture is fundamental to the system's design
- Tree-sitter based multi-language discovery is a key capability
- The system maintains persistent state through SQLite storage
- Agents execute in isolated workspaces using the Cairn filesystem abstraction