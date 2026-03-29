## NO SUBAGENTS

# PLAN — 64-graph-ui-refactor

## Goal
Refactor the Remora web UI from deterministic scene composition to a graph-native runtime layout with incremental SSE updates and interaction-driven readability.

## Scope
In scope:
- Split monolithic `index.html` graph script into focused ES modules.
- Replace full-graph refresh behavior with diff-based incremental graph updates.
- Introduce force-layout lifecycle (initial run + reheat policy + pinning hooks).
- Preserve current UX contracts (selection, side panel detail, filters, screenshot stability).
- Add validation coverage for incremental updates, focus mode behavior, and layout stability in this repo's web UI test suite.

Out of scope:
- Backend API redesign.
- Mandatory bundler migration.
- Non-graph sidebar redesign beyond compatibility updates.
- Cross-repo demo/check updates (handled later in the external demo repository).

## Phases
1. Baseline guardrails
- Capture screenshot and check outputs.
- Record graph cardinality and baseline behavior.

2. Decomposition without behavior change
- Create module boundaries and compatibility bootstrap.
- Keep existing runtime behavior equivalent.

3. Graph-state diff engine
- Add `nodesById`/`edgesByKey` state model.
- Replace hot-path `graph.clear()` reloads.

4. Graph-native layout runtime
- Add force layout engine lifecycle.
- Seeded initialization and controlled reheats.

5. Interaction-first readability
- Focus mode, semantic filters, search/jump, pin/unpin.

6. Event reconciliation + camera stability
- Batch SSE bursts and patch graph incrementally.
- Preserve camera/selection mental map.

7. Legacy layout retirement
- Remove deterministic V4/V5 code paths.

8. Validation hardening
- Run existing `remora-v2` web UI tests.
- Add incremental/focus/layout-stability checks in `remora-v2` test paths.

9. Rollout and cleanup
- Temporary `layout_mode` switch.
- Dogfood graph mode, flip default, remove legacy path.

## Deliverables
- Project scaffold docs under `.scratch/projects/64-graph-ui-refactor/`.
- Refactor template module tree for `src/remora/web/static/`.
- Explicit verification checklist and rollout gate criteria.

## Acceptance Criteria
- Phased plan aligned with `GRAPH_IMPLEMENTATION_GUIDE.md`.
- Standard project files exist and are initialized.
- Template module files exist for graph-state/layout/renderer/interactions/events/panels/main.
- Scaffold scope is constrained to `remora-v2` web UI refactor work.

## Immediate Next Tasks
1. Wire template modules into production `index.html` bootstrap with no behavior change.
2. Land graph-state diff engine and migrate `node_discovered` hot path.
3. Add force layout vendor and runtime integration behind feature flag.

## NO SUBAGENTS
