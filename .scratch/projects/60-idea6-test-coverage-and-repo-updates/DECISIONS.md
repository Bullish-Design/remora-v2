# Decisions — 60-idea6-test-coverage-and-repo-updates

## 2026-03-27 — Create dedicated project for coverage + repo update planning
- Decision: create `.scratch/projects/60-idea6-test-coverage-and-repo-updates`.
- Rationale: isolate Idea #6 reliability planning artifacts from implementation docs in project 58.

## 2026-03-27 — Treat ongoing semantic-edge backfill as P0
- Decision: classify target-only change backfill (`importer` unchanged, `target` changed) as required library work for demo reliability.
- Rationale: without this, semantic hotspots can remain incomplete after incremental updates, weakening technical credibility.

## 2026-03-27 — Make tests drive this reliability work
- Decision: define explicit P0 tests first (reconcile, watch path, lifecycle API semantic edge assertions) before implementation updates.
- Rationale: converts reliability claims into enforceable behavior and prevents regression.
