# Context — 64-graph-ui-refactor

User requested: study `GRAPH_IMPLEMENTATION_GUIDE.md` and scaffold a project template directory to prepare a full web UI graph refactor.

Current status:
- Guide reviewed in full.
- Project scaffolding created with standard tracking files.
- Template directory created with module placeholders for:
  - graph state
  - layout engine
  - renderer
  - interactions
  - event routing
  - panels
  - bootstrap entrypoint
- Scope updated to this repo only (`src/remora/web/static/*` and local test paths); demo-repo check scaffolds removed.

Next step:
- Begin Phase 1 implementation by creating a non-breaking module bootstrap in production static assets and validating `remora-v2` web UI tests.
