# Assumptions

- Remora should represent directories as first-class `CodeNode` entries (no new model type), likely via a new `NodeType` value such as `directory`.
- The project/repo entrypoint node should be the root directory node for `project_root`.
- Every file node should have a directory parent (`parent_id`), and directory nodes should chain to parent directories up to root.
- Directory node "awareness" should come from graph data (children + parent) derived from node/edge relationships, not ad-hoc global state.
- Directory nodes should be discoverable/reconcilable incrementally from existing file reconciliation events.
- Existing actor model remains the execution runtime; directory nodes become new actors within that runtime.
