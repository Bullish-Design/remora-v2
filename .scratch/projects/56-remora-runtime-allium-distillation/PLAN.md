# PLAN

## Goal
Distill an initial Allium specification for Remora v2 runtime behavior from current implementation.

## Scope
- Included: runtime core (node projection, event store/dispatch, actor lifecycle, subscriptions, human-input/rewrite pauses, startup/shutdown lifecycle).
- Excluded: transport/API specifics, database DDL, tree-sitter parsing internals, search backend implementation details.

## Steps
1. Capture assumptions and distillation boundary.
2. Extract entities, enums, and config-level constraints from core modules.
3. Extract rule-level transitions from reconciler, dispatcher, actor, and tool capability flows.
4. Draft `.allium` spec with explicit include/exclude scope notes.
5. Self-review for terminology consistency and missing critical transitions.

## Acceptance
- A saved `.allium` file exists with `-- allium: 3` as line 1.
- The file contains entities, rules, and invariants for the included runtime scope.
- Scratch tracking files are updated with current progress and decisions.

## Reminder
NO SUBAGENTS (Task tool) for this repository process unless explicitly directed by the user.
