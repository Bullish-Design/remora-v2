# Alignment Refactor Investigation

## Table of Contents

1. Alignment Target (Current Remora v2 Goal)
2. Investigation Scope and Method
3. Executive Findings
4. Detailed Clutter Inventory
5. Recommended Alignment Refactor Plan
6. Test and Verification Impact
7. Risks and Decision Points
8. Alignment Completion Criteria

## 1. Alignment Target (Current Remora v2 Goal)

Remora v2 is currently positioned as an event-driven runtime where discovered code nodes operate as autonomous agents with a unified naming model and runtime contract.

Primary goal references:
- `README.md:3-11`
- `.scratch/projects/14-code-review-and-demo/CODE_REVIEW.md:38-40`

Alignment target for this refactor:
- One canonical vocabulary and API surface (`Node`, `Actor`, `ActorPool`, `TurnContext`, `role`, `bundle_overlays`, `workspace_root`).
- No runtime compatibility shims for old names/keys/schemas.
- Runtime code optimized for current behavior, not for legacy payloads.
- Repository contents limited to source-of-truth assets (no generated artifacts or stale temporary outputs).

## 2. Investigation Scope and Method

Scope reviewed:
- Runtime source: `src/remora/**`
- Bundles/tools: `bundles/**`
- Config artifacts: `remora.yaml`, `remora.yaml.example`
- Unit/integration tests for compatibility behavior and API coupling
- Repository-level generated artifact footprint (`.grail/**`)

Method:
1. Identify all legacy-name aliases, migration code paths, and backward-compatibility accessors.
2. Identify stale naming and docs/config drift that conflict with the current model.
3. Identify generated or transient artifacts checked into git.
4. Identify internal boundary leaks that preserve old/test-only behavior instead of clean module contracts.

Key evidence commands used:
- `rg` searches for `alias`, `legacy`, `bundle_name`, `swarm_root`, `bundle_mapping`, old type names.
- Line-level inspection via `nl -ba` for cited files.
- `git ls-files .grail` for repository clutter inventory.

## 3. Executive Findings

1. Backward-compatibility shims are still present across core runtime models, config, and public exports, even though the current architecture has already standardized new names.
2. Legacy migration logic is still embedded in hot-path runtime code (model validators, runtime schema migration helpers, startup subscription upgrade behavior).
3. Config and naming drift exists in user-facing artifacts (`remora.yaml.example`, docstrings, UI text), reinforcing old concepts.
4. The repository includes substantial generated Grail artifacts (`115` tracked files), including random temporary output (`.grail/tmp98yh9rr7/*`).
5. A few internals are exposed primarily for test coupling (`EventStore.connection`, `EventStore.lock`), which broadens public surface area without direct product value.

Conclusion: The codebase is operationally strong, but not yet fully aligned with a strict "no shims / no legacy clutter" policy.

## 4. Detailed Clutter Inventory

