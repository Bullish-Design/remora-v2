# Proposal Accept Event-Order Fix Guide

## 1. Problem Summary
Current accept flow emits `content_changed` before `rewrite_accepted`.

Impact in real demos:
- Accept scripts that require proof of `rewrite_accepted` followed by `content_changed` fail intermittently.
- `content_changed` triggers immediate reconciler activity and additional events before acceptance proof is observed.
- Global `/api/events?limit=N` polling is noisy and can miss earlier events.

## 2. Root Cause (Code-Level)
File: `src/remora/web/routes/proposals.py`
- `ContentChangedEvent` is appended per changed file inside the materialization loop.
- `RewriteAcceptedEvent` is appended only after the loop.

This guarantees current order is opposite of desired contract.

## 3. Target Behavior
For accept flow:
1. Materialize file bytes to disk.
2. Transition node status to idle.
3. Append `rewrite_accepted`.
4. Append `content_changed` events for modified files.

Required outcomes:
- Accept response still returns materialized files.
- Reject flow behavior unchanged.
- Demo can deterministically prove event order.

## 4. Implementation Steps

### Step 1: Refactor accept handler emission order
File: `src/remora/web/routes/proposals.py`

Change logic:
- During loop: write bytes to disk and collect pending content-change payloads (path, hashes, change type) in memory.
- After loop:
  - `await deps.node_store.transition_status(node_id, NodeStatus.IDLE)`
  - `await deps.event_store.append(RewriteAcceptedEvent(...))`
  - Iterate collected payloads and append `ContentChangedEvent(...)`.

Notes:
- Keep disk writes before acceptance event so acceptance never precedes mutation.
- Maintain same response body shape.

### Step 2: Strengthen tests for event ordering
Primary file: `tests/unit/test_web_server.py`

Add/adjust test for accept route:
- Assert materialized file content changed.
- Fetch recent events and locate both `rewrite_accepted` and `content_changed` for same node.
- Assert event id ordering: `rewrite_accepted.id < content_changed.id`.

If event ids are not exposed in route-level payloads, query through `event_store.get_events(...)` rows and compare persisted ids.

### Step 3: Add real-world acceptance proof test path
File: `tests/acceptance/test_live_runtime_real_llm.py`

For proposal-flow test:
- Capture a baseline latest event id before calling `/accept`.
- After accept, poll `/api/events` and filter by:
  - matching `correlation_id` where available, or
  - matching `agent_id == node_id` plus event id > baseline.
- Assert ordered observation:
  - `rewrite_accepted` exists,
  - subsequent `content_changed` exists for materialized path.

This avoids failures due to unrelated background events.

### Step 4: Reject flow guard
Keep existing reject test and ensure it still passes unchanged.

## 5. Verification Matrix

## Unit
- `devenv shell -- pytest tests/unit/test_web_server.py -k "proposal_accept or proposal_reject or proposal_diff" -q`

## Acceptance (real-world)
- `devenv shell -- pytest tests/acceptance/test_live_runtime_real_llm.py -k "proposal_flow" -q -rs`

## Manual API Proof (demo runtime)
1. Trigger proposal for a controlled node/file.
2. `GET /api/proposals/{node_id}/diff` and assert non-empty `diffs`.
3. `POST /api/proposals/{node_id}/accept`.
4. Assert disk file mutation.
5. `GET /api/events?limit=...` and validate ordered evidence (`rewrite_accepted` before `content_changed`) using scoped filtering.
6. Run reject script and confirm unchanged behavior.

## 6. Risk Notes
- If downstream consumers already rely on old ordering, this is behaviorally breaking for them; communicate in changelog.
- Multi-file proposals emit one acceptance event plus multiple content-change events; tests should assert at least one matching file path, not exactly one event.

## 7. Definition of Done
- Code updated and lint-clean.
- Unit + acceptance target tests pass.
- Manual demo proof succeeds with stable ordering evidence.
- Reject flow remains green.
