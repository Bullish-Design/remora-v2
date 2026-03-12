# Plan

## NO SUBAGENTS - Do all work directly.

1. Define data model semantics for directory nodes.
- Add/confirm `NodeType.directory` and a stable directory node ID scheme.
- Define root node ID semantics for project entrypoint.

2. Extend reconciliation to materialize directory hierarchy.
- During scan/reconcile, build required directory nodes from discovered file paths.
- Upsert directory nodes and link hierarchy via `parent_id` and/or `contains` edges.
- Set each file node's `parent_id` to its containing directory node.

3. Define directory-node awareness contract.
- Ensure parent and child directory/file relationships are queryable from existing stores.
- Add helper/query path(s) for "list children" and "get parent" suitable for agent prompts/tools.

4. Integrate directory nodes with runtime behavior.
- Ensure directory nodes get default subscriptions for subtree-relevant events.
- Validate runner/actor flow can trigger directory nodes safely (no cascade regressions).

5. Add tests first, then implementation.
- Unit tests for ID scheme, hierarchy projection, parent linkage, and reconcile update/removal behavior.
- Integration test covering project root entrypoint node and file-parent linkage.

6. Final validation.
- Run full test suite.
- Confirm graph invariants: exactly one root directory node per project, all file nodes have directory parent, no orphan directory references.

## NO SUBAGENTS - Do all work directly.
