# Plan

## Project Goal

Review and redesign the configuration system for remora-v2 to create a unified, elegant, single-source-of-truth architecture.

---

## Phase 1: Cleanup [LOW RISK]

- [ ] Remove unused `project_path` field from Config
- [ ] Create `remora/core/defaults.py` for hardcoded values
- [ ] Add web server config (`host`, `port`, `enabled`) to Config
- [ ] Remove hardcoded fallback system prompt in runner.py
- [ ] Add validators for URLs and paths

## Phase 2: Consolidation [MEDIUM RISK]

- [ ] Design new unified config schema
- [ ] Move bundle.yaml contents into remora.yaml
- [ ] Implement per-node-type configuration overrides
- [ ] Remove `bundle_root` and `bundle_mapping` (replaced by node_types)
- [ ] Update projections.py and runner.py to use new config
- [ ] Update tests

## Phase 3: Refinement [HIGHER RISK]

- [ ] Implement PathResolver class
- [ ] Add configuration validation CLI command
- [ ] Document configuration hierarchy and precedence
- [ ] Add configuration change events (optional)

---

## Key Decisions

1. **Bundle files eliminated** — All agent behavior config in `remora.yaml`
2. **Per-node-type overrides** — Different node types can have different models/turns/tools
3. **CLI overrides config** — CLI args take precedence over YAML
4. **Single defaults source** — All defaults in one place

---

## IMPORTANT

**NO SUBAGENTS.** Do all work directly — read files, search, write, edit, run commands. No delegation.

**ALWAYS CONTINUE.** Do not stop after compaction. Resume from CONTEXT.md and PROGRESS.md immediately.