| ID | Category | Evidence | Misalignment | Recommended Action |
|---|---|---|---|---|
| C-01 | Public API shim | `src/remora/core/node.py:138-142` (`CodeElement`, `CodeNode` aliases in `__all__`) | Keeps old type names alive in public API | Remove aliases and export only `DiscoveredElement`, `Agent`, `Node` |
| C-02 | Model shim | `src/remora/core/node.py:42-49`, `85-92` (`_migrate_bundle_name`) | Runtime accepts old field name (`bundle_name`) | Remove migration validators; accept `role` only |
| C-03 | Model shim | `src/remora/core/node.py:61-62`, `134-135` (`bundle_name` property) | Old naming retained for convenience | Remove `bundle_name` properties |
| C-04 | Public API shim | `src/remora/core/actor.py:451-454` (`AgentActor = Actor`) | Old class name preserved | Remove alias and old export |
| C-05 | Public API shim | `src/remora/core/runner.py:115-118` (`AgentRunner = ActorPool`) | Old runner naming retained | Remove alias and old export |
| C-06 | Public API shim | `src/remora/core/externals.py:274-276` (`to_externals_dict`) | Old externals terminology still supported | Remove alias method; keep `to_capabilities_dict` |
| C-07 | Public API shim | `src/remora/core/externals.py:308-311` (`AgentContext = TurnContext`) | Old context type name retained | Remove alias and old export |
| C-08 | Config shim | `src/remora/core/config.py:101-109` (`bundle_mapping` / `swarm_root` migration) | Accepts old config keys indefinitely | Remove migration block; require modern keys only |
| C-09 | Config shim | `src/remora/core/config.py:112-119` (`bundle_mapping`, `swarm_root` properties) | Legacy key names exposed at runtime | Remove both compatibility properties |
| C-10 | Config drift | `remora.yaml.example:12`, `22` uses `bundle_mapping`, `swarm_root` | Example config teaches deprecated names | Replace with `bundle_overlays` and `workspace_root` |
| C-11 | Persistence migration clutter | `src/remora/core/graph.py:205-213`, `289-293` role-column migration helpers | Legacy schema migration runs in core code path | Move to one-time migration utility, remove runtime migration code |
| C-12 | Startup compatibility behavior | `src/remora/code/reconciler.py:51-56`, `262-267`, `280`; plus migration test `tests/unit/test_reconciler.py:284-327` | First-run bootstrapping exists partly to upgrade old subscription shapes | Drop legacy upgrade path; use single subscription contract |
| C-13 | Compatibility alias method | `src/remora/core/events/store.py:67-69` (`initialize`) | Duplicate lifecycle API retained for old callers | Remove alias, keep `create_tables` |
| C-14 | Compatibility alias method | `src/remora/core/events/subscriptions.py:73-75` (`initialize`) | Duplicate lifecycle API retained for old callers | Remove alias, keep `create_tables` |
| C-15 | Stale naming | `src/remora/code/projections.py:1`, `23` references `CodeNodes` | Old terminology remains in docs/comments | Rename docstrings to `Node` terminology |
| C-16 | Test suite enforces legacy behavior | `tests/unit/test_config.py:23-25`, `tests/unit/test_refactor_naming.py:29-34` | Tests currently require legacy key support | Replace with strict-modern-key tests |
| C-17 | Internal boundary leak | `src/remora/core/events/store.py:38-43` + test usage (`tests/unit/test_reconciler.py:69`, `159`, `289`) | Exposes DB internals primarily for tests | Remove properties; test through public APIs or dedicated test helpers |
| C-18 | Abstraction bypass | `src/remora/web/server.py:55-58` (`node_store.db.fetch_all`) | Web layer bypasses store contract | Add `NodeStore.list_all_edges()` and use it |
| C-19 | Optional-surface mismatch | `src/remora/lsp/__init__.py:3` unconditional import of `pygls` path | Optional dependency surface is eagerly imported | Lazy import or guarded import with clear error |
| C-20 | UI claim drift | `src/remora/web/static/index.html:90` says "companion panel" | UI copy overstates implemented feature set | Rename copy until companion features exist |
| C-21 | Generated artifact clutter | `git ls-files .grail` -> `115` tracked files | Repository contains generated compiler/cache outputs | Remove tracked `.grail` artifacts; add `.grail/` ignore policy |
| C-22 | Suspicious transient artifact | `.grail/tmp98yh9rr7/*` tracked | Random temp namespace should never be source-of-truth | Remove from git history moving forward (at minimum, delete current tracked files) |
| C-23 | Over-broad re-export surface | `src/remora/core/events/__init__.py:3-7` star imports from all event modules | Expands implicit API and obscures intended stable surface | Replace with explicit symbol exports |
| C-24 | Runtime defect that compounds clutter | `bundles/code-agent/tools/rewrite_self.pym:7,10` uses missing `propose_rewrite` | Broken tool contracts undermine "clean current API" alignment | Switch to `apply_rewrite` and add runtime test |

### Findings Specifically About Shims/Aliases (User Priority)

Highest-priority removals matching the "no leftover compatibility clutter" requirement:
- C-01 through C-09
- C-13 through C-14
- C-16

## 5. Recommended Alignment Refactor Plan

### Phase A: Remove Public Compatibility API (No Runtime Behavior Change)

Targets:
- C-01, C-04, C-05, C-06, C-07, C-13, C-14, C-23

