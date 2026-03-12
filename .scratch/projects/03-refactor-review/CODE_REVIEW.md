# Remora-v2 Refactor Review

## Table of Contents
- Overview: what Remora is and how it works
- Refactor-plan completion audit
- Detailed findings (ordered by severity)
- Additional strengths
- Recommendations (focus: reduce developer mental-model overhead)

## Overview
Remora is an event-driven runtime that turns discovered code/content nodes (functions, classes, methods, markdown sections, TOML tables) into autonomous agents.

Core flow:
1. `discover` (tree-sitter + `.scm` queries) extracts `CSTNode`s from files.
2. `project_nodes` materializes them as persisted `CodeNode`s.
3. `FileReconciler` keeps graph state in sync as files are added/changed/deleted.
4. `EventStore` + `SubscriptionRegistry` route events into trigger queues.
5. `AgentRunner` executes node agents with Grail tools and kernel backends.
6. Web/LSP adapters expose graph state and event streams to humans/editors.

## Refactor-Plan Completion Audit

### Overall status
Mostly implemented, but not fully “done” at an architecture-quality bar.

### What is complete
- Multi-language tree-sitter discovery with query overrides (`python`, `markdown`, `toml`).
- New `FileReconciler` with add/change/delete handling and `NodeRemovedEvent` emission.
- Runner external fixes (`event_emit` payload retention, workspace path listing, bundle read fallback).
- Web XSS hardening for source rendering.
- Proposal flow improvement to avoid whole-file truncation from node-slice-only writes.
- Tests are passing (`125 passed`).

### What is incomplete or still problematic
- Critical correctness gaps remain in rewrite/status flow (see findings F1-F3).
- Some planned cleanup intent is still fragmented (duplicate path-resolution/walk logic).
- Discovery identity model still allows silent collisions in realistic edge cases.

## Detailed Findings

### Critical

1. `pending_approval` status is overwritten at end of turns.
- Evidence: [src/remora/core/runner.py:176](/home/andrew/Documents/Projects/remora-v2/src/remora/core/runner.py:176), [src/remora/core/runner.py:351](/home/andrew/Documents/Projects/remora-v2/src/remora/core/runner.py:351)
- `propose_rewrite()` sets node status to `pending_approval`, but `_execute_turn()` unconditionally resets status to `idle` in `finally`.
- Impact: approval state is unreliable; UI/workflow semantics are incorrect.

2. Rewrite construction can patch the wrong region.
- Evidence: [src/remora/core/runner.py:333](/home/andrew/Documents/Projects/remora-v2/src/remora/core/runner.py:333), [src/remora/core/runner.py:334](/home/andrew/Documents/Projects/remora-v2/src/remora/core/runner.py:334)
- Proposal generation uses first textual `replace(old_source, new_source, 1)` across full file.
- Impact: if duplicated code blocks exist, it may rewrite the wrong occurrence.

3. Approval endpoint blindly overwrites file content without concurrency guard.
- Evidence: [src/remora/web/server.py:117](/home/andrew/Documents/Projects/remora-v2/src/remora/web/server.py:117), [src/remora/web/server.py:118](/home/andrew/Documents/Projects/remora-v2/src/remora/web/server.py:118)
- No check that current file content still matches proposal base (`old_source`/hash).
- Impact: stale approvals can clobber newer edits.

### High

4. Discovery IDs can silently collide.
- Evidence: [src/remora/code/discovery.py:220](/home/andrew/Documents/Projects/remora-v2/src/remora/code/discovery.py:220)
- Node IDs are `file_path::full_name`; same-name definitions in one file collapse to one persisted node with no warning.
- Impact: silent graph corruption in edge cases; surprising reconciler behavior.

5. Reconciler loop has no fault isolation.
- Evidence: [src/remora/code/reconciler.py:71](/home/andrew/Documents/Projects/remora-v2/src/remora/code/reconciler.py:71), [src/remora/code/reconciler.py:76](/home/andrew/Documents/Projects/remora-v2/src/remora/code/reconciler.py:76)
- Any unexpected exception in `reconcile_cycle()` kills the background task.
- Impact: runtime can silently stop tracking file changes.

### Medium

6. Web graph is not fully reactive to node lifecycle events.
- Evidence: [src/remora/web/views.py:241](/home/andrew/Documents/Projects/remora-v2/src/remora/web/views.py:241)
- UI handles `NodeDiscoveredEvent` but not `NodeRemovedEvent`/`NodeChangedEvent` for graph updates.
- Impact: stale graph state until full page reload.

7. Proposal lookup is bounded to last 1000 events.
- Evidence: [src/remora/web/server.py:159](/home/andrew/Documents/Projects/remora-v2/src/remora/web/server.py:159)
- Old proposals become undiscoverable in long-lived runtimes.
- Impact: operational flakiness over time.

8. Path resolution/walking logic is duplicated across modules.
- Evidence: [src/remora/__main__.py:177](/home/andrew/Documents/Projects/remora-v2/src/remora/__main__.py:177), [src/remora/code/reconciler.py:188](/home/andrew/Documents/Projects/remora-v2/src/remora/code/reconciler.py:188)
- Similar responsibilities exist in multiple places with slight behavior differences.
- Impact: higher cognitive load and future drift risk.

## Additional Strengths
- Refactor successfully removed AST-only discovery and introduced query-driven multi-language parsing.
- Subscription deduplication and stale-node cleanup were materially improved.
- Security posture improved vs. prior review (notably XSS handling and project-root path checks).
- Test coverage breadth is good for core flows.

## Recommendations (Mental-Model-First)

1. Introduce a formal `RewriteProposal` domain model.
- Store proposal metadata in dedicated persistence (`proposal_id`, `file_path`, `base_hash`, `patch`/`replacement_span`, `created_at`, `status`).
- Stop scraping proposal state from generic event history.

2. Move rewrite semantics to span-based edits.
- Use node `start_byte`/`end_byte` or explicit structured patch objects, not substring replacement.
- Validate preconditions before apply (base hash/content match).

3. Make node status a state machine.
- Allowed transitions only (`idle -> running -> pending_approval -> idle`, etc.).
- Runner should not unconditionally force `idle`; transition based on terminal state.

4. Centralize discovery path/query-path resolution.
- Create one resolver utility used by CLI discovery and reconciler.
- Keep one source of truth for ignore behavior and path normalization.

5. Make discovery identity explicit and collision-safe.
- Prefer stable identity that includes span or explicit per-node UUID derivation with collision checks.
- At minimum, detect collisions and emit warning/error events.

6. Harden background loops.
- Wrap cycle internals with exception handling + retry/backoff + error event emission.
- Add health/status endpoint for reconciler and runner tasks.

7. Standardize event typing.
- Replace raw `event_type: str` protocols for external-emitted events with typed payload schema/registry.
- Reduces stringly-typed coupling across tools, subscriptions, and UI.

8. Expand tests around the highest-risk paths.
- Add tests for:
  - pending-approval status persistence after turn completion,
  - duplicate `old_source` replacement correctness,
  - stale proposal rejection on concurrent edits,
  - reconciler survival after one-cycle exception.
