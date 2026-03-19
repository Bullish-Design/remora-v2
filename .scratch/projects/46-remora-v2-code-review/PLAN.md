# Remora-v2 Code Review Plan

## Objective
Conduct a ruthless, thorough code review of the remora-v2 library. The codebase was written by a new intern, and we need to ensure it meets our high standards.

## Approach
1. **NO SUBAGENTS** - Review all code directly
2. Read and analyze each major module systematically
3. Document issues with line references
4. Create actionable recommendations

## Review Scope
- Core model types and configuration
- Event system (types, bus, store, dispatcher, subscriptions)
- Agent system (actor, runner, turn execution, kernel, prompt)
- Code discovery and reconciliation (watcher, reconciler, discovery)
- Web layer (server, routes, deps)
- Storage layer (graph, workspace, db, transactions)
- Services (lifecycle, broker, rate_limit, search, metrics)
- Tools and capabilities
- LSP integration
- CLI entry point

## Output
1. `CODE_REVIEW.md` - Detailed review with numbered issues
2. `RECOMMENDATIONS.md` - Actionable improvements for moving forward

## Critical Rules Applied
- All work done directly, no delegation
- Document findings as we go
- Be ruthless but constructive
- Focus on architecture, patterns, type safety, error handling, and maintainability