Actions:
1. Remove alias symbols and alias methods from `node.py`, `actor.py`, `runner.py`, `externals.py`, `events/store.py`, `events/subscriptions.py`.
2. Tighten `__all__` to canonical names only.
3. Replace star re-exports in `core/events/__init__.py` with explicit exports.

Expected output:
- Cleaner public API surface with one canonical naming scheme.

### Phase B: Remove Legacy Field/Config Migration Paths

Targets:
- C-02, C-03, C-08, C-09, C-10, C-16

Actions:
1. Remove `bundle_name` migration logic and accessors from runtime models.
2. Remove config migration for `bundle_mapping`/`swarm_root` and remove compatibility properties.
3. Update `remora.yaml.example` to modern keys only.
4. Replace tests that assert legacy support with strict modern-contract tests.

Expected output:
- Config and model parsing fail fast on obsolete keys.

### Phase C: Remove Legacy Runtime Upgrade Behavior and Test Coupling

Targets:
- C-11, C-12, C-17, C-18

Actions:
1. Move schema upgrades out of core runtime path into explicit migration tooling or one-time command.
2. Remove reconciler startup compatibility bootstrapping for old subscription shapes.
3. Remove `EventStore.connection` and `EventStore.lock` escape hatches.
4. Add explicit store methods for web needs (`list_all_edges`) and remove direct DB access from web server.

Expected output:
- Fewer hidden side paths and tighter module boundaries.

### Phase D: Repository Hygiene and Messaging Alignment

Targets:
- C-15, C-19, C-20, C-21, C-22, C-24

Actions:
1. Update stale naming in docstrings/comments/UI copy.
2. Fix optional LSP import behavior.
3. Remove tracked `.grail` artifacts and add ignore rules.
4. Fix broken `rewrite_self` tool contract and verify with tests.

Expected output:
- Source tree reflects current implementation state with no generated or misleading residue.

## 6. Test and Verification Impact

Tests expected to change or be removed:
- `tests/unit/test_config.py:23-25` (legacy bundle mapping alias behavior)
- `tests/unit/test_refactor_naming.py:29-34` (legacy `swarm_root` alias behavior)
- `tests/unit/test_graph.py:134-135` (asserting access to `EventStore.connection/lock`)
- `tests/unit/test_reconciler.py:69`, `159-161`, `289-322` (direct SQL access via `event_store.connection` and legacy subscription upgrade path)

Tests to add/update for strict alignment:
1. Config rejects unknown legacy keys (`bundle_mapping`, `swarm_root`).
2. Runtime models reject `bundle_name` input unless explicit migration tool used before runtime startup.
3. Public import checks ensure only canonical symbols are exported.
4. Web API edge retrieval uses store abstraction only.
5. `rewrite_self` tool executes against `TurnContext` capabilities using `apply_rewrite`.

Verification gates:
- Unit suite passes after removing legacy compatibility support.
- Integration suite passes without any alias-dependent code paths.
- No tracked `.grail` generated outputs remain.

## 7. Risks and Decision Points

1. Database migration policy decision:
- If runtime migration helpers are removed (C-11), old on-disk databases must be migrated before startup.
- Decision needed: ship one-time migration command vs. require DB reset.

2. Public API break policy decision:
- Removing aliases is a hard break for any downstream code importing old names.
- Decision needed: immediate removal in current minor/patch cycle vs. explicit major bump.

3. Test philosophy decision:
- Current tests intentionally preserve legacy behavior in places.
- Decision needed: convert all compatibility tests to strict-contract tests in same PR series.

4. LSP optionality decision:
- Current import path may fail if optional deps are missing.
- Decision needed: lazy import with explicit error messaging vs. make LSP deps hard dependencies.

## 8. Alignment Completion Criteria

Alignment work is complete when all conditions are true:
- No compatibility aliases remain in runtime API exports.
- No runtime config/model validators accept deprecated key names.
- Legacy upgrade logic is removed from steady-state runtime paths.
- `remora.yaml.example` and UI text reflect current features and naming.
- Repository contains no generated `.grail` artifacts.
- Test suite enforces current contracts only (no alias/back-compat expectations).
