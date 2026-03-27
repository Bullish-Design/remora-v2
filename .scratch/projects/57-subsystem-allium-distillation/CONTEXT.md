# CONTEXT

Task: create one Allium distillation per Remora v2 subsystem requested by user.

Planned output location: `specs/subsystems/`.

Subsystem list:
1. discovery-reconciliation
2. node-graph-storage
3. eventing
4. subscriptions-dispatch
5. agent-runtime
6. workspace-bundles
7. tool-capability-layer
8. runtime-orchestration
9. web-interface
10. lsp-interface
11. cli-config-defaults
12. semantic-search

Status:
- All 12 specs created under `specs/subsystems/`.
- Index file created: `specs/subsystems/README.md`.
- Quick consistency checks completed:
  - all files begin with `-- allium: 3`
  - no accidental malformed quote artifacts
  - fixed missing `created_at` field for temporal trigger usage in tool capability spec
