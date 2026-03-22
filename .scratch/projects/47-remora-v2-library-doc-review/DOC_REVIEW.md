# Remora-v2 Documentation Review

## Scope
- Reviewed docs: `README.md`, `docs/user-guide.md`, `docs/architecture.md`, `docs/externals-api.md`, `docs/externals-contract.md`.
- Also checked `remora.yaml.example` because docs direct users to it as canonical configuration shape.
- Cross-checked against current implementation under `src/remora/**`.

## Library Understanding (What It Is / Does / How)

### What it is
Remora is an event-driven runtime that maps discovered code/content structure into node agents stored in SQLite and executed as actor turns.

### What it does
1. Discovers nodes from source files using tree-sitter queries.
2. Persists nodes/edges/events/subscriptions in SQLite.
3. Routes events via subscription matching to per-node actors.
4. Executes model + tool turns inside per-agent workspaces.
5. Exposes runtime state through web APIs/SSE and optional LSP.

### How it does it
- Boot: CLI (`remora start`) builds `RemoraLifecycle` and `RuntimeServices`.
- Projection: `FileReconciler` continuously syncs file changes into node graph state.
- Execution: `ActorPool` lazily creates actors; actors enforce cooldown/depth and run `AgentTurnExecutor`.
- Tools: Grail `.pym` scripts are loaded from workspace `_bundle/tools` with externals from `TurnContext` capability groups.
- Observability: events are persisted first, then emitted on bus/dispatcher; web/LSP consume from stores and streams.

## Findings (Prioritized)

### High

1. Wrong config keys documented (`query_paths`, `bundle_root`) but runtime expects `query_search_paths`, `bundle_search_paths`.
- Docs: `README.md:17`, `docs/user-guide.md:88`, `docs/user-guide.md:92`, `docs/user-guide.md:142`, `docs/architecture.md:229`.
- Code: `src/remora/core/model/config.py:178-179`, `src/remora/core/model/config.py:199`, `remora.yaml.example:9-14`.
- Impact: users set keys that are ignored for query/bundle path resolution.
- Recommended fix: replace all mentions/examples of `query_paths` -> `query_search_paths` and `bundle_root` -> `bundle_search_paths`.

2. Event type examples use class-style names (`NodeChangedEvent`) but runtime matches snake_case event type strings (e.g. `node_changed`).
- Docs: `docs/user-guide.md:220`, `docs/externals-api.md:283`.
- Example config: `remora.yaml.example:27-30`, `remora.yaml.example:46`.
- Code: `src/remora/core/model/types.py:42-63`, `src/remora/core/events/subscriptions.py:28`.
- Impact: copied subscription examples will not match events, so virtual/tool subscriptions silently fail.
- Recommended fix: use event strings such as `node_changed`, `node_discovered`, `turn_digested` in all examples.

3. Externals compatibility contract is incorrect.
- Docs claim: if bundle `externals_version` is too high, core logs warning and continues (`docs/externals-contract.md:14`).
- Code behavior: runtime raises `IncompatibleBundleError` and fails the turn (`src/remora/core/agents/turn.py:220-227`, error path `:182-189`).
- Impact: operators expect degraded behavior but get failing agents.
- Recommended fix: update contract to reflect hard-fail behavior and show recovery path.

4. Architecture document has stale module/file paths and wrong schema field names.
- Stale paths: `docs/architecture.md:50`, `:64`, `:72`, `:73`, `:77-79`, `:88`.
- Wrong node column: `source_code` at `docs/architecture.md:99`; actual column is `text` (`src/remora/core/storage/graph.py:71`).
- Actual paths: e.g. `RuntimeServices` in `src/remora/core/services/container.py`, `NodeStore` in `src/remora/core/storage/graph.py`, db factory in `src/remora/core/storage/db.py`.
- Impact: contributor navigation and DB inspection guidance are unreliable.
- Recommended fix: refresh all module references and regenerate schema section directly from `create_tables()` definitions.

5. Environment-variable guidance is misleading for nested fields.
- Docs example: `REMORA_MODEL_BASE_URL`, `REMORA_MODEL_DEFAULT` (`docs/user-guide.md:122-127`).
- Config model is nested (`infra`, `behavior`) with only `env_prefix` configured (`src/remora/core/model/config.py:255`, nested fields `:257-262`).
- Runtime validation check (performed in this review): setting those env vars did not change `infra.model_base_url` or `behavior.model_default`.
- Impact: users think they switched model endpoint/default model but runtime still uses defaults.
- Recommended fix: document supported env override strategy accurately (YAML `${VAR:-default}` expansion, or explicitly documented nested env mechanism if added).

### Medium

6. README node-type description is outdated.
- Docs: "functions, classes, methods, files" (`README.md:3-4`).
- Code node types: `function`, `class`, `method`, `section`, `table`, `directory`, `virtual` (`src/remora/core/model/types.py:21-27`).
- Impact: inaccurate mental model for users and plugin authors.
- Recommended fix: update wording to match current node taxonomy.

7. README testing section is internally inconsistent.
- Docs: says run via `devenv shell -- ...` (`README.md:21`), but command examples omit it (`README.md:24-30`).
- Impact: execution friction and avoidable onboarding confusion.
- Recommended fix: either prepend `devenv shell --` in examples or adjust header text.

8. Architecture doc says reconciler emits `ContentChangedEvent`, but current reconciler subscribes to it.
- Docs: `docs/architecture.md:58-59`.
- Code: reconciler subscribes (`src/remora/code/reconciler.py:172`); emitters include LSP/proposal accept paths (`src/remora/lsp/server.py:156,165`, `src/remora/web/routes/proposals.py:138`).
- Impact: incorrect event ownership model for maintainers.
- Recommended fix: move `ContentChangedEvent` emission ownership to LSP/web/tooling sections.

9. Externals API signatures are incomplete for event tags.
- Docs omit tags args in API examples/signatures (`docs/externals-api.md:262`, `:275`).
- Code includes `tags` on `event_emit` and `event_subscribe` (`src/remora/core/tools/capabilities.py:198-203`, `:212-218`).
- Impact: users miss a useful filtering/routing feature.
- Recommended fix: update signatures and add tag-based usage examples.

10. `remora.yaml.example` includes `bundle_overlays.file`, but there is no `file` node type.
- Example: `remora.yaml.example:19`.
- Runtime types: no `file` enum (`src/remora/core/model/types.py:21-27`).
- Impact: confusing/no-op overlay configuration.
- Recommended fix: remove `file` overlay entry or document how file-level nodes would be introduced.

### Low

11. README "key capabilities" omits current CLI subcommands (`index`, standalone `lsp`).
- Docs list only `start` and `discover` (`README.md:11`).
- Code has `index` and `lsp` commands (`src/remora/__main__.py:115`, `:136`).
- Impact: discoverability gap.
- Recommended fix: include all stable commands or link to `remora --help` output.

## Suggested Remediation Order
1. Fix configuration key names + event-type string examples.
2. Correct externals compatibility rule and architecture stale paths/schema.
3. Correct environment-variable guidance.
4. Clean up medium/low consistency issues.

## Overall Assessment
- Documentation quality: **mixed**.
- Strengths: high-level intent and subsystem decomposition remain understandable.
- Main risk: several examples are stale enough to cause immediate misconfiguration or non-functional subscriptions.
