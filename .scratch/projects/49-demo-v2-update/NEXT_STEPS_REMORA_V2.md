# Next Steps for remora-v2 (Upstream)

Date: 2026-03-24  
Target upstream repository: `/home/andrew/Documents/Projects/remora-v2`

## Scope

This document covers only changes that should be made upstream in `remora-v2` to remove the need for constrained local workarounds in downstream demos.

Goals:
- make default virtual bundles (`review-agent`, `companion`) robust in reactive workflows
- improve observability when tool/type failures occur
- provide offline-safe web UI behavior by default
- improve operator UX for search and LSP dependency states
- add regression tests and docs for these paths

## Workstream 1: Harden Virtual Bundle Runtime Reliability

Primary upstream files:
- `/home/andrew/Documents/Projects/remora-v2/src/remora/defaults/bundles/review-agent/bundle.yaml`
- `/home/andrew/Documents/Projects/remora-v2/src/remora/defaults/bundles/review-agent/tools/*.pym`
- `/home/andrew/Documents/Projects/remora-v2/src/remora/defaults/bundles/companion/bundle.yaml`
- `/home/andrew/Documents/Projects/remora-v2/src/remora/defaults/bundles/companion/tools/*.pym`

Required changes:
1. reproduce and isolate the Grail/type-check failure mode observed in reactive virtual-agent turns.
2. patch incompatible tool scripts and/or prompt contracts so reactive turns complete cleanly.
3. ensure review and companion tools are resilient to missing/partial event payload fields.
4. guard against self-trigger loops and repeated non-productive turns.

Suggested engineering checks:
1. add explicit tool input validation and fallback defaults.
2. ensure tool outputs are simple and schema-consistent.
3. bound expensive operations and message length where needed.

Acceptance criteria:
1. default `review-agent` and `companion` run without repeated type-check/tool errors in a source-change workload.
2. virtual-agent flows do not require downstream "no-tools reactive" fallback to remain stable.

## Workstream 2: Improve Event/Failure Observability

Primary upstream files:
- `/home/andrew/Documents/Projects/remora-v2/src/remora/core/events/types.py`
- `/home/andrew/Documents/Projects/remora-v2/src/remora/web/routes/events.py`
- relevant runner/execution services under `/home/andrew/Documents/Projects/remora-v2/src/remora/core/`

Required changes:
1. emit consistent, queryable event records for:
- tool start/success/failure
- agent turn start/end/error
2. include stable error fields (error class, concise reason, correlation id).
3. ensure `/api/events` payload shape is documented and stable enough for external validation scripts.

Acceptance criteria:
1. downstream scripts can reliably detect meaningful review/companion actions from `/api/events`.
2. failure diagnosis does not require scraping verbose logs only.

## Workstream 3: Offline-Safe Web UI Defaults

Primary upstream files:
- `/home/andrew/Documents/Projects/remora-v2/src/remora/web/` (templates/static packaging and server wiring)

Required changes:
1. remove hard dependency on CDN (`unpkg`) for core graph libraries.
2. ship required frontend assets with the package and serve from `/static`.
3. preserve functionality in network-restricted environments without post-install patching.

Acceptance criteria:
1. opening `/` works without internet access.
2. downstream repos do not need custom scripts to patch runtime `index.html`.

## Workstream 4: Search and LSP Operator UX

Primary upstream files:
- `/home/andrew/Documents/Projects/remora-v2/src/remora/__main__.py`
- `/home/andrew/Documents/Projects/remora-v2/src/remora/web/routes/search.py`
- `/home/andrew/Documents/Projects/remora-v2/src/remora/lsp/__init__.py`
- related docs under `/home/andrew/Documents/Projects/remora-v2/docs/`

Required changes:
1. make missing search/LSP dependencies produce actionable, standardized diagnostics.
2. ensure CLI and API paths clearly distinguish configuration errors vs backend unreachability.
3. document exact setup expectations for:
- `remora[search]` + embeddy
- `remora[lsp]` + pygls

Acceptance criteria:
1. operators can resolve search/LSP setup issues from one error message plus docs.
2. downstream demo docs can reference a stable upstream troubleshooting contract.

## Workstream 5: Upstream Regression Tests

Add or extend upstream tests to cover:
1. virtual review + companion reactive flow under simulated source-change events.
2. tool-failure event emission and payload consistency.
3. web UI asset availability without external CDN.
4. search and LSP missing-dependency diagnostics.

Acceptance criteria:
1. test suite fails if previously observed virtual-agent failure mode regresses.
2. offline web UI dependency regression is caught automatically.

## Workstream 6: Upstream Documentation

Update upstream docs to include:
1. canonical virtual-agent architecture and event semantics.
2. stable event fields intended for external script consumption.
3. offline web UI behavior and packaging expectations.
4. search and LSP setup/diagnostics matrix.

Suggested doc locations:
- `/home/andrew/Documents/Projects/remora-v2/docs/HOW_TO_USE_REMORA.md`
- additional focused pages under `/home/andrew/Documents/Projects/remora-v2/docs/`

## Definition of Done (remora-v2)

1. default virtual bundles are stable in reactive execution without downstream constrained-role workarounds.
2. event stream contains reliable, scriptable evidence of tool and turn outcomes.
3. web UI works offline without CDN access.
4. search/LSP dependency failures are explicit and actionable.
5. regression tests cover these guarantees.
6. docs reflect the guaranteed behavior.

## Suggested Commit Plan (remora-v2)

1. `fix(virtual): harden review-agent/companion reactive tool flows`
2. `feat(events): standardize tool/turn failure event payloads`
3. `feat(web): vendor graph UI assets for offline-safe runtime`
4. `fix(ux): improve search and lsp dependency diagnostics`
5. `test(regression): add reactive virtual-agent and offline-ui coverage`
6. `docs: publish virtual/event/offline/search/lsp operational contracts`

